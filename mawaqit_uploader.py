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
import random
import math
from datetime import datetime, timedelta
from playwright.sync_api import sync_playwright, expect

def human_like_mouse_move(page, target_selector):
    """
    Move mouse to target in a human-like curved path with realistic timing
    """
    try:
        target = page.locator(target_selector)
        if target.count() == 0:
            return False
            
        box = target.bounding_box()
        if not box:
            return False
        
        target_x = box['x'] + box['width'] / 2
        target_y = box['y'] + box['height'] / 2
        
        start_x = target_x + random.randint(-200, -100)
        start_y = target_y + random.randint(-100, 100)
        
        steps = random.randint(15, 25)
        points = []
        
        for i in range(steps + 1):
            progress = i / steps
            x = start_x + (target_x - start_x) * progress
            y = start_y + (target_y - start_y) * progress
            
            curve_height = random.randint(20, 50)
            curve_offset = math.sin(progress * math.pi) * curve_height
            
            x += random.randint(-5, 5)
            y += curve_offset + random.randint(-5, 5)
            
            points.append((x, y))
        
        for i, (x, y) in enumerate(points):
            page.mouse.move(x, y)
            
            if i < 3 or i > len(points) - 4:
                delay = random.randint(50, 100)
            else:
                delay = random.randint(10, 30)
            
            time.sleep(delay / 1000)
        
        time.sleep(random.randint(100, 300) / 1000)
        return True
        
    except Exception as e:
        print(f"⚠️ Error in human-like mouse movement: {e}")
        return False

def solve_recaptcha_checkbox(page):
    """
    Attempt to solve reCAPTCHA v2 checkbox with human-like behavior
    """
    print("🤖 Attempting to solve reCAPTCHA checkbox...")
    
    try:
        # Find the reCAPTCHA anchor iframe (the one with the checkbox)
        anchor_iframe_selectors = [
            'iframe[src*="recaptcha/api2/anchor"]',
            'iframe[title="reCAPTCHA"]',
            'iframe[name*="a-"]'  # Anchor iframe usually has name starting with "a-"
        ]
        
        checkbox_frame = None
        
        for selector in anchor_iframe_selectors:
            if page.locator(selector).count() > 0:
                print(f"✅ Found reCAPTCHA anchor iframe: {selector}")
                checkbox_frame = page.frame_locator(selector).first
                
                # Check if this iframe contains the checkbox
                if checkbox_frame.locator('[role="checkbox"]').count() > 0:
                    print("✅ Confirmed checkbox is in this iframe")
                    break
        
        if not checkbox_frame:
            print("❌ Could not find reCAPTCHA anchor iframe with checkbox")
            return False
        
        # Add random delay before interaction
        print("⏳ Adding human-like delay before clicking...")
        time.sleep(random.randint(1000, 3000) / 1000)
        
        # Click the checkbox within the anchor iframe
        print("🖱️ Clicking reCAPTCHA checkbox...")
        checkbox_element = checkbox_frame.locator('[role="checkbox"]')
        
        # Try to get the checkbox position for human-like movement
        try:
            # Get the anchor iframe element for positioning
            anchor_iframe = page.locator('iframe[src*="recaptcha/api2/anchor"]').first
            iframe_box = anchor_iframe.bounding_box()
            
            if iframe_box:
                # Calculate approximate checkbox position within iframe
                checkbox_x = iframe_box['x'] + 25  # Checkbox is usually ~25px from left
                checkbox_y = iframe_box['y'] + 25  # And ~25px from top
                
                # Human-like mouse movement to checkbox area
                print("🔄 Moving mouse in human-like pattern...")
                page.mouse.move(
                    checkbox_x + random.randint(-50, -20), 
                    checkbox_y + random.randint(-20, 20)
                )
                time.sleep(random.randint(100, 300) / 1000)
                
                # Move closer to checkbox
                page.mouse.move(
                    checkbox_x + random.randint(-5, 5), 
                    checkbox_y + random.randint(-5, 5)
                )
                time.sleep(random.randint(50, 150) / 1000)
                
        except Exception as e:
            print(f"⚠️ Could not get iframe position for mouse movement: {e}")
        
        # Click the checkbox
        checkbox_element.click()
        print("✅ Clicked reCAPTCHA checkbox")
        
        # Wait for reCAPTCHA to process
        print("⏳ Waiting for reCAPTCHA verification...")
        time.sleep(random.randint(3000, 5000) / 1000)
        
        # Check if reCAPTCHA was solved (look for success indicators)
        success_indicators = [
            # Check if checkbox is marked as checked
            checkbox_frame.locator('[aria-checked="true"]'),
            # Check if there's a success checkmark
            checkbox_frame.locator('.recaptcha-checkbox-checked'),
            # Check for green checkmark
            checkbox_frame.locator('[style*="color: rgb(0, 153, 51)"]')
        ]
        
        for indicator in success_indicators:
            try:
                if indicator.count() > 0:
                    print("✅ reCAPTCHA appears to be solved! (checkbox checked)")
                    return True
            except:
                continue
        
        # Also check the main page for reCAPTCHA response token
        try:
            response_token = page.locator('.g-recaptcha-response').first
            if response_token.count() > 0:
                token_value = response_token.get_attribute('value')
                if token_value and len(token_value) > 10:
                    print("✅ reCAPTCHA response token found - likely solved!")
                    return True
        except:
            pass
        
        # Check if an image challenge appeared
        challenge_iframe_visible = False
        try:
            challenge_iframe = page.locator('iframe[src*="recaptcha/api2/bframe"]')
            if challenge_iframe.count() > 0:
                challenge_box = challenge_iframe.first.bounding_box()
                if challenge_box and challenge_box['height'] > 10:
                    challenge_iframe_visible = True
                    print("🖼️ Image challenge appeared - this requires manual solving")
        except:
            pass
        
        if challenge_iframe_visible:
            print("❌ reCAPTCHA image challenge detected - cannot solve automatically")
            print("💡 This requires human intervention to solve the image puzzle")
            return False
        
        # If we can't detect success but no challenge appeared, assume it worked
        print("⚠️ Cannot confirm reCAPTCHA status, but no challenge detected - proceeding...")
        return True
        
    except Exception as e:
        print(f"❌ Error solving reCAPTCHA: {e}")
        return False

