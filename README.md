# Prayer Times Scraper & Mawaqit Uploader

Automated system for scraping prayer times and uploading them to Mawaqit.

## Overview

This project automates the process of:
1. Scraping prayer times from a source
2. Uploading the times to Mawaqit (both Athan and Iqama times)
3. Running on a scheduled basis via GitHub Actions

## Configuration

### Required Environment Variables

The following environment variables are **required**:

- `MAWAQIT_USER`: Your Mawaqit account email/username
- `MAWAQIT_PASS`: Your Mawaqit account password

### Optional Environment Variables

For enhanced functionality (2FA, captcha solving):

- `GMAIL_USER`: Gmail address for receiving 2FA codes (if 2FA is enabled)
- `GMAIL_APP_PASSWORD`: Gmail app-specific password for IMAP access
- `TWOCAPTCHA_API_KEY`: API key for 2Captcha service (for solving reCAPTCHA)

### Additional Settings

- `PRAYER_TIMES_DIR`: Directory containing prayer times CSV files (default: `./prayer_times`)
- `HEADLESS`: Run browser in headless mode (default: `true` in CI/CD)
- `DEBUG_MODE`: Enable debug mode with screenshots (default: `false`)

## Running Locally

### Prerequisites

1. Python 3.11+
2. Node.js (for prayer times extraction)
3. Chrome/Chromium browser

### Setup

```bash
# Install Python dependencies
pip install -r requirements.txt

# Install Playwright browsers
playwright install chromium

# Install Node.js dependencies (for prayer times scraper)
npm install
```

### Local Development with .env File

Create a `.env` file in the project root (never commit this file):

```env
MAWAQIT_USER=your_email@example.com
MAWAQIT_PASS=your_password
GMAIL_USER=your_gmail@gmail.com
GMAIL_APP_PASSWORD=your_app_password
TWOCAPTCHA_API_KEY=your_captcha_key
```

### Running the Uploader

```bash
# Run directly (will use .env file if present, or environment variables)
python mawaqit_uploader.py

# Or set environment variables directly
export MAWAQIT_USER=your_email@example.com
export MAWAQIT_PASS=your_password
python mawaqit_uploader.py
```

## GitHub Actions (CI/CD)

The project is configured to run automatically via GitHub Actions.

### Setting Up Secrets

1. Go to your repository on GitHub
2. Navigate to **Settings** → **Secrets and variables** → **Actions**
3. Add the following repository secrets:
   - `MAWAQIT_USER`
   - `MAWAQIT_PASS`
   - `GMAIL_USER` (optional)
   - `GMAIL_APP_PASSWORD` (optional)
   - `TWOCAPTCHA_API_KEY` (optional)

### Workflows

- **mawaqit-automation.yml**: Main workflow that runs weekly to update prayer times
- **prayer-times.yml**: Extracts prayer times from source

### CI/CD Behavior

When running in GitHub Actions:
- Environment variables are automatically loaded from GitHub secrets
- No `.env` file is required or expected
- Warnings about missing `.env` files are suppressed
- Clear "Running in CI/CD environment" message is displayed

## Configuration Priority

The configuration system follows this priority order:

1. **Environment variables** (highest priority) - from GitHub secrets or shell
2. `.env` file in current directory
3. `.env` file in package directory
4. `.env` file in parent directory

Environment variables always override `.env` file values.

## Troubleshooting

### "Missing required core config" error

Ensure `MAWAQIT_USER` and `MAWAQIT_PASS` are set either:
- As environment variables, OR
- In a `.env` file in the project root

### "No .env files found" message in local development

This is informational only. If you see this message:
- In **CI/CD**: This is normal and expected (not shown)
- In **local development**: Either create a `.env` file or set environment variables

### Optional items missing warning

If you see warnings about `GMAIL_USER`, `GMAIL_APP_PASSWORD`, or `TWOCAPTCHA_API_KEY`:
- These are optional features
- 2FA and captcha solving will be disabled
- The uploader will still work if 2FA is not required

## Architecture

- **config.py**: Configuration management with environment variable support
- **mawaqit_uploader.py**: Main uploader using Selenium for browser automation
- **prayer_times_scraper.py**: Prayer times extraction (if applicable)
- **email_helper.py**: Gmail IMAP helper for 2FA code retrieval

## License

See LICENSE file for details.

## Support

For issues, questions, or contributions, please open an issue on GitHub.
