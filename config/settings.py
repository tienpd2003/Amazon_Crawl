import os
from dotenv import load_dotenv

load_dotenv()

class Settings:
    # Database
    DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./amazon_crawler.db")
    
    # Amazon Crawler Settings
    CRAWLER_DELAY = int(os.getenv("CRAWLER_DELAY", "3"))  # seconds between requests
    MAX_RETRIES = int(os.getenv("MAX_RETRIES", "3"))
    TIMEOUT = int(os.getenv("TIMEOUT", "30"))
    
    # User Agents
    USER_AGENTS = [
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    ]
    
    # Proxy Settings (Optional)
    USE_PROXY = os.getenv("USE_PROXY", "false").lower() == "true"
    PROXY_LIST = os.getenv("PROXY_LIST", "").split(",") if os.getenv("PROXY_LIST") else []
    
    # Notification Settings
    TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
    TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")
    DISCORD_WEBHOOK_URL = os.getenv("DISCORD_WEBHOOK_URL", "")
    EMAIL_SMTP_SERVER = os.getenv("EMAIL_SMTP_SERVER", "")
    EMAIL_SMTP_PORT = int(os.getenv("EMAIL_SMTP_PORT", "587"))
    EMAIL_USERNAME = os.getenv("EMAIL_USERNAME", "")
    EMAIL_PASSWORD = os.getenv("EMAIL_PASSWORD", "")
    EMAIL_RECIPIENTS = os.getenv("EMAIL_RECIPIENTS", "")
    
    # Dashboard Settings
    DASHBOARD_HOST = os.getenv("DASHBOARD_HOST", "127.0.0.1")
    DASHBOARD_PORT = int(os.getenv("DASHBOARD_PORT", "8000"))
    
    # Scheduler Settings
    SCHEDULER_TIMEZONE = os.getenv("SCHEDULER_TIMEZONE", "Asia/Ho_Chi_Minh")
    DAILY_CRAWL_TIME = os.getenv("DAILY_CRAWL_TIME", "09:00")  # HH:MM format
    
    # Data Storage
    IMAGE_STORAGE_PATH = os.getenv("IMAGE_STORAGE_PATH", "./data/images/")
    VIDEO_STORAGE_PATH = os.getenv("VIDEO_STORAGE_PATH", "./data/videos/")
    EXCEL_EXPORT_PATH = os.getenv("EXCEL_EXPORT_PATH", "./data/exports/")
    
    # Amazon Specific
    AMAZON_BASE_URL = "https://www.amazon.com"
    AMAZON_DP_URL = "https://www.amazon.com/dp/{asin}"
    
    # Selenium Settings
    HEADLESS_BROWSER = os.getenv("HEADLESS_BROWSER", "false").lower() == "true"
    BROWSER_TYPE = os.getenv("BROWSER_TYPE", "chrome")  # chrome, firefox
    SELENIUM_GRID_URL = os.getenv("SELENIUM_GRID_URL", "")
    
    # Rate Limiting
    REQUESTS_PER_MINUTE = int(os.getenv("REQUESTS_PER_MINUTE", "10"))
    CONCURRENT_REQUESTS = int(os.getenv("CONCURRENT_REQUESTS", "1"))

settings = Settings() 