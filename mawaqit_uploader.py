#!/usr/bin/env python3
"""
Enhanced Mawaqit Prayer Times Uploader with improved debugging and robustness
"""

import imaplib
import email
import re
import time
import os
import csv
import requests
from datetime import datetime
from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeoutError

TWOCAPTCHA_API_KEY = "398d8ae5ed1cea23fdabf36c752e9774"

def debug_page_state(page, step_name):
    """Debug helper to capture page state"""
    print(f"🔍 DEBUG {step_name}:")
    print(f"   URL: {page.url}")
    print(f"   Title: {page.title()}")
    
    # Save screenshot for debugging
    screenshot_path = f"debug_{step_name.lower().replace(' ', '_')}.png"
    page.screenshot(path=screenshot_path)
    print(f"   Screenshot saved: {screenshot_path}")

def solve_recaptcha_with_2captcha(page, site_key=None):
    print("Solving reCAPTCHA using 2Captcha...")
    
    try:
        if not site_key:
            recaptcha_elements = page.locator('[data-sitekey]')
            if recaptcha_elements.count() > 0:
                site_key = recaptcha_elements.first.get_attribute('data-sitekey')
                print(f"Found site key: {site_key}")
            else:
                print("Could not find reCAPTCHA site key")
                return False
        
        current_url = page.url
        
        submit_url = "http://2captcha.com/in.php"
        submit_params = {
            'key': TWOCAPTCHA_API_KEY,
            'method': 'userrecaptcha',
            'googlekey': site_key,
            'pageurl': current_url,
            'json': 1
        }
        
        print("Submitting reCAPTCHA to 2Captcha...")
        response = requests.post(submit_url, data=submit_params, timeout=30)
        
        if response.status_code != 200:
            print(f"Failed to submit: HTTP {response.status_code}")
            return False
        
        result = response.json()
        print(f"Submit response: {result}")
        
        if result['status'] != 1:
            print(f"Submission failed: {result.get('error_text', 'Unknown error')}")
            return False
        
        captcha_id = result['request']
        print(f"Task submitted with ID: {captcha_id}")
        
        result_url = "http://2captcha.com/res.php"
        print("Waiting for solution...")
        
        for attempt in range(60):
            time.sleep(5)
            
            result_params = {
                'key': TWOCAPTCHA_API_KEY,
                'action': 'get',
                'id': captcha_id,
                'json': 1
            }
            
            result_response = requests.get(result_url, params=result_params, timeout=10)
            
            if result_response.status_code != 200:
                print(f"Failed to get result: HTTP {result_response.status_code}")
                continue
            
            result = result_response.json()
            print(f"Attempt {attempt + 1}: Status = {result.get('status', 'unknown')}")
            
            if result['status'] == 1:
                solution = result['request']
                print(f"reCAPTCHA solved! Solution length: {len(solution)}")
                
                page.evaluate(f'''
                    const responseElement = document.querySelector('[name="g-recaptcha-response"]');
                    if (responseElement) {{
                        responseElement.value = "{solution}";
                        responseElement.style.display = 'block';
                    }}
                    
                    if (window.grecaptcha) {{
                        window.grecaptcha.getResponse = function() {{ return "{solution}"; }};
                    }}
                    
                    console.log('2Captcha solution injected');
                ''')
                
                print("Solution injected into page")
                return True
                
            elif result['status'] == 0:
                if result.get('request') == 'CAPCHA_NOT_READY':
                    continue
                else:
                    print(f"Error: {result.get('request', 'Unknown error')}")
                    return False
        
        print("Timeout waiting for solution")
        return False
        
    except Exception as e:
        print(f"Error solving reCAPTCHA: {e}")
        return False

