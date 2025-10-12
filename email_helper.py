"""Email helper for retrieving 2FA codes"""
import imaplib
import email
import re
import time
from datetime import datetime, timedelta
from typing import Optional
from loguru import logger

class EmailHelper:
    """Helper class for Gmail operations"""
    
    def __init__(self, gmail_user: str, gmail_app_password: str):
        self.gmail_user = gmail_user
        self.gmail_app_password = gmail_app_password
    
    def get_2fa_code(self, max_wait_minutes: int = 5) -> Optional[str]:
        """Retrieve 2FA code from Gmail"""
        logger.info("Checking Gmail for 2FA verification code...")
        
        start_time = datetime.now()
        check_interval = 10
        attempts = 0
        
        while (datetime.now() - start_time).total_seconds() < max_wait_minutes * 60:
            attempts += 1
            try:
                logger.debug(f"Email check attempt {attempts}")
                
                imap = imaplib.IMAP4_SSL("imap.gmail.com")
                imap.login(self.gmail_user, self.gmail_app_password)
                imap.select("inbox")
                
                # Search queries
                search_queries = [
                    'FROM "mawaqit"',
                    'FROM "noreply@mawaqit.net"',
                    'SUBJECT "verification"',
                    'SUBJECT "code"'
                ]
                
                all_mail_ids = []
                
                for query in search_queries:
                    try:
                        since_date = (datetime.now() - timedelta(hours=1)).strftime("%d-%b-%Y")
                        search_criteria = f'({query} SINCE "{since_date}")'
                        status, messages = imap.search(None, search_criteria)
                        
                        if status == 'OK' and messages[0]:
                            mail_ids = messages[0].split()
                            all_mail_ids.extend(mail_ids)
                    except Exception as e:
                        logger.debug(f"Search error with query {query}: {e}")
                        continue
                
                all_mail_ids = list(set(all_mail_ids))
                
                if all_mail_ids:
                    logger.info(f"Found {len(all_mail_ids)} potential emails")
                    
                    for mail_id in reversed(all_mail_ids[-10:]):
                        try:
                            status, msg_data = imap.fetch(mail_id, "(RFC822)")
                            if status != 'OK':
                                continue
                            
                            raw_msg = msg_data[0][1]
                            msg = email.message_from_bytes(raw_msg)
                            
                            from_addr = msg.get('From', '')
                            if 'mawaqit' not in from_addr.lower():
                                continue
                            
                            body = self._extract_email_body(msg)
                            
                            # Look for 6-digit code
                            code_patterns = [r'(\d{6})']
                            
                            for pattern in code_patterns:
                                matches = re.findall(pattern, body, re.IGNORECASE)
                                if matches:
                                    code = matches[0]
                                    logger.success(f"Found 2FA code: {code}")
                                    imap.close()
                                    imap.logout()
                                    return code
                        
                        except Exception as e:
                            logger.warning(f"Error processing email: {e}")
                            continue
                
                imap.close()
                imap.logout()
                
                logger.info(f"No code found yet, waiting {check_interval} seconds...")
                time.sleep(check_interval)
            
            except Exception as e:
                logger.error(f"Error checking email: {e}")
                time.sleep(check_interval)
        
        logger.error("No 2FA code found within timeout period")
        return None
    
    def _extract_email_body(self, msg) -> str:
        """Extract text body from email message"""
        body = ""
        
        if msg.is_multipart():
            for part in msg.walk():
                content_type = part.get_content_type()
                if content_type in ["text/plain", "text/html"]:
                    try:
                        payload = part.get_payload(decode=True)
                        if payload:
                            text = payload.decode('utf-8', errors='ignore')
                            text = re.sub(r'<[^>]+>', ' ', text)
                            text = ' '.join(text.split())
                            body += text + " "
                    except Exception:
                        continue
        else:
            try:
                payload = msg.get_payload(decode=True)
                if payload:
                    body = payload.decode('utf-8', errors='ignore')
                    body = re.sub(r'<[^>]+>', ' ', body)
                    body = ' '.join(body.split())
            except Exception:
                pass
        
        return body
