"""2Captcha integration for solving reCAPTCHA"""
import time
import requests
from typing import Optional, Tuple
from loguru import logger

class CaptchaSolver:
    """2Captcha reCAPTCHA solver"""
    
    def __init__(self, api_key: str):
        self.api_key = api_key
    
    def solve_recaptcha(self, site_key: str, page_url: str) -> Optional[str]:
        """Solve reCAPTCHA using 2Captcha service"""
        if not self.api_key:
            logger.error("2Captcha API key not configured")
            return None
        
        logger.info("Starting 2Captcha reCAPTCHA solving process")
        
        try:
            # Submit captcha
            submit_url = "http://2captcha.com/in.php"
            submit_params = {
                'key': self.api_key,
                'method': 'userrecaptcha',
                'googlekey': site_key,
                'pageurl': page_url,
                'json': 1
            }
            
            logger.info("Submitting reCAPTCHA to 2Captcha...")
            response = requests.post(submit_url, data=submit_params, timeout=30)
            
            if response.status_code != 200:
                logger.error(f"2Captcha submission failed: HTTP {response.status_code}")
                return None
            
            result = response.json()
            
            if result.get('status') != 1:
                error_msg = result.get('error_text', 'Unknown error')
                logger.error(f"2Captcha submission error: {error_msg}")
                return None
            
            captcha_id = result['request']
            logger.success(f"Captcha submitted. Task ID: {captcha_id}")
            
            # Wait for solution
            return self._wait_for_solution(captcha_id)
        
        except Exception as e:
            logger.error(f"Unexpected error in captcha solver: {e}")
            return None
    
    def _wait_for_solution(self, captcha_id: str, max_attempts: int = 60, 
                          check_interval: int = 5) -> Optional[str]:
        """Wait for captcha solution"""
        result_url = "http://2captcha.com/res.php"
        
        logger.info(f"Waiting for solution (max {max_attempts * check_interval} seconds)...")
        
        for attempt in range(max_attempts):
            time.sleep(check_interval)
            
            result_params = {
                'key': self.api_key,
                'action': 'get',
                'id': captcha_id,
                'json': 1
            }
            
            try:
                result_response = requests.get(result_url, params=result_params, timeout=10)
                
                if result_response.status_code != 200:
                    continue
                
                result = result_response.json()
                
                if result.get('status') == 1:
                    solution = result['request']
                    logger.success(f"reCAPTCHA solved! (length: {len(solution)})")
                    return solution
                
                elif result.get('status') == 0:
                    request_status = result.get('request', '')
                    if request_status == 'CAPCHA_NOT_READY':
                        if attempt % 6 == 0:
                            logger.info(f"Still waiting... ({attempt * check_interval}s elapsed)")
                    else:
                        logger.error(f"2Captcha error: {request_status}")
                        return None
            
            except Exception as e:
                logger.warning(f"Error checking result: {e}")
                continue
        
        logger.error("Timeout waiting for 2Captcha solution")
        return None