def get_2fa_code_from_email(gmail_user, gmail_app_password, max_retries=5):
    print("📧 Checking Gmail for 2FA code...")
    
    for retry in range(max_retries):
        try:
            imap = imaplib.IMAP4_SSL("imap.gmail.com")
            imap.login(gmail_user, gmail_app_password)
            imap.select("inbox")

            # Search for recent emails from Mawaqit
            status, messages = imap.search(None, 'FROM "mawaqit" SINCE "29-Aug-2025"')
            if status != 'OK' or not messages[0]:
                print(f"No recent Mawaqit emails found (attempt {retry + 1})")
                if retry < max_retries - 1:
                    time.sleep(30)  # Wait before retrying
                    continue
                return None

            mail_ids = messages[0].split()
            
            for mail_id in reversed(mail_ids[-10:]):  # Check last 10 emails
                try:
                    status, msg_data = imap.fetch(mail_id, "(RFC822)")
                    if status != 'OK':
                        continue
                        
                    raw_msg = msg_data[0][1]
                    msg = email.message_from_bytes(raw_msg)
                    
                    sender = msg.get('From', '').lower()
                    subject = msg.get('Subject', '').lower()
                    
                    print(f"📧 Found Mawaqit verification email: {subject}")
                    
                    try:
                        email_date = email.utils.parsedate_to_datetime(msg['Date'])
                        age_minutes = (datetime.now(email_date.tzinfo) - email_date).total_seconds() / 60
                        print(f"📧 Email age: {age_minutes:.1f} minutes")
                        
                        if age_minutes > 10:  # Only check very recent emails
                            continue
                    except:
                        pass
                    
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

                    # Look for 6-digit codes
                    code_patterns = [
                        r'\b(\d{6})\b',  # Standard 6-digit code
                        r'code[:\s]*(\d{6})',  # "code: 123456"
                        r'verification[:\s]*(\d{6})',  # "verification: 123456"
                    ]
                    
                    for pattern in code_patterns:
                        code_match = re.search(pattern, body, re.IGNORECASE)
                        if code_match:
                            code = code_match.group(1)
                            print(f"✅ Found 2FA code: {code}")
                            imap.close()
                            imap.logout()
                            return code
                    
                except Exception as e:
                    print(f"Error processing email: {e}")
                    continue
            
            imap.close()
            imap.logout()
            
            if retry < max_retries - 1:
                print(f"No valid code found, waiting 30 seconds before retry {retry + 2}...")
                time.sleep(30)
            
        except Exception as e:
            print(f"❌ Error checking email (attempt {retry + 1}): {e}")
            if retry < max_retries - 1:
                time.sleep(30)
    
    return None

def read_prayer_times_csv(prayer_times_dir):
    current_month = datetime.now().strftime('%B')
    athan_csv_path = os.path.join(prayer_times_dir, f'athan_times_{current_month}.csv')
    iqama_csv_path = os.path.join(prayer_times_dir, f'iqama_times_{current_month}.csv')
    
    print(f"📁 Looking for CSV files:")
    print(f"   Athan: {athan_csv_path}")
    print(f"   Iqama: {iqama_csv_path}")
    
    if not os.path.exists(athan_csv_path) or not os.path.exists(iqama_csv_path):
        print(f"❌ CSV files not found for {current_month}")
        return None
    
    prayer_times = {}
    
    try:
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
        
    except Exception as e:
        print(f"❌ Error reading CSV files: {e}")
        return None

def find_and_click_element(page, selectors, description, required=True, wait_time=2):
    """Helper function to find and click elements with multiple selector fallbacks"""
    print(f"Looking for {description}...")
    
    for i, selector in enumerate(selectors):
        try:
            elements = page.locator(selector)
            count = elements.count()
            
            if count > 0:
                # Check if any element is visible
                for j in range(count):
                    element = elements.nth(j)
                    if element.is_visible():
                        print(f"Found {description} with selector {i+1}: {selector}")
                        element.click()
                        print(f"Clicked {description}")
                        time.sleep(wait_time)
                        return True
                        
                print(f"Found {description} but not visible with selector: {selector}")
            else:
                print(f"Selector {i+1} not found: {selector}")
                
        except Exception as e:
            print(f"Error with selector {selector}: {e}")
            continue
    
    if required:
        print(f"❌ Could not find {description}")
        debug_page_state(page, f"missing_{description.replace(' ', '_')}")
    
    return False

