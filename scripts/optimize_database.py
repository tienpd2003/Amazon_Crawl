#!/usr/bin/env python3
"""
Database optimization script for large-scale Amazon crawler
Usage: python scripts/optimize_database.py
"""

import sqlite3
import os
import sys
from pathlib import Path
from datetime import datetime

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

def optimize_database():
    """Optimize database for large-scale operations"""
    db_path = "amazon_crawler.db"
    
    if not os.path.exists(db_path):
        print(f"❌ Database not found: {db_path}")
        return False
    
    print("🔧 Optimizing database for large-scale operations...")
    print("="*50)
    
    try:
        # Connect to database
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        
        # Get database info
        cursor.execute("PRAGMA database_list")
        db_info = cursor.fetchall()
        print(f"📊 Database: {db_info[0][2]}")
        
        # Get table sizes
        cursor.execute("""
            SELECT name, sql FROM sqlite_master 
            WHERE type='table' AND name NOT LIKE 'sqlite_%'
        """)
        tables = cursor.fetchall()
        
        print(f"\n📋 Tables found: {len(tables)}")
        for table_name, _ in tables:
            cursor.execute(f"SELECT COUNT(*) FROM {table_name}")
            count = cursor.fetchone()[0]
            print(f"   - {table_name}: {count:,} rows")
        
        # Create indexes for better performance
        print("\n🔍 Creating indexes...")
        
        # Indexes for asin_watchlist
        indexes = [
            ("CREATE INDEX IF NOT EXISTS idx_asin_watchlist_asin ON asin_watchlist(asin)", "asin_watchlist.asin"),
            ("CREATE INDEX IF NOT EXISTS idx_asin_watchlist_active ON asin_watchlist(is_active)", "asin_watchlist.is_active"),
            ("CREATE INDEX IF NOT EXISTS idx_asin_watchlist_next_crawl ON asin_watchlist(next_crawl)", "asin_watchlist.next_crawl"),
            
            # Indexes for product_crawl_history
            ("CREATE INDEX IF NOT EXISTS idx_crawl_history_asin ON product_crawl_history(asin)", "product_crawl_history.asin"),
            ("CREATE INDEX IF NOT EXISTS idx_crawl_history_date ON product_crawl_history(crawl_date)", "product_crawl_history.crawl_date"),
            ("CREATE INDEX IF NOT EXISTS idx_crawl_history_success ON product_crawl_history(crawl_success)", "product_crawl_history.crawl_success"),
            ("CREATE INDEX IF NOT EXISTS idx_crawl_history_product_id ON product_crawl_history(product_id)", "product_crawl_history.product_id"),
            
            # Indexes for products
            ("CREATE INDEX IF NOT EXISTS idx_products_asin ON products(asin)", "products.asin"),
        ]
        
        for sql, description in indexes:
            try:
                cursor.execute(sql)
                print(f"   ✅ Created index: {description}")
            except Exception as e:
                print(f"   ⚠️  Index already exists or error: {description}")
        
        # Optimize database
        print("\n⚡ Optimizing database...")
        
        # Enable WAL mode for better concurrency
        cursor.execute("PRAGMA journal_mode=WAL")
        print("   ✅ Enabled WAL mode")
        
        # Set page size for better performance
        cursor.execute("PRAGMA page_size=4096")
        print("   ✅ Set page size to 4096")
        
        # Set cache size (in pages)
        cursor.execute("PRAGMA cache_size=10000")
        print("   ✅ Set cache size to 10,000 pages")
        
        # Enable foreign keys
        cursor.execute("PRAGMA foreign_keys=ON")
        print("   ✅ Enabled foreign keys")
        
        # Analyze tables for query optimization
        cursor.execute("ANALYZE")
        print("   ✅ Analyzed tables for optimization")
        
        # Vacuum database to reclaim space
        print("\n🧹 Cleaning up database...")
        cursor.execute("VACUUM")
        print("   ✅ Vacuumed database")
        
        # Get final statistics
        print("\n📈 Final database statistics:")
        
        # Table sizes after optimization
        for table_name, _ in tables:
            cursor.execute(f"SELECT COUNT(*) FROM {table_name}")
            count = cursor.fetchone()[0]
            
            # Get table size in bytes
            cursor.execute(f"PRAGMA table_info({table_name})")
            columns = cursor.fetchall()
            
            print(f"   - {table_name}: {count:,} rows")
        
        # Database file size
        file_size = os.path.getsize(db_path)
        file_size_mb = file_size / (1024 * 1024)
        print(f"   - Database file size: {file_size_mb:.2f} MB")
        
        # Commit changes
        conn.commit()
        print("\n✅ Database optimization completed successfully!")
        
        return True
        
    except Exception as e:
        print(f"❌ Database optimization failed: {e}")
        return False
        
    finally:
        if 'conn' in locals():
            conn.close()

