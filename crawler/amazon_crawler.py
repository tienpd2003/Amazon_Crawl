import time
import random
import re
import json
from typing import Dict, List, Optional, Tuple
from datetime import datetime
from urllib.parse import urljoin, urlparse

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

class AmazonCrawler:
    def __init__(self):
        self.driver = None
        self.wait = None
        self.session = get_db_session()
        
    def _setup_driver(self):
        """Setup Chrome driver with anti-detection measures"""
        try:
            chrome_options = Options()
            
            # Debug logging for headless setting
            logger.info(f"HEADLESS_BROWSER setting: {settings.HEADLESS_BROWSER}")
            
            # Run in headless mode by default (hidden browser)
            if settings.HEADLESS_BROWSER:
                chrome_options.add_argument("--headless")
                logger.info("Running in HEADLESS mode (browser hidden)")
            else:
                logger.info("Running in VISIBLE mode (browser window will show)")
            
            # Anti-detection measures
            chrome_options.add_argument("--no-sandbox")
            chrome_options.add_argument("--disable-dev-shm-usage")
            chrome_options.add_argument("--disable-blink-features=AutomationControlled")
            chrome_options.add_experimental_option("excludeSwitches", ["enable-automation"])
            chrome_options.add_experimental_option('useAutomationExtension', False)
            
            # Windows specific fixes
            chrome_options.add_argument("--disable-extensions")
            chrome_options.add_argument("--disable-gpu")
            chrome_options.add_argument("--disable-web-security")
            chrome_options.add_argument("--allow-running-insecure-content")
            
            # Random user agent
            user_agent = random.choice(settings.USER_AGENTS)
            chrome_options.add_argument(f"--user-agent={user_agent}")
            
            # Window size
            chrome_options.add_argument("--window-size=1920,1080")
            
            # Try multiple approaches to setup driver
            self.driver = None
            last_error = None
            
            # Approach 1: Try ChromeDriverManager with specific version
            try:
                logger.info("Attempting ChromeDriverManager setup...")
                from webdriver_manager.chrome import ChromeDriverManager
                import os
                
                # Force download latest version
                manager = ChromeDriverManager()
                driver_path = manager.install()
                
                # Verify the file exists and is executable
                if os.path.exists(driver_path):
                    logger.info(f"ChromeDriver found at: {driver_path}")
                    service = Service(driver_path)
                    self.driver = webdriver.Chrome(service=service, options=chrome_options)
                    logger.info("ChromeDriverManager setup successful")
                else:
                    raise Exception(f"ChromeDriver not found at {driver_path}")
                    
            except Exception as e:
                last_error = e
                logger.warning(f"ChromeDriverManager failed: {e}")
            
            # Approach 2: Try system Chrome driver
            if not self.driver:
                try:
                    logger.info("Attempting system ChromeDriver...")
                    self.driver = webdriver.Chrome(options=chrome_options)
                    logger.info("System ChromeDriver setup successful")
                except Exception as e:
                    last_error = e
                    logger.warning(f"System ChromeDriver failed: {e}")
            
            # Approach 3: Try downloading manually
            if not self.driver:
                try:
                    logger.info("Attempting manual ChromeDriver download...")
                    driver_path = self._download_chromedriver_manually()
                    if driver_path:
                        service = Service(driver_path)
                        self.driver = webdriver.Chrome(service=service, options=chrome_options)
                        logger.info("Manual ChromeDriver setup successful")
                    else:
                        raise Exception("Manual download failed")
                except Exception as e:
                    last_error = e
                    logger.warning(f"Manual ChromeDriver failed: {e}")
            
            if not self.driver:
                raise Exception(f"All ChromeDriver setup methods failed. Last error: {last_error}")
            
            # Execute script to hide automation
            self.driver.execute_script("Object.defineProperty(navigator, 'webdriver', {get: () => undefined})")
            
            self.wait = WebDriverWait(self.driver, settings.TIMEOUT)
            logger.info("Chrome driver setup successful")
            
        except Exception as e:
            logger.error(f"Failed to setup Chrome driver: {e}")
            raise
    
    def _download_chromedriver_manually(self):
        """Download ChromeDriver manually as fallback"""
        try:
            import requests
            import zipfile
            import subprocess
            from pathlib import Path
            
            # Get Chrome version
            chrome_version = self._get_chrome_version()
            if not chrome_version:
                return None
            
            logger.info(f"Chrome version detected: {chrome_version}")
            
            # Create drivers directory
            drivers_dir = Path("drivers")
            drivers_dir.mkdir(exist_ok=True)
            
            # Try to get latest ChromeDriver version for this Chrome version
            try:
                version_url = f"https://chromedriver.storage.googleapis.com/LATEST_RELEASE_{chrome_version}"
                response = requests.get(version_url, timeout=10)
                if response.status_code == 200:
                    driver_version = response.text.strip()
                else:
                    # Fallback to latest stable
                    response = requests.get("https://chromedriver.storage.googleapis.com/LATEST_RELEASE", timeout=10)
                    driver_version = response.text.strip()
                
                logger.info(f"ChromeDriver version: {driver_version}")
                
                # Download URL
                download_url = f"https://chromedriver.storage.googleapis.com/{driver_version}/chromedriver_win32.zip"
                
                # Download
                response = requests.get(download_url, timeout=30)
                if response.status_code != 200:
                    logger.error(f"Failed to download ChromeDriver: HTTP {response.status_code}")
                    return None
                
                # Save and extract
                zip_path = drivers_dir / "chromedriver.zip"
                with open(zip_path, 'wb') as f:
                    f.write(response.content)
                
                # Extract
                with zipfile.ZipFile(zip_path, 'r') as zip_ref:
                    zip_ref.extractall(drivers_dir)
                
                # Clean up zip
                zip_path.unlink()
                
                # Return path to executable
                chromedriver_path = drivers_dir / "chromedriver.exe"
                if chromedriver_path.exists():
                    logger.info(f"ChromeDriver manually downloaded: {chromedriver_path}")
                    return str(chromedriver_path)
                
            except Exception as e:
                logger.error(f"Error in manual download: {e}")
                return None
                
        except Exception as e:
            logger.error(f"Manual ChromeDriver download failed: {e}")
            return None
    
    def _get_chrome_version(self):
        """Get Chrome browser version"""
        try:
            import subprocess
            
            # Try different Chrome paths on Windows
            chrome_paths = [
                r"C:\Program Files\Google\Chrome\Application\chrome.exe",
                r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
            ]
            
            for chrome_path in chrome_paths:
                try:
                    result = subprocess.run([chrome_path, "--version"], 
                                          capture_output=True, text=True, timeout=10)
                    if result.returncode == 0:
                        version = result.stdout.strip().split()[-1]
                        major_version = version.split('.')[0]
                        return major_version
                except:
                    continue
            
            logger.warning("Could not detect Chrome version")
            return None
            
        except Exception as e:
            logger.error(f"Error getting Chrome version: {e}")
            return None
    
    def _random_delay(self):
        """Add random delay to mimic human behavior"""
        delay = settings.CRAWLER_DELAY + random.uniform(0, 2)
        time.sleep(delay)
    
    def _set_delivery_location(self, zip_code: str = "10009"):
        """Set delivery location to New York 10009 with human-like typing"""
        try:
            logger.info(f"Attempting to set delivery location to zip code: {zip_code}")
            
            # Click delivery location button
            try:
                location_button = self.driver.find_element(By.CSS_SELECTOR, "#nav-global-location-popover-link")
                location_button.click()
                logger.info("Clicked delivery location button")
                time.sleep(3)
            except Exception as e:
                logger.warning(f"Could not click location button: {e}")
                return False
            
            # Enter zip code slowly like a human
            try:
                zip_input = WebDriverWait(self.driver, 10).until(
                    EC.presence_of_element_located((By.XPATH, "//input[contains(@aria-label, 'zip') or contains(@placeholder, 'zip')]"))
                )
                zip_input.clear()
                time.sleep(0.5)
                
                # Type each character with delay to mimic human typing
                for char in zip_code:
                    zip_input.send_keys(char)
                    time.sleep(random.uniform(0.1, 0.3))  # Random delay between keystrokes
                    
                logger.info(f"Entered zip code: {zip_code} (human-like typing)")
                time.sleep(1)
            except Exception as e:
                logger.warning(f"Could not enter zip code: {e}")
                return False
            
            # Click Apply button using exact CSS selector
            try:
                apply_button = WebDriverWait(self.driver, 10).until(
                    EC.element_to_be_clickable((By.CSS_SELECTOR, "input.a-button-input[type='submit'][aria-labelledby='GLUXZipUpdate-announce']"))
                )
                apply_button.click()
                logger.info("Clicked Apply button")
                time.sleep(3)
            except Exception as e:
                logger.warning(f"Could not click Apply: {e}")
                return False
            
            # Click Continue button - try multiple selectors
            try:
                # Try different ways to click Continue button
                continue_clicked = False
                
                # Method 1: Click the input element
                try:
                    continue_button = WebDriverWait(self.driver, 5).until(
                        EC.element_to_be_clickable((By.CSS_SELECTOR, "#GLUXConfirmClose"))
                    )
                    continue_button.click()
                    logger.info("Clicked Continue button (input)")
                    continue_clicked = True
                except:
                    pass
                
                # Method 2: Click the span text element if input failed
                if not continue_clicked:
                    try:
                        span_button = self.driver.find_element(By.CSS_SELECTOR, "span#GLUXConfirmClose-announce")
                        span_button.click()
                        logger.info("Clicked Continue button (span)")
                        continue_clicked = True
                    except:
                        pass
                
                # Method 3: Click the outer span container
                if not continue_clicked:
                    try:
                        outer_span = self.driver.find_element(By.CSS_SELECTOR, "span.a-button-inner[data-action='GLUXConfirmAction']")
                        outer_span.click()
                        logger.info("Clicked Continue button (outer span)")
                        continue_clicked = True
                    except:
                        pass
                
                # Method 4: JavaScript click as last resort
                if not continue_clicked:
                    try:
                        js_button = self.driver.find_element(By.CSS_SELECTOR, "#GLUXConfirmClose")
                        self.driver.execute_script("arguments[0].click();", js_button)
                        logger.info("Clicked Continue button (JavaScript)")
                        continue_clicked = True
                    except:
                        pass
                
                if continue_clicked:
                                                    # Wait 7 seconds for page to load new data
                    logger.info("Waiting 7 seconds for page to load updated data...")
                    time.sleep(7)
                else:
                    logger.warning("Could not click Continue button with any method")
                    logger.info("Waiting 7 seconds for any data updates...")
                    time.sleep(7)
                
            except Exception as e:
                logger.warning(f"Error in Continue button logic: {e}")
                # Continue anyway as location might still be set
                logger.info("Waiting 7 seconds for any data updates...")
                time.sleep(7)
            
            # Verify location change
            try:
                location_element = self.driver.find_element(By.CSS_SELECTOR, "#glow-ingress-line2")
                new_location = location_element.text
                logger.info(f"New delivery location: {new_location}")
                
                if zip_code in new_location or "New York" in new_location:
                    logger.info(f"Successfully changed delivery to: {new_location}")
                    return True
                else:
                    logger.warning(f"Location may not have changed: {new_location}")
                    return True  # Continue crawling anyway
            except Exception as e:
                logger.warning(f"Could not verify location change: {e}")
                return True  # Continue crawling anyway
                
        except Exception as e:
            logger.error(f"❌ Error setting delivery location: {e}")
            return False
    

    
    def crawl_product(self, asin: str) -> Dict:
        """Crawl product information from Amazon"""
        if not self.driver:
            self._setup_driver()
            
        url = settings.AMAZON_DP_URL.format(asin=asin)
        logger.info(f"Crawling product: {asin} from {url}")
        
        product_data = {
            'asin': asin,
            'crawl_date': datetime.utcnow(),
            'crawl_success': False,
            'crawl_error': None
        }
        
        try:
            # Navigate to product page  
            self.driver.get(url)
            self._random_delay()
            
            # Check if page loaded successfully
            if "Page Not Found" in self.driver.title or "404" in self.driver.title:
                raise Exception("Product page not found")
            
            # Display current delivery location
            try:
                location_element = self.driver.find_element(By.CSS_SELECTOR, "#glow-ingress-line2")
                current_location = location_element.text
                logger.info(f"Current delivery location: {current_location}")
                
                # Set delivery location to New York 10009 if not already set
                if "10009" not in current_location and "New York" not in current_location:
                    logger.info("Setting delivery location to New York 10009...")
                    location_changed = self._set_delivery_location()
                    # No need to refresh - page already updated after 7s wait in location change
                else:
                    logger.info("Delivery location already set to New York area")
                    
            except Exception as e:
                logger.warning(f"Could not read delivery location: {e}")
            
            # Extract all product information (EXCEPT images/videos first to avoid DOM changes)
            product_data.update(self._extract_basic_info())
            product_data.update(self._extract_pricing())
            product_data.update(self._extract_ratings())
            product_data.update(self._extract_promotions())
            product_data.update(self._extract_inventory())
            product_data.update(self._extract_seller_info())
            product_data.update(self._extract_technical_info())
            product_data.update(self._extract_advertisements())
            
            # Extract images and videos LAST to avoid affecting other data extraction
            # (clicking video thumbnail may change DOM structure)
            logger.info("Starting images/videos extraction (last step)")
            product_data.update(self._extract_images_videos())
            
            # Format output according to required 22 fields
            product_data = self._format_final_output(product_data)
            
            product_data['crawl_success'] = True
            logger.info(f"Successfully crawled product {asin}")
            
        except Exception as e:
            error_msg = str(e)
            product_data['crawl_error'] = error_msg
            logger.error(f"Failed to crawl product {asin}: {error_msg}")
        
        return product_data
    
    def _format_final_output(self, data: Dict) -> Dict:
        """Format output according to required 22 fields"""
        try:
            # Keep sale_percentage exactly as extracted - NEVER recalculate
            existing_percentage = data.get('sale_percentage', 0)
            data['sale_percentage'] = existing_percentage
            logger.info(f"Final sale_percentage: {existing_percentage}% (preserved from extraction)")
            
            # Ensure values are correct format
            data['coupon'] = data.get('coupon', "")  # Empty string if no coupon
            data['best_deal'] = data.get('best_deal', "")  # Empty string if no deal
            data['lightning_deal'] = data.get('lightning_deal', "")  # Empty string if no lightning deal
            data['amazon_choice'] = data.get('amazon_choice', 0)
            
            # No mapping needed - field names match exactly
            formatted_data = {
                # Core product info (4 fields)
                'asin': data.get('asin'),
                'title': data.get('title'),
                'product_description': data.get('product_description', ''),
                'product_information': data.get('product_information', {}),
                'about_this_item': data.get('about_this_item', []),
                
                # Media (4 fields)
                'image_count': data.get('image_count', 0),
                'image_urls': data.get('image_urls', []),
                'video_count': data.get('video_count', 0), 
                'video_urls': data.get('video_urls', []),
                
                # Pricing (3 fields)
                'sale_price': data.get('sale_price'),
                'list_price': data.get('list_price'),
                'sale_percentage': data.get('sale_percentage', 0),
                
                # Promotions (3 fields)
                'best_deal': data.get('best_deal', ""),  # Text like "Limited time deal"
                'lightning_deal': data.get('lightning_deal', ""),  # Text like "81% claimed"
                'coupon': data.get('coupon', ""),  # Coupon text like "Apply $40 coupon"
                'bag_sale': data.get('bag_sale', ''),
                
                # Reviews (2 fields)
                'rating': data.get('rating'),
                'rating_count': data.get('rating_count', 0),
                
                # Seller info (2 fields)
                'brand_store_link': data.get('brand_store_link', ''),
                'sold_by_link': data.get('sold_by_link', ''),
                
                # Marketing (3 fields)
                'advertised_asins': data.get('advertised_asins', []),
                'amazon_choice': data.get('amazon_choice', 0),
                'inventory': data.get('inventory', 'Unknown'),
                
                # Meta
                'crawl_date': data.get('crawl_date'),
                'crawl_success': data.get('crawl_success'),
                'crawl_error': data.get('crawl_error')
            }
            
            return formatted_data
            
        except Exception as e:
            logger.error(f"Error formatting final output: {e}")
            return data

    def _extract_basic_info(self) -> Dict:
        """Extract basic product information"""
        data = {}
        
        try:
            # Product title - using exact CSS selector
            try:
                title_element = self.driver.find_element(By.CSS_SELECTOR, "#productTitle")
                data['title'] = title_element.text.strip()
                logger.info(f"Extracted title: {data['title'][:50]}...")
            except:
                # Fallback selectors
                title_selectors = [".product-title", "h1.a-size-large"]
                data['title'] = self._get_text_by_selectors(title_selectors)
            
            # About this item - using exact CSS selector from HTML
            bullet_points = []
            try:
                # Extract from feature-bullets div with exact structure
                bullet_elements = self.driver.find_elements(By.CSS_SELECTOR, "#feature-bullets ul.a-unordered-list.a-vertical.a-spacing-mini li.a-spacing-mini span.a-list-item")
                for bullet in bullet_elements:
                    text = bullet.text.strip()
                    if text and len(text) > 10:
                        bullet_points.append(text)
                
                # Fallback to simpler selector if needed
                if not bullet_points:
                    bullet_elements = self.driver.find_elements(By.CSS_SELECTOR, "#feature-bullets ul li span.a-list-item")
                    for bullet in bullet_elements:
                        text = bullet.text.strip()
                        if text and len(text) > 10:
                            bullet_points.append(text)
                
                # Also check expanded content if exists
                expanded_bullets = self.driver.find_elements(By.CSS_SELECTOR, "#feature-bullets .a-expander-content ul li span.a-list-item")
                for bullet in expanded_bullets:
                    text = bullet.text.strip()
                    if text and len(text) > 10 and text not in bullet_points:
                        bullet_points.append(text)
                        
                logger.info(f"Extracted {len(bullet_points)} about_this_item bullet points")
            except Exception as e:
                logger.warning(f"Could not extract about_this_item: {e}")
            
            data['about_this_item'] = bullet_points
            
            # Amazon's Choice (1 or 0) - targeting specific HTML structure
            choice_selectors = [
                ".mvt-ac-badge-wrapper",                                                     # Main badge wrapper
                ".mvt-ac-badge-rectangle",                                                   # Badge rectangle container  
                "[data-action='a-popover'][data-a-popover*='amazons-choice-popover']",     # Specific popover trigger
                ".mvt-ac-badge-wrapper .a-size-small",                                      # Text "Amazon's Choice"
                "[data-csa-c-type='element'][data-csa-c-content-id='amazon-choice-badge']", # Legacy selector
                ".ac-badge-wrapper",                                                         # Alternative wrapper
                "[aria-label*='Amazon\\'s Choice']"                                        # Fallback aria-label
            ]
            data['amazon_choice'] = 1 if self._get_element_by_selectors(choice_selectors) else 0
            
        except Exception as e:
            logger.error(f"Error extracting basic info: {e}")
        
        return data
    
    def _extract_pricing(self) -> Dict:
        """Extract all pricing information from same corePriceDisplay container"""
        data = {}
        
        try:
            # Find the main pricing container that contains all pricing info
            # Target the corePriceDisplay_desktop_feature_div structure from user's HTML
            core_pricing_container = None
            sale_price = None
            sale_percentage = 0
            list_price = None
            
            # Try to find the core pricing container first
            try:
                # Look for the main corePriceDisplay container
                core_pricing_container = self.driver.find_element(By.CSS_SELECTOR, "#corePriceDisplay_desktop_feature_div")
                logger.info("Found corePriceDisplay_desktop_feature_div container")
            except:
                # Fallback to class-based selector
                try:
                    core_pricing_containers = self.driver.find_elements(By.CSS_SELECTOR, "[data-feature-name='corePriceDisplay_desktop']")
                    if core_pricing_containers:
                        core_pricing_container = core_pricing_containers[0]
                        logger.info("Found corePriceDisplay container via data-feature-name")
                except:
                    logger.warning("Could not find corePriceDisplay container")
            
            # Extract all pricing from the core container
            if core_pricing_container:
                logger.info("Extracting all pricing from corePriceDisplay container")
                
                # Extract sale price from priceToPay within the container
                try:
                    price_selectors = [
                        ".priceToPay .a-offscreen",
                        ".priceToPay .a-price-whole", 
                        ".a-price .a-offscreen"
                    ]
                    
                    for selector in price_selectors:
                        try:
                            price_elem = core_pricing_container.find_element(By.CSS_SELECTOR, selector)
                            price_text = price_elem.text.strip()
                            if price_text:
                                sale_price = self._parse_price(price_text)
                                if sale_price:
                                    logger.info(f"Extracted sale price from corePriceDisplay: ${sale_price}")
                                    break
                        except:
                            continue
                except Exception as e:
                    logger.warning(f"Could not extract sale price from container: {e}")
                
                # Extract sale percentage from savingsPercentage within the container
                try:
                    percentage_elem = core_pricing_container.find_element(By.CSS_SELECTOR, ".savingsPercentage")
                    percentage_text = percentage_elem.text.strip()
                    logger.info(f"Found percentage text in corePriceDisplay: '{percentage_text}'")
                    
                    # Extract percentage value (e.g., "-20%" -> 20)
                    percent_match = re.search(r'-?(\d+)%', percentage_text)
                    if percent_match:
                        sale_percentage = int(percent_match.group(1))
                        logger.info(f"Extracted sale percentage from corePriceDisplay: {sale_percentage}%")
                except:
                    # No percentage in container = no discount
                    sale_percentage = 0
                    logger.info("No percentage found in corePriceDisplay - no discount")
                    
                    # Also check for "with X percent savings" in aok-offscreen within container
                    try:
                        offscreen_elem = core_pricing_container.find_element(By.CSS_SELECTOR, ".aok-offscreen")
                        offscreen_text = offscreen_elem.text.strip()
                        savings_match = re.search(r'with\s+(\d+)\s+percent\s+savings', offscreen_text, re.IGNORECASE)
                        if savings_match:
                            sale_percentage = int(savings_match.group(1))
                            logger.info(f"Extracted sale percentage from offscreen in corePriceDisplay: {sale_percentage}%")
                    except:
                        pass
                
                # Extract list price from basisPrice within the container ONLY
                try:
                    list_price_selectors = [
                        ".basisPrice .a-price.a-text-price .a-offscreen",              # "$24.95" from basisPrice span  
                        ".basisPrice .a-price.a-text-price span[aria-hidden='true']",  # Visible "$24.95" in basisPrice
                        ".basisPrice .a-size-small.aok-offscreen",                     # "List Price: $24.95" in basisPrice
                        "span.basisPrice .a-offscreen"                                 # Direct basisPrice targeting
                    ]
                    
                    for selector in list_price_selectors:
                        try:
                            list_price_elem = core_pricing_container.find_element(By.CSS_SELECTOR, selector)
                            list_price_text = list_price_elem.text.strip()
                            if list_price_text:
                                logger.info(f"Found list price text in corePriceDisplay: '{list_price_text}'")
                                
                                # Handle "List Price: $24.95" format - extract price after colon
                                if "List Price:" in list_price_text:
                                    price_match = re.search(r'List Price:\s*\$?([\d,]+\.?\d*)', list_price_text)
                                    if price_match:
                                        list_price = float(price_match.group(1).replace(',', ''))
                                    else:
                                        list_price = self._parse_price(list_price_text)
                                else:
                                    list_price = self._parse_price(list_price_text)
                                
                                if list_price:
                                    logger.info(f"Extracted list price from corePriceDisplay: ${list_price}")
                                    break
                        except:
                            continue
                            
                    if not list_price:
                        logger.info("No list price found in corePriceDisplay container - setting to NULL")
                        
                except Exception as e:
                    logger.warning(f"Could not extract list price from container: {e}")
                    list_price = None
            
            # Fallback extraction ONLY if no core container found
            if not core_pricing_container:
                logger.warning("No corePriceDisplay container found - using fallback extraction")
                
                # Fallback sale price
                fallback_price_selectors = [
                    ".a-price-current .a-offscreen",
                    ".a-price.a-text-price.a-size-medium .a-offscreen", 
                    "#priceblock_dealprice",
                    "#price_inside_buybox",
                    "span.a-price.a-text-price.a-size-medium.apexPriceToPay .a-offscreen"
                ]
                
                price_text = self._get_text_by_selectors(fallback_price_selectors)
                if price_text:
                    sale_price = self._parse_price(price_text)
                    logger.info(f"Extracted sale price via fallback: ${sale_price}")
                
                # No percentage and list_price for fallback (not in same container)
                sale_percentage = 0
                list_price = None
                logger.info("Using fallback extraction - no percentage/list_price (not in same container)")
            
            # Set final data
            data['sale_price'] = sale_price
            data['sale_percentage'] = sale_percentage  
            data['list_price'] = list_price
            
            # Log final results
            if sale_percentage > 0:
                logger.info(f"Final pricing from corePriceDisplay: sale=${sale_price}, list=${list_price}, discount={sale_percentage}%")
            else:
                logger.info(f"Final pricing from corePriceDisplay: sale=${sale_price}, list=${list_price}, no discount")
            
        except Exception as e:
            logger.error(f"Error extracting pricing: {e}")
            # Set defaults on error
            data['sale_price'] = None
            data['sale_percentage'] = 0
            data['list_price'] = None
        
        return data
    
    def _extract_ratings(self) -> Dict:
        """Extract rating information"""
        data = {}
        
        try:
            # Rating value - targeting specific structure from HTML  
            rating_selectors = [
                "#acrPopover",                                              # Element with text='4.6' found in debug
                ".reviewCountTextLinkedHistogram",                          # Class found in debug
                "#averageCustomerReviews span.a-size-small.a-color-base",   # "4.6" in averageCustomerReviews context
                "#acrPopover span.a-size-small.a-color-base",              # In acrPopover specifically 
                ".a-popover-trigger span.a-size-small.a-color-base",       # With popover trigger context
                "a.a-popover-trigger span[aria-hidden='true'].a-size-small.a-color-base",  # Full chain
                "#averageCustomerReviews .a-icon-alt",                     # Icon alt text in reviews context
                ".reviewCountTextLinkedHistogram .a-icon-alt",             # Alternative icon location
                "span[aria-hidden='true'].a-size-small.a-color-base",      # General fallback
                "[data-hook='average-star-rating'] .a-icon-alt"
            ]
            rating_text = self._get_text_by_selectors(rating_selectors)
            if rating_text:
                logger.info(f"Found rating text: '{rating_text}'")
                rating_match = re.search(r'(\d+\.?\d*)', rating_text.strip())
                if rating_match:
                    data['rating'] = float(rating_match.group(1))
                    logger.info(f"Extracted rating: {data['rating']}")
                else:
                    # Try to extract from "X out of 5 stars" format
                    stars_match = re.search(r'(\d+\.?\d*)\s*out\s*of\s*5', rating_text.strip(), re.IGNORECASE)
                    if stars_match:
                        data['rating'] = float(stars_match.group(1))
                        logger.info(f"Extracted rating from 'out of 5': {data['rating']}")
            else:
                logger.warning("Could not extract rating - trying manual debug...")
                # Debug: try to find rating related elements
                try:
                    debug_elements = self.driver.find_elements(By.CSS_SELECTOR, "[class*='rating'], [class*='star'], [class*='review'], [id*='review'], [id*='rating']")
                    logger.info(f"Found {len(debug_elements)} rating-related elements for debugging")
                    for i, elem in enumerate(debug_elements[:5]):  # Check first 5
                        try:
                            text = elem.text.strip()
                            classes = elem.get_attribute('class')
                            elem_id = elem.get_attribute('id')
                            if any(word in text.lower() for word in ['star', 'out of', '4.', '3.', '5.']):
                                logger.info(f"Debug rating element {i}: text='{text}', classes='{classes}', id='{elem_id}'")
                        except:
                            pass
                except Exception as debug_e:
                    logger.warning(f"Rating debug failed: {debug_e}")
            
            # Rating count
            rating_count_selectors = [
                "[data-hook='total-review-count']",
                "#acrCustomerReviewText",
                ".a-link-normal .a-size-base"
            ]
            rating_count_text = self._get_text_by_selectors(rating_count_selectors)
            if rating_count_text:
                count_match = re.search(r'([\d,]+)', rating_count_text.replace(',', ''))
                if count_match:
                    data['rating_count'] = int(count_match.group(1).replace(',', ''))
            
        except Exception as e:
            logger.error(f"Error extracting ratings: {e}")
        
        return data
    
    def _extract_images_videos(self) -> Dict:
        """Extract images and videos from product page"""
        data = {
            'image_urls': [],
            'image_count': 0,
            'video_urls': [],
            'video_count': 0
        }
        
        try:
            # Initialize dictionary to store unique images
            unique_images = {}
            
            # Image extraction logic...
            # First try to extract from ivThumbs container (new structure)
            try:
                # Find all ivThumb elements that have an ID (excluding placeholders)
                thumb_elements = self.driver.find_elements(By.CSS_SELECTOR, "#ivThumbs .ivThumb[id^='ivImage_']")
                logger.info(f"Found {len(thumb_elements)} thumbnail elements in ivThumbs")
                
                # Try to scroll through all thumbnails if there's a "Show more" button
                try:
                    show_more = self.driver.find_element(By.CSS_SELECTOR, "#ivShowMore")
                    if show_more and show_more.is_displayed():
                        show_more.click()
                        logger.info("Clicked 'Show more' button for images")
                        time.sleep(2)  # Wait for more images to load
                        # Get updated list of thumbnails
                        thumb_elements = self.driver.find_elements(By.CSS_SELECTOR, "#ivThumbs .ivThumb[id^='ivImage_']")
                        logger.info(f"After showing more, found {len(thumb_elements)} thumbnails")
                except Exception as e:
                    logger.debug(f"No 'Show more' button found or error clicking it: {e}")
                
                for thumb_elem in thumb_elements:
                    try:
                        # Get the background image URL from the inner ivThumbImage div
                        thumb_image = thumb_elem.find_element(By.CSS_SELECTOR, ".ivThumbImage")
                        bg_style = thumb_image.get_attribute("style")
                        
                        # Extract URL from background-image style
                        url_match = re.search(r'url\("([^"]+)"\)', bg_style)
                        if url_match:
                            thumb_url = url_match.group(1)
                            
                            # Convert thumbnail URL to high resolution
                            # From: https://m.media-amazon.com/images/I/41NAxoL57FL._AC_US40_AA50_.jpg
                            # To:   https://m.media-amazon.com/images/I/41NAxoL57FL._AC_SL1500_.jpg
                            high_res_url = thumb_url.replace('_AC_US40_AA50_', '_AC_SL1500_')
                            
                            # Extract image ID to avoid duplicates
                            id_match = re.search(r'/I/([^._]+)', high_res_url)
                            if id_match:
                                image_id = id_match.group(1)
                                unique_images[image_id] = high_res_url
                                logger.info(f"Added image from ivThumbs: {image_id}")
                    except Exception as e:
                        logger.warning(f"Error processing thumbnail: {e}")
                
                # If we found images in ivThumbs, use this count
                if unique_images:
                    data['image_urls'] = list(unique_images.values())
                    data['image_count'] = len(unique_images)
                    logger.info(f"Successfully extracted {data['image_count']} images from ivThumbs")
                    
                    # Video extraction logic - must click video thumbnail first to open popup
                    try:
                        video_urls = []
                        
                        # Step 1: Find and click video thumbnail to open video popup
                        try:
                            # Look for video thumbnail that shows video count (e.g., "8 videos")
                            video_thumbnails = self.driver.find_elements(By.CSS_SELECTOR, "li.videoThumbnail")
                            if not video_thumbnails:
                                # Try alternative selectors for video thumbnail
                                video_thumbnails = self.driver.find_elements(By.CSS_SELECTOR, "li[class*='video'], .video-thumbnail, [id*='video']")
                            
                            video_thumbnail_clicked = False
                            for thumb in video_thumbnails:
                                try:
                                    # Check if this thumbnail has video count info
                                    video_count_elem = thumb.find_elements(By.CSS_SELECTOR, "#videoCount, .video-count, [class*='video'][class*='count']")
                                    if video_count_elem:
                                        count_text = video_count_elem[0].text.strip()
                                        logger.info(f"Found video thumbnail with count: {count_text}")
                                        
                                        # Click the thumbnail to open video popup
                                        thumb.click()
                                        logger.info("Clicked video thumbnail to open popup")
                                        video_thumbnail_clicked = True
                                        
                                        # Wait for video popup/carousel to load
                                        time.sleep(3)
                                        break
                                    else:
                                        # Try clicking any video-related thumbnail
                                        if 'video' in thumb.get_attribute('class').lower():
                                            thumb.click()
                                            logger.info("Clicked video thumbnail (no count found)")
                                            video_thumbnail_clicked = True
                                            time.sleep(3)
                                            break
                                except Exception as e:
                                    logger.debug(f"Could not process video thumbnail: {e}")
                                    continue
                            
                            if not video_thumbnail_clicked:
                                logger.info("No video thumbnail found to click")
                                data['video_urls'] = []
                                data['video_count'] = 0
                                return data
                            
                        except Exception as e:
                            logger.warning(f"Could not find/click video thumbnail: {e}")
                            data['video_urls'] = []
                            data['video_count'] = 0
                            return data
                        
                        # Step 2: Now look for video carousel container (after clicking thumbnail)
                        carousel_containers = self.driver.find_elements(By.CSS_SELECTOR, "div.vse-related-videos-container")
                        if not carousel_containers:
                            # Try alternative selectors for video carousel
                            carousel_containers = self.driver.find_elements(By.CSS_SELECTOR, "div[class*='video'][class*='container'], .video-carousel, [id*='video'][id*='carousel']")
                        
                        logger.info(f"Found {len(carousel_containers)} video carousel containers after clicking thumbnail")
                        
                        for carousel in carousel_containers:
                            try:
                                # Find "Videos for this product" section specifically
                                product_video_section = None
                                section_headers = carousel.find_elements(By.CSS_SELECTOR, "h4[data-element-id='segment-title-1']")
                                
                                for header in section_headers:
                                    if "Videos for this product" in header.text:
                                        product_video_section = header
                                        logger.info("Found 'Videos for this product' section")
                                        break
                                
                                if not product_video_section:
                                    # Try alternative selectors for the section
                                    alt_headers = carousel.find_elements(By.CSS_SELECTOR, "li.segment-title-IB_G1 h4")
                                    for header in alt_headers:
                                        if "Videos for this product" in header.text:
                                            product_video_section = header
                                            logger.info("Found 'Videos for this product' section (alternative selector)")
                                            break
                                
                                if product_video_section:
                                    # Extract videos from "Videos for this product" section
                                    # Look for video cards that come after the "Videos for this product" header
                                    video_cards = carousel.find_elements(By.CSS_SELECTOR, "li.vse-video-card .vse-video-item")
                                    
                                    for video_card in video_cards:
                                        try:
                                            # Check if this video belongs to "Videos for this product" section
                                            # by looking for the redirect URL in the anchor tag
                                            video_link = video_card.find_element(By.CSS_SELECTOR, "a[data-redirect-url]")
                                            redirect_url = video_link.get_attribute("data-redirect-url")
                                            
                                            if redirect_url and redirect_url.startswith("/vdp/"):
                                                # Convert relative URL to full Amazon URL
                                                full_video_url = f"https://amazon.com{redirect_url}"
                                                
                                                # Extract video metadata
                                                title = video_card.get_attribute("data-title") or ""
                                                duration = video_card.get_attribute("data-duration") or ""
                                                vendor = video_card.get_attribute("data-vendor-name") or ""
                                                video_id = video_card.get_attribute("data-asin") or ""
                                                
                                                # Also try to get title from the title element if not in data attribute
                                                if not title:
                                                    try:
                                                        title_elem = video_card.find_element(By.CSS_SELECTOR, ".vse-video-title-text")
                                                        title = title_elem.text.strip()
                                                    except:
                                                        pass
                                                
                                                # Get duration from duration element if not in data attribute
                                                if not duration:
                                                    try:
                                                        duration_elem = video_card.find_element(By.CSS_SELECTOR, ".vse-video-duration")
                                                        duration = duration_elem.text.strip()
                                                    except:
                                                        pass
                                                
                                                # Get vendor from vendor element if not in data attribute
                                                if not vendor:
                                                    try:
                                                        vendor_elem = video_card.find_element(By.CSS_SELECTOR, ".vse-video-vendorname")
                                                        vendor = vendor_elem.text.strip()
                                                    except:
                                                        pass
                                                
                                                video_data = {
                                                    'url': full_video_url,
                                                    'redirect_path': redirect_url,
                                                    'title': title,
                                                    'duration': duration,
                                                    'vendor': vendor,
                                                    'video_id': video_id,
                                                    'type': 'product'
                                                }
                                                
                                                video_urls.append(video_data)
                                                logger.info(f"Found product video: '{title}' - {full_video_url}")
                                                
                                        except Exception as e:
                                            logger.warning(f"Error extracting video details: {e}")
                                            continue
                                    
                                    logger.info(f"Extracted {len(video_urls)} videos from 'Videos for this product' section")
                                else:
                                    logger.info("Could not find 'Videos for this product' section")
                                    
                            except Exception as e:
                                logger.warning(f"Error processing video carousel: {e}")
                                continue
                        
                        # Set final video data
                        if video_urls:
                            data['video_urls'] = video_urls
                            data['video_count'] = len(video_urls)
                            logger.info(f"Total product videos found: {data['video_count']}")
                            
                            # Log video details for verification
                            for i, video in enumerate(video_urls, 1):
                                logger.info(f"Video {i}: {video['title']} ({video['duration']}) - {video['url']}")
                        else:
                            data['video_urls'] = []
                            data['video_count'] = 0
                            logger.info("No product videos found")
                            
                    except Exception as e:
                        logger.warning(f"Error extracting videos: {e}")
                        data['video_urls'] = []
                        data['video_count'] = 0
                    
                    return data
                    
            except Exception as e:
                logger.warning(f"Could not extract from ivThumbs container: {e}")
            
            # If ivThumbs extraction failed, fall back to original imageBlock extraction
            logger.info("Falling back to imageBlock extraction...")
            
            # Find the imageBlock container
            imageblock_container = None
            try:
                imageblock_container = self.driver.find_element(By.CSS_SELECTOR, "#imageBlock")
                logger.info("Found #imageBlock container - extracting media from this container")
                
                # Wait a bit for all images to load completely
                time.sleep(2)
                
            except:
                logger.warning("Could not find #imageBlock container")
                # Set defaults and return early
                data['image_urls'] = []
                data['image_count'] = 0
                data['video_urls'] = []
                data['video_count'] = 0
                return data
            
            # Extract images from imageBlock container ONLY - count unique images
            unique_images = {}  # Use dict to track unique images by their base ID
            
            try:
                # Extract unique image thumbnails from #altImages - including hidden images
                visible_thumbnails = []
                hidden_count = 0
                
                # First find all thumbnail elements
                thumbnail_elements = imageblock_container.find_elements(By.CSS_SELECTOR, "#altImages li.item.imageThumbnail")
                logger.info(f"Found {len(thumbnail_elements)} thumbnail elements")
                
                for thumb_elem in thumbnail_elements:
                    try:
                        # Skip video thumbnails
                        if 'videoThumbnail' in thumb_elem.get_attribute('class'):
                            continue
                            
                        # Get the image element
                        img = thumb_elem.find_element(By.CSS_SELECTOR, "img")
                        src = img.get_attribute('src')
                        
                        if src and 'media-amazon.com' in src:
                            # Check for "4+" or similar text indicating hidden images
                            more_text = thumb_elem.find_elements(By.CSS_SELECTOR, ".textMoreImages")
                            if more_text:
                                text = more_text[0].text.strip()
                                if text and text.endswith('+'):
                                    try:
                                        # Extract number before "+" (e.g., "4+" -> 4)
                                        hidden_count = int(text.rstrip('+'))
                                        logger.info(f"Found {hidden_count} additional hidden images")
                                    except:
                                        pass
                            
                            # Add visible thumbnail
                            visible_thumbnails.append(img)
                            
                            # Extract and convert to high res
                            id_match = re.search(r'/I/([^._]+)', src)
                            if id_match:
                                image_id = id_match.group(1)
                                # Convert to highest resolution version
                                if '_AC_US40_' in src:
                                    high_res_src = src.replace('_AC_US40_', '_AC_SL1500_')
                                else:
                                    high_res_src = src
                                unique_images[image_id] = high_res_src
                                logger.info(f"Added visible thumbnail: {image_id}")
                                
                    except Exception as e:
                        logger.warning(f"Error processing thumbnail: {e}")
                
                # Calculate total images (visible + hidden)
                total_images = len(visible_thumbnails) + hidden_count
                logger.info(f"Total images: {total_images} ({len(visible_thumbnails)} visible + {hidden_count} hidden)")
                
                # Store total image count for later
                data['image_count'] = total_images
                
                # Extract unique main images from the right panel - comprehensive search
                logger.info("Searching for main images in right panel...")
                
                # Find all images in the main display area - search for all itemNo variations
                main_images_found = []
                
                # Search for all possible itemNo images (itemNo0, itemNo1, itemNo2, etc.)
                for item_num in range(10):  # Check itemNo0 through itemNo9
                    try:
                        item_selector = f"li.itemNo{item_num} img, li[class*='itemNo{item_num}'] img"
                        item_images = imageblock_container.find_elements(By.CSS_SELECTOR, item_selector)
                        if item_images:
                            logger.info(f"Found {len(item_images)} images for itemNo{item_num}")
                            for img in item_images:
                                src = img.get_attribute('src')
                                old_hires = img.get_attribute('data-old-hires')
                                if (src or old_hires) and img not in main_images_found:
                                    main_images_found.append(img)
                    except:
                        pass
                
                # Also search general selectors as fallback
                general_selectors = [
                    "ul.maintain-height li.image.item img",      # Standard item images
                    "#landingImage",                              # Landing image
                    ".imgTagWrapper img"                          # Images in wrapper
                ]
                
                for selector in general_selectors:
                    try:
                        found_images = imageblock_container.find_elements(By.CSS_SELECTOR, selector)
                        for img in found_images:
                            src = img.get_attribute('src')
                            old_hires = img.get_attribute('data-old-hires')
                            if (src or old_hires) and img not in main_images_found:
                                main_images_found.append(img)
                        if found_images:
                            logger.info(f"General selector '{selector}' found {len(found_images)} additional images")
                    except Exception as e:
                        logger.debug(f"General selector '{selector}' failed: {e}")
                
                logger.info(f"Total unique main images found: {len(main_images_found)}")
                
                # Process each main image
                for i, img in enumerate(main_images_found):
                    try:
                        # Get highest resolution available
                        old_hires = img.get_attribute('data-old-hires')
                        src = img.get_attribute('src')
                        
                        best_url = old_hires if old_hires and 'media-amazon.com' in old_hires else src
                        if best_url and 'media-amazon.com' in best_url:
                            # Extract base image ID to avoid duplicates
                            id_match = re.search(r'/I/([^._]+)', best_url)
                            if id_match:
                                image_id = id_match.group(1)
                                # Only add if not already exists or if this is higher resolution
                                if image_id not in unique_images or '_SL1500_' in best_url or '_SL1080_' in best_url:
                                    unique_images[image_id] = best_url
                                    logger.info(f"Added main image {i+1}: {image_id}")
                                else:
                                    logger.debug(f"Skipped duplicate main image: {image_id}")
                    except Exception as e:
                        logger.warning(f"Error processing main image {i+1}: {e}")
                
            except Exception as e:
                logger.warning(f"Could not extract images from #imageBlock: {e}")
            
            # Convert to final list
            image_urls = list(unique_images.values())
            data['image_urls'] = image_urls
            data['image_count'] = len(image_urls)
            logger.info(f"Extracted {data['image_count']} unique image URLs from #imageBlock")
            
            # Video extraction logic (fallback) - must click video thumbnail first to open popup
            try:
                video_urls = []
                
                # Step 1: Find and click video thumbnail to open video popup (fallback)
                try:
                    # Look for video thumbnail that shows video count (e.g., "8 videos")
                    video_thumbnails = self.driver.find_elements(By.CSS_SELECTOR, "li.videoThumbnail")
                    if not video_thumbnails:
                        # Try alternative selectors for video thumbnail
                        video_thumbnails = self.driver.find_elements(By.CSS_SELECTOR, "li[class*='video'], .video-thumbnail, [id*='video']")
                    
                    video_thumbnail_clicked = False
                    for thumb in video_thumbnails:
                        try:
                            # Check if this thumbnail has video count info
                            video_count_elem = thumb.find_elements(By.CSS_SELECTOR, "#videoCount, .video-count, [class*='video'][class*='count']")
                            if video_count_elem:
                                count_text = video_count_elem[0].text.strip()
                                logger.info(f"Found video thumbnail with count (fallback): {count_text}")
                                
                                # Click the thumbnail to open video popup
                                thumb.click()
                                logger.info("Clicked video thumbnail to open popup (fallback)")
                                video_thumbnail_clicked = True
                                
                                # Wait for video popup/carousel to load
                                time.sleep(3)
                                break
                            else:
                                # Try clicking any video-related thumbnail
                                if 'video' in thumb.get_attribute('class').lower():
                                    thumb.click()
                                    logger.info("Clicked video thumbnail (fallback - no count found)")
                                    video_thumbnail_clicked = True
                                    time.sleep(3)
                                    break
                        except Exception as e:
                            logger.debug(f"Could not process video thumbnail (fallback): {e}")
                            continue
                    
                    if not video_thumbnail_clicked:
                        logger.info("No video thumbnail found to click (fallback)")
                        data['video_urls'] = []
                        data['video_count'] = 0
                        return data
                    
                except Exception as e:
                    logger.warning(f"Could not find/click video thumbnail (fallback): {e}")
                    data['video_urls'] = []
                    data['video_count'] = 0
                    return data
                
                # Step 2: Now look for video carousel container (after clicking thumbnail)
                carousel_containers = self.driver.find_elements(By.CSS_SELECTOR, "div.vse-related-videos-container")
                if not carousel_containers:
                    # Try alternative selectors for video carousel
                    carousel_containers = self.driver.find_elements(By.CSS_SELECTOR, "div[class*='video'][class*='container'], .video-carousel, [id*='video'][id*='carousel']")
                
                logger.info(f"Found {len(carousel_containers)} video carousel containers (fallback) after clicking thumbnail")
                
                for carousel in carousel_containers:
                    try:
                        # Find "Videos for this product" section specifically
                        product_video_section = None
                        section_headers = carousel.find_elements(By.CSS_SELECTOR, "h4[data-element-id='segment-title-1']")
                        
                        for header in section_headers:
                            if "Videos for this product" in header.text:
                                product_video_section = header
                                logger.info("Found 'Videos for this product' section (fallback)")
                                break
                        
                        if not product_video_section:
                            # Try alternative selectors for the section
                            alt_headers = carousel.find_elements(By.CSS_SELECTOR, "li.segment-title-IB_G1 h4")
                            for header in alt_headers:
                                if "Videos for this product" in header.text:
                                    product_video_section = header
                                    logger.info("Found 'Videos for this product' section (fallback - alternative)")
                                    break
                        
                        if product_video_section:
                            # Extract videos from "Videos for this product" section
                            video_cards = carousel.find_elements(By.CSS_SELECTOR, "li.vse-video-card .vse-video-item")
                            
                            for video_card in video_cards:
                                try:
                                    # Get redirect URL from anchor tag
                                    video_link = video_card.find_element(By.CSS_SELECTOR, "a[data-redirect-url]")
                                    redirect_url = video_link.get_attribute("data-redirect-url")
                                    
                                    if redirect_url and redirect_url.startswith("/vdp/"):
                                        # Convert relative URL to full Amazon URL
                                        full_video_url = f"https://amazon.com{redirect_url}"
                                        
                                        # Extract video metadata
                                        title = video_card.get_attribute("data-title") or ""
                                        duration = video_card.get_attribute("data-duration") or ""
                                        vendor = video_card.get_attribute("data-vendor-name") or ""
                                        video_id = video_card.get_attribute("data-asin") or ""
                                        
                                        # Fallback to element text if data attributes are empty
                                        if not title:
                                            try:
                                                title_elem = video_card.find_element(By.CSS_SELECTOR, ".vse-video-title-text")
                                                title = title_elem.text.strip()
                                            except:
                                                pass
                                        
                                        if not duration:
                                            try:
                                                duration_elem = video_card.find_element(By.CSS_SELECTOR, ".vse-video-duration")
                                                duration = duration_elem.text.strip()
                                            except:
                                                pass
                                        
                                        if not vendor:
                                            try:
                                                vendor_elem = video_card.find_element(By.CSS_SELECTOR, ".vse-video-vendorname")
                                                vendor = vendor_elem.text.strip()
                                            except:
                                                pass
                                        
                                        video_data = {
                                            'url': full_video_url,
                                            'redirect_path': redirect_url,
                                            'title': title,
                                            'duration': duration,
                                            'vendor': vendor,
                                            'video_id': video_id,
                                            'type': 'product'
                                        }
                                        
                                        video_urls.append(video_data)
                                        logger.info(f"Found product video (fallback): '{title}' - {full_video_url}")
                                        
                                except Exception as e:
                                    logger.warning(f"Error extracting video details (fallback): {e}")
                                    continue
                            
                            logger.info(f"Extracted {len(video_urls)} videos from 'Videos for this product' section (fallback)")
                        else:
                            logger.info("Could not find 'Videos for this product' section (fallback)")
                            
                    except Exception as e:
                        logger.warning(f"Error processing video carousel (fallback): {e}")
                        continue
                
                # Set final video data
                if video_urls:
                    data['video_urls'] = video_urls
                    data['video_count'] = len(video_urls)
                    logger.info(f"Total product videos found (fallback): {data['video_count']}")
                    
                    # Log video details for verification
                    for i, video in enumerate(video_urls, 1):
                        logger.info(f"Video {i} (fallback): {video['title']} ({video['duration']}) - {video['url']}")
                else:
                    data['video_urls'] = []
                    data['video_count'] = 0
                    logger.info("No product videos found (fallback)")
                
            except Exception as e:
                logger.warning(f"Error extracting videos: {e}")
            
            # Extract lightning deal progress
            try:
                deal_progress = self.driver.find_element(By.ID, "dealProgress_feature_div")
                if deal_progress:
                    percent_message = deal_progress.find_element(By.ID, "dealsx_percent_message")
                    if percent_message:
                        claimed_text = percent_message.text.strip()
                        if "claimed" in claimed_text.lower():
                            data['lightning_deal'] = claimed_text
                            logger.info(f"Found lightning deal: {claimed_text}")
            except Exception as e:
                logger.debug(f"No lightning deal found: {e}")
            
            # Extract bag sale info
            try:
                bag_sale_elem = self.driver.find_element(By.ID, "social-proofing-faceout-title-tk_bought")
                if bag_sale_elem:
                    data['bag_sale'] = bag_sale_elem.text.strip()
                    logger.info(f"Found bag sale info: {data['bag_sale']}")
            except Exception as e:
                logger.debug(f"No bag sale info found: {e}")
                
            # Extract best deal
            try:
                deal_badge = self.driver.find_element(By.CSS_SELECTOR, "#dealBadge_feature_div .a-badge-text")
                if deal_badge:
                    data['best_deal'] = deal_badge.text.strip()
                    logger.info(f"Found best deal: {data['best_deal']}")
            except Exception as e:
                logger.debug(f"No best deal found: {e}")
                
        except Exception as e:
            logger.error(f"Error in _extract_images_videos: {e}")
        
        return data
    
    def _extract_promotions(self) -> Dict:
        """Extract promotion information"""
        data = {
            'best_deal': '',
            'lightning_deal': '',
            'coupon': '',
            'bag_sale': ''
        }
        
        try:
            # Extract best deal (Limited time deal, etc)
            try:
                deal_badge = self.driver.find_element(By.CSS_SELECTOR, "#dealBadgeSupportingText span")
                if deal_badge:
                    data['best_deal'] = deal_badge.text.strip()
                    logger.info(f"Extracted best deal: {data['best_deal']}")
            except Exception as e:
                logger.debug(f"No best deal badge found: {e}")
            
            # Extract lightning deal progress
            try:
                # Try to find the percentage message directly
                percent_message = self.driver.find_element(By.CSS_SELECTOR, "#dealsx_percent_message")
                if percent_message:
                    claimed_text = percent_message.text.strip()
                    if "claimed" in claimed_text.lower():
                        data['lightning_deal'] = claimed_text
                        logger.info(f"Found lightning deal: {claimed_text}")
                        
            except Exception as e:
                # Try alternative selector if first attempt fails
                try:
                    percent_message = self.driver.find_element(By.CSS_SELECTOR, ".new-percentage-message span")
                    if percent_message:
                        claimed_text = percent_message.text.strip()
                        if "claimed" in claimed_text.lower():
                            data['lightning_deal'] = claimed_text
                            logger.info(f"Found lightning deal (alternative): {claimed_text}")
                except Exception as e2:
                    logger.debug(f"No lightning deal found: {e2}")
                
            # Extract coupon information
            try:
                coupon_elem = self.driver.find_element(By.CSS_SELECTOR, "#couponBadgeRegularVpc")
                if coupon_elem:
                    data['coupon'] = coupon_elem.text.strip()
                    logger.info(f"Extracted coupon: {data['coupon']}")
            except Exception as e:
                logger.debug(f"No coupon found: {e}")
            
            # Extract bag sale information
            try:
                bag_sale_elem = self.driver.find_element(By.CSS_SELECTOR, "#social-proofing-faceout-title-tk_bought")
                if bag_sale_elem:
                    data['bag_sale'] = bag_sale_elem.text.strip()
                    logger.info(f"Extracted bag_sale: {data['bag_sale']}")
            except Exception as e:
                # Try alternative selector
                try:
                    bag_sale_elem = self.driver.find_element(By.CSS_SELECTOR, ".social-proofing-faceout-title-text")
                    if bag_sale_elem:
                        data['bag_sale'] = bag_sale_elem.text.strip()
                        logger.info(f"Extracted bag_sale (alternative): {data['bag_sale']}")
                except Exception as e2:
                    logger.debug(f"No bag sale info found: {e2}")
            
        except Exception as e:
            logger.error(f"Error extracting promotion info: {e}")
        
        return data
    
    def _extract_inventory(self) -> Dict:
        """Extract inventory information"""
        data = {}
        
        try:
            inventory_selectors = [
                "#availability span",
                ".availability",
                "[data-feature-name='availability']"
            ]
            inventory_text = self._get_text_by_selectors(inventory_selectors)
            if inventory_text:
                data['inventory'] = inventory_text.strip()
            else:
                data['inventory'] = "Unknown"
            
        except Exception as e:
            logger.error(f"Error extracting inventory: {e}")
        
        return data
    
    def _extract_seller_info(self) -> Dict:
        """Extract seller and brand information"""
        data = {}
        
        try:
            # Brand store link
            brand_selectors = [
                "#bylineInfo",
                ".author",
                "[data-feature-name='brand']"
            ]
            brand_element = self._get_element_by_selectors(brand_selectors)
            if brand_element:
                brand_link = brand_element.get_attribute('href')
                if brand_link:
                    data['brand_store_link'] = brand_link
            
            # Sold by link - using exact CSS selector from HTML
            sold_by_selectors = [
                "#sellerProfileTriggerId",                    # Exact ID from HTML
                ".offer-display-feature-text-message",       # Class from HTML
                "#merchant-info",
                ".tabular-buybox-text .a-link-normal",
                "[data-feature-name='merchant-info']"
            ]
            sold_by_element = self._get_element_by_selectors(sold_by_selectors)
            if sold_by_element:
                sold_by_link = sold_by_element.get_attribute('href')
                if sold_by_link and sold_by_link.startswith('/'):
                    # Convert relative link to absolute
                    data['sold_by_link'] = f"https://www.amazon.com{sold_by_link}"
                elif sold_by_link:
                    data['sold_by_link'] = sold_by_link
                else:
                    # If no link, use seller name as fallback
                    seller_name = sold_by_element.text.strip()
                    data['sold_by_link'] = seller_name if seller_name else ""
                logger.info(f"Extracted sold_by_link: {data.get('sold_by_link', '')}")
            else:
                data['sold_by_link'] = ""
            
        except Exception as e:
            logger.error(f"Error extracting seller info: {e}")
        
        return data
    
    def _extract_technical_info(self) -> Dict:
        """Extract technical specifications and EBC content"""
        data = {}
        
        try:
            # Product information (technical details) - using exact table structure
            product_info = {}
            
            try:
                # Look for the product overview table first 
                table_rows = self.driver.find_elements(By.CSS_SELECTOR, "table.a-normal.a-spacing-micro tr")
                for row in table_rows:
                    try:
                        # Find the key and value cells
                        key_cell = row.find_element(By.CSS_SELECTOR, "td.a-span3 span.a-text-bold")
                        value_cell = row.find_element(By.CSS_SELECTOR, "td.a-span9 span.po-break-word")
                        
                        key = key_cell.text.strip()
                        value = value_cell.text.strip()
                        
                        if key and value:
                            product_info[key] = value
                            
                    except:
                        continue
                        
                if product_info:
                    logger.info(f"Extracted {len(product_info)} technical specifications")
                
            except Exception as e:
                logger.warning(f"Could not extract from product overview table: {e}")
                
                # Fallback to other technical details tables
                tech_table_selectors = [
                    "#productDetails_techSpec_section_1 tr",
                    "#technical-details tr",
                    ".pdTab tr"
                ]
                
                for selector in tech_table_selectors:
                    try:
                        rows = self.driver.find_elements(By.CSS_SELECTOR, selector)
                        for row in rows:
                            cells = row.find_elements(By.TAG_NAME, "td")
                            if len(cells) >= 2:
                                key = cells[0].text.strip()
                                value = cells[1].text.strip()
                                if key and value:
                                    product_info[key] = value
                    except:
                        continue
            
            data['product_information'] = product_info
            
            # Product description from productDescription div - using exact CSS selector from HTML
            try:
                desc_element = self.driver.find_element(By.CSS_SELECTOR, "#productDescription")
                if desc_element:
                    # Extract text from all p tags within productDescription
                    desc_paragraphs = desc_element.find_elements(By.TAG_NAME, "p")
                    desc_texts = []
                    for p in desc_paragraphs:
                        text = p.text.strip()
                        if text and len(text) > 5:  # Filter out empty paragraphs
                            desc_texts.append(text)
                    
                    data['product_description'] = "\n".join(desc_texts) if desc_texts else ""
                    logger.info(f"Extracted product_description: {len(data['product_description'])} characters")
                else:
                    data['product_description'] = ""
            except Exception as e:
                logger.warning(f"Could not extract product_description: {e}")
                # Fallback to other description selectors
                desc_selectors = [
                    "#aplus",                    # EBC A+ content
                    ".aplus-v2",                # EBC A+ content v2
                    "#productDetails_techSpec_section_1",  # Technical description
                    ".a-section.product-description",      # Alternative description
                    "[data-feature-name='aplus']",         # Feature description
                    "#feature-bullets .a-expander-content", # Extended bullet content
                ]
                
                for selector in desc_selectors:
                    try:
                        desc_element = self.driver.find_element(By.CSS_SELECTOR, selector)
                        if desc_element:
                            desc_text = desc_element.text.strip()
                            if len(desc_text) > 20:  # Only use if meaningful content
                                data['product_description'] = desc_text
                                logger.info(f"Extracted product_description from {selector}: {len(desc_text)} characters")
                                break
                    except:
                        continue
                
                # If still empty, set empty string
                if 'product_description' not in data:
                    data['product_description'] = ""
            
        except Exception as e:
            logger.error(f"Error extracting technical info: {e}")
        
        return data
    
    def _extract_advertisements(self) -> Dict:
        """Extract advertised ASINs"""
        data = {}
        
        try:
            advertised_asins = set()
            
            # Look for sponsored products
            ad_selectors = [
                "[data-asin]",
                ".s-asin",
                "[data-component-type='s-search-result']"
            ]
            
            for selector in ad_selectors:
                try:
                    elements = self.driver.find_elements(By.CSS_SELECTOR, selector)
                    for element in elements:
                        asin = element.get_attribute('data-asin')
                        if asin and len(asin) == 10:
                            advertised_asins.add(asin)
                except:
                    continue
            
            data['advertised_asins'] = list(advertised_asins)
            
        except Exception as e:
            logger.error(f"Error extracting advertisements: {e}")
        
        return data
    
    def _get_element_by_selectors(self, selectors: List[str]):
        """Try multiple selectors to find an element"""
        for selector in selectors:
            try:
                element = self.driver.find_element(By.CSS_SELECTOR, selector)
                if element:
                    return element
            except NoSuchElementException:
                continue
        return None
    
    def _get_elements_by_selectors(self, selectors: List[str]):
        """Try multiple selectors to find elements"""
        for selector in selectors:
            try:
                elements = self.driver.find_elements(By.CSS_SELECTOR, selector)
                if elements:
                    return elements
            except NoSuchElementException:
                continue
        return []
    
    def _get_text_by_selectors(self, selectors: List[str]) -> Optional[str]:
        """Try multiple selectors to get text"""
        for selector in selectors:
            try:
                elements = self.driver.find_elements(By.CSS_SELECTOR, selector)
                for element in elements:
                    text = element.text.strip()
                    if text:  # Return first non-empty text
                        return text
            except NoSuchElementException:
                continue
        return None
    
    def _parse_price(self, price_text: str) -> Optional[float]:
        """Parse price from text"""
        if not price_text:
            return None
        
        # Remove currency symbols and extract number
        price_match = re.search(r'([\d,]+\.?\d*)', price_text.replace(',', ''))
        if price_match:
            try:
                return float(price_match.group(1).replace(',', ''))
            except ValueError:
                return None
        return None
    
    def save_to_database(self, product_data: Dict):
        """Save crawled data to database with proper field mapping"""
        try:
            asin = product_data['asin']
            
            # Get or create product
            product = self.session.query(Product).filter_by(asin=asin).first()
            if not product:
                product = Product(asin=asin)
                self.session.add(product)
                self.session.commit()
                logger.info(f"Created new product record for ASIN: {asin}")
            
            # Remove asin and meta fields to avoid conflicts
            save_data = {k: v for k, v in product_data.items() 
                        if k not in ['asin'] and v is not None}
            
            # Create crawl history record - no mapping needed, field names match exactly
            crawl_record = ProductCrawlHistory(
                product_id=product.id,
                asin=asin,
                **save_data
            )
            
            self.session.add(crawl_record)
            self.session.commit()
            logger.info(f"Saved crawl data for ASIN: {asin} with {len(save_data)} fields")
            
        except Exception as e:
            logger.error(f"Error saving to database: {e}")
            self.session.rollback()
    
    def close(self):
        """Close browser and database session"""
        if self.driver:
            self.driver.quit()
        if self.session:
            self.session.close()

# Utility function for single product crawl
def crawl_single_product(asin: str) -> Dict:
    """Crawl a single product by ASIN"""
    crawler = AmazonCrawler()
    try:
        product_data = crawler.crawl_product(asin)
        crawler.save_to_database(product_data)
        return product_data
    finally:
        crawler.close()

if __name__ == "__main__":
    # Test crawl
    test_asin = "B019OZBSJ8"  # Hipa SRM 210 Carburetor
    result = crawl_single_product(test_asin)
    print(json.dumps(result, indent=2, default=str)) 