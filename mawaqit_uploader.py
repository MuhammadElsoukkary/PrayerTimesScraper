#!/usr/bin/env python3
"""
Automated Mawaqit Prayer Times Uploader
Handles Gmail 2FA and uploads CSV prayer times to Mawaqit backoffice
"""

import imaplib
import email
import re
import time
import os
import csv
from datetime import datetime, timedelta
from playwright.sync_api import sync_playwright, expect

def get_latest_mawaqit_2fa_code(gmail_user, gmail_app_password, max_wait=120):
    """
    Fetch the latest 2FA code from Gmail for Mawaqit
    """
    print("🔍 Checking Gmail for 2FA code...")
    
    start_time = time.time()
    attempt = 0
    
    while time.time() - start_time < max_wait:
        attempt += 1
        print(f"🔄 Attempt {attempt} to find 2FA code...")
        
        try:
            # Connect to Gmail via IMAP
            print("📧 Connecting to Gmail...")
            imap = imaplib.IMAP4_SSL("imap.gmail.com")
            imap.login(gmail_user, gmail_app_password)
            imap.select("inbox")
            print("✅ Connected to Gmail successfully")

            # Get all recent emails (last 50) and check them manually
            print("🔍 Fetching recent emails...")
            status, messages = imap.search(None, 'ALL')
            
            if status != 'OK' or not messages[0]:
                print("⏳ No emails found, waiting...")
                imap.close()
                imap.logout()
                time.sleep(10)
                continue

            mail_ids = messages[0].split()
            print(f"📧 Found {len(mail_ids)} total emails in inbox")
            
            # Check the most recent emails for 2FA code
            recent_emails = mail_ids[-20:]  # Check last 20 emails
            print(f"🔍 Checking {len(recent_emails)} most recent emails...")
            
            for i, mail_id in enumerate(reversed(recent_emails)):
                try:
                    print(f"📧 Checking email {i+1}/{len(recent_emails)}...")
                    
                    status, msg_data = imap.fetch(mail_id, "(RFC822)")
                    if status != 'OK':
                        continue
                        
                    raw_msg = msg_data[0][1]
                    msg = email.message_from_bytes(raw_msg)
                    
                    # Get sender and subject for debugging
                    sender = msg.get('From', '')
                    subject = msg.get('Subject', '')
                    date_str = msg.get('Date', '')
                    
                    print(f"   From: {sender}")
                    print(f"   Subject: {subject}")
                    print(f"   Date: {date_str}")
                    
                    # Check if it's from Mawaqit or contains verification keywords
                    sender_lower = sender.lower()
                    subject_lower = subject.lower()
                    
                    is_mawaqit = any(domain in sender_lower for domain in ['mawaqit.net', 'mawaqit.com'])
                    has_verification_keywords = any(keyword in subject_lower for keyword in ['verification', 'code', 'login', 'authenticate', 'security'])
                    
                    if not is_mawaqit and not has_verification_keywords:
                        print("   ⏭️ Not from Mawaqit or verification-related, skipping...")
                        continue
                    
                    print("   ✅ Email looks relevant, checking content...")
                    
                    # Get email date and check if it's recent
                    try:
                        email_date = email.utils.parsedate_to_datetime(msg['Date'])
                        time_diff = (datetime.now(email_date.tzinfo) - email_date).total_seconds()
                        print(f"   ⏰ Email age: {time_diff/60:.1f} minutes")
                        
                        if time_diff > 1800:  # 30 minutes
                            print("   ⏳ Email too old, skipping...")
                            continue
                    except Exception as e:
                        print(f"   ⚠️ Could not parse email date: {e}")
                        # Continue anyway
                    
                    # Extract email body
                    body = ""
                    if msg.is_multipart():
                        for part in msg.walk():
                            content_type = part.get_content_type()
                            if content_type in ["text/plain", "text/html"]:
                                try:
                                    payload = part.get_payload(decode=True)
                                    if payload:
                                        decoded_content = payload.decode('utf-8', errors='ignore')
                                        body += decoded_content
                                except Exception as e:
                                    print(f"   ⚠️ Error decoding email part: {e}")
                                    continue
                    else:
                        try:
                            payload = msg.get_payload(decode=True)
                            if payload:
                                body = payload.decode('utf-8', errors='ignore')
                        except Exception as e:
                            print(f"   ⚠️ Error decoding email: {e}")
                            continue

                    if not body:
                        print("   ⚠️ Empty email body, skipping...")
                        continue
                    
                    print(f"   📄 Email body length: {len(body)} characters")
                    
                    # Look for verification-related keywords in body
                    verification_keywords = ['verification', 'verify', 'authenticate', 'login', 'code', 'mawaqit', 'security']
                    body_lower = body.lower()
                    
                    matching_keywords = [kw for kw in verification_keywords if kw in body_lower]
                    if matching_keywords:
                        print(f"   ✅ Found verification keywords: {matching_keywords}")
                    else:
                        print("   ⏳ No verification keywords in body, skipping...")
                        continue
                    
                    # Look for 6-digit verification code
                    code_patterns = [
                        r'\b(\d{6})\b',  # Any 6 digits
                        r'verification.*?(\d{6})',  # 6 digits after "verification"
                        r'code.*?(\d{6})',  # 6 digits after "code"
                        r'(\d{6}).*?verification',  # 6 digits before "verification"
                        r'(\d{6}).*?code',  # 6 digits before "code"
                    ]
                    
                    for pattern_name, pattern in enumerate(code_patterns):
                        code_matches = re.findall(pattern, body, re.IGNORECASE | re.DOTALL)
                        if code_matches:
                            code = code_matches[-1]  # Get the last match
                            print(f"   ✅ Found 2FA code with pattern {pattern_name + 1}: {code}")
                            
                            # Verify it's a valid 6-digit code
                            if code.isdigit() and len(code) == 6:
                                print(f"✅ Valid 2FA code found: {code}")
                                imap.close()
                                imap.logout()
                                return code
                            else:
                                print(f"   ⚠️ Invalid code format: {code}")
                    
                    print("   ⏳ No verification code found in this email")
                    
                except Exception as e:
                    print(f"   ❌ Error processing email {mail_id}: {e}")
                    continue
            
            print("⏳ No recent 2FA code found in current batch, waiting...")
            imap.close()
            imap.logout()
            time.sleep(15)  # Wait longer between attempts
            
        except Exception as e:
            print(f"❌ Error checking email: {e}")
            try:
                imap.close()
                imap.logout()
            except:
                pass
            time.sleep(15)
    
    print("❌ Timeout waiting for 2FA code")
    return None

