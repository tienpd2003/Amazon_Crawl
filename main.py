#!/usr/bin/env python3
"""
Amazon Product Crawler - Main Application
Hệ thống crawl và theo dõi sản phẩm Amazon
"""

import asyncio
import sys
import signal
import uvicorn
from pathlib import Path

# Add project root to Python path
project_root = Path(__file__).parent
sys.path.insert(0, str(project_root))

from config.settings import settings
from database.connection import create_tables, init_default_settings
from scheduler.crawler_scheduler import start_scheduler, stop_scheduler
from utils.logger import get_logger

logger = get_logger(__name__)

class AmazonCrawlerApp:
    def __init__(self):
        self.scheduler_running = False
        
    async def initialize(self):
        """Initialize the application"""
        try:
            logger.info("Starting Amazon Product Crawler...")
            
            # Initialize database
            logger.info("Initializing database...")
            create_tables()
            init_default_settings()
            
            # Start scheduler
            logger.info("Starting crawler scheduler...")
            await start_scheduler()
            self.scheduler_running = True
            
            logger.info("Application initialized successfully!")
            
        except Exception as e:
            logger.error(f"❌ Failed to initialize application: {e}")
            raise
    
    async def cleanup(self):
        """Cleanup on shutdown"""
        try:
            logger.info("Shutting down Amazon Crawler...")
            
            if self.scheduler_running:
                await stop_scheduler()
                self.scheduler_running = False
            
            logger.info("Cleanup completed!")
            
        except Exception as e:
            logger.error(f"❌ Error during cleanup: {e}")
    
    def setup_signal_handlers(self):
        """Setup signal handlers for graceful shutdown"""
        def signal_handler(signum, frame):
            logger.info(f"📡 Received signal {signum}, initiating graceful shutdown...")
            asyncio.create_task(self.cleanup())
            sys.exit(0)
        
        signal.signal(signal.SIGINT, signal_handler)
        signal.signal(signal.SIGTERM, signal_handler)

async def run_web_server():
    """Run the FastAPI web server"""
    try:
        # Initialize app
        app = AmazonCrawlerApp()
        await app.initialize()
        
        # Setup signal handlers
        app.setup_signal_handlers()
        
        # Start web server
        logger.info(f"Starting web server on http://{settings.DASHBOARD_HOST}:{settings.DASHBOARD_PORT}")
        
        config = uvicorn.Config(
            "api.main:app",
            host=settings.DASHBOARD_HOST,
            port=settings.DASHBOARD_PORT,
            log_level="info",
            reload=False
        )
        
        server = uvicorn.Server(config)
        await server.serve()
        
    except KeyboardInterrupt:
        logger.info("📡 Received keyboard interrupt")
    except Exception as e:
        logger.error(f"❌ Error running web server: {e}")
    finally:
        if 'app' in locals():
            await app.cleanup()

async def run_crawler_only():
    """Run only the crawler scheduler without web interface"""
    try:
        # Initialize app
        app = AmazonCrawlerApp()
        await app.initialize()
        
        # Setup signal handlers
        app.setup_signal_handlers()
        
        logger.info("🔄 Crawler scheduler is running. Press Ctrl+C to stop.")
        
        # Keep running
        while True:
            await asyncio.sleep(60)  # Check every minute
            
    except KeyboardInterrupt:
        logger.info("📡 Received keyboard interrupt")
    except Exception as e:
        logger.error(f"❌ Error running crawler: {e}")
    finally:
        await app.cleanup()

def show_help():
    """Show help message"""
    print("""
🔹 Amazon Product Crawler - Hệ thống crawl và theo dõi sản phẩm Amazon

📋 Sử dụng:
    python main.py [command]

🔧 Commands:
    web         - Chạy web server với dashboard (mặc định)
    crawler     - Chỉ chạy crawler scheduler (không có web interface)
    setup       - Thiết lập database và cấu hình ban đầu
    test        - Test crawl một ASIN mẫu
    help        - Hiển thị thông tin này

📚 Ví dụ:
    python main.py                    # Chạy full web server
    python main.py web                # Chạy web server  
    python main.py crawler            # Chỉ chạy crawler
    python main.py test B019QZBS10    # Test crawl ASIN
    
🌐 Dashboard: http://{host}:{port}
📧 Hỗ trợ: Xem README.md để biết thêm chi tiết
    """.format(host=settings.DASHBOARD_HOST, port=settings.DASHBOARD_PORT))

