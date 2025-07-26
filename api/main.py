import asyncio
from datetime import datetime, timedelta
from typing import List, Optional, Dict, Any
from pathlib import Path

from fastapi import FastAPI, HTTPException, Depends, BackgroundTasks, Request
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from fastapi.responses import HTMLResponse, JSONResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session

from config.settings import settings
from database.connection import get_db, get_db_session
from database.models import (
    Product, ProductCrawlHistory, ASINWatchlist, 
    NotificationLog
)
from scheduler.crawler_scheduler import (
    crawler_scheduler, start_scheduler, stop_scheduler,
    crawl_asin_now, add_asin, remove_asin
)
from crawler.change_detector import ChangeDetector
from utils.logger import get_logger

logger = get_logger(__name__)

app = FastAPI(
    title="Amazon Product Crawler",
    description="API cho hệ thống crawl và theo dõi sản phẩm Amazon",
    version="1.0.0"
)

# Create templates directory and static files
templates_dir = Path("templates")
static_dir = Path("static")
templates_dir.mkdir(exist_ok=True)
static_dir.mkdir(exist_ok=True)

templates = Jinja2Templates(directory="templates")
app.mount("/static", StaticFiles(directory="static"), name="static")

# Pydantic models
class ASINRequest(BaseModel):
    asin: str
    frequency: str = "daily"
    notes: str = ""

class NotificationConfig(BaseModel):
    notification_type: str
    enabled: bool
    config: Dict[str, Any]

class ProductResponse(BaseModel):
    asin: str
    title: Optional[str]
    sale_price: Optional[float]
    list_price: Optional[float]
    rating: Optional[float]
    rating_count: Optional[int]
    inventory_status: Optional[str]
    last_crawled: Optional[datetime]
    
class DashboardStats(BaseModel):
    total_products: int
    active_watchlist: int
    successful_crawls_today: int
    failed_crawls_today: int
    avg_crawl_time: float
    recent_changes: int

# Startup event
@app.on_event("startup")
async def startup_event():
    """Initialize application"""
    try:
        # Initialize database
        from database.connection import create_tables, init_default_settings
        create_tables()
        init_default_settings()
        
        # Start scheduler
        await start_scheduler()
        logger.info("Application started successfully")
        
    except Exception as e:
        logger.error(f"Failed to start application: {e}")
        raise

# Shutdown event
@app.on_event("shutdown")
async def shutdown_event():
    """Cleanup on shutdown"""
    try:
        await stop_scheduler()
        logger.info("Application shutdown completed")
    except Exception as e:
        logger.error(f"Error during shutdown: {e}")

# Dashboard Routes
@app.get("/", response_class=HTMLResponse)
async def dashboard(request: Request):
    """Main dashboard page"""
    return templates.TemplateResponse("dashboard.html", {"request": request})

@app.get("/products", response_class=HTMLResponse)
async def products_page(request: Request):
    """Products management page"""
    return templates.TemplateResponse("products.html", {"request": request})

@app.get("/notifications", response_class=HTMLResponse)
async def notifications_page(request: Request):
    """Notifications settings page"""
    return templates.TemplateResponse("notifications.html", {"request": request})

@app.get("/settings", response_class=HTMLResponse)
async def settings_page(request: Request):
    """Settings page"""
    return templates.TemplateResponse("settings.html", {"request": request})

@app.get("/price-tracking", response_class=HTMLResponse)
async def price_tracking_page(request: Request):
    """Price tracking dashboard page"""
    return templates.TemplateResponse("price_tracking.html", {"request": request})

