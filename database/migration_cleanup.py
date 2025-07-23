"""
Migration script to clean up database schema
Remove unused columns and keep only required 22 fields + meta fields
"""

import sqlite3
import logging
from pathlib import Path

# Setup logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def migrate_database():
    """Remove unused columns from ProductCrawlHistory table"""
    
    db_path = Path("amazon_crawler.db")
    if not db_path.exists():
        logger.info("No existing database found. No migration needed.")
        return
    
    try:
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        
        logger.info("🔧 Starting database migration...")
        
        # Check if ProductCrawlHistory table exists
        cursor.execute("""
            SELECT name FROM sqlite_master 
            WHERE type='table' AND name='product_crawl_history'
        """)
        
        if not cursor.fetchone():
            logger.info("ProductCrawlHistory table not found. No migration needed.")
            return
        
        # Get current columns
        cursor.execute("PRAGMA table_info(product_crawl_history)")
        current_columns = [row[1] for row in cursor.fetchall()]
        logger.info(f"Current columns: {len(current_columns)} columns found")
        
        # Define required columns (22 fields + meta)
        required_columns = [
            'id', 'product_id', 'asin', 'crawl_date',
            # 22 required fields
            'title', 'description_ebc', 'product_information', 'bullet_points',
            'image_count', 'image_urls', 'video_count', 'video_urls',
            'sale_price', 'list_price', 'sale_percentage',
            'best_deal', 'lightning_deal', 'coupon_available', 'bag_sale_text',
            'rating', 'rating_count',
            'brand_store_link', 'sold_by_link',
            'advertised_asins', 'amazon_choice', 'inventory_status',
            # meta fields
            'crawl_success', 'crawl_error'
        ]
        
        # Find columns to remove
        columns_to_remove = [col for col in current_columns if col not in required_columns]
        
        if not columns_to_remove:
            logger.info("✅ Database schema is already clean. No migration needed.")
            return
        
        logger.info(f"🗑️ Columns to remove: {columns_to_remove}")
        
        # Create new table with only required columns
        cursor.execute("""
            CREATE TABLE product_crawl_history_new (
                id INTEGER PRIMARY KEY,
                product_id INTEGER,
                asin VARCHAR(10),
                crawl_date DATETIME,
                
                -- 📊 Core Product Info (4 fields)
                title TEXT,                          -- 1. Tên sản phẩm
                description_ebc TEXT,                -- 2. Mô tả sản phẩm (EBC content)
                product_information JSON,            -- 3. Thông số kỹ thuật
                bullet_points JSON,                  -- 4. About this item (bullet points)
                
                -- 🖼️ Media (4 fields)
                image_count INTEGER DEFAULT 0,      -- 5. Số lượng ảnh
                image_urls JSON,                     -- 6. Link ảnh
                video_count INTEGER DEFAULT 0,      -- 7. Số lượng video
                video_urls JSON,                     -- 8. Link video
                
                -- 💰 Pricing (3 fields)
                sale_price FLOAT,                   -- 9. Giá sale
                list_price FLOAT,                   -- 10. Giá niêm yết
                sale_percentage INTEGER,            -- 11. % giảm giá
                
                -- 🏷️ Promotions (4 fields)
                best_deal BOOLEAN DEFAULT 0,        -- 12. Best deal flag
                lightning_deal BOOLEAN DEFAULT 0,   -- 13. Lightning deal flag
                coupon_available BOOLEAN DEFAULT 0, -- 14. Có coupon (1/0)
                bag_sale_text VARCHAR(100),         -- 15. Thông tin bag sale
                
                -- ⭐ Reviews (2 fields)
                rating FLOAT,                       -- 16. Đánh giá (4.0)
                rating_count INTEGER,               -- 17. Số lượng rating
                
                -- 🏪 Seller Info (2 fields)
                brand_store_link VARCHAR(500),      -- 18. Link store nhãn hàng
                sold_by_link VARCHAR(500),          -- 19. Link nhà bán
                
                -- 📢 Marketing (3 fields)
                advertised_asins JSON,              -- 20. ID sản phẩm quảng cáo
                amazon_choice BOOLEAN DEFAULT 0,    -- 21. Amazon's Choice (1/0)
                inventory_status VARCHAR(50),       -- 22. Tình trạng kho (InStock)
                
                -- Meta fields
                crawl_success BOOLEAN DEFAULT 0,
                crawl_error TEXT,
                
                FOREIGN KEY (product_id) REFERENCES products (id)
            )
        """)
        
        # Copy data from old table to new table
        column_list = ', '.join([col for col in required_columns if col in current_columns])
        cursor.execute(f"""
            INSERT INTO product_crawl_history_new ({column_list})
            SELECT {column_list} FROM product_crawl_history
        """)
        
        # Drop old table and rename new table
        cursor.execute("DROP TABLE product_crawl_history")
        cursor.execute("ALTER TABLE product_crawl_history_new RENAME TO product_crawl_history")
        
        # Recreate indexes
        cursor.execute("CREATE INDEX idx_product_crawl_history_asin ON product_crawl_history(asin)")
        cursor.execute("CREATE INDEX idx_product_crawl_history_product_id ON product_crawl_history(product_id)")
        
        conn.commit()
        logger.info("✅ Database migration completed successfully!")
        logger.info(f"Removed {len(columns_to_remove)} unused columns")
        logger.info("Database now contains only required 22 fields + meta fields")
        
    except Exception as e:
        logger.error(f"❌ Migration failed: {e}")
        conn.rollback()
        raise
    finally:
        conn.close()

if __name__ == "__main__":
    migrate_database() 