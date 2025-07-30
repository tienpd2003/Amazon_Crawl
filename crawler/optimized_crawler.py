import time
import random
import re
import json
from typing import Dict, List, Optional, Tuple
from datetime import datetime
from urllib.parse import urljoin, urlparse
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
import queue
import gc

from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from selenium.common.exceptions import TimeoutException, NoSuchElementException, WebDriverException
from webdriver_manager.chrome import ChromeDriverManager
from bs4 import BeautifulSoup

from config.settings import settings
from database.connection import get_db_session
from database.models import Product, ProductCrawlHistory
from utils.logger import get_logger

logger = get_logger(__name__)

class OptimizedAmazonCrawler:
    """
    Optimized Amazon Crawler for large-scale crawling
    Features:
    - Connection pooling
    - Resource management
    - Batch processing
    - Memory optimization
    - Retry mechanisms
    """
    
    def __init__(self, max_workers: int = 5, batch_size: int = 100):
        self.max_workers = max_workers
        self.batch_size = batch_size
        self.driver_pool = queue.Queue(maxsize=max_workers)
        self.session_pool = queue.Queue(maxsize=max_workers)
        self.lock = threading.Lock()
        
        # Initialize pools
        self._init_pools()
        
    def _init_pools(self):
        """Initialize driver and session pools"""
        logger.info(f"Initializing crawler pools: {self.max_workers} workers, batch size: {self.batch_size}")
        
        for i in range(self.max_workers):
            try:
                # Create driver
                driver = self._create_driver()
                self.driver_pool.put(driver)
                
                # Create session
                session = get_db_session()
                self.session_pool.put(session)
                
            except Exception as e:
                logger.error(f"Error initializing pool item {i}: {e}")
    
    def _create_driver(self):
        """Create optimized Chrome driver"""
        try:
            chrome_options = Options()
            
            # Headless mode for better performance
            if settings.HEADLESS_BROWSER:
                chrome_options.add_argument("--headless")
            
            # Performance optimizations
            chrome_options.add_argument("--no-sandbox")
            chrome_options.add_argument("--disable-dev-shm-usage")
            chrome_options.add_argument("--disable-blink-features=AutomationControlled")
            chrome_options.add_experimental_option("excludeSwitches", ["enable-automation"])
            chrome_options.add_experimental_option('useAutomationExtension', False)
            
            # Memory optimizations
            chrome_options.add_argument("--disable-extensions")
            chrome_options.add_argument("--disable-gpu")
            chrome_options.add_argument("--disable-web-security")
            chrome_options.add_argument("--allow-running-insecure-content")
            chrome_options.add_argument("--disable-images")  # Disable images for faster loading
            chrome_options.add_argument("--disable-javascript")  # Disable JS for basic data
            chrome_options.add_argument("--disable-plugins")
            chrome_options.add_argument("--disable-default-apps")
            
            # Memory limits
            chrome_options.add_argument("--memory-pressure-off")
            chrome_options.add_argument("--max_old_space_size=512")
            
            # Random user agent
            user_agent = random.choice(settings.USER_AGENTS)
            chrome_options.add_argument(f"--user-agent={user_agent}")
            
            # Window size
            chrome_options.add_argument("--window-size=1920,1080")
            
            # Create driver
            driver = webdriver.Chrome(options=chrome_options)
            
            # Execute script to hide automation
            driver.execute_script("Object.defineProperty(navigator, 'webdriver', {get: () => undefined})")
            
            return driver
            
        except Exception as e:
            logger.error(f"Failed to create driver: {e}")
            raise
    
    def _get_driver(self):
        """Get driver from pool"""
        try:
            return self.driver_pool.get(timeout=30)
        except queue.Empty:
            logger.warning("No drivers available in pool, creating new one")
            return self._create_driver()
    
    def _return_driver(self, driver):
        """Return driver to pool"""
        try:
            # Clear cookies and cache
            driver.delete_all_cookies()
            driver.execute_script("window.localStorage.clear();")
            driver.execute_script("window.sessionStorage.clear();")
            
            self.driver_pool.put(driver, timeout=5)
        except queue.Full:
            logger.warning("Driver pool full, closing driver")
            try:
                driver.quit()
            except:
                pass
    
    def _get_session(self):
        """Get database session from pool"""
        try:
            return self.session_pool.get(timeout=30)
        except queue.Empty:
            logger.warning("No sessions available in pool, creating new one")
            return get_db_session()
    
    def _return_session(self, session):
        """Return session to pool"""
        try:
            self.session_pool.put(session, timeout=5)
        except queue.Full:
            logger.warning("Session pool full, closing session")
            try:
                session.close()
            except:
                pass
    
    def crawl_batch(self, asin_list: List[str]) -> Dict:
        """Crawl a batch of ASINs concurrently"""
        logger.info(f"Starting batch crawl of {len(asin_list)} ASINs")
        
        results = {
            'total': len(asin_list),
            'successful': 0,
            'failed': 0,
            'errors': [],
            'start_time': datetime.utcnow(),
            'results': []
        }
        
        try:
            # Use ThreadPoolExecutor for concurrent crawling
            with ThreadPoolExecutor(max_workers=self.max_workers) as executor:
                # Submit crawl tasks
                future_to_asin = {}
                for asin in asin_list:
                    future = executor.submit(self._crawl_single_asin_optimized, asin)
                    future_to_asin[future] = asin
                
                # Process completed tasks
                for future in as_completed(future_to_asin):
                    asin = future_to_asin[future]
                    try:
                        result = future.result()
                        results['results'].append(result)
                        
                        if result.get('success'):
                            results['successful'] += 1
                        else:
                            results['failed'] += 1
                            results['errors'].append(f"{asin}: {result.get('error', 'Unknown error')}")
                            
                    except Exception as e:
                        results['failed'] += 1
                        results['errors'].append(f"{asin}: {str(e)}")
                        logger.error(f"Exception crawling {asin}: {e}")
            
            # Calculate duration
            results['end_time'] = datetime.utcnow()
            results['duration'] = (results['end_time'] - results['start_time']).total_seconds()
            results['avg_time_per_asin'] = results['duration'] / len(asin_list) if asin_list else 0
            
            logger.info(f"Batch completed: {results['successful']} success, {results['failed']} failed, "
                       f"Duration: {results['duration']:.2f}s, Avg: {results['avg_time_per_asin']:.2f}s")
            
        except Exception as e:
            logger.error(f"Error in batch crawl: {e}")
            results['errors'].append(f"Batch error: {str(e)}")
        
        return results
    
    def _crawl_single_asin_optimized(self, asin: str) -> Dict:
        """Optimized single ASIN crawl"""
        driver = None
        session = None
        
        try:
            # Get resources from pools
            driver = self._get_driver()
            session = self._get_session()
            
            # Crawl product
            product_data = self._crawl_product_optimized(driver, asin)
            
            # Save to database
            self._save_to_database_optimized(session, product_data)
            
            return {
                'asin': asin,
                'success': product_data.get('crawl_success', False),
                'error': product_data.get('crawl_error'),
                'crawl_time': datetime.utcnow()
            }
            
        except Exception as e:
            logger.error(f"Error in optimized crawl for {asin}: {e}")
            return {
                'asin': asin,
                'success': False,
                'error': str(e),
                'crawl_time': datetime.utcnow()
            }
        finally:
            # Return resources to pools
            if driver:
                self._return_driver(driver)
            if session:
                self._return_session(session)
    
    def _crawl_product_optimized(self, driver, asin: str) -> Dict:
        """Optimized product crawling with minimal data extraction"""
        url = settings.AMAZON_DP_URL.format(asin=asin)
        
        product_data = {
            'asin': asin,
            'crawl_date': datetime.utcnow(),
            'crawl_success': False,
            'crawl_error': None
        }
        
        try:
            # Navigate to product page
            driver.get(url)
            time.sleep(settings.CRAWLER_DELAY)
            
            # Check if page loaded successfully
            if "Page Not Found" in driver.title or "404" in driver.title:
                raise Exception("Product page not found")
            
            # Extract only essential data for performance
            product_data.update(self._extract_basic_info_optimized(driver))
            product_data.update(self._extract_pricing_optimized(driver))
            product_data.update(self._extract_ratings_optimized(driver))
            
            # Skip heavy operations for batch processing
            # product_data.update(self._extract_images_videos())  # Skip for performance
            # product_data.update(self._extract_technical_info())  # Skip for performance
            
            product_data['crawl_success'] = True
            
        except Exception as e:
            product_data['crawl_error'] = str(e)
            logger.error(f"Failed to crawl product {asin}: {e}")
        
        return product_data
    
    def _extract_basic_info_optimized(self, driver) -> Dict:
        """Extract basic info with minimal processing"""
        data = {}
        
        try:
            # Title
            try:
                title_element = driver.find_element(By.CSS_SELECTOR, "#productTitle")
                data['title'] = title_element.text.strip()
            except:
                data['title'] = "Unknown"
            
            # Amazon's Choice
            try:
                choice_element = driver.find_element(By.CSS_SELECTOR, ".mvt-ac-badge-wrapper")
                data['amazon_choice'] = 1
            except:
                data['amazon_choice'] = 0
            
        except Exception as e:
            logger.warning(f"Error extracting basic info: {e}")
        
        return data
    
    def _extract_pricing_optimized(self, driver) -> Dict:
        """Extract pricing with minimal processing"""
        data = {}
        
        try:
            # Find pricing container
            try:
                core_pricing_container = driver.find_element(By.CSS_SELECTOR, "#corePriceDisplay_desktop_feature_div")
                
                # Sale price
                try:
                    price_elem = core_pricing_container.find_element(By.CSS_SELECTOR, ".priceToPay .a-offscreen")
                    price_text = price_elem.text.strip()
                    data['sale_price'] = self._parse_price(price_text)
                except:
                    data['sale_price'] = None
                
                # Sale percentage
                try:
                    percentage_elem = core_pricing_container.find_element(By.CSS_SELECTOR, ".savingsPercentage")
                    percentage_text = percentage_elem.text.strip()
                    percent_match = re.search(r'-?(\d+)%', percentage_text)
                    if percent_match:
                        data['sale_percentage'] = int(percent_match.group(1))
                    else:
                        data['sale_percentage'] = 0
                except:
                    data['sale_percentage'] = 0
                
                # List price
                try:
                    list_price_elem = core_pricing_container.find_element(By.CSS_SELECTOR, ".basisPrice .a-price.a-text-price .a-offscreen")
                    list_price_text = list_price_elem.text.strip()
                    data['list_price'] = self._parse_price(list_price_text)
                except:
                    data['list_price'] = None
                    
            except:
                # Fallback
                data['sale_price'] = None
                data['sale_percentage'] = 0
                data['list_price'] = None
            
        except Exception as e:
            logger.warning(f"Error extracting pricing: {e}")
            data['sale_price'] = None
            data['sale_percentage'] = 0
            data['list_price'] = None
        
        return data
    
    def _extract_ratings_optimized(self, driver) -> Dict:
        """Extract ratings with minimal processing"""
        data = {}
        
        try:
            # Rating
            try:
                rating_elem = driver.find_element(By.CSS_SELECTOR, "#acrPopover span.a-size-small.a-color-base")
                rating_text = rating_elem.text.strip()
                rating_match = re.search(r'(\d+\.?\d*)', rating_text)
                if rating_match:
                    data['rating'] = float(rating_match.group(1))
                else:
                    data['rating'] = None
            except:
                data['rating'] = None
            
            # Rating count
            try:
                count_elem = driver.find_element(By.CSS_SELECTOR, "[data-hook='total-review-count']")
                count_text = count_elem.text.strip()
                count_match = re.search(r'([\d,]+)', count_text.replace(',', ''))
                if count_match:
                    data['rating_count'] = int(count_match.group(1).replace(',', ''))
                else:
                    data['rating_count'] = 0
            except:
                data['rating_count'] = 0
            
        except Exception as e:
            logger.warning(f"Error extracting ratings: {e}")
            data['rating'] = None
            data['rating_count'] = 0
        
        return data
    
    def _save_to_database_optimized(self, session, product_data: Dict):
        """Save to database with optimized session handling"""
        try:
            asin = product_data['asin']
            
            # Get or create product
            product = session.query(Product).filter_by(asin=asin).first()
            if not product:
                product = Product(asin=asin)
                session.add(product)
                session.commit()
            
            # Remove asin and meta fields
            save_data = {k: v for k, v in product_data.items() 
                        if k not in ['asin'] and v is not None}
            
            # Create crawl history record
            crawl_record = ProductCrawlHistory(
                product_id=product.id,
                asin=asin,
                **save_data
            )
            
            session.add(crawl_record)
            session.commit()
            
        except Exception as e:
            logger.error(f"Error saving to database: {e}")
            session.rollback()
    
    def _parse_price(self, price_text: str) -> Optional[float]:
        """Parse price from text"""
        if not price_text:
            return None
        
        price_match = re.search(r'([\d,]+\.?\d*)', price_text.replace(',', ''))
        if price_match:
            try:
                return float(price_match.group(1).replace(',', ''))
            except ValueError:
                return None
        return None
    
    def close(self):
        """Close all resources"""
        logger.info("Closing optimized crawler and cleaning up resources")
        
        # Close all drivers
        while not self.driver_pool.empty():
            try:
                driver = self.driver_pool.get_nowait()
                driver.quit()
            except:
                pass
        
        # Close all sessions
        while not self.session_pool.empty():
            try:
                session = self.session_pool.get_nowait()
                session.close()
            except:
                pass
        
        # Force garbage collection
        gc.collect()

# Utility function for batch crawling
def crawl_batch_optimized(asin_list: List[str], max_workers: int = 5, batch_size: int = 100) -> Dict:
    """Crawl a batch of ASINs using optimized crawler"""
    crawler = OptimizedAmazonCrawler(max_workers=max_workers, batch_size=batch_size)
    try:
        return crawler.crawl_batch(asin_list)
    finally:
        crawler.close()

if __name__ == "__main__":
    # Test optimized crawler
    test_asins = ["B019OZBSJ8", "B08N5WRWNW", "B07XYZ1234"]
    result = crawl_batch_optimized(test_asins, max_workers=3, batch_size=10)
    print(json.dumps(result, indent=2, default=str)) 