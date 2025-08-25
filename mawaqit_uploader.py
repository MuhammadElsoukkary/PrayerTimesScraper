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
        browser = p.chromium.launch(headless=True)
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
            
            # Navigate to Configuration → Athan & Iqama
            print("🏛️ Navigating to Athan & Iqama configuration...")
            
            try:
                # Wait for page to load completely
                page.wait_for_load_state("networkidle")
                
                # Look for Configuration menu/link
                if page.locator('text="Configuration"').count() > 0:
                    page.click('text="Configuration"')
                    page.wait_for_load_state("networkidle")
                    print("✅ Clicked Configuration")
                
                # Look for Athan & Iqama link
                if page.locator('text="Athan & Iqama"').count() > 0:
                    page.click('text="Athan & Iqama"')
                    page.wait_for_load_state("networkidle")
                    print("✅ Navigated to Athan & Iqama page")
                elif page.locator('text="Athan"').count() > 0:
                    page.click('text="Athan"')
                    page.wait_for_load_state("networkidle")
                    print("✅ Navigated to Athan page")
                
                # Wait for the calendar/form to load
                page.wait_for_timeout(3000)
                
            except Exception as e:
                print(f"⚠️ Navigation error: {e}")
                print("🔍 Taking screenshot for debugging...")
                page.screenshot(path="debug_navigation.png")
            
            # Fill prayer times for each day of the month
            print("📅 Filling prayer times...")
            
            # Get today's date to highlight current day
            today = datetime.now().day
            print(f"📅 Today is day {today} of the month")
            
            filled_days = 0
            for day, times in prayer_times.items():
                try:
                    day_marker = "🔥 TODAY" if day == today else ""
                    print(f"Processing day {day} {day_marker}...")
                    
                    # Log the times we're about to upload for today
                    if day == today:
                        print(f"🕐 Today's Athan times: Fajr={times['athan']['fajr']}, Dhuhr={times['athan']['dhuhr']}, Asr={times['athan']['asr']}, Maghrib={times['athan']['maghrib']}, Isha={times['athan']['isha']}")
                        print(f"🕐 Today's Iqama times: Fajr={times['iqama']['fajr']}, Dhuhr={times['iqama']['dhuhr']}, Asr={times['iqama']['asr']}, Maghrib={times['iqama']['maghrib']}, Isha={times['iqama']['isha']}")
                    
                    # Fill Athan times (based on Mawaqit's form structure)
                    athan_times = times['athan']
                    
                    # Try different selector patterns for day inputs
                    # Pattern 1: day-based inputs
                    day_selectors = [
                        f'input[name*="day_{day}"]',
                        f'input[data-day="{day}"]',
                        f'td[data-day="{day}"] input',
                        f'.day-{day} input'
                    ]
                    
                    # Try to find and fill Fajr time for this day
                    fajr_filled = False
                    for selector_pattern in day_selectors:
                        fajr_selectors = [
                            f'{selector_pattern}[name*="fajr"]',
                            f'{selector_pattern}[placeholder*="Fajr"]',
                            f'{selector_pattern}.fajr'
                        ]
                        
                        for fajr_selector in fajr_selectors:
                            if page.locator(fajr_selector).count() > 0:
                                page.fill(fajr_selector, athan_times['fajr'])
                                fajr_filled = True
                                break
                        
                        if fajr_filled:
                            break
                    
                    # Similar pattern for other prayers
                    prayer_names = ['dhuhr', 'asr', 'maghrib', 'isha']
                    iqama_times = times['iqama']
                    
                    for prayer in prayer_names:
                        # Fill Athan time
                        if athan_times.get(prayer):
                            athan_selectors = [
                                f'input[name*="day_{day}"][name*="{prayer}"][name*="athan"]',
                                f'input[data-day="{day}"][data-prayer="{prayer}"][data-type="athan"]',
                                f'td[data-day="{day}"] input[name*="{prayer}"].athan'
                            ]
                            
                            for selector in athan_selectors:
                                if page.locator(selector).count() > 0:
                                    page.fill(selector, athan_times[prayer])
                                    break
                        
                        # Fill Iqama time
                        if iqama_times.get(prayer):
                            iqama_selectors = [
                                f'input[name*="day_{day}"][name*="{prayer}"][name*="iqama"]',
                                f'input[data-day="{day}"][data-prayer="{prayer}"][data-type="iqama"]',
                                f'td[data-day="{day}"] input[name*="{prayer}"].iqama'
                            ]
                            
                            for selector in iqama_selectors:
                                if page.locator(selector).count() > 0:
                                    page.fill(selector, iqama_times[prayer])
                                    break
                    
                    filled_days += 1
                    
                    # Add small delay to avoid overwhelming the form
                    page.wait_for_timeout(100)
                    
                except Exception as e:
                    print(f"⚠️ Error filling day {day}: {e}")
                    continue
            
            print(f"✅ Filled prayer times for {filled_days} days")
            
            # Save the changes
            print("💾 Saving changes...")
            
            # Look for Save button
            save_selectors = [
                'button:has-text("Save")',
                'input[type="submit"][value*="Save"]',
                'button[type="submit"]',
                '.btn-save',
                '#save-btn'
            ]
            
            saved = False
            for save_selector in save_selectors:
                if page.
