# upload_current_month.py (debug version)
# ---------------------------------------
# Logs into Mawaqit, but first prints out what it thinks the current month is
# and which files exist under prayer_times/. This will help us catch mismatches.

import os
import glob
import requests
from bs4 import BeautifulSoup
from urllib.parse import urljoin
from datetime import datetime

# ─── CONFIGURATION ─────────────────────────────────────────────────────────────
MAWAQIT_BASE = "https://mawaqit.net"
MOSQUE_SLUG  = "your-mosque-slug"        # e.g. "al-salam-masjid"
LOGIN_PATH   = "/login"
UPLOAD_PATH  = f"/{MOSQUE_SLUG}/timetable/upload"

USERNAME     = os.environ.get("MAWAQIT_USER")
PASSWORD     = os.environ.get("MAWAQIT_PASS")

CSV_DIR      = "prayer_times"
# Compute month name from UTC now:
NOW_UTC      = datetime.utcnow()
CURRENT_MONTH = NOW_UTC.strftime("%B")  # e.g. "June"
GLOB_PATTERN = os.path.join(CSV_DIR, f"*_{CURRENT_MONTH}.csv")
# ────────────────────────────────────────────────────────────────────────────────

def fetch_csrf_token(html_text, field_name="_token"):
    soup = BeautifulSoup(html_text, "html.parser")
    tag = soup.find("input", {"name": field_name})
    return tag["value"] if tag else None

def main():
    # 1) Print debug info: UTC now, computed month, and all files in prayer_times/
    print("===== DEBUG: upload_current_month.py =====")
    print(f"• Runner UTC time is: {NOW_UTC.isoformat()}Z")
    print(f"• CURRENT_MONTH = '{CURRENT_MONTH}'")
    print("• All files under prayer_times/ directory:")
    try:
        all_files = os.listdir(CSV_DIR)
    except FileNotFoundError:
        all_files = []
    for f in all_files:
        print(f"    - {f}")
    print(f"• Looking for files matching pattern: '{GLOB_PATTERN}'")

    matching_csvs = glob.glob(GLOB_PATTERN)
    if not matching_csvs:
        print("⚠️  No CSVs found matching that pattern. Exiting without upload.")
        exit(0)

    print(f"→ Found {len(matching_csvs)} matching CSV(s):")
    for f in matching_csvs:
        print(f"   • {f}")

    # 2) Verify we have username/password
    if not USERNAME or not PASSWORD:
        print("❌ Missing MAWAQIT_USER or MAWAQIT_PASS environment variables.")
        exit(1)

    session = requests.Session()

    # 3) GET login page, fetch CSRF
    login_url = urljoin(MAWAQIT_BASE, LOGIN_PATH)
    print(f"→ Fetching login page: {login_url}")
    resp = session.get(login_url)
    if resp.status_code != 200:
        print("❌ Unable to load login page. Status:", resp.status_code)
        exit(1)
    csrf_token = fetch_csrf_token(resp.text, "_token")
    print(f"→ CSRF token for login: {csrf_token}")

    # 4) POST credentials to login
    print("→ Submitting login form...")
    login_data = {"email": USERNAME, "password": PASSWORD}
    if csrf_token:
        login_data["_token"] = csrf_token

    login_resp = session.post(login_url, data=login_data)
    if login_resp.status_code not in (200, 302):
        print("❌ Login failed:", login_resp.status_code, login_resp.text[:200])
        exit(1)
    print("→ Login succeeded (cookies set).")

    # 5) Optionally check dashboard access
    dash_url = urljoin(MAWAQIT_BASE, f"/{MOSQUE_SLUG}/dashboard")
    dash_resp = session.get(dash_url)
    if dash_resp.status_code != 200:
        print("❌ Could not reach dashboard after login. Status:", dash_resp.status_code)
        exit(1)
    print("→ Dashboard loaded OK.")

    # 6) For each matching CSV, fetch timetable page & get fresh CSRF, then upload
    for csv_path in matching_csvs:
        print(f"\n→ Preparing to upload '{csv_path}'")
        timetable_url = urljoin(MAWAQIT_BASE, f"/{MOSQUE_SLUG}/timetable")
        page_resp = session.get(timetable_url)
        if page_resp.status_code != 200:
            print("❌ Failed to load timetable page. Status:", page_resp.status_code)
            exit(1)
        upload_csrf = fetch_csrf_token(page_resp.text, "_token")
        print(f"   • Upload CSRF token: {upload_csrf}")

        files = {
            # Replace "csv_file" with the actual field name from DevTools if different
            "csv_file": (os.path.basename(csv_path), open(csv_path, "rb"), "text/csv")
        }
        data = {}
        if upload_csrf:
            data["_token"] = upload_csrf

        upload_url = urljoin(MAWAQIT_BASE, UPLOAD_PATH)
        print(f"   • POSTing to: {upload_url}")
        post_resp = session.post(upload_url, data=data, files=files)
        if post_resp.status_code in (200, 302):
            print(f"✔ Successfully uploaded '{csv_path}'")
        else:
            print(f"❌ Failed to upload '{csv_path}':", post_resp.status_code, post_resp.text[:200])
            exit(1)

    print("\n✅ All matching CSVs for this month have been uploaded (debug mode).")

if __name__ == "__main__":
    main()
