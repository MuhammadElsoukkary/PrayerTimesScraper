"""Main Mawaqit Prayer Times Uploader"""
import time
import os
import csv
from datetime import datetime
from typing import Optional, Dict, List
from playwright.sync_api import sync_playwright, Page, Browser, BrowserContext
from loguru import logger
from tenacity import retry, stop_after_attempt, wait_fixed

from config import Config
from email_helper import EmailHelper
from captcha_solver import CaptchaSolver

class MawaqitUploader:
    """Mawaqit Prayer Times Uploader"""
    
    def __init__(self):
        self.config = Config
        self.email_helper = EmailHelper(Config.GMAIL_USER, Config.GMAIL_APP_PASSWORD)
        self.captcha_solver = CaptchaSolver(Config.TWOCAPTCHA_API_KEY)
        
        self.page: Optional[Page] = None
        self.context: Optional[BrowserContext] = None
        self.browser: Optional[Browser] = None
    
    def save_screenshot(self, name: str):
        """Save debug screenshot"""
        if Config.DEBUG_MODE and self.page:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            filename = f"debug_{name}_{timestamp}.png"
            try:
                self.page.screenshot(path=filename)
                logger.debug(f"Screenshot saved: {filename}")
            except Exception as e:
                logger.warning(f"Failed to save screenshot: {e}")
    
    def detect_and_solve_recaptcha(self) -> bool:
        """Detect and solve reCAPTCHA if present"""
        try:
            # Check for reCAPTCHA
            recaptcha_indicators = [
                'iframe[src*="recaptcha"]',
                '.g-recaptcha',
                '[data-sitekey]'
            ]
            
            has_recaptcha = False
            site_key = None
            
            for indicator in recaptcha_indicators:
                if self.page.locator(indicator).count() > 0:
                    has_recaptcha = True
                    
                    # Try to extract site key
                    elements = self.page.locator('[data-sitekey]')
                    if elements.count() > 0:
                        site_key = elements.first.get_attribute('data-sitekey')
                    break
            
            if not has_recaptcha:
                logger.info("No reCAPTCHA detected")
                return True
            
            if not site_key:
                logger.warning("reCAPTCHA present but couldn't extract site key")
                return False
            
            logger.info(f"reCAPTCHA detected. Site key: {site_key}")
            
            # Solve captcha
            solution = self.captcha_solver.solve_recaptcha(site_key, self.page.url)
            
            if not solution:
                return False
            
            # Inject solution
            injection_script = f"""
            (function() {{
                const textareas = document.querySelectorAll('[name="g-recaptcha-response"]');
                textareas.forEach(textarea => {{
                    textarea.value = "{solution}";
                    textarea.style.display = 'block';
                }});
                
                if (typeof grecaptcha !== 'undefined') {{
                    grecaptcha.getResponse = function() {{ return "{solution}"; }};
                }}
                
                return true;
            }})();
            """
            
            self.page.evaluate(injection_script)
            logger.success("reCAPTCHA solution injected")
            time.sleep(2)
            
            # Try to auto-submit
            submit_buttons = self.page.locator('button[type="submit"], input[type="submit"]')
            if submit_buttons.count() > 0:
                for i in range(submit_buttons.count()):
                    if submit_buttons.nth(i).is_visible():
                        logger.info("Auto-clicking submit button")
                        submit_buttons.nth(i).click()
                        break
            
            return True
        
        except Exception as e:
            logger.error(f"Error in reCAPTCHA handling: {e}")
            return False
    
    def check_if_logged_in(self) -> bool:
        """Check if already logged in"""
        try:
            current_url = self.page.url
            logger.debug(f"Current URL: {current_url}")
            
            # Check if still on login page
            if "login" in current_url:
                time.sleep(2)
                current_url = self.page.url
                if "login" in current_url:
                    return False
            
            # Check for logged-in indicators
            logged_in_indicators = [
                'button:has-text("Actions")',
                'a:has-text("Logout")',
                '.admin-panel',
                '.dashboard'
            ]
            
            for indicator in logged_in_indicators:
                if self.page.locator(indicator).count() > 0:
                    logger.success(f"Logged in (found: {indicator})")
                    return True
            
            # Check for login form presence
            login_indicators = [
                'input[type="email"]',
                'button:has-text("Sign in")',
                'button:has-text("Login")'
            ]
            
            for indicator in login_indicators:
                if self.page.locator(indicator).count() > 0:
                    logger.debug(f"Not logged in (found: {indicator})")
                    return False
            
            # If not on login page and no login form, assume logged in
            if "login" not in current_url:
                logger.info("Assuming logged in (no login indicators found)")
                return True
            
            return False
        
        except Exception as e:
            logger.warning(f"Error checking login status: {e}")
            return False
    
    def perform_login(self) -> bool:
        """Perform login with reCAPTCHA and 2FA"""
        logger.info("Starting login process")
        
        try:
            self.page.goto("https://mawaqit.net/en/backoffice/login", wait_until="domcontentloaded")
            time.sleep(3)
            
            if self.check_if_logged_in():
                logger.success("Already logged in")
                return True
            
            self.save_screenshot("login_page")
            
            # Fill credentials
            logger.info("Filling login credentials")
            email_input = self.page.locator('input[type="email"]').first
            password_input = self.page.locator('input[type="password"]').first
            
            email_input.fill(self.config.MAWAQIT_USER)
            password_input.fill(self.config.MAWAQIT_PASS)
            
            # Handle reCAPTCHA
            if not self.detect_and_solve_recaptcha():
                logger.error("Failed to solve reCAPTCHA")
                return False
            
            time.sleep(5)
            
            # Check if login successful without 2FA
            if self.check_if_logged_in():
                logger.success("Login successful (no 2FA required)")
                return True
            
            # Handle 2FA
            page_content = self.page.content().lower()
            if any(kw in page_content for kw in ["verification", "code", "2fa"]):
                logger.info("2FA verification required")
                self.save_screenshot("2fa_page")
                
                # Get 2FA code
                code = self.config.MANUAL_2FA_CODE or self.email_helper.get_2fa_code()
                
                if not code:
                    logger.error("Could not retrieve 2FA code")
                    return False
                
                # Enter 2FA code
                code_input_selectors = [
                    'input[placeholder*="code" i]',
                    'input[type="text"]',
                    'input[type="number"]'
                ]
                
                for selector in code_input_selectors:
                    elements = self.page.locator(selector)
                    if elements.count() > 0:
                        for i in range(elements.count()):
                            if elements.nth(i).is_visible():
                                elements.nth(i).fill(code)
                                logger.success("2FA code entered")
                                break
                        break
                
                # Submit 2FA
                time.sleep(1)
                submit_button = self.page.locator('button[type="submit"]').first
                submit_button.click()
                
                logger.info("Waiting for 2FA to process...")
                time.sleep(10)
                
                self.save_screenshot("after_2fa")
            
            # Final login check
            if self.check_if_logged_in():
                logger.success("Login successful")
                return True
            else:
                logger.error("Login failed")
                self.save_screenshot("login_failed")
                return False
        
        except Exception as e:
            logger.error(f"Login error: {e}")
            self.save_screenshot("login_error")
            return False
    
    def smart_click(self, selectors: List[str], description: str, required: bool = True) -> bool:
        """Click element with multiple selector fallbacks"""
        logger.info(f"Looking for: {description}")
        
        for attempt in range(2):
            for selector in selectors:
                try:
                    elements = self.page.locator(selector)
                    if elements.count() > 0:
                        for i in range(elements.count()):
                            element = elements.nth(i)
                            if element.is_visible(timeout=1000):
                                element.scroll_into_view_if_needed()
                                time.sleep(0.5)
                                element.click()
                                logger.success(f"Clicked: {description}")
                                time.sleep(Config.WAIT_BETWEEN_ACTIONS)
                                return True
                except Exception:
                    continue
            
            if attempt == 0:
                logger.info(f"First attempt failed for {description}, retrying...")
                time.sleep(2)
        
        if required:
            logger.error(f"Could not find: {description}")
            self.save_screenshot(f"missing_{description.replace(' ', '_')}")
        
        return False
    
    def read_prayer_times_csv(self) -> Optional[Dict]:
        """Read prayer times from CSV files"""
        current_month = datetime.now().strftime('%B')
        athan_path = os.path.join(Config.PRAYER_TIMES_DIR, f'athan_times_{current_month}.csv')
        iqama_path = os.path.join(Config.PRAYER_TIMES_DIR, f'iqama_times_{current_month}.csv')
        
        logger.info(f"Looking for CSV files for {current_month}")
        
        if not os.path.exists(athan_path) or not os.path.exists(iqama_path):
            logger.error("CSV files not found")
            return None
        
        prayer_times = {}
        
        try:
            with open(athan_path, 'r', encoding='utf-8') as file:
                reader = csv.DictReader(file)
                for row in reader:
                    day = row.get('Day')
                    if day:
                        prayer_times[int(day)] = {
                            'athan': {k: v for k, v in row.items() if k != 'Day'},
                            'iqama': {}
                        }
            
            with open(iqama_path, 'r', encoding='utf-8') as file:
                reader = csv.DictReader(file)
                for row in reader:
                    day = row.get('Day')
                    if day and int(day) in prayer_times:
                        prayer_times[int(day)]['iqama'] = {k: v for k, v in row.items() if k != 'Day'}
            
            logger.success(f"Loaded {len(prayer_times)} days of prayer times")
            return prayer_times
        
        except Exception as e:
            logger.error(f"Error reading CSV files: {e}")
            return None
    
    def navigate_to_config(self) -> bool:
        """Navigate to prayer times configuration"""
        logger.info("Navigating to prayer times configuration")
        
        actions_selectors = [
            'button:has-text("Actions")',
            '.btn:has-text("Actions")'
        ]
        
        if not self.smart_click(actions_selectors, "Actions button"):
            return False
        
        configure_selectors = [
            'a:has-text("Configure")',
            '.dropdown-item:has-text("Configure")'
        ]
        
        if not self.smart_click(configure_selectors, "Configure option"):
            return False
        
        time.sleep(2)
        self.save_screenshot("configure_page")
        
        calculation_selectors = [
            'text="Calculation of prayer times"',
            'h3:has-text("Calculation")'
        ]
        
        if not self.smart_click(calculation_selectors, "Calculation section"):
            return False
        
        return True
    
    def upload_csv_file(self, csv_type: str) -> bool:
        """Upload CSV file"""
        current_month = datetime.now().strftime('%B')
        logger.info(f"Uploading {csv_type} CSV for {current_month}")
        
        csv_button_selectors = [
            'button:has-text("Pre-populate from a csv file")',
            'button:has-text("CSV")'
        ]
        
        if not self.smart_click(csv_button_selectors, f"CSV upload button ({csv_type})"):
            return False
        
        file_input = self.page.locator('input[type="file"]').first
        csv_path = os.path.join(Config.PRAYER_TIMES_DIR, f'{csv_type}_times_{current_month}.csv')
        
        if not os.path.exists(csv_path):
            logger.error(f"CSV file not found: {csv_path}")
            return False
        
        logger.info(f"Uploading: {csv_path}")
        file_input.set_input_files(csv_path)
        time.sleep(2)
        
        submit_selectors = [
            'button:has-text("Upload")',
            'button:has-text("Submit")',
            'button[type="submit"]'
        ]
        
        self.smart_click(submit_selectors, f"Submit ({csv_type})", required=False)
        time.sleep(3)
        
        logger.success(f"{csv_type.capitalize()} CSV uploaded")
        return True
    
    def upload_monthly_times(self) -> bool:
        """Upload both Athan and Iqama times"""
        current_month = datetime.now().strftime('%B')
        logger.info(f"Uploading prayer times for {current_month}")
        
        month_selectors = [
            f'text="{current_month}"',
            f'h3:has-text("{current_month}")'
        ]
        
        if not self.smart_click(month_selectors, f"{current_month} month"):
            return False
        
        # Upload Athan
        if not self.upload_csv_file('athan'):
            return False
        
        # Navigate to Iqama tab
        iqama_selectors = [
            'a:has-text("Iqama")',
            'button:has-text("Iqama")'
        ]
        
        if not self.smart_click(iqama_selectors, "Iqama tab"):
            return False
        
        # Click "By calendar"
        calendar_selectors = [
            'a:has-text("By calendar")',
            'button:has-text("By calendar")'
        ]
        
        if not self.smart_click(calendar_selectors, "By calendar"):
            return False
        
        # Click month again for Iqama
        if not self.smart_click(month_selectors, f"{current_month} month (Iqama)"):
            return False
        
        # Upload Iqama
        if not self.upload_csv_file('iqama'):
            return False
        
        logger.success("Both CSV files uploaded successfully!")
        return True
    
    @retry(stop=stop_after_attempt(Config.MAX_RETRIES), wait=wait_fixed(5))
    def run(self) -> bool:
        """Main execution with retry logic"""
        logger.info("Starting Mawaqit Prayer Times Uploader v3.2")
        logger.info("=" * 60)
        
        # Validate prayer times exist
        if not self.read_prayer_times_csv():
            return False
        
        playwright_instance = None
        
        try:
            playwright_instance = sync_playwright().start()
            
            self.browser = playwright_instance.chromium.launch(
                headless=Config.HEADLESS,
                args=[
                    '--disable-blink-features=AutomationControlled',
                    '--no-sandbox'
                ]
            )
            
            self.context = self.browser.new_context(
                viewport={'width': 1920, 'height': 1080},
                user_agent='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
            )
            
            self.page = self.context.new_page()
            self.page.set_default_timeout(Config.PAGE_TIMEOUT)
            
            # Perform login
            if not self.perform_login():
                raise Exception("Login failed")
            
            # Navigate to configuration
            if not self.navigate_to_config():
                raise Exception("Failed to navigate to configuration")
            
            # Upload prayer times
            if not self.upload_monthly_times():
                raise Exception("Failed to upload prayer times")
            
            logger.success("Process completed successfully!")
            return True
        
        except Exception as e:
            logger.error(f"Execution error: {e}")
            self.save_screenshot("error_state")
            raise
        
        finally:
            # Cleanup
            try:
                if self.page:
                    self.page.close()
                if self.context:
                    self.context.close()
                if self.browser:
                    self.browser.close()
                if playwright_instance:
                    playwright_instance.stop()
            except:
                pass
