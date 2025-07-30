import asyncio
import json
from typing import Dict
from datetime import datetime
import pytz

import telegram
from config.settings import settings
from database.connection import get_db_session
from database.models import NotificationLog, Product
from utils.logger import get_logger

logger = get_logger(__name__)

class NotificationService:
    def __init__(self):
        self.session = get_db_session()
        self.timezone = pytz.timezone('America/New_York')
    
    async def send_product_change_notification(self, asin: str, changes: Dict, product_data: Dict):
        """Send notification about product changes - 1 message per ASIN"""
        try:
            # Generate message for all changes of this ASIN
            message = self._generate_change_message(asin, changes, product_data)
            
            # Send Telegram notification if configured
            if settings.TELEGRAM_BOT_TOKEN and settings.TELEGRAM_CHAT_ID:
                try:
                    telegram_config = {
                        'bot_token': settings.TELEGRAM_BOT_TOKEN,
                        'chat_id': settings.TELEGRAM_CHAT_ID
                    }
                    success = await self._send_telegram_notification(message, telegram_config)
                    self._log_notification(asin, "telegram", message, success, None)
                except Exception as e:
                    logger.error(f"Failed to send Telegram notification: {e}")
                    self._log_notification(asin, "telegram", message, False, str(e))
            
        except Exception as e:
            logger.error(f"Error sending notifications for ASIN {asin}: {e}")
    
    def _generate_change_message(self, asin: str, changes: Dict, product_data: Dict) -> str:
        """Generate notification message for all changes of an ASIN - Clear and concise format"""
        title = product_data.get('title', 'Unknown Product')
        
        message_parts = [
            f"🚨 THAY ĐỔI SẢN PHẨM AMAZON",
            f"ASIN: {asin}",
            f"Sản phẩm: {title[:80]}...",
            f"",
            f"📊 Có {len(changes)} thay đổi:"
        ]
        
        change_number = 1
        
        # Price changes
        if 'sale_price' in changes:
            old_price = changes['sale_price']['old']
            new_price = changes['sale_price']['new']
            if old_price and new_price:
                change_percent = ((new_price - old_price) / old_price) * 100
                direction = "📈" if change_percent > 0 else "📉"
                message_parts.append(f"{change_number}. {direction} Giá bán: ${old_price:.2f} → ${new_price:.2f} ({change_percent:+.1f}%)")
                change_number += 1
        
        if 'list_price' in changes:
            old_price = changes['list_price']['old']
            new_price = changes['list_price']['new']
            if old_price and new_price:
                message_parts.append(f"{change_number}. 💰 Giá niêm yết: ${old_price:.2f} → ${new_price:.2f}")
                change_number += 1
        
        # Rating changes
        if 'rating' in changes:
            old_rating = changes['rating']['old']
            new_rating = changes['rating']['new']
            if old_rating and new_rating:
                direction = "⭐" if new_rating > old_rating else "📉"
                message_parts.append(f"{change_number}. {direction} Đánh giá: {old_rating} → {new_rating}")
                change_number += 1
        
        if 'rating_count' in changes:
            old_count = changes['rating_count']['old']
            new_count = changes['rating_count']['new']
            if old_count and new_count:
                message_parts.append(f"{change_number}. 👥 Số lượng đánh giá: {old_count:,} → {new_count:,}")
                change_number += 1
        
        # Sale percentage changes
        if 'sale_percentage' in changes:
            old_percent = changes['sale_percentage']['old']
            new_percent = changes['sale_percentage']['new']
            if old_percent is not None and new_percent is not None:
                message_parts.append(f"{change_number}. 📊 Phần trăm giảm giá: {old_percent}% → {new_percent}%")
                change_number += 1
        
        # Inventory changes
        if 'inventory' in changes:
            old_status = changes['inventory']['old']
            new_status = changes['inventory']['new']
            emoji = "✅" if "in stock" in str(new_status).lower() else "❌"
            message_parts.append(f"{change_number}. {emoji} Tình trạng kho: {old_status} → {new_status}")
            change_number += 1
        
        # Promotions
        if 'coupon' in changes:
            old_coupon = changes['coupon']['old']
            new_coupon = changes['coupon']['new']
            if new_coupon and not old_coupon:
                message_parts.append(f"{change_number}. 🎟️ Có coupon mới: {new_coupon}")
            elif old_coupon and not new_coupon:
                message_parts.append(f"{change_number}. ❌ Coupon đã hết hạn")
            elif old_coupon != new_coupon:
                message_parts.append(f"{change_number}. 🔄 Coupon có thay đổi")
            change_number += 1
        
        if 'lightning_deal' in changes:
            if changes['lightning_deal']['new']:
                message_parts.append(f"{change_number}. ⚡ Lightning Deal đang diễn ra!")
                change_number += 1
        
        if 'best_deal' in changes:
            if changes['best_deal']['new']:
                message_parts.append(f"{change_number}. 🔥 Best Deal đang diễn ra!")
                change_number += 1
        
        # Bag sale changes
        if 'bag_sale' in changes:
            old_bag = changes['bag_sale']['old']
            new_bag = changes['bag_sale']['new']
            if old_bag != new_bag:
                if new_bag:
                    message_parts.append(f"{change_number}. 🛒 {new_bag}")
                else:
                    message_parts.append(f"{change_number}. ❌ Bag sale đã kết thúc")
                change_number += 1
        
        # Amazon's Choice
        if 'amazon_choice' in changes:
            if changes['amazon_choice']['new']:
                message_parts.append(f"{change_number}. 🏆 Được chọn làm Amazon's Choice!")
            else:
                message_parts.append(f"{change_number}. 📉 Không còn là Amazon's Choice")
            change_number += 1
        
        # Product Description Images changes
        if 'product_description_images' in changes:
            old_images = changes['product_description_images']['old'] or []
            new_images = changes['product_description_images']['new'] or []
            
            if isinstance(old_images, list) and isinstance(new_images, list):
                old_set = set(str(x) for x in old_images)
                new_set = set(str(x) for x in new_images)
                
                # Find added and removed images
                added_images = new_set - old_set
                removed_images = old_set - new_set
                
                if added_images and removed_images:
                    message_parts.append(f"{change_number}. 🖼️ Ảnh mô tả: +{len(added_images)} link mới, -{len(removed_images)} link cũ")
                elif added_images:
                    message_parts.append(f"{change_number}. 🖼️ Thêm {len(added_images)} link ảnh mô tả")
                elif removed_images:
                    message_parts.append(f"{change_number}. 📷 Xóa {len(removed_images)} link ảnh mô tả")
                else:
                    message_parts.append(f"{change_number}. 🔄 Link ảnh mô tả có thay đổi")
                change_number += 1
        
        # Product Images changes (main product images)
        if 'image_urls' in changes:
            old_images = changes['image_urls']['old'] or []
            new_images = changes['image_urls']['new'] or []
            
            if isinstance(old_images, list) and isinstance(new_images, list):
                old_set = set(str(x) for x in old_images)
                new_set = set(str(x) for x in new_images)
                
                # Find added and removed images
                added_images = new_set - old_set
                removed_images = old_set - new_set
                
                if added_images and removed_images:
                    message_parts.append(f"{change_number}. 📸 Ảnh sản phẩm: +{len(added_images)} link mới, -{len(removed_images)} link cũ")
                elif added_images:
                    message_parts.append(f"{change_number}. 📸 Thêm {len(added_images)} link ảnh sản phẩm")
                elif removed_images:
                    message_parts.append(f"{change_number}. 🗑️ Xóa {len(removed_images)} link ảnh sản phẩm")
                else:
                    message_parts.append(f"{change_number}. 🔄 Link ảnh sản phẩm có thay đổi")
                change_number += 1
        
        # Product Videos changes
        if 'video_urls' in changes:
            old_videos = changes['video_urls']['old'] or []
            new_videos = changes['video_urls']['new'] or []
            
            if isinstance(old_videos, list) and isinstance(new_videos, list):
                old_set = set(str(x) for x in old_videos)
                new_set = set(str(x) for x in new_videos)
                
                # Find added and removed videos
                added_videos = new_set - old_set
                removed_videos = old_set - new_set
                
                if added_videos and removed_videos:
                    message_parts.append(f"{change_number}. 🎬 Video sản phẩm: +{len(added_videos)} link mới, -{len(removed_videos)} link cũ")
                elif added_videos:
                    message_parts.append(f"{change_number}. 🎬 Thêm {len(added_videos)} link video sản phẩm")
                elif removed_videos:
                    message_parts.append(f"{change_number}. 🎥 Xóa {len(removed_videos)} link video sản phẩm")
                else:
                    message_parts.append(f"{change_number}. 🔄 Link video sản phẩm có thay đổi")
                change_number += 1
        
        # Seller info changes
        if 'brand_store_link' in changes:
            old_link = changes['brand_store_link']['old']
            new_link = changes['brand_store_link']['new']
            if old_link != new_link:
                message_parts.append(f"{change_number}. 🏪 Link store nhãn hàng có thay đổi")
                change_number += 1
        
        if 'sold_by_link' in changes:
            old_link = changes['sold_by_link']['old']
            new_link = changes['sold_by_link']['new']
            if old_link != new_link:
                message_parts.append(f"{change_number}. 🏪 Link nhà bán có thay đổi")
                change_number += 1
        
        # Advertised ASINs changes
        if 'advertised_asins' in changes:
            old_asins = changes['advertised_asins']['old'] or []
            new_asins = changes['advertised_asins']['new'] or []
            if isinstance(old_asins, list) and isinstance(new_asins, list):
                if len(old_asins) != len(new_asins):
                    message_parts.append(f"{change_number}. 📢 Sản phẩm quảng cáo có thay đổi")
                    change_number += 1
        
        # Image count changes
        if 'image_count' in changes:
            old_count = changes['image_count']['old']
            new_count = changes['image_count']['new']
            if old_count is not None and new_count is not None and old_count != new_count:
                message_parts.append(f"{change_number}. 📸 Số lượng ảnh: {old_count} → {new_count}")
                change_number += 1
        
        # Video count changes
        if 'video_count' in changes:
            old_count = changes['video_count']['old']
            new_count = changes['video_count']['new']
            if old_count is not None and new_count is not None and old_count != new_count:
                message_parts.append(f"{change_number}. 🎬 Số lượng video: {old_count} → {new_count}")
                change_number += 1
        
        # Bag sale count changes
        if 'bag_sale_count' in changes:
            old_count = changes['bag_sale_count']['old']
            new_count = changes['bag_sale_count']['new']
            if old_count and new_count:
                message_parts.append(f"{change_number}. 🛒 Đã bán: {old_count}+ → {new_count}+ trong tháng qua")
                change_number += 1
        
        # Other text changes (shortened)
        text_fields = ['title', 'product_description', 'about_this_item', 'product_information']
        for field in text_fields:
            if field in changes:
                old_value = changes[field]['old']
                new_value = changes[field]['new']
                
                if field == 'title':
                    message_parts.append(f"{change_number}. 📝 Tên sản phẩm có thay đổi")
                elif field == 'product_description':
                    message_parts.append(f"{change_number}. 📄 Mô tả sản phẩm có thay đổi")
                elif field == 'about_this_item':
                    message_parts.append(f"{change_number}. 📋 Tính năng sản phẩm có thay đổi")
                elif field == 'product_information':
                    message_parts.append(f"{change_number}. ℹ️ Thông tin sản phẩm có thay đổi")
                change_number += 1
        
        # Get current time in New York timezone
        ny_time = datetime.now(self.timezone)
        
        message_parts.extend([
            f"",
            f"🕒 Thời gian: {ny_time.strftime('%d/%m/%Y %H:%M:%S %Z')}",
            f"🔗 https://www.amazon.com/dp/{asin}"
        ])
        
        return "\n".join(message_parts)
    
    async def _send_telegram_notification(self, message: str, config: Dict) -> bool:
        """Send Telegram notification"""
        try:
            bot_token = config.get('bot_token') or settings.TELEGRAM_BOT_TOKEN
            chat_id = config.get('chat_id') or settings.TELEGRAM_CHAT_ID
            
            if not bot_token or not chat_id:
                logger.warning("Telegram bot token or chat ID not configured")
                return False
            
            bot = telegram.Bot(token=bot_token)
            await bot.send_message(
                chat_id=chat_id,
                text=message,
                parse_mode='HTML' if '<' in message else None
            )
            
            logger.info("Telegram notification sent successfully")
            return True
            
        except Exception as e:
            logger.error(f"Failed to send Telegram notification: {e}")
            return False
    
    def _log_notification(self, asin: str, notification_type: str, message: str, success: bool, error_message: str = None):
        """Log notification attempt"""
        try:
            # Get product
            product = self.session.query(Product).filter_by(asin=asin).first()
            if not product:
                return
            
            log_entry = NotificationLog(
                product_id=product.id,
                notification_type=notification_type,
                message=message,
                success=success,
                error_message=error_message
            )
            
            self.session.add(log_entry)
            self.session.commit()
            
        except Exception as e:
            logger.error(f"Failed to log notification: {e}")
            self.session.rollback()
    
    def close(self):
        """Close database session"""
        if self.session:
            self.session.close()

# Utility function
async def send_notification(asin: str, changes: Dict, product_data: Dict):
    """Send notification about product changes"""
    service = NotificationService()
    try:
        await service.send_product_change_notification(asin, changes, product_data)
    finally:
        service.close()

if __name__ == "__main__":
    # Test notification
    async def test():
        test_changes = {
            'sale_price': {'old': 13.99, 'new': 11.99},
            'rating': {'old': 4.3, 'new': 4.5},
            'coupon_available': {'old': False, 'new': True}
        }
        test_product = {
            'asin': 'B019QZBS10',
            'title': 'Test Product for Amazon Crawler'
        }
        await send_notification('B019QZBS10', test_changes, test_product)
    
    asyncio.run(test()) 