async def setup_database():
    """Setup database and initial configuration"""
    try:
        logger.info("Setting up database...")
        create_tables()
        init_default_settings()
        
        # Add sample ASIN for testing
        from scheduler.crawler_scheduler import add_asin
        sample_asin = "B019QZBS10"  # ASIN from the screenshot
        
        logger.info(f"Adding sample ASIN: {sample_asin}")
        success = await add_asin(sample_asin, "daily", "Sample product for testing")
        
        if success:
            logger.info("Sample ASIN added successfully!")
        else:
            logger.info("Sample ASIN already exists or failed to add")
        
        logger.info("Database setup completed!")
        
        # Show next steps
        print(f"""
🎉 Setup hoàn tất!

🔄 Bước tiếp theo:
1. Cấu hình thông báo (tùy chọn):
   - Telegram: Thêm TELEGRAM_BOT_TOKEN và TELEGRAM_CHAT_ID vào .env
   - Discord: Thêm DISCORD_WEBHOOK_URL vào .env
   - Email: Cấu hình SMTP trong .env

2. Chạy ứng dụng:
   python main.py web

3. Truy cập dashboard:
   http://{settings.DASHBOARD_HOST}:{settings.DASHBOARD_PORT}

📋 Các tính năng chính:
- ✅ Crawl sản phẩm Amazon theo ASIN
- ✅ Theo dõi thay đổi giá, đánh giá, tồn kho
- ✅ Thông báo qua Telegram/Discord/Email
- ✅ Dashboard web để quản lý
- ✅ Lập lịch crawl tự động hàng ngày
        """)
        
    except Exception as e:
        logger.error(f"❌ Error setting up database: {e}")
        raise

async def test_crawl(asin: str = None):
    """Test crawl a single ASIN"""
    if not asin:
        asin = "B019QZBS10"  # Default test ASIN
    
    try:
        logger.info(f"Testing crawl for ASIN: {asin}")
        
        from crawler.amazon_crawler import crawl_single_product
        result = crawl_single_product(asin)
        
        if result.get('crawl_success'):
            logger.info("Test crawl successful!")
            print(f"""
📊 Kết quả test crawl:
- ASIN: {result.get('asin')}
- Tiêu đề: {result.get('title', 'N/A')[:100]}...
- Giá bán: ${result.get('sale_price', 'N/A')}
- Giá niêm yết: ${result.get('list_price', 'N/A')}
- Đánh giá: {result.get('rating', 'N/A')}/5 ({result.get('rating_count', 'N/A')} reviews)
- Tồn kho: {result.get('inventory_status', 'N/A')}
- Amazon's Choice: {'Có' if result.get('amazon_choice') else 'Không'}
            """)
        else:
            logger.error(f"❌ Test crawl failed: {result.get('crawl_error', 'Unknown error')}")
            
    except Exception as e:
        logger.error(f"❌ Error during test crawl: {e}")

def create_env_file():
    """Create sample .env file"""
    env_file = Path(".env")
    
    if env_file.exists():
        logger.info(".env file already exists")
        return
    
    env_content = """# Amazon Crawler Configuration

# Database
DATABASE_URL=sqlite:///./amazon_crawler.db

# Crawler Settings
CRAWLER_DELAY=3
MAX_RETRIES=3
TIMEOUT=30
HEADLESS_BROWSER=true

# Scheduler
SCHEDULER_TIMEZONE=Asia/Ho_Chi_Minh
DAILY_CRAWL_TIME=09:00

# Dashboard
DASHBOARD_HOST=127.0.0.1
DASHBOARD_PORT=8000

# Telegram Notifications (Optional)
TELEGRAM_BOT_TOKEN=
TELEGRAM_CHAT_ID=

# Discord Notifications (Optional)
DISCORD_WEBHOOK_URL=

# Email Notifications (Optional)
EMAIL_SMTP_SERVER=
EMAIL_SMTP_PORT=587
EMAIL_USERNAME=
EMAIL_PASSWORD=
"""
    
    env_file.write_text(env_content)
    logger.info("Created .env file with default configuration")

async def main():
    """Main application entry point"""
    # Create .env file if it doesn't exist
    create_env_file()
    
    # Parse command line arguments
    command = sys.argv[1] if len(sys.argv) > 1 else "web"
    
    try:
        if command == "help" or command == "--help" or command == "-h":
            show_help()
            
        elif command == "setup":
            await setup_database()
            
        elif command == "test":
            test_asin = sys.argv[2] if len(sys.argv) > 2 else None
            await test_crawl(test_asin)
            
        elif command == "crawler":
            await run_crawler_only()
            
        elif command == "web" or command == "server":
            await run_web_server()
            
        else:
            logger.error(f"❌ Unknown command: {command}")
            show_help()
            sys.exit(1)
            
    except KeyboardInterrupt:
        logger.info("Goodbye!")
    except Exception as e:
        logger.error(f"Application error: {e}")
        sys.exit(1)

if __name__ == "__main__":
    # Run the application
    asyncio.run(main()) 