#!/usr/bin/env python3
"""
Test script for daily crawl with Telegram notifications
"""

import asyncio
import sys
import os
from datetime import datetime, timedelta

# Add project root to path
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from database.connection import get_db_session
from database.models import ProductCrawlHistory, ASINWatchlist
from scheduler.crawler_scheduler import crawler_scheduler
from utils.logger import get_logger

logger = get_logger(__name__)

async def create_yesterday_data():
    """Tạo dữ liệu crawl hôm qua để test change detection"""
    
    # 3 ASINs từ demo file
    test_asins = [
        "B0CSVB9C5G",
        "B0016HF5GK", 
        "B004Q4DRJW"
    ]
    
    db_session = get_db_session()
    try:
        # Tạo dữ liệu hôm qua cho mỗi ASIN
        yesterday = datetime.utcnow() - timedelta(days=1)
        
        for asin in test_asins:
            # Tạo dữ liệu crawl hôm qua với cấu trúc đúng
            yesterday_data = ProductCrawlHistory(
                asin=asin,
                crawl_date=yesterday,
                crawl_success=True,
                title=f"Yesterday Product {asin}",
                product_description="Yesterday description",
                product_description_images=["https://example.com/desc1.jpg"],
                product_information={"Brand": "Test Brand", "Model": "Test Model"},
                about_this_item=["Feature 1", "Feature 2"],
                image_count=5,
                image_urls=["https://example.com/image1.jpg", "https://example.com/image2.jpg"],
                video_count=2,
                video_urls=["https://example.com/video1.mp4"],
                sale_price=99.99,
                list_price=109.99,
                sale_percentage=10,
                best_deal="Limited Time Offer",
                lightning_deal="",
                coupon="SAVE10",
                bag_sale="",
                rating=4.5,
                rating_count=100,
                brand_store_link="https://example.com/store",
                sold_by_link="https://example.com/seller",
                advertised_asins=["B123456789"],
                amazon_choice=0,
                inventory="In Stock",
                crawl_error=None
            )
            
            db_session.add(yesterday_data)
            logger.info(f"Created yesterday data for {asin}")
        
        db_session.commit()
        logger.info(f"Created yesterday data for {len(test_asins)} ASINs")
        
    except Exception as e:
        logger.error(f"Error creating yesterday data: {e}")
        db_session.rollback()
        raise
    finally:
        db_session.close()

async def ensure_asins_in_watchlist():
    """Đảm bảo ASINs có trong watchlist"""
    
    test_asins = [
        "B0CSVB9C5G",
        "B0016HF5GK", 
        "B004Q4DRJW"
    ]
    
    logger.info("Adding ASINs to watchlist for daily crawl...")
    result = await crawler_scheduler.add_multiple_asins(test_asins, "daily", "Test daily crawl", crawl_immediately=False)
    logger.info(f"Add result: {result}")
    
    # Set next_crawl to now so they will be crawled
    db_session = get_db_session()
    try:
        for asin in test_asins:
            watchlist_item = db_session.query(ASINWatchlist).filter_by(asin=asin).first()
            if watchlist_item:
                watchlist_item.next_crawl = datetime.utcnow()
                logger.info(f"Set next_crawl to now for {asin}")
        
        db_session.commit()
        logger.info("Updated next_crawl for all ASINs")
        
    except Exception as e:
        logger.error(f"Error updating watchlist: {e}")
        db_session.rollback()
    finally:
        db_session.close()

async def test_daily_crawl_with_notification():
    """Test daily crawl với Telegram notifications"""
    
    try:
        logger.info("=== Testing Daily Crawl with Telegram Notifications ===")
        
        # 1. Không tạo dữ liệu hôm qua nữa (đã có sẵn)
        logger.info("Using existing yesterday's data...")
        
        # 2. Start scheduler
        crawler_scheduler.start()
        logger.info("Scheduler started")
        
        # 3. Đảm bảo ASINs có trong watchlist và sẵn sàng crawl
        await ensure_asins_in_watchlist()
        
        # 4. Test daily crawl job
        logger.info("Testing daily crawl job...")
        logger.info("This will crawl the 3 ASINs and compare with yesterday's data")
        logger.info("If there are changes, Telegram notifications will be sent!")
        
        await crawler_scheduler.daily_crawl_job()
        
        # 5. Get stats
        stats = await crawler_scheduler.get_watchlist_stats()
        logger.info(f"Watchlist stats: {stats}")
        
        logger.info("=== Test completed ===")
        logger.info("Check Telegram for notifications!")
        logger.info("If you see changes in price, rating, or other data, you should get Telegram messages!")
        
    except Exception as e:
        logger.error(f"Test failed: {e}")
        raise
    finally:
        # Stop scheduler
        crawler_scheduler.stop()
        logger.info("Scheduler stopped")

if __name__ == "__main__":
    print("Starting test...")
    print("This will:")
    print("1. Use existing yesterday's data for 3 ASINs")
    print("2. Add ASINs to watchlist")
    print("3. Crawl today's data from Amazon")
    print("4. Compare and send Telegram notifications if there are changes")
    print("=" * 50)
    
    asyncio.run(test_daily_crawl_with_notification()) 