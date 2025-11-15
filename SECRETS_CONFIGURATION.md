# GitHub Actions Secrets Configuration

This document outlines the required GitHub Actions secrets for the PrayerTimesScraper repository.

## Required Secrets

The following secrets must be configured in your GitHub repository settings (Settings → Secrets and variables → Actions → Repository secrets):

### 1. **MAWAQIT_USER**
- **Description**: Your Mawaqit account username/email
- **Used by**: All automation workflows that interact with Mawaqit
- **Required**: Yes

### 2. **MAWAQIT_PASS**
- **Description**: Your Mawaqit account password
- **Used by**: All automation workflows that interact with Mawaqit
- **Required**: Yes

### 3. **GMAIL_USER**
- **Description**: Gmail account email address for receiving 2FA codes
- **Used by**: 2FA authentication during Mawaqit login
- **Required**: Yes (for 2FA-enabled accounts)
- **Note**: Must have IMAP enabled

### 4. **GMAIL_APP_PASSWORD**
- **Description**: Gmail app-specific password (not your regular Gmail password)
- **Used by**: Accessing Gmail via IMAP to retrieve 2FA codes
- **Required**: Yes (for 2FA-enabled accounts)
- **How to generate**: https://support.google.com/accounts/answer/185833

### 5. **TWOCAPTCHA_API_KEY**
- **Description**: API key for 2Captcha service (for solving reCAPTCHA)
- **Used by**: Automated captcha solving during login
- **Required**: Optional (if reCAPTCHA is present on login page)
- **How to get**: Sign up at https://2captcha.com

## Configuration Status

✅ **config.py** - Already properly configured to read from environment variables
✅ **mawaqit-automation.yml** - Updated to use correct secret names
✅ **main.yml** - Verified, uses correct secret names
✅ **prayer-times.yml** - Verified, no secrets needed (only extracts prayer times)

## How to Set Secrets

1. Go to your GitHub repository
2. Click on **Settings** → **Secrets and variables** → **Actions**
3. Click **New repository secret**
4. Add each secret with the exact name listed above
5. Paste the corresponding value
6. Click **Add secret**

## Verification

All secrets are accessed via `os.getenv()` in the `config.py` file, which means:
- They can be set as environment variables locally for testing
- They are automatically available from GitHub Actions secrets
- They can also be loaded from a `.env` file for local development (not committed to Git)

## Security Notes

- Never commit actual secret values to the repository
- Never log or print secret values in workflows
- Use app-specific passwords for Gmail (not your main password)
- Rotate secrets regularly for security
- The `.env` file (if created) is already in `.gitignore`

## Changes Made

The following change was made to ensure consistency:
- **mawaqit-automation.yml**: Changed `NO_CAPTCHA_API_KEY` to `TWOCAPTCHA_API_KEY` to match the config.py expectation

All secrets are now properly aligned across the codebase and workflows.
