#!/usr/bin/env python3
"""
Batch Import CLI for Amazon Crawler
Usage: python scripts/batch_import_cli.py [options]
"""

import asyncio
import argparse
import sys
import os
from pathlib import Path
from typing import List

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from utils.batch_import import import_from_file, import_from_list, get_import_stats
from utils.logger import get_logger

logger = get_logger(__name__)

def parse_arguments():
    """Parse command line arguments"""
    parser = argparse.ArgumentParser(
        description="Batch import ASINs to Amazon Crawler watchlist",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Import from CSV file
  python scripts/batch_import_cli.py --file products.csv --frequency daily --notes "Electronics products"
  
  # Import from Excel file with specific column
  python scripts/batch_import_cli.py --file products.xlsx --column "Product_ASIN" --frequency daily
  
  # Import from text file (one ASIN per line)
  python scripts/batch_import_cli.py --file asins.txt --frequency daily
  
  # Import specific ASINs
  python scripts/batch_import_cli.py --asins B019OZBSJ8,B08N5WRWNW,B07XYZ1234 --frequency daily
  
  # Get watchlist statistics
  python scripts/batch_import_cli.py --stats
  
  # Test mode (dry run)
  python scripts/batch_import_cli.py --file products.csv --test
        """
    )
    
    # Input options
    input_group = parser.add_mutually_exclusive_group(required=True)
    input_group.add_argument(
        '--file', '-f',
        type=str,
        help='File path to import ASINs from (CSV, TXT, XLSX, XLS)'
    )
    input_group.add_argument(
        '--asins', '-a',
        type=str,
        help='Comma-separated list of ASINs to import'
    )
    input_group.add_argument(
        '--stats', '-s',
        action='store_true',
        help='Show watchlist statistics'
    )
    
    # Import options
    parser.add_argument(
        '--frequency', '--freq',
        type=str,
        default='daily',
        choices=['daily', 'weekly', 'monthly'],
        help='Crawl frequency (default: daily)'
    )
    
    parser.add_argument(
        '--notes', '-n',
        type=str,
        default='',
        help='Notes for the imported ASINs'
    )
    
    # File options
    parser.add_argument(
        '--column', '-c',
        type=str,
        help='Column name containing ASINs (for CSV/Excel files)'
    )
    
    parser.add_argument(
        '--sheet',
        type=str,
        help='Sheet name (for Excel files)'
    )
    
    # Other options
    parser.add_argument(
        '--test', '--dry-run',
        action='store_true',
        help='Test mode - validate ASINs without importing'
    )
    
    parser.add_argument(
        '--verbose', '-v',
        action='store_true',
        help='Verbose output'
    )
    
    return parser.parse_args()

def validate_file(file_path: str) -> bool:
    """Validate file exists and is readable"""
    if not os.path.exists(file_path):
        print(f"❌ Error: File not found: {file_path}")
        return False
    
    if not os.access(file_path, os.R_OK):
        print(f"❌ Error: File not readable: {file_path}")
        return False
    
    return True

def parse_asin_list(asin_string: str) -> List[str]:
    """Parse comma-separated ASIN string into list"""
    return [asin.strip() for asin in asin_string.split(',') if asin.strip()]

async def show_stats():
    """Show watchlist statistics"""
    print("📊 Getting watchlist statistics...")
    
    try:
        stats = await get_import_stats()
        
        print("\n" + "="*50)
        print("📈 WATCHLIST STATISTICS")
        print("="*50)
        print(f"Total ASINs: {stats.get('total_asins', 0):,}")
        print(f"Active ASINs: {stats.get('active_asins', 0):,}")
        print(f"Due for crawl: {stats.get('due_for_crawl', 0):,}")
        print(f"Batch size: {stats.get('batch_size', 100)}")
        print(f"Max concurrent crawlers: {stats.get('max_concurrent_crawlers', 5)}")
        
        if stats.get('frequency_distribution'):
            print("\n📅 Frequency Distribution:")
            for freq, count in stats['frequency_distribution'].items():
                print(f"  {freq}: {count:,}")
        
        print("="*50)
        
    except Exception as e:
        print(f"❌ Error getting statistics: {e}")

async def test_import(file_path: str, **kwargs):
    """Test import without actually importing"""
    print(f"🧪 Testing import from: {file_path}")
    
    try:
        from utils.batch_import import batch_importer
        
        # Extract ASINs without importing
        asins = batch_importer.extract_asins_from_file(file_path, **kwargs)
        
        print(f"\n✅ Test Results:")
        print(f"  Valid ASINs found: {len(asins):,}")
        
        if asins:
            print(f"  Sample ASINs: {asins[:5]}")
            if len(asins) > 5:
                print(f"  ... and {len(asins) - 5} more")
        
        # Show duplicates
        unique_asins = list(dict.fromkeys(asins))
        if len(unique_asins) != len(asins):
            print(f"  Duplicates found: {len(asins) - len(unique_asins)}")
            print(f"  Unique ASINs: {len(unique_asins):,}")
        
        print(f"\n💡 To actually import, run without --test flag")
        
    except Exception as e:
        print(f"❌ Test failed: {e}")

async def import_from_file_async(file_path: str, frequency: str, notes: str, **kwargs):
    """Import ASINs from file"""
    print(f"📁 Importing from file: {file_path}")
    print(f"📅 Frequency: {frequency}")
    if notes:
        print(f"📝 Notes: {notes}")
    
    try:
        result = await import_from_file(file_path, frequency, notes, **kwargs)
        
        print(f"\n✅ Import Results:")
        print(f"  Total ASINs: {result.get('total_asins', 0):,}")
        print(f"  Added: {result.get('added', 0):,}")
        print(f"  Added (no crawl): {result.get('added_no_crawl', 0):,}")
        print(f"  Reactivated: {result.get('reactivated', 0):,}")
        print(f"  Already exists: {result.get('exists', 0):,}")
        print(f"  Errors: {result.get('errors', 0):,}")
        print(f"  Duration: {result.get('duration', 0):.2f}s")
        
        if result.get('error_details'):
            print(f"\n⚠️  Error details (first 5):")
            for error in result['error_details'][:5]:
                print(f"  - {error}")
            if len(result['error_details']) > 5:
                print(f"  ... and {len(result['error_details']) - 5} more errors")
        
    except Exception as e:
        print(f"❌ Import failed: {e}")

async def import_from_list_async(asin_list: List[str], frequency: str, notes: str):
    """Import ASINs from list"""
    print(f"📋 Importing {len(asin_list)} ASINs from list")
    print(f"📅 Frequency: {frequency}")
    if notes:
        print(f"📝 Notes: {notes}")
    
    try:
        result = await import_from_list(asin_list, frequency, notes)
        
        print(f"\n✅ Import Results:")
        print(f"  Total ASINs: {result.get('total_asins', 0):,}")
        print(f"  Added: {result.get('added', 0):,}")
        print(f"  Added (no crawl): {result.get('added_no_crawl', 0):,}")
        print(f"  Reactivated: {result.get('reactivated', 0):,}")
        print(f"  Already exists: {result.get('exists', 0):,}")
        print(f"  Errors: {result.get('errors', 0):,}")
        print(f"  Duration: {result.get('duration', 0):.2f}s")
        
        if result.get('invalid_asins'):
            print(f"\n⚠️  Invalid ASINs (first 5):")
            for asin in result['invalid_asins'][:5]:
                print(f"  - {asin}")
            if len(result['invalid_asins']) > 5:
                print(f"  ... and {len(result['invalid_asins']) - 5} more")
        
        if result.get('error_details'):
            print(f"\n⚠️  Error details (first 5):")
            for error in result['error_details'][:5]:
                print(f"  - {error}")
            if len(result['error_details']) > 5:
                print(f"  ... and {len(result['error_details']) - 5} more errors")
        
    except Exception as e:
        print(f"❌ Import failed: {e}")

async def main():
    """Main function"""
    args = parse_arguments()
    
    # Set log level
    if args.verbose:
        import logging
        logging.getLogger().setLevel(logging.DEBUG)
    
    print("🚀 Amazon Crawler - Batch Import Tool")
    print("="*50)
    
    try:
        if args.stats:
            await show_stats()
            return
        
        if args.file:
            if not validate_file(args.file):
                sys.exit(1)
            
            # Prepare kwargs for file import
            kwargs = {}
            if args.column:
                kwargs['asin_column'] = args.column
            if args.sheet:
                kwargs['sheet_name'] = args.sheet
            
            if args.test:
                await test_import(args.file, **kwargs)
            else:
                await import_from_file_async(args.file, args.frequency, args.notes, **kwargs)
        
        elif args.asins:
            asin_list = parse_asin_list(args.asins)
            
            if args.test:
                print("🧪 Testing ASIN list...")
                from utils.batch_import import batch_importer
                
                valid_asins = []
                invalid_asins = []
                
                for asin in asin_list:
                    if batch_importer.validate_asin(asin):
                        valid_asins.append(asin.strip().upper())
                    else:
                        invalid_asins.append(asin)
                
                print(f"\n✅ Test Results:")
                print(f"  Valid ASINs: {len(valid_asins)}")
                print(f"  Invalid ASINs: {len(invalid_asins)}")
                
                if valid_asins:
                    print(f"  Sample valid ASINs: {valid_asins[:5]}")
                if invalid_asins:
                    print(f"  Invalid ASINs: {invalid_asins}")
                
                print(f"\n💡 To actually import, run without --test flag")
            else:
                await import_from_list_async(asin_list, args.frequency, args.notes)
        
        print(f"\n✅ Operation completed successfully!")
        
    except KeyboardInterrupt:
        print(f"\n⚠️  Operation cancelled by user")
        sys.exit(1)
    except Exception as e:
        print(f"\n❌ Unexpected error: {e}")
        if args.verbose:
            import traceback
            traceback.print_exc()
        sys.exit(1)

if __name__ == "__main__":
    asyncio.run(main()) 