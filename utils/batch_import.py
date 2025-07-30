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

from scheduler.crawler_scheduler import add_multiple_asins, get_watchlist_stats, crawler_scheduler
from utils.logger import get_logger

logger = get_logger(__name__)

class BatchImporter:
    def __init__(self):
        self.supported_formats = ['.csv', '.txt', '.xlsx', '.xls']
        # Port pool để tránh conflict - range từ 9222-9999
        self.port_pool = list(range(9222, 10000))
        self.used_ports = set()
        self.port_lock = asyncio.Lock()
    
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
    
    def extract_asins_from_csv(self, file_path: str, asin_column: str = None) -> List[str]:
        """Extract ASINs from CSV file"""
        asins = []
        
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
                
                for row in reader:
                    asin = row.get(asin_column, '').strip()
                    if self.validate_asin(asin):
                        asins.append(asin.upper())
                    else:
                        logger.warning(f"Invalid ASIN in CSV: {asin}")
        
        except Exception as e:
            logger.error(f"Error reading CSV file: {e}")
            raise
        
        return asins
    
    def extract_asins_from_txt(self, file_path: str) -> List[str]:
        """Extract ASINs from text file (one per line)"""
        asins = []
        
        try:
            with open(file_path, 'r', encoding='utf-8') as file:
                for line_num, line in enumerate(file, 1):
                    asin = line.strip()
                    if self.validate_asin(asin):
                        asins.append(asin.upper())
                    else:
                        logger.warning(f"Invalid ASIN at line {line_num}: {asin}")
        
        except Exception as e:
            logger.error(f"Error reading text file: {e}")
            raise
        
        return asins
    
    def extract_asins_from_excel(self, file_path: str, sheet_name: str = None, asin_column: str = None) -> List[str]:
        """Extract ASINs from Excel file"""
        asins = []
        
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
            
            # Extract ASINs from the specified column
            for index, value in df[asin_column].items():
                asin = str(value).strip()
                if self.validate_asin(asin):
                    asins.append(asin.upper())
                else:
                    logger.warning(f"Invalid ASIN at row {index + 1}: {asin}")
        
        except Exception as e:
            logger.error(f"Error reading Excel file: {e}")
            raise
        
        return asins
    
    def extract_asins_from_file(self, file_path: str, **kwargs) -> List[str]:
        """Extract ASINs from file based on file extension"""
        if not os.path.exists(file_path):
            raise FileNotFoundError(f"File not found: {file_path}")
        
        file_ext = os.path.splitext(file_path)[1].lower()
        
        if file_ext not in self.supported_formats:
            raise ValueError(f"Unsupported file format: {file_ext}. Supported: {self.supported_formats}")
        
        logger.info(f"Extracting ASINs from {file_path}")
        
        if file_ext == '.csv':
            return self.extract_asins_from_csv(file_path, kwargs.get('asin_column'))
        elif file_ext == '.txt':
            return self.extract_asins_from_txt(file_path)
        elif file_ext in ['.xlsx', '.xls']:
            return self.extract_asins_from_excel(file_path, kwargs.get('sheet_name'), kwargs.get('asin_column'))
        else:
            raise ValueError(f"Unsupported file format: {file_ext}")
    
    async def import_from_file(self, file_path: str, crawl_frequency: str = "daily", notes: str = "", **kwargs) -> Dict:
        """Import ASINs from file to watchlist"""
        start_time = datetime.utcnow()
        
        try:
            # Extract ASINs from file
            asins = self.extract_asins_from_file(file_path, **kwargs)
            
            if not asins:
                return {
                    'success': False,
                    'error': 'No valid ASINs found in file',
                    'file_path': file_path,
                    'total_asins': 0
                }
            
            logger.info(f"Found {len(asins)} valid ASINs in {file_path}")
            
            # Remove duplicates while preserving order
            unique_asins = list(dict.fromkeys(asins))
            if len(unique_asins) != len(asins):
                logger.info(f"Removed {len(asins) - len(unique_asins)} duplicate ASINs")
            
            # Add to watchlist first
            result = await add_multiple_asins(unique_asins, crawl_frequency, notes, crawl_immediately=False)
            
            # Add file info to result
            result['file_path'] = file_path
            result['total_asins'] = len(unique_asins)
            result['import_time'] = datetime.utcnow()
            
            # Start immediate crawling with batch processing
            logger.info(f"Starting immediate crawl for {len(unique_asins)} ASINs")
            crawl_result = await self._crawl_asins_in_batches(unique_asins)
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
        """Import ASINs from list to watchlist"""
        start_time = datetime.utcnow()
        
        try:
            # Validate and clean ASINs
            valid_asins = []
            invalid_asins = []
            
            for asin in asin_list:
                if self.validate_asin(asin):
                    valid_asins.append(asin.strip().upper())
                else:
                    invalid_asins.append(asin)
            
            if invalid_asins:
                logger.warning(f"Found {len(invalid_asins)} invalid ASINs: {invalid_asins[:10]}...")
            
            if not valid_asins:
                return {
                    'success': False,
                    'error': 'No valid ASINs in list',
                    'total_asins': 0,
                    'invalid_asins': invalid_asins
                }
            
            # Remove duplicates
            unique_asins = list(dict.fromkeys(valid_asins))
            if len(unique_asins) != len(valid_asins):
                logger.info(f"Removed {len(valid_asins) - len(unique_asins)} duplicate ASINs")
            
            # Add to watchlist first
            result = await add_multiple_asins(unique_asins, crawl_frequency, notes, crawl_immediately=False)
            
            # Add list info to result
            result['total_asins'] = len(unique_asins)
            result['invalid_asins'] = invalid_asins
            result['import_time'] = datetime.utcnow()
            
            # Start immediate crawling with batch processing
            logger.info(f"Starting immediate crawl for {len(unique_asins)} ASINs")
            crawl_result = await self._crawl_asins_in_batches(unique_asins)
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
    
    async def _crawl_asins_in_batches(self, asin_list: List[str], batch_size: int = 2, delay_seconds: int = 2) -> Dict:
        """Crawl ASINs in batches with delay between batches"""
        logger.info(f"Starting batch crawl: {len(asin_list)} ASINs, batch_size={batch_size}, delay={delay_seconds}s")
        
        crawl_results = {
            'total_asins': len(asin_list),
            'batches_processed': 0,
            'successful_crawls': 0,
            'failed_crawls': 0,
            'batch_results': []
        }
        
        try:
            # Process ASINs in batches
            for i in range(0, len(asin_list), batch_size):
                batch = asin_list[i:i + batch_size]
                batch_num = i // batch_size + 1
                total_batches = (len(asin_list) + batch_size - 1) // batch_size
                
                logger.info(f"Processing batch {batch_num}/{total_batches}: {len(batch)} ASINs")
                
                # Crawl current batch
                batch_result = await self._crawl_single_batch(batch)
                crawl_results['batch_results'].append(batch_result)
                crawl_results['batches_processed'] += 1
                crawl_results['successful_crawls'] += batch_result['successful']
                crawl_results['failed_crawls'] += batch_result['failed']
                
                # Log batch progress
                logger.info(f"Batch {batch_num} completed: {batch_result['successful']} successful, {batch_result['failed']} failed")
                
                # Add delay between batches (except for the last batch)
                if i + batch_size < len(asin_list):
                    logger.info(f"Waiting {delay_seconds} seconds before next batch...")
                    await asyncio.sleep(delay_seconds)
            
            logger.info(f"Batch crawl completed: {crawl_results['successful_crawls']} successful, {crawl_results['failed_crawls']} failed")
            return crawl_results
            
        except Exception as e:
            logger.error(f"Error in batch crawl: {e}")
            crawl_results['error'] = str(e)
            return crawl_results
    
    async def _crawl_single_batch(self, asin_batch: List[str]) -> Dict:
        """Crawl a single batch of ASINs concurrently (2 ASINs at once with 2 separate browser tabs)"""
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
            
            # Execute all tasks concurrently - this will open 20 browser tabs simultaneously
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
        """Crawl a single ASIN with its own browser instance and database session"""
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
                
                result = {
                    'asin': asin,
                    'success': product_data.get('crawl_success', False),
                    'error': product_data.get('crawl_error'),
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
                'crawl_time': datetime.utcnow()
            }
        finally:
            # Giải phóng port
            if port:
                await self._release_port(port)
    
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

