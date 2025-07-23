from sqlalchemy import Column, Integer, String, Text, Float, Boolean, DateTime, JSON, ForeignKey
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import relationship
from datetime import datetime

Base = declarative_base()

class Product(Base):
    __tablename__ = "products"
    
    id = Column(Integer, primary_key=True, index=True)
    asin = Column(String(10), unique=True, index=True, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    is_active = Column(Boolean, default=True)
    
    # Relationships
    crawl_history = relationship("ProductCrawlHistory", back_populates="product")
    notifications = relationship("NotificationLog", back_populates="product")

class ProductCrawlHistory(Base):
    __tablename__ = "product_crawl_history"
    
    id = Column(Integer, primary_key=True, index=True)
    product_id = Column(Integer, ForeignKey("products.id"))
    asin = Column(String(10), index=True)
    crawl_date = Column(DateTime, default=datetime.utcnow)
    
    # 📊 Core Product Info (4 fields)
    title = Column(Text)                        # 1. Tên sản phẩm
    product_description = Column(Text)          # 2. Mô tả sản phẩm (EBC content)
    product_information = Column(JSON)          # 3. Thông số kỹ thuật
    about_this_item = Column(JSON)              # 4. About this item (bullet points)
    
    # 🖼️ Media (4 fields)
    image_count = Column(Integer, default=0)    # 5. Số lượng ảnh
    image_urls = Column(JSON)                   # 6. Link ảnh
    video_count = Column(Integer, default=0)    # 7. Số lượng video
    video_urls = Column(JSON)                   # 8. Link video
    
    # 💰 Pricing (3 fields)
    sale_price = Column(Float)                  # 9. Giá sale
    list_price = Column(Float)                  # 10. Giá niêm yết
    sale_percentage = Column(Integer)           # 11. % giảm giá
    
    # 🏷️ Promotions (4 fields)
    best_deal = Column(String(100), default="")  # 12. Chương trình khuyến mãi (e.g., "Limited time deal")
    lightning_deal = Column(String(20))          # 13. Lightning deal (e.g., "81% claimed")
    coupon = Column(Text, default="")            # 14. Có coupon (1 or 0)
    bag_sale = Column(String(100))               # 15. Thông tin bag sale
    
    # ⭐ Reviews (2 fields)
    rating = Column(Float)                      # 16. Đánh giá (4.0)
    rating_count = Column(Integer)              # 17. Số lượng rating
    
    # 🏪 Seller Info (2 fields)
    brand_store_link = Column(String(500))      # 18. Link store nhãn hàng
    sold_by_link = Column(String(500))          # 19. Link nhà bán
    
    # 📢 Marketing (3 fields)
    advertised_asins = Column(JSON)             # 20. ID sản phẩm quảng cáo
    amazon_choice = Column(Integer, default=0)  # 21. Amazon's Choice (1 or 0)
    inventory = Column(String(50))              # 22. Tình trạng kho (InStock)
    
    # Meta fields
    crawl_success = Column(Boolean, default=False)
    crawl_error = Column(Text)
    
    # Relationships
    product = relationship("Product", back_populates="crawl_history")

class ASINWatchlist(Base):
    __tablename__ = "asin_watchlist"
    
    id = Column(Integer, primary_key=True, index=True)
    asin = Column(String(10), unique=True, index=True)
    added_date = Column(DateTime, default=datetime.utcnow)
    is_active = Column(Boolean, default=True)
    crawl_frequency = Column(String(20), default="daily")  # daily, weekly, monthly
    last_crawled = Column(DateTime)
    next_crawl = Column(DateTime)
    notes = Column(Text)

class NotificationSettings(Base):
    __tablename__ = "notification_settings"
    
    id = Column(Integer, primary_key=True, index=True)
    notification_type = Column(String(20))  # telegram, discord, email
    enabled = Column(Boolean, default=True)
    config = Column(JSON)  # Store notification-specific configuration
    
    # Notification Triggers
    price_change = Column(Boolean, default=True)
    availability_change = Column(Boolean, default=True)
    rating_change = Column(Boolean, default=True)
    new_coupon = Column(Boolean, default=True)
    new_deal = Column(Boolean, default=True)

class NotificationLog(Base):
    __tablename__ = "notification_log"
    
    id = Column(Integer, primary_key=True, index=True)
    product_id = Column(Integer, ForeignKey("products.id"))
    notification_type = Column(String(20))
    message = Column(Text)
    sent_at = Column(DateTime, default=datetime.utcnow)
    success = Column(Boolean, default=False)
    error_message = Column(Text)
    
    # Relationships
    product = relationship("Product", back_populates="notifications")

class CrawlStats(Base):
    __tablename__ = "crawl_stats"
    
    id = Column(Integer, primary_key=True, index=True)
    date = Column(DateTime, default=datetime.utcnow)
    total_asins_crawled = Column(Integer, default=0)
    successful_crawls = Column(Integer, default=0)
    failed_crawls = Column(Integer, default=0)
    average_crawl_time = Column(Float)
    errors_encountered = Column(JSON)

class UserSettings(Base):
    __tablename__ = "user_settings"
    
    id = Column(Integer, primary_key=True, index=True)
    setting_key = Column(String(100), unique=True)
    setting_value = Column(Text)
    description = Column(Text)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow) 