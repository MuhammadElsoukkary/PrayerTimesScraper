# upload_current_month.py
# -----------------------
# Logs into Mawaqit, then uploads exactly the CSV(s) that match the current month name.

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

# Directory where your CSVs live:
CSV_DIR      = "prayer_times"

# Pick “June” or “July” etc. based on how your files are named.
# We'll auto-detect the current month name in title-case:
CURRENT_MONTH = datetime.utcnow().strftime("%B")  # e.g. "June"

# Pattern: anything ending with “_<Month>.csv” in prayer_times/
GLOB_PATTERN = os.path.join(CSV_DIR, f"*_{CURRENT_MONTH}.csv")
# ────────────────────────────────────────────────────────────────────────────────

def fetch_csrf_token(html_text, field_name="_token"):
    """
    Given HTML text, scrape out the hidden field <input name="_token" value="..."> 
    (or whatever `field_name` is).
    """
    soup = BeautifulSoup(html_text, "html.parser")
    tag = soup.find("input", {"name": field_name})
    return tag["value"] if tag else None

def main():
    if not USERNAME or not PASSWORD:
        print("❌ Missing MAWAQIT_USER / MAWAQIT_PASS environment variables.")
        exit(1)

    session = requests.Session()

    # ─── (1) GET the login page to grab any CSRF token ──────────────────────────
    login_url = urljoin(MAWAQIT_BASE, LOGIN_PATH)
    print(f"→ Fetching login page: {login_url}")
    resp = session.get(login_url)
    resp.raise_for_status()
    csrf_token = fetch_csrf_token(resp.text, "_token")
    print(f"→ CSRF token for login: {csrf_token}")

    # ─── (2) POST credentials + CSRF to log in ─────────────────────────────────
    login_data = {"email": USERNAME, "password": PASSWORD}
    if csrf_token:
        login_data["_token"] = csrf_token

    print("→ Submitting login form…")
    login_resp = session.post(login_url, data=login_data)
    if login_resp.status_code not in (200, 302):
        print("❌ Login failed:", login_resp.status_code, login_resp.text)
        exit(1)
    print("→ Login succeeded (cookies set).")

    # (Optional) sanity-check: GET dashboard or some page behind login
    dash_url = urljoin(MAWAQIT_BASE, f"/{MOSQUE_SLUG}/dashboard")
    dash_resp = session.get(dash_url)
    if dash_resp.status_code != 200:
        print("❌ Unable to reach dashboard; aborting.")
        exit(1)
    print("→ Confirmed access to dashboard.")

    # ─── (3) Find only the CSV(s) for the current month ────────────────────────
    matching_csvs = glob.glob(GLOB_PATTERN)
    if not matching_csvs:
        print(f"⚠️ No CSVs found matching pattern: '{GLOB_PATTERN}'")
        print("Make sure your files are named like 'athan_times_June.csv' etc.")
        exit(0)  # nothing to upload, exit cleanly

    print(f"→ Found {len(matching_csvs)} CSV(s) for {CURRENT_MONTH}:")
    for f in matching_csvs:
        print("   •", f)

    # ─── (4) For each matching CSV, re-GET the upload page to obtain fresh CSRF ──
    for csv_path in matching_csvs:
        print(f"\n→ Preparing to upload '{csv_path}'")

        timetable_url = urljoin(MAWAQIT_BASE, f"/{MOSQUE_SLUG}/timetable")
        page_resp = session.get(timetable_url)
        page_resp.raise_for_status()
        upload_csrf = fetch_csrf_token(page_resp.text, "_token")
        print(f"   • Upload CSRF token: {upload_csrf}")

        # Build multipart data exactly as the form expects. 
        # Inspect DevTools → “Network” → “Form Data” for your actual field names.
        files = {
            # If Mawaqit’s form field is called "csv_file", use that.
            # Sometimes it’s “file” or “files[0]”. Adjust as needed.
            "csv_file": (os.path.basename(csv_path), open(csv_path, "rb"), "text/csv")
        }

        data = {}
        if upload_csrf:
            data["_token"] = upload_csrf

        # If the form has extra hidden fields (year/month), you can add:
        # data["year"] = str(datetime.utcnow().year)
        # data["month"] = f"{datetime.utcnow().month:02d}"
        # (But most Mawaqit CSV forms only need the file + token.)

        upload_url = urljoin(MAWAQIT_BASE, UPLOAD_PATH)
        print(f"   • POSTing to: {upload_url}")

        post_resp = session.post(upload_url, data=data, files=files)
        if post_resp.status_code in (200, 302):
            print(f"✔ Successfully uploaded '{csv_path}'")
        else:
            print(f"❌ Failed to upload '{csv_path}':")
            print(post_resp.status_code, post_resp.text[:200])
            exit(1)

    print("\nAll matching CSVs for this month have been uploaded. Done.")

if __name__ == "__main__":
    main()
