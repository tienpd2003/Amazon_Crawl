import asyncio
import csv
import logging
import os
import pandas as pd
import re
import random
import tempfile
from datetime import datetime
from typing import Dict, List, Optional
from concurrent.futures import ThreadPoolExecutor

from utils.logger import get_logger

logger = get_logger(__name__)

class OptimizedBatchImporter:
    def __init__(self):
        self.supported_formats = ['.csv', '.txt', '.xlsx', '.xls']
        # Port pool để tránh conflict - range từ 9222-9999
        self.port_pool = list(range(9222, 10000))
        self.used_ports = set()
        self.port_lock = asyncio.Lock()
        
        # Profile management để tái sử dụng
        self.profile_pool = {}  # {profile_id: {'crawler': crawler, 'port': port, 'delivery_set': bool}}
        self.profile_lock = asyncio.Lock()
        self.max_profiles = 50  # Số profile tối đa để tái sử dụng
    
    async def _get_or_create_profile(self, profile_id: int) -> Dict:
        """Lấy hoặc tạo profile mới để tái sử dụng"""
        async with self.profile_lock:
            if profile_id in self.profile_pool:
                profile = self.profile_pool[profile_id]
                logger.info(f"Reusing profile {profile_id} (port {profile['port']}) - delivery_set: {profile['delivery_set']}")
                return profile
            
            # Tạo profile mới nếu chưa có
            if len(self.profile_pool) >= self.max_profiles:
                # Xóa profile cũ nhất
                oldest_profile_id = min(self.profile_pool.keys())
                old_profile = self.profile_pool.pop(oldest_profile_id)
                old_profile['crawler'].close()
                await self._release_port(old_profile['port'])
                logger.info(f"Removed old profile {oldest_profile_id} to make room for new profile")
            
            # Lấy port mới
            port = await self._get_available_port()
            
            # Tạo crawler mới
            from crawler.amazon_crawler import AmazonCrawler
            crawler = AmazonCrawler()
            
            profile = {
                'crawler': crawler,
                'port': port,
                'delivery_set': False,
                'created_at': datetime.utcnow()
            }
            
            self.profile_pool[profile_id] = profile
            logger.info(f"Created new profile {profile_id} (port {port})")
            return profile
    
    async def _release_profile(self, profile_id: int):
        """Giải phóng profile"""
        async with self.profile_lock:
            if profile_id in self.profile_pool:
                profile = self.profile_pool.pop(profile_id)
                profile['crawler'].close()
                await self._release_port(profile['port'])
                logger.info(f"Released profile {profile_id}")
    
    async def _get_available_port(self) -> int:
        """Lấy port available từ pool"""
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
        """Giải phóng port"""
        async with self.port_lock:
            self.used_ports.discard(port)
    
    def validate_asin(self, asin: str) -> bool:
        """Validate ASIN format"""
        if not asin:
            return False
        
        # Clean ASIN
        clean_asin = asin.strip().upper()
        
        # ASIN must be exactly 10 characters, alphanumeric
        if len(clean_asin) != 10:
            return False
        
        # Check if it's alphanumeric
        if not re.match(r'^[A-Z0-9]{10}$', clean_asin):
            return False
        
        return True
    
    def extract_asins_from_csv(self, file_path: str, asin_column: str = None, category_column: str = None) -> List[Dict[str, str]]:
        """Extract ASINs and categories from CSV file"""
        asin_data = []
        
        try:
            with open(file_path, 'r', encoding='utf-8') as file:
                reader = csv.DictReader(file)
                
                # If no column specified, try to find ASIN column
                if not asin_column:
                    columns = reader.fieldnames
                    for col in columns:
                        if 'asin' in col.lower():
                            asin_column = col
                            break
                    
                    if not asin_column:
                        # If no ASIN column found, assume first column
                        asin_column = columns[0]
                
                # Try to find category column
                if not category_column:
                    columns = reader.fieldnames
                    for col in columns:
                        if 'category' in col.lower():
                            category_column = col
                            break
                
                for row in reader:
                    asin = row.get(asin_column, '').strip()
                    category = row.get(category_column, '').strip() if category_column else ""
                    
                    if self.validate_asin(asin):
                        asin_data.append({
                            "asin": asin.upper(),
                            "category": category
                        })
                    else:
                        logger.warning(f"Invalid ASIN in CSV: {asin}")
        
        except Exception as e:
            logger.error(f"Error reading CSV file: {e}")
            raise
        
        return asin_data
    
    def extract_asins_from_txt(self, file_path: str) -> List[Dict[str, str]]:
        """Extract ASINs from text file (one per line) - no category for txt files"""
        asin_data = []
        
        try:
            with open(file_path, 'r', encoding='utf-8') as file:
                for line_num, line in enumerate(file, 1):
                    asin = line.strip()
                    if self.validate_asin(asin):
                        asin_data.append({
                            "asin": asin.upper(),
                            "category": ""  # No category for txt files
                        })
                    else:
                        logger.warning(f"Invalid ASIN at line {line_num}: {asin}")
        
        except Exception as e:
            logger.error(f"Error reading text file: {e}")
            raise
        
        return asin_data
    
    def extract_asins_from_excel(self, file_path: str, sheet_name: str = None, asin_column: str = None, category_column: str = None) -> List[Dict[str, str]]:
        """Extract ASINs and categories from Excel file"""
        asin_data = []
        
        try:
            # Read Excel file
            if sheet_name:
                df = pd.read_excel(file_path, sheet_name=sheet_name)
            else:
                df = pd.read_excel(file_path)
            
            # If no column specified, try to find ASIN column
            if not asin_column:
                columns = df.columns.tolist()
                for col in columns:
                    if 'asin' in col.lower():
                        asin_column = col
                        break
                
                if not asin_column:
                    # If no ASIN column found, assume first column
                    asin_column = columns[0]
            
            # Try to find category column
            if not category_column:
                columns = df.columns.tolist()
                for col in columns:
                    if 'category' in col.lower():
                        category_column = col
                        break
            
            # Extract ASINs and categories from the specified columns
            for index, row in df.iterrows():
                asin = str(row[asin_column]).strip()
                category = str(row[category_column]).strip() if category_column and category_column in row else ""
                
                if self.validate_asin(asin):
                    asin_data.append({
                        "asin": asin.upper(),
                        "category": category
                    })
                else:
                    logger.warning(f"Invalid ASIN at row {index + 1}: {asin}")
        
        except Exception as e:
            logger.error(f"Error reading Excel file: {e}")
            raise
        
        return asin_data
    
    def extract_asins_from_file(self, file_path: str, **kwargs) -> List[Dict[str, str]]:
        """Extract ASINs and categories from file based on file extension"""
        if not os.path.exists(file_path):
            raise FileNotFoundError(f"File not found: {file_path}")
        
        file_ext = os.path.splitext(file_path)[1].lower()
        
        if file_ext not in self.supported_formats:
            raise ValueError(f"Unsupported file format: {file_ext}. Supported: {self.supported_formats}")
        
        logger.info(f"Extracting ASINs and categories from {file_path}")
        
        if file_ext == '.csv':
            return self.extract_asins_from_csv(file_path, kwargs.get('asin_column'), kwargs.get('category_column'))
        elif file_ext == '.txt':
            return self.extract_asins_from_txt(file_path)
        elif file_ext in ['.xlsx', '.xls']:
            return self.extract_asins_from_excel(file_path, kwargs.get('sheet_name'), kwargs.get('asin_column'), kwargs.get('category_column'))
        else:
            raise ValueError(f"Unsupported file format: {file_ext}")
    
    async def import_from_file(self, file_path: str, crawl_frequency: str = "daily", notes: str = "", **kwargs) -> Dict:
        """Import ASINs from file to watchlist with optimized profile reuse"""
        start_time = datetime.utcnow()
        
        try:
            # Extract ASINs and categories from file
            asin_data = self.extract_asins_from_file(file_path, **kwargs)
            
            if not asin_data:
                return {
                    'success': False,
                    'error': 'No valid ASINs found in file',
                    'file_path': file_path,
                    'total_asins': 0
                }
            
            # Extract just ASINs for watchlist
            asins = [item["asin"] for item in asin_data]
            
            logger.info(f"Found {len(asin_data)} valid ASINs in {file_path}")
            
            # Remove duplicates while preserving order
            unique_asin_data = []
            seen_asins = set()
            for item in asin_data:
                if item["asin"] not in seen_asins:
                    unique_asin_data.append(item)
                    seen_asins.add(item["asin"])
            
            if len(unique_asin_data) != len(asin_data):
                logger.info(f"Removed {len(asin_data) - len(unique_asin_data)} duplicate ASINs")
            
            # Extract unique ASINs for watchlist
            unique_asins = [item["asin"] for item in unique_asin_data]
            
            # Add to watchlist first
            from scheduler.crawler_scheduler import add_multiple_asins
            result = await add_multiple_asins(unique_asins, crawl_frequency, notes, crawl_immediately=False)
            
            # Add file info to result
            result['file_path'] = file_path
            result['total_asins'] = len(unique_asin_data)
            result['import_time'] = datetime.utcnow()
            
            # Start immediate crawling with optimized batch processing
            batch_size = kwargs.get('batch_size', 2)  # Get batch_size from kwargs
            logger.info(f"Starting optimized crawl for {len(unique_asin_data)} ASINs with batch_size={batch_size}")
            crawl_result = await self._crawl_asins_optimized(unique_asin_data, batch_size=batch_size)
            result['crawl_result'] = crawl_result
            
            result['duration'] = (datetime.utcnow() - start_time).total_seconds()
            
            logger.info(f"Import completed: {result}")
            return result
        
        except Exception as e:
            logger.error(f"Error importing from file {file_path}: {e}")
            return {
                'success': False,
                'error': str(e),
                'file_path': file_path,
                'total_asins': 0,
                'import_time': datetime.utcnow(),
                'duration': (datetime.utcnow() - start_time).total_seconds()
            }
    
    async def import_from_list(self, asin_list: List[str], crawl_frequency: str = "daily", notes: str = "") -> Dict:
        """Import ASINs from list to watchlist with optimized profile reuse"""
        start_time = datetime.utcnow()
        
        try:
            # Convert asin_list to asin_data format (no categories for list import)
            asin_data = []
            invalid_asins = []
            
            for asin in asin_list:
                if self.validate_asin(asin):
                    asin_data.append({
                        "asin": asin.strip().upper(),
                        "category": ""  # No category for list import
                    })
                else:
                    invalid_asins.append(asin)
            
            if invalid_asins:
                logger.warning(f"Found {len(invalid_asins)} invalid ASINs: {invalid_asins[:10]}...")
            
            if not asin_data:
                return {
                    'success': False,
                    'error': 'No valid ASINs in list',
                    'total_asins': 0,
                    'invalid_asins': invalid_asins
                }
            
            # Remove duplicates
            unique_asin_data = []
            seen_asins = set()
            for item in asin_data:
                if item["asin"] not in seen_asins:
                    unique_asin_data.append(item)
                    seen_asins.add(item["asin"])
            
            if len(unique_asin_data) != len(asin_data):
                logger.info(f"Removed {len(asin_data) - len(unique_asin_data)} duplicate ASINs")
            
            # Extract unique ASINs for watchlist
            unique_asins = [item["asin"] for item in unique_asin_data]
            
            # Add to watchlist first
            from scheduler.crawler_scheduler import add_multiple_asins
            result = await add_multiple_asins(unique_asins, crawl_frequency, notes, crawl_immediately=False)
            
            # Add list info to result
            result['total_asins'] = len(unique_asin_data)
            result['invalid_asins'] = invalid_asins
            result['import_time'] = datetime.utcnow()
            
            # Start immediate crawling with optimized batch processing
            logger.info(f"Starting optimized crawl for {len(unique_asin_data)} ASINs with default batch_size=2")
            crawl_result = await self._crawl_asins_optimized(unique_asin_data, batch_size=2)
            result['crawl_result'] = crawl_result
            
            result['duration'] = (datetime.utcnow() - start_time).total_seconds()
            
            logger.info(f"List import completed: {result}")
            return result
        
        except Exception as e:
            logger.error(f"Error importing from list: {e}")
            return {
                'success': False,
                'error': str(e),
                'total_asins': 0,
                'import_time': datetime.utcnow(),
                'duration': (datetime.utcnow() - start_time).total_seconds()
            }
    
    async def _crawl_asins_optimized(self, asin_data: List[Dict[str, str]], batch_size: int = 50, delay_seconds: int = 5) -> Dict:
        """Crawl ASINs with optimized profile reuse"""
        logger.info(f"Starting optimized crawl: {len(asin_data)} ASINs, batch_size={batch_size}, delay={delay_seconds}s")
        
        crawl_results = {
            'total_asins': len(asin_data),
            'batches_processed': 0,
            'successful_crawls': 0,
            'failed_crawls': 0,
            'profiles_used': 0,
            'batch_results': []
        }
        
        try:
            # Process ASINs in batches
            for i in range(0, len(asin_data), batch_size):
                batch = asin_data[i:i + batch_size]
                batch_num = i // batch_size + 1
                total_batches = (len(asin_data) + batch_size - 1) // batch_size
                
                logger.info(f"Processing batch {batch_num}/{total_batches}: {len(batch)} ASINs")
                
                # Crawl current batch with profile reuse
                batch_result = await self._crawl_batch_with_profile_reuse(batch)
                crawl_results['batch_results'].append(batch_result)
                crawl_results['batches_processed'] += 1
                crawl_results['successful_crawls'] += batch_result['successful']
                crawl_results['failed_crawls'] += batch_result['failed']
                crawl_results['profiles_used'] = batch_result['profiles_used']
                
                # Log batch progress
                logger.info(f"Batch {batch_num} completed: {batch_result['successful']} successful, {batch_result['failed']} failed, {batch_result['profiles_used']} profiles used")
                
                # Add delay between batches (except for the last batch)
                if i + batch_size < len(asin_data):
                    logger.info(f"Waiting {delay_seconds} seconds before next batch...")
                    await asyncio.sleep(delay_seconds)
            
            logger.info(f"Optimized crawl completed: {crawl_results['successful_crawls']} successful, {crawl_results['failed_crawls']} failed, {crawl_results['profiles_used']} profiles used")
            
            # Cleanup all profiles after crawl completion
            logger.info("Cleaning up all profiles and closing browser tabs...")
            await self.cleanup()
            
            return crawl_results
            
        except Exception as e:
            logger.error(f"Error in optimized crawl: {e}")
            crawl_results['error'] = str(e)
            
            # Cleanup profiles even if there was an error
            logger.info("Cleaning up profiles due to error...")
            await self.cleanup()
            
            return crawl_results
    
    async def _crawl_batch_with_profile_reuse(self, asin_batch: List[Dict[str, str]]) -> Dict:
        """Crawl a batch of ASINs with profile reuse - CONCURRENT processing"""
        batch_result = {
            'batch_size': len(asin_batch),
            'successful': 0,
            'failed': 0,
            'profiles_used': 0,
            'results': []
        }
        
        try:
            logger.info(f"Starting CONCURRENT batch crawl for {len(asin_batch)} ASINs")
            
            # Tạo tasks cho tất cả ASINs trong batch để chạy concurrent
            tasks = []
            for i, asin_item in enumerate(asin_batch):
                profile_id = i % self.max_profiles  # Luân phiên sử dụng profiles
                task = self._crawl_single_asin_concurrent(asin_item["asin"], profile_id, asin_item["category"])
                tasks.append(task)
            
            # Chạy tất cả tasks cùng lúc
            logger.info(f"Executing {len(tasks)} concurrent crawl tasks...")
            results = await asyncio.gather(*tasks, return_exceptions=True)
            
            # Xử lý kết quả
            for i, result in enumerate(results):
                asin_item = asin_batch[i]
                asin = asin_item["asin"]
                profile_id = i % self.max_profiles
                
                if isinstance(result, Exception):
                    # Task bị lỗi
                    batch_result['failed'] += 1
                    logger.error(f"❌ Exception crawling {asin}: {result}")
                    batch_result['results'].append({
                        'asin': asin,
                        'category': asin_item["category"],
                        'profile_id': profile_id,
                        'success': False,
                        'error': str(result)
                    })
                else:
                    # Task thành công
                    if result['success']:
                        batch_result['successful'] += 1
                        logger.info(f"✅ Successfully crawled {asin} with profile {profile_id}")
                    else:
                        batch_result['failed'] += 1
                        logger.error(f"❌ Failed to crawl {asin}: {result.get('error', 'Unknown error')}")
                    
                    batch_result['results'].append({
                        'asin': asin,
                        'category': asin_item["category"],
                        'profile_id': profile_id,
                        'port': result.get('port'),
                        'success': result['success'],
                        'error': result.get('error')
                    })
            
            # Tính số profiles đã sử dụng
            batch_result['profiles_used'] = min(len(asin_batch), self.max_profiles)
            
            logger.info(f"CONCURRENT batch completed: {batch_result['successful']} successful, {batch_result['failed']} failed, {batch_result['profiles_used']} profiles used")
            return batch_result
            
        except Exception as e:
            logger.error(f"Error in concurrent batch crawl: {e}")
            batch_result['error'] = str(e)
            return batch_result
    
    async def _crawl_single_asin_concurrent(self, asin: str, profile_id: int, category: str = "") -> Dict:
        """Crawl a single ASIN concurrently with a specific profile"""
        try:
            # Lấy hoặc tạo profile
            profile = await self._get_or_create_profile(profile_id)
            
            # Crawl với profile này
            result = await self._crawl_single_asin_with_profile(asin, profile, category)
            
            # Thêm thông tin port vào result
            result['port'] = profile['port']
            
            return result
            
        except Exception as e:
            logger.error(f"ASIN {asin}: ❌ Error in concurrent crawl - {str(e)}")
            return {
                'asin': asin,
                'category': category,
                'success': False,
                'error': str(e),
                'crawl_time': datetime.utcnow(),
                'port': None
            }
    
    async def _crawl_single_asin_with_profile(self, asin: str, profile: Dict, category: str = "") -> Dict:
        """Crawl a single ASIN with a specific profile"""
        try:
            crawler = profile['crawler']
            port = profile['port']
            
            # Crawl product with profile - run in thread to avoid blocking
            product_data = await asyncio.to_thread(crawler.crawl_product, asin, port)
            
            # Add category to product_data
            product_data['category'] = category
            
            # Update profile delivery_set status
            if product_data.get('crawl_success'):
                profile['delivery_set'] = True
            
            # Save to database with new session - also run in thread
            await asyncio.to_thread(crawler.save_to_database, product_data)
            
            # Update watchlist with new session - run in thread
            await asyncio.to_thread(self._update_watchlist, asin)
            
            result = {
                'asin': asin,
                'category': category,
                'success': product_data.get('crawl_success', False),
                'error': product_data.get('crawl_error'),
                'crawl_time': datetime.utcnow()
            }
            
            return result
            
        except Exception as e:
            logger.error(f"ASIN {asin}: ❌ Error - {str(e)}")
            return {
                'asin': asin,
                'category': category,
                'success': False,
                'error': str(e),
                'crawl_time': datetime.utcnow()
            }
    
    def _update_watchlist(self, asin: str):
        """Update watchlist for an ASIN (synchronous method for threading)"""
        try:
            from database.connection import get_db_session
            from database.models import ASINWatchlist
            from scheduler.crawler_scheduler import crawler_scheduler
            
            db_session = get_db_session()
            try:
                watchlist_item = db_session.query(ASINWatchlist).filter_by(asin=asin).first()
                if watchlist_item:
                    watchlist_item.last_crawled = datetime.utcnow()
                    watchlist_item.next_crawl = crawler_scheduler._calculate_next_crawl(watchlist_item)
                    db_session.commit()
            except Exception as e:
                logger.error(f"Error updating watchlist for {asin}: {e}")
                db_session.rollback()
            finally:
                db_session.close()
        except Exception as e:
            logger.error(f"Error in _update_watchlist for {asin}: {e}")
    
    async def cleanup(self):
        """Cleanup all profiles"""
        async with self.profile_lock:
            logger.info(f"Cleaning up {len(self.profile_pool)} profiles...")
            
            for profile_id, profile in list(self.profile_pool.items()):
                try:
                    logger.info(f"Closing profile {profile_id} (port: {profile['port']})")
                    profile['crawler'].close()
                    await self._release_port(profile['port'])
                except Exception as e:
                    logger.error(f"Error closing profile {profile_id}: {e}")
            
            self.profile_pool.clear()
            logger.info("✅ All profiles cleaned up and browser tabs closed")