def upload_to_mawaqit(mawaqit_email, mawaqit_password, gmail_user, gmail_app_password, prayer_times_dir):
    print("🚀 Starting Mawaqit upload process...")
    
    prayer_times = read_prayer_times_csv(prayer_times_dir)
    if not prayer_times:
        return False
    
    is_headless = bool(os.getenv('CI')) or bool(os.getenv('GITHUB_ACTIONS'))
    print(f"🖥️ Running in {'headless' if is_headless else 'headed'} mode")
    
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=is_headless)
        context = browser.new_context()
        page = context.new_page()
        
        try:
            print("🌐 Navigating to Mawaqit login...")
            page.goto("https://mawaqit.net/en/backoffice/login", wait_until="load")
            time.sleep(3)
            
            debug_page_state(page, "login_page")
            
            print("Filling login credentials...")
            page.fill('input[type="email"], input[name="email"]', mawaqit_email)
            page.fill('input[type="password"], input[name="password"]', mawaqit_password)
            
            # Check for reCAPTCHA
            if page.locator('.g-recaptcha, iframe[src*="recaptcha"]').count() > 0:
                print("reCAPTCHA detected - solving with 2Captcha...")
                recaptcha_solved = solve_recaptcha_with_2captcha(page)
                
                if not recaptcha_solved:
                    print("Failed to solve reCAPTCHA")
                    return False
                else:
                    print("reCAPTCHA solved successfully!")
            else:
                print("No reCAPTCHA detected")
            
            print("Submitting login...")
            page.click('button[type="submit"], input[type="submit"]')
            
            print("⏳ Waiting for login response...")
            time.sleep(5)
            
            debug_page_state(page, "after_login")
            
            current_url = page.url
            page_content = page.content().lower()
            
            # Handle 2FA if required
            if "verification" in page_content or "code" in page_content or "2fa" in page_content:
                print("📧 2FA required - getting code from email...")
                
                verification_code = get_2fa_code_from_email(gmail_user, gmail_app_password)
                
                if not verification_code:
                    print("❌ No 2FA code found in recent emails")
                    debug_page_state(page, "2fa_code_not_found")
                    return False
                
                # Try multiple selectors for 2FA input
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
                        element = page.locator(selector).first
                        if element.is_visible():
                            element.fill(verification_code)
                            code_entered = True
                            print("✅ Entered 2FA code")
                            break
                
                if not code_entered:
                    print("❌ Could not find 2FA input field")
                    debug_page_state(page, "2fa_input_not_found")
                    return False
                
                page.click('button[type="submit"], input[type="submit"]')
                time.sleep(5)
            
            # Wait for successful login
            try:
                page.wait_for_url("**/backoffice/**", timeout=15000)
                print("✅ Successfully logged into Mawaqit backoffice!")
            except PlaywrightTimeoutError:
                if "login" in page.url.lower():
                    print("❌ Still on login page - login failed")
                    debug_page_state(page, "login_failed")
                    return False
                else:
                    print("✅ Login appears successful (URL changed)")
            
            debug_page_state(page, "logged_in")
            
            # Step 1: Click Actions button
            actions_selectors = [
                'button:has-text("Actions")',
                '.btn:has-text("Actions")',
                '[class*="btn"]:has-text("Actions")'
            ]
            
            if not find_and_click_element(page, actions_selectors, "Actions button"):
                return False
            
            debug_page_state(page, "actions_clicked")
            
            # Step 2: Click Configure from dropdown
            configure_selectors = [
                'text="Configure"',
                'a:has-text("Configure")',
                '.dropdown-item:has-text("Configure")',
                '[href*="configure"]'
            ]
            
            # Wait for dropdown to appear
            time.sleep(1)
            if not find_and_click_element(page, configure_selectors, "Configure option"):
                return False
            
            debug_page_state(page, "configure_page")
            
            # Step 3: Click "Calculation of prayer times" to expand section
            calculation_selectors = [
                'text="Calculation of prayer times"',
                'h3:has-text("Calculation of prayer times")',
                'h4:has-text("Calculation of prayer times")',
                '.panel-heading:has-text("Calculation of prayer times")',
                '.card-header:has-text("Calculation of prayer times")'
            ]
            
            if not find_and_click_element(page, calculation_selectors, "Calculation of prayer times section"):
                return False
            
            debug_page_state(page, "calculation_expanded")
            
            # Step 4: Click current month 
            current_month = datetime.now().strftime('%B')
            print(f"Looking for {current_month} month...")
            
            month_selectors = [
                f'text="{current_month}"',
                f'h3:has-text("{current_month}")',
                f'h4:has-text("{current_month}")',
                f'.month-header:has-text("{current_month}")'
            ]
            
            if not find_and_click_element(page, month_selectors, f"{current_month} month"):
                return False
                
            debug_page_state(page, "month_clicked")
            
            # Step 5: Upload Athan CSV
            print("📄 Uploading Athan CSV...")
            if not upload_csv_file(page, prayer_times_dir, current_month, 'athan'):
                return False
            
            # Step 6: Navigate to Iqama section
            iqama_selectors = [
                'text="Iqama"',
                'a:has-text("Iqama")',
                '.nav-link:has-text("Iqama")',
                'button:has-text("Iqama")',
                '.tab:has-text("Iqama")'
            ]
            
            if not find_and_click_element(page, iqama_selectors, "Iqama tab"):
                return False
                
            debug_page_state(page, "iqama_tab")
            
            # Step 7: Click "By calendar" under Iqama
            calendar_selectors = [
                'text="By calendar"',
                'a:has-text("By calendar")',
                '.nav-link:has-text("By calendar")',
                'button:has-text("By calendar")'
            ]
            
            if not find_and_click_element(page, calendar_selectors, "By calendar tab"):
                return False
                
            debug_page_state(page, "calendar_tab")
            
            # Step 8: Click current month again (under Iqama section)
            if not find_and_click_element(page, month_selectors, f"{current_month} month (Iqama)"):
                return False
                
            # Step 9: Upload Iqama CSV
            print("📄 Uploading Iqama CSV...")
            if not upload_csv_file(page, prayer_times_dir, current_month, 'iqama'):
                return False
            
            print("✅ Both CSV files uploaded successfully!")
            return True

