from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeoutError

MAWAQIT_URL = "https://mawaqit.net/en/backoffice/login"
EMAIL = "YOUR_EMAIL_HERE"
PASSWORD = "YOUR_PASSWORD_HERE"

def upload_to_mawaqit():
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)  # Always headless
        context = browser.new_context()
        page = context.new_page()

        # Go to login page
        page.goto(MAWAQIT_URL, wait_until="load")

        try:
            # Fill login form
            page.fill('input[name="email"]', EMAIL)
            page.fill('input[name="password"]', PASSWORD)

            # Click login and wait for navigation
            page.click('button[type="submit"]')

            # Wait for dashboard or any URL that indicates successful login
            page.wait_for_url("**/backoffice/**", timeout=60000)

        except PlaywrightTimeoutError:
            print("Login failed or dashboard did not load in time.")
            browser.close()
            return

        print("Login successful! Ready to upload data.")

        # --- Add your scraping/upload logic here ---
        # e.g., navigate to the section, fill forms, submit prayer times, etc.

        browser.close()

if __name__ == "__main__":
    upload_to_mawaqit()