# API Routes
@app.get("/api/dashboard/stats")
async def get_dashboard_stats(db: Session = Depends(get_db)) -> DashboardStats:
    """Get dashboard statistics"""
    try:
        # Total products
        total_products = db.query(Product).count()
        
        # Active watchlist
        active_watchlist = db.query(ASINWatchlist).filter_by(is_active=True).count()
        
        # Today's stats
        today = datetime.utcnow().date()
        today_start = datetime.combine(today, datetime.min.time())
        today_end = datetime.combine(today, datetime.max.time())
        
        # Recent changes (last 24 hours)
        yesterday = datetime.utcnow() - timedelta(days=1)
        
        today_crawls = db.query(ProductCrawlHistory).filter(
            ProductCrawlHistory.crawl_date >= today_start,
            ProductCrawlHistory.crawl_date <= today_end
        ).all()
        
        successful_today = len([c for c in today_crawls if c.crawl_success])
        failed_today = len([c for c in today_crawls if not c.crawl_success])
        
        # Average crawl time (not available, set to 0)
        avg_crawl_time = 0
        
        recent_notifications = db.query(NotificationLog).filter(
            NotificationLog.sent_at >= yesterday
        ).count()
        
        return DashboardStats(
            total_products=total_products,
            active_watchlist=active_watchlist,
            successful_crawls_today=successful_today,
            failed_crawls_today=failed_today,
            avg_crawl_time=avg_crawl_time,
            recent_changes=recent_notifications
        )
        
    except Exception as e:
        logger.error(f"Error getting dashboard stats: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/products")
async def get_products(
    page: int = 1, 
    limit: int = 50,
    search: Optional[str] = None,
    db: Session = Depends(get_db)
):
    """Get products with pagination"""
    try:
        offset = (page - 1) * limit
        
        # Base query
        query = db.query(Product).filter_by(is_active=True)
        
        # Search filter
        if search:
            query = query.join(ProductCrawlHistory).filter(
                ProductCrawlHistory.title.contains(search) |
                Product.asin.contains(search)
            )
        
        # Get total count
        total = query.count()
        
        # Get products with latest data
        products = query.offset(offset).limit(limit).all()
        
        # Format response
        product_list = []
        for product in products:
            # Get latest crawl data
            latest_crawl = db.query(ProductCrawlHistory).filter_by(
                product_id=product.id,
                crawl_success=True
            ).order_by(ProductCrawlHistory.crawl_date.desc()).first()
            
            # Get watchlist status
            watchlist_item = db.query(ASINWatchlist).filter_by(asin=product.asin).first()
            is_active = watchlist_item.is_active if watchlist_item else None
            
            if latest_crawl:
                product_data = {
                    "id": product.id,
                    "asin": product.asin,
                    "title": latest_crawl.title,
                    "sale_price": latest_crawl.sale_price,
                    "list_price": latest_crawl.list_price,
                    "rating": latest_crawl.rating,
                    "rating_count": latest_crawl.rating_count,
                    "inventory_status": latest_crawl.inventory,  # FIXED: was inventory_status
                    "amazon_choice": latest_crawl.amazon_choice,
                    "last_crawled": latest_crawl.crawl_date,
                    "created_at": product.created_at,
                    "is_active": is_active
                }
            else:
                product_data = {
                    "id": product.id,
                    "asin": product.asin,
                    "title": None,
                    "sale_price": None,
                    "list_price": None,
                    "rating": None,
                    "rating_count": None,
                    "inventory_status": None,
                    "amazon_choice": False,
                    "last_crawled": None,
                    "created_at": product.created_at,
                    "is_active": is_active
                }
            
            product_list.append(product_data)
        
        return {
            "products": product_list,
            "total": total,
            "page": page,
            "limit": limit,
            "pages": (total + limit - 1) // limit
        }
        
    except Exception as e:
        logger.error(f"Error getting products: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/products/stats")