def upload_csv_file(page, prayer_times_dir, current_month, csv_type):
    """Helper function to upload CSV files (athan or iqama)"""
    
    # Look for "Pre-populate from a csv file" button
    csv_button_selectors = [
        'text="Pre-populate from a csv file"',
        'button:has-text("Pre-populate")',
        'a:has-text("Pre-populate")',
        '.btn:has-text("csv")',
        'button:has-text("csv")'
    ]
    
    # Wait for content to load
    time.sleep(2)
    
    csv_button_found = False
    for selector in csv_button_selectors:
        elements = page.locator(selector)
        if elements.count() > 0:
            for i in range(elements.count()):
                element = elements.nth(i)
                try:
                    if element.is_visible():
                        element.scroll_into_view_if_needed()
                        time.sleep(1)
                        element.click()
                        print(f"Clicked 'Pre-populate from csv' button")
                        time.sleep(2)
                        csv_button_found = True
                        break
                except Exception as e:
                    print(f"Error clicking csv button: {e}")
                    continue
            if csv_button_found:
                break
    
    if not csv_button_found:
        print(f"❌ CSV upload button not found for {csv_type}")
        page.screenshot(path=f"debug_csv_button_not_found_{csv_type}.png")
        return False
    
    # Look for file input
    file_input_selectors = [
        'input[type="file"]',
        'input[accept*="csv"]',
        '.file-input input'
    ]
    
    file_input_found = False
    for selector in file_input_selectors:
        if page.locator(selector).count() > 0:
            file_input = page.locator(selector).first
            
            csv_filename = f'{csv_type}_times_{current_month}.csv'
            csv_path = os.path.join(prayer_times_dir, csv_filename)
            
            if os.path.exists(csv_path):
                print(f"📁 Uploading {csv_type} file: {csv_path}")
                file_input.set_input_files(csv_path)
                print(f"✅ {csv_type.capitalize()} file uploaded successfully")
                file_input_found = True
                break
            else:
                print(f"❌ CSV file not found: {csv_path}")
                return False
    
    if not file_input_found:
        print(f"❌ File input not found for {csv_type}")
        page.screenshot(path=f"debug_file_input_not_found_{csv_type}.png")
        return False
    
    time.sleep(2)
    
    # Submit the form
    submit_selectors = [
        'button:has-text("Upload")',
        'button:has-text("Submit")',
        'button:has-text("Save")',
        'input[type="submit"]',
        '.btn-primary',
        '.btn-success'
    ]
    
    submit_found = False
    for selector in submit_selectors:
        if page.locator(selector).count() > 0:
            elements = page.locator(selector)
            for i in range(elements.count()):
                element = elements.nth(i)
                try:
                    if element.is_visible():
                        element.click()
                        print(f"Clicked submit button for {csv_type}")
                        time.sleep(3)
                        submit_found = True
                        break
                except Exception as e:
                    continue
            if submit_found:
                break
    
    if not submit_found:
        print(f"⚠️ Submit button not found for {csv_type}, but file was uploaded")
    
    return True
            
        except Exception as e:
            print(f"❌ Error during upload: {e}")
            debug_page_state(page, "error_occurred")
            return False
        finally:
            print("🔄 Closing browser...")
            browser.close()

def main():
    print("🕌 Mawaqit Prayer Times Uploader v2.0")
    print("=" * 50)
    
    # Check environment variables
    required_vars = {
        'MAWAQIT_USER': os.getenv('MAWAQIT_USER'),
        'MAWAQIT_PASS': os.getenv('MAWAQIT_PASS'),
        'GMAIL_USER': os.getenv('GMAIL_USER'),
        'GMAIL_APP_PASSWORD': os.getenv('GMAIL_APP_PASSWORD')
    }
    
    missing_vars = [var for var, value in required_vars.items() if not value]
    if missing_vars:
        print(f"❌ Missing required environment variables: {', '.join(missing_vars)}")
        return False
    
    prayer_times_dir = os.getenv('PRAYER_TIMES_DIR', './prayer_times')
    
    print("✅ All environment variables found")
    print(f"📁 Prayer times directory: {prayer_times_dir}")
    
    success = upload_to_mawaqit(
        required_vars['MAWAQIT_USER'], 
        required_vars['MAWAQIT_PASS'], 
        required_vars['GMAIL_USER'], 
        required_vars['GMAIL_APP_PASSWORD'],
        prayer_times_dir
    )
    
    if success:
        print("\n🎉 Mawaqit process completed successfully!")
    else:
        print("\n💥 Mawaqit process failed!")
        print("🔍 Check debug screenshots for troubleshooting")
    
    return success

if __name__ == "__main__":
    main()
