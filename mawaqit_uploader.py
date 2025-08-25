from playwright.sync_api import sync_playwright
import os

# Credentials from environment variables
MAWAQIT_USER = os.getenv("MAWAQIT_USER", "YOUR_EMAIL_HERE")
MAWAQIT_PASSWORD = os.getenv("MAWAQIT_PASSWORD", "YOUR_PASSWORD_HERE")
FILE_TO_UPLOAD = os.getenv("PRAYER_TIMES_FILE", "prayer_times.csv")

def upload_to_mawaqit():
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context()
        page = context.new_page()

        # Go to login page
        page.goto("https://mawaqit.net/en/backoffice/login")

        # Wait for login form
        page.wait_for_selector('input[name="email"]', timeout=60000)

        # Fill login credentials
        page.fill('input[name="email"]', MAWAQIT_USER)
        page.fill('input[name="password"]', MAWAQIT_PASSWORD)
        page.click('button[type="submit"]')

        # Wait for dashboard to load
        page.wait_for_url("**/backoffice/dashboard", timeout=60000)
        print("Login successful!")

        # Navigate to upload page
        page.goto("https://mawaqit.net/en/backoffice/prayer-times")
        page.wait_for_selector('input[type="file"]', timeout=60000)

        # Upload the prayer times file
        page.set_input_files('input[type="file"]', FILE_TO_UPLOAD)

        # Click upload button
        page.click('button[type="submit"]')

        # Wait for success message
        page.wait_for_selector("text=Upload successful", timeout=60000)
        print("Prayer times upload completed!")

        browser.close()

if __name__ == "__main__":
    upload_to_mawaqit()