def read_prayer_times_csv(athan_csv_path, iqama_csv_path):
    """
    Read prayer times from CSV files generated by scraper
    Returns dict with days as keys and prayer times as values
    """
    prayer_times = {}
    
    try:
        # Read Athan times
        athan_times = {}
        with open(athan_csv_path, 'r', encoding='utf-8') as file:
            reader = csv.DictReader(file)
            for row in reader:
                day = row.get('Day')
                if day:
                    athan_times[int(day)] = {
                        'fajr': row.get('Fajr', ''),
                        'sunrise': row.get('Sunrise', ''),
                        'dhuhr': row.get('Dhuhr', ''),
                        'asr': row.get('Asr', ''),
                        'maghrib': row.get('Maghrib', ''),
                        'isha': row.get('Isha', '')
                    }
        
        # Read Iqama times
        iqama_times = {}
        with open(iqama_csv_path, 'r', encoding='utf-8') as file:
            reader = csv.DictReader(file)
            for row in reader:
                day = row.get('Day')
                if day:
                    iqama_times[int(day)] = {
                        'fajr': row.get('Fajr', ''),
                        'dhuhr': row.get('Dhuhr', ''),
                        'asr': row.get('Asr', ''),
                        'maghrib': row.get('Maghrib', ''),
                        'isha': row.get('Isha', '')
                    }
        
        # Combine both into prayer_times dict
        for day in athan_times:
            prayer_times[day] = {
                'athan': athan_times[day],
                'iqama': iqama_times.get(day, {})
            }
    
    except Exception as e:
        print(f"❌ Error reading CSV files: {e}")
        return {}
    
    print(f"📊 Loaded {len(prayer_times)} days of prayer times from CSV files")
    return prayer_times

