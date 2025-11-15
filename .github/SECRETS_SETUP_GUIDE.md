# Quick Setup Guide for GitHub Actions Secrets

This is a quick reference for setting up the required secrets in your GitHub repository.

## Step-by-Step Setup

### 1. Navigate to Repository Settings
```
Your Repository → Settings → Secrets and variables → Actions → New repository secret
```

### 2. Add Each Secret

Copy and paste these exact names (case-sensitive):

#### Secret 1: MAWAQIT_USER
```
Name: MAWAQIT_USER
Value: your-mawaqit-email@example.com
```

#### Secret 2: MAWAQIT_PASS
```
Name: MAWAQIT_PASS
Value: your-mawaqit-password
```

#### Secret 3: GMAIL_USER
```
Name: GMAIL_USER
Value: your-gmail@gmail.com
```

#### Secret 4: GMAIL_APP_PASSWORD
```
Name: GMAIL_APP_PASSWORD
Value: your-16-character-app-password
```
**Note**: This is NOT your regular Gmail password. Generate it at:
https://myaccount.google.com/apppasswords

#### Secret 5: TWOCAPTCHA_API_KEY
```
Name: TWOCAPTCHA_API_KEY
Value: your-2captcha-api-key
```
**Optional** - Only needed if Mawaqit login has reCAPTCHA.
Sign up at: https://2captcha.com

## Verification Checklist

After adding all secrets:

- [ ] All 5 secret names match exactly (case-sensitive)
- [ ] GMAIL_APP_PASSWORD is a 16-character app password (not regular password)
- [ ] Gmail has 2-factor authentication enabled
- [ ] Gmail has IMAP access enabled
- [ ] Test by manually triggering the workflow

## Testing

1. Go to **Actions** tab
2. Select **Update Mawaqit Prayer Times** workflow
3. Click **Run workflow**
4. Select branch and click **Run workflow**
5. Check the workflow logs for success

## Troubleshooting

### "Missing required environment variables"
→ Double-check secret names are spelled exactly right

### "Gmail authentication failed"
→ Ensure you're using an app password, not your regular password
→ Enable IMAP: Gmail Settings → See all settings → Forwarding and POP/IMAP

### "2FA code not found"
→ Check that GMAIL_USER and GMAIL_APP_PASSWORD are correct
→ Verify emails from no-reply@mawaqit.net aren't filtered to spam

### "reCAPTCHA solving failed"
→ Verify TWOCAPTCHA_API_KEY is correct
→ Check your 2Captcha account balance

## Security Best Practices

✅ Use app-specific passwords (never your main password)
✅ Rotate secrets periodically
✅ Monitor secret usage in workflow logs
✅ Never commit secrets to the repository
✅ Don't share or expose secret values

## Additional Resources

- [GitHub Actions Secrets Documentation](https://docs.github.com/en/actions/security-guides/encrypted-secrets)
- [Gmail App Passwords Guide](https://support.google.com/accounts/answer/185833)
- [2Captcha Documentation](https://2captcha.com/2captcha-api)

---

**Quick Tip**: Save this guide locally for reference when setting up secrets!
