import time
import requests
from playwright.sync_api import sync_playwright

# ------------------------------
# NoCaptcha AI Solver Function
# ------------------------------
def solve_recaptcha_with_nocaptchaai(page, site_key, api_key="alsalaam465-80e91086-9f21-c204-2d46-c8e4a8a5ef3f", target_url=None):
    if not target_url:
        target_url = page.url

    print("🤖 Sending reCAPTCHA to NoCaptcha AI for solving...")
    
    create_task_payload = {
        "clientKey": api_key,
        "task": {
            "type": "NoCaptchaTaskProxyless",
            "websiteURL": target_url,
            "websiteKey": site_key
        }
    }

    try:
        task_response = requests.post("https://api.nocaptchaai.com/solve", json=create_task_payload).json()
        if "taskId" not in task_response:
            print(f"❌ Failed to create CAPTCHA task: {task_response}")
            return False
        
        task_id = task_response["taskId"]
        print(f"✅ CAPTCHA task created with ID: {task_id}")
        
        # Polling for result
        for attempt in range(1, 20):
            time.sleep(5)
            result_response = requests.post("https://api.nocaptchaai.com/getTaskResult", json={"clientKey": api_key, "taskId": task_id}).json()
            if result_response.get("status") == "ready":
                g_recaptcha_response = result_response["solution"]["gRecaptchaResponse"]
                print("✅ CAPTCHA solved successfully!")
                
                # Inject token into page
                page.evaluate(f'document.getElementById("g-recaptcha-response").innerHTML="{g_recaptcha_response}";')
                return True
            else:
                print(f"⏳ Waiting for CAPTCHA solution... (attempt {attempt})")
        
        print("❌ CAPTCHA solving timed out")
        return False

    except Exception as e:
        print(f"❌ Error solving CAPTCHA via NoCaptcha AI: {e}")
        return False

# ------------------------------
# Main Automation
# ------------------------------
def upload_to_mawaqit():
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()

        # Navigate to Mawaqit login page
        page.goto("https://mawaqit.com/login")

        # Fill in login info
        page.fill('input[name="email"]', "YOUR_EMAIL_HERE")
        page.fill('input[name="password"]', "YOUR_PASSWORD_HERE")

        # Solve CAPTCHA if detected
        if page.locator('.g-recaptcha, [data-sitekey], iframe[src*="recaptcha"]').count() > 0:
            print("🛡️ reCAPTCHA detected - attempting to solve via NoCaptcha AI...")
            
            site_key_elem = page.locator('[data-sitekey]').first
            if site_key_elem.count() > 0:
                site_key = site_key_elem.get_attribute('data-sitekey')
                recaptcha_solved = solve_recaptcha_with_nocaptchaai(page, site_key)
            else:
                print("❌ Could not find reCAPTCHA site key on page")
                recaptcha_solved = False
            
            if not recaptcha_solved:
                print("❌ CAPTCHA solving failed. Aborting.")
                browser.close()
                return
        
        # Submit login form
        page.click('button[type="submit"]')
        print("✅ Login submitted!")

        # Wait for login to complete
        page.wait_for_url("https://mawaqit.com/dashboard", timeout=15000)

        # Navigate to upload page and perform upload
        page.goto("https://mawaqit.com/upload")
        page.set_input_files('input[type="file"]', "YOUR_FILE_PATH_HERE")
        page.click('button[type="submit"]')
        print("✅ File upload submitted!")

        # Finish
        time.sleep(5)
        browser.close()

# ------------------------------
# Run the script
# ------------------------------
if __name__ == "__main__":
    upload_to_mawaqit()