def upload_to_mawaqit(mawaqit_email, mawaqit_password, gmail_user, gmail_app_password, prayer_times_dir):
    """
    Main function to login to Mawaqit and upload prayer times
    """
    print("🚀 Starting Mawaqit upload process...")
    
    # Get current month name for CSV files
    current_month = datetime.now().strftime('%B')
    athan_csv_path = os.path.join(prayer_times_dir, f'athan_times_{current_month}.csv')
    iqama_csv_path = os.path.join(prayer_times_dir, f'iqama_times_{current_month}.csv')
    
    print(f"🗓️ Current month: {current_month}")
    print(f"📂 Looking for Athan CSV: {athan_csv_path}")
    print(f"📂 Looking for Iqama CSV: {iqama_csv_path}")
    
    # Check if CSV files exist
    if not os.path.exists(athan_csv_path) or not os.path.exists(iqama_csv_path):
        print(f"❌ CSV files not found:")
        print(f"   Athan exists: {os.path.exists(athan_csv_path)}")
        print(f"   Iqama exists: {os.path.exists(iqama_csv_path)}")
        
        # List what files ARE in the directory
        if os.path.exists(prayer_times_dir):
            print(f"📁 Files in {prayer_times_dir}:")
            for file in os.listdir(prayer_times_dir):
                print(f"   - {file}")
        
        return False
    
    # Read prayer times from CSV files
    prayer_times = read_prayer_times_csv(athan_csv_path, iqama_csv_path)
    if not prayer_times:
        print("❌ No prayer times found in CSV files")
        return False
    
    # Log some sample data
    sample_day = list(prayer_times.keys())[0]
    print(f"📊 Sample data for day {sample_day}:")
    print(f"   Athan: {prayer_times[sample_day]['athan']}")
    print(f"   Iqama: {prayer_times[sample_day]['iqama']}")
    
    with sync_playwright() as p:
        # Launch browser
        browser = p.chromium.launch(headless=False)  # Set to False for debugging
        context = browser.new_context()
        page = context.new_page()
        
        try:
            # Navigate to Mawaqit login
            print("🌐 Navigating to Mawaqit login...")
            page.goto("https://mawaqit.net/en/backoffice/login", wait_until="networkidle")
            
            # Fill login form
            print("📝 Filling login credentials...")
            page.fill('input[type="email"]', mawaqit_email)
            page.fill('input[type="password"]', mawaqit_password)
            
            # Submit login
            page.click('button[type="submit"]')
            print("🔑 Login submitted, waiting for response...")
            
            # Wait for page to load
            page.wait_for_load_state("networkidle")
            page.wait_for_timeout(3000)  # Give it extra time
            
            # Check if 2FA is required
            page_content = page.content().lower()
            if "verification" in page_content or "code" in page_content or "authenticate" in page_content:
                print("📧 2FA required, fetching code from Gmail...")
                
                # Get 2FA code from email
                verification_code = get_latest_mawaqit_2fa_code(gmail_user, gmail_app_password)
                
                if not verification_code:
                    print("❌ Failed to get 2FA code")
                    return False
                
                # Enter 2FA code - try different input selectors
                code_input_selectors = [
                    'input[placeholder*="code" i]',
                    'input[name*="code" i]',
                    'input[type="text"]',
                    'input[type="number"]',
                    '.form-control'
                ]
                
                code_entered = False
                for selector in code_input_selectors:
                    if page.locator(selector).count() > 0:
                        page.fill(selector, verification_code)
                        code_entered = True
                        print(f"✅ 2FA code entered using selector: {selector}")
                        break
                
                if not code_entered:
                    print("❌ Could not find 2FA input field")
                    page.screenshot(path="debug_2fa_input.png")
                    return False
                
                # Submit 2FA
                submit_selectors = [
                    'button[type="submit"]',
                    'input[type="submit"]',
                    'button:has-text("Verify")',
                    'button:has-text("Submit")',
                    '.btn-primary'
                ]
                
                submitted = False
                for selector in submit_selectors:
                    if page.locator(selector).count() > 0:
                        page.click(selector)
                        submitted = True
                        print(f"✅ 2FA submitted using selector: {selector}")
                        break
                
                if not submitted:
                    print("❌ Could not find submit button for 2FA")
                    page.screenshot(path="debug_2fa_submit.png")
                    return False
                
                page.wait_for_load_state("networkidle")
                page.wait_for_timeout(3000)
            
            print("✅ Successfully logged in to Mawaqit!")
            
            # Take a screenshot to see what we're working with
            page.screenshot(path="debug_logged_in.png")
            
            # Navigate to prayer times configuration
            print("🏛️ Looking for prayer times configuration...")
            
            # Try to find and click on prayer times related links
            prayer_time_links = [
                'text="Athan & Iqama"',
                'text="Prayer Times"',
                'text="Configuration"',
                'a[href*="athan"]',
                'a[href*="prayer"]',
                'a[href*="times"]'
            ]
            
            for link_selector in prayer_time_links:
                if page.locator(link_selector).count() > 0:
                    print(f"🔗 Found link: {link_selector}")
                    try:
                        page.click(link_selector)
                        page.wait_for_load_state("networkidle")
                        print(f"✅ Clicked: {link_selector}")
                        break
                    except Exception as e:
                        print(f"⚠️ Failed to click {link_selector}: {e}")
                        continue
            
            # Take another screenshot after navigation
            page.screenshot(path="debug_prayer_times_page.png")
            
            print("📝 Prayer times form should now be visible")
            print("🎉 Basic login and navigation completed successfully!")
            
            return True
            
        except Exception as e:
            print(f"❌ Error during upload: {e}")
            page.screenshot(path="debug_error.png")
            return False
        finally:
            # Don't close browser immediately for debugging
            print("⏸️  Browser will stay open for 30 seconds for debugging...")
            time.sleep(30)
            browser.close()

