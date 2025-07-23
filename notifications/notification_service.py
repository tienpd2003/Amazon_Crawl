import asyncio
import smtplib
import json
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from typing import Dict, List, Optional
from datetime import datetime

import requests
import telegram
from discord_webhook import DiscordWebhook, DiscordEmbed

from config.settings import settings
from database.connection import get_db_session
from database.models import NotificationSettings, NotificationLog, Product
from utils.logger import get_logger

logger = get_logger(__name__)

class NotificationService:
    def __init__(self):
        self.session = get_db_session()
    
    async def send_product_change_notification(self, asin: str, changes: Dict, product_data: Dict):
        """Send notification about product changes"""
        try:
            # Get notification settings
            notification_settings = self._get_notification_settings()
            
            # Generate message
            message = self._generate_change_message(asin, changes, product_data)
            
            # Send notifications
            for setting in notification_settings:
                if setting.enabled:
                    success = False
                    error_msg = None
                    
                    try:
                        if setting.notification_type == "telegram":
                            success = await self._send_telegram_notification(message, setting.config)
                        elif setting.notification_type == "discord":
                            success = await self._send_discord_notification(message, changes, product_data, setting.config)
                        elif setting.notification_type == "email":
                            success = await self._send_email_notification(message, asin, setting.config)
                        
                    except Exception as e:
                        error_msg = str(e)
                        logger.error(f"Failed to send {setting.notification_type} notification: {e}")
                    
                    # Log notification attempt
                    self._log_notification(asin, setting.notification_type, message, success, error_msg)
            
        except Exception as e:
            logger.error(f"Error sending notifications for ASIN {asin}: {e}")
    
    def _get_notification_settings(self) -> List[NotificationSettings]:
        """Get enabled notification settings"""
        return self.session.query(NotificationSettings).filter_by(enabled=True).all()
    
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
        
        # Bag sale changes
        if 'bag_sale_count' in changes:
            old_count = changes['bag_sale_count']['old']
            new_count = changes['bag_sale_count']['new']
            if old_count and new_count:
                message_parts.append(f"🛒 Đã bán: {old_count}+ → {new_count}+ trong tháng qua")
        
        message_parts.extend([
            f"",
            f"🕒 Thời gian: {datetime.now().strftime('%d/%m/%Y %H:%M:%S')}",
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
    
    async def _send_discord_notification(self, message: str, changes: Dict, product_data: Dict, config: Dict) -> bool:
        """Send Discord notification"""
        try:
            webhook_url = config.get('webhook_url') or settings.DISCORD_WEBHOOK_URL
            
            if not webhook_url:
                logger.warning("Discord webhook URL not configured")
                return False
            
            webhook = DiscordWebhook(url=webhook_url)
            
            # Create embed
            embed = DiscordEmbed(
                title="🚨 Amazon Product Change Alert",
                description=f"ASIN: {product_data.get('asin')}",
                color=0xff5733
            )
            
            embed.add_embed_field(
                name="Product",
                value=product_data.get('title', 'Unknown')[:1000],
                inline=False
            )
            
            # Add change fields
            if 'sale_price' in changes:
                old_price = changes['sale_price']['old']
                new_price = changes['sale_price']['new']
                if old_price and new_price:
                    change_percent = ((new_price - old_price) / old_price) * 100
                    embed.add_embed_field(
                        name="💰 Price Change",
                        value=f"${old_price:.2f} → ${new_price:.2f} ({change_percent:+.1f}%)",
                        inline=True
                    )
            
            if 'rating' in changes:
                old_rating = changes['rating']['old']
                new_rating = changes['rating']['new']
                if old_rating and new_rating:
                    embed.add_embed_field(
                        name="⭐ Rating Change",
                        value=f"{old_rating} → {new_rating}",
                        inline=True
                    )
            
            embed.add_embed_field(
                name="🔗 Product Link",
                value=f"https://www.amazon.com/dp/{product_data.get('asin')}",
                inline=False
            )
            
            embed.set_timestamp()
            webhook.add_embed(embed)
            
            response = webhook.execute()
            
            logger.info("Discord notification sent successfully")
            return True
            
        except Exception as e:
            logger.error(f"Failed to send Discord notification: {e}")
            return False
    
    async def _send_email_notification(self, message: str, asin: str, config: Dict) -> bool:
        """Send email notification"""
        try:
            smtp_server = config.get('smtp_server') or settings.EMAIL_SMTP_SERVER
            smtp_port = config.get('smtp_port') or settings.EMAIL_SMTP_PORT
            username = config.get('username') or settings.EMAIL_USERNAME
            password = config.get('password') or settings.EMAIL_PASSWORD
            recipients = config.get('recipients', [])
            
            if not all([smtp_server, username, password, recipients]):
                logger.warning("Email configuration incomplete")
                return False
            
            # Create message
            msg = MIMEMultipart()
            msg['From'] = username
            msg['To'] = ', '.join(recipients)
            msg['Subject'] = f"Amazon Product Change Alert - ASIN: {asin}"
            
            # Add body
            msg.attach(MIMEText(message, 'plain', 'utf-8'))
            
            # Send email
            with smtplib.SMTP(smtp_server, smtp_port) as server:
                server.starttls()
                server.login(username, password)
                server.send_message(msg)
            
            logger.info("Email notification sent successfully")
            return True
            
        except Exception as e:
            logger.error(f"Failed to send email notification: {e}")
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