def extract_code_from_recent_email(gmail_user, gmail_app_password):
    """
    Fallback: Extract code from the most recent Mawaqit email, regardless of age
    """
    print("🔍 Fallback: Looking for code in most recent Mawaqit email...")
    
    try:
        imap = imaplib.IMAP4_SSL("imap.gmail.com")
        imap.login(gmail_user, gmail_app_password)
        imap.select("inbox")

        status, messages = imap.search(None, 'ALL')
        if status != 'OK' or not messages[0]:
            return None

        mail_ids = messages[0].split()
        
        for mail_id in reversed(mail_ids[-50:]):
            try:
                status, msg_data = imap.fetch(mail_id, "(RFC822)")
                if status != 'OK':
                    continue
                    
                raw_msg = msg_data[0][1]
                msg = email.message_from_bytes(raw_msg)
                
                sender = msg.get('From', '').lower()
                
                if not any(domain in sender for domain in ['mawaqit.net', 'mawaqit.com']):
                    continue
                
                print(f"🔍 Found Mawaqit email from: {sender}")
                
                body = ""
                if msg.is_multipart():
                    for part in msg.walk():
                        content_type = part.get_content_type()
                        if content_type in ["text/plain", "text/html"]:
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

                if not body:
                    continue
                
                code_patterns = [
                    r'\b(\d{6})\b',
                    r'verification.*?(\d{6})',
                    r'code.*?(\d{6})',
                ]
                
                for pattern in code_patterns:
                    matches = re.findall(pattern, body, re.IGNORECASE | re.DOTALL)
                    if matches:
                        code = matches[-1]
                        if code.isdigit() and len(code) == 6:
                            print(f"✅ Extracted code from recent email: {code}")
                            imap.close()
                            imap.logout()
                            return code
                
            except Exception as e:
                continue
        
        imap.close()
        imap.logout()
        
    except Exception as e:
        print(f"❌ Error in fallback email extraction: {e}")
    
    return None

