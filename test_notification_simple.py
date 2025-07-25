#!/usr/bin/env python3
"""
Test script đơn giản cho notification từ .env
"""
import asyncio
from config.settings import settings
from notifications.notification_service import NotificationService

async def test_notification():
    """Test gửi notification với dữ liệu giả"""
    print("🧪 TESTING NOTIFICATION WITH .ENV CONFIG")
    print("=" * 50)
    
    # Kiểm tra cấu hình
    print("📋 CHECKING CONFIGURATION:")
    
    if settings.TELEGRAM_BOT_TOKEN and settings.TELEGRAM_CHAT_ID:
        print(f"✅ Telegram: Bot Token: {settings.TELEGRAM_BOT_TOKEN[:10]}...")
        print(f"           Chat ID: {settings.TELEGRAM_CHAT_ID}")
    else:
        print("❌ Telegram: Chưa cấu hình")
    
    if settings.DISCORD_WEBHOOK_URL:
        print(f"✅ Discord: {settings.DISCORD_WEBHOOK_URL[:30]}...")
    else:
        print("❌ Discord: Chưa cấu hình")
    
    if settings.EMAIL_SMTP_SERVER and settings.EMAIL_USERNAME:
        print(f"✅ Email: {settings.EMAIL_USERNAME}")
    else:
        print("❌ Email: Chưa cấu hình")
    
    # Dữ liệu test giả
    test_asin = "B0BZYCJK89"
    test_changes = {
        'sale_price': {'old': 15.99, 'new': 13.99, 'type': 'float'},
        'rating': {'old': 4.4, 'new': 4.6, 'type': 'float'},
        'rating_count': {'old': 120, 'new': 145, 'type': 'int'},
        'coupon_available': {'old': False, 'new': True, 'type': 'bool'},
        'best_deal': {'old': '', 'new': 'Limited time deal', 'type': 'string'}
    }
    test_product_data = {
        'asin': test_asin,
        'title': 'Test Product - Amazon Crawler Demo Item'
    }
    
    print(f"\n📊 TEST DATA:")
    print(f"   ASIN: {test_asin}")
    print(f"   Giá: ${test_changes['sale_price']['old']} → ${test_changes['sale_price']['new']}")
    print(f"   Rating: {test_changes['rating']['old']} → {test_changes['rating']['new']}")
    print(f"   Coupon: {test_changes['coupon_available']['old']} → {test_changes['coupon_available']['new']}")
    print(f"   Deal: '{test_changes['best_deal']['old']}' → '{test_changes['best_deal']['new']}'")
    
    # Test gửi notification
    print(f"\n📱 SENDING TEST NOTIFICATION...")
    
    service = NotificationService()
    try:
        await service.send_product_change_notification(test_asin, test_changes, test_product_data)
        print("✅ Notification sent successfully!")
        print("📲 Kiểm tra Telegram/Discord/Email để xem thông báo")
    except Exception as e:
        print(f"❌ Error sending notification: {e}")
    finally:
        service.close()

if __name__ == "__main__":
    print("🚀 Starting Notification Test...")
    asyncio.run(test_notification()) 