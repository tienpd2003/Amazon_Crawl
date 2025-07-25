import asyncio
import pytz
from datetime import datetime, timedelta
from typing import List
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger

from config.settings import settings
from database.connection import get_db_session
from database.models import ASINWatchlist
from crawler.amazon_crawler import AmazonCrawler
from crawler.change_detector import detect_changes
from utils.logger import get_logger

logger = get_logger(__name__)

class CrawlerScheduler:
    def __init__(self):
        self.scheduler = AsyncIOScheduler()
        self.session = get_db_session()
        self.timezone = pytz.timezone(settings.SCHEDULER_TIMEZONE)
        self.is_running = False
        
    def start(self):
        """Start the scheduler"""
        try:
            # Parse daily crawl time
            hour, minute = map(int, settings.DAILY_CRAWL_TIME.split(':'))
            
            # Remove existing jobs if they exist
            if self.scheduler.get_job('daily_crawl'):
                self.scheduler.remove_job('daily_crawl')
            if self.scheduler.get_job('hourly_stats'):
                self.scheduler.remove_job('hourly_stats')
            
            # Schedule daily crawl
            self.scheduler.add_job(
                self.daily_crawl_job,
                CronTrigger(hour=hour, minute=minute, timezone=self.timezone),
                id='daily_crawl',
                name='Daily ASIN Crawl',
                max_instances=1,
                coalesce=True
            )
            
            # Schedule hourly stats update
            self.scheduler.add_job(
                self.update_stats_job,
                CronTrigger(minute=0, timezone=self.timezone),
                id='hourly_stats',
                name='Hourly Stats Update',
                max_instances=1
            )
            
            # Start scheduler if not already running
            if not self.scheduler.running:
                self.scheduler.start()
            self.is_running = True
            logger.info(f"Crawler scheduler started - Daily crawl at {settings.DAILY_CRAWL_TIME}")
            
        except Exception as e:
            logger.error(f"Failed to start scheduler: {e}")
            raise
    
    def stop(self):
        """Stop the scheduler"""
        if self.scheduler.running:
            self.scheduler.shutdown()
            self.is_running = False
            logger.info("Crawler scheduler stopped")
    
    async def daily_crawl_job(self):
        """Main daily crawl job"""
        logger.info("Starting daily crawl job")
        start_time = datetime.utcnow()
        
        try:
            # Get all active ASINs from watchlist
            active_asins = self._get_active_asins()
            
            if not active_asins:
                logger.warning("No active ASINs found in watchlist")
                return
            
            logger.info(f"Found {len(active_asins)} ASINs to crawl")
            
            # Initialize crawler
            crawler = AmazonCrawler()
            
            # Stats tracking
            total_crawled = 0
            successful_crawls = 0
            failed_crawls = 0
            errors = []
            
            try:
                # Crawl each ASIN
                for asin_data in active_asins:
                    asin = asin_data.asin
                    
                    try:
                        logger.info(f"Crawling ASIN: {asin}")
                        
                        # Crawl product
                        product_data = crawler.crawl_product(asin)
                        
                        # Save to database
                        crawler.save_to_database(product_data)
                        
                        # Detect changes and send notifications
                        change_result = await detect_changes(asin, product_data)
                        
                        if product_data.get('crawl_success'):
                            successful_crawls += 1
                            logger.info(f"Successfully crawled {asin}")
                            
                            # Update last crawled time
                            asin_data.last_crawled = datetime.utcnow()
                            asin_data.next_crawl = self._calculate_next_crawl(asin_data)
                            
                        else:
                            failed_crawls += 1
                            error_msg = product_data.get('crawl_error', 'Unknown error')
                            errors.append(f"{asin}: {error_msg}")
                            logger.error(f"Failed to crawl {asin}: {error_msg}")
                        
                        total_crawled += 1
                        
                        # Random delay between crawls
                        crawler._random_delay()
                        
                    except Exception as e:
                        failed_crawls += 1
                        error_msg = str(e)
                        errors.append(f"{asin}: {error_msg}")
                        logger.error(f"Error crawling {asin}: {e}")
                        total_crawled += 1
                
            finally:
                crawler.close()
                self.session.commit()
            
            # Calculate stats
            end_time = datetime.utcnow()
            crawl_duration = (end_time - start_time).total_seconds()
            avg_crawl_time = crawl_duration / total_crawled if total_crawled > 0 else 0
            
            # Log crawl stats (no DB save)
            logger.info(
                f"Daily crawl completed - Total: {total_crawled}, "
                f"Success: {successful_crawls}, Failed: {failed_crawls}, "
                f"Duration: {crawl_duration:.1f}s, Avg: {avg_crawl_time:.2f}s"
            )
            if errors:
                logger.warning(f"Crawl errors: {errors}")
            
        except Exception as e:
            logger.error(f"Error in daily crawl job: {e}")
    
    async def crawl_single_asin(self, asin: str) -> dict:
        """Crawl a single ASIN immediately"""
        logger.info(f"Manual crawl requested for ASIN: {asin}")
        
        crawler = AmazonCrawler()
        try:
            # Crawl product
            product_data = crawler.crawl_product(asin)
            
            # Save to database
            crawler.save_to_database(product_data)
            
            # Detect changes and send notifications
            change_result = await detect_changes(asin, product_data)
            
            # Update watchlist if ASIN exists
            watchlist_item = self.session.query(ASINWatchlist).filter_by(asin=asin).first()
            if watchlist_item:
                watchlist_item.last_crawled = datetime.utcnow()
                watchlist_item.next_crawl = self._calculate_next_crawl(watchlist_item)
                self.session.commit()
            
            result = {
                'asin': asin,
                'success': product_data.get('crawl_success', False),
                'error': product_data.get('crawl_error'),
                'changes': change_result,
                'crawl_time': datetime.utcnow()
            }
            
            logger.info(f"Manual crawl completed for {asin}: {'Success' if result['success'] else 'Failed'}")
            return result
            
        except Exception as e:
            logger.error(f"Error in manual crawl for {asin}: {e}")
            return {
                'asin': asin,
                'success': False,
                'error': str(e),
                'changes': {},
                'crawl_time': datetime.utcnow()
            }
        finally:
            crawler.close()
    
    async def add_asin_to_watchlist(self, asin: str, crawl_frequency: str = "daily", notes: str = "") -> str:
        """Add ASIN to watchlist. Return 'added', 'added_no_crawl', 'reactivated', or 'exists'"""
        try:
            # Check if ASIN already exists
            existing = self.session.query(ASINWatchlist).filter_by(asin=asin).first()
            if existing:
                if not existing.is_active:
                    # Reactivate and update info
                    existing.is_active = True
                    existing.crawl_frequency = crawl_frequency
                    existing.notes = notes
                    existing.next_crawl = datetime.utcnow()
                    self.session.commit()
                    logger.info(f"Re-activated ASIN {asin} in watchlist with {crawl_frequency} frequency")
                    return 'reactivated'
                logger.warning(f"ASIN {asin} already exists in watchlist")
                return 'exists'

            # Nếu đã có dữ liệu crawl thành công thì chỉ thêm vào watchlist, không crawl lại
            from database.models import ProductCrawlHistory
            has_crawled = self.session.query(ProductCrawlHistory).filter_by(asin=asin, crawl_success=True).first()
            watchlist_item = ASINWatchlist(
                asin=asin,
                crawl_frequency=crawl_frequency,
                notes=notes,
                next_crawl=datetime.utcnow()  # Crawl immediately
            )
            self.session.add(watchlist_item)
            self.session.commit()
            logger.info(f"Added ASIN {asin} to watchlist with {crawl_frequency} frequency")
            if has_crawled:
                return 'added_no_crawl'
            return 'added'
        except Exception as e:
            logger.error(f"Error adding ASIN {asin} to watchlist: {e}")
            self.session.rollback()
            return 'error'
    
    async def remove_asin_from_watchlist(self, asin: str) -> bool:
        """Remove ASIN from watchlist"""
        try:
            watchlist_item = self.session.query(ASINWatchlist).filter_by(asin=asin).first()
            if not watchlist_item:
                logger.warning(f"ASIN {asin} not found in watchlist")
                return False
            
            # Soft delete - mark as inactive
            watchlist_item.is_active = False
            self.session.commit()
            
            logger.info(f"Removed ASIN {asin} from watchlist")
            return True
            
        except Exception as e:
            logger.error(f"Error removing ASIN {asin} from watchlist: {e}")
            self.session.rollback()
            return False
    
    async def update_stats_job(self):
        """Hourly stats update job"""
        try:
            logger.info("Updating hourly stats")
            # This could include cleanup tasks, health checks, etc.
            
        except Exception as e:
            logger.error(f"Error in stats update job: {e}")
    
    def _get_active_asins(self) -> List[ASINWatchlist]:
        """Get list of active ASINs that need crawling"""
        try:
            now = datetime.utcnow()
            
            # Get ASINs that are due for crawling
            active_asins = (
                self.session.query(ASINWatchlist)
                .filter_by(is_active=True)
                .filter(
                    (ASINWatchlist.next_crawl.is_(None)) |
                    (ASINWatchlist.next_crawl <= now)
                )
                .all()
            )
            
            return active_asins
            
        except Exception as e:
            logger.error(f"Error getting active ASINs: {e}")
            return []
    
    def _calculate_next_crawl(self, asin_data: ASINWatchlist) -> datetime:
        """Calculate next crawl time based on frequency"""
        now = datetime.utcnow()
        
        if asin_data.crawl_frequency == "daily":
            return now + timedelta(days=1)
        elif asin_data.crawl_frequency == "weekly":
            return now + timedelta(weeks=1)
        elif asin_data.crawl_frequency == "monthly":
            return now + timedelta(days=30)
        else:
            # Default to daily
            return now + timedelta(days=1)
    
    def get_scheduler_status(self) -> dict:
        """Get scheduler status"""
        jobs = []
        if self.scheduler.running:
            for job in self.scheduler.get_jobs():
                jobs.append({
                    'id': job.id,
                    'name': job.name,
                    'next_run': job.next_run_time,
                    'trigger': str(job.trigger)
                })
        
        return {
            'running': self.is_running,
            'jobs': jobs,
            'timezone': settings.SCHEDULER_TIMEZONE
        }
    
    def close(self):
        """Close scheduler and database session"""
        self.stop()
        if self.session:
            self.session.close()

# Global scheduler instance
crawler_scheduler = CrawlerScheduler()

# Utility functions
async def start_scheduler():
    """Start the crawler scheduler"""
    crawler_scheduler.start()

async def stop_scheduler():
    """Stop the crawler scheduler"""
    crawler_scheduler.stop()

async def crawl_asin_now(asin: str) -> dict:
    """Crawl an ASIN immediately"""
    return await crawler_scheduler.crawl_single_asin(asin)

async def add_asin(asin: str, frequency: str = "daily", notes: str = "") -> bool:
    """Add ASIN to watchlist"""
    return await crawler_scheduler.add_asin_to_watchlist(asin, frequency, notes)

async def remove_asin(asin: str) -> bool:
    """Remove ASIN from watchlist"""
    return await crawler_scheduler.remove_asin_from_watchlist(asin)

if __name__ == "__main__":
    # Test scheduler
    async def test():
        try:
            await start_scheduler()
            print("Scheduler started")
            
            # Keep running
            while True:
                await asyncio.sleep(60)
                
        except KeyboardInterrupt:
            print("Stopping scheduler...")
            await stop_scheduler()
    
    asyncio.run(test()) 