# Global optimized importer instance
optimized_batch_importer = OptimizedBatchImporter()

# Utility functions
async def import_from_file_optimized(file_path: str, crawl_frequency: str = "daily", notes: str = "", **kwargs) -> Dict:
    """Import ASINs from file with optimized profile reuse"""
    return await optimized_batch_importer.import_from_file(file_path, crawl_frequency, notes, **kwargs)

async def import_from_list_optimized(asin_list: List[str], crawl_frequency: str = "daily", notes: str = "") -> Dict:
    """Import ASINs from list with optimized profile reuse"""
    return await optimized_batch_importer.import_from_list(asin_list, crawl_frequency, notes)

async def get_import_stats() -> Dict:
    """Get import statistics"""
    from scheduler.crawler_scheduler import get_watchlist_stats
    return await get_watchlist_stats()

async def cleanup_profiles():
    """Cleanup all profiles"""
    await optimized_batch_importer.cleanup()

if __name__ == "__main__":
    # Test optimized batch import
    async def test():
        # Test with sample ASINs
        sample_asins = [
            "B0DZD9S5GC",
            "B0DZDB8H69", 
            "B0DP3G4GVQ",
            "B0FDQHJ46H",
            "B0DFM5VSWF",
            "B0D9YZJ3V7"
        ]
        
        print("Testing optimized batch import...")
        result = await import_from_list_optimized(sample_asins, "daily", "Test optimized import")
        print(f"Import result: {result}")
        
        # Get stats
        stats = await get_import_stats()
        print(f"Watchlist stats: {stats}")
        
        # Cleanup
        await cleanup_profiles()

    asyncio.run(test()) 