def main():
    """
    Main entry point
    """
    # Get credentials from environment variables
    mawaqit_email = os.getenv('MAWAQIT_USER')
    mawaqit_password = os.getenv('MAWAQIT_PASS')
    gmail_user = os.getenv('GMAIL_USER')
    gmail_app_password = os.getenv('GMAIL_APP_PASSWORD')
    
    # Path to your prayer times directory
    prayer_times_dir = os.getenv('PRAYER_TIMES_DIR', './prayer_times')
    
    if not all([mawaqit_email, mawaqit_password, gmail_user, gmail_app_password]):
        print("❌ Missing required environment variables")
        print("Required: MAWAQIT_USER, MAWAQIT_PASS, GMAIL_USER, GMAIL_APP_PASSWORD")
        print("\nCurrent values:")
        print(f"MAWAQIT_USER: {'✅' if mawaqit_email else '❌'}")
        print(f"MAWAQIT_PASS: {'✅' if mawaqit_password else '❌'}")
        print(f"GMAIL_USER: {'✅' if gmail_user else '❌'}")
        print(f"GMAIL_APP_PASSWORD: {'✅' if gmail_app_password else '❌'}")
        return False
    
    print("🔧 Environment variables loaded successfully")
    
    success = upload_to_mawaqit(
        mawaqit_email=mawaqit_email,
        mawaqit_password=mawaqit_password,
        gmail_user=gmail_user,
        gmail_app_password=gmail_app_password,
        prayer_times_dir=prayer_times_dir
    )
    
    if success:
        print("🎉 Mawaqit upload completed successfully!")
    else:
        print("💥 Mawaqit upload failed!")
    
    return success

if __name__ == "__main__":
    main()