def get_latest_mawaqit_2fa_code(gmail_user, gmail_app_password, max_wait=120):
    """
    Fetch the latest 2FA code from Gmail for Mawaqit - extended wait time
    """
    print("🔍 Checking Gmail for 2FA code...")
    
    start_time = time.time()
    attempt = 0
    
    while time.time() - start_time < max_wait:
        attempt += 1
        print(f"🔄 Attempt {attempt} to find 2FA code...")
        
        try:
            print("📧 Connecting to Gmail...")
            imap = imaplib.IMAP4_SSL("imap.gmail.com")
            imap.login(gmail_user, gmail_app_password)
            imap.select("inbox")
            print("✅ Connected to Gmail successfully")

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
            
            recent_emails = mail_ids[-20:]
            print(f"🔍 Checking {len(recent_emails)} most recent emails...")
            
            for i, mail_id in enumerate(reversed(recent_emails)):
                try:
                    print(f"📧 Checking email {i+1}/{len(recent_emails)}...")
                    
                    status, msg_data = imap.fetch(mail_id, "(RFC822)")
                    if status != 'OK':
                        continue
                        
                    raw_msg = msg_data[0][1]
                    msg = email.message_from_bytes(raw_msg)
                    
                    sender = msg.get('From', '')
                    subject = msg.get('Subject', '')
                    date_str = msg.get('Date', '')
                    
                    print(f"   From: {sender}")
                    print(f"   Subject: {subject}")
                    print(f"   Date: {date_str}")
                    
                    sender_lower = sender.lower()
                    subject_lower = subject.lower()
                    
                    is_mawaqit = any(domain in sender_lower for domain in ['mawaqit.net', 'mawaqit.com'])
                    has_verification_keywords = any(keyword in subject_lower for keyword in ['verification', 'code', 'login', 'authenticate', 'security', 'authentication'])
                    
                    if not is_mawaqit and not has_verification_keywords:
                        print("   ⏭️ Not from Mawaqit or verification-related, skipping...")
                        continue
                    
                    print("   ✅ Email looks relevant, checking content...")
                    
                    try:
                        email_date = email.utils.parsedate_to_datetime(msg['Date'])
                        time_diff = (datetime.now(email_date.tzinfo) - email_date).total_seconds()
                        print(f"   ⏰ Email age: {time_diff/60:.1f} minutes")
                        
                        max_age = 7200 if is_mawaqit else 300
                        if time_diff > max_age:
                            print(f"   ⏳ Email too old (>{max_age/60:.0f} min), skipping...")
                            continue
                        else:
                            print(f"   ✅ Email is within acceptable age limit ({max_age/60:.0f} min)")
                    except Exception as e:
                        print(f"   ⚠️ Could not parse email date: {e}")
                        if not is_mawaqit:
                            continue
                    
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
                    
                    verification_keywords = ['verification', 'verify', 'authenticate', 'login', 'code', 'mawaqit', 'security']
                    body_lower = body.lower()
                    
                    matching_keywords = [kw for kw in verification_keywords if kw in body_lower]
                    if matching_keywords:
                        print(f"   ✅ Found verification keywords: {matching_keywords}")
                    else:
                        print("   ⏳ No verification keywords in body, skipping...")
                        continue
                    
                    code_patterns = [
                        r'\b(\d{6})\b',
                        r'verification.*?(\d{6})',
                        r'code.*?(\d{6})',
                        r'(\d{6}).*?verification',
                        r'(\d{6}).*?code',
                    ]
                    
                    for pattern_name, pattern in enumerate(code_patterns):
                        code_matches = re.findall(pattern, body, re.IGNORECASE | re.DOTALL)
                        if code_matches:
                            code = code_matches[-1]
                            print(f"   ✅ Found 2FA code with pattern {pattern_name + 1}: {code}")
                            
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
            time.sleep(15)
            
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
    
    current_month = datetime.now().strftime('%B')
    athan_csv_path = os.path.join(prayer_times_dir, f'athan_times_{current_month}.csv')
    iqama_csv_path = os.path.join(prayer_times_dir, f'iqama_times_{current_month}.csv')
    
    print(f"🗓️ Current month: {current_month}")
    print(f"📂 Looking for Athan CSV: {athan_csv_path}")
    print(f"📂 Looking for Iqama CSV: {iqama_csv_path}")
    
    if not os.path.exists(athan_csv_path) or not os.path.exists(iqama_csv_path):
        print(f"❌ CSV files not found:")
        print(f"   Athan exists: {os.path.exists(athan_csv_path)}")
        print(f"   Iqama exists: {os.path.exists(iqama_csv_path)}")
        
        if os.path.exists(prayer_times_dir):
            print(f"📁 Files in {prayer_times_dir}:")
            for file in os.listdir(prayer_times_dir):
                print(f"   - {file}")
        
        return False
    
    prayer_times = read_prayer_times_csv(athan_csv_path, iqama_csv_path)
    if not prayer_times:
        print("❌ No prayer times found in CSV files")
        return False
    
    sample_day = list(prayer_times.keys())[0]
    print(f"📊 Sample data for day {sample_day}:")
    print(f"   Athan: {prayer_times[sample_day]['athan']}")
    print(f"   Iqama: {prayer_times[sample_day]['iqama']}")
    
    with sync_playwright() as p:
        is_ci = bool(os.getenv('CI'))
        is_github_actions = bool(os.getenv('GITHUB_ACTIONS')) 
        has_display = bool(os.getenv('DISPLAY'))
        is_headless = is_ci or is_github_actions or not has_display
        
        print(f"🖥️ Environment: CI={is_ci}, GitHub Actions={is_github_actions}, Display={has_display}")
        print(f"🖥️ Running in {'headless' if is_headless else 'headed'} mode")
        
        browser = p.chromium.launch(
            headless=is_headless,
            args=[
                '--no-sandbox',
                '--disable-blink-features=AutomationControlled',
                '--disable-dev-shm-usage',
                '--disable-extensions',
                '--no-first-run',
                '--disable-default-apps',
                '--disable-infobars',
                '--window-size=1920,1080',
                '--user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
            ]
        )
        context = browser.new_context(
            viewport={'width': 1920, 'height': 1080},
            user_agent='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
        )
        
        # Add stealth JavaScript to hide automation
        context.add_init_script("""
            Object.defineProperty(navigator, 'webdriver', {
                get: () => undefined,
            });
            
            Object.defineProperty(navigator, 'plugins', {
                get: () => [1, 2, 3, 4, 5],
            });
            
            Object.defineProperty(navigator, 'languages', {
                get: () => ['en-US', 'en'],
            });
            
            window.chrome = {
                runtime: {},
            };
        """)
        
        page = context.new_page()
        
        try:
            print("🌐 Navigating to Mawaqit login...")
            page.goto("https://mawaqit.net/en/backoffice/login", wait_until="networkidle")
            
            print("📝 Filling login credentials...")
            page.fill('input[type="email"]', mawaqit_email)
            page.fill('input[type="password"]', mawaqit_password)
            
            print("🤖 Checking for reCAPTCHA...")
            recaptcha_solved = True
            
            if page.locator('.g-recaptcha, [data-sitekey], iframe[src*="recaptcha"]').count() > 0:
                print("🛡️ reCAPTCHA detected - attempting to solve...")
                recaptcha_solved = solve_recaptcha_checkbox(page)
                
                if not recaptcha_solved:
                    print("❌ Failed to solve reCAPTCHA automatically")
                    print("💡 Manual intervention needed")
                    return False
            
            time.sleep(random.randint(1000, 2000) / 1000)
            
            page.screenshot(path="debug_before_login.png")
            
            print("🔑 Submitting login...")
            if human_like_mouse_move(page, 'button[type="submit"]'):
                page.click('button[type="submit"]')
            else:
                page.click('button[type="submit"]')
            
            print("⏳ Waiting for login response...")
            
            page.wait_for_load_state("networkidle", timeout=30000)
            page.wait_for_timeout(3000)
            
            page.screenshot(path="debug_after_login.png")
            
            current_url = page.url
            page_content = page.content().lower()
            
            print(f"🌐 Current URL: {current_url}")
            
            if "login" in current_url.lower():
                print("❌ Still on login page - login may have failed")
                
                error_selectors = [
                    '.error', '.alert-danger', '.invalid-feedback',
                    'text="Invalid"', 'text="Wrong"', 'text="Incorrect"'
                ]
                
                for error_selector in error_selectors:
                    if page.locator(error_selector).count() > 0:
                        error_text = page.locator(error_selector).inner_text()
                        print(f"🚨 Login error found: {error_text}")
                
                if page.locator('.g-recaptcha, [data-sitekey]').count() > 0:
                    print("🛡️ reCAPTCHA is likely blocking the login")
                    print("💡 Manual intervention needed - reCAPTCHA must be solved by human")
                    return False
                
                print("❌ Login failed for unknown reason")
                return False
            
            print("🔍 Checking if 2FA is required...")
            
            if "verification" in page_content or "code" in page_content or "authenticate" in page_content:
                print("📧 2FA page detected!")
                
                print("🔄 Looking for resend code button...")
                resend_selectors = [
                    'button:has-text("Resend")',
                    'a:has-text("Resend")', 
                    'button:has-text("Send new code")',
                    'button:has-text("Send again")',
                    '.resend-code',
                    '[data-action="resend"]'
                ]
                
                for resend_selector in resend_selectors:
                    if page.locator(resend_selector).count() > 0:
                        try:
                            print(f"✅ Found resend button: {resend_selector}")
                            page.click(resend_selector)
                            print("🔄 Clicked resend - waiting for new email...")
                            page.wait_for_timeout(5000)
                            break
                        except Exception as e:
                            print(f"⚠️ Failed to click resend: {e}")
                            continue
                else:
                    print("⚠️ No resend button found, proceeding with existing 2FA flow...")
                
                print("📧 Waiting for 2FA code from Gmail...")
                verification_code = get_latest_mawaqit_2fa_code(gmail_user, gmail_app_password, max_wait=120)
                
                if not verification_code:
                    print("❌ Still no 2FA code found")
                    print("🔍 Let's try to use the most recent Mawaqit email even if it's old...")
                    
                    verification_code = extract_code_from_recent_email(gmail_user, gmail_app_password)
                
                if not verification_code:
                    print("❌ Failed to get any 2FA code")
                    return False
                
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
            page.screenshot(path="debug_logged_in.png")
            
            print("🏛️ Looking for prayer times configuration...")
            
            prayer_time_links = [
                'text="Athan & Iqama"',
                'text="Prayer Times"',
                'text="Configuration"',
                'a[href*="athan"]',
                'a[href*="prayer"]',
                'a[href*="times"]'
            ]
            
            navigation_success = False
            for link_selector in prayer_time_links:
                if page.locator(link_selector).count() > 0:
                    print(f"🔗 Found link: {link_selector}")
                    try:
                        page.click(link_selector)
                        page.wait_for_load_state("networkidle")
                        print(f"✅ Clicked: {link_selector}")
                        navigation_success = True
                        break
                    except Exception as e:
                        print(f"⚠️ Failed to click {link_selector}: {e}")
                        continue
            
            if not navigation_success:
                print("⚠️ Could not find prayer times configuration link")
                page.screenshot(path="debug_no_navigation.png")
            
            page.screenshot(path="debug_prayer_times_page.png")
            
            print("📝 Looking for prayer times form...")
            
            today = datetime.now().day
            print(f"📅 Today is day {today} of the month")
            
            filled_days = 0
            errors = []
            
            for day, times in prayer_times.items():
                try:
                    day_marker = "🔥 TODAY" if day == today else ""
                    print(f"Processing day {day} {day_marker}...")
                    
                    if day == today:
                        athan = times['athan']
                        iqama = times['iqama']
                        print(f"🕐 Today's Athan times: Fajr={athan['fajr']}, Dhuhr={athan['dhuhr']}, Asr={athan['asr']}, Maghrib={athan['maghrib']}, Isha={athan['isha']}")
                        print(f"🕐 Today's Iqama times: Fajr={iqama['fajr']}, Dhuhr={iqama['dhuhr']}, Asr={iqama['asr']}, Maghrib={iqama['maghrib']}, Isha={iqama['isha']}")
                    
                    day_filled = False
                    
                    selectors_to_try = [
                        f'input[name*="day_{day}"]',
                        f'input[data-day="{day}"]', 
                        f'input[id*="day_{day}"]',
                        f'td[data-day="{day}"] input',
                        f'.day-{day} input',
                        f'[data-date*="{day:02d}"] input'
                    ]
                    
                    for base_selector in selectors_to_try:
                        if page.locator(base_selector).count() > 0:
                            print(f"   ✅ Found inputs with selector: {base_selector}")
                            
                            prayers = ['fajr', 'dhuhr', 'asr', 'maghrib', 'isha']
                            
                            for prayer in prayers:
                                athan_time = times['athan'].get(prayer, '')
                                if athan_time:
                                    athan_selectors = [
                                        f'{base_selector}[name*="{prayer}"][name*="athan"]',
                                        f'{base_selector}[name*="{prayer}_athan"]',
                                        f'{base_selector}.{prayer}.athan',
                                        f'{base_selector}[placeholder*="{prayer.title()}"]'
                                    ]
                                    
                                    for athan_sel in athan_selectors:
                                        try:
                                            if page.locator(athan_sel).count() > 0:
                                                page.fill(athan_sel, athan_time)
                                                print(f"   ✅ Filled {prayer} athan: {athan_time}")
                                                break
                                        except Exception as e:
                                            continue
                                
                                iqama_time = times['iqama'].get(prayer, '')
                                if iqama_time:
                                    iqama_selectors = [
                                        f'{base_selector}[name*="{prayer}"][name*="iqama"]',
                                        f'{base_selector}[name*="{prayer}_iqama"]', 
                                        f'{base_selector}.{prayer}.iqama'
                                    ]
                                    
                                    for iqama_sel in iqama_selectors:
                                        try:
                                            if page.locator(iqama_sel).count() > 0:
                                                page.fill(iqama_sel, iqama_time)
                                                print(f"   ✅ Filled {prayer} iqama: {iqama_time}")
                                                break
                                        except Exception as e:
                                            continue
                            
                            day_filled = True
                            break
                    
                    if day_filled:
                        filled_days += 1
                    else:
                        errors.append(f"Could not find inputs for day {day}")
                        if day == today:
                            page.screenshot(path=f"debug_day_{day}_not_found.png")
                    
                    page.wait_for_timeout(50)
                    
                except Exception as e:
                    error_msg = f"Error filling day {day}: {e}"
                    print(f"⚠️ {error_msg}")
                    errors.append(error_msg)
                    continue
            
            print(f"✅ Filled prayer times for {filled_days} days")
            if errors:
                print(f"⚠️ Encountered {len(errors)} errors:")
                for error in errors[:5]:
                    print(f"   - {error}")
            
            print("💾 Looking for save button...")
            
            save_selectors = [
                'button:has-text("Save")',
                'input[type="submit"][value*="Save"]',
                'button[type="submit"]',
                'button:has-text("Update")',
                '.btn-save',
                '.btn-primary:has-text("Save")',
                '#save-btn'
            ]
            
            saved = False
            for save_selector in save_selectors:
                if page.locator(save_selector).count() > 0:
                    try:
                        page.click(save_selector)
                        saved = True
                        print(f"✅ Save button clicked: {save_selector}")
                        break
                    except Exception as e:
                        print(f"⚠️ Failed to click save button {save_selector}: {e}")
                        continue
            
            if not saved:
                print("⚠️ Could not find or click save button")
                page.screenshot(path="debug_save_button.png")
            else:
                page.wait_for_load_state("networkidle")
                page.wait_for_timeout(2000)
                print("✅ Save completed!")
            
            page.screenshot(path="debug_final_state.png")
            
            print("📝 Prayer times form processing completed!")
            
            return True
            
        except Exception as e:
            print(f"❌ Error during upload: {e}")
            page.screenshot(path="debug_error.png")
            return False
        finally:
            if not is_headless:
                print("⏸️  Browser will stay open for 30 seconds for debugging...")
                time.sleep(30)
            browser.close()

def main():
    """
    Main entry point
    """
    mawaqit_email = os.getenv('MAWAQIT_USER')
    mawaqit_password = os.getenv('MAWAQIT_PASS')
    gmail_user = os.getenv('GMAIL_USER')
    gmail_app_password = os.getenv('GMAIL_APP_PASSWORD')
    
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
