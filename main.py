"""Entry point for Mawaqit Prayer Times Uploader"""
from loguru import logger
import sys
from config import Config
from mawaqit_uploader import MawaqitUploader

def setup_logging():
    """Configure logging"""
    logger.remove()  # Remove default handler
    logger.add(
        sys.stdout,
        format="<green>{time:HH:mm:ss}</green> | <level>{level: <8}</level> | <level>{message}</level>",
        level="DEBUG" if Config.DEBUG_MODE else "INFO"
    )
    logger.add(
        "mawaqit_uploader.log",
        rotation="1 MB",
        retention="7 days",
        level="DEBUG"
    )

def main():
    """Main entry point"""
    print("""
    ╔══════════════════════════════════════════════════════════╗
    ║       Mawaqit Prayer Times Uploader v3.2                 ║
    ║       Refactored & Improved Architecture                 ║
    ╚══════════════════════════════════════════════════════════╝
    """)
    
    setup_logging()
    
    # Validate configuration
    valid, missing = Config.validate()
    if not valid:
        logger.error(f"Missing required environment variables: {', '.join(missing)}")
        logger.info("Please set the following environment variables:")
        for var in missing
