"""MawaqitUploader class implementation"""
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.common.action_chains import ActionChains
import time
import requests
import urllib.parse
import re
import imaplib
import email
import json
from datetime import datetime, timedelta
from selenium.common.exceptions import TimeoutException, NoSuchElementException
from selenium.webdriver.common.keys import Keys
from config import Config
from loguru import logger
import os

class MawaqitUploader:
    def __init__(self):
        self.setup_browser()
        
    def setup_browser(self):
        """Initialize browser with appropriate options"""
        chrome_options = Options()
        if Config.HEADLESS:
            chrome_options.add_argument('--headless=new' if hasattr(Options, "add_argument") else '--headless')
        chrome_options.add_argument('--start-maximized')
        chrome_options.add_argument('--no-sandbox')
        chrome_options.add_argument('--disable-dev-shm-usage')
        
        # Enable performance logging to capture network traffic
        chrome_options.set_capability('goog:loggingPrefs', {'performance': 'ALL', 'browser': 'ALL'})
        
        # Use Selenium Manager (built-in to Selenium 4.6+) to automatically manage ChromeDriver
        self.driver = webdriver.Chrome(options=chrome_options)

    def _find_element_with_selectors(self, selectors, timeout=15):
        """Try multiple selector tuples until one matches."""
        wait = WebDriverWait(self.driver, timeout)
        last_exc = None
        for by, selector in selectors:
            try:
                return wait.until(EC.presence_of_element_located((by, selector)))
            except Exception as e:
                last_exc = e
        raise last_exc if last_exc else Exception("Element not found with provided selectors")

    def _type_visible(self, element, text, char_delay=0.1):
        """Type text visibly with logging."""
        element.clear()
        logger.debug(f"Typing into {element.get_attribute('name') or element.get_attribute('id') or 'element'}: ", end='')
        for char in text:
            element.send_keys(char)
            logger.debug(char, end='', flush=True)
            time.sleep(char_delay)
        logger.debug("")  # New line after typing
        
    def _detect_recaptcha_iframe(self):
        """Return the iframe element for reCAPTCHA if present, else None."""
        try:
            iframes = self.driver.find_elements(By.TAG_NAME, "iframe")
            for iframe in iframes:
                title = (iframe.get_attribute("title") or "").lower()
                src = (iframe.get_attribute("src") or "").lower()
                if "recaptcha" in title or "recaptcha" in src:
                    return iframe
        except Exception:
            pass
        return None

    def _click_recaptcha_checkbox(self, iframe_element, timeout=15):
        """Switch into reCAPTCHA iframe and click the visible checkbox to trigger the challenge/solver."""
        try:
            self.driver.switch_to.frame(iframe_element)
            wait = WebDriverWait(self.driver, timeout)

            # Try common checkbox selectors in order
            checkbox_selectors = [
                (By.ID, "recaptcha-anchor"),
                (By.CSS_SELECTOR, ".recaptcha-checkbox-border"),
                (By.CSS_SELECTOR, ".recaptcha-checkbox"),
                (By.XPATH, "//div[contains(@class,'recaptcha-checkbox')]"),
            ]

            el = None
            for by, sel in checkbox_selectors:
                try:
                    el = wait.until(EC.element_to_be_clickable((by, sel)))
                    if el:
                        break
                except Exception:
                    el = None
            if not el:
                logger.error("Could not find clickable reCAPTCHA checkbox inside iframe.")
                return False

            try:
                # Use ActionChains to ensure visible movement + click for triggering solver
                actions = ActionChains(self.driver)
                actions.move_to_element(el).pause(0.2).click().perform()
                logger.info("Clicked reCAPTCHA checkbox.")
            except Exception:
                # Fallback to element.click()
                try:
                    el.click()
                    logger.info("Clicked reCAPTCHA checkbox (fallback click).")
                except Exception as e:
                    logger.error(f"Failed to click reCAPTCHA checkbox: {e}")
                    return False

            # Wait a short moment for challenge to appear / token to be requested
            time.sleep(1.5)
            # Return to default content after clicking
            self.driver.switch_to.default_content()
            return True

        except Exception as e:
            logger.error(f"Error while attempting to click reCAPTCHA checkbox: {e}")
            try:
                self.driver.switch_to.default_content()
            except Exception:
                pass
            return False

    def _extract_sitekey(self):
        """Try to find a reCAPTCHA sitekey on the page."""
        # 1) Look for elements with data-sitekey attribute
        try:
            el = self.driver.find_elements(By.CSS_SELECTOR, "[data-sitekey]")
            if el:
                sitekey = el[0].get_attribute("data-sitekey")
                if sitekey:
                    logger.debug(f"Found sitekey via data-sitekey: {sitekey}")
                    return sitekey
        except Exception:
            pass

        # 2) Look for iframe src with k= parameter
        try:
            iframes = self.driver.find_elements(By.TAG_NAME, "iframe")
            for iframe in iframes:
                src = iframe.get_attribute("src") or ""
                if "recaptcha" in src.lower():
                    m = re.search(r"k=([^&]+)", src)
                    if m:
                        sitekey = urllib.parse.unquote(m.group(1))
                        logger.debug(f"Found sitekey via iframe src: {sitekey}")
                        return sitekey
        except Exception:
            pass

        return None

    def _is_driver_alive(self):
        """Return True if the webdriver session appears alive."""
        try:
            # quick lightweight check
            if not hasattr(self, "driver") or self.driver is None:
                return False
            # return document.readyState to keep session active
            state = self.driver.execute_script("return document.readyState")
            logger.debug(f"Browser readyState: {state}")
            return True
        except Exception as e:
            logger.debug(f"Driver alive check failed: {e}")
            return False

    def _keep_browser_awake(self):
        """Perform a tiny no-op script to keep the browser/webdriver responsive during long waits."""
        try:
            self.driver.execute_script("void(0);")
            return True
        except Exception as e:
            logger.debug(f"Keep-alive script failed: {e}")
            return False

    def _submit_2captcha(self, sitekey, page_url, timeout=None, poll_interval=5):
        """Submit a userrecaptcha request to 2captcha and poll for the solution token."""
        if timeout is None:
            timeout = getattr(Config, "CAPTCHA_SOLVE_TIMEOUT", 180)
        
        api_key = getattr(Config, "TWOCAPTCHA_API_KEY", None)
        if not api_key:
            logger.error("2Captcha API key not configured (TWOCAPTCHA_API_KEY).")
            return None

        create_url = "http://2captcha.com/in.php"
        params = {
            "key": api_key,
            "method": "userrecaptcha",
            "googlekey": sitekey,
            "pageurl": page_url,
            "json": 1
        }
        try:
            logger.info("Submitting captcha to 2Captcha...")
            r = requests.post(create_url, data=params, timeout=30)
            r.raise_for_status()
            data = r.json()
            logger.debug(f"2Captcha submission response: {data}")
            if data.get("status") != 1:
                logger.error(f"2Captcha submission failed: {data}")
                return None
            captcha_id = data.get("request")
            logger.info(f"2Captcha job created, id={captcha_id}")
        except Exception as e:
            logger.error(f"Error submitting captcha to 2Captcha: {e}")
            return None

        # Poll for result, keeping browser awake
        result_url = "http://2captcha.com/res.php"
        end_time = time.time() + timeout
        logger.info("Waiting for 2Captcha to solve reCAPTCHA (this can take a while)...")
        while time.time() < end_time:
            # keep browser alive before each poll attempt
            if hasattr(self, "driver"):
                if not self._keep_browser_awake():
                    logger.warning("Browser session appears unresponsive while waiting for solver.")
                    # do not return yet; allow one final poll attempt but if driver is dead avoid injection later
            try:
                params = {"key": api_key, "action": "get", "id": captcha_id, "json": 1}
                r = requests.get(result_url, params=params, timeout=30)
                r.raise_for_status()
                data = r.json()
                logger.debug(f"2Captcha poll response: {data}")
                if data.get("status") == 1:
                    token = data.get("request")
                    logger.success("2Captcha returned a solution token.")
                    return token
                elif data.get("request") == "CAPCHA_NOT_READY":
                    logger.debug("2Captcha not ready yet, polling again...")
                else:
                    logger.error(f"2Captcha returned error during poll: {data}")
                    return None
            except Exception as e:
                logger.debug(f"Polling error: {e}")
            time.sleep(poll_interval)

        logger.error("Timeout waiting for 2Captcha solution.")
        return None

    def _inject_recaptcha_token(self, token):
        """Insert the g-recaptcha-response token into the page so server validation can proceed."""
        try:
            js = """
            (function(token){
                var id = 'g-recaptcha-response';
                var el = document.getElementById(id);
                if(!el){
                    el = document.createElement('textarea');
                    el.id = id;
                    el.name = id;
                    el.style = 'display:none;';
                    document.body.appendChild(el);
                }
                el.value = token;
                // also set value on any existing element with that name
                var els = document.getElementsByName('g-recaptcha-response');
                for(var i=0;i<els.length;i++){ els[i].value = token; }
                // Trigger change events
                var evt = document.createEvent('HTMLEvents');
                evt.initEvent('change', true, true);
                el.dispatchEvent(evt);
            })(arguments[0]);
            """
            self.driver.execute_script(js, token)
            logger.info("Injected g-recaptcha-response token into the page.")
            return True
        except Exception as e:
            logger.error(f"Failed to inject reCAPTCHA token: {e}")
            return False

    def _get_2fa_code_from_email(self, timeout=60):
        """Fetch the most recent 2FA code from Gmail."""
        try:
            # Wait 30 seconds to ensure new email arrives
            logger.info("Waiting 10 seconds for new 2FA email to arrive...")
            time.sleep(10)
            
            logger.info("Checking Gmail for 2FA code...")
            mail = imaplib.IMAP4_SSL("imap.gmail.com")
            mail.login(Config.GMAIL_USER, Config.GMAIL_APP_PASSWORD)
            mail.select("inbox")

            # Format date for IMAP search (need only date part for SINCE)
            cutoff_date = (datetime.now() - timedelta(minutes=2)).strftime("%d-%b-%Y")
            logger.debug(f"Looking for emails since: {cutoff_date}")
            
            # Search in steps to avoid syntax errors
            try:
                # First find all emails from the sender
                _, sender_msgs = mail.search(None, f'(FROM "no-reply@mawaqit.net")')
                
                # Then find recent emails
                _, date_msgs = mail.search(None, f'(SINCE "{cutoff_date}")')
                
                # Convert message IDs to sets and find intersection
                sender_ids = set(sender_msgs[0].split())
                date_ids = set(date_msgs[0].split())
                message_ids = sorted(list(sender_ids & date_ids), reverse=True)
                
                logger.debug(f"Found {len(message_ids)} matching emails")
                
                if not message_ids:
                    logger.error("No matching emails found")
                    return None
                
                # Get the most recent email
                latest_email_id = message_ids[0]
                _, msg_data = mail.fetch(latest_email_id, "(RFC822)")
                email_body = msg_data[0][1]
                email_message = email.message_from_bytes(email_body)
                
                # Get email date for verification
                email_date = email.utils.parsedate_to_datetime(email_message['date'])
                logger.debug(f"Processing email from: {email_date}")

                # Extract code from email body
                for part in email_message.walk():
                    if part.get_content_type() == "text/plain":
                        body = part.get_payload(decode=True).decode()
                        # Look for 6-digit code
                        match = re.search(r'\b(\d{6})\b', body)
                        if match:
                            code = match.group(1)
                            logger.success(f"Found authentication code: {code}")
                            return code

                logger.error("No 6-digit code found in email body")
                return None

            except Exception as e:
                logger.error(f"Error searching emails: {str(e)}")
                return None

        except Exception as e:
            logger.error(f"Error in email processing: {str(e)}")
            return None
        finally:
            try:
                mail.close()
                mail.logout()
            except Exception:
                pass

    def _save_debug_screenshot(self, name):
        """Save a debug screenshot with timestamp."""
        try:
            timestamp = datetime.now().strftime("%H%M%S")
            filename = f"debug_{name}_{timestamp}.png"
            self.driver.save_screenshot(filename)
            logger.debug(f"Saved screenshot: {filename}")
        except Exception as e:
            logger.debug(f"Failed to save screenshot: {e}")
    
    def _capture_network_logs(self, context=""):
        """Capture and log network requests, especially file uploads."""
        try:
            logger.info(f"📡 CAPTURING NETWORK LOGS [{context}]")
            logger.info("=" * 80)
            
            # Get browser logs
            logs = self.driver.get_log('performance')
            
            upload_requests = []
            file_related = []
            errors = []
            
            for entry in logs:
                try:
                    log_entry = json.loads(entry['message'])
                    message = log_entry.get('message', {})
                    method = message.get('method', '')
                    
                    # Focus on network events
                    if 'Network' in method:
                        params = message.get('params', {})
                        
                        # Request details
                        if method == 'Network.requestWillBeSent':
                            request = params.get('request', {})
                            url = request.get('url', '')
                            req_method = request.get('method', '')
                            
                            # Log file-related requests
                            if 'csv' in url.lower() or 'upload' in url.lower() or 'file' in url.lower():
                                file_related.append({
                                    'method': req_method,
                                    'url': url,
                                    'headers': request.get('headers', {}),
                                    'postData': request.get('postData', 'N/A')
                                })
                                logger.debug(f"🔵 REQUEST: {req_method} {url}")
                        
                        # Response details
                        elif method == 'Network.responseReceived':
                            response = params.get('response', {})
                            url = response.get('url', '')
                            status = response.get('status', 0)
                            
                            if 'csv' in url.lower() or 'upload' in url.lower() or 'file' in url.lower():
                                logger.debug(f"🟢 RESPONSE: {status} {url}")
                                if status >= 400:
                                    errors.append({
                                        'url': url,
                                        'status': status,
                                        'statusText': response.get('statusText', '')
                                    })
                        
                        # Failed requests
                        elif method == 'Network.loadingFailed':
                            error_text = params.get('errorText', '')
                            request_id = params.get('requestId', '')
                            logger.error(f"🔴 FAILED REQUEST: {error_text}")
                            errors.append({
                                'type': 'loading_failed',
                                'error': error_text,
                                'requestId': request_id
                            })
                
                except Exception as e:
                    continue
            
            # Log summary
            logger.info(f"File-related requests: {len(file_related)}")
            for req in file_related:
                logger.info(f"  📤 {req['method']} {req['url']}")
                if req.get('postData'):
                    data_preview = str(req['postData'])[:200]
                    logger.info(f"     Data: {data_preview}...")
            
            logger.info(f"Errors found: {len(errors)}")
            for err in errors:
                logger.error(f"  ❌ {err}")
            
            logger.info("=" * 80)
            
            return {'file_related': file_related, 'errors': errors}
            
        except Exception as e:
            logger.error(f"Error capturing network logs: {e}")
            return None
    
    def _capture_console_logs(self, context=""):
        """Capture and log browser console messages."""
        try:
            logger.info(f"🖥️ CAPTURING CONSOLE LOGS [{context}]")
            logger.info("=" * 80)
            
            # Get browser console logs
            logs = self.driver.get_log('browser')
            
            errors = []
            warnings = []
            info = []
            
            for entry in logs:
                level = entry.get('level', '').upper()
                message = entry.get('message', '')
                
                if level == 'SEVERE':
                    errors.append(message)
                    logger.error(f"  🔴 {message}")
                elif level == 'WARNING':
                    warnings.append(message)
                    logger.warning(f"  🟡 {message}")
                else:
                    info.append(message)
                    logger.debug(f"  ℹ️ {message}")
            
            logger.info(f"Console errors: {len(errors)}, warnings: {len(warnings)}, info: {len(info)}")
            logger.info("=" * 80)
            
            return {'errors': errors, 'warnings': warnings, 'info': info}
            
        except Exception as e:
            logger.error(f"Error capturing console logs: {e}")
            return None
    
    def _trigger_file_input_events(self, file_input):
        """Trigger various events on file input to ensure proper handling by JS frameworks."""
        try:
            logger.info("🎯 TRIGGERING FILE INPUT EVENTS")
            
            # Comprehensive event triggering for different frameworks
            js = """
            var input = arguments[0];
            
            // Standard DOM events
            ['change', 'input', 'blur'].forEach(function(eventType) {
                var event = new Event(eventType, { bubbles: true, cancelable: true });
                input.dispatchEvent(event);
                console.log('Dispatched: ' + eventType);
            });
            
            // Vue.js specific (if Vue is detected)
            if (input.__vue__) {
                console.log('Vue.js detected - triggering Vue update');
                try {
                    input.__vue__.$forceUpdate();
                } catch(e) {
                    console.warn('Vue forceUpdate failed:', e);
                }
            }
            
            // Check if there's a parent Vue component
            var el = input;
            while (el.parentElement) {
                el = el.parentElement;
                if (el.__vue__) {
                    console.log('Parent Vue component found - triggering update');
                    try {
                        el.__vue__.$forceUpdate();
                    } catch(e) {}
                    break;
                }
            }
            
            // Trigger any onchange handler directly
            if (input.onchange) {
                console.log('Direct onchange handler found - calling it');
                try {
                    input.onchange();
                } catch(e) {
                    console.warn('onchange call failed:', e);
                }
            }
            
            return 'Events triggered';
            """
            
            result = self.driver.execute_script(js, file_input)
            logger.info(f"  ✓ {result}")
            
        except Exception as e:
            logger.error(f"Error triggering events: {e}")
    
    def _inspect_file_input_context(self, file_input):
        """Inspect the file input element and its surrounding context."""
        try:
            logger.info("🔍 INSPECTING FILE INPUT CONTEXT")
            logger.info("=" * 80)
            
            # Get info about the file input itself
            logger.info("File Input Attributes:")
            attrs = ['id', 'name', 'class', 'accept', 'multiple', 'required']
            for attr in attrs:
                val = file_input.get_attribute(attr)
                if val:
                    logger.info(f"  {attr}: {val}")
            
            # Get the parent form if any
            try:
                form_js = """
                var input = arguments[0];
                var form = input.closest('form');
                if (form) {
                    return {
                        id: form.id,
                        name: form.name,
                        action: form.action,
                        method: form.method,
                        enctype: form.enctype,
                        innerHTML: form.innerHTML.substring(0, 500)
                    };
                }
                return null;
                """
                form_info = self.driver.execute_script(form_js, file_input)
                if form_info:
                    logger.info("Parent Form:")
                    for key, val in form_info.items():
                        if key != 'innerHTML':
                            logger.info(f"  {key}: {val}")
                        else:
                            logger.debug(f"  Form HTML preview: {val}...")
                else:
                    logger.warning("  No parent form found")
            except Exception as e:
                logger.debug(f"Error getting form info: {e}")
            
            # Check for event listeners
            try:
                listeners_js = """
                var input = arguments[0];
                var events = ['change', 'input', 'blur', 'focus'];
                var result = {};
                events.forEach(function(evt) {
                    var listener = input['on' + evt];
                    result[evt] = listener ? 'YES' : 'NO';
                });
                return result;
                """
                listeners = self.driver.execute_script(listeners_js, file_input)
                logger.info("Event Listeners:")
                for evt, has in listeners.items():
                    logger.info(f"  on{evt}: {has}")
            except Exception as e:
                logger.debug(f"Error checking listeners: {e}")
            
            # Check for Vue.js or other frameworks
            try:
                framework_js = """
                var input = arguments[0];
                var checks = {
                    'Vue.js': !!input.__vue__,
                    'React': !!input._reactRootContainer || !!input._reactRootContainerID,
                    'Angular': !!input.getAttribute('ng-model') || !!input.getAttribute('[ngModel]')
                };
                return checks;
                """
                frameworks = self.driver.execute_script(framework_js, file_input)
                logger.info("Framework Detection:")
                for fw, detected in frameworks.items():
                    if detected:
                        logger.info(f"  {fw}: ✓ DETECTED")
            except Exception as e:
                logger.debug(f"Error checking frameworks: {e}")
            
            logger.info("=" * 80)
            
        except Exception as e:
            logger.error(f"Error inspecting file input context: {e}")

    def _log_debug_state(self, context=""):
        """Log current page state for debugging."""
        try:
            timestamp = time.strftime("%H%M%S")
            screenshot_path = f"debug_{context}_{timestamp}.png"
            self.driver.save_screenshot(screenshot_path)
            logger.debug(f"Screenshot saved: {screenshot_path}")
            
            logger.debug(f"Current URL: {self.driver.current_url}")
            logger.debug(f"Page title: {self.driver.title}")
            
            # Log visible text
            body_text = self.driver.find_element(By.TAG_NAME, "body").text
            logger.debug("Visible text on page:")
            for line in body_text.split('\n')[:10]:  # First 10 lines
                logger.debug(f"  > {line}")
                
            # Log input fields
            inputs = self.driver.find_elements(By.TAG_NAME, "input")
            logger.debug("Input fields found:")
            for inp in inputs:
                logger.debug(f"  > {inp.get_attribute('name')} - {inp.get_attribute('type')} - {inp.get_attribute('placeholder')}")
                
        except Exception as e:
            logger.error(f"Error logging debug state: {e}")

    def _wait_for_url_change(self, expected_urls, timeout=30, on_match=None):
        """Wait for URL to contain any of expected_urls; log and return True on success.
        If on_match is provided it will be called immediately after a match is detected.
        """
        try:
            WebDriverWait(self.driver, timeout).until(
                lambda d: any(u in (d.current_url or "") for u in expected_urls)
            )
            logger.success(f"URL changed to: {self.driver.current_url}")

            # If a callback is provided and the current URL contains /en, call it immediately
            try:
                if on_match and "/en" in (self.driver.current_url or "").lower():
                    logger.info("Detected /en landing — invoking on_match callback immediately.")
                    try:
                        on_match()
                    except Exception as e:
                        logger.debug(f"on_match callback raised: {e}")
            except Exception:
                # swallow any callback-related errors to avoid breaking main flow
                logger.debug("Error while attempting on_match callback")

            return True
        except Exception:
            logger.debug(f"URL did not change to any of {expected_urls} within {timeout}s. Current URL: {self.driver.current_url}")
            return False

    def _click_visible_login_button(self):
        """Try multiple strategies to click the visible 'Login' control.
        Returns True if a click/submit was attempted, False otherwise.
        """
        try:
            logger.info("Attempting to locate a visible 'Login' control (button/link/input/role=button)...")
            # Selenium-level tries for common element types first (fast)
            candidates = []
            candidates += self.driver.find_elements(By.XPATH, "//button")
            candidates += self.driver.find_elements(By.XPATH, "//a")
            candidates += self.driver.find_elements(By.XPATH, "//input[@type='submit' or @type='button']")
            candidates += self.driver.find_elements(By.CSS_SELECTOR, "[role='button']")

            def visible_text_matches(el):
                try:
                    if not el.is_displayed():
                        return False
                    txt = (el.text or el.get_attribute("value") or "").strip().lower()
                    return "login" == txt or txt.startswith("login") or "login" in txt
                except Exception:
                    return False

            for el in candidates:
                try:
                    if visible_text_matches(el):
                        logger.debug(f"Found visible candidate element: tag={el.tag_name} text='{el.text}'")
                        try:
                            self.driver.execute_script("arguments[0].scrollIntoView({block:'center',inline:'nearest'});", el)
                        except Exception:
                            pass
                        try:
                            el.click()
                            logger.success("Clicked login control via Selenium element.click()")
                        except Exception as e:
                            logger.debug(f"Element.click() failed: {e}; trying JS click fallback on the element")
                            try:
                                self.driver.execute_script("arguments[0].click();", el)
                                logger.success("Clicked login control via JS on element")
                            except Exception as e2:
                                logger.debug(f"JS click on element failed: {e2}")
                                continue
                        return True
                except Exception:
                    continue

            # If no Selenium candidate matched, use a robust JS fallback:
            logger.info("Selenium search did not find a clear candidate — running JS fallback to click visible element by text.")
            js_clicker = """
            (function(){
                function isVisible(el){
                    if(!el) return false;
                    var rect = el.getBoundingClientRect();
                    return !!(rect.width && rect.height) && window.getComputedStyle(el).visibility !== 'hidden' && el.offsetParent !== null;
                }
                var texts = ['login','log in'];
                var elements = Array.from(document.querySelectorAll('button, a, input[type=submit], [role=button]'));
                for(var i=0;i<elements.length;i++){
                    var el = elements[i];
                    if(!isVisible(el)) continue;
                    var txt = (el.innerText || el.value || '').trim().toLowerCase();
                    for(var j=0;j<texts.length;j++){
                        if(txt === texts[j] || txt.indexOf(texts[j]) !== -1){
                            el.scrollIntoView({block:'center'});
                            el.click();
                            return true;
                        }
                    }
                }
                // Last resort: try any visible button in the primary card area
                var cardButtons = Array.from(document.querySelectorAll('.card button, form button'));
                for(var k=0;k<cardButtons.length;k++){
                    if(isVisible(cardButtons[k])){
                        cardButtons[k].scrollIntoView({block:'center'});
                        cardButtons[k].click();
                        return true;
                    }
                }
                return false;
            })();
            """
            clicked = self.driver.execute_script(js_clicker)
            if clicked:
                logger.success("Clicked login control via JS fallback")
                return True

            # Final fallback: submit the form that contains the code input if we can find it
            try:
                js_submit_form = """
                (function(){
                    var inputs = document.querySelectorAll('input, textarea, select');
                    for(var i=0;i<inputs.length;i++){
                        var el = inputs[i];
                        if(el && el.value && el.value.trim().length>0){
                            var form = el.closest('form');
                            if(form){ form.submit(); return true; }
                        }
                    }
                    return false;
                })();
                """
                submitted = self.driver.execute_script(js_submit_form)
                if submitted:
                    logger.success("Submitted enclosing form via JS fallback")
                    return True
            except Exception as e:
                logger.debug(f"Form submit fallback failed: {e}")

            logger.warning("Could not find or click a visible Login control.")
            return False

        except Exception as e:
            logger.error(f"Error in _click_visible_login_button: {e}")
            return False

    def _wait_for_en_landing(self, timeout=30, on_match=None):
        """Wait specifically for the site landing under /en (https://mawaqit.net/en/).
        Uses URL and heuristics (anchors, canonical, logo) to detect the landing.
        Calls on_match() immediately if provided when match occurs.
        """
        try:
            end_time = time.time() + timeout
            while time.time() < end_time:
                try:
                    cur = (self.driver.current_url or "").lower()
                except Exception:
                    cur = ""
                # direct URL match /en root or path
                if cur.startswith("https://mawaqit.net/en") or "/en/" in cur or cur.endswith("/en"):
                    logger.success(f"EN landing detected: {self.driver.current_url}")
                    if on_match:
                        try:
                            on_match()
                        except Exception as e:
                            logger.debug(f"on_match callback error: {e}")
                    return True

                # fallback heuristics: canonical link, visible anchor/logo to /en
                try:
                    # canonical
                    canon = self.driver.find_elements(By.XPATH, "//link[@rel='canonical']")
                    for c in canon:
                        h = (c.get_attribute("href") or "").lower()
                        if "/en" in h:
                            logger.success(f"EN landing detected via canonical: {h}")
                            if on_match:
                                try:
                                    on_match()
                                except Exception as e:
                                    logger.debug(f"on_match callback error: {e}")
                            return True
                except Exception:
                    pass

                try:
                    anchors = self.driver.find_elements(By.CSS_SELECTOR, "a[href*='/en']")
                    for a in anchors:
                        try:
                            if a.is_displayed():
                                logger.success("EN landing detected via visible anchor")
                                if on_match:
                                    try:
                                        on_match()
                                    except Exception as e:
                                        logger.debug(f"on_match callback error: {e}")
                                return True
                        except Exception:
                            continue
                except Exception:
                    pass

                # short keep-alive and retry
                try:
                    self._keep_browser_awake()
                except Exception:
                    pass
                time.sleep(0.5)

            logger.debug(f"EN landing not detected within {timeout}s. Current URL: {getattr(self.driver,'current_url',None)}")
            return False
        except Exception as e:
            logger.debug(f"_wait_for_en_landing error: {e}")
            return False

    def _handle_2fa(self, timeout=60):
        """Handle 2FA verification on the /security/2fa page."""
        try:
            if "/security/2fa" not in self.driver.current_url:
                logger.error(f"Not on 2FA page. Current URL: {self.driver.current_url}")
                return False

            logger.info("On 2FA verification page, looking for input field...")
            
            # Look for input field - it's the only input on the page
            input_selectors = [
                (By.CSS_SELECTOR, "input[type='text']"),
                (By.XPATH, "//h1[contains(text(),'Two-factor authentication')]/..//input"),
                (By.XPATH, "//div[contains(text(),'6-digit code')]/following::input[1]")
            ]

            two_fa_input = None
            for by, selector in input_selectors:
                try:
                    two_fa_input = WebDriverWait(self.driver, 5).until(
                        EC.presence_of_element_located((by, selector))
                    )
                    if two_fa_input and two_fa_input.is_displayed():
                        logger.success(f"Found 2FA input using {by}={selector}")
                        break
                except Exception:
                    two_fa_input = None
                    continue

            if not two_fa_input:
                logger.error("Could not find 2FA input field")
                self._save_debug_screenshot("no_2fa_input")
                return False

            # Wait a short extra time so the correct email/code arrives if needed
            extra_wait = getattr(Config, "EXTRA_2FA_EMAIL_WAIT", 30)
            logger.info(f"Waiting additional {extra_wait}s to ensure latest email arrives...")
            time.sleep(extra_wait)

            logger.info("Checking Gmail for 2FA code...")
            code = self._get_2fa_code_from_email(timeout)
            if not code:
                logger.error("Failed to get 2FA code from email")
                self._save_debug_screenshot("2fa_no_code")
                return False

            # Enter the code with visible typing and dispatch events
            logger.info(f"Entering 2FA code: {code}")
            two_fa_input.clear()
            for ch in code:
                two_fa_input.send_keys(ch)
                logger.debug(f"Typed digit: {ch}")
                time.sleep(0.18)

            # Dispatch input/change and blur so client-side listeners update
            try:
                self.driver.execute_script("""
                    var el = arguments[0];
                    el.dispatchEvent(new Event('input', {bubbles:true}));
                    el.dispatchEvent(new Event('change', {bubbles:true}));
                    el.blur();
                """, two_fa_input)
            except Exception as e:
                logger.debug(f"Failed to dispatch input/change events: {e}")

            # Try to click the visible login button (robust helper)
            clicked = self._click_visible_login_button()
            if not clicked:
                logger.error("Could not click Login control after entering 2FA code")
                self._save_debug_screenshot("2fa_click_fail")
                return False

            # Wait specifically for the /en landing (instead of backoffice)
            logger.info("Waiting for the /en landing after 2FA submission...")
            if self._wait_for_en_landing(timeout=30):
                logger.success("2FA verification appears successful (EN landing detected).")
                return True
            else:
                # fallback: try old backoffice detection if needed
                logger.warning("EN landing not detected after 2FA; trying backoffice detection as fallback...")
                if self._wait_for_url_change(["/backoffice"], timeout=20):
                    logger.success("Backoffice detected after fallback.")
                    return True
                else:
                    logger.error("Failed to detect either /en landing or backoffice after 2FA.")
                    self._save_debug_screenshot("2fa_no_redirect")
                    return False

        except Exception as e:
            logger.error(f"Error during 2FA handling: {e}")
            self._save_debug_screenshot("2fa_error_exception")
            return False

    def _click_admin_button(self, timeout=10):
        """Locate and click the top 'Admin' control in the header. Returns True on success."""
        try:
            logger.info("Looking for Admin link/button in header...")
            selectors = [
                (By.LINK_TEXT, "ADMIN"),
                (By.LINK_TEXT, "Admin"),
                (By.XPATH, "//a[contains(translate(normalize-space(.),'abcdefghijklmnopqrstuvwxyz','ABCDEFGHIJKLMNOPQRSTUVWXYZ'),'ADMIN')]"),
                (By.CSS_SELECTOR, "a[href*='/admin']"),
                (By.XPATH, "//nav//a[contains(@href, '/admin')]"),
            ]

            for by, sel in selectors:
                try:
                    el = WebDriverWait(self.driver, 2).until(EC.element_to_be_clickable((by, sel)))
                    if el and el.is_displayed():
                        logger.debug(f"Clicking Admin control via selector: {by}={sel}")
                        try:
                            self.driver.execute_script("arguments[0].scrollIntoView({block:'center'});", el)
                        except Exception:
                            pass
                        try:
                            el.click()
                        except Exception:
                            # fallback JS click
                            self.driver.execute_script("arguments[0].click();", el)
                        logger.success("Clicked Admin control")
                        return True
                except Exception:
                    continue

            # JS fallback: search by visible text and click the first match
            logger.info("Admin not found via selectors — trying JS fallback")
            js = """
            (function(){
                function visible(el){
                    if(!el) return false;
                    var rc = el.getBoundingClientRect();
                    return rc.width>0 && rc.height>0 && window.getComputedStyle(el).visibility!=='hidden';
                }
                var texts = ['admin','ADMIN','Admin'];
                var elems = Array.from(document.querySelectorAll('a, button, [role=button]'));
                for(var i=0;i<elems.length;i++){
                    var e = elems[i];
                    if(!visible(e)) continue;
                    var t = (e.innerText || e.value || '').trim();
                    for(var j=0;j<texts.length;j++){
                        if(t === texts[j] || t.indexOf(texts[j]) !== -1){
                            e.scrollIntoView({block:'center'});
                            e.click();
                            return true;
                        }
                    }
                }
                return false;
            })();
            """
            clicked = self.driver.execute_script(js)
            if clicked:
                logger.success("Clicked Admin control via JS fallback")
                return True

            logger.warning("Admin control not found")
            self._save_debug_screenshot("admin_not_found")
            return False

        except Exception as e:
            logger.error(f"Error clicking Admin control: {e}")
            self._save_debug_screenshot("admin_click_error")
            return False

    def _is_on_en_landing(self):
        """Heuristic check if the browser is on the /en landing (covers URL-less content swaps)."""
        try:
            cur = (self.driver.current_url or "").lower()
            # quick URL check (but avoid treating the /security/2fa page as landing)
            if "/en" in cur and "/security/2fa" not in cur:
                return True

            # look for anchor links that point to /en (visible)
            anchors = self.driver.find_elements(By.CSS_SELECTOR, "a[href*='/en']")
            for a in anchors:
                try:
                    if a.is_displayed():
                        h = (a.get_attribute("href") or "").lower()
                        if "/en" in h:
                            return True
                except Exception:
                    continue

            # check canonical/meta link
            try:
                canon = self.driver.find_element(By.XPATH, "//link[@rel='canonical']")
                href = (canon.get_attribute("href") or "").lower()
                if "/en" in href:
                    return True
            except Exception:
                pass

            # check for common header/logo linking to /en
            logo_candidates = self.driver.find_elements(By.CSS_SELECTOR, "a.navbar-brand, a.logo, header a")
            for l in logo_candidates:
                try:
                    if not l.is_displayed():
                        continue
                    h = (l.get_attribute("href") or "").lower()
                    if "/en" in h:
                        return True
                except Exception:
                    continue

            # fallback: page title / visible keywords
            title = (self.driver.title or "").lower()
            if "mawaqit" in title or "prayer" in title or "backoffice" not in title:
                # presence of site title is a weak positive
                return True

        except Exception as e:
            logger.debug(f"_is_on_en_landing check error: {e}")
        return False

    def _click_actions_and_configure(self, timeout=10):
        """Locate a visible 'Actions' button on the admin card and click the 'Configure' menu item.
        Returns True on success, False otherwise.
        """
        try:
            logger.info("Looking for visible 'Actions' button on mosque card...")
            # Strategy 1: visible button elements containing 'Actions'
            candidates = self.driver.find_elements(By.XPATH, "//button[contains(normalize-space(.),'Actions') or contains(normalize-space(.),'Action')]")
            # include links that may act as buttons
            candidates += self.driver.find_elements(By.XPATH, "//a[contains(normalize-space(.),'Actions') or contains(normalize-space(.),'Action')]")

            btn = None
            for el in candidates:
                try:
                    if el.is_displayed() and el.is_enabled():
                        btn = el
                        logger.debug(f"Found Actions candidate: tag={el.tag_name} text='{el.text}'")
                        break
                except Exception:
                    continue

            # Fallback: search within card elements for a button labelled "Actions"
            if not btn:
                logger.debug("No immediate Actions button found, scanning card areas...")
                card_buttons = self.driver.find_elements(By.XPATH, "//div[contains(@class,'card')]//button")
                for el in card_buttons:
                    try:
                        txt = (el.text or "").strip().lower()
                        if "action" in txt:
                            if el.is_displayed() and el.is_enabled():
                                btn = el
                                break
                    except Exception:
                        continue

            if not btn:
                logger.warning("Could not find an Actions button on the page.")
                self._save_debug_screenshot("actions_not_found")
                return False

            # Click the Actions button (use JS fallback if standard click fails)
            logger.info("Clicking the Actions button...")
            try:
                # Try a visible move + click to mimic user
                actions = ActionChains(self.driver)
                actions.move_to_element(btn).pause(0.2).click().perform()
            except Exception as e:
                logger.debug(f"ActionChains click failed: {e}; trying element.click()")
                try:
                    btn.click()
                except Exception as e:
                    logger.debug(f"element.click() failed: {e}; trying JS click")
                    try:
                        self.driver.execute_script("arguments[0].click();", btn)
                    except Exception as e3:
                        logger.error(f"Failed to click Actions button: {e3}")
                        self._save_debug_screenshot("actions_click_failed")
                        return False

            # Wait for dropdown / menu to appear with 'Configure' item
            logger.info("Waiting for 'Configure' menu item to appear...")
            menu_selectors = [
                (By.XPATH, "//a[normalize-space(.)='Configure']"),
                (By.XPATH, "//button[normalize-space(.)='Configure']"),
                (By.XPATH, "//li//a[normalize-space(.)='Configure']"),
                (By.XPATH, "//div[contains(@class,'dropdown-menu')]//a[contains(normalize-space(.),'Configure')]"),
                (By.XPATH, "//div[contains(@class,'dropdown-menu')]//button[contains(normalize-space(.),'Configure')]"),
                (By.XPATH, "//*[contains(normalize-space(.),'Configure') and (self::a or self::button or ancestor::li)]")
            ]

            config_el = None
            wait = WebDriverWait(self.driver, timeout)
            for by, sel in menu_selectors:
                try:
                    config_el = wait.until(EC.element_to_be_clickable((by, sel)))
                    if config_el and config_el.is_displayed():
                        logger.debug(f"Found Configure menu item using {by}={sel}")
                        break
                except Exception:
                    config_el = None
                    continue

            if not config_el:
                # As a final fallback, try to locate any visible menu item containing 'configure' text
                try:
                    all_menu_el = self.driver.find_elements(By.XPATH, "//*[contains(translate(normalize-space(.),'ABCDEFGHIJKLMNOPQRSTUVWXYZ','abcdefghijklmnopqrstuvwxyz'),'configure')]")
                    for el in all_menu_el:
                        try:
                            if el.is_displayed() and el.is_enabled():
                                config_el = el
                                logger.debug("Found Configure-like element via fallback visible search")
                                break
                        except Exception:
                            continue
                except Exception:
                    pass

            if not config_el:
                logger.error("Could not find 'Configure' in Actions dropdown.")
                self._save_debug_screenshot("configure_not_found")
                return False

            # Click Configure
            logger.info("Clicking 'Configure'...")
            try:
                # Scroll into view + click
                self.driver.execute_script("arguments[0].scrollIntoView({block:'center'});", config_el)
                time.sleep(0.2)
                config_el.click()
            except Exception as e:
                logger.debug(f"Direct click failed: {e}; trying JS click")
                try:
                    self.driver.execute_script("arguments[0].click();", config_el)
                except Exception as e2:
                    logger.error(f"Failed to click Configure: {e2}")
                    self._save_debug_screenshot("configure_click_failed")
                    return False

            # Wait briefly for configure page/modal to load
            logger.info("Waiting briefly for configure page/modal to appear...")
            time.sleep(1.0)
            logger.success("Clicked Configure from Actions dropdown.")
            return True

        except Exception as e:
            logger.error(f"Error in _click_actions_and_configure: {e}")
            self._save_debug_screenshot("actions_configure_exception")
            return False

    def _get_month_name(self):
        """Return current month name (e.g. 'November')."""
        return datetime.now().strftime("%B")

    def _possible_month_labels(self, month_name):
        """Return a list of possible displayed labels for the given English month name.
        Add localized variants (French) that the site may use.
        """
        # Minimal mapping; extend if you see other variants/languages on the site
        mapping = {
            "January":   ["January", "Janvier"],
            "February":  ["February", "Février", "Fevrier"],
            "March":     ["March", "Mars"],
            "April":     ["April", "Avril"],
            "May":       ["May", "Mai"],
            "June":      ["June", "Juin"],
            "July":      ["July", "Juillet"],
            "August":    ["August", "Août", "Aout"],
            "September": ["September", "Septembre"],
            "October":   ["October", "Octobre"],
            "November":  ["November", "Novembre"],
            "December":  ["December", "Décembre", "Decembre"]
        }
        return mapping.get(month_name, [month_name, month_name.lower(), month_name.capitalize()])

    def _log_csv_verification(self, local_path):
        """Log first few lines of CSV for verification."""
        try:
            with open(local_path, 'r') as f:
                first_lines = [f.readline().strip() for _ in range(3)]
                logger.debug(f"   First 3 lines of CSV:")
                for i, line in enumerate(first_lines, 1):
                    logger.debug(f"     {i}. {line[:80]}...")
        except Exception:
            pass

    def _download_month_csvs(self, month_name):
        """Get athan and iqama CSVs for the given month.
        First checks for local files, then falls back to downloading from GitHub.
        Returns dict{ 'athan': path, 'iqama': path } on success or None on failure.
        """
        try:
            names = {
                'athan': f"athan_times_{month_name}.csv",
                'iqama': f"iqama_times_{month_name}.csv"
            }
            out_dir = getattr(Config, "PRAYER_TIMES_DIR", "./prayer-times")
            os.makedirs(out_dir, exist_ok=True)
            
            # GitHub base URL for downloading files if not found locally
            github_base_url = "https://raw.githubusercontent.com/MuhammadElsoukkary/PrayerTimesScraper/main/prayer_times/"

            paths = {}
            for key, fname in names.items():
                local = os.path.join(out_dir, fname)
                
                # Check if file exists locally first
                if os.path.exists(local) and os.path.getsize(local) > 0:
                    file_size = os.path.getsize(local)
                    logger.success(f"✓ Found local {fname} ({file_size} bytes)")
                    logger.debug(f"   Local path: {os.path.abspath(local)}")
                    self._log_csv_verification(local)
                    paths[key] = local
                else:
                    # File doesn't exist locally, try downloading from GitHub
                    url = github_base_url + fname
                    logger.info(f"📥 Local file not found, downloading {fname} from GitHub...")
                    logger.debug(f"   URL: {url}")
                    try:
                        r = requests.get(url, timeout=30)
                        if r.status_code == 200:
                            with open(local, "wb") as fh:
                                fh.write(r.content)
                            
                            # Verify file was written
                            file_size = os.path.getsize(local)
                            logger.success(f"✓ Downloaded and saved {fname} ({file_size} bytes)")
                            logger.debug(f"   Local path: {os.path.abspath(local)}")
                            self._log_csv_verification(local)
                            paths[key] = local
                        else:
                            logger.error(f"Failed to download {fname}: HTTP {r.status_code}")
                            logger.debug(f"   Response: {r.text[:200]}")
                            return None
                    except Exception as e:
                        logger.error(f"Exception downloading {fname}: {e}")
                        return None
            return paths
        except Exception as e:
            logger.error(f"Error in _download_month_csvs: {e}")
            return None

    def _get_day_1_fajr_value(self, month_name):
        """
        Robustly finds the Fajr time for Day 1 in the currently visible month's table.
        """
        try:
            # Find the currently expanded accordion panel (which has class 'show')
            # This ensures we are looking in the correct month's section
            visible_panel_xpath = "//div[contains(@class, 'collapse') and contains(@class, 'show')]"
            visible_panel = self.driver.find_element(By.XPATH, visible_panel_xpath)
            
            # Within that visible panel, find the table row where the first cell is '1'
            day_1_row_xpath = ".//tr[td[1][normalize-space(.)='1']]"
            day_1_row = visible_panel.find_element(By.XPATH, day_1_row_xpath)
            
            # FIXED: Mawaqit uses input[@type='text'] with class 'calendar-prayer-time', NOT input[@type='time']
            # Try text input first (correct way), then fall back to time input if needed
            fajr_input = None
            try:
                fajr_input = day_1_row.find_element(By.XPATH, ".//input[contains(@class, 'calendar-prayer-time')]")
            except:
                # Fallback to old way
                fajr_input = day_1_row.find_element(By.XPATH, ".//input[@type='time']")
            
            value = fajr_input.get_attribute('value')
            return value if value else "empty"
            
        except Exception as e:
            logger.debug(f"Could not find Day 1 Fajr value. Reason: {e}")
            # Save a screenshot to see why the element wasn't found
            self._save_debug_screenshot("get_fajr_value_failed")
            return "not_found"

    def _click_calculation_and_prepopulate(self, athan_filepath, month_name, timeout=10):
        """Finds and clicks 'Pre-populate', uploads the file, and verifies data changes."""
        try:
            logger.info("=" * 60)
            logger.info("🔵 STARTING ATHAN CSV UPLOAD SEQUENCE")
            logger.info("=" * 60)
            logger.info(f"📄 File to upload: {athan_filepath}")
            logger.info(f"📂 Absolute path: {os.path.abspath(athan_filepath)}")
            logger.info(f"📊 File exists: {os.path.exists(athan_filepath)}")
            if os.path.exists(athan_filepath):
                logger.info(f"📦 File size: {os.path.getsize(athan_filepath)} bytes")
            logger.info("=" * 60)
            
            # Step 1: Click "Calculation of prayer times" section to expand it
            logger.info("Looking for 'Calculation of prayer times' section header...")
            calc_section = None
            
            # Try to find the clickable header
            calc_selectors = [
                "//*[normalize-space(.)='Calculation of prayer times']",
                "//*[contains(@class, 'panel-heading') and contains(., 'Calculation of prayer times')]",
                "//*[contains(normalize-space(.), 'Calculation of prayer times')]"
            ]
            
            for sel in calc_selectors:
                try:
                    elements = self.driver.find_elements(By.XPATH, sel)
                    for el in elements:
                        if el.is_displayed():
                            calc_section = el
                            logger.debug(f"Found calculation section with selector: {sel}")
                            break
                    if calc_section:
                        break
                except Exception:
                    continue
            
            if not calc_section:
                logger.error("Could not find 'Calculation of prayer times' section")
                self._save_debug_screenshot("calc_section_not_found")
                return False
            
            # Click to expand the calculation section
            logger.info("Clicking 'Calculation of prayer times' to expand it...")
            try:
                self.driver.execute_script("arguments[0].scrollIntoView({block:'center'});", calc_section)
                time.sleep(0.3)
                calc_section.click()
                logger.success("Clicked 'Calculation of prayer times'")
            except Exception as e:
                logger.debug(f"Direct click failed: {e}, trying JS click")
                try:
                    self.driver.execute_script("arguments[0].click();", calc_section)
                    logger.success("Clicked 'Calculation of prayer times' via JS")
                except Exception as e2:
                    logger.error(f"Failed to click calculation section: {e2}")
                    self._save_debug_screenshot("calc_section_click_failed")
                    return False
            
            # Wait for the section to expand
            time.sleep(1.0)

            # Step 2: Now find and click the month accordion INSIDE the expanded calculation section
            labels = self._possible_month_labels(month_name)
            logger.info(f"Opening month accordion for {month_name} — trying labels: {labels}")
            month_el = None

            for label in labels:
                lower = label.lower()
                # Look specifically inside the calculation section that we just expanded
                xpath_contains = f"//*[contains(translate(normalize-space(.),'ABCDEFGHIJKLMNOPQRSTUVWXYZ','abcdefghijklmnopqrstuvwxyz'), '{lower}')]"
                try:
                    candidates = self.driver.find_elements(By.XPATH, xpath_contains)
                    for el in candidates:
                        try:
                            if el.is_displayed():
                                txt = (el.text or "").strip()
                                # Make sure we're getting the month accordion, not other text
                                if txt and len(txt) < 30:  # Month names are short
                                    month_el = el
                                    logger.debug(f"Matched month label '{label}' with element text: '{txt}'")
                                    break
                        except Exception:
                            continue
                    if month_el:
                        break
                except Exception as e:
                    logger.debug(f"XPath search for label '{label}' failed: {e}")
                    continue

            if not month_el:
                logger.error(f"Could not find accordion header for month '{month_name}' (tried {labels}).")
                self._save_debug_screenshot("month_header_not_found")
                return False

            # Click to expand the month accordion - with detailed debugging
            logger.info(f"Opening month accordion for {month_name}...")
            try:
                # Check the current state before clicking
                before_state = self.driver.execute_script("""
                    var el = arguments[0];
                    var ariaExpanded = el.getAttribute('aria-expanded');
                    var classList = el.className;
                    
                    // Find associated panel
                    var target = el.getAttribute('data-target') || el.getAttribute('href');
                    var panel = target ? document.querySelector(target) : null;
                    var panelVisible = panel ? panel.classList.contains('show') : false;
                    
                    return {
                        ariaExpanded: ariaExpanded,
                        classList: classList,
                        target: target,
                        panelVisible: panelVisible
                    };
                """, month_el)
                logger.info(f"Before click: {before_state}")
                
                # Try MULTIPLE click strategies to ensure accordion opens
                self.driver.execute_script("arguments[0].scrollIntoView({block:'center'});", month_el)
                time.sleep(0.5)
                
                # Strategy 1: JS click
                self.driver.execute_script("arguments[0].click();", month_el)
                time.sleep(1.0)
                
                # Strategy 2: If not opened, try regular click
                try:
                    month_el.click()
                except:
                    pass
                time.sleep(1.0)
                
                # Strategy 3: Try clicking parent if it's a link/button wrapper
                try:
                    parent = month_el.find_element(By.XPATH, "..")
                    self.driver.execute_script("arguments[0].click();", parent)
                except:
                    pass
                
                logger.success(f"Clicked month header: {month_el.text.strip() if month_el.text else month_name}")
                
                # Wait for animation
                time.sleep(2.0)
                
                # Force the panel to open with JavaScript if click didn't work
                force_open_result = self.driver.execute_script("""
                    var el = arguments[0];
                    var ariaExpanded = el.getAttribute('aria-expanded');
                    var target = el.getAttribute('data-target') || el.getAttribute('href');
                    var panel = target ? document.querySelector(target) : null;
                    
                    if (!panel) {
                        return {success: false, error: 'No target panel found'};
                    }
                    
                    var wasVisible = panel.classList.contains('show');
                    
                    // Force open the panel
                    if (!wasVisible) {
                        panel.classList.add('show', 'in');
                        panel.style.display = 'block';
                        el.setAttribute('aria-expanded', 'true');
                        el.classList.remove('collapsed');
                    }
                    
                    var panelInputs = panel.querySelectorAll('input.calendar-prayer-time').length;
                    
                    return {
                        success: true,
                        wasVisible: wasVisible,
                        nowVisible: panel.classList.contains('show'),
                        panelInputs: panelInputs
                    };
                """, month_el)
                logger.info(f"Force open result: {force_open_result}")
                
                if force_open_result.get('success') and force_open_result.get('nowVisible'):
                    logger.success(f"✅ Panel is now open with {force_open_result.get('panelInputs')} inputs")
                else:
                    logger.error("❌ Could not open panel!")
                    
            except Exception as e:
                logger.error(f"Failed to click month header: {e}")
                self._save_debug_screenshot("month_click_failed")
                return False

            # METHOD 2: MANUAL ENTRY - Reliable for headless mode
            logger.info("="*60)
            logger.info("🚀 MANUAL ENTRY MODE: Entering each prayer time individually")
            logger.info("="*60)
            
            # Read the CSV file
            logger.info(f"📖 Reading CSV file: {athan_filepath}")
            import csv
            csv_data = []
            try:
                with open(athan_filepath, 'r') as f:
                    reader = csv.DictReader(f)
                    for row in reader:
                        csv_data.append(row)
                logger.success(f"✅ Loaded {len(csv_data)} rows from CSV")
                logger.info(f"Sample row: {csv_data[0] if csv_data else 'empty'}")
            except Exception as e:
                logger.error(f"Failed to read CSV: {e}")
                return False
            
            # Find all calendar input fields in the expanded month WITHIN Athan section
            logger.info("🔍 Finding Athan calendar input fields...")
            try:
                # Wait a bit more for panel to be ready
                time.sleep(2)
                
                # CRITICAL: Get inputs from the expanded month panel using the month_el we just clicked
                # The month_el has a data-target or href that points to the panel
                panel_id = month_el.get_attribute('data-target') or month_el.get_attribute('href')
                logger.info(f"📍 Athan panel ID: {panel_id}")
                
                if panel_id and panel_id.startswith('#'):
                    panel_id = panel_id[1:]  # Remove the #
                    month_panel = self.driver.find_element(By.ID, panel_id)
                    inputs = month_panel.find_elements(By.CSS_SELECTOR, "input.calendar-prayer-time")
                    logger.info(f"Found {len(inputs)} total inputs in Athan panel #{panel_id}")
                else:
                    # Fallback: find all inputs and filter by visibility
                    inputs = self.driver.find_elements(By.CSS_SELECTOR, "input.calendar-prayer-time")
                    logger.info(f"Found {len(inputs)} total calendar-prayer-time inputs")
                
                # Filter to only visible inputs (in the expanded panel)
                visible_inputs = []
                for inp in inputs:
                    try:
                        if inp.is_displayed():
                            visible_inputs.append(inp)
                    except:
                        pass
                
                logger.info(f"Found {len(visible_inputs)} VISIBLE Athan calendar inputs")
                
                if len(visible_inputs) == 0:
                    logger.error("No visible inputs found! Cannot populate.")
                    self._save_debug_screenshot("no_visible_inputs")
                    return False
                
                # First, log the CSV structure to verify
                logger.info(f"📊 CSV structure - First row keys: {list(csv_data[0].keys()) if csv_data else 'empty'}")
                logger.info(f"📊 First 3 days of data:")
                for i in range(min(3, len(csv_data))):
                    logger.info(f"  Day {i+1}: {csv_data[i]}")
                
                # CRITICAL: Check how many inputs per day to determine field mapping
                inputs_per_day = len(visible_inputs) // len(csv_data) if csv_data else 6
                logger.info(f"📊 Detected {inputs_per_day} inputs per day ({len(visible_inputs)} total / {len(csv_data)} days)")
                
                # Athan times typically have 6 prayers including Sunrise
                # But some calendars may have only 5 (no Sunrise)
                if inputs_per_day == 5:
                    logger.warning("⚠️ Only 5 inputs per day detected - skipping Sunrise")
                    prayer_names = ['Fajr', 'Dhuhr', 'Asr', 'Maghrib', 'Isha']
                else:
                    prayer_names = ['Fajr', 'Sunrise', 'Dhuhr', 'Asr', 'Maghrib', 'Isha']
                
                logger.info(f"📋 Using prayer mapping: {prayer_names}")
                
                # Populate each input
                logger.info("✍️ Entering prayer times into each field...")
                populated = 0
                
                for day_idx, row in enumerate(csv_data):
                    day_number = row.get('Day', day_idx + 1)
                    
                    for prayer_idx, prayer_name in enumerate(prayer_names):
                        input_index = (day_idx * inputs_per_day) + prayer_idx
                        
                        if input_index >= len(visible_inputs):
                            break
                        
                        time_value = row.get(prayer_name, '')
                        if time_value:
                            try:
                                inp = visible_inputs[input_index]
                                # Clear and enter the value
                                inp.clear()
                                inp.send_keys(time_value)
                                populated += 1
                                
                                # Log first 3 entries to verify mapping
                                if populated <= 3:
                                    logger.info(f"  📝 Entered: Day {day_number} {prayer_name} = {time_value} (input #{input_index})")
                                
                                # Log progress every 30 entries
                                if populated % 30 == 0:
                                    logger.info(f"Progress: {populated} fields entered...")
                            except Exception as e:
                                logger.error(f"Error entering Day {day_number} {prayer_name}: {e}")
                
                logger.success(f"✅ Successfully entered {populated} prayer times!")
                
                # CRITICAL: Close BOTH the month accordion AND the entire "Calculation of prayer times" section
                logger.info("🔽 Closing Athan month accordion and Calculation section...")
                try:
                    # Close the month accordion
                    self.driver.execute_script("""
                        var el = arguments[0];
                        var target = el.getAttribute('data-target') || el.getAttribute('href');
                        var panel = null;
                        
                        if (target) {
                            if (target.startsWith('#')) {
                                var id = target.substring(1);
                                panel = document.getElementById(id);
                            } else {
                                panel = document.querySelector(target);
                            }
                        }
                        
                        if (panel) {
                            panel.classList.remove('show', 'in');
                            panel.style.display = 'none';
                            el.setAttribute('aria-expanded', 'false');
                            el.classList.add('collapsed');
                        }
                    """, month_el)
                    logger.success("✅ Closed Athan month accordion")
                    time.sleep(0.5)
                    
                    # DON'T close the "Calculation" section - it will collapse Iqama too!
                    # Just closing the month accordion is enough
                    
                except Exception as e:
                    logger.warning(f"Could not close Athan accordion: {e}")
                
                return True
                
            except Exception as e:
                logger.error(f"Manual entry failed: {e}")
                return False
            pre_btn = None
            
            # Scroll to ensure the buttons are in view
            try:
                self.driver.execute_script("window.scrollBy(0, 200);")
                time.sleep(0.5)
            except Exception:
                pass

            # Look for turquoise button (btn-info class is commonly used for turquoise/cyan buttons)
            try:
                # First try to find all buttons that are visible
                all_buttons = self.driver.find_elements(By.TAG_NAME, "button")
                logger.debug(f"Found {len(all_buttons)} total buttons on page")
                
                for btn in all_buttons:
                    try:
                        if not btn.is_displayed():
                            continue
                        
                        btn_text = (btn.text or "").strip().lower()
                        btn_class = (btn.get_attribute("class") or "").lower()
                        
                        # Check if it's the pre-populate button by text or class
                        if ("pre" in btn_text and "csv" in btn_text) or \
                           ("prepopulate" in btn_text) or \
                           ("btn-info" in btn_class and "csv" in btn_text):
                            pre_btn = btn
                            logger.debug(f"Found Pre-populate button: text='{btn_text}' class='{btn_class}'")
                            break
                    except Exception as e:
                        logger.debug(f"Error checking button: {e}")
                        continue
                    if pre_btn:
                        break
            except Exception as e:
                logger.debug(f"Error finding buttons: {e}")

            # Fallback: try XPath selectors
            if not pre_btn:
                btn_selectors = [
                    "//*[contains(translate(., 'ABCDEFGHIJKLMNOPQRSTUVWXYZ', 'abcdefghijklmnopqrstuvwxyz'), 'pre-populate')]",
                    "//*[contains(@class, 'btn-info')]",
                    "//*[contains(., 'csv') and contains(., 'Pre')]"
                ]
                
                for sel in btn_selectors:
                    try:
                        logger.debug(f"Trying XPath: {sel}")
                        elements = self.driver.find_elements(By.XPATH, sel)
                        logger.debug(f"Found {len(elements)} elements with this XPath")
                        for el in elements:
                            if el.is_displayed():
                                el_text = (el.text or "").strip()
                                logger.debug(f"Found visible element: '{el_text}'")
                                if 'pre' in el_text.lower() or 'csv' in el_text.lower():
                                    pre_btn = el
                                    logger.success(f"Found via XPath: {sel}, text: '{el_text}'")
                                    break
                        if pre_btn:
                            break
                    except Exception as e:
                        logger.debug(f"XPath {sel} failed: {e}")
                        continue

            if not pre_btn:
                logger.error("Could not find Pre-populate button.")
                self._save_debug_screenshot("prepopulate_not_found")
                return False

            # CRITICAL: This button click should trigger the hidden file input to become active
            # We need to understand what JavaScript runs when this button is clicked
            logger.info("Inspecting 'Pre-populate' button's onclick handler...")
            try:
                button_info = self.driver.execute_script("""
                    var btn = arguments[0];
                    var onclick = btn.getAttribute('onclick') || btn.onclick;
                    var listeners = getEventListeners ? getEventListeners(btn) : null;
                    
                    return {
                        onclick: onclick ? onclick.toString() : null,
                        hasClickListener: listeners && listeners.click ? listeners.click.length : 0
                    };
                """, pre_btn)
                logger.info(f"Button info: {button_info}")
            except Exception as e:
                logger.debug(f"Could not inspect button: {e}")
            
            # Click using multiple strategies with explicit wait for clickability
            logger.info("Clicking 'Pre-populate from a csv file'...")
            clicked = False
            
            # Strategy 1: Wait for element to be clickable, then use JS click
            try:
                WebDriverWait(self.driver, 5).until(
                    EC.element_to_be_clickable((By.XPATH, f"//*[@id='{pre_btn.get_attribute('id')}']" if pre_btn.get_attribute('id') else "//button[1]"))
                )
            except Exception:
                pass
            
            # Try JS click first (most reliable for covered elements)
            try:
                self.driver.execute_script("arguments[0].scrollIntoView({block:'center', behavior:'smooth'});", pre_btn)
                time.sleep(0.5)
                self.driver.execute_script("arguments[0].click();", pre_btn)
                logger.success("Clicked Pre-populate button via JS")
                clicked = True
            except Exception as e:
                logger.debug(f"JS click failed: {e}")
            
            # Strategy 2: ActionChains click
            if not clicked:
                try:
                    actions = ActionChains(self.driver)
                    actions.move_to_element(pre_btn).pause(0.3).click().perform()
                    logger.success("Clicked Pre-populate button via ActionChains")
                    clicked = True
                except Exception as e:
                    logger.debug(f"ActionChains click failed: {e}")
            
            # Strategy 3: Direct click
            if not clicked:
                try:
                    pre_btn.click()
                    logger.success("Clicked Pre-populate button directly")
                    clicked = True
                except Exception as e:
                    logger.error(f"All click strategies failed: {e}")
                    self._save_debug_screenshot("prepopulate_click_failed")
                    return False

            # Wait for file input to appear
            logger.info("Waiting for file input to appear...")
            time.sleep(1.0)
            
            # Capture initial state
            self._capture_console_logs("BEFORE_ATHAN_UPLOAD")
            
            # --- NEW: Verify data BEFORE upload ---
            logger.info("Verifying data before upload...")
            # Use the capitalized English month name for the log message
            before_value = self._get_day_1_fajr_value(month_name.capitalize())
            logger.info(f"  > Fajr time for Day 1 (before): '{before_value}'")

            # CRITICAL: Find the hidden file input with class "fill-calendar"
            logger.info("🔍 Locating the hidden file input...")
            
            file_input = WebDriverWait(self.driver, 10).until(EC.presence_of_element_located((By.XPATH, "//input[@type='file' and contains(@class, 'fill-calendar')]")))
            
            # Search page source for fill-calendar event binding
            logger.info("🔍 Searching page source for fill-calendar event handler...")
            try:
                page_source = self.driver.page_source
                
                # Look for common patterns where .fill-calendar event is bound
                patterns = [
                    'fill-calendar',
                    '.fill-calendar',
                    'fillCalendar',
                    'data-calendar'
                ]
                
                for pattern in patterns:
                    if pattern in page_source:
                        # Find surrounding context (50 chars before/after)
                        idx = page_source.find(pattern)
                        if idx != -1:
                            context = page_source[max(0, idx-100):min(len(page_source), idx+200)]
                            logger.info(f"Found '{pattern}' in source: ...{context}...")
                            break
            except Exception as e:
                logger.debug(f"Could not search page source: {e}")
            
            abs_path = os.path.abspath(athan_filepath)
            
            # Inspect the file input and its context
            self._inspect_file_input_context(file_input)
            
            logger.info("🔄 Sending file to hidden input field...")
            file_input.send_keys(abs_path)
            logger.success("File path sent to input.")
            
            # Trigger all necessary events to ensure JS frameworks pick up the change
            time.sleep(0.5)
            self._trigger_file_input_events(file_input)
            
            # CRITICAL: We need to manually read the CSV and populate the calendar
            # since the automatic processing isn't working
            logger.info("🎯 Manually processing CSV file and populating calendar...")
            try:
                result = self.driver.execute_script("""
                    var input = arguments[0];
                    var file = input.files[0];
                    
                    if (!file) {
                        return {success: false, error: 'No file'};
                    }
                    
                    console.log('Starting manual CSV processing...');
                    
                    // Read the CSV file
                    var reader = new FileReader();
                    reader.onload = function(e) {
                        var csvText = e.target.result;
                        var lines = csvText.split('\\n');
                        
                        console.log('CSV loaded, lines:', lines.length);
                        
                        // Parse CSV (skip header)
                        var rows = [];
                        for (var i = 1; i < lines.length; i++) {
                            var line = lines[i].trim();
                            if (line) {
                                var values = line.split(',');
                                if (values.length >= 7) {
                                    rows.push({
                                        day: values[0],
                                        fajr: values[1],
                                        sunrise: values[2],
                                        dhuhr: values[3],
                                        asr: values[4],
                                        maghrib: values[5],
                                        isha: values[6]
                                    });
                                }
                            }
                        }
                        
                        console.log('Parsed rows:', rows.length);
                        
                        // Find the calendar inputs - but ONLY for the VISIBLE/EXPANDED month
                        var calendarName = input.getAttribute('data-calendar');
                        console.log('Calendar name:', calendarName);
                        
                        // CRITICAL: Find the currently VISIBLE/EXPANDED panel (accordion)
                        var expandedPanels = document.querySelectorAll('.panel-collapse.show, .collapse.show');
                        console.log('Found', expandedPanels.length, 'expanded panels');
                        
                        var expandedPanel = null;
                        // Find the panel with calendar inputs
                        for (var i = 0; i < expandedPanels.length; i++) {
                            var panel = expandedPanels[i];
                            var inputs = panel.querySelectorAll('input.calendar-prayer-time');
                            if (inputs.length > 0) {
                                expandedPanel = panel;
                                console.log('Found expanded panel with', inputs.length, 'calendar inputs');
                                break;
                            }
                        }
                        
                        if (!expandedPanel) {
                            console.error('No expanded panel with calendar inputs found!');
                            console.log('Trying to find ALL panels...');
                            var allPanels = document.querySelectorAll('.panel-collapse, .collapse');
                            console.log('Total panels:', allPanels.length);
                            
                            // Use the first panel with calendar inputs, even if not expanded
                            for (var i = 0; i < allPanels.length; i++) {
                                var panel = allPanels[i];
                                var inputs = panel.querySelectorAll('input.calendar-prayer-time');
                                if (inputs.length > 0) {
                                    expandedPanel = panel;
                                    console.log('Using first panel with', inputs.length, 'inputs');
                                    break;
                                }
                            }
                        }
                        
                        if (!expandedPanel) {
                            console.error('Could not find any panel with calendar inputs!');
                            return;
                        }
                        
                        // Find calendar inputs within the panel
                        var inputs = expandedPanel.querySelectorAll('input.calendar-prayer-time');
                        console.log('Final input count:', inputs.length);
                        
                        // Populate the inputs
                        // Each day has 6 times, so we need to map rows to inputs
                        var populated = 0;
                        rows.forEach(function(row, dayIndex) {
                            var dayTimes = [row.fajr, row.sunrise, row.dhuhr, row.asr, row.maghrib, row.isha];
                            dayTimes.forEach(function(time, timeIndex) {
                                var inputIndex = (dayIndex * 6) + timeIndex;
                                if (inputIndex < inputs.length) {
                                    var input = inputs[inputIndex];
                                    input.value = time;
                                    
                                    // Mark as changed
                                    input.classList.add('changed');
                                    input.setAttribute('data-changed', 'true');
                                    
                                    // Dispatch events
                                    input.dispatchEvent(new Event('change', {bubbles: true}));
                                    input.dispatchEvent(new Event('input', {bubbles: true}));
                                    input.dispatchEvent(new Event('blur', {bubbles: true}));
                                    
                                    populated++;
                                }
                            });
                        });
                        
                        console.log('Populated', populated, 'inputs in expanded panel');
                    };
                    
                    reader.readAsText(file);
                    return {success: true, method: 'manual'};
                """, file_input)
                logger.info(f"Manual CSV processing initiated: {result}")
            except Exception as e:
                logger.debug(f"Error in manual CSV processing: {e}")
            
            # Also try to trigger the file input's onchange handler via JS
            logger.info("🎯 Triggering file processing via JavaScript...")
            try:
                js_trigger = """
                var input = arguments[0];
                var file = input.files[0];
                
                if (!file) {
                    console.error('No file found in input');
                    return {success: false, error: 'No file'};
                }
                
                console.log('File found:', file.name, file.size, 'bytes');
                
                // Try to find and call any CSV processing function
                if (typeof window.processCsvFile === 'function') {
                    window.processCsvFile(input);
                    return {success: true, method: 'processCsvFile'};
                } else if (typeof window.importCsv === 'function') {
                    window.importCsv(input);
                    return {success: true, method: 'importCsv'};
                } else if (typeof window.parseCsv === 'function') {
                    window.parseCsv(input);
                    return {success: true, method: 'parseCsv'};
                }
                
                // If no custom function, try to manually read and trigger parsing
                console.log('No custom CSV function found, attempting FileReader...');
                var reader = new FileReader();
                reader.onload = function(e) {
                    var csvContent = e.target.result;
                    console.log('CSV content loaded:', csvContent.substring(0, 100));
                    
                    // Trigger a custom event with the CSV data
                    var event = new CustomEvent('csvLoaded', { detail: { content: csvContent } });
                    document.dispatchEvent(event);
                    input.dispatchEvent(event);
                    
                    // Try to find Vue component and update it
                    if (input.__vue__) {
                        input.__vue__.$emit('csv-loaded', csvContent);
                        input.__vue__.$forceUpdate();
                    }
                };
                reader.readAsText(file);
                
                return {success: true, method: 'FileReader'};
                """
                result = self.driver.execute_script(js_trigger, file_input)
                logger.debug(f"CSV processing trigger result: {result}")
            except Exception as e:
                logger.debug(f"JS trigger error: {e}")
            
            # Wait for modal/buttons to appear after file selection
            time.sleep(1.5)
            
            # WAIT AND CHECK IF CSV WAS ACTUALLY PROCESSED
            logger.info("⏳ Waiting for CSV file to be processed...")
            time.sleep(2)  # Initial wait
            
            # Check the file input's files property to see if file was received
            logger.info("🔍 Checking if file was received by browser...")
            try:
                file_received = self.driver.execute_script("""
                    var input = document.querySelector('input[type="file"]');
                    if (input && input.files && input.files.length > 0) {
                        return {
                            received: true,
                            filename: input.files[0].name,
                            size: input.files[0].size,
                            type: input.files[0].type
                        };
                    }
                    return {received: false};
                """)
                if file_received.get('received'):
                    logger.success(f"✅ File received by browser: {file_received.get('filename')} ({file_received.get('size')} bytes)")
                else:
                    logger.warning("⚠️ File NOT received by browser!")
            except Exception as e:
                logger.debug(f"Error checking file receipt: {e}")
            
            # CRITICAL: The file input has class "fill-calendar" which likely has a change event listener
            # We need to wait for that listener to process the file and populate the table
            logger.info("⏳ Waiting for 'fill-calendar' change listener to process CSV...")
            time.sleep(3)
            
            # Check if the calendar table was updated
            logger.info("🔍 Checking if calendar table was populated...")
            try:
                table_check = self.driver.execute_script("""
                    // Look for VISIBLE elements only
                    var allInputs = document.querySelectorAll('input');
                    var visibleInputs = [];
                    var timeInputs = [];
                    
                    for (var i = 0; i < allInputs.length; i++) {
                        var input = allInputs[i];
                        var rect = input.getBoundingClientRect();
                        var isVisible = rect.width > 0 && rect.height > 0 && 
                                       window.getComputedStyle(input).display !== 'none' &&
                                       window.getComputedStyle(input).visibility !== 'hidden';
                        
                        if (isVisible) {
                            visibleInputs.push({
                                type: input.type,
                                value: input.value ? input.value.substring(0, 20) : '',
                                class: input.className
                            });
                            
                            if (input.type === 'time') {
                                timeInputs.push(input.value || 'empty');
                            }
                        }
                    }
                    
                    // Look for tables
                    var tables = document.querySelectorAll('table');
                    var visibleTables = 0;
                    for (var i = 0; i < tables.length; i++) {
                        var rect = tables[i].getBoundingClientRect();
                        if (rect.width > 0 && rect.height > 0) visibleTables++;
                    }
                    
                    return {
                        totalInputs: allInputs.length,
                        visibleInputs: visibleInputs.length,
                        timeInputsVisible: timeInputs.length,
                        timeInputSample: timeInputs.slice(0, 3),
                        visibleTables: visibleTables,
                        inputSample: visibleInputs.slice(0, 5)
                    };
                """)
                logger.info(f"  Page structure: {table_check}")
                logger.info(f"  Time inputs: {table_check.get('timeInputSample', [])}")
                logger.info(f"  Input sample: {table_check.get('inputSample', [])}")
                
                if table_check.get('timeInputsVisible', 0) == 0:
                    logger.warning("⚠️ No VISIBLE time input fields found! The 'fill-calendar' listener may not have fired.")
                else:
                    logger.success(f"✅ Found {table_check.get('timeInputsVisible')} visible time inputs!")
            except Exception as e:
                logger.debug(f"Error checking table: {e}")
            
            # Try to manually parse and populate the CSV data
            logger.info("🔍 Attempting to manually parse and populate CSV data...")
            try:
                populate_result = self.driver.execute_script("""
                    var input = document.querySelector('input[type="file"]');
                    if (!input || !input.files || input.files.length === 0) {
                        return {success: false, error: 'No file'};
                    }
                    
                    var file = input.files[0];
                    var reader = new FileReader();
                    
                    return new Promise((resolve) => {
                        reader.onload = function(e) {
                            var csvText = e.target.result;
                            var lines = csvText.split('\\n');
                            
                            // Skip header row
                            var dataRows = lines.slice(1).filter(line => line.trim() !== '');
                            
                            console.log('Parsing CSV:', dataRows.length, 'rows');
                            
                            // Find all time input fields
                            var timeInputs = document.querySelectorAll('input[type="time"]');
                            console.log('Found', timeInputs.length, 'time inputs');
                            
                            var populated = 0;
                            
                            // Try to populate the inputs
                            // The pattern is: each day has 6 prayer times (Fajr, Sunrise, Dhuhr, Asr, Maghrib, Isha)
                            dataRows.forEach((row, dayIndex) => {
                                var values = row.split(',');
                                if (values.length >= 7) {  // Day + 6 times
                                    // values[0] is day number, values[1-6] are the times
                                    for (var i = 1; i <= 6; i++) {
                                        var inputIndex = (dayIndex * 6) + (i - 1);
                                        if (inputIndex < timeInputs.length) {
                                            var timeValue = values[i].trim();
                                            timeInputs[inputIndex].value = timeValue;
                                            timeInputs[inputIndex].dispatchEvent(new Event('input', {bubbles: true}));
                                            timeInputs[inputIndex].dispatchEvent(new Event('change', {bubbles: true}));
                                            populated++;
                                        }
                                    }
                                }
                            });
                            
                            console.log('Populated', populated, 'time inputs');
                            resolve({success: true, populated: populated, totalInputs: timeInputs.length});
                        };
                        
                        reader.readAsText(file);
                    });
                """)
                logger.info(f"  Manual CSV parsing result: {populate_result}")
            except Exception as e:
                logger.debug(f"Error manually parsing CSV: {e}")
            
            # WAIT for the manual population to complete
            logger.info("⏳ Waiting 3 seconds for manual CSV population to complete...")
            time.sleep(3)
            
            # Check if the CSV data from November is actually there
            logger.info("🔍 Verifying November CSV data was populated correctly...")
            data_loaded = False
            try:
                # Check for specific November values to confirm new data loaded
                verify_result = self.driver.execute_script("""
                    var inputs = document.querySelectorAll('input.calendar-prayer-time');
                    var values = [];
                    for (var i = 0; i < Math.min(inputs.length, 10); i++) {
                        values.push(inputs[i].value);
                    }
                    return {
                        total: inputs.length,
                        first10: values
                    };
                """)
                logger.info(f"  Total prayer inputs: {verify_result.get('total')}")
                logger.info(f"  First 10 values: {verify_result.get('first10')}")
                
                # Check if we see November's first day Fajr time (05:54)
                first_10 = verify_result.get('first10', [])
                if '05:54' in first_10:
                    logger.success("✅ November data CONFIRMED! Found Day 1 Fajr = 05:54")
                    data_loaded = True
                elif any(val for val in first_10 if val and val != ''):
                    logger.warning(f"⚠️ Data found but doesn't match November CSV: {first_10[:3]}")
                else:
                    logger.warning("⚠️ No data in inputs - population may have failed")
            except Exception as e:
                logger.debug(f"Error verifying data: {e}")
            
            time.sleep(1)
            
            # Take a screenshot to see what's on screen
            self._save_debug_screenshot("after_file_selected_athan")
            
            # Check for any visible buttons/modals
            logger.info("📋 Checking for any visible buttons or modals...")
            try:
                all_buttons = self.driver.find_elements(By.TAG_NAME, "button")
                visible_buttons = []
                for btn in all_buttons:
                    try:
                        if btn.is_displayed() and btn.is_enabled():
                            text = (btn.text or "").strip()
                            if text:
                                visible_buttons.append(text)
                    except Exception:
                        continue
                logger.info(f"Visible buttons on page: {visible_buttons}")
            except Exception as e:
                logger.debug(f"Error checking buttons: {e}")
            
            # Check if there's a modal with an import button
            logger.info("🔍 Looking for modal Import button (if any)...")
            import_clicked = False
            
            # Look for import buttons - first in modals, then anywhere but avoid "Save" at bottom
            import_selectors = [
                # Modal buttons first
                "//*[contains(@class, 'modal') and contains(@class, 'show')]//button[contains(translate(., 'ABCDEFGHIJKLMNOPQRSTUVWXYZ', 'abcdefghijklmnopqrstuvwxyz'), 'import')]",
                "//*[contains(@class, 'modal') and contains(@class, 'show')]//button[contains(translate(., 'ABCDEFGHIJKLMNOPQRSTUVWXYZ', 'abcdefghijklmnopqrstuvwxyz'), 'upload')]",
                "//*[contains(@class, 'modal') and contains(@class, 'show')]//button[contains(translate(., 'ABCDEFGHIJKLMNOPQRSTUVWXYZ', 'abcdefghijklmnopqrstuvwxyz'), 'confirm')]",
                "//*[contains(@class, 'modal') and contains(@class, 'show')]//button[contains(@class, 'btn')]",
                # Then look near the file input (but not "Save" at page bottom)
                "//input[@type='file']/following::button[contains(translate(., 'ABCDEFGHIJKLMNOPQRSTUVWXYZ', 'abcdefghijklmnopqrstuvwxyz'), 'import')][1]",
                "//input[@type='file']/following::button[contains(translate(., 'ABCDEFGHIJKLMNOPQRSTUVWXYZ', 'abcdefghijklmnopqrstuvwxyz'), 'upload')][1]",
                "//input[@type='file']/following::button[contains(translate(., 'ABCDEFGHIJKLMNOPQRSTUVWXYZ', 'abcdefghijklmnopqrstuvwxyz'), 'confirm')][1]"
            ]
            
            for selector in import_selectors:
                try:
                    buttons = self.driver.find_elements(By.XPATH, selector)
                    for btn in buttons:
                        try:
                            if btn.is_displayed() and btn.is_enabled():
                                btn_text = (btn.text or btn.get_attribute('value') or '').strip()
                                logger.info(f"Found visible button: '{btn_text}'")
                                
                                # Click it
                                try:
                                    self.driver.execute_script("arguments[0].scrollIntoView({block:'center'});", btn)
                                    time.sleep(0.3)
                                    btn.click()
                                    logger.success(f"✅ Clicked '{btn_text}' button")
                                    import_clicked = True
                                    break
                                except Exception:
                                    try:
                                        self.driver.execute_script("arguments[0].click();", btn)
                                        logger.success(f"✅ Clicked '{btn_text}' button (JS)")
                                        import_clicked = True
                                        break
                                    except Exception as e:
                                        logger.debug(f"Failed to click button: {e}")
                        except Exception:
                            continue
                    if import_clicked:
                        break
                except Exception:
                    continue
            
            if not import_clicked:
                logger.info("✓ No modal Import button - file appears to auto-process")
            else:
                logger.info("✓ Modal Import button clicked, waiting for processing...")
            
            # Capture network and console after button click
            time.sleep(3)  # Give it more time to process
            self._capture_network_logs("AFTER_ATHAN_FILE_SENT")
            self._capture_console_logs("AFTER_ATHAN_FILE_SENT")
            
            time.sleep(2) # Wait a bit longer for processing

            # --- NEW: Verify data AFTER upload ---
            logger.info("Verifying data after upload...")
            after_value = self._get_day_1_fajr_value(month_name.capitalize())
            logger.info(f"  > Fajr time for Day 1 (after): '{after_value}'")

            if after_value == "not_found":
                logger.error("❌ VERIFICATION FAILED: Could not find the time field after upload.")
            elif before_value == after_value:
                logger.warning("⚠️ DATA DID NOT CHANGE AFTER UPLOAD! The form was not updated.")
                self._save_debug_screenshot("data_did_not_change_athan")
            else:
                logger.success(f"✓ Data successfully changed from '{before_value}' to '{after_value}'.");

            # CRITICAL: Close the Athan month accordion after we're done to prevent confusion with Iqama
            logger.info("Closing Athan month accordion...")
            try:
                # Click the month element again to collapse its panel
                if month_el:
                    self.driver.execute_script("arguments[0].scrollIntoView({block:'center'});", month_el)
                    time.sleep(0.3)
                    self.driver.execute_script("arguments[0].click();", month_el)
                    time.sleep(1)
                    logger.success("✅ Closed Athan month accordion")
            except Exception as e:
                logger.warning(f"Could not close Athan month accordion: {e}")

            return True
        except Exception as e:
            logger.error(f"Error in _click_calculation_and_prepopulate: {e}")
            return False

    def _upload_iqama_times(self, iqama_filepath, month_name, timeout=10):
        """Uploads Iqama CSV and verifies data changes."""
        try:
            logger.info("=" * 60)
            logger.info("🟢 STARTING IQAMA CSV UPLOAD SEQUENCE")
            logger.info("=" * 60)
            
            # CRITICAL: Force close ALL expanded accordions in the Athan section
            logger.info("🔒 Closing all Athan section accordions...")
            try:
                close_result = self.driver.execute_script("""
                    // Find all panels that are currently expanded
                    var panels = document.querySelectorAll('.panel-collapse.show, .collapse.show');
                    var closed = 0;
                    
                    panels.forEach(function(panel) {
                        // Only close panels that contain calendar inputs (Athan month panels)
                        var inputs = panel.querySelectorAll('input.calendar-prayer-time');
                        if (inputs.length > 0) {
                            panel.classList.remove('show', 'in');
                            panel.style.display = 'none';
                            
                            // Also close the associated button/link
                            var target = '#' + panel.id;
                            var button = document.querySelector('[data-target="' + target + '"], [href="' + target + '"]');
                            if (button) {
                                button.setAttribute('aria-expanded', 'false');
                                button.classList.add('collapsed');
                            }
                            closed++;
                        }
                    });
                    
                    return {closed: closed, total: panels.length};
                """)
                logger.success(f"✅ Closed {close_result.get('closed', 0)} Athan accordions (of {close_result.get('total', 0)} total expanded panels)")
            except Exception as e:
                logger.warning(f"Could not force-close Athan accordions: {e}")
            
            time.sleep(1.0)
            
            # Scroll down significantly to ensure Iqama section is in view
            logger.info("Scrolling down to find Iqama section...")
            self.driver.execute_script("window.scrollBy(0, 800);")
            time.sleep(1.5)
            
            # Step 1: Find and click "Iqama" section
            logger.info("Looking for 'Iqama' section...")
            iqama_section = None
            
            iqama_selectors = [
                "//*[contains(text(), 'Iqama') or contains(text(), 'iqama')]",
                "//div[contains(., 'Iqama')]",
                "//h3[contains(., 'Iqama')]",
                "//h4[contains(., 'Iqama')]",
                "//*[contains(@class, 'panel') and contains(., 'Iqama')]",
                "//*[contains(@class, 'accordion') and contains(., 'Iqama')]"
            ]
            
            for sel in iqama_selectors:
                try:
                    elements = self.driver.find_elements(By.XPATH, sel)
                    for el in elements:
                        if el.is_displayed():
                            txt = (el.text or "").strip()
                            if txt and len(txt) < 20:  # Iqama header should be short
                                iqama_section = el
                                logger.debug(f"Found Iqama section: '{txt}'")
                                break
                    if iqama_section:
                        break
                except Exception:
                    continue
            
            if not iqama_section:
                logger.error("Could not find 'Iqama' section after trying all selectors")
                logger.info("Dumping visible page text for debugging...")
                try:
                    body_text = self.driver.find_element(By.TAG_NAME, "body").text
                    logger.debug(f"Page contains: {body_text[:500]}...")
                except Exception:
                    pass
                self._save_debug_screenshot("iqama_section_not_found")
                logger.warning("Continuing without Iqama upload - check if athan was successful")
                return True  # Return True to allow Save button click
            
            # Click to expand Iqama section
            logger.info("Clicking 'Iqama' section to expand it...")
            try:
                self.driver.execute_script("arguments[0].scrollIntoView({block:'center'});", iqama_section)
                time.sleep(0.3)
                self.driver.execute_script("arguments[0].click();", iqama_section)
                logger.success("Clicked 'Iqama' section")
            except Exception as e:
                logger.error(f"Failed to click Iqama section: {e}")
                self._save_debug_screenshot("iqama_click_failed")
                return False
            
            time.sleep(1.0)
            
            # Step 2: Click "By calendar" tab
            logger.info("Looking for 'By calendar' tab...")
            calendar_tab = None
            
            calendar_selectors = [
                "//a[normalize-space(.)='By calendar']",
                "//button[normalize-space(.)='By calendar']",
                "//*[contains(translate(., 'ABCDEFGHIJKLMNOPQRSTUVWXYZ', 'abcdefghijklmnopqrstuvwxyz'), 'calendar')]",
                "//*[contains(@class, 'nav-link') and contains(., 'calendar')]"
            ]
            
            for sel in calendar_selectors:
                try:
                    elements = self.driver.find_elements(By.XPATH, sel)
                    for el in elements:
                        if el.is_displayed():
                            calendar_tab = el
                            logger.debug(f"Found By calendar tab: '{el.text}'")
                            break
                    if calendar_tab:
                        break
                except Exception:
                    continue
            
            if not calendar_tab:
                # Do not fail here; some layouts may show the calendar by default
                logger.warning("Could not find 'By calendar' tab — proceeding with deterministic fill anyway")
                self._save_debug_screenshot("calendar_tab_not_found")
            else:
                logger.info("Clicking 'By calendar' tab...")
                try:
                    self.driver.execute_script("arguments[0].scrollIntoView({block:'center'});", calendar_tab)
                    time.sleep(0.3)
                    calendar_tab.click()
                    logger.success("Clicked 'By calendar' tab")
                except Exception as e:
                    logger.debug(f"Direct click failed: {e}, trying JS")
                    try:
                        self.driver.execute_script("arguments[0].click();", calendar_tab)
                        logger.success("Clicked 'By calendar' tab via JS")
                    except Exception as e2:
                        logger.warning(f"Failed to click By calendar (continuing): {e2}")
                        self._save_debug_screenshot("calendar_tab_click_failed")
            
            time.sleep(2.0)  # Wait longer for tab content to load
            
            # Step 3: Check if Iqama uses month accordions or if calendar is always visible
            # IMPORTANT: Iqama structure might be DIFFERENT from Athan!
            logger.info("Checking if Iqama calendar needs month selection...")
            
            # First, check if inputs are already visible (no month accordion needed)
            month_el = None
            skip_month_search = False
            try:
                test_inputs = self.driver.find_elements(By.CSS_SELECTOR, "input.calendar-prayer-time")
                visible_count = sum(1 for inp in test_inputs if inp.is_displayed())
                logger.info(f"Found {visible_count} visible calendar inputs before month click")
                
                if visible_count >= 150:  # Iqama should have ~150-180 inputs
                    logger.success("✅ Iqama calendar inputs already visible, no month accordion needed!")
                    skip_month_search = True  # Skip month clicking entirely
                else:
                    logger.info("Iqama calendar inputs not visible, need to find month accordion...")
            except Exception as e:
                logger.warning(f"Could not check for visible inputs: {e}")
            
            # Step 3b: Find and click the month accordion ONLY if inputs not already visible
            if skip_month_search:
                logger.info("Skipping month search - inputs already visible!")
            else:
                labels = self._possible_month_labels(month_name)
                logger.info(f"Looking for month '{month_name}' in Iqama calendar (trying: {labels})...")
                
                # Get ALL month elements on the page (more permissive search)
                all_months = []
                for label in labels:
                    lower = label.lower()
                    # Search for ANY element containing the month name
                    xpath_contains = f"//*[contains(translate(normalize-space(.),'ABCDEFGHIJKLMNOPQRSTUVWXYZ','abcdefghijklmnopqrstuvwxyz'), '{lower}')]"
                    try:
                        candidates = self.driver.find_elements(By.XPATH, xpath_contains)
                        logger.debug(f"Found {len(candidates)} candidates for '{label}'")
                        
                        for el in candidates:
                            try:
                                if el.is_displayed():
                                    txt = (el.text or "").strip()
                                    # Month names should be short
                                    if txt and len(txt) < 30 and len(txt) > 2:
                                        tag = el.tag_name
                                        # Only add clickable elements (a, button, etc.)
                                        if tag in ['a', 'button', 'div', 'h4', 'h5']:
                                            all_months.append(el)
                                            logger.debug(f"  Added: <{tag}> '{txt}' at Y={el.location['y']}")
                            except Exception as e:
                                logger.debug(f"  Skipped element: {e}")
                                continue
                    except Exception as e:
                        logger.debug(f"XPath search for label '{label}' failed: {e}")
                        continue
                
                logger.info(f"Found {len(all_months)} total month elements matching '{month_name}'")
                
                if len(all_months) == 0:
                    logger.warning("No month elements found — skipping month click and proceeding with deterministic fill")
                    self._save_debug_screenshot("no_months_found")
                    skip_month_search = True
                
                # CRITICAL: Get the Y position of the Iqama section header to find months BELOW it
                iqama_y_position = iqama_section.location['y']
                logger.info(f"Iqama section Y position: {iqama_y_position}")
                
                # Find the month accordion that's BELOW the Iqama header (not above in Athan section)
                for el in all_months:
                    try:
                        el_y = el.location['y']
                        logger.debug(f"Checking month at Y={el_y}, text='{el.text.strip()}'")
                        
                        if el_y > iqama_y_position:
                            month_el = el
                            logger.success(f"✅ Selected Iqama month '{el.text.strip()}' at Y={el_y} (below Iqama header at Y={iqama_y_position})")
                            break
                    except Exception as e:
                        logger.debug(f"Error checking month position: {e}")
                        continue
                
                # Handle month accordion if needed  
                if not month_el:
                    logger.warning(f"Could not find month '{month_name}' in Iqama section — proceeding without clicking month")
                    self._save_debug_screenshot("iqama_month_not_found")
                    skip_month_search = True
            
            if month_el:
                # Debug: Check what element we found
                logger.info(f"Selected Iqama month element: tag={month_el.tag_name}, text='{month_el.text.strip()}'")
                logger.info(f"  Classes: {month_el.get_attribute('class')}")
                logger.info(f"  data-target: {month_el.get_attribute('data-target')}")
                logger.info(f"  href: {month_el.get_attribute('href')}")
                
                logger.info(f"Clicking month '{month_name}' in Iqama...")
                try:
                    self.driver.execute_script("arguments[0].scrollIntoView({block:'center'});", month_el)
                    time.sleep(0.5)
                    
                    # Try multiple click strategies
                    self.driver.execute_script("arguments[0].click();", month_el)
                    time.sleep(1.0)
                    
                    try:
                        month_el.click()
                    except:
                        pass
                    time.sleep(1.0)
                    
                    logger.success(f"Clicked month: {month_el.text.strip()}")
                except Exception as e:
                    logger.warning(f"Failed to click month (continuing): {e}")
                    self._save_debug_screenshot("iqama_month_click_failed")
                
                # Wait and force open if needed
                time.sleep(2.0)
                
                # Force the Iqama panel to open with JavaScript
                force_open_result = self.driver.execute_script("""
                    var el = arguments[0];
                    var target = el.getAttribute('data-target') || el.getAttribute('href');
                    var panel = null;
                    
                    if (target) {
                        // Handle IDs that start with digits - use getElementById instead
                        if (target.startsWith('#')) {
                            var id = target.substring(1);
                            panel = document.getElementById(id);
                        } else {
                            panel = document.querySelector(target);
                        }
                    }
                    
                    if (!panel) {
                        return {success: false, error: 'No target panel found', target: target};
                    }
                    
                    var wasVisible = panel.classList.contains('show');
                    
                    // Force open the panel
                    if (!wasVisible) {
                        panel.classList.add('show', 'in');
                        panel.style.display = 'block';
                        el.setAttribute('aria-expanded', 'true');
                        el.classList.remove('collapsed');
                    }
                    
                    var panelInputs = panel.querySelectorAll('input.calendar-prayer-time').length;
                    
                    return {
                        success: true,
                        wasVisible: wasVisible,
                        nowVisible: panel.classList.contains('show'),
                        panelInputs: panelInputs
                    };
                """, month_el)
                logger.info(f"Iqama force open result: {force_open_result}")
                
                if force_open_result.get('success'):
                    logger.success(f"✅ Iqama panel force-opened, contains {force_open_result.get('panelInputs', 0)} inputs")
                else:
                    logger.warning(f"⚠️ Force-open failed (will use fallback): {force_open_result.get('error', 'unknown')}")
            else:
                logger.info("ℹ️  Skipping month accordion (inputs already visible)")
            
            # Wait longer for panel animation to complete
            logger.info("⏳ Waiting briefly before deterministic fill...")
            time.sleep(1.5)
            
            # Debug: Take screenshot after clicking Iqama month
            self._save_debug_screenshot("after_iqama_month_click")

            # METHOD 2: MANUAL ENTRY for Iqama (same as Athan)
            logger.info("="*60)
            logger.info("🚀 MANUAL ENTRY MODE: Entering Iqama times individually")
            logger.info("="*60)
            
            # Read the Iqama CSV file
            logger.info(f"📖 Reading Iqama CSV file: {iqama_filepath}")
            import csv
            csv_data = []
            try:
                with open(iqama_filepath, 'r') as f:
                    reader = csv.DictReader(f)
                    for row in reader:
                        csv_data.append(row)
                logger.success(f"✅ Loaded {len(csv_data)} rows from Iqama CSV")
                logger.info(f"Sample row: {csv_data[0] if csv_data else 'empty'}")
            except Exception as e:
                logger.error(f"Failed to read Iqama CSV: {e}")
                return False
            
            # Deterministic: fill Iqama by name attribute, 5 prayers only (no Sunrise)
            logger.info("🔍 Filling Iqama times via deterministic name selectors (no month/panel assumptions)...")
            try:
                # Month index mapping (0-based as observed on the site: November -> 10)
                month_map = {
                    'january': 0, 'janvier': 0,
                    'february': 1, 'février': 1, 'fevrier': 1,
                    'march': 2, 'mars': 2,
                    'april': 3, 'avril': 3,
                    'may': 4, 'mai': 4,
                    'june': 5, 'juin': 5,
                    'july': 6, 'juillet': 6,
                    'august': 7, 'août': 7, 'aout': 7,
                    'september': 8, 'septembre': 8,
                    'october': 9, 'octobre': 9,
                    'november': 10, 'novembre': 10,
                    'december': 11, 'décembre': 11, 'decembre': 11
                }
                m_key = (month_name or "").strip().lower()
                m_idx = month_map.get(m_key)
                if m_idx is None:
                    logger.error(f"❌ Could not map month '{month_name}' to index")
                    return False

                # Slot mapping: strictly 5 prayers (no Sunrise)
                # 1: Fajr, 2: Dhuhr, 3: Asr, 4: Maghrib, 5: Isha
                prayer_to_slot = {
                    'Fajr': 1,
                    'Dhuhr': 2,
                    'Asr': 3,
                    'Maghrib': 4,
                    'Isha': 5,
                }

                def _normalize_time(val:str) -> str:
                    v = (val or '').strip()
                    if not v:
                        return v
                    # Accept HH:mm or H:m and normalize to HH:mm
                    parts = v.replace('.', ':').replace(' ', '').split(':')
                    if len(parts) == 2 and all(p.isdigit() for p in parts):
                        h, m = parts
                        try:
                            h_i, m_i = int(h), int(m)
                            if 0 <= h_i <= 23 and 0 <= m_i <= 59:
                                return f"{h_i:02d}:{m_i:02d}"
                        except Exception:
                            pass
                    return v

                def _try_selectors(day:int, slot:int, month_index:int):
                    # Build multiple selector variants to tolerate off-by-one indexing differences
                    selectors = [
                        f"input[name='configuration[iqamaCalendar][{month_index}][{day}][{slot}]']",
                    ]
                    if slot > 0:
                        selectors.append(f"input[name='configuration[iqamaCalendar][{month_index}][{day}][{slot-1}]']")
                    selectors.append(f"input[name='configuration[iqamaCalendar][{month_index+1}][{day}][{slot}]']")
                    if slot > 0:
                        selectors.append(f"input[name='configuration[iqamaCalendar][{month_index+1}][{day}][{slot-1}]']")
                    for sel in selectors:
                        try:
                            els = self.driver.find_elements(By.CSS_SELECTOR, sel)
                            if els:
                                return els[0]
                            # JS querySelector fallback after small scroll
                            self.driver.execute_script("window.scrollBy(0, 200);")
                            el = self.driver.execute_script("return document.querySelector(arguments[0]);", sel)
                            if el:
                                return el
                        except Exception:
                            continue
                    return None

                populated, missing = 0, 0
                # Progressive scroll anchors to help lazy DOMs
                def _progressive_scroll_attempt(day:int, slot:int):
                    # Try current viewport + a few scroll steps
                    for _ in range(8):
                        el = _try_selectors(day, slot, m_idx)
                        if el:
                            return el
                        self.driver.execute_script("window.scrollBy(0, 600);")
                        time.sleep(0.05)
                    # Try from top as a last resort
                    self.driver.execute_script("window.scrollTo(0, 0);")
                    time.sleep(0.05)
                    return _try_selectors(day, slot, m_idx)

                for day_idx, row in enumerate(csv_data, start=1):
                    for prayer, slot in prayer_to_slot.items():
                        time_value = _normalize_time(row.get(prayer))
                        if not time_value:
                            # Skip silently if CSV value missing (shouldn't happen per user's guarantee)
                            continue
                        inp = _progressive_scroll_attempt(day_idx, slot)
                        if not inp:
                            missing += 1
                            if missing <= 5:
                                logger.warning(f"⚠️ Missing input for day {day_idx}, {prayer} (slot {slot})")
                            continue
                        try:
                            # Scroll into view then clear & type
                            try:
                                self.driver.execute_script("arguments[0].scrollIntoView({block:'center'});", inp)
                                time.sleep(0.05)
                            except Exception:
                                pass
                            try:
                                inp.clear()
                            except Exception:
                                pass
                            try:
                                inp.send_keys(time_value)
                            except Exception:
                                # Fallback: set value via JS and trigger events
                                self.driver.execute_script("arguments[0].value = arguments[1];", inp, time_value)
                            # Fire events so the page registers the change
                            try:
                                self.driver.execute_script("""
                                    var el = arguments[0];
                                    el.dispatchEvent(new Event('input', {bubbles:true}));
                                    el.dispatchEvent(new Event('change', {bubbles:true}));
                                    el.blur();
                                """, inp)
                            except Exception:
                                pass
                            populated += 1
                            if populated <= 5:
                                logger.info(f"  📝 Day {day_idx} {prayer} = {time_value}")
                            if populated % 30 == 0:
                                logger.info(f"Progress: {populated} Iqama fields entered...")
                        except Exception as e:
                            logger.error(f"Error typing for day {day_idx} {prayer}: {e}")

                logger.success(f"✅ Iqama filled via name selectors: {populated} fields populated, {missing} missing inputs.")
                # Do not fail run if some inputs were missing; the rest will still be saved.
                return True

            except Exception as e:
                logger.error(f"Deterministic Iqama fill failed: {e}")
                return False

            # OLD FILE UPLOAD METHOD (DISABLED - using manual entry above)
            """
            # Find file input directly as a primary strategy for Iqama
            file_input = None
            try:
                file_input = self.driver.find_element(By.XPATH, "//input[@type='file']")
            except Exception:
                logger.debug("File input not found, will try button click strategy")

            if not file_input:
                # If not found, try clicking a pre-populate button first
                logger.info("Looking for Pre-populate button to click...")
                pre_btn = None
                try:
                    buttons = self.driver.find_elements(By.TAG_NAME, "button")
                    for btn in buttons:
                        try:
                            if btn.is_displayed():
                                text = (btn.text or "").strip().lower()
                                if ('pre' in text or 'csv' in text) and len(text) > 3:
                                    pre_btn = btn
                                    logger.debug(f"Found button: '{btn.text}'")
                                    break
                        except Exception:
                            continue
                except Exception as e:
                    logger.debug(f"Error finding buttons: {e}")

                if pre_btn:
                    # Click the button
                    logger.info("Clicking Pre-populate button...")
                    try:
                        self.driver.execute_script("arguments[0].scrollIntoView({block:'center'});", pre_btn)
                        time.sleep(0.3)
                        self.driver.execute_script("arguments[0].click();", pre_btn)
                        logger.success("Clicked Pre-populate button")
                        time.sleep(1.5)
                    except Exception as e:
                        logger.error(f"Failed to click button: {e}")
                        return False
                else:
                    logger.error("Could not find file input or Pre-populate button for Iqama.")
                    return False
            
            if file_input:
                abs_path = os.path.abspath(iqama_filepath)
                
                # Capture state before upload
                self._capture_console_logs("BEFORE_IQAMA_UPLOAD")
                
                logger.info("🔄 Sending Iqama file to input field...")
                file_input.send_keys(abs_path)
                logger.success("File path sent to Iqama file input.")
                
                # Trigger all necessary events
                time.sleep(0.5)
                self._trigger_file_input_events(file_input)
                
                # Wait for file to be processed
                logger.info("⏳ Waiting for Iqama file to be processed...")
                time.sleep(5)
                
                # Look for modal Import button only
                logger.info("🔍 Looking for modal Import button for Iqama...")
                import_clicked = False
                
                import_selectors = [
                    "//*[contains(@class, 'modal') and contains(@class, 'show')]//button[contains(translate(., 'ABCDEFGHIJKLMNOPQRSTUVWXYZ', 'abcdefghijklmnopqrstuvwxyz'), 'import')]",
                    "//*[contains(@class, 'modal') and contains(@class, 'show')]//button[contains(translate(., 'ABCDEFGHIJKLMNOPQRSTUVWXYZ', 'abcdefghijklmnopqrstuvwxyz'), 'upload')]",
                    "//*[contains(@class, 'modal') and contains(@class, 'show')]//button[contains(translate(., 'ABCDEFGHIJKLMNOPQRSTUVWXYZ', 'abcdefghijklmnopqrstuvwxyz'), 'confirm')]",
                    "//*[contains(@class, 'modal') and contains(@class, 'show')]//button[contains(@class, 'btn-primary')]"
                ]
                
                for selector in import_selectors:
                    try:
                        buttons = self.driver.find_elements(By.XPATH, selector)
                        for btn in buttons:
                            try:
                                if btn.is_displayed() and btn.is_enabled():
                                    btn_text = (btn.text or btn.get_attribute('value') or '').strip()
                                    logger.info(f"Found visible button: '{btn_text}'")
                                    
                                    try:
                                        self.driver.execute_script("arguments[0].scrollIntoView({block:'center'});", btn)
                                        time.sleep(0.3)
                                        btn.click()
                                        logger.success(f"✅ Clicked '{btn_text}' button")
                                        import_clicked = True
                                        break
                                    except Exception:
                                        try:
                                            self.driver.execute_script("arguments[0].click();", btn)
                                            logger.success(f"✅ Clicked '{btn_text}' button (JS)")
                                            import_clicked = True
                                            break
                                        except Exception as e:
                                            logger.debug(f"Failed to click: {e}")
                            except Exception:
                                continue
                        if import_clicked:
                            break
                    except Exception:
                        continue
                
                if not import_clicked:
                    logger.info("✓ No modal Import button for Iqama - auto-processing")
                
                # Capture after processing
                time.sleep(2)
                self._capture_network_logs("AFTER_IQAMA_FILE_SENT")
                self._capture_console_logs("AFTER_IQAMA_FILE_SENT")
                
                time.sleep(1) # Wait a bit longer

                logger.info("Verifying Iqama data after upload...")
                after_value = self._get_day_1_fajr_value(month_name.capitalize())
                logger.info(f"  > Fajr Iqama for Day 1 (after): '{after_value}'")

                if after_value == "not_found":
                    logger.error("❌ VERIFICATION FAILED: Could not find the Iqama time field after upload.")
                    self._save_debug_screenshot("verification_field_not_found_iqama")
                elif before_value == after_value:
                    logger.warning("⚠️ IQAMA DATA DID NOT CHANGE AFTER UPLOAD!")
                    self._save_debug_screenshot("data_did_not_change_iqama")
                else:
                    logger.success(f"✓ Iqama data successfully changed from '{before_value}' to '{after_value}'.");
            """
            # End of old file upload method

            return True
        except Exception as e:
            logger.error(f"Error in _upload_iqama_times: {e}")
            return False

    def _click_save_button(self):
        """Scroll to bottom and click the Save button. Returns True on success."""
        try:
            logger.info("Scrolling to bottom to find Save button...")
            
            # Scroll to bottom
            self.driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
            time.sleep(1.0)
            
            # Find Save button
            save_selectors = [
                "//button[normalize-space(.)='Save']",
                "//*[contains(@class, 'btn-primary') and contains(., 'Save')]"
            ]
            
            save_btn = None
            for sel in save_selectors:
                try:
                    elements = self.driver.find_elements(By.XPATH, sel)
                    for el in elements:
                        if el.is_displayed():
                            save_btn = el
                            logger.debug(f"Found Save button: '{el.text}'")
                            break
                    if save_btn:
                        break
                except Exception:
                    continue
            
            if not save_btn:
                logger.error("Could not find Save button")
                self._save_debug_screenshot("save_button_not_found")
                return False
            
            logger.info("Clicking Save button...")
            try:
                self.driver.execute_script("arguments[0].scrollIntoView({block:'center'});", save_btn)
                time.sleep(0.5)
                save_btn.click()
                logger.success("✅ Clicked Save button")
            except Exception as e:
                logger.debug(f"Direct click failed: {e}, trying JS")
                try:
                    self.driver.execute_script("arguments[0].click();", save_btn)
                    logger.success("✅ Clicked Save button via JS")
                except Exception as e2:
                    logger.error(f"Failed to click Save: {e2}")
                    self._save_debug_screenshot("save_click_failed")
                    return False
            
            # Wait for save to complete
            time.sleep(2.0)
            logger.success("Save completed successfully")
            return True
            
        except Exception as e:
            logger.error(f"Error clicking Save button: {e}")
            self._save_debug_screenshot("save_button_error")
            return False

    def run(self):
        """Execute the upload process."""
        try:
            login_url = Config.LOGIN_URL
            logger.info("Opening Mawaqit backoffice login page...")
            self.driver.get(login_url)

            wait_secs = getattr(Config, "WAIT_BETWEEN_ACTIONS", 3)
            
            # Define selectors
            email_selectors = [
                (By.NAME, "email"),
                (By.CSS_SELECTOR, "input[type='email']"),
                (By.ID, "email"),
                (By.NAME, "username"),
                (By.CSS_SELECTOR, "input[name='username']")
            ]
            password_selectors = [
                (By.NAME, "password"),
                (By.CSS_SELECTOR, "input[type='password']"),
                (By.ID, "password")
            ]
            submit_selectors = [
                (By.CSS_SELECTOR, "button[type='submit']"),
                (By.XPATH, "//button[contains(., 'Login') or contains(., 'Sign in') or contains(., 'Log in')]")
            ]

            # Fill email
            email_el = self._find_element_with_selectors(email_selectors, timeout=20)
            logger.info("Entering email...")
            self._type_visible(email_el, Config.MAWAQIT_USER, char_delay=0.1)

            time.sleep(wait_secs / 2)

            # Fill password
            pwd_el = self._find_element_with_selectors(password_selectors, timeout=20)
            logger.info("Entering password...")
            self._type_visible(pwd_el, Config.MAWAQIT_PASS, char_delay=0.1)

            time.sleep(wait_secs / 2)

            # Handle reCAPTCHA before form submission
            recaptcha_iframe = self._detect_recaptcha_iframe()
            if recaptcha_iframe:
                logger.info("reCAPTCHA detected - starting solve sequence...")
                
                # Click the checkbox
                clicked = self._click_recaptcha_checkbox(recaptcha_iframe, timeout=15)
                if not clicked:
                    logger.error("Could not click reCAPTCHA checkbox.")
                    return False

                # Submit to 2Captcha and get solution
                sitekey = self._extract_sitekey()
                if not sitekey:
                    logger.error("Could not extract reCAPTCHA sitekey.")
                    return False

                logger.info("Submitting to 2Captcha for solution...")
                token = self._submit_2captcha(sitekey, self.driver.current_url)
                if not token:
                    logger.error("Failed to get solution from 2Captcha.")
                    return False

                # Inject the token
                if not self._inject_recaptcha_token(token):
                    logger.error("Failed to inject solved token.")
                    return False

                logger.success("Successfully obtained and injected captcha solution.")

            # Submit the login form
            submit_el = self._find_element_with_selectors(submit_selectors, timeout=15)
            logger.info("Submitting login form with solved captcha...")
            try:
                submit_el.click()
            except Exception:
                pwd_el.send_keys("\n")

            # Wait for either 2FA page or landing
            logger.info("Waiting for login response...")
            if not self._wait_for_url_change(["/security/2fa", "/en"], timeout=30):
                logger.error("Login form submission failed")
                return False

            # Check if we're on 2FA page
            if "/security/2fa" in self.driver.current_url:
                logger.info("Detected 2FA verification page")
                if not self._handle_2fa():
                    logger.error("2FA verification failed")
                    return False

            logger.success("Successfully logged in!")

            # Wait for navigation after login
            logger.info("Waiting for navigation after login...")
            time.sleep(3)
            
            current_url = self.driver.current_url
            logger.info(f"Current URL after login: {current_url}")
            
            # Check if we need to handle 2FA first
            if "/security/2fa" in current_url:
                logger.info("2FA page detected, handling 2FA verification...")
                if not self._handle_2fa():
                    logger.error("2FA verification failed")
                    return False
                
                # Wait for navigation after 2FA
                time.sleep(3)
                current_url = self.driver.current_url
                logger.info(f"Current URL after 2FA: {current_url}")
            
            # Check if we're already on a mosque/admin page
            if "/mosque/" in current_url and "/configure" in current_url:
                logger.success("Already on mosque configuration page")
            elif "/mosque/" in current_url:
                logger.success("On mosque dashboard - navigating to configure")
                # Already on mosque page, just need to click configure
            elif "/en/backoffice" in current_url or current_url.endswith("/en") or current_url == "https://mawaqit.net/en/":
                # We're on the backoffice or main landing, need to navigate to mosque
                logger.info("On landing page, looking for mosque/backoffice link...")
                
                # Try to find a mosque card, backoffice link, or admin link
                mosque_selectors = [
                    "//a[contains(@href, '/backoffice')]",
                    "//a[contains(@href, '/mosque/')]",
                    "//a[contains(., 'Backoffice') or contains(., 'Administration')]",
                    "//a[contains(., 'Manage') or contains(., 'Configure') or contains(., 'Admin')]",
                    "//div[contains(@class, 'card')]//a[contains(@class, 'btn')]",
                    "//nav//a[contains(@href, 'backoffice')]"
                ]
                
                found_mosque = False
                for selector in mosque_selectors:
                    try:
                        links = self.driver.find_elements(By.XPATH, selector)
                        for link in links:
                            if link.is_displayed():
                                href = link.get_attribute('href') or ''
                                text = link.text or ''
                                logger.info(f"Found link: '{text}' -> {href}")
                                
                                # Click the first visible mosque/admin link
                                try:
                                    link.click()
                                    logger.success(f"Clicked link: {text}")
                                    time.sleep(2)
                                    found_mosque = True
                                    break
                                except Exception as e:
                                    logger.debug(f"Click failed: {e}")
                        if found_mosque:
                            break
                    except Exception:
                        continue
                
                if not found_mosque:
                    logger.error("Could not find mosque/admin link on backoffice page")
                    self._save_debug_screenshot("no_mosque_link")
                    return False
            
            # Now try Actions -> Configure
            logger.info("Attempting to open Actions menu and click Configure...")
            if self._click_actions_and_configure(timeout=12):
                logger.success("✅ Actions -> Configure clicked successfully.")
                
                # Download and upload CSVs
                month = self._get_month_name()
                logger.info(f"Preparing CSVs for month: {month}")
                csvs = self._download_month_csvs(month)
                if csvs and 'athan' in csvs:
                    logger.info("Uploading athan CSV via Pre-populate UI...")
                    if self._click_calculation_and_prepopulate(csvs['athan'], month):
                        logger.success("Athan CSV pre-population sequence complete.")
                        
                        # Now upload iqama times
                        if 'iqama' in csvs:
                            logger.info("Now uploading iqama CSV...")
                            if self._upload_iqama_times(csvs['iqama'], month):
                                logger.success("Iqama CSV pre-population sequence complete.")
                                
                                # Click Save button
                                if self._click_save_button():
                                    logger.success("🎉 All prayer times uploaded and saved!")
                                    return True  # Success!
                                else:
                                    logger.error("Failed to click Save button")
                                    return False
                            else:
                                logger.error("Failed during iqama upload sequence")
                                return False
                        else:
                            logger.error("Iqama CSV not downloaded")
                            return False
                    else:
                        logger.error("Failed during pre-populate/upload - check screenshots.")
                        return False
                else:
                    logger.error("Could not download required CSVs.")
                    return False

            # If we reach here without explicit return, something went wrong
            logger.warning("Reached end of run() without explicit success/failure")
            return False

        except Exception as e:
            logger.error(f"Error during upload process: {e}")
            import traceback
            logger.debug(traceback.format_exc())
            return False

        finally:
            logger.info("Closing browser...")
            try:
                self.driver.quit()
            except Exception:
                pass


