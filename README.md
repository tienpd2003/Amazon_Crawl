# Amazon Crawler - Docker Setup

Ứng dụng crawler Amazon với giao diện web dashboard, được thiết kế để chạy trong Docker container.

## 🚀 Tính năng

- **Web Crawling**: Tự động crawl thông tin sản phẩm từ Amazon
- **Dashboard**: Giao diện web để theo dõi và quản lý
- **Scheduler**: Lên lịch crawl tự động
- **Database**: Lưu trữ dữ liệu với SQLite
- **Notifications**: Hỗ trợ thông báo qua Telegram và Discord
- **Batch Import**: Import danh sách sản phẩm từ file CSV

## 📋 Yêu cầu hệ thống

- Docker
- Docker Compose
- Ít nhất 2GB RAM
- 10GB dung lượng ổ cứng

## 🐳 Cài đặt và chạy với Docker

### 1. Clone repository

```bash
git clone <repository-url>
cd CrawlAmazon
```

### 2. Cấu hình môi trường (Tùy chọn)

Tạo file `.env` để tùy chỉnh cấu hình:

```bash
# Copy template
cp env_template.txt .env

# Chỉnh sửa file .env theo nhu cầu
```

### 3. Chạy ứng dụng

```bash
# Build và chạy container
docker-compose up -d

# Xem logs
docker-compose logs -f

# Dừng ứng dụng
docker-compose down
```

### 4. Truy cập ứng dụng

Mở trình duyệt và truy cập: `http://localhost:8000`

## ⚙️ Cấu hình Docker

### Ports
- **8000**: Dashboard web interface

### Volumes
- `./amazon_crawler.db`: Database file
- `./data`: Thư mục chứa dữ liệu (images, videos, exports)
- `./logs`: Log files
- `./cookies`: Cookie files

### Environment Variables

| Biến | Mô tả | Giá trị mặc định |
|------|-------|------------------|
| `DATABASE_URL` | URL kết nối database | `sqlite:///./amazon_crawler.db` |
| `CRAWLER_DELAY` | Độ trễ giữa các request (giây) | `3` |
| `MAX_RETRIES` | Số lần thử lại tối đa | `3` |
| `TIMEOUT` | Timeout cho request (giây) | `30` |
| `SCHEDULER_TIMEZONE` | Múi giờ cho scheduler | `Asia/Ho_Chi_Minh` |
| `DAILY_CRAWL_TIME` | Thời gian crawl hàng ngày | `09:00` |
| `HEADLESS_BROWSER` | Chạy browser ẩn | `true` |
| `BROWSER_TYPE` | Loại browser | `chrome` |
| `REQUESTS_PER_MINUTE` | Số request tối đa/phút | `10` |
| `CONCURRENT_REQUESTS` | Số request đồng thời | `1` |

## 🔧 Lệnh Docker hữu ích

```bash
# Xem trạng thái container
docker-compose ps

# Restart container
docker-compose restart

# Xem logs real-time
docker-compose logs -f amazon-crawler

# Xem logs của 100 dòng cuối
docker-compose logs --tail=100 amazon-crawler

# Vào container để debug
docker-compose exec amazon-crawler bash

# Backup database
docker-compose exec amazon-crawler cp amazon_crawler.db amazon_crawler.db.backup

# Xóa container và volumes (cẩn thận!)
docker-compose down -v
```

## 📊 Monitoring

### Health Check
Container có health check tự động kiểm tra endpoint `/` mỗi 30 giây.

### Logs
Logs được lưu trong thư mục `./logs` và có thể xem qua:
```bash
docker-compose logs -f
```

## 🚨 Troubleshooting

### Container không start
```bash
# Kiểm tra logs
docker-compose logs amazon-crawler

# Kiểm tra port có bị conflict không
netstat -an | grep 8000
```

### Database issues
```bash
# Backup database hiện tại
cp amazon_crawler.db amazon_crawler.db.backup

# Restart container
docker-compose restart
```

### Permission issues
```bash
# Fix permissions cho volumes
sudo chown -R $USER:$USER data/ logs/ cookies/
```

### Browser issues
```bash
# Rebuild container
docker-compose down
docker-compose build --no-cache
docker-compose up -d
```

## 📁 Cấu trúc thư mục

```
CrawlAmazon/
├── docker-compose.yml    # Docker configuration
├── Dockerfile           # Container build file
├── requirements.txt     # Python dependencies
├── main.py             # Application entry point
├── amazon_crawler.db   # SQLite database
├── data/               # Crawled data
│   ├── images/         # Product images
│   ├── videos/         # Product videos
│   └── exports/        # Exported data
├── logs/               # Application logs
└── cookies/            # Browser cookies
```

## 🔐 Bảo mật

- Không commit file `.env` chứa thông tin nhạy cảm
- Sử dụng volume để persist data thay vì copy vào container
- Health check giúp phát hiện container bị lỗi

## 📞 Hỗ trợ

Nếu gặp vấn đề, vui lòng:
1. Kiểm tra logs: `docker-compose logs -f`
2. Kiểm tra trạng thái container: `docker-compose ps`
3. Restart container: `docker-compose restart`

## 📝 License

[Thêm thông tin license của dự án] 