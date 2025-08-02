import asyncio
from typing import Dict, List, Optional, Any
from datetime import datetime, timedelta
from sqlalchemy.orm import Session

from database.connection import get_db_session
from database.models import Product, ProductCrawlHistory
from notifications.notification_service import send_notification
from utils.logger import get_logger

logger = get_logger(__name__)

class ChangeDetector:
    def __init__(self):
        self.session = get_db_session()
        # Đúng 22 trường như model ProductCrawlHistory
        self.monitored_fields = {
            'title': {'type': 'string'},
            'product_description': {'type': 'string'},
            'product_description_images': {'type': 'json'},
            'product_information': {'type': 'json'},
            'about_this_item': {'type': 'json'},
            'image_count': {'type': 'int', 'threshold': 1},
            'image_urls': {'type': 'json'},
            'video_count': {'type': 'int', 'threshold': 1},
            'video_urls': {'type': 'json'},
            'sale_price': {'type': 'float', 'threshold': 0.01},
            'list_price': {'type': 'float', 'threshold': 0.01},
            'sale_percentage': {'type': 'float', 'threshold': 0.1},
            'best_deal': {'type': 'string'},
            'lightning_deal': {'type': 'string'},
            'coupon': {'type': 'string'},
            'bag_sale': {'type': 'string'},
            'rating': {'type': 'float', 'threshold': 0.1},
            'rating_count': {'type': 'int', 'threshold': 1},
            'brand_store_link': {'type': 'string'},
            'sold_by_link': {'type': 'string'},
            'advertised_asins': {'type': 'json'},
            'amazon_choice': {'type': 'int'},
            'inventory': {'type': 'string'},
        }
    
    async def detect_and_notify_changes(self, asin: str, new_data: Dict) -> Dict:
        """Detect changes and send notifications if any significant changes found"""
        try:
            # Get the latest previous crawl data (yesterday only)
            previous_data = self._get_yesterday_crawl_data(asin)
            if not previous_data:
                logger.info(f"No yesterday data found for ASIN {asin}, this is the first crawl today or no crawl yesterday")
                return {'is_first_crawl': True, 'changes': {}}
            # Detect changes
            changes = self._compare_data(previous_data, new_data)
            # Filter significant changes
            significant_changes = self._filter_significant_changes(changes)
            if significant_changes:
                logger.info(f"Detected {len(significant_changes)} significant changes for ASIN {asin}")
                # Send notifications
                await send_notification(asin, significant_changes, new_data)
                # Log the changes
                self._log_changes(asin, significant_changes)
                return {
                    'is_first_crawl': False,
                    'has_changes': True,
                    'changes': significant_changes,
                    'change_count': len(significant_changes)
                }
            else:
                logger.info(f"No significant changes detected for ASIN {asin}")
                return {
                    'is_first_crawl': False,
                    'has_changes': False,
                    'changes': {},
                    'change_count': 0
                }
        except Exception as e:
            logger.error(f"Error detecting changes for ASIN {asin}: {e}")
            return {'error': str(e)}
    
    def _get_latest_crawl_data(self, asin: str) -> Optional[Dict]:
        """Get the latest successful crawl data for comparison"""
        try:
            latest_crawl = (
                self.session.query(ProductCrawlHistory)
                .filter_by(asin=asin, crawl_success=True)
                .order_by(ProductCrawlHistory.crawl_date.desc())
                .first()
            )
            
            if not latest_crawl:
                return None
            
            # Convert to dictionary for comparison
            data = {}
            for field in self.monitored_fields.keys():
                data[field] = getattr(latest_crawl, field, None)
            
            return data
            
        except Exception as e:
            logger.error(f"Error getting latest crawl data for {asin}: {e}")
            return None
    
    def _get_yesterday_crawl_data(self, asin: str) -> Optional[Dict]:
        """Get the latest successful crawl data for yesterday"""
        try:
            from datetime import time
            today = datetime.utcnow().date()
            yesterday = today - timedelta(days=1)
            start_yesterday = datetime.combine(yesterday, time.min)
            end_yesterday = datetime.combine(yesterday, time.max)
            latest_crawl = (
                self.session.query(ProductCrawlHistory)
                .filter_by(asin=asin, crawl_success=True)
                .filter(ProductCrawlHistory.crawl_date >= start_yesterday)
                .filter(ProductCrawlHistory.crawl_date <= end_yesterday)
                .order_by(ProductCrawlHistory.crawl_date.desc())
                .first()
            )
            if not latest_crawl:
                return None
            data = {field: getattr(latest_crawl, field, None) for field in self.monitored_fields.keys()}
            return data
        except Exception as e:
            logger.error(f"Error getting yesterday crawl data for {asin}: {e}")
            return None
    
    def _get_field_value_for_compare(self, value, field):
        if field in ["amazon_choice", "image_count", "video_count", "rating_count"]:
            try:
                return int(value) if value is not None else None
            except Exception:
                return value
        if field in ["sale_price", "list_price", "sale_percentage", "rating"]:
            try:
                return float(value) if value is not None else None
            except Exception:
                return value
        if field in ["advertised_asins", "image_urls", "video_urls"]:
            # Chuẩn hóa list: sort, ép về str
            if isinstance(value, list):
                return sorted([str(x) for x in value])
            if value is None:
                return []
            try:
                import json
                v = json.loads(value)
                if isinstance(v, list):
                    return sorted([str(x) for x in v])
            except Exception:
                pass
            return [str(value)]
        if field in ["product_information", "about_this_item"]:
            # Xử lý đặc biệt cho product_information và about_this_item
            if value is None:
                return {}
            if isinstance(value, dict):
                # Nếu dict rỗng hoặc chỉ có key rỗng, coi như None
                if not value or (len(value) == 1 and 'full_details' in value and not value['full_details']):
                    return {}
                return value
            try:
                import json
                v = json.loads(value) if isinstance(value, str) else value
                if isinstance(v, dict):
                    if not v or (len(v) == 1 and 'full_details' in v and not v['full_details']):
                        return {}
                    return v
            except Exception:
                pass
            return {}
        return value

    def _equal_value(self, a, b):
        # So sánh số học cho int/float/str
        try:
            if a is None and b is None:
                return True
            if a is None or b is None:
                return False
            
            # Xử lý đặc biệt cho dict rỗng
            if isinstance(a, dict) and isinstance(b, dict):
                # Nếu cả hai đều rỗng hoặc chỉ có key rỗng, coi như bằng nhau
                a_empty = not a or (len(a) == 1 and 'full_details' in a and not a['full_details'])
                b_empty = not b or (len(b) == 1 and 'full_details' in b and not b['full_details'])
                if a_empty and b_empty:
                    return True
                return a == b
            
            # Nếu là số, so sánh số học
            if isinstance(a, (int, float, str)) and isinstance(b, (int, float, str)):
                try:
                    return float(a) == float(b)
                except Exception:
                    return str(a) == str(b)
            # Nếu là list, so sánh từng phần tử đã sort
            if isinstance(a, list) and isinstance(b, list):
                return sorted([str(x) for x in a]) == sorted([str(x) for x in b])
            # Mặc định
            return a == b
        except Exception:
            return a == b

    def _compare_data(self, old_data: Dict, new_data: Dict) -> Dict:
        """Compare old and new data to detect changes"""
        changes = {}
        for field, config in self.monitored_fields.items():
            old_value = self._get_field_value_for_compare(old_data.get(field), field)
            new_value = self._get_field_value_for_compare(new_data.get(field), field)
            
            # Skip if both values are None
            if old_value is None and new_value is None:
                continue
                
            # Skip if both values are empty dicts (for product_information, about_this_item)
            if field in ["product_information", "about_this_item"]:
                if isinstance(old_value, dict) and isinstance(new_value, dict):
                    old_empty = not old_value or (len(old_value) == 1 and 'full_details' in old_value and not old_value['full_details'])
                    new_empty = not new_value or (len(new_value) == 1 and 'full_details' in new_value and not new_value['full_details'])
                    if old_empty and new_empty:
                        continue
            
            # So sánh chuẩn hóa
            if not self._equal_value(old_value, new_value):
                changes[field] = {
                    'old': old_value,
                    'new': new_value,
                    'type': config['type']
                }
        return changes
    
    def _values_different(self, old_value: Any, new_value: Any, config: Dict) -> bool:
        """Check if two values are different based on field configuration"""
        field_type = config['type']
        threshold = config.get('threshold', 0)
        
        # Handle None values
        if old_value is None or new_value is None:
            return old_value != new_value
        
        try:
            if field_type == 'float':
                # For floats, check if difference exceeds threshold
                return abs(float(new_value) - float(old_value)) >= threshold
            
            elif field_type == 'int':
                # For integers, check if difference exceeds threshold
                return abs(int(new_value) - int(old_value)) >= threshold
            
            elif field_type == 'bool':
                # For booleans, any change is significant
                return bool(old_value) != bool(new_value)
            
            elif field_type == 'string':
                # For strings, any change is significant (but normalize whitespace)
                old_str = str(old_value).strip() if old_value else ""
                new_str = str(new_value).strip() if new_value else ""
                return old_str != new_str
            
            elif field_type == 'list':
                # For lists, compare content
                if isinstance(old_value, list) and isinstance(new_value, list):
                    return set(str(x) for x in old_value) != set(str(x) for x in new_value)
                else:
                    return str(old_value) != str(new_value)
            
            elif field_type == 'json':
                # For JSON fields (like product_description_images), compare content
                if isinstance(old_value, list) and isinstance(new_value, list):
                    # Compare each item in the lists
                    old_set = set(str(x) for x in old_value)
                    new_set = set(str(x) for x in new_value)
                    return old_set != new_set
                elif isinstance(old_value, dict) and isinstance(new_value, dict):
                    # For dictionaries, compare key-value pairs
                    return old_value != new_value
                else:
                    return str(old_value) != str(new_value)
            
            else:
                # Default: direct comparison
                return old_value != new_value
                
        except (ValueError, TypeError) as e:
            logger.warning(f"Error comparing values {old_value} and {new_value}: {e}")
            return str(old_value) != str(new_value)
    
    def _filter_significant_changes(self, changes: Dict) -> Dict:
        """Filter out insignificant changes"""
        significant_changes = {}
        
        for field, change_data in changes.items():
            if self._is_change_significant(field, change_data):
                significant_changes[field] = change_data
        
        return significant_changes
    
    def _is_change_significant(self, field: str, change_data: Dict) -> bool:
        """Determine if a change is significant enough to notify"""
        # Báo cáo TẤT CẢ 23 trường khi có thay đổi
        # Không lọc bớt nữa - báo cáo mọi thay đổi
        return True
        
        # Code cũ (đã comment):
        # old_value = change_data['old']
        # new_value = change_data['new']
        # 
        # # Always significant changes
        # significant_fields = [
        #     'best_deal', 'lightning_deal', 'coupon_available', 
        #     'amazon_choice', 'inventory_status', 'product_description_images'
        # ]
        # 
        # if field in significant_fields:
        #     return True
        # 
        # # Price changes - significant if change is more than 1%
        # if field in ['sale_price', 'list_price']:
        #     if old_value and new_value and old_value > 0:
        #         change_percent = abs((new_value - old_value) / old_value) * 100
        #         return change_percent >= 1.0  # 1% threshold
        # 
        # # Rating changes - significant if change is 0.1 or more
        # if field == 'rating':
        #     if old_value and new_value:
        #         return abs(new_value - old_value) >= 0.1
        # 
        # # Rating count changes - significant if change is 10 or more
        # if field == 'rating_count':
        #     if old_value and new_value:
        #         return abs(new_value - old_value) >= 10
        # 
        # # Bag sale count changes - significant if change is 50+ or more
        # if field == 'bag_sale_count':
        #     if old_value and new_value:
        #         return abs(new_value - old_value) >= 50
        # 
        # # Image/video count changes
        # if field in ['image_count', 'video_count']:
        #     return True  # Any change in media count is significant
        # 
        # # Title changes
        # if field == 'title':
        #     if old_value and new_value:
        #         # Significant if title changes substantially
        #         old_words = set(str(old_value).lower().split())
        #         new_words = set(str(new_value).lower().split())
        #         # Check if more than 20% of words changed
        #         total_words = len(old_words.union(new_words))
        #         common_words = len(old_words.intersection(new_words))
        #         if total_words > 0:
        #             similarity = common_words / total_words
        #             return similarity < 0.8  # 80% similarity threshold
        # 
        # # Seller/brand link changes
        # if field in ['brand_store_link', 'sold_by_link']:
        #     return True  # Any seller change is significant
        # 
        # # Default: consider it significant
        # return True
    
    def _log_changes(self, asin: str, changes: Dict):
        """Log detected changes"""
        try:
            change_summary = []
            for field, change_data in changes.items():
                old_val = change_data['old']
                new_val = change_data['new']
                change_summary.append(f"{field}: {old_val} → {new_val}")
            
            logger.info(f"Changes detected for ASIN {asin}: {'; '.join(change_summary)}")
            
        except Exception as e:
            logger.error(f"Error logging changes: {e}")
    
    def get_change_history(self, asin: str, days: int = 30) -> List[Dict]:
        """Get change history for an ASIN over specified days"""
        try:
            since_date = datetime.utcnow() - timedelta(days=days)
            
            crawl_history = (
                self.session.query(ProductCrawlHistory)
                .filter_by(asin=asin)
                .filter(ProductCrawlHistory.crawl_date >= since_date)
                .order_by(ProductCrawlHistory.crawl_date.desc())
                .all()
            )
            
            if len(crawl_history) < 2:
                return []
            
            change_history = []
            
            for i in range(len(crawl_history) - 1):
                current_crawl = crawl_history[i]
                previous_crawl = crawl_history[i + 1]
                
                # Convert to dict for comparison
                current_data = {}
                previous_data = {}
                
                for field in self.monitored_fields.keys():
                    current_data[field] = getattr(current_crawl, field, None)
                    previous_data[field] = getattr(previous_crawl, field, None)
                
                # Detect changes
                changes = self._compare_data(previous_data, current_data)
                significant_changes = self._filter_significant_changes(changes)
                
                if significant_changes:
                    change_history.append({
                        'date': current_crawl.crawl_date,
                        'changes': significant_changes
                    })
            
            return change_history
            
        except Exception as e:
            logger.error(f"Error getting change history for {asin}: {e}")
            return []
    
    def close(self):
        """Close database session"""
        if self.session:
            self.session.close()

# Utility function
async def detect_changes(asin: str, new_data: Dict) -> Dict:
    """Detect changes for a product"""
    detector = ChangeDetector()
    try:
        return await detector.detect_and_notify_changes(asin, new_data)
    finally:
        detector.close()

if __name__ == "__main__":
    # Test change detection
    async def test():
        test_asin = "B019QZBS10"
        
        # Mock new data
        new_data = {
            'sale_price': 12.99,
            'list_price': 15.99,
            'rating': 4.5,
            'rating_count': 150,
            'inventory_status': 'In Stock',
            'coupon_available': True,
            'amazon_choice': True
        }
        
        result = await detect_changes(test_asin, new_data)
        print(f"Change detection result: {result}")
    
    asyncio.run(test()) 