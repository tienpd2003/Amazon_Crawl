from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, Session
from sqlalchemy.ext.declarative import declarative_base
from config.settings import settings
from database.models import Base
import os

# Create database engine
engine = create_engine(
    settings.DATABASE_URL,
    echo=False,  # Set to True for SQL debugging
    pool_pre_ping=True,
)

# Create session factory
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

def get_database_url():
    """Get the database URL"""
    return settings.DATABASE_URL

def get_db_session():
    """Get a database session"""
    # Use the same engine as the main application
    return SessionLocal()

def create_tables():
    """Create all database tables"""
    # Create data directories if they don't exist
    os.makedirs(settings.IMAGE_STORAGE_PATH, exist_ok=True)
    os.makedirs(settings.VIDEO_STORAGE_PATH, exist_ok=True)
    os.makedirs(settings.EXCEL_EXPORT_PATH, exist_ok=True)
    
    # Create all tables
    Base.metadata.create_all(bind=engine)
    print("Database tables created successfully!")

def get_db() -> Session:
    """Get database session"""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

def init_default_settings():
    """Initialize default settings in the database"""
    db = get_db_session()
    try:
        from database.models import NotificationSettings, UserSettings
        
        # Check if notification settings already exist
        existing_telegram = db.query(NotificationSettings).filter_by(notification_type="telegram").first()
        if not existing_telegram:
            # Create default notification settings
            telegram_settings = NotificationSettings(
                notification_type="telegram",
                enabled=False,
                config={
                    "bot_token": "",
                    "chat_id": ""
                }
            )
            db.add(telegram_settings)
            
            discord_settings = NotificationSettings(
                notification_type="discord",
                enabled=False,
                config={
                    "webhook_url": ""
                }
            )
            db.add(discord_settings)
            
            email_settings = NotificationSettings(
                notification_type="email",
                enabled=False,
                config={
                    "smtp_server": "",
                    "smtp_port": 587,
                    "username": "",
                    "password": "",
                    "recipients": []
                }
            )
            db.add(email_settings)
        
        # Create default user settings
        default_settings = [
            ("crawler_delay", "3", "Delay between requests in seconds"),
            ("max_retries", "3", "Maximum number of retry attempts"),
            ("timeout", "30", "Request timeout in seconds"),
            ("headless_browser", "true", "Run browser in headless mode"),
            ("daily_crawl_time", "09:00", "Daily crawl time (HH:MM)"),
            ("timezone", "Asia/Ho_Chi_Minh", "Timezone for scheduling"),
        ]
        
        for key, value, desc in default_settings:
            existing = db.query(UserSettings).filter_by(setting_key=key).first()
            if not existing:
                setting = UserSettings(
                    setting_key=key,
                    setting_value=value,
                    description=desc
                )
                db.add(setting)
        
        db.commit()
        print("Default settings initialized!")
        
    except Exception as e:
        print(f"Error initializing default settings: {e}")
        db.rollback()
    finally:
        db.close()

def reset_database():
    """Reset database - DROP ALL TABLES and recreate"""
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    init_default_settings()
    print("Database reset completed!")

if __name__ == "__main__":
    create_tables()
    init_default_settings() 