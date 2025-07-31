import asyncio
from utils.batch_import_optimized import optimized_batch_importer
from database.connection import get_db_session
from database.models import ASINWatchlist, Product, ProductCrawlHistory
from datetime import datetime, timedelta

sample_asins = [
    'B07YKLXB3Y',
    'B0DK4MFCVD',
    'B07VVK39F7'
]

def setup_test_data():
    db = get_db_session()
    try:
        # Đảm bảo 3 ASIN đều có trong watchlist và Product
        for asin in sample_asins:
            # Watchlist
            item = db.query(ASINWatchlist).filter_by(asin=asin).first()
            if not item:
                item = ASINWatchlist(
                    asin=asin,
                    crawl_frequency='daily',
                    notes='Test optimized scheduler',
                    is_active=True
                )
                db.add(item)
            # Product
            product = db.query(Product).filter_by(asin=asin).first()
            if not product:
                product = Product(
                    asin=asin,
                    title=f"Test Product {asin}"
                )
                db.add(product)
        db.commit()

        # Tạo dữ liệu crawl history mẫu cho mỗi ASIN (ngày hôm qua)
        yesterday = datetime.utcnow() - timedelta(days=1)
        for asin in sample_asins:
            product = db.query(Product).filter_by(asin=asin).first()
            crawl = ProductCrawlHistory(
                product_id=product.id,
                asin=asin,
                crawl_date=yesterday,
                title=f"Test Product {asin}",
                product_description="Mô tả sản phẩm mẫu",
                product_description_images=["img1.jpg", "img2.jpg"],
                product_information={"weight": "1kg", "color": "red"},
                about_this_item=["item1", "item2"],
                image_count=3,
                image_urls=["img1.jpg", "img2.jpg", "img3.jpg"],
                video_count=1,
                video_urls=["vid1.mp4"],
                sale_price=10.99,
                list_price=15.99,
                sale_percentage=31,
                best_deal="Deal tốt",
                lightning_deal="Có",
                coupon="Coupon 10%",
                bag_sale="Bag sale info",
                rating=4.5,
                rating_count=123,
                brand_store_link="https://amazon.com/store",
                sold_by_link="https://amazon.com/seller",
                advertised_asins=["B000000001", "B000000002"],
                amazon_choice=1,
                inventory="In Stock",
                crawl_success=True,
                crawl_error=None
            )
            db.add(crawl)
        db.commit()
    finally:
        db.close()

async def test_crawl_and_notify():
    # Chỉ test crawl cho đúng 3 ASIN này
    await optimized_batch_importer._crawl_asins_optimized(sample_asins, batch_size=3)

    # Test gửi thông báo cho 1 ASIN (ví dụ B07YKLXB3Y)
    from notifications.notification_service import send_notification
    changes = {
        "sale_price": {"old": 10.99, "new": 9.99},
        "rating": {"old": 4.5, "new": 4.7},
        "inventory": {"old": "In Stock", "new": "Out of Stock"}
    }
    product_data = {
        "asin": "B07YKLXB3Y",
        "title": "Test Product B07YKLXB3Y"
    }
    await send_notification("B07YKLXB3Y", changes, product_data)

if __name__ == "__main__":
    setup_test_data()
    asyncio.run(test_crawl_and_notify())