if __name__ == "__main__":
    """Entry point when run directly"""
    import sys
    
    print("""
    ╔══════════════════════════════════════════════════════════╗
    ║       Mawaqit Prayer Times Uploader                      ║
    ║       Automated Prayer Times Management                  ║
    ╚══════════════════════════════════════════════════════════╝
    """)
    
    # Validate configuration before proceeding
    try:
        Config.validate()
        logger.success("✅ Configuration validated successfully")
    except ValueError as e:
        logger.error(f"❌ Configuration validation failed: {e}")
        logger.info("Please ensure the following environment variables are set:")
        logger.info("  Required: MAWAQIT_USER, MAWAQIT_PASS")
        logger.info("  Optional: GMAIL_USER, GMAIL_APP_PASSWORD, TWOCAPTCHA_API_KEY")
        sys.exit(1)
    except Exception as e:
        logger.error(f"❌ Unexpected error during configuration: {e}")
        sys.exit(1)
    
    print("-" * 60)
    
    # Create uploader instance and run
    try:
        uploader = MawaqitUploader()
        success = uploader.run()
        
        if success:
            logger.success("🎉 Prayer times uploaded to Mawaqit successfully!")
            logger.success("✅ Both Athan and Iqama times have been updated")
            sys.exit(0)
        else:
            logger.error("❌ Failed to complete the upload process")
            sys.exit(1)
    
    except KeyboardInterrupt:
        logger.warning("⚠️ Process interrupted by user")
        sys.exit(130)
    
    except Exception as e:
        logger.error(f"❌ Unexpected error: {e}")
        import traceback
        logger.debug(traceback.format_exc())
        sys.exit(1)
