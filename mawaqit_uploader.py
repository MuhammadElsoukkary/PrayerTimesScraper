#!/usr/bin/env python3
"""
Mawaqit Prayer Times Uploader with corrected NoCaptchaAI integration
"""

import imaplib
import email
import re
import time
import os
import csv
import requests
import json
from datetime import datetime
from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeoutError

NOCAPTCHAAI_API_KEY = "alsalaam465-80e91086-9f21-c204-2d46-c8e4a8a5ef3f"
NOCAPTCHAAI_API_URL = "https://api.nocaptchaai.com"

def solve_recaptcha_with_nocaptchaai(page, site_key=None):
    """
    Solve reCAPTCHA using NoCaptchaAI service with correct API endpoint
    """
    print("Solving reCAPTCHA using NoCaptchaAI...")
    
    try:
        # Get the site key if not provided
        if not site_key:
            # Try multiple ways to find the site key
            selectors = [
                '[data-sitekey]',
                '.g-recaptcha[data-sitekey]',
                'div[data-sitekey]',
                'iframe[src*="recaptcha"]'
            ]
            
            for selector in selectors:
                elements = page.locator(selector)
                if elements.count() > 0:
                    if 'iframe' in selector:
                        # Extract from iframe src
                        iframe_src = elements.first.get_attribute('src')
                        import urllib.parse
                        params = urllib.parse.parse_qs(urllib.parse.urlparse(iframe_src).query)
                        if 'k' in params:
                            site_key = params['k'][0]
                    else:
                        site_key = elements.first.get_attribute('data-sitekey')
                    
                    if site_key:
                        print(f"Found site key: {site_key}")
                        break
            
            if not site_key:
                # Try JavaScript extraction
                site_key = page.evaluate("""
                    () => {
                        // Check for grecaptcha object
                        if (typeof grecaptcha !== 'undefined' && grecaptcha.execute) {
                            const widgets = Object.keys(___grecaptcha_cfg.clients);
                            if (widgets.length > 0) {
                                return ___grecaptcha_cfg.clients[widgets[0]].id;
                            }
                        }
                        // Check for data-sitekey attribute
                        const element = document.querySelector('[data-sitekey]');
                        return element ? element.getAttribute('data-sitekey') : null;
                    }
                """)
                
                if site_key:
                    print(f"Found site key via JS: {site_key}")
                else:
                    print("Could not find reCAPTCHA site key")
                    return False
        
        current_url = page.url
        
        # Use the correct NoCaptchaAI API format for reCAPTCHA v2
        # Based on their documentation, the correct endpoint structure is:
        submit_url = f"{NOCAPTCHAAI_API_URL}/solve"
        
        # Prepare the request with correct parameters
        headers = {
            'Content-Type': 'application/json',
            'apikey': NOCAPTCHAAI_API_KEY
        }
        
        payload = {
            'type': 'recaptchav2',  # Specify reCAPTCHA v2
            'sitekey': site_key,
            'url': current_url,
            'invisible': False,  # Set to True if it's invisible reCAPTCHA
            'enterprise': False  # Set to True if it's reCAPTCHA Enterprise
        }
        
        print(f"Submitting to NoCaptchaAI...")
        print(f"URL: {submit_url}")
        print(f"Payload: {json.dumps(payload, indent=2)}")
        
        # Submit the CAPTCHA task
        submit_response = requests.post(submit_url, json=payload, headers=headers, timeout=30)
        
        print(f"Response status: {submit_response.status_code}")
        print(f"Response: {submit_response.text}")
        
        if submit_response.status_code != 200:
            # Try alternative API format (in.php style)
            print("Trying alternative API format...")
            
            alt_payload = {
                'key': NOCAPTCHAAI_API_KEY,
                'method': 'userrecaptcha',  # Try userrecaptcha method
                'googlekey': site_key,
                'pageurl': current_url,
                'json': 1
            }
            
            alt_response = requests.post(f"{NOCAPTCHAAI_API_URL}/in.php", data=alt_payload, timeout=30)
            print(f"Alternative response: {alt_response.text}")
            
            if alt_response.status_code == 200:
                try:
                    result = alt_response.json()
                    if result.get('status') == 1:
                        captcha_id = result.get('request')
                        print(f"Task submitted! ID: {captcha_id}")
                    else:
                        print(f"Failed to submit: {result}")
                        return False
                except:
                    if alt_response.text.startswith('OK|'):
                        captcha_id = alt_response.text.split('|')[1]
                        print(f"Task submitted! ID: {captcha_id}")
                    else:
                        print(f"Failed to submit: {alt_response.text}")
                        return False
            else:
                print("Both API formats failed")
                return False
        else:
            # Parse response from main API
            try:
                result = submit_response.json()
                if 'id' in result:
                    captcha_id = result['id']
                    print(f"Task submitted successfully! ID: {captcha_id}")
                elif 'taskId' in result:
                    captcha_id = result['taskId']
                    print(f"Task submitted successfully! Task ID: {captcha_id}")
                else:
                    print(f"Unexpected response format: {result}")
                    return False
            except Exception as e:
                print(f"Failed to parse response: {e}")
                return False
        
        # Poll for the solution
        print("Waiting for solution...")
        max_attempts = 30  # 5 minutes max
        
        for attempt in range(max_attempts):
            time.sleep(10)  # Wait 10 seconds between checks
            
            # Check result using the appropriate endpoint
            if 'captcha_id' in locals():
                # Using old API format
                result_url = f"{NOCAPTCHAAI_API_URL}/res.php"
                result_params = {
                    'key': NOCAPTCHAAI_API_KEY,
                    'action': 'get',
                    'id': captcha_id,
                    'json': 1
                }
                result_response = requests.get(result_url, params=result_params, timeout=10)
            else:
                # Using new API format
                result_url = f"{NOCAPTCHAAI_API_URL}/status"
                result_params = {'id': captcha_id}
                result_headers = {'apikey': NOCAPTCHAAI_API_KEY}
                result_response = requests.get(result_url, params=result_params, headers=result_headers, timeout=10)
            
            print(f"Attempt {attempt + 1}: {result_response.text[:100]}...")
            
            if result_response.status_code != 200:
                continue
            
            try:
                result_data = result_response.json()
                
                # Check if solution is ready
                if result_data.get('status') == 'ready' or result_data.get('status') == 1:
                    solution = result_data.get('solution', result_data.get('request', ''))
                    
                    if isinstance(solution, dict):
                        solution = solution.get('gRecaptchaResponse', '')
                    
                    if solution and solution != 'CAPCHA_NOT_READY':
                        print(f"✅ Solution received! Length: {len(solution)}")
                        
                        # Inject the solution
                        injection_script = f"""
                        (function() {{
                            // Find the textarea
                            let textarea = document.querySelector('#g-recaptcha-response');
                            if (!textarea) {{
                                textarea = document.querySelector('[name="g-recaptcha-response"]');
                            }}
                            if (!textarea) {{
                                // Create it if it doesn't exist
                                textarea = document.createElement('textarea');
                                textarea.id = 'g-recaptcha-response';
                                textarea.name = 'g-recaptcha-response';
                                textarea.style.display = 'none';
                                document.body.appendChild(textarea);
                            }}
                            
                            // Set the value
                            textarea.value = `{solution}`;
                            textarea.innerHTML = `{solution}`;
                            
                            // Make sure it's not disabled
                            textarea.disabled = false;
                            
                            // Trigger the callback if it exists
                            if (typeof ___grecaptcha_cfg !== 'undefined') {{
                                Object.keys(___grecaptcha_cfg.clients).forEach(key => {{
                                    const client = ___grecaptcha_cfg.clients[key];
                                    if (client.callback) {{
                                        client.callback(`{solution}`);
                                    }}
                                }});
                            }}
                            
                            // Also try window callbacks
                            if (window.recaptchaCallback) {{
                                window.recaptchaCallback(`{solution}`);
                            }}
                            if (window.onRecaptchaSuccess) {{
                                window.onRecaptchaSuccess(`{solution}`);
                            }}
                            
                            console.log('reCAPTCHA solution injected successfully');
                            return true;
                        }})();
                        """
                        
                        page.evaluate(injection_script)
                        print("✅ Solution injected into page")
                        
                        # Give it a moment to process
                        time.sleep(2)
                        
                        # Try to submit the form if there's a submit button
                        try:
                            submit_button = page.locator('button[type="submit"], input[type="submit"]').first
                            if submit_button.is_visible():
                                print("Clicking submit button...")
                                submit_button.click()
                        except:
                            pass
                        
                        return True
                
                elif result_data.get('status') == 'processing' or result_data.get('request') == 'CAPCHA_NOT_READY':
                    print(f"Still processing... ({attempt + 1}/{max_attempts})")
                    continue
                else:
                    error_msg = result_data.get('error', result_data.get('request', 'Unknown error'))
                    print(f"Error from service: {error_msg}")
                    if 'ERROR' in str(error_msg).upper():
                        return False
                    
            except Exception as e:
                print(f"Error parsing result: {e}")
                continue
        
        print("❌ Timeout waiting for solution")
        return False
        
    except Exception as e:
        print(f"❌ Error solving reCAPTCHA: {e}")
        import traceback
        traceback.print_exc()
        return False