def cleanup_old_data():
    """Clean up old crawl data to save space"""
    db_path = "amazon_crawler.db"
    
    if not os.path.exists(db_path):
        print(f"❌ Database not found: {db_path}")
        return False
    
    print("\n🧹 Cleaning up old crawl data...")
    print("="*50)
    
    try:
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        
        # Get current data counts
        cursor.execute("SELECT COUNT(*) FROM product_crawl_history")
        total_crawls = cursor.fetchone()[0]
        
        cursor.execute("SELECT COUNT(*) FROM products")
        total_products = cursor.fetchone()[0]
        
        print(f"📊 Current data:")
        print(f"   - Total crawl records: {total_crawls:,}")
        print(f"   - Total products: {total_products:,}")
        
        # Keep only last 30 days of crawl data for each product
        print("\n🗑️  Removing old crawl data (keeping last 30 days)...")
        
        cursor.execute("""
            DELETE FROM product_crawl_history 
            WHERE crawl_date < datetime('now', '-30 days')
        """)
        deleted_crawls = cursor.rowcount
        
        print(f"   ✅ Deleted {deleted_crawls:,} old crawl records")
        
        # Remove products with no crawl history
        print("\n🗑️  Removing products with no crawl history...")
        
        cursor.execute("""
            DELETE FROM products 
            WHERE id NOT IN (
                SELECT DISTINCT product_id 
                FROM product_crawl_history 
                WHERE product_id IS NOT NULL
            )
        """)
        deleted_products = cursor.rowcount
        
        print(f"   ✅ Deleted {deleted_products:,} orphaned products")
        
        # Vacuum to reclaim space
        cursor.execute("VACUUM")
        print("   ✅ Vacuumed database after cleanup")
        
        # Get final counts
        cursor.execute("SELECT COUNT(*) FROM product_crawl_history")
        final_crawls = cursor.fetchone()[0]
        
        cursor.execute("SELECT COUNT(*) FROM products")
        final_products = cursor.fetchone()[0]
        
        print(f"\n📊 After cleanup:")
        print(f"   - Crawl records: {final_crawls:,} (was {total_crawls:,})")
        print(f"   - Products: {final_products:,} (was {total_products:,})")
        
        # Database file size
        file_size = os.path.getsize(db_path)
        file_size_mb = file_size / (1024 * 1024)
        print(f"   - Database file size: {file_size_mb:.2f} MB")
        
        conn.commit()
        print("\n✅ Data cleanup completed successfully!")
        
        return True
        
    except Exception as e:
        print(f"❌ Data cleanup failed: {e}")
        return False
        
    finally:
        if 'conn' in locals():
            conn.close()

def main():
    """Main function"""
    print("🚀 Amazon Crawler - Database Optimization Tool")
    print("="*60)
    
    # Optimize database
    success1 = optimize_database()
    
    # Cleanup old data (optional)
    if success1:
        response = input("\n🧹 Do you want to clean up old crawl data? (y/N): ")
        if response.lower() in ['y', 'yes']:
            success2 = cleanup_old_data()
        else:
            success2 = True
            print("   Skipped data cleanup")
    else:
        success2 = False
    
    if success1 and success2:
        print("\n🎉 Database optimization completed successfully!")
        print("\n💡 Your database is now optimized for large-scale operations.")
        print("   You can now import and process 50k+ products efficiently.")
    else:
        print("\n❌ Database optimization failed. Please check the errors above.")
        sys.exit(1)

if __name__ == "__main__":
    main() 