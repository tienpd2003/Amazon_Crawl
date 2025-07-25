import sqlite3
from datetime import datetime, timedelta

ASIN = 'TEST123456'
DB_PATH = 'amazon_crawler.db'

conn = sqlite3.connect(DB_PATH)
cursor = conn.cursor()

# Thêm sản phẩm nếu chưa có
cursor.execute("SELECT id FROM products WHERE asin=?", (ASIN,))
row = cursor.fetchone()
if row:
    product_id = row[0]
else:
    cursor.execute("INSERT INTO products (asin, created_at, updated_at, is_active) VALUES (?, ?, ?, 1)", (ASIN, datetime.utcnow(), datetime.utcnow()))
    product_id = cursor.lastrowid

# Thêm vào asin_watchlist nếu chưa có
cursor.execute("SELECT id FROM asin_watchlist WHERE asin=?", (ASIN,))
if not cursor.fetchone():
    cursor.execute("INSERT INTO asin_watchlist (asin, added_date, is_active, crawl_frequency) VALUES (?, ?, 1, 'daily')", (ASIN, datetime.utcnow()))

# Xoá các bản ghi cũ của asin này trong product_crawl_history (nếu cần)
cursor.execute("DELETE FROM product_crawl_history WHERE asin=?", (ASIN,))

# Thêm bản ghi hôm qua
crawl_date_yesterday = (datetime.utcnow() - timedelta(days=1)).replace(hour=10, minute=0, second=0, microsecond=0)
cursor.execute('''
INSERT INTO product_crawl_history (
    product_id, asin, crawl_date, title, sale_price, list_price, rating, rating_count, inventory, crawl_success
) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 1)
''', (
    product_id, ASIN, crawl_date_yesterday, 'Sản phẩm test', 100.0, 120.0, 4.5, 100, 'Còn hàng',
))

# Thêm bản ghi hôm nay (thay đổi sale_price, rating, inventory)
crawl_date_today = datetime.utcnow().replace(hour=10, minute=0, second=0, microsecond=0)
cursor.execute('''
INSERT INTO product_crawl_history (
    product_id, asin, crawl_date, title, sale_price, list_price, rating, rating_count, inventory, crawl_success
) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 1)
''', (
    product_id, ASIN, crawl_date_today, 'Sản phẩm test', 90.0, 120.0, 4.7, 100, 'Hết hàng',
))

conn.commit()
conn.close()
print('Đã chèn dữ liệu test cho ASIN', ASIN) 