def get_2fa_code_from_email(gmail_user, gmail_app_password):
    """
    Get 2FA code from most recent Mawaqit email (up to 2 hours old)
    """
    print("📧 Checking Gmail for 2FA code...")
    
    try:
        imap = imaplib.IMAP4_SSL("imap.gmail.com")
        imap.login(gmail_user, gmail_app_password)
        imap.select("inbox")

        status, messages = imap.search(None, 'ALL')
        if status != 'OK' or not messages[0]:
            return None

        mail_ids = messages[0].split()
        
        # Check recent emails for Mawaqit codes
        for mail_id in reversed(mail_ids[-30:]):
            try:
                status, msg_data = imap.fetch(mail_id, "(RFC822)")
                if status != 'OK':
                    continue
                    
                raw_msg = msg_data[0][1]
                msg = email.message_from_bytes(raw_msg)
                
                sender = msg.get('From', '').lower()
                subject = msg.get('Subject', '').lower()
                
                # Check if it's from Mawaqit
                if not any(domain in sender for domain in ['mawaqit.net', 'mawaqit.com']):
                    continue
                
                # Check if it's a verification email
                if not any(keyword in subject for keyword in ['verification', 'code', 'authentication']):
                    continue
                
                print(f"📧 Found Mawaqit verification email: {subject}")
                
                # Check email age (accept up to 2 hours)
                try:
                    email_date = email.utils.parsedate_to_datetime(msg['Date'])
                    age_minutes = (datetime.now(email_date.tzinfo) - email_date).total_seconds() / 60
                    print(f"📧 Email age: {age_minutes:.1f} minutes")
                    
                    if age_minutes > 120:  # 2 hours
                        continue
                except:
                    pass  # Use email anyway if we can't parse date
                
                # Extract body
                body = ""
                if msg.is_multipart():
                    for part in msg.walk():
                        if part.get_content_type() in ["text/plain", "text/html"]:
                            try:
                                payload = part.get_payload(decode=True)
                                if payload:
                                    body += payload.decode('utf-8', errors='ignore')
                            except:
                                continue
                else:
                    try:
                        payload = msg.get_payload(decode=True)
                        if payload:
                            body = payload.decode('utf-8', errors='ignore')
                    except:
                        continue

                # Find 6-digit code
                code_match = re.search(r'\b(\d{6})\b', body)
                if code_match:
                    code = code_match.group(1)
                    print(f"✅ Found 2FA code: {code}")
                    imap.close()
                    imap.logout()
                    return code
                
            except Exception:
                continue
        
        imap.close()
        imap.logout()
        
    except Exception as e:
        print(f"❌ Error checking email: {e}")
    
    return None

