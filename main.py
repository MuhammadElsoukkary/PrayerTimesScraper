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
        for var in missing:
            logger.info(f"  {var}=your_value_here")
        return 1

    logger.success("Environment validated")
    Config.display_config()
    print("-" * 60)

    # Create uploader and run
    try:
        uploader = MawaqitUploader()
        success = uploader.run()

        if success:
            logger.success("🎉 Prayer times uploaded to Mawaqit!")
            logger.success("✅ Both Athan and Iqama times have been updated")
            return 0
        else:
            logger.error("❌ Failed to complete the upload process")
            return 1

    except KeyboardInterrupt:
        logger.warning("⚠️ Process interrupted by user")
        return 130

    except Exception as e:
        logger.error(f"❌ Unexpected error: {e}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