async def get_products_stats(db: Session = Depends(get_db)):
    """Get product statistics for management page"""
    try:
        total_products = db.query(Product).count()
        active_watchlist = db.query(ASINWatchlist).filter_by(is_active=True).count()
        inactive_watchlist = db.query(ASINWatchlist).filter_by(is_active=False).count()
        # Sản phẩm không nằm trong watchlist
        subq = db.query(ASINWatchlist.asin)
        not_in_watchlist = db.query(Product).filter(~Product.asin.in_(subq)).count()
        return {
            "total_products": total_products,
            "active_watchlist": active_watchlist,
            "inactive_watchlist": inactive_watchlist,
            "not_in_watchlist": not_in_watchlist
        }
    except Exception as e:
        logger.error(f"Error getting product stats: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/products/list")
async def get_products_list(db: Session = Depends(get_db)):
    """Get list of all products for dropdown"""
    try:
        logger.info("Starting get_products_list API call")
        
        # Get all unique ASINs with their latest title - no limit
        from sqlalchemy import func
        
        # Get latest crawl for each ASIN
        subquery = db.query(
            ProductCrawlHistory.asin,
            func.max(ProductCrawlHistory.crawl_date).label('max_date')
        ).filter(
            ProductCrawlHistory.title != None,
            ProductCrawlHistory.title != "",
            ProductCrawlHistory.crawl_success == True
        ).group_by(ProductCrawlHistory.asin).subquery()
        
        # Join back to get the titles
        products = db.query(ProductCrawlHistory.asin, ProductCrawlHistory.title)\
            .join(subquery, 
                  (ProductCrawlHistory.asin == subquery.c.asin) & 
                  (ProductCrawlHistory.crawl_date == subquery.c.max_date))\
            .all()
        
        logger.info(f"Found {len(products)} unique ASINs from database")
        
        product_list = [{"asin": asin, "title": title[:50] + "..." if len(title) > 50 else title} 
                       for asin, title in products]
        
        logger.info(f"Returning {len(product_list)} products")
        
        return {
            "products": product_list,
            "total": len(product_list)
        }
        
    except Exception as e:
        logger.error(f"Error getting products list: {e}")
        import traceback
        logger.error(f"Traceback: {traceback.format_exc()}")
        raise HTTPException(status_code=500, detail=f"Database error: {str(e)}")

