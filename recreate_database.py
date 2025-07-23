"""
Script to recreate database with new schema
Force delete old database and create new one with exact field names
"""

import os
import time
from sqlalchemy import create_engine
from database.models import Base
from database.connection import get_database_url

def recreate_database():
    """Recreate the database with updated schema"""
    try:
        # Get database URL
        db_url = get_database_url()
        
        # Delete existing database file if it exists
        if os.path.exists('amazon_crawler.db'):
            os.remove('amazon_crawler.db')
            print("Deleted existing database file")
            
        # Create new database with updated schema
        engine = create_engine(db_url)
        Base.metadata.create_all(engine)
        print("Successfully recreated database with new schema")
        
    except Exception as e:
        print(f"Error recreating database: {e}")

if __name__ == '__main__':
    recreate_database() 