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
        """Send notification about product changes"""
        try:
            # Generate message
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
        """Generate notification message"""
        title = product_data.get('title', 'Unknown Product')
        
        message_parts = [
            f"🚨 THAY ĐỔI SẢN PHẨM AMAZON",
            f"ASIN: {asin}",
            f"Sản phẩm: {title[:100]}...",
            f"",
            f"📊 CÁC THAY ĐỔI:"
        ]
        
        # Price changes
        if 'sale_price' in changes:
            old_price = changes['sale_price']['old']
            new_price = changes['sale_price']['new']
            if old_price and new_price:
                change_percent = ((new_price - old_price) / old_price) * 100
                direction = "📈" if change_percent > 0 else "📉"
                message_parts.append(f"{direction} Giá bán: ${old_price:.2f} → ${new_price:.2f} ({change_percent:+.1f}%)")
        
        if 'list_price' in changes:
            old_price = changes['list_price']['old']
            new_price = changes['list_price']['new']
            if old_price and new_price:
                message_parts.append(f"💰 Giá niêm yết: ${old_price:.2f} → ${new_price:.2f}")
        
        # Rating changes
        if 'rating' in changes:
            old_rating = changes['rating']['old']
            new_rating = changes['rating']['new']
            if old_rating and new_rating:
                direction = "⭐" if new_rating > old_rating else "📉"
                message_parts.append(f"{direction} Đánh giá: {old_rating} → {new_rating}")
        
        if 'rating_count' in changes:
            old_count = changes['rating_count']['old']
            new_count = changes['rating_count']['new']
            if old_count and new_count:
                message_parts.append(f"👥 Số lượng đánh giá: {old_count:,} → {new_count:,}")
        
        # Inventory changes
        if 'inventory_status' in changes:
            old_status = changes['inventory_status']['old']
            new_status = changes['inventory_status']['new']
            emoji = "✅" if "in stock" in new_status.lower() else "❌"
            message_parts.append(f"{emoji} Tồn kho: {old_status} → {new_status}")
        
        # Promotions
        if 'coupon_available' in changes:
            if changes['coupon_available']['new']:
                message_parts.append(f"🎟️ Coupon mới có sẵn!")
            else:
                message_parts.append(f"❌ Coupon đã hết hạn")
        
        if 'lightning_deal' in changes:
            if changes['lightning_deal']['new']:
                message_parts.append(f"⚡ Lightning Deal đang diễn ra!")
        
        if 'best_deal' in changes:
            if changes['best_deal']['new']:
                message_parts.append(f"🔥 Best Deal đang diễn ra!")
        
        # Amazon's Choice
        if 'amazon_choice' in changes:
            if changes['amazon_choice']['new']:
                message_parts.append(f"🏆 Được chọn làm Amazon's Choice!")
            else:
                message_parts.append(f"📉 Không còn là Amazon's Choice")
        
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
                
                old_count = len(old_images)
                new_count = len(new_images)
                
                if added_images and removed_images:
                    message_parts.append(f"🔄 Ảnh mô tả sản phẩm đã thay đổi: +{len(added_images)} ảnh mới, -{len(removed_images)} ảnh cũ")
                elif added_images:
                    message_parts.append(f"🖼️ Thêm {len(added_images)} ảnh mô tả sản phẩm mới!")
                elif removed_images:
                    message_parts.append(f"📷 Giảm {len(removed_images)} ảnh mô tả sản phẩm")
                elif old_count != new_count:
                    # Same URLs but different count (duplicates removed/added)
                    message_parts.append(f"🔄 Số lượng ảnh mô tả sản phẩm thay đổi: {old_count} → {new_count}")
                else:
                    message_parts.append(f"🔄 Ảnh mô tả sản phẩm đã thay đổi (thứ tự hoặc nội dung)")
            else:
                # Fallback for non-list data
                if old_images != new_images:
                    message_parts.append(f"🔄 Ảnh mô tả sản phẩm đã thay đổi")
        
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
                
                old_count = len(old_images)
                new_count = len(new_images)
                
                if added_images and removed_images:
                    message_parts.append(f"🔄 Ảnh sản phẩm đã thay đổi: +{len(added_images)} ảnh mới, -{len(removed_images)} ảnh cũ")
                elif added_images:
                    message_parts.append(f"📸 Thêm {len(added_images)} ảnh sản phẩm mới!")
                elif removed_images:
                    message_parts.append(f"🗑️ Giảm {len(removed_images)} ảnh sản phẩm")
                elif old_count != new_count:
                    # Same URLs but different count (duplicates removed/added)
                    message_parts.append(f"🔄 Số lượng ảnh sản phẩm thay đổi: {old_count} → {new_count}")
                else:
                    message_parts.append(f"🔄 Ảnh sản phẩm đã thay đổi (thứ tự hoặc nội dung)")
            else:
                # Fallback for non-list data
                if old_images != new_images:
                    message_parts.append(f"🔄 Ảnh sản phẩm đã thay đổi")
        
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
                
                old_count = len(old_videos)
                new_count = len(new_videos)
                
                if added_videos and removed_videos:
                    message_parts.append(f"🔄 Video sản phẩm đã thay đổi: +{len(added_videos)} video mới, -{len(removed_videos)} video cũ")
                elif added_videos:
                    message_parts.append(f"🎬 Thêm {len(added_videos)} video sản phẩm mới!")
                elif removed_videos:
                    message_parts.append(f"🎥 Giảm {len(removed_videos)} video sản phẩm")
                elif old_count != new_count:
                    # Same URLs but different count (duplicates removed/added)
                    message_parts.append(f"🔄 Số lượng video sản phẩm thay đổi: {old_count} → {new_count}")
                else:
                    message_parts.append(f"🔄 Video sản phẩm đã thay đổi (thứ tự hoặc nội dung)")
            else:
                # Fallback for non-list data
                if old_videos != new_videos:
                    message_parts.append(f"🔄 Video sản phẩm đã thay đổi")
        
        # Bag sale changes
        if 'bag_sale_count' in changes:
            old_count = changes['bag_sale_count']['old']
            new_count = changes['bag_sale_count']['new']
            if old_count and new_count:
                message_parts.append(f"🛒 Đã bán: {old_count}+ → {new_count}+ trong tháng qua")
        
        # Get current time in New York timezone
        ny_time = datetime.now(self.timezone)
        
        message_parts.extend([
            f"",
            f"🕒 Thời gian (New York): {ny_time.strftime('%d/%m/%Y %H:%M:%S %Z')}",
            f"🔗 Link: https://www.amazon.com/dp/{asin}"
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