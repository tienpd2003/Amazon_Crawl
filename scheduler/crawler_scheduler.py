import asyncio
import pytz
import random
from datetime import datetime, timedelta
from typing import List, Dict, Optional
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger
import concurrent.futures
import threading
from queue import Queue
import time

from config.settings import settings
from database.connection import get_db_session
from database.models import ASINWatchlist
from crawler.amazon_crawler import AmazonCrawler
from crawler.optimized_crawler import OptimizedAmazonCrawler
from crawler.change_detector import detect_changes
from utils.logger import get_logger
from utils.batch_import_optimized import optimized_batch_importer

logger = get_logger(__name__)

class CrawlerScheduler:
    def __init__(self):
        self.scheduler = AsyncIOScheduler()
        self.session = get_db_session()
        self.timezone = pytz.timezone(settings.SCHEDULER_TIMEZONE)
        self.is_running = False
        
        # Batch processing settings - giống batch_import.py
        self.batch_size = 50  # Mặc định 50 để đồng bộ với batch_import_optimized.py
        self.max_concurrent_crawlers = 2  # Giảm từ 5 xuống 2
        self.crawl_queue = Queue()
        self.active_crawlers = 0
        self.crawler_lock = threading.Lock()
        
        # Port pool để tránh conflict - giống batch_import.py
        self.port_pool = list(range(9222, 10000))
        self.used_ports = set()
        self.port_lock = asyncio.Lock()
        
    async def _get_available_port(self) -> int:
        """Lấy port available từ pool - giống batch_import.py"""
        async with self.port_lock:
            available_ports = [p for p in self.port_pool if p not in self.used_ports]
            if not available_ports:
                # Reset pool nếu hết port
                self.used_ports.clear()
                available_ports = self.port_pool
            
            port = random.choice(available_ports)
            self.used_ports.add(port)
            return port
    
    async def _release_port(self, port: int):
        """Giải phóng port - giống batch_import.py"""
        async with self.port_lock:
            self.used_ports.discard(port)
        
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
            if self.scheduler.get_job('batch_processor'):
                self.scheduler.remove_job('batch_processor')
            
            # Schedule daily crawl
            self.scheduler.add_job(
                self.daily_crawl_job,
                CronTrigger(hour=hour, minute=minute, timezone=self.timezone),
                id='daily_crawl',
                name='Daily ASIN Crawl',
                max_instances=1,
                coalesce=True
            )
            
            # Schedule batch processor (runs every 30 minutes)
            self.scheduler.add_job(
                self.batch_processor_job,
                CronTrigger(minute='*/30', timezone=self.timezone),
                id='batch_processor',
                name='Batch Crawl Processor',
                max_instances=1
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
            logger.info(f"Crawler scheduler started - Daily crawl at {settings.DAILY_CRAWL_TIME}, Batch size: {self.batch_size}")
            
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
        """Main daily crawl job - sử dụng concurrent crawling như batch_import_optimized.py"""
        logger.info("Starting daily crawl job (optimized)")
        start_time = datetime.utcnow()
        
        try:
            # Get all active ASINs from watchlist
            active_asins = self._get_active_asins()
            
            if not active_asins:
                logger.warning("No active ASINs found in watchlist")
                return
            
            logger.info(f"Found {len(active_asins)} ASINs to crawl")
            
            # Extract ASIN strings from ASINWatchlist objects
            asin_list = [asin_data.asin for asin_data in active_asins]
            
            # Dùng engine tối ưu
            crawl_result = await optimized_batch_importer._crawl_asins_optimized(asin_list, batch_size=self.batch_size)
            
            # Calculate final stats
            end_time = datetime.utcnow()
            crawl_duration = (end_time - start_time).total_seconds()
            
            logger.info(
                f"Daily crawl completed (optimized) - "
                f"Total: {crawl_result['total_asins']}, "
                f"Successful: {crawl_result['successful_crawls']}, "
                f"Failed: {crawl_result['failed_crawls']}, "
                f"Batches: {crawl_result['batches_processed']}, "
                f"Duration: {crawl_duration:.1f}s"
            )
            
        except Exception as e:
            logger.error(f"Error in daily crawl job (optimized): {e}")

    async def _crawl_asins_in_batches(self, asin_list: List[str], batch_size: int = 2, delay_seconds: int = 2) -> Dict:
        """DEPRECATED: Use optimized_batch_importer._crawl_asins_optimized instead"""
        logger.warning("_crawl_asins_in_batches is deprecated. Use optimized_batch_importer._crawl_asins_optimized instead.")
        return await optimized_batch_importer._crawl_asins_optimized(asin_list, batch_size=self.batch_size)

    async def _crawl_single_batch(self, asin_batch: List[str]) -> Dict:
        """Crawl a single batch of ASINs concurrently - giống batch_import.py"""
        batch_result = {
            'batch_size': len(asin_batch),
            'successful': 0,
            'failed': 0,
            'results': []
        }
        
        try:
            logger.info(f"Starting concurrent crawl for {len(asin_batch)} ASINs with separate browser instances")
            
            # Create tasks for truly concurrent crawling
            tasks = []
            for asin in asin_batch:
                # Each ASIN gets its own browser instance
                task = self._crawl_single_asin_async(asin)
                tasks.append(task)
            
            # Execute all tasks concurrently
            logger.info(f"Launching {len(tasks)} concurrent browser instances...")
            results = await asyncio.gather(*tasks, return_exceptions=True)
            
            # Process results
            for i, result in enumerate(results):
                asin = asin_batch[i]
                
                if isinstance(result, Exception):
                    batch_result['failed'] += 1
                    logger.error(f"Exception crawling {asin}: {result}")
                    batch_result['results'].append({
                        'asin': asin,
                        'success': False,
                        'error': str(result)
                    })
                else:
                    if result['success']:
                        batch_result['successful'] += 1
                        logger.info(f"Successfully crawled {asin}")
                    else:
                        batch_result['failed'] += 1
                        logger.error(f"Failed to crawl {asin}: {result.get('error', 'Unknown error')}")
                    
                    batch_result['results'].append({
                        'asin': asin,
                        'success': result['success'],
                        'error': result.get('error')
                    })
            
            logger.info(f"Batch completed: {batch_result['successful']} successful, {batch_result['failed']} failed")
            return batch_result
            
        except Exception as e:
            logger.error(f"Error in single batch crawl: {e}")
            batch_result['error'] = str(e)
            return batch_result

    async def _crawl_single_asin_async(self, asin: str) -> Dict:
        """Crawl a single ASIN with its own browser instance - giống batch_import.py"""
        port = None
        try:
            # Lấy port available từ pool
            port = await self._get_available_port()
            
            # Create a new crawler instance for each ASIN (separate browser tab)
            from crawler.amazon_crawler import AmazonCrawler
            
            crawler = AmazonCrawler()
            
            try:
                # Crawl product with unique port - run in thread to avoid blocking
                product_data = await asyncio.to_thread(crawler.crawl_product, asin, port)
                
                # Save to database with new session - also run in thread
                await asyncio.to_thread(crawler.save_to_database, product_data)
                
                # Update watchlist with new session - run in thread
                await asyncio.to_thread(self._update_watchlist, asin)
                
                # Detect changes and send notifications
                change_result = await detect_changes(asin, product_data)
                
                result = {
                    'asin': asin,
                    'success': product_data.get('crawl_success', False),
                    'error': product_data.get('crawl_error'),
                    'changes': change_result,
                    'crawl_time': datetime.utcnow()
                }
                
                # Chỉ log kết quả cuối
                status = "✅ Success" if result['success'] else "❌ Failed"
                logger.info(f"ASIN {asin}: {status}")
                
                return result
                
            finally:
                crawler.close()
                
        except Exception as e:
            logger.error(f"ASIN {asin}: ❌ Error - {str(e)}")
            return {
                'asin': asin,
                'success': False,
                'error': str(e),
                'changes': {},
                'crawl_time': datetime.utcnow()
            }
        finally:
            # Giải phóng port
            if port:
                await self._release_port(port)

    def _update_watchlist(self, asin: str):
        """Update watchlist for an ASIN (synchronous method for threading) - giống batch_import.py"""
        try:
            from database.connection import get_db_session
            from database.models import ASINWatchlist
            
            db_session = get_db_session()
            try:
                watchlist_item = db_session.query(ASINWatchlist).filter_by(asin=asin).first()
                if watchlist_item:
                    watchlist_item.last_crawled = datetime.utcnow()
                    watchlist_item.next_crawl = self._calculate_next_crawl(watchlist_item)
                    db_session.commit()
            except Exception as e:
                logger.error(f"Error updating watchlist for {asin}: {e}")
                db_session.rollback()
            finally:
                db_session.close()
        except Exception as e:
            logger.error(f"Error in _update_watchlist for {asin}: {e}")

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
                    existing.next_crawl = self._calculate_next_crawl(existing)
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
                next_crawl=self._calculate_next_crawl()
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
    
    async def batch_processor_job(self):
        """Process crawl queue in batches"""
        try:
            # Get ASINs that need crawling
            active_asins = self._get_active_asins()
            
            if not active_asins:
                logger.info("No ASINs need crawling in batch processor")
                return
            
            logger.info(f"Batch processor: Found {len(active_asins)} ASINs to process")
            
            # Process in batches
            for i in range(0, len(active_asins), self.batch_size):
                batch = active_asins[i:i + self.batch_size]
                await self._process_crawl_batch(batch)
                
                # Small delay between batches to avoid overwhelming the system
                await asyncio.sleep(5)
                
        except Exception as e:
            logger.error(f"Error in batch processor job: {e}")

    async def _process_crawl_batch(self, asin_batch: List[ASINWatchlist]):
        """Process a batch of ASINs for crawling using optimized crawler"""
        logger.info(f"Processing batch of {len(asin_batch)} ASINs with optimized crawler")
        
        try:
            # Extract ASINs from batch
            asin_list = [asin_data.asin for asin_data in asin_batch]
            
            # Use optimized crawler for batch processing
            optimized_crawler = OptimizedAmazonCrawler(
                max_workers=self.max_concurrent_crawlers,
                batch_size=self.batch_size
            )
            
            try:
                # Crawl batch
                result = optimized_crawler.crawl_batch(asin_list)
                
                # Update watchlist based on results
                successful_crawls = 0
                failed_crawls = 0
                
                for crawl_result in result.get('results', []):
                    asin = crawl_result.get('asin')
                    if crawl_result.get('success'):
                        successful_crawls += 1
                        
                        # Update watchlist
                        asin_data = next((a for a in asin_batch if a.asin == asin), None)
                        if asin_data:
                            asin_data.last_crawled = datetime.utcnow()
                            asin_data.next_crawl = self._calculate_next_crawl(asin_data)
                    else:
                        failed_crawls += 1
                        logger.error(f"Failed to crawl {asin}: {crawl_result.get('error')}")
                
                # Commit batch results
                try:
                    self.session.commit()
                    logger.info(f"Optimized batch completed: {successful_crawls} success, {failed_crawls} failed, "
                               f"Duration: {result.get('duration', 0):.2f}s")
                except Exception as e:
                    logger.error(f"Error committing batch results: {e}")
                    self.session.rollback()
                    
            finally:
                optimized_crawler.close()
                
        except Exception as e:
            logger.error(f"Error in optimized batch processing: {e}")
            # Fallback to original method if optimized crawler fails
            await self._process_crawl_batch_fallback(asin_batch)
    
    async def _process_crawl_batch_fallback(self, asin_batch: List[ASINWatchlist]):
        """Fallback method using original crawler"""
        logger.info(f"Using fallback method for batch of {len(asin_batch)} ASINs")
        
        # Use ThreadPoolExecutor for concurrent crawling
        with concurrent.futures.ThreadPoolExecutor(max_workers=self.max_concurrent_crawlers) as executor:
            # Submit crawl tasks
            future_to_asin = {}
            for asin_data in asin_batch:
                future = executor.submit(self._crawl_single_asin_sync, asin_data.asin)
                future_to_asin[future] = asin_data.asin
            
            # Process completed tasks
            successful_crawls = 0
            failed_crawls = 0
            
            for future in concurrent.futures.as_completed(future_to_asin):
                asin = future_to_asin[future]
                try:
                    result = future.result()
                    if result.get('success'):
                        successful_crawls += 1
                        
                        # Update watchlist
                        asin_data = next((a for a in asin_batch if a.asin == asin), None)
                        if asin_data:
                            asin_data.last_crawled = datetime.utcnow()
                            asin_data.next_crawl = self._calculate_next_crawl(asin_data)
                    else:
                        failed_crawls += 1
                        logger.error(f"Failed to crawl {asin}: {result.get('error')}")
                        
                except Exception as e:
                    failed_crawls += 1
                    logger.error(f"Exception crawling {asin}: {e}")
            
            # Commit batch results
            try:
                self.session.commit()
                logger.info(f"Fallback batch completed: {successful_crawls} success, {failed_crawls} failed")
            except Exception as e:
                logger.error(f"Error committing batch results: {e}")
                self.session.rollback()

    def _crawl_single_asin_sync(self, asin: str) -> Dict:
        """Synchronous version of crawl_single_asin for ThreadPoolExecutor"""
        crawler = AmazonCrawler()
        try:
            # Crawl product
            product_data = crawler.crawl_product(asin)
            
            # Save to database
            crawler.save_to_database(product_data)
            
            # Note: Change detection is async, so we'll handle it separately
            # For now, just return the crawl result
            
            return {
                'asin': asin,
                'success': product_data.get('crawl_success', False),
                'error': product_data.get('crawl_error'),
                'crawl_time': datetime.utcnow()
            }
            
        except Exception as e:
            logger.error(f"Error in sync crawl for {asin}: {e}")
            return {
                'asin': asin,
                'success': False,
                'error': str(e),
                'crawl_time': datetime.utcnow()
            }
        finally:
            crawler.close()

    def _get_active_asins(self, include_all_active: bool = False) -> List[ASINWatchlist]:
        """Get list of active ASINs that need crawling based on next_crawl time"""
        try:
            if include_all_active:
                # Get all active ASINs regardless of next_crawl time
                active_asins = (
                    self.session.query(ASINWatchlist)
                    .filter_by(is_active=True)
                    .all()
                )
            else:
                # Get ASINs that are due for crawling
                now = datetime.utcnow()
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
    
    def _calculate_next_crawl(self, asin_data: ASINWatchlist = None) -> datetime:
        """Calculate next crawl time - 5:30 UTC of next day after last_crawled"""
        if asin_data and asin_data.last_crawled:
            # Use last_crawled as base
            last_crawled_date = asin_data.last_crawled.date()
            next_day = last_crawled_date + timedelta(days=1)
        else:
            # If no last_crawled, use current time as base
            now = datetime.utcnow()
            next_day = now.date() + timedelta(days=1)
        
        # Calculate 5:30 UTC of next day
        next_crawl_time = datetime.combine(next_day, datetime.min.time().replace(hour=5, minute=30))
        
        return next_crawl_time
    
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

    async def add_multiple_asins(self, asin_list: List[str], crawl_frequency: str = "daily", notes: str = "", crawl_immediately: bool = True) -> Dict:
        """Add multiple ASINs to watchlist at once"""
        logger.info(f"Adding {len(asin_list)} ASINs to watchlist (crawl_immediately={crawl_immediately})")
        
        results = {
            'total_requested': len(asin_list),
            'added': 0,
            'added_no_crawl': 0,
            'reactivated': 0,
            'exists': 0,
            'errors': 0,
            'error_details': []
        }
        
        try:
            # Process in batches to avoid memory issues
            batch_size = 1000
            for i in range(0, len(asin_list), batch_size):
                batch = asin_list[i:i + batch_size]
                
                for asin in batch:
                    try:
                        # Clean ASIN (remove whitespace, convert to uppercase)
                        clean_asin = asin.strip().upper()
                        if not clean_asin or len(clean_asin) != 10:
                            results['errors'] += 1
                            results['error_details'].append(f"Invalid ASIN format: {asin}")
                            continue
                        
                        # Check if ASIN already exists
                        existing = self.session.query(ASINWatchlist).filter_by(asin=clean_asin).first()
                        if existing:
                            if not existing.is_active:
                                # Reactivate
                                existing.is_active = True
                                existing.crawl_frequency = crawl_frequency
                                existing.notes = notes
                                if crawl_immediately:
                                    # Set next_crawl to now for immediate crawling
                                    existing.next_crawl = datetime.utcnow()
                                else:
                                    existing.next_crawl = self._calculate_next_crawl(existing)
                                results['reactivated'] += 1
                            else:
                                results['exists'] += 1
                            continue

                        # Check if already crawled
                        from database.models import ProductCrawlHistory
                        has_crawled = self.session.query(ProductCrawlHistory).filter_by(asin=clean_asin, crawl_success=True).first()
                        
                        # Create new watchlist item
                        if crawl_immediately:
                            # Set next_crawl to now for immediate crawling
                            next_crawl_time = datetime.utcnow()
                        else:
                            # Use normal schedule
                            next_crawl_time = self._calculate_next_crawl()
                        
                        watchlist_item = ASINWatchlist(
                            asin=clean_asin,
                            crawl_frequency=crawl_frequency,
                            notes=notes,
                            next_crawl=next_crawl_time
                        )
                        self.session.add(watchlist_item)
                        
                        if has_crawled:
                            results['added_no_crawl'] += 1
                        else:
                            results['added'] += 1
                            
                    except Exception as e:
                        results['errors'] += 1
                        results['error_details'].append(f"{asin}: {str(e)}")
                        logger.error(f"Error adding ASIN {asin}: {e}")
                
                # Commit batch
                try:
                    self.session.commit()
                    logger.info(f"Committed batch {i//batch_size + 1}: {len(batch)} ASINs")
                except Exception as e:
                    self.session.rollback()
                    logger.error(f"Error committing batch: {e}")
                    results['errors'] += len(batch)
                    results['error_details'].append(f"Batch commit error: {str(e)}")
            
            logger.info(f"Batch import completed: {results}")
            return results
            
        except Exception as e:
            logger.error(f"Error in batch import: {e}")
            self.session.rollback()
            results['errors'] = len(asin_list)
            results['error_details'].append(f"General error: {str(e)}")
            return results

    async def get_watchlist_stats(self) -> Dict:
        """Get statistics about the watchlist"""
        try:
            total_asins = self.session.query(ASINWatchlist).count()
            active_asins = self.session.query(ASINWatchlist).filter_by(is_active=True).count()
            due_for_crawl = len(self._get_active_asins())
            
            # Get frequency distribution
            frequency_stats = {}
            frequencies = self.session.query(ASINWatchlist.crawl_frequency, 
                                           self.session.query(ASINWatchlist).filter_by(is_active=True).count()).group_by(ASINWatchlist.crawl_frequency).all()
            
            for freq, count in frequencies:
                frequency_stats[freq] = count
            
            return {
                'total_asins': total_asins,
                'active_asins': active_asins,
                'due_for_crawl': due_for_crawl,
                'frequency_distribution': frequency_stats,
                'batch_size': self.batch_size,
                'max_concurrent_crawlers': self.max_concurrent_crawlers
            }
            
        except Exception as e:
            logger.error(f"Error getting watchlist stats: {e}")
            return {}

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

async def add_multiple_asins(asin_list: List[str], frequency: str = "daily", notes: str = "", crawl_immediately: bool = True) -> Dict:
    """Add multiple ASINs to watchlist"""
    return await crawler_scheduler.add_multiple_asins(asin_list, frequency, notes, crawl_immediately)

async def remove_asin(asin: str) -> bool:
    """Remove ASIN from watchlist"""
    return await crawler_scheduler.remove_asin_from_watchlist(asin)

async def get_watchlist_stats() -> Dict:
    """Get watchlist statistics"""
    return await crawler_scheduler.get_watchlist_stats()

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