@app.get("/api/products/{asin}")
async def get_product_details(asin: str, db: Session = Depends(get_db)):
    """Get detailed product information"""
    try:
        product = db.query(Product).filter_by(asin=asin).first()
        if not product:
            raise HTTPException(status_code=404, detail="Product not found")
        
        # Get all crawl history
        crawl_history = db.query(ProductCrawlHistory).filter_by(
            product_id=product.id
        ).order_by(ProductCrawlHistory.crawl_date.desc()).limit(30).all()
        
        # Get latest successful crawl
        latest_crawl = next((c for c in crawl_history if c.crawl_success), None)
        
        # Get change history
        detector = ChangeDetector()
        try:
            change_history = detector.get_change_history(asin, days=30)
        finally:
            detector.close()
        
        return {
            "product": {
                "id": product.id,
                "asin": product.asin,
                "created_at": product.created_at,
                "updated_at": product.updated_at
            },
            "latest_data": latest_crawl.__dict__ if latest_crawl else None,
            "crawl_history": [c.__dict__ for c in crawl_history],
            "change_history": change_history
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting product details for {asin}: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/products/add")
async def add_product(request: ASINRequest, background_tasks: BackgroundTasks):
    """Add ASIN to watchlist and crawl immediately if needed"""
    try:
        # Validate ASIN format (should be 10 characters)
        if not request.asin or len(request.asin) != 10:
            raise HTTPException(status_code=400, detail="Invalid ASIN format")
        
        # Add to watchlist (có thể trả về: 'added', 'added_no_crawl', 'reactivated', 'exists', 'error')
        result = await add_asin(request.asin, request.frequency, request.notes)
        if result == 'exists':
            raise HTTPException(status_code=400, detail="ASIN already exists or failed to add")
        if result == 'reactivated':
            return {"message": f"ASIN {request.asin} re-activated in watchlist", "asin": request.asin}
        if result == 'added_no_crawl':
            return {"message": f"ASIN {request.asin} đã có dữ liệu, chỉ thêm vào watchlist, không crawl lại", "asin": request.asin}
        if result == 'added':
            # Trigger immediate crawl in background
            background_tasks.add_task(crawl_asin_now, request.asin)
            return {"message": f"ASIN {request.asin} added successfully and crawl started", "asin": request.asin}
        raise HTTPException(status_code=500, detail="Unknown error when adding ASIN")
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error adding ASIN {request.asin}: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.delete("/api/products/{asin}")
async def remove_product(asin: str):
    """Remove ASIN from watchlist"""
    try:
        success = await remove_asin(asin)
        if not success:
            raise HTTPException(status_code=404, detail="ASIN not found")
        
        return {"message": f"ASIN {asin} removed successfully"}
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error removing ASIN {asin}: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/products/{asin}/crawl")
async def manual_crawl(asin: str, background_tasks: BackgroundTasks):
    """Trigger manual crawl for specific ASIN"""
    try:
        # Start crawl in background
        background_tasks.add_task(crawl_asin_now, asin)
        
        return {"message": f"Manual crawl started for ASIN {asin}"}
        
    except Exception as e:
        logger.error(f"Error starting manual crawl for {asin}: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/products/{asin}/detailed-comparison")
async def get_product_detailed_comparison(asin: str, db: Session = Depends(get_db)):
    """Get latest detailed product data"""
    try:
        # Get latest successful crawl
        latest_crawl = (
            db.query(ProductCrawlHistory)
            .filter_by(asin=asin, crawl_success=True)
            .order_by(ProductCrawlHistory.crawl_date.desc())
            .first()
        )
        
        # Get watchlist info
        watchlist_item = db.query(ASINWatchlist).filter_by(asin=asin).first()
        
        if not latest_crawl:
            return {
                "asin": asin,
                "data": None,
                "is_in_watchlist": watchlist_item is not None,
                "is_active": watchlist_item.is_active if watchlist_item else None,
                "message": "Chưa có dữ liệu crawl cho ASIN này"
            }
        
        return {
            "asin": asin,
            "data": {
                "crawl_date": latest_crawl.crawl_date,
                "title": latest_crawl.title,
                "product_description": latest_crawl.product_description,
                "product_information": latest_crawl.product_information,
                "about_this_item": latest_crawl.about_this_item,
                "sale_price": latest_crawl.sale_price,
                "list_price": latest_crawl.list_price,
                "sale_percentage": latest_crawl.sale_percentage,
                "rating": latest_crawl.rating,
                "rating_count": latest_crawl.rating_count,
                "inventory": latest_crawl.inventory,
                "image_count": latest_crawl.image_count,
                "image_urls": latest_crawl.image_urls,
                "video_count": latest_crawl.video_count,
                "video_urls": latest_crawl.video_urls,
                "best_deal": latest_crawl.best_deal,
                "lightning_deal": latest_crawl.lightning_deal,
                "coupon": latest_crawl.coupon,
                "bag_sale": latest_crawl.bag_sale,
                "amazon_choice": latest_crawl.amazon_choice,
                "advertised_asins": latest_crawl.advertised_asins,
                "brand_store_link": latest_crawl.brand_store_link,
                "sold_by_link": latest_crawl.sold_by_link
            },
            "is_in_watchlist": watchlist_item is not None,
            "is_active": watchlist_item.is_active if watchlist_item else None
        }
        
    except Exception as e:
        logger.error(f"Error getting detailed data for {asin}: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.put("/api/watchlist/{asin}/toggle")
async def toggle_watchlist_status(asin: str, db: Session = Depends(get_db)):
    """Toggle active status of ASIN in watchlist (pause/resume monitoring)"""
    try:
        watchlist_item = db.query(ASINWatchlist).filter_by(asin=asin).first()
        if not watchlist_item:
            raise HTTPException(status_code=404, detail="ASIN not found in watchlist")
        
        # Toggle active status
        watchlist_item.is_active = not watchlist_item.is_active
        db.commit()
        
        status_text = "resumed" if watchlist_item.is_active else "paused"
        
        return {
            "message": f"ASIN {asin} monitoring {status_text}",
            "asin": asin,
            "is_active": watchlist_item.is_active
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error toggling watchlist status for {asin}: {e}")
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/watchlist/{asin}/add")
async def add_to_watchlist(asin: str, db: Session = Depends(get_db)):
    """Add an existing product to the watchlist (for products already crawled but not in watchlist)"""
    try:
        # Kiểm tra đã có trong watchlist chưa
        watchlist_item = db.query(ASINWatchlist).filter_by(asin=asin).first()
        if watchlist_item:
            if watchlist_item.is_active:
                return {"message": f"ASIN {asin} đã nằm trong watchlist và đang active"}
            else:
                watchlist_item.is_active = True
                db.commit()
                return {"message": f"ASIN {asin} đã được kích hoạt lại trong watchlist"}
        # Kiểm tra đã có dữ liệu crawl chưa
        from database.models import ProductCrawlHistory
        has_crawled = db.query(ProductCrawlHistory).filter_by(asin=asin, crawl_success=True).first()
        if not has_crawled:
            raise HTTPException(status_code=400, detail="ASIN chưa có dữ liệu crawl, không thể thêm vào watchlist")
        # Thêm mới vào watchlist
        new_item = ASINWatchlist(asin=asin, crawl_frequency="daily", is_active=True, next_crawl=datetime.utcnow())
        db.add(new_item)
        db.commit()
        return {"message": f"ASIN {asin} đã được thêm vào watchlist"}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error adding ASIN {asin} to watchlist: {e}")
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/watchlist")
async def get_watchlist(active_only: bool = False, db: Session = Depends(get_db)):
    """Get ASIN watchlist"""
    try:
        from database.models import ProductCrawlHistory
        from datetime import datetime, timedelta, time
        if active_only:
            watchlist = db.query(ASINWatchlist).filter_by(is_active=True).all()
        else:
            watchlist = db.query(ASINWatchlist).all()
        today = datetime.utcnow().date()
        start_today = datetime.combine(today, time.min)
        end_today = datetime.combine(today, time.max)
        yesterday = today - timedelta(days=1)
        start_yesterday = datetime.combine(yesterday, time.min)
        end_yesterday = datetime.combine(yesterday, time.max)
        compare_fields = [
            'title', 'product_description', 'product_information', 'about_this_item',
            'image_count', 'image_urls', 'video_count', 'video_urls',
            'sale_price', 'list_price', 'sale_percentage',
            'best_deal', 'lightning_deal', 'coupon', 'bag_sale',
            'rating', 'rating_count',
            'brand_store_link', 'sold_by_link',
            'advertised_asins', 'amazon_choice', 'inventory'
        ]
        result = []
        for item in watchlist:
            # Lấy bản ghi hôm nay (gần nhất trong ngày hôm nay)
            crawl_today = db.query(ProductCrawlHistory).filter(
                ProductCrawlHistory.asin == item.asin,
                ProductCrawlHistory.crawl_date >= start_today,
                ProductCrawlHistory.crawl_date <= end_today,
                ProductCrawlHistory.crawl_success == True
            ).order_by(ProductCrawlHistory.crawl_date.desc()).first()
            # Lấy bản ghi hôm qua (gần nhất trong ngày hôm qua)
            crawl_yesterday = db.query(ProductCrawlHistory).filter(
                ProductCrawlHistory.asin == item.asin,
                ProductCrawlHistory.crawl_date >= start_yesterday,
                ProductCrawlHistory.crawl_date <= end_yesterday,
                ProductCrawlHistory.crawl_success == True
            ).order_by(ProductCrawlHistory.crawl_date.desc()).first()
            change_count_today = 0
            if crawl_today and crawl_yesterday:
                for field in compare_fields:
                    v_today = getattr(crawl_today, field, None)
                    v_yesterday = getattr(crawl_yesterday, field, None)
                    if v_today != v_yesterday:
                        change_count_today += 1
            last_update_date = crawl_today.crawl_date.strftime('%d/%m/%Y') if crawl_today else None
            result.append({
                "id": item.id,
                "asin": item.asin,
                "frequency": item.crawl_frequency,
                "is_active": item.is_active,
                "added_date": item.added_date,
                "last_crawled": item.last_crawled,
                "next_crawl": item.next_crawl,
                "notes": item.notes,
                "change_count_today": change_count_today,
                "last_update_date": last_update_date
            })
        return {"watchlist": result}
    except Exception as e:
        logger.error(f"Error getting watchlist: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/watchlist/change-detail")
async def get_watchlist_change_detail(asin: str, db: Session = Depends(get_db)):
    """Trả về chi tiết các trường đã thay đổi hôm nay so với hôm qua cho ASIN"""
    try:
        from crawler.change_detector import ChangeDetector
        from datetime import datetime, time, timedelta
        detector = ChangeDetector()
        today = datetime.utcnow().date()
        start_today = datetime.combine(today, time.min)
        end_today = datetime.combine(today, time.max)
        # Lấy bản ghi hôm nay
        crawl_today = db.query(ProductCrawlHistory).filter(
            ProductCrawlHistory.asin == asin,
            ProductCrawlHistory.crawl_date >= start_today,
            ProductCrawlHistory.crawl_date <= end_today,
            ProductCrawlHistory.crawl_success == True
        ).order_by(ProductCrawlHistory.crawl_date.desc()).first()
        # Lấy bản ghi hôm qua
        yesterday = today - timedelta(days=1)
        start_yesterday = datetime.combine(yesterday, time.min)
        end_yesterday = datetime.combine(yesterday, time.max)
        crawl_yesterday = db.query(ProductCrawlHistory).filter(
            ProductCrawlHistory.asin == asin,
            ProductCrawlHistory.crawl_date >= start_yesterday,
            ProductCrawlHistory.crawl_date <= end_yesterday,
            ProductCrawlHistory.crawl_success == True
        ).order_by(ProductCrawlHistory.crawl_date.desc()).first()
        if not crawl_today or not crawl_yesterday:
            return {"changes": {}}
        # So sánh từng trường
        changes = {}
        for field in detector.monitored_fields.keys():
            v_today = getattr(crawl_today, field, None)
            v_yesterday = getattr(crawl_yesterday, field, None)
            if v_today != v_yesterday:
                changes[field] = {"old": v_yesterday, "new": v_today}
        return {"changes": changes}
    except Exception as e:
        logger.error(f"Error getting change detail for {asin}: {e}")
        raise HTTPException(status_code=500, detail=str(e))

# @app.get("/api/notifications/settings")
# async def get_notification_settings(db: Session = Depends(get_db)):
#     """Get notification settings - MOVED TO .ENV CONFIG"""
#     # Notification settings are now managed via .env file
#     return {"message": "Notification settings are now managed via .env file"}

# @app.put("/api/notifications/settings/{setting_id}")
# async def update_notification_setting(
#     setting_id: int, 
#     config: NotificationConfig,
#     db: Session = Depends(get_db)
# ):
#     """Update notification settings - MOVED TO .ENV CONFIG"""
#     # Notification settings are now managed via .env file
#     return {"message": "Notification settings are now managed via .env file"}

@app.get("/api/scheduler/status")
async def get_scheduler_status():
    """Get scheduler status"""
    try:
        status = crawler_scheduler.get_scheduler_status()
        return status
        
    except Exception as e:
        logger.error(f"Error getting scheduler status: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/logs/notifications")
async def get_notification_logs(
    page: int = 1,
    limit: int = 50,
    db: Session = Depends(get_db)
):
    """Get notification logs"""
    try:
        offset = (page - 1) * limit
        
        logs = db.query(NotificationLog).order_by(
            NotificationLog.sent_at.desc()
        ).offset(offset).limit(limit).all()
        
        total = db.query(NotificationLog).count()
        
        return {
            "logs": [
                {
                    "id": log.id,
                    "product_id": log.product_id,
                    "type": log.notification_type,
                    "message": log.message,
                    "sent_at": log.sent_at,
                    "success": log.success,
                    "error": log.error_message
                }
                for log in logs
            ],
            "total": total,
            "page": page,
            "limit": limit
        }
        
    except Exception as e:
        logger.error(f"Error getting notification logs: {e}")
        raise HTTPException(status_code=500, detail=str(e))

# @app.get("/api/stats/crawl")
# async def get_crawl_stats(days: int = 7, db: Session = Depends(get_db)):
#     """Get crawl statistics - DISABLED (CrawlStats table removed)"""
#     # CrawlStats functionality moved to direct calculation from ProductCrawlHistory
#     return {"message": "Crawl stats moved to dashboard calculations"}

# Price History API
@app.get("/api/price-history/{asin}")
async def get_price_history(asin: str, days: int = 30, db: Session = Depends(get_db)):
    """Get price history for an ASIN"""
    try:
        # Get price history for the last N days
        from_date = datetime.utcnow() - timedelta(days=days)
        
        price_history = db.query(ProductCrawlHistory)\
            .filter(ProductCrawlHistory.asin == asin)\
            .filter(ProductCrawlHistory.crawl_date >= from_date)\
            .filter(ProductCrawlHistory.sale_price.isnot(None))\
            .order_by(ProductCrawlHistory.crawl_date.asc())\
            .all()
        
        if not price_history:
            raise HTTPException(status_code=404, detail="No price history found for this ASIN")
        
        # Process data for chart
        chart_data = []
        prices = []
        
        for record in price_history:
            chart_data.append({
                "date": record.crawl_date.strftime("%Y-%m-%d"),
                "price": float(record.sale_price) if record.sale_price else 0,
                "list_price": float(record.list_price) if record.list_price else 0,
                "title": record.title
            })
            if record.sale_price:
                prices.append(float(record.sale_price))
        
        # Calculate statistics
        current_price = prices[-1] if prices else 0
        min_price = min(prices) if prices else 0
        max_price = max(prices) if prices else 0
        
        # Find min/max dates
        min_date = ""
        max_date = ""
        for record in price_history:
            if record.sale_price and float(record.sale_price) == min_price:
                min_date = record.crawl_date.strftime("%d-%m-%Y")
            if record.sale_price and float(record.sale_price) == max_price:
                max_date = record.crawl_date.strftime("%d-%m-%Y")
        
        return {
            "asin": asin,
            "current_price": current_price,
            "min_price": min_price,
            "max_price": max_price,
            "min_date": min_date,
            "max_date": max_date,
            "chart_data": chart_data,
            "total_records": len(chart_data)
        }
        
    except Exception as e:
        logger.error(f"Error getting price history: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/crawl/watchlist/now")
async def crawl_all_watchlist_now(background_tasks: BackgroundTasks):
    from scheduler.crawler_scheduler import crawler_scheduler
    background_tasks.add_task(crawler_scheduler.daily_crawl_job)
    return {"message": "Đã bắt đầu crawl toàn bộ ASIN trong watchlist!"}

# Health check
@app.get("/health")
async def health_check():
    """Health check endpoint"""
    return {
        "status": "healthy",
        "timestamp": datetime.utcnow(),
        "scheduler_running": crawler_scheduler.is_running
    }

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "api.main:app",
        host=settings.DASHBOARD_HOST,
        port=settings.DASHBOARD_PORT,
        reload=True
    ) 