#!/usr/bin/env python3
"""
Mawaqit Prayer Times Uploader with 2Captcha integration
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

def get_2fa_code_from_email(gmail_user, gmail_app_password):
    print("📧 Checking Gmail for 2FA code...")
    
    try:
        imap = imaplib.IMAP4_SSL("imap.gmail.com")
        imap.login(gmail_user, gmail_app_password)
        imap.select("inbox")

        status, messages = imap.search(None, 'ALL')
        if status != 'OK' or not messages[0]:
            return None

        mail_ids = messages[0].split()
        
        for mail_id in reversed(mail_ids[-30:]):
            try:
                status, msg_data = imap.fetch(mail_id, "(RFC822)")
                if status != 'OK':
                    continue
                    
                raw_msg = msg_data[0][1]
                msg = email.message_from_bytes(raw_msg)
                
                sender = msg.get('From', '').lower()
                subject = msg.get('Subject', '').lower()
                
                if not any(domain in sender for domain in ['mawaqit.net', 'mawaqit.com']):
                    continue
                
                if not any(keyword in subject for keyword in ['verification', 'code', 'authentication']):
                    continue
                
                print(f"📧 Found Mawaqit verification email: {subject}")
                
                try:
                    email_date = email.utils.parsedate_to_datetime(msg['Date'])
                    age_minutes = (datetime.now(email_date.tzinfo) - email_date).total_seconds() / 60
                    print(f"📧 Email age: {age_minutes:.1f} minutes")
                    
                    if age_minutes > 120:
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
    current_month = datetime.now().strftime('%B')
    athan_csv_path = os.path.join(prayer_times_dir, f'athan_times_{current_month}.csv')
    iqama_csv_path = os.path.join(prayer_times_dir, f'iqama_times_{current_month}.csv')
    
    if not os.path.exists(athan_csv_path) or not os.path.exists(iqama_csv_path):
        print(f"❌ CSV files not found for {current_month}")
        return None
    
    prayer_times = {}
    
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
            
            print("Filling login credentials...")
            page.fill('input[type="email"], input[name="email"]', mawaqit_email)
            page.fill('input[type="password"], input[name="password"]', mawaqit_password)
            
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
            
            current_url = page.url
            page_content = page.content().lower()
            
            if "verification" in page_content or "code" in page_content:
                print("📧 2FA required - getting code from email...")
                
                verification_code = get_2fa_code_from_email(gmail_user, gmail_app_password)
                
                if not verification_code:
                    print("❌ No 2FA code found in recent emails")
                    return False
                
                code_inputs = [
                    'input[placeholder*="code" i]',
                    'input[name*="code" i]',
                    'input[type="text"]'
                ]
                
                code_entered = False
                for selector in code_inputs:
                    if page.locator(selector).count() > 0:
                        page.fill(selector, verification_code)
                        code_entered = True
                        print("✅ Entered 2FA code")
                        break
                
                if not code_entered:
                    print("❌ Could not find 2FA input field")
                    return False
                
                page.click('button[type="submit"], input[type="submit"]')
                time.sleep(3)
            
            try:
                page.wait_for_url("**/backoffice/**", timeout=10000)
                print("✅ Successfully logged into Mawaqit backoffice!")
            except PlaywrightTimeoutError:
                if "login" in page.url.lower():
                    print("❌ Still on login page - login failed")
                    return False
                else:
                    print("✅ Login appears successful (URL changed)")
            
            print("Looking for Actions dropdown...")
            # First click the Actions dropdown to reveal Configure option
            actions_selectors = [
                'button:has-text("Actions")',
                'text="Actions"',
                '.dropdown:has-text("Actions")',
                '[data-toggle="dropdown"]:has-text("Actions")'
            ]
            
            actions_found = False
            for selector in actions_selectors:
                if page.locator(selector).count() > 0:
                    print(f"Found Actions dropdown: {selector}")
                    page.click(selector)
                    print("Clicked Actions dropdown")
                    time.sleep(1)
                    actions_found = True
                    break
            
            if not actions_found:
                print("Actions dropdown not found, trying direct Configure link...")
            
            print("Looking for Configure option...")
            configure_selectors = [
                'text="Configure"',
                'a:has-text("Configure")',
                '[href*="configure"]'
            ]
            
            configure_found = False
            for selector in configure_selectors:
                if page.locator(selector).count() > 0:
                    # Check if element is visible
                    if page.locator(selector).is_visible():
                        page.click(selector)
                        print("Clicked Configure")
                        page.wait_for_load_state("networkidle")
                        time.sleep(2)
                        configure_found = True
                        break
                    else:
                        print(f"Configure found but not visible: {selector}")
            
            if not configure_found:
                print("Configure option not found or not visible")
                # Take screenshot for debugging
                page.screenshot(path="debug_configure_not_found.png")
                return False
            
            if page.locator('text="Iqama"').count() > 0:
                page.click('text="Iqama"')
                print("Clicked Iqama section")
                page.wait_for_load_state("networkidle")
                time.sleep(1)
            
            if page.locator('text="By calendar"').count() > 0:
                page.click('text="By calendar"')
                print("Clicked 'By calendar' tab")
                page.wait_for_load_state("networkidle")
                time.sleep(1)
            
            current_month = datetime.now().strftime('%B')
            print(f"Looking for {current_month} month...")
            
            # Scroll down to find August month since it's lower on the page
            page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
            time.sleep(2)
            
            # Look for August month element specifically
            august_element = page.locator(f'text="{current_month}"').last  # Use .last to get the bottom one
            
            if august_element.count() > 0:
                print(f"Found {current_month} month, scrolling to it")
                august_element.scroll_into_view_if_needed()
                time.sleep(1)
                
                # Click on August to expand/select it
                august_element.click()
                print(f"Clicked {current_month} month")
                time.sleep(2)
                
                # Now look for the Pre-populate button that should appear under August
                print("Looking for CSV upload button under August...")
                
                # The button should be visible now under the August section
                csv_button = page.locator('text="Pre-populate from a csv file"').last
                
                if csv_button.count() > 0 and csv_button.is_visible():
                    csv_button.click()
                    print("Clicked 'Pre-populate from a csv file' button")
                    page.wait_for_load_state("networkidle")
                    time.sleep(2)
                else:
                    print("CSV upload button not found under August")
                    page.screenshot(path="debug_august_section.png")
                    return False
                    
            else:
                print(f"Could not find {current_month} month")
                page.screenshot(path="debug_no_august.png")
                return False
            
            print("Looking for file input...")
            file_input = page.locator('input[type="file"]')
            
            if file_input.count() > 0:
                iqama_csv_path = os.path.join('./prayer_times', f'iqama_times_{current_month}.csv')
                
                if os.path.exists(iqama_csv_path):
                    print(f"Uploading file: {iqama_csv_path}")
                    file_input.set_input_files(iqama_csv_path)
                    print("File uploaded successfully")
                    
                    time.sleep(3)
                    
                    submit_selectors = [
                        'button:has-text("Upload")',
                        'button:has-text("Submit")',
                        'button:has-text("Save")',
                        'input[type="submit"]'
                    ]
                    
                    for selector in submit_selectors:
                        if page.locator(selector).count() > 0:
                            page.click(selector)
                            print(f"Clicked submit button: {selector}")
                            break
                    
                    page.wait_for_load_state("networkidle")
                    time.sleep(2)
                    
                    print("CSV upload completed!")
                    return True
                    
                else:
                    print(f"CSV file not found: {iqama_csv_path}")
                    return False
            else:
                print("File input not found")
                return False
            
        except Exception as e:
            print(f"❌ Error during upload: {e}")
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
