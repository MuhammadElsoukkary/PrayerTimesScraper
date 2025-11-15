"""Configuration for Mawaqit Uploader"""
import os
from pathlib import Path
from os import getenv
from dotenv import load_dotenv

def _load_env_files():
    """Load .env from multiple likely locations so manual CLI env exports aren't required.
    Order:
      1. CWD/.env (project root when invoked from repository root)
      2. This package directory (where config.py lives)
      3. Parent of package directory (alternate project root)
    Later loads do NOT overwrite already-set variables to preserve precedence (CWD wins).
    """
    searched = []
    loaded = []
    try:
        candidates = [
            Path('.') / '.env',
            Path(__file__).parent / '.env',
            Path(__file__).parent.parent / '.env'
        ]
        for p in candidates:
            searched.append(str(p.resolve()))
            if p.exists():
                # Use override=False so earlier env takes precedence
                load_dotenv(p, override=False)
                loaded.append(str(p.resolve()))
    except Exception as e:
        print(f"[Config] .env loading error: {e}")
    if loaded:
        print(f"[Config] Loaded .env files: {', '.join(loaded)}")
    else:
        print("[Config] No .env files found in: " + ", ".join(searched))

_load_env_files()

class Config:
    # Mawaqit Credentials (blank default -> must come from .env or environment)
    MAWAQIT_USER = os.getenv('MAWAQIT_USER', '')
    MAWAQIT_PASS = os.getenv('MAWAQIT_PASS', '')

    # Gmail for 2FA (optional; blank if absent)
    GMAIL_USER = os.getenv('GMAIL_USER', '')
    GMAIL_APP_PASSWORD = os.getenv('GMAIL_APP_PASSWORD', '')

    # 2Captcha API (optional; blank if absent)
    TWOCAPTCHA_API_KEY = os.getenv('TWOCAPTCHA_API_KEY', '')
    
    # Optional: Manual 2FA code (if you want to enter it yourself)
    MANUAL_2FA_CODE = os.getenv('MANUAL_2FA_CODE', None)
    
    # Prayer Times Directory
    PRAYER_TIMES_DIR = os.getenv('PRAYER_TIMES_DIR', './prayer-times')
    
    # Captcha related settings
    CAPTCHA_PRE_SUBMIT_WAIT = int(getenv('CAPTCHA_PRE_SUBMIT_WAIT', '90'))
    CAPTCHA_SOLVE_TIMEOUT = int(getenv('CAPTCHA_SOLVE_TIMEOUT', '300'))
    
    # Browser Settings - CHANGED FOR LOCAL TESTING
    # Allow overriding via environment so GitHub Actions can set different modes for normal vs debug retry
    HEADLESS = os.getenv('HEADLESS', 'true').lower() in ['1','true','yes']  # default headless true
    DEBUG_MODE = os.getenv('DEBUG_MODE', 'false').lower() in ['1','true','yes']
    
    # Timing Settings
    PAGE_TIMEOUT = 60000  # 60 seconds
    WAIT_BETWEEN_ACTIONS = 3  # Slower for debugging (seconds)
    MAX_RETRIES = 3
    
    LOGIN_URL = getenv('LOGIN_URL', 'https://mawaqit.net/en/backoffice/login')
    
    @classmethod
    def validate(cls):
        """Validate required credentials. Only MAWAQIT_USER/PASS are mandatory.
        If optional items missing, print warnings but continue (captcha/2FA will be skipped)."""
        core_required = ['MAWAQIT_USER', 'MAWAQIT_PASS']
        missing_core = [v for v in core_required if not getattr(cls, v)]
        if missing_core:
            # Attempt a final reload (in case validate called before module load finished)
            _load_env_files()
            for v in core_required:
                setattr(cls, v, os.getenv(v, getattr(cls, v)))
            missing_core = [v for v in core_required if not getattr(cls, v)]
        if missing_core:
            raise ValueError(f"Missing required core config: {', '.join(missing_core)}")

        # Re-bind optional after potential reload
        cls.GMAIL_USER = os.getenv('GMAIL_USER', cls.GMAIL_USER)
        cls.GMAIL_APP_PASSWORD = os.getenv('GMAIL_APP_PASSWORD', cls.GMAIL_APP_PASSWORD)
        cls.TWOCAPTCHA_API_KEY = os.getenv('TWOCAPTCHA_API_KEY', cls.TWOCAPTCHA_API_KEY)

        optional_missing = []
        if not cls.GMAIL_USER or not cls.GMAIL_APP_PASSWORD:
            optional_missing.append('GMAIL_USER/GMAIL_APP_PASSWORD')
        if not cls.TWOCAPTCHA_API_KEY:
            optional_missing.append('TWOCAPTCHA_API_KEY')
        if optional_missing:
            print(f"[Config] Optional items missing -> {', '.join(optional_missing)} (captcha/2FA disabled)")

        # Masked output for sanity check
        def _mask(val: str) -> str:
            if not val: return '<empty>'
            if len(val) <= 4: return '****'
            return val[0] + '***' + val[-2:]
        print(f"[Config] MAWAQIT_USER={_mask(cls.MAWAQIT_USER)}")
        print(f"[Config] MAWAQIT_PASS={'****' if cls.MAWAQIT_PASS else '<empty>'}")
        print(f"[Config] GMAIL_USER={_mask(cls.GMAIL_USER)}")
        print(f"[Config] 2CAPTCHA={_mask(cls.TWOCAPTCHA_API_KEY)}")
        return True