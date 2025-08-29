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

TWOCAPTCHA_API_KEY = "398d8ae5ed1cea23fdabf36c752e9774"  # Your 2Captcha API key

def solve_recaptcha_with_2captcha(page, site_key=None):
    """
    Solve reCAPTCHA using 2Captcha service
    """
    print("Solving reCAPTCHA using 2Captcha...")
    
    try:
        # Get the site key if not provided
        if not site_key:
            recaptcha_elements = page.locator('[data-sitekey]')
            if recaptcha_elements.count() > 0:
                site_key = recaptcha_elements.first.get_attribute('data-sitekey')
                print(f"Found site key: {site_key}")
            else:
                print("Could not find reCAPTCHA site key")
                return False
        
        current_url = page.url
        
        # Submit reCAPTCHA to 2Captcha
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
        
        # Poll for results
        result_url = "http://2captcha.com/res.php"
        print("Waiting for solution...")
        
        for attempt in range(60):  # Wait up to 5 minutes
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
                
                # Inject the solution into the page
                page.evaluate(f'''
                    // Set the response textarea
                    const responseElement = document.querySelector('[name="g-recaptcha-response"]');
                    if (responseElement) {{
                        responseElement.value = "{solution}";
                        responseElement.style.display = 'block';
                    }}
                    
                    // Override grecaptcha if it exists
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
        
        # Poll for result
        print("Waiting for reCAPTCHA solution...")
        for attempt in range(30):  # Wait up to 5 minutes
            time.sleep(10)
            
            # Request with JSON format
            result_url = f'https://api.nocaptchaai.com/res.php?key={NOCAPTCHAAI_API_KEY}&action=get&id={captcha_id}&json=1'
            result_response = requests.get(result_url, timeout=10)
            
            print(f"Result response: {result_response.text}")
            
            if result_response.status_code != 200:
                print(f"Failed to get result: {result_response.status_code}")
                continue
            
            try:
                result = result_response.json()
                if result.get('status') == 0:
                    if result.get('request') == 'CAPCHA_NOT_READY':
                        print(f"Attempt {attempt + 1}: Not ready yet...")
                        continue
                elif result.get('status') == 1:
                    solution = result.get('request')
                    print(f"reCAPTCHA solved! Solution length: {len(solution)}")
                    
                    # Inject the solution into the page
                    page.evaluate(f'''
                        // Find and set the response textarea
                        const responseElement = document.querySelector('[name="g-recaptcha-response"]');
                        if (responseElement) {{
                            responseElement.value = "{solution}";
                            responseElement.style.display = 'block';
                        }}
                        
                        // Override grecaptcha if it exists
                        if (window.grecaptcha) {{
                            window.grecaptcha.getResponse = function() {{ return "{solution}"; }};
                        }}
                        
                        console.log('reCAPTCHA solution injected');
                    ''')
                    
                    print("Solution injected into page")
                    return True
                else:
                    print(f"reCAPTCHA solving failed: {result}")
                    return False
                    
            except:
                # Fallback to text parsing
                result_text = result_response.text
                if result_text == 'CAPCHA_NOT_READY':
                    print(f"Attempt {attempt + 1}: Not ready yet...")
                    continue
                elif result_text.startswith('OK|'):
                    solution = result_text.split('|')[1]
                    print(f"reCAPTCHA solved! Solution length: {len(solution)}")
                    
                    page.evaluate(f'''
                        const responseElement = document.querySelector('[name="g-recaptcha-response"]');
                        if (responseElement) {{
                            responseElement.value = "{solution}";
                        }}
                        if (window.grecaptcha) {{
                            window.grecaptcha.getResponse = function() {{ return "{solution}"; }};
                        }}
                    ''')
                    
                    print("Solution injected into page")
                    return True
                else:
                    print(f"reCAPTCHA solving failed: {result_text}")
                    return False
        
        print("Timeout waiting for reCAPTCHA solution")
        return False
        
    except Exception as e:
        print(f"Error solving reCAPTCHA: {e}")
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
        browser = p.chromium.launch(headless=is_headless)
        context = browser.new_context()
        page = context.new_page()
        
        try:
            print("🌐 Navigating to Mawaqit login...")
            page.goto("https://mawaqit.net/en/backoffice/login", wait_until="load")
            
            print("Filling login credentials...")
            page.fill('input[type="email"], input[name="email"]', mawaqit_email)
            page.fill('input[type="password"], input[name="password"]', mawaqit_password)
            
            # Handle reCAPTCHA with 2Captcha
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
            
            # Wait for either dashboard or 2FA page
            print("⏳ Waiting for login response...")
            time.sleep(5)
            
            current_url = page.url
            page_content = page.content().lower()
            
            # Check if 2FA is required
            if "verification" in page_content or "code" in page_content:
                print("📧 2FA required - getting code from email...")
                
                verification_code = get_2fa_code_from_email(gmail_user, gmail_app_password)
                
                if not verification_code:
                    print("❌ No 2FA code found in recent emails")
                    return False
                
                # Enter 2FA code
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
                        print(f"✅ Entered 2FA code")
                        break
                
                if not code_entered:
                    print("❌ Could not find 2FA input field")
                    return False
                
                # Submit 2FA
                page.click('button[type="submit"], input[type="submit"]')
                time.sleep(3)
            
            # Check if we're logged in by looking for backoffice URL or dashboard elements
            try:
                page.wait_for_url("**/backoffice/**", timeout=10000)
                print("✅ Successfully logged into Mawaqit backoffice!")
            except PlaywrightTimeoutError:
                if "login" in page.url.lower():
                    print("❌ Still on login page - login failed")
                    return False
                else:
                    print("✅ Login appears successful (URL changed)")
            
            # Navigate to prayer times configuration
            print("🔍 Looking for prayer times configuration...")
            
            # Try common navigation patterns
            nav_links = [
                'a:has-text("Configuration")',
                'a:has-text("Prayer")',
                'a:has-text("Athan")',
                'a[href*="prayer"]',
                'a[href*="athan"]'
            ]
            
            for link in nav_links:
                if page.locator(link).count() > 0:
                    print(f"🔗 Clicking: {link}")
                    page.click(link)
                    page.wait_for_load_state("networkidle")
                    break
            
            print("✅ Basic login and navigation completed!")
            print(f"📊 Ready to upload {len(prayer_times)} days of prayer times")
            
            # Here you would add the actual form filling logic
            # For now, we've proven the login works
            
            return True
            
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
