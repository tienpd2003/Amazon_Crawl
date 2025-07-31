from fastapi import APIRouter, UploadFile, File, Form, HTTPException, BackgroundTasks
from fastapi.responses import JSONResponse
import asyncio
import os
import tempfile
from typing import List, Optional
import json

from utils.batch_import import import_from_file, import_from_list, get_import_stats
from utils.batch_import_optimized import import_from_file_optimized, import_from_list_optimized, get_import_stats as get_optimized_stats
from utils.logger import get_logger

logger = get_logger(__name__)

def serialize_for_json(obj):
    """Convert datetime objects to strings for JSON serialization"""
    try:
        if hasattr(obj, 'isoformat'):  # datetime objects
            return obj.isoformat()
        elif isinstance(obj, dict):
            return {key: serialize_for_json(value) for key, value in obj.items()}
        elif isinstance(obj, list):
            return [serialize_for_json(item) for item in obj]
        elif isinstance(obj, (str, int, float, bool, type(None))):
            return obj
        else:
            # For any other objects, convert to string
            return str(obj)
    except Exception as e:
        # If serialization fails, return string representation
        return str(obj)

router = APIRouter(prefix="/api/batch-import", tags=["batch-import"])

@router.get("/stats")
async def get_batch_import_stats():
    """Get batch import statistics"""
    try:
        stats = await get_import_stats()
        return JSONResponse(content=stats)
    except Exception as e:
        logger.error(f"Error getting batch import stats: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/upload")
async def upload_and_import(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    frequency: str = Form("daily"),
    notes: str = Form(""),
    column: Optional[str] = Form(None),
    optimized: bool = Form(False)
):
    """Upload file and import ASINs"""
    try:
        # Validate file type
        allowed_extensions = ['.csv', '.xlsx', '.xls', '.txt']
        file_ext = os.path.splitext(file.filename)[1].lower()
        
        if file_ext not in allowed_extensions:
            raise HTTPException(
                status_code=400, 
                detail=f"Invalid file type. Allowed: {', '.join(allowed_extensions)}"
            )
        
        # Save uploaded file temporarily
        with tempfile.NamedTemporaryFile(delete=False, suffix=file_ext) as temp_file:
            content = await file.read()
            temp_file.write(content)
            temp_file_path = temp_file.name
        
        try:
            # Prepare kwargs for import
            kwargs = {}
            if column:
                kwargs['asin_column'] = column
            
            # Import from file (original or optimized)
            if optimized:
                logger.info("Using OPTIMIZED batch import with concurrent processing")
                result = await import_from_file_optimized(temp_file_path, frequency, notes, **kwargs)
            else:
                logger.info("Using ORIGINAL batch import")
                result = await import_from_file(temp_file_path, frequency, notes, **kwargs)
            
            # Serialize result for JSON
            serializable_result = serialize_for_json(result)
            
            # Add file info to result
            serializable_result['file_name'] = file.filename
            serializable_result['file_size'] = len(content)
            
            logger.info(f"Batch import completed: {serializable_result}")
            return JSONResponse(content=serializable_result)
            
        finally:
            # Clean up temporary file
            if os.path.exists(temp_file_path):
                os.unlink(temp_file_path)
                
    except Exception as e:
        logger.error(f"Error in batch import upload: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/upload-optimized")
async def upload_and_import_optimized(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    frequency: str = Form("daily"),
    notes: str = Form(""),
    column: Optional[str] = Form(None),
    batch_size: str = Form("2")
):
    """Upload file and import ASINs with OPTIMIZED concurrent processing"""
    try:
        # Validate file type
        allowed_extensions = ['.csv', '.xlsx', '.xls', '.txt']
        file_ext = os.path.splitext(file.filename)[1].lower()
        
        if file_ext not in allowed_extensions:
            raise HTTPException(
                status_code=400, 
                detail=f"Invalid file type. Allowed: {', '.join(allowed_extensions)}"
            )
        
        # Save uploaded file temporarily
        with tempfile.NamedTemporaryFile(delete=False, suffix=file_ext) as temp_file:
            content = await file.read()
            temp_file.write(content)
            temp_file_path = temp_file.name
        
        try:
            # Prepare kwargs for import
            kwargs = {}
            if column:
                kwargs['asin_column'] = column
            
            # Convert batch_size to int and add to kwargs
            try:
                batch_size_int = int(batch_size)
                kwargs['batch_size'] = batch_size_int
                logger.info(f"Using OPTIMIZED batch import with batch_size={batch_size_int}")
            except ValueError:
                logger.warning(f"Invalid batch_size '{batch_size}', using default 2")
                kwargs['batch_size'] = 2
            
            # Import from file with OPTIMIZED processing
            result = await import_from_file_optimized(temp_file_path, frequency, notes, **kwargs)
            
            # Serialize result for JSON
            serializable_result = serialize_for_json(result)
            
            # Add file info to result
            serializable_result['file_name'] = file.filename
            serializable_result['file_size'] = len(content)
            serializable_result['batch_size'] = batch_size
            serializable_result['optimized'] = True
            
            logger.info(f"Optimized batch import completed: {serializable_result}")
            return JSONResponse(content=serializable_result)
            
        finally:
            # Clean up temporary file
            if os.path.exists(temp_file_path):
                os.unlink(temp_file_path)
                
    except Exception as e:
        logger.error(f"Error in optimized batch import upload: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/test")
