#!/usr/bin/env python3
"""
Test script cho chức năng phát hiện thay đổi
Sử dụng: python test_change_detection.py
"""
import asyncio
import json
from datetime import datetime
from typing import Dict

# Import modules
from crawler.amazon_crawler import AmazonCrawler
from crawler.change_detector import detect_changes
from database.connection import get_db_session
from database.models import Product, ProductCrawlHistory, ASINWatchlist

class ChangeDetectionTester:
    def __init__(self):
        self.session = get_db_session()
        
    async def test_single_asin(self, asin: str):
        """Test phát hiện thay đổi cho 1 ASIN"""
        print(f"\n🧪 TESTING CHANGE DETECTION FOR ASIN: {asin}")
        print("=" * 60)
        
        # 1. Kiểm tra ASIN có trong watchlist không
        watchlist_item = self.session.query(ASINWatchlist).filter_by(asin=asin).first()
        if not watchlist_item:
            print(f"⚠️  ASIN {asin} không có trong watchlist. Thêm vào watchlist...")
            watchlist_item = ASINWatchlist(
                asin=asin,
                crawl_frequency="daily",
                is_active=True,
                notes="Added by test script"
            )
            self.session.add(watchlist_item)
            self.session.commit()
            print(f"✅ Đã thêm {asin} vào watchlist")
        
        # 2. Kiểm tra dữ liệu crawl trước đó
        previous_crawls = (
            self.session.query(ProductCrawlHistory)
            .filter_by(asin=asin, crawl_success=True)
            .order_by(ProductCrawlHistory.crawl_date.desc())
            .limit(3)
            .all()
        )
        
        print(f"\n📊 LỊCH SỬ CRAWL:")
        if previous_crawls:
            for i, crawl in enumerate(previous_crawls, 1):
                print(f"  {i}. {crawl.crawl_date.strftime('%Y-%m-%d %H:%M:%S')}")
                print(f"     Giá: ${crawl.sale_price} | Rating: {crawl.rating} | Kho: {crawl.inventory}")
        else:
            print("  📭 Chưa có dữ liệu crawl trước đó")
        
        # 3. Crawl dữ liệu mới
        print(f"\n🕸️  CRAWLING DỮ LIỆU MỚI...")
        crawler = AmazonCrawler()
        try:
            product_data = crawler.crawl_product(asin)
            
            if not product_data.get('crawl_success'):
                print(f"❌ Crawl thất bại: {product_data.get('crawl_error')}")
                return
            
            print(f"✅ Crawl thành công!")
            print(f"   Tên: {product_data.get('title', 'N/A')[:50]}...")
            print(f"   Giá: ${product_data.get('sale_price', 'N/A')}")
            print(f"   Rating: {product_data.get('rating', 'N/A')}")
            print(f"   Kho: {product_data.get('inventory', 'N/A')}")
            
            # 4. Lưu dữ liệu vào database
            print(f"\n💾 SAVING DATA...")
            crawler.save_to_database(product_data)
            print(f"✅ Đã lưu dữ liệu vào database")
            
            # 5. Test phát hiện thay đổi
            print(f"\n🔍 TESTING CHANGE DETECTION...")
            change_result = await detect_changes(asin, product_data)
            
            if change_result.get('is_first_crawl'):
                print(f"🆕 Đây là lần crawl đầu tiên - chưa có dữ liệu để so sánh")
            
            elif change_result.get('has_changes'):
                changes = change_result.get('changes', {})
                print(f"🚨 PHÁT HIỆN {len(changes)} THAY ĐỔI:")
                
                for field, change_data in changes.items():
                    old_val = change_data['old']
                    new_val = change_data['new']
                    
                    if field == 'sale_price':
                        if old_val and new_val:
                            change_percent = ((new_val - old_val) / old_val) * 100
                            direction = "📈" if change_percent > 0 else "📉"
                            print(f"  {direction} {field}: ${old_val} → ${new_val} ({change_percent:+.1f}%)")
                        else:
                            print(f"  💰 {field}: {old_val} → {new_val}")
                    else:
                        print(f"  🔄 {field}: {old_val} → {new_val}")
                
                print(f"\n📱 Thông báo đã được gửi đến các kênh đã cấu hình!")
                
            else:
                print(f"😴 Không có thay đổi nào được phát hiện")
                
        except Exception as e:
            print(f"❌ Lỗi trong quá trình test: {e}")
        finally:
            crawler.close()
    
    async def test_manual_change_simulation(self, asin: str):
        """Mô phỏng thay đổi dữ liệu để test notification"""
        print(f"\n🎭 SIMULATING PRICE CHANGE FOR {asin}")
        print("=" * 50)
        
        # Lấy dữ liệu crawl gần nhất
        latest_crawl = (
            self.session.query(ProductCrawlHistory)
            .filter_by(asin=asin, crawl_success=True)
            .order_by(ProductCrawlHistory.crawl_date.desc())
            .first()
        )
        
        if not latest_crawl:
            print("❌ Không có dữ liệu crawl để mô phỏng")
            return
        
        # Tạo dữ liệu giả với giá thay đổi
        simulated_data = {
            'asin': asin,
            'title': latest_crawl.title,
            'sale_price': latest_crawl.sale_price * 0.85 if latest_crawl.sale_price else 99.99,  # Giảm 15%
            'list_price': latest_crawl.list_price,
            'rating': latest_crawl.rating + 0.2 if latest_crawl.rating else 4.5,  # Tăng 0.2 sao
            'rating_count': latest_crawl.rating_count + 25 if latest_crawl.rating_count else 150,
            'inventory': 'In Stock',
            'coupon_available': True,  # Thêm coupon mới
            'best_deal': 'Limited time deal',  # Thêm deal
            'crawl_success': True
        }
        
        print(f"📊 DỮ LIỆU MÔ PHỎNG:")
        print(f"   Giá cũ: ${latest_crawl.sale_price} → Giá mới: ${simulated_data['sale_price']}")
        print(f"   Rating cũ: {latest_crawl.rating} → Rating mới: {simulated_data['rating']}")
        print(f"   Coupon: Không → Có")
        print(f"   Deal: Không → Limited time deal")
        
        # Test change detection với dữ liệu giả
        change_result = await detect_changes(asin, simulated_data)
        
        if change_result.get('has_changes'):
            changes = change_result.get('changes', {})
            print(f"\n🚨 PHÁT HIỆN {len(changes)} THAY ĐỔI:")
            
            for field, change_data in changes.items():
                print(f"  🔄 {field}: {change_data['old']} → {change_data['new']}")
            
            print(f"\n📱 Notification system sẽ gửi thông báo về những thay đổi này!")
        else:
            print(f"😴 Không có thay đổi nào được phát hiện")
    
    def close(self):
        """Đóng database session"""
        if self.session:
            self.session.close()

async def main():
    """Main function để chạy test"""
    print("🧪 AMAZON CRAWLER - CHANGE DETECTION TESTER")
    print("=" * 60)
    
    # Danh sách ASIN để test (chỉ test mã B01KZ6UMUQ)
    test_asins = [
        "B01KZ6UMUQ",
    ]
    
    tester = ChangeDetectionTester()
    
    try:
        for asin in test_asins:
            # Test crawl mới và phát hiện thay đổi
            await tester.test_single_asin(asin)
            print("\n" + "="*60)
    except KeyboardInterrupt:
        print("\n🛑 Test dừng bởi người dùng")
    except Exception as e:
        print(f"\n❌ Lỗi không mong muốn: {e}")
    finally:
        tester.close()

if __name__ == "__main__":
    print("🚀 Starting Change Detection Test...")
    asyncio.run(main()) 