# Global importer instance
batch_importer = BatchImporter()

# Utility functions
async def import_from_file(file_path: str, crawl_frequency: str = "daily", notes: str = "", **kwargs) -> Dict:
    """Import ASINs from file"""
    return await batch_importer.import_from_file(file_path, crawl_frequency, notes, **kwargs)

async def import_from_list(asin_list: List[str], crawl_frequency: str = "daily", notes: str = "") -> Dict:
    """Import ASINs from list"""
    return await batch_importer.import_from_list(asin_list, crawl_frequency, notes)

async def get_import_stats() -> Dict:
    """Get import statistics"""
    return await get_watchlist_stats()

if __name__ == "__main__":
    # Test batch import
    async def test():
        # Test with sample ASINs
        sample_asins = [
            "B019OZBSJ8",  # Valid ASIN
            "B08N5WRWNW",  # Valid ASIN
            "INVALID123",  # Invalid ASIN
            "B019OZBSJ8",  # Duplicate
            "B08N5WRWNW"   # Duplicate
        ]
        
        print("Testing batch import...")
        result = await import_from_list(sample_asins, "daily", "Test import")
        print(f"Import result: {result}")
        
        # Get stats
        stats = await get_import_stats()
        print(f"Watchlist stats: {stats}")

    asyncio.run(test()) 