def read_prayer_times_csv(prayer_times_dir):
    """
    Read prayer times from CSV files
    """
    current_month = datetime.now().strftime('%B')
    athan_csv_path = os.path.join(prayer_times_dir, f'athan_times_{current_month}.csv')
    iqama_csv_path = os.path.join(prayer_times_dir, f'iqama_times_{current_month}.csv')
    
    if not os.path.exists(athan_csv_path) or not os.path.exists(iqama_csv_path):
        print(f"❌ CSV files not found for {current_month}")
        return None
    
    prayer_times = {}
    
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
    
    print(f"📊 Loaded {len(prayer_times)} days of prayer times")
    return prayer_times

def upload_to_mawaqit(mawaqit_email, mawaqit_password, gmail_user, gmail_app_password, prayer_times_dir):
    """
    Main upload function - simplified approach
    """
    print("🚀 Starting Mawaqit upload process...")
    
    # Load prayer times
    prayer_times = read_prayer_times_csv(prayer_times_dir)
    if not prayer_times:
        return False
    
    # Determine if headless
    is_headless = bool(os.getenv('CI')) or bool(os.getenv('GITHUB_ACTIONS'))
    print(f"🖥️ Running in {'headless' if is_headless else 'headed'} mode")
    
    with sync_playwright() as p:
        # Launch with additional args for better CAPTCHA handling
        browser_args = [
            '--disable-blink-features=AutomationControlled',
            '--disable-features=site-per-process',
            '--disable-dev-shm-usage'
        ]
        
        browser = p.chromium.launch(
            headless=is_headless,
            args=browser_args
        )
        
        context = browser.new_context(
            viewport={'width': 1920, 'height': 1080},
            user_agent='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
        )
        
        page = context.new_page()
        
        # Add console logging for debugging
        page.on("console", lambda msg: print(f"Browser console: {msg.text}"))
        
        try:
            print("🌐 Navigating to Mawaqit login...")
            page.goto("https://mawaqit.net/en/backoffice/login", wait_until="networkidle")
            
            # Wait a moment for page to fully load
            time.sleep(3)
            
            print("Filling login credentials...")
            page.fill('input[type="email"], input[name="email"]', mawaqit_email)
            page.fill('input[type="password"], input[name="password"]', mawaqit_password)
            
            # Check for reCAPTCHA presence
            has_recaptcha = page.locator('.g-recaptcha, iframe[src*="recaptcha"], [data-sitekey]').count() > 0
            
            if has_recaptcha:
                print("reCAPTCHA detected - solving with NoCaptchaAI...")
                recaptcha_solved = solve_recaptcha_with_nocaptchaai(page)
                
                if not recaptcha_solved:
                    print("❌ Failed to solve reCAPTCHA")
                    return False
                else:
                    print("✅ reCAPTCHA solved successfully!")
            else:
                print("No reCAPTCHA detected")
            
            print("Submitting login form...")
            # Try to find and click the submit button
            submit_selectors = [
                'button[type="submit"]',
                'input[type="submit"]',
                'button:has-text("Login")',
                'button:has-text("Sign in")',
                'button:has-text("Se connecter")'
            ]
            
            for selector in submit_selectors:
                if page.locator(selector).count() > 0:
                    page.click(selector)
                    print(f"Clicked: {selector}")
                    break
            
            # Wait for navigation
            print("⏳ Waiting for login response...")
            time.sleep(5)
            
            current_url = page.url
            page_content = page.content().lower()
            
            # Check if 2FA is required
            if any(keyword in page_content for keyword in ["verification", "code", "authentication", "2fa"]):
                print("📧 2FA required - getting code from email...")
                
                verification_code = get_2fa_code_from_email(gmail_user, gmail_app_password)
                
                if not verification_code:
                    print("❌ No 2FA code found in recent emails")
                    return False
                
                # Enter 2FA code
                code_inputs = [
                    'input[placeholder*="code" i]',
                    'input[name*="code" i]',
                    'input[name*="verification" i]',
                    'input[type="text"]',
                    'input[type="number"]'
                ]
                
                code_entered = False
                for selector in code_inputs:
                    if page.locator(selector).count() > 0:
                        page.fill(selector, verification_code)
                        code_entered = True
                        print(f"✅ Entered 2FA code using: {selector}")
                        break
                
                if not code_entered:
                    print("❌ Could not find 2FA input field")
                    return False
                
                # Submit 2FA
                for selector in submit_selectors:
                    if page.locator(selector).count() > 0:
                        page.click(selector)
                        break
                
                time.sleep(3)
            
            # Check if we're logged in
            if "backoffice" in page.url or "dashboard" in page.url:
                print("✅ Successfully logged into Mawaqit backoffice!")
            elif "login" in page.url.lower():
                print("❌ Still on login page - login failed")
                return False
            else:
                print(f"📍 Current URL: {page.url}")
                print("✅ Login appears successful")
            
            # Navigate to prayer times configuration
            print("🔍 Looking for prayer times configuration...")
            
            # Try navigation patterns
            nav_links = [
                'a:has-text("Configuration")',
                'a:has-text("Prayer")',
                'a:has-text("Times")',
                'a[href*="prayer"]',
                'a[href*="configuration"]'
            ]
            
            for link in nav_links:
                if page.locator(link).count() > 0:
                    print(f"🔗 Clicking: {link}")
                    page.click(link)
                    page.wait_for_load_state("networkidle")
                    break
            
            print("✅ Basic login and navigation completed!")
            print(f"📊 Ready to upload {len(prayer_times)} days of prayer times")
            
            return True
            
        except Exception as e:
            print(f"❌ Error during upload: {e}")
            import traceback
            traceback.print_exc()
            return False
        finally:
            browser.close()

def main():
    mawaqit_email = os.getenv('MAWAQIT_USER')
    mawaqit_password = os.getenv('MAWAQIT_PASS') 
    gmail_user = os.getenv('GMAIL_USER')
    gmail_app_password = os.getenv('GMAIL_APP_PASSWORD')
    prayer_times_dir = os.getenv('PRAYER_TIMES_DIR', './prayer_times')
    
    if not all([mawaqit_email, mawaqit_password, gmail_user, gmail_app_password]):
        print("❌ Missing required environment variables")
        return False
    
    success = upload_to_mawaqit(
        mawaqit_email, mawaqit_password, 
        gmail_user, gmail_app_password,
        prayer_times_dir
    )
    
    if success:
        print("🎉 Mawaqit process completed successfully!")
    else:
        print("💥 Mawaqit process failed!")
    
    return success

if __name__ == "__main__":
    main()