async def test_import(
    file: UploadFile = File(...),
    column: Optional[str] = Form(None)
):
    """Test import without actually importing"""
    try:
        # Validate file type
        allowed_extensions = ['.csv', '.xlsx', '.xls', '.txt']
        file_ext = os.path.splitext(file.filename)[1].lower()
        
        if file_ext not in allowed_extensions:
            raise HTTPException(
                status_code=400, 
                detail=f"Invalid file type. Allowed: {', '.join(allowed_extensions)}"
            )
        
        # Save uploaded file temporarily
        with tempfile.NamedTemporaryFile(delete=False, suffix=file_ext) as temp_file:
            content = await file.read()
            temp_file.write(content)
            temp_file_path = temp_file.name
        
        try:
            from utils.batch_import import batch_importer
            
            # Prepare kwargs for test
            kwargs = {}
            if column:
                kwargs['asin_column'] = column
            
            # Extract ASINs without importing
            asins = batch_importer.extract_asins_from_file(temp_file_path, **kwargs)
            
            # Validate ASINs
            valid_asins = []
            invalid_asins = []
            
            for asin in asins:
                if batch_importer.validate_asin(asin):
                    valid_asins.append(asin)
                else:
                    invalid_asins.append(asin)
            
            # Remove duplicates
            unique_valid_asins = list(dict.fromkeys(valid_asins))
            
            result = {
                'file_name': file.filename,
                'file_size': len(content),
                'total_asins': len(asins),
                'valid_asins': len(unique_valid_asins),
                'invalid_asins': invalid_asins,
                'duplicates_removed': len(valid_asins) - len(unique_valid_asins),
                'sample_valid_asins': unique_valid_asins[:5] if unique_valid_asins else []
            }
            
            logger.info(f"Test import completed: {result}")
            return JSONResponse(content=result)
            
        finally:
            # Clean up temporary file
            if os.path.exists(temp_file_path):
                os.unlink(temp_file_path)
                
    except Exception as e:
        logger.error(f"Error in test import: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/quick")
async def quick_import(request: dict):
    """Quick import from ASIN list"""
    try:
        asins = request.get('asins', [])
        frequency = request.get('frequency', 'daily')
        notes = request.get('notes', 'Quick import')
        
        if not asins:
            raise HTTPException(status_code=400, detail="No ASINs provided")
        
        # Import from list
        result = await import_from_list(asins, frequency, notes)
        
        # Serialize result for JSON
        serializable_result = serialize_for_json(result)
        
        logger.info(f"Quick import completed: {serializable_result}")
        return JSONResponse(content=serializable_result)
        
    except Exception as e:
        logger.error(f"Error in quick import: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/manual")
async def manual_import(request: dict):
    """Manual import with custom settings"""
    try:
        asins = request.get('asins', [])
        frequency = request.get('frequency', 'daily')
        notes = request.get('notes', '')
        
        if not asins:
            raise HTTPException(status_code=400, detail="No ASINs provided")
        
        # Import from list
        result = await import_from_list(asins, frequency, notes)
        
        # Serialize result for JSON
        serializable_result = serialize_for_json(result)
        
        logger.info(f"Manual import completed: {serializable_result}")
        return JSONResponse(content=serializable_result)
        
    except Exception as e:
        logger.error(f"Error in manual import: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/status")
async def get_import_status():
    """Get current import status"""
    try:
        from scheduler.crawler_scheduler import crawler_scheduler
        
        status = {
            'scheduler_running': crawler_scheduler.is_running,
            'batch_size': crawler_scheduler.batch_size,
            'max_concurrent_crawlers': crawler_scheduler.max_concurrent_crawlers,
            'active_crawlers': crawler_scheduler.active_crawlers,
            'queue_size': crawler_scheduler.crawl_queue.qsize() if hasattr(crawler_scheduler, 'crawl_queue') else 0
        }
        
        # Serialize status for JSON
        serializable_status = serialize_for_json(status)
        
        return JSONResponse(content=serializable_status)
        
    except Exception as e:
        logger.error(f"Error getting import status: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/start-scheduler")
