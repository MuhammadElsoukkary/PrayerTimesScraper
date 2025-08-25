from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeoutError

MAWAQIT_URL = "https://mawaqit.net/en/backoffice/login"
EMAIL = "YOUR_EMAIL_HERE"
PASSWORD = "YOUR_PASSWORD_HERE"

def upload_to_mawaqit():
    print("🚀 Starting Mawaqit upload process...")

    with sync_playwright() as p:
        print("🌐 Launching browser (headless)...")
        browser = p.chromium.launch(headless=True)
        context = browser.new_context()
        page = context.new_page()

        print(f"➡️ Navigating to {MAWAQIT_URL}")
        page.goto(MAWAQIT_URL, wait_until="load")

        try:
            print("✍️ Filling login form...")
            page.fill('input[name="email"]', EMAIL)
            page.fill('input[name="password"]', PASSWORD)

            print("🔑 Submitting login form...")
            page.click('button[type="submit"]')

            print("⏳ Waiting for dashboard to load...")
            page.wait_for_url("**/backoffice/**", timeout=60000)

        except PlaywrightTimeoutError:
            print("❌ Login failed or dashboard did not load in time.")
            browser.close()
            return

        print("✅ Login successful! Ready to upload data.")
        # --- Add your scraping/upload logic here ---

        browser.close()
        print("🛑 Browser closed. Process finished.")

if __name__ == "__main__":
    upload_to_mawaqit()
