#!/usr/bin/env python3
"""
Enhanced Mawaqit Prayer Times Uploader v3.0
- Improved 2Captcha integration with proper waiting and retry logic
- Better UI element detection and interaction
- Enhanced error handling and recovery
- More robust email verification code retrieval
"""

import imaplib
import email
import re
import time
import os
import csv
import requests
import json
from datetime import datetime, timedelta
from typing import Optional, Dict, List, Tuple
from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeoutError, Page

# Configuration
TWOCAPTCHA_API_KEY = "398d8ae5ed1cea23fdabf36c752e9774"
DEBUG_MODE = True  # Set to False in production
MAX_RETRIES = 3
WAIT_BETWEEN_ACTIONS = 2  # seconds

class MawaqitUploader:
    def __init__(self, mawaqit_email: str, mawaqit_password: str, 
                 gmail_user: str, gmail_app_password: str, prayer_times_dir: str):
        self.mawaqit_email = mawaqit_email
        self.mawaqit_password = mawaqit_password
        self.gmail_user = gmail_user
        self.gmail_app_password = gmail_app_password
        self.prayer_times_dir = prayer_times_dir
        self.page = None
        self.context = None
        self.browser = None
        
    def debug_log(self, message: str, level: str = "INFO"):
        """Enhanced logging with levels"""
        timestamp = datetime.now().strftime("%H:%M:%S")
        prefix = {"INFO": "ℹ️", "SUCCESS": "✅", "ERROR": "❌", "DEBUG": "🔍", "WARNING": "⚠️"}.get(level, "📝")
        print(f"[{timestamp}] {prefix} {message}")
        
    def save_debug_screenshot(self, step_name: str):
        """Save screenshot for debugging with timestamp"""
        if not DEBUG_MODE or not self.page:
            return
            
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        screenshot_path = f"debug_{step_name}_{timestamp}.png"
        try:
            self.page.screenshot(path=screenshot_path)
            self.debug_log(f"Screenshot saved: {screenshot_path}", "DEBUG")
        except Exception as e:
            self.debug_log(f"Failed to save screenshot: {e}", "WARNING")
    
    def wait_for_page_load(self, timeout: int = 30):
        """Wait for page to fully load"""
        try:
            self.page.wait_for_load_state("networkidle", timeout=timeout * 1000)
            return True
        except PlaywrightTimeoutError:
            self.debug_log("Page load timeout - continuing anyway", "WARNING")
            return False
    
    def detect_recaptcha(self) -> Tuple[bool, Optional[str]]:
        """Detect reCAPTCHA presence and extract site key"""
        try:
            # Check for various reCAPTCHA indicators
            recaptcha_indicators = [
                'iframe[src*="recaptcha"]',
                '.g-recaptcha',
                '[data-sitekey]',
                '#g-recaptcha',
                'div[class*="recaptcha"]'
            ]
            
            for indicator in recaptcha_indicators:
                if self.page.locator(indicator).count() > 0:
                    self.debug_log("reCAPTCHA detected on page", "INFO")
                    
                    # Try to extract site key
                    site_key = None
                    
                    # Method 1: data-sitekey attribute
                    elements_with_sitekey = self.page.locator('[data-sitekey]')
                    if elements_with_sitekey.count() > 0:
                        site_key = elements_with_sitekey.first.get_attribute('data-sitekey')
                    
                    # Method 2: Parse from iframe src
                    if not site_key:
                        iframes = self.page.locator('iframe[src*="recaptcha"]')
                        if iframes.count() > 0:
                            src = iframes.first.get_attribute('src')
                            match = re.search(r'[?&]k=([^&]+)', src)
                            if match:
                                site_key = match.group(1)
                    
                    # Method 3: Check in page scripts
                    if not site_key:
                        page_content = self.page.content()
                        match = re.search(r'grecaptcha\.render.*?sitekey["\']?\s*:\s*["\']([^"\']+)', page_content)
                        if match:
                            site_key = match.group(1)
                    
                    if site_key:
                        self.debug_log(f"Site key found: {site_key}", "SUCCESS")
                    else:
                        self.debug_log("reCAPTCHA present but couldn't extract site key", "WARNING")
                    
                    return True, site_key
            
            return False, None
            
        except Exception as e:
            self.debug_log(f"Error detecting reCAPTCHA: {e}", "ERROR")
            return False, None
    
    def solve_recaptcha_with_2captcha(self, site_key: Optional[str] = None) -> bool:
        """Enhanced 2Captcha solver with better error handling"""
        self.debug_log("Starting 2Captcha reCAPTCHA solving process", "INFO")
        
        try:
            # Detect reCAPTCHA if site_key not provided
            if not site_key:
                has_recaptcha, detected_key = self.detect_recaptcha()
                if not has_recaptcha:
                    self.debug_log("No reCAPTCHA found on page", "INFO")
                    return True
                site_key = detected_key
                
            if not site_key:
                self.debug_log("Cannot proceed without site key", "ERROR")
                return False
            
            current_url = self.page.url
            self.debug_log(f"Page URL: {current_url}", "DEBUG")
            
            # Submit captcha to 2Captcha
            submit_url = "http://2captcha.com/in.php"
            submit_params = {
                'key': TWOCAPTCHA_API_KEY,
                'method': 'userrecaptcha',
                'googlekey': site_key,
                'pageurl': current_url,
                'json': 1
            }
            
            self.debug_log("Submitting reCAPTCHA to 2Captcha...", "INFO")
            response = requests.post(submit_url, data=submit_params, timeout=30)
            
            if response.status_code != 200:
                self.debug_log(f"2Captcha submission failed: HTTP {response.status_code}", "ERROR")
                return False
            
            result = response.json()
            
            if result.get('status') != 1:
                error_msg = result.get('error_text', result.get('request', 'Unknown error'))
                self.debug_log(f"2Captcha submission error: {error_msg}", "ERROR")
                return False
            
            captcha_id = result['request']
            self.debug_log(f"Captcha submitted successfully. Task ID: {captcha_id}", "SUCCESS")
            
            # Wait for solution
            result_url = "http://2captcha.com/res.php"
            max_attempts = 60
            check_interval = 5
            
            self.debug_log(f"Waiting for solution (max {max_attempts * check_interval} seconds)...", "INFO")
            
            for attempt in range(max_attempts):
                time.sleep(check_interval)
                
                result_params = {
                    'key': TWOCAPTCHA_API_KEY,
                    'action': 'get',
                    'id': captcha_id,
                    'json': 1
                }
                
                try:
                    result_response = requests.get(result_url, params=result_params, timeout=10)
                    
                    if result_response.status_code != 200:
                        self.debug_log(f"Failed to check result: HTTP {result_response.status_code}", "WARNING")
                        continue
                    
                    result = result_response.json()
                    
                    if result.get('status') == 1:
                        solution = result['request']
                        self.debug_log(f"reCAPTCHA solved! Solution received (length: {len(solution)})", "SUCCESS")
                        
                        # Inject solution into page
                        injection_script = f"""
                        (function() {{
                            // Method 1: Set g-recaptcha-response textarea
                            const textareas = document.querySelectorAll('[name="g-recaptcha-response"]');
                            textareas.forEach(textarea => {{
                                textarea.value = "{solution}";
                                textarea.style.display = 'block';
                            }});
                            
                            // Method 2: Override grecaptcha.getResponse
                            if (typeof grecaptcha !== 'undefined') {{
                                grecaptcha.getResponse = function() {{ return "{solution}"; }};
                                
                                // Trigger any callbacks
                                if (window.___grecaptcha_cfg && window.___grecaptcha_cfg.clients) {{
                                    Object.keys(window.___grecaptcha_cfg.clients).forEach(key => {{
                                        const client = window.___grecaptcha_cfg.clients[key];
                                        if (client.callback) {{
                                            try {{
                                                client.callback("{solution}");
                                            }} catch(e) {{
                                                console.log('Callback error:', e);
                                            }}
                                        }}
                                    }});
                                }}
                            }}
                            
                            // Method 3: Dispatch events
                            const event = new Event('captcha-solved');
                            document.dispatchEvent(event);
                            
                            console.log('2Captcha solution injected successfully');
                            return true;
                        }})();
                        """
                        
                        injection_result = self.page.evaluate(injection_script)
                        self.debug_log("Solution injected into page", "SUCCESS")
                        
                        # Give the page time to process the solution
                        time.sleep(2)
                        
                        # Try to auto-submit if there's a submit button
                        try:
                            submit_buttons = self.page.locator('button[type="submit"], input[type="submit"]')
                            if submit_buttons.count() > 0:
                                visible_button = None
                                for i in range(submit_buttons.count()):
                                    if submit_buttons.nth(i).is_visible():
                                        visible_button = submit_buttons.nth(i)
                                        break
                                
                                if visible_button:
                                    self.debug_log("Auto-clicking submit button after captcha solve", "INFO")
                                    visible_button.click()
                        except Exception as e:
                            self.debug_log(f"Could not auto-submit: {e}", "DEBUG")
                        
                        return True
                        
                    elif result.get('status') == 0:
                        request_status = result.get('request', '')
                        if request_status == 'CAPCHA_NOT_READY':
                            if attempt % 6 == 0:  # Log every 30 seconds
                                self.debug_log(f"Still waiting... ({attempt * check_interval} seconds elapsed)", "INFO")
                        else:
                            self.debug_log(f"2Captcha error: {request_status}", "ERROR")
                            return False
                            
                except Exception as e:
                    self.debug_log(f"Error checking result: {e}", "WARNING")
                    continue
            
            self.debug_log("Timeout waiting for 2Captcha solution", "ERROR")
            return False
            
        except Exception as e:
            self.debug_log(f"Unexpected error in 2Captcha solver: {e}", "ERROR")
            return False
    
    def get_2fa_code_from_email(self, max_wait_minutes: int = 5) -> Optional[str]:
        """Enhanced email checker with better pattern matching"""
        self.debug_log("Checking Gmail for 2FA verification code...", "INFO")
        
        start_time = datetime.now()
        check_interval = 15  # seconds
        
        while (datetime.now() - start_time).total_seconds() < max_wait_minutes * 60:
            try:
                imap = imaplib.IMAP4_SSL("imap.gmail.com")
                imap.login(self.gmail_user, self.gmail_app_password)
                imap.select("inbox")
                
                # Search for recent Mawaqit emails
                since_date = (datetime.now() - timedelta(minutes=10)).strftime("%d-%b-%Y")
                search_criteria = f'(FROM "mawaqit" SINCE "{since_date}")'
                
                status, messages = imap.search(None, search_criteria)
                
                if status == 'OK' and messages[0]:
                    mail_ids = messages[0].split()
                    
                    # Check most recent emails first
                    for mail_id in reversed(mail_ids[-5:]):
                        try:
                            status, msg_data = imap.fetch(mail_id, "(RFC822)")
                            if status != 'OK':
                                continue
                            
                            raw_msg = msg_data[0][1]
                            msg = email.message_from_bytes(raw_msg)
                            
                            # Check email age
                            email_date = email.utils.parsedate_to_datetime(msg['Date'])
                            age_minutes = (datetime.now(email_date.tzinfo) - email_date).total_seconds() / 60
                            
                            if age_minutes > 10:
                                continue
                            
                            self.debug_log(f"Found recent Mawaqit email (age: {age_minutes:.1f} minutes)", "INFO")
                            
                            # Extract body
                            body = self.extract_email_body(msg)
                            
                            # Enhanced code patterns
                            code_patterns = [
                                r'\b(\d{6})\b',  # 6-digit code
                                r'code[:\s]+(\d{6})',
                                r'verification[:\s]+(\d{6})',
                                r'OTP[:\s]+(\d{6})',
                                r'PIN[:\s]+(\d{6})',
                            ]
                            
                            for pattern in code_patterns:
                                matches = re.findall(pattern, body, re.IGNORECASE)
                                if matches:
                                    code = matches[0]
                                    self.debug_log(f"Found 2FA code: {code}", "SUCCESS")
                                    imap.close()
                                    imap.logout()
                                    return code
                            
                        except Exception as e:
                            self.debug_log(f"Error processing email: {e}", "WARNING")
                            continue
                
                imap.close()
                imap.logout()
                
                elapsed = (datetime.now() - start_time).total_seconds()
                if elapsed < max_wait_minutes * 60:
                    self.debug_log(f"No code found yet, waiting {check_interval} seconds... ({elapsed:.0f}s elapsed)", "INFO")
                    time.sleep(check_interval)
                
            except Exception as e:
                self.debug_log(f"Error checking email: {e}", "ERROR")
                time.sleep(check_interval)
        
        self.debug_log("No 2FA code found within timeout period", "ERROR")
        return None
    
    def extract_email_body(self, msg) -> str:
        """Extract text body from email message"""
        body = ""
        
        if msg.is_multipart():
            for part in msg.walk():
                content_type = part.get_content_type()
                if content_type in ["text/plain", "text/html"]:
                    try:
                        payload = part.get_payload(decode=True)
                        if payload:
                            text = payload.decode('utf-8', errors='ignore')
                            # Remove HTML tags if present
                            text = re.sub(r'<[^>]+>', '', text)
                            body += text
                    except Exception:
                        continue
        else:
            try:
                payload = msg.get_payload(decode=True)
                if payload:
                    body = payload.decode('utf-8', errors='ignore')
                    body = re.sub(r'<[^>]+>', '', body)
            except Exception:
                pass
        
        return body
    
    def read_prayer_times_csv(self) -> Optional[Dict]:
        """Read prayer times from CSV files"""
        current_month = datetime.now().strftime('%B')
        athan_csv_path = os.path.join(self.prayer_times_dir, f'athan_times_{current_month}.csv')
        iqama_csv_path = os.path.join(self.prayer_times_dir, f'iqama_times_{current_month}.csv')
        
        self.debug_log(f"Looking for CSV files for {current_month}", "INFO")
        
        if not os.path.exists(athan_csv_path):
            self.debug_log(f"Athan CSV not found: {athan_csv_path}", "ERROR")
            return None
            
        if not os.path.exists(iqama_csv_path):
            self.debug_log(f"Iqama CSV not found: {iqama_csv_path}", "ERROR")
            return None
        
        prayer_times = {}
        
        try:
            # Read Athan times
            with open(athan_csv_path, 'r', encoding='utf-8') as file:
                reader = csv.DictReader(file)
                for row in reader:
                    day = row.get('Day')
                    if day:
                        prayer_times[int(day)] = {
                            'athan': {
                                'fajr': row.get('Fajr', ''),
                                'dhuhr': row.get('Dhuhr', ''),
                                'asr': row.get('Asr', ''),
                                'maghrib': row.get('Maghrib', ''),
                                'isha': row.get('Isha', '')
                            },
                            'iqama': {}
                        }
            
            # Read Iqama times
            with open(iqama_csv_path, 'r', encoding='utf-8') as file:
                reader = csv.DictReader(file)
                for row in reader:
                    day = row.get('Day')
                    if day and int(day) in prayer_times:
                        prayer_times[int(day)]['iqama'] = {
                            'fajr': row.get('Fajr', ''),
                            'dhuhr': row.get('Dhuhr', ''),
                            'asr': row.get('Asr', ''),
                            'maghrib': row.get('Maghrib', ''),
                            'isha': row.get('Isha', '')
                        }
            
            self.debug_log(f"Successfully loaded {len(prayer_times)} days of prayer times", "SUCCESS")
            return prayer_times
            
        except Exception as e:
            self.debug_log(f"Error reading CSV files: {e}", "ERROR")
            return None
    
    def smart_click(self, selectors: List[str], description: str, 
                   required: bool = True, wait_after: int = WAIT_BETWEEN_ACTIONS) -> bool:
        """Smart element clicking with multiple fallback selectors"""
        self.debug_log(f"Looking for: {description}", "INFO")
        
        for attempt in range(2):  # Try twice in case of timing issues
            for i, selector in enumerate(selectors):
                try:
                    elements = self.page.locator(selector)
                    count = elements.count()
                    
                    if count > 0:
                        # Try to find visible element
                        for j in range(count):
                            element = elements.nth(j)
                            
                            try:
                                if element.is_visible(timeout=1000):
                                    # Scroll into view if needed
                                    element.scroll_into_view_if_needed()
                                    time.sleep(0.5)
                                    
                                    # Click
                                    element.click()
                                    self.debug_log(f"Clicked: {description} (selector {i+1})", "SUCCESS")
                                    
                                    if wait_after > 0:
                                        time.sleep(wait_after)
                                    
                                    return True
                            except Exception:
                                continue
                    
                except Exception as e:
                    self.debug_log(f"Error with selector {i+1}: {e}", "DEBUG")
                    continue
            
            if attempt == 0:
                self.debug_log(f"First attempt failed for {description}, retrying...", "INFO")
                time.sleep(2)
        
        if required:
            self.debug_log(f"Could not find: {description}", "ERROR")
            self.save_debug_screenshot(f"missing_{description.replace(' ', '_')}")
        else:
            self.debug_log(f"Optional element not found: {description}", "INFO")
        
        return False
    
    def upload_csv_file(self, csv_type: str) -> bool:
        """Upload CSV file (athan or iqama)"""
        current_month = datetime.now().strftime('%B')
        self.debug_log(f"Starting {csv_type} CSV upload for {current_month}", "INFO")
        
        # Click "Pre-populate from CSV" button
        csv_button_selectors = [
            f'button:has-text("Pre-populate from a csv file")',
            f'a:has-text("Pre-populate from a csv file")',
            f'button:has-text("CSV")',
            f'button:has-text("csv")',
            f'.btn:has-text("csv")'
        ]
        
        if not self.smart_click(csv_button_selectors, f"CSV upload button ({csv_type})", wait_after=2):
            return False
        
        # Find and use file input
        file_input_selectors = [
            'input[type="file"]',
            'input[accept*="csv"]',
            'input[accept*="CSV"]',
            '.file-input input'
        ]
        
        file_uploaded = False
        for selector in file_input_selectors:
            try:
                if self.page.locator(selector).count() > 0:
                    file_input = self.page.locator(selector).first
                    
                    csv_filename = f'{csv_type}_times_{current_month}.csv'
                    csv_path = os.path.join(self.prayer_times_dir, csv_filename)
                    
                    if not os.path.exists(csv_path):
                        self.debug_log(f"CSV file not found: {csv_path}", "ERROR")
                        return False
                    
                    self.debug_log(f"Uploading file: {csv_path}", "INFO")
                    file_input.set_input_files(csv_path)
                    file_uploaded = True
                    self.debug_log(f"{csv_type.capitalize()} file uploaded", "SUCCESS")
                    break
                    
            except Exception as e:
                self.debug_log(f"Error with file input: {e}", "DEBUG")
                continue
        
        if not file_uploaded:
            self.debug_log(f"Could not upload {csv_type} file", "ERROR")
            return False
        
        time.sleep(2)
        
        # Submit the upload
        submit_selectors = [
            'button:has-text("Upload")',
            'button:has-text("Submit")',
            'button:has-text("Save")',
            'button[type="submit"]',
            'input[type="submit"]',
            '.btn-primary',
            '.btn-success'
        ]
        
        self.smart_click(submit_selectors, f"Submit button ({csv_type})", required=False, wait_after=3)
        
        return True
    
    def perform_login(self) -> bool:
        """Perform login with reCAPTCHA and 2FA handling"""
        self.debug_log("Starting login process", "INFO")
        
        try:
            # Navigate to login page
            self.page.goto("https://mawaqit.net/en/backoffice/login", wait_until="domcontentloaded")
            self.wait_for_page_load()
            self.save_debug_screenshot("login_page")
            
            # Fill credentials
            self.debug_log("Filling login credentials", "INFO")
            email_input = self.page.locator('input[type="email"], input[name="email"], #email')
            password_input = self.page.locator('input[type="password"], input[name="password"], #password')
            
            if email_input.count() == 0 or password_input.count() == 0:
                self.debug_log("Login form fields not found", "ERROR")
                return False
            
            email_input.first.fill(self.mawaqit_email)
            password_input.first.fill(self.mawaqit_password)
            
            # Check for reCAPTCHA
            has_recaptcha, site_key = self.detect_recaptcha()
            
            if has_recaptcha:
                self.debug_log("reCAPTCHA detected - solving with 2Captcha", "INFO")
                if not self.solve_recaptcha_with_2captcha(site_key):
                    self.debug_log("Failed to solve reCAPTCHA", "ERROR")
                    return False
                # Don't click submit here - solver will auto-submit if possible
                time.sleep(3)
            else:
                # No reCAPTCHA - submit normally
                self.debug_log("No reCAPTCHA detected - submitting form", "INFO")
                submit_button = self.page.locator('button[type="submit"], input[type="submit"]').first
                submit_button.click()
            
            # Wait for response
            time.sleep(5)
            self.wait_for_page_load()
            
            # Check if we need 2FA
            page_content = self.page.content().lower()
            current_url = self.page.url.lower()
            
            if "verification" in page_content or "code" in page_content or "2fa" in current_url:
                self.debug_log("2FA verification required", "INFO")
                self.save_debug_screenshot("2fa_page")
                
                # Get code from email
                verification_code = self.get_2fa_code_from_email()
                
                if not verification_code:
                    self.debug_log("Could not retrieve 2FA code", "ERROR")
                    return False
                
                # Enter 2FA code
                code_input_selectors = [
                    'input[placeholder*="code" i]',
                    'input[name*="code" i]',
                    'input[name*="verification" i]',
                    'input[type="text"]:not([type="email"]):not([type="password"])',
                    'input[type="number"]'
                ]
                
                code_entered = False
                for selector in code_input_selectors:
                    try:
                        elements = self.page.locator(selector)
                        if elements.count() > 0:
                            for i in range(elements.count()):
                                element = elements.nth(i)
                                if element.is_visible():
                                    element.fill(verification_code)
                                    code_entered = True
                                    self.debug_log("2FA code entered", "SUCCESS")
                                    break
                            if code_entered:
                                break
                    except Exception:
                        continue
                
                if not code_entered:
                    self.debug_log("Could not find 2FA input field", "ERROR")
                    return False
                
                # Submit 2FA
                self.page.locator('button[type="submit"], input[type="submit"]').first.click()
                time.sleep(5)
                self.wait_for_page_load()
            
            # Verify login success
            if "backoffice" in self.page.url and "login" not in self.page.url:
                self.debug_log("Login successful!", "SUCCESS")
                self.save_debug_screenshot("logged_in")
                return True
            else:
                self.debug_log("Login failed - still on login page", "ERROR")
                self.save_debug_screenshot("login_failed")
                return False
                
        except Exception as e:
            self.debug_log(f"Login error: {e}", "ERROR")
            return False
    
    def navigate_to_prayer_times_config(self) -> bool:
        """Navigate to prayer times configuration"""
        self.debug_log("Navigating to prayer times configuration", "INFO")
        
        # Click Actions button
        actions_selectors = [
            'button:has-text("Actions")',
            '.btn:has-text("Actions")',
            'a:has-text("Actions")',
            '[class*="dropdown-toggle"]:has-text("Actions")'
        ]
        
        if not self.smart_click(actions_selectors, "Actions button"):
            return False
        
        # Click Configure from dropdown
        configure_selectors = [
            'a:has-text("Configure")',
            '.dropdown-item:has-text("Configure")',
            '[href*="/configure"]',
            'li:has-text("Configure") a'
        ]
        
        if not self.smart_click(configure_selectors, "Configure option"):
            return False
        
        self.wait_for_page_load()
        self.save_debug_screenshot("configure_page")
        
        # Expand Calculation of prayer times section
        calculation_selectors = [
            'text="Calculation of prayer times"',
            'h3:has-text("Calculation of prayer times")',
            'h4:has-text("Calculation of prayer times")',
            '.panel-heading:has-text("Calculation")',
            '.card-header:has-text("Calculation")',
            '[data-toggle]:has-text("Calculation")'
        ]
        
        if not self.smart_click(calculation_selectors, "Calculation section"):
            return False
        
        return True
    
    def upload_monthly_times(self) -> bool:
        """Upload both Athan and Iqama times for current month"""
        current_month = datetime.now().strftime('%B')
        self.debug_log(f"Uploading prayer times for {current_month}", "INFO")
        
        # Click on current month
        month_selectors = [
            f'text="{current_month}"',
            f'h3:has-text("{current_month}"