async def start_scheduler():
    """Start the crawler scheduler"""
    try:
        from scheduler.crawler_scheduler import start_scheduler
        await start_scheduler()
        
        logger.info("Scheduler started via API")
        return JSONResponse(content={"message": "Scheduler started successfully"})
        
    except Exception as e:
        logger.error(f"Error starting scheduler: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/stop-scheduler")
async def stop_scheduler():
    """Stop the crawler scheduler"""
    try:
        from scheduler.crawler_scheduler import stop_scheduler
        await stop_scheduler()
        
        logger.info("Scheduler stopped via API")
        return JSONResponse(content={"message": "Scheduler stopped successfully"})
        
    except Exception as e:
        logger.error(f"Error stopping scheduler: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/recent-imports")
async def get_recent_imports(limit: int = 10):
    """Get recent import history"""
    try:
        from database.connection import get_db_session
        from database.models import ASINWatchlist
        from sqlalchemy import desc
        
        session = get_db_session()
        
        # Get recent watchlist entries
        recent_imports = (
            session.query(ASINWatchlist)
            .filter_by(is_active=True)
            .order_by(desc(ASINWatchlist.added_date))
            .limit(limit)
            .all()
        )
        
        result = []
        for item in recent_imports:
            result.append({
                'asin': item.asin,
                'frequency': item.crawl_frequency,
                'notes': item.notes,
                'created_at': item.added_date.isoformat() if item.added_date else None,
                'last_crawled': item.last_crawled.isoformat() if item.last_crawled else None,
                'next_crawl': item.next_crawl.isoformat() if item.next_crawl else None
            })
        
        session.close()
        # Serialize result for JSON
        serializable_result = serialize_for_json(result)
        return JSONResponse(content=serializable_result)
        
    except Exception as e:
        logger.error(f"Error getting recent imports: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.delete("/remove-asin/{asin}")
async def remove_asin(asin: str):
    """Remove ASIN from watchlist"""
    try:
        from scheduler.crawler_scheduler import remove_asin_from_watchlist
        
        success = await remove_asin_from_watchlist(asin)
        
        if success:
            logger.info(f"ASIN {asin} removed from watchlist")
            return JSONResponse(content={"message": f"ASIN {asin} removed successfully"})
        else:
            raise HTTPException(status_code=404, detail=f"ASIN {asin} not found")
            
    except Exception as e:
        logger.error(f"Error removing ASIN {asin}: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/crawl-now/{asin}")
async def crawl_asin_now(asin: str):
    """Crawl a specific ASIN immediately"""
    try:
        from scheduler.crawler_scheduler import crawl_single_asin
        
        result = await crawl_single_asin(asin)
        
        logger.info(f"Manual crawl completed for {asin}: {result}")
        return JSONResponse(content=result)
        
    except Exception as e:
        logger.error(f"Error crawling ASIN {asin}: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/crawl/watchlist/now")
async def crawl_all_watchlist_now():
    """Crawl all active ASINs in watchlist immediately"""
    try:
        from scheduler.crawler_scheduler import crawler_scheduler
        
        # Get all active ASINs regardless of next_crawl time
        active_asins = crawler_scheduler._get_active_asins(include_all_active=True)
        
        if not active_asins:
            return JSONResponse(content={
                "message": "No active ASINs found in watchlist",
                "total_asins": 0,
                "crawled": 0
            })
        
        # Crawl all active ASINs
        total_asins = len(active_asins)
        crawled_count = 0
        
        for asin_data in active_asins:
            try:
                result = await crawler_scheduler.crawl_single_asin(asin_data.asin)
                if result.get('success', False):
                    crawled_count += 1
                    logger.info(f"Crawled ASIN {asin_data.asin} successfully")
                else:
                    logger.warning(f"Failed to crawl ASIN {asin_data.asin}: {result.get('error', 'Unknown error')}")
            except Exception as e:
                logger.error(f"Error crawling ASIN {asin_data.asin}: {e}")
        
        result = {
            "message": f"Crawled {crawled_count}/{total_asins} ASINs from watchlist",
            "total_asins": total_asins,
            "crawled": crawled_count,
            "failed": total_asins - crawled_count
        }
        
        logger.info(f"Watchlist crawl completed: {result}")
        return JSONResponse(content=result)
        
    except Exception as e:
        logger.error(f"Error crawling watchlist: {e}")
        raise HTTPException(status_code=500, detail=str(e)) 