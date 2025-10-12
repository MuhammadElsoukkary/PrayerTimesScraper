"""Configuration management for Mawaqit Prayer Times Uploader"""
import os
from typing import Optional
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

class Config:
    """Application configuration"""
    
    # Mawaqit credentials
    MAWAQIT_USER: str = os.getenv('MAWAQIT_USER', '')
    MAWAQIT_PASS: str = os.getenv('MAWAQIT_PASS', '')
    
    # Gmail credentials for 2FA
    GMAIL_USER: str = os.getenv('GMAIL_USER', '')
    GMAIL_APP_PASSWORD: str = os.getenv('GMAIL_APP_PASSWORD', '')
    
    # 2Captcha API
    TWOCAPTCHA_API_KEY: str = os.getenv('TWOCAPTCHA_API_KEY', '')
    
    # Prayer times directory
    PRAYER_TIMES_DIR: str = os.getenv('PRAYER_TIMES_DIR', './prayer_times')
    
    # Optional manual 2FA code
    MANUAL_2FA_CODE: Optional[str] = os.getenv('MANUAL_2FA_CODE')
    
    # Browser settings
    DEBUG_MODE: bool = os.getenv('DEBUG_MODE', 'True').lower() == 'true'
    HEADLESS: bool = bool(os.getenv('CI')) or bool(os.getenv('GITHUB_ACTIONS'))
    
    # Timeouts and retries
    MAX_RETRIES: int = 3
    WAIT_BETWEEN_ACTIONS: int = 2
    PAGE_TIMEOUT: int = 30000
    
    @classmethod
    def validate(cls) -> tuple[bool, list[str]]:
        """Validate required configuration"""
        required_vars = {
            'MAWAQIT_USER': cls.MAWAQIT_USER,
            'MAWAQIT_PASS': cls.MAWAQIT_PASS,
            'GMAIL_USER': cls.GMAIL_USER,
            'GMAIL_APP_PASSWORD': cls.GMAIL_APP_PASSWORD
        }
        
        missing = [var for var, value in required_vars.items() if not value]
        return len(missing) == 0, missing
    
    @classmethod
    def display_config(cls):
        """Display configuration status"""
        print(f"✅ Prayer times directory: {cls.PRAYER_TIMES_DIR}")
        print(f"🌐 2Captcha API: {'configured' if cls.TWOCAPTCHA_API_KEY else 'not configured'}")
        print(f"🔑 Manual 2FA: {'provided' if cls.MANUAL_2FA_CODE else 'will retrieve from Gmail'}")
        print(f"🖥️  Browser mode: {'headless' if cls.HEADLESS else 'headed'}")
