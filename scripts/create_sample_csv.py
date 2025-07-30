#!/usr/bin/env python3
"""
Create sample CSV files for batch importing ASINs
Usage: python scripts/create_sample_csv.py [options]
"""

import csv
import argparse
import os
from pathlib import Path
from typing import List

def create_simple_csv(filename: str, asins: List[str]):
    """Create simple CSV with ASINs only"""
    with open(filename, 'w', newline='', encoding='utf-8') as file:
        writer = csv.writer(file)
        writer.writerow(['ASIN'])
        for asin in asins:
            writer.writerow([asin])
    
    print(f"✅ Created simple CSV: {filename}")

def create_detailed_csv(filename: str, asins: List[str]):
    """Create detailed CSV with additional columns"""
    with open(filename, 'w', newline='', encoding='utf-8') as file:
        writer = csv.writer(file)
        writer.writerow(['ASIN', 'Product_Name', 'Category', 'Notes'])
        
        for i, asin in enumerate(asins):
            # Generate sample data
            product_name = f"Sample Product {i+1}"
            category = "Electronics" if i % 3 == 0 else "Home & Garden" if i % 3 == 1 else "Books"
            notes = f"Imported on {i+1}st batch"
            
            writer.writerow([asin, product_name, category, notes])
    
    print(f"✅ Created detailed CSV: {filename}")

def create_large_csv(filename: str, count: int = 1000):
    """Create large CSV with many ASINs"""
    # Generate sample ASINs (these are not real, just for testing)
    sample_asins = [
        "B019OZBSJ8", "B08N5WRWNW", "B07XYZ1234", "B06ABC5678", "B05DEF9012",
        "B04GHI3456", "B03JKL7890", "B02MNO1234", "B01PQR5678", "B00STU9012"
    ]
    
    asins = []
    for i in range(count):
        # Cycle through sample ASINs and add numbers
        base_asin = sample_asins[i % len(sample_asins)]
        # Create variations by changing last few characters
        variation = str(i).zfill(3)
        asin = base_asin[:-3] + variation
        asins.append(asin)
    
    with open(filename, 'w', newline='', encoding='utf-8') as file:
        writer = csv.writer(file)
        writer.writerow(['ASIN', 'Batch_Number'])
        
        for i, asin in enumerate(asins):
            batch_num = (i // 100) + 1
            writer.writerow([asin, f"Batch_{batch_num}"])
    
    print(f"✅ Created large CSV: {filename} with {count} ASINs")

def create_text_file(filename: str, asins: List[str]):
    """Create text file with one ASIN per line"""
    with open(filename, 'w', encoding='utf-8') as file:
        for asin in asins:
            file.write(f"{asin}\n")
    
    print(f"✅ Created text file: {filename}")

def main():
    parser = argparse.ArgumentParser(
        description="Create sample files for batch importing ASINs",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Create simple CSV with sample ASINs
  python scripts/create_sample_csv.py --simple sample_asins.csv
  
  # Create detailed CSV with additional columns
  python scripts/create_sample_csv.py --detailed detailed_asins.csv
  
  # Create large CSV with 1000 ASINs
  python scripts/create_sample_csv.py --large large_asins.csv --count 1000
  
  # Create text file
  python scripts/create_sample_csv.py --text asins.txt
        """
    )
    
    parser.add_argument(
        '--simple', '-s',
        type=str,
        help='Create simple CSV file with ASINs only'
    )
    
    parser.add_argument(
        '--detailed', '-d',
        type=str,
        help='Create detailed CSV file with additional columns'
    )
    
    parser.add_argument(
        '--large', '-l',
        type=str,
        help='Create large CSV file with many ASINs'
    )
    
    parser.add_argument(
        '--text', '-t',
        type=str,
        help='Create text file with one ASIN per line'
    )
    
    parser.add_argument(
        '--count', '-c',
        type=int,
        default=1000,
        help='Number of ASINs for large file (default: 1000)'
    )
    
    parser.add_argument(
        '--all', '-a',
        action='store_true',
        help='Create all sample files'
    )
    
    args = parser.parse_args()
    
    # Sample ASINs (mix of real and test ASINs)
    sample_asins = [
        "B019OZBSJ8",  # Real ASIN
        "B08N5WRWNW",  # Real ASIN
        "B07XYZ1234",  # Test ASIN
        "B06ABC5678",  # Test ASIN
        "B05DEF9012",  # Test ASIN
        "B04GHI3456",  # Test ASIN
        "B03JKL7890",  # Test ASIN
        "B02MNO1234",  # Test ASIN
        "B01PQR5678",  # Test ASIN
        "B00STU9012"   # Test ASIN
    ]
    
    print("🚀 Creating sample files for batch import...")
    print("="*50)
    
    try:
        if args.all:
            # Create all sample files
            create_simple_csv("sample_simple.csv", sample_asins)
            create_detailed_csv("sample_detailed.csv", sample_asins)
            create_large_csv("sample_large.csv", args.count)
            create_text_file("sample_asins.txt", sample_asins)
            
        else:
            if args.simple:
                create_simple_csv(args.simple, sample_asins)
            
            if args.detailed:
                create_detailed_csv(args.detailed, sample_asins)
            
            if args.large:
                create_large_csv(args.large, args.count)
            
            if args.text:
                create_text_file(args.text, sample_asins)
            
            if not any([args.simple, args.detailed, args.large, args.text]):
                print("❌ No file type specified. Use --help for options.")
                return
        
        print("\n📋 Sample files created successfully!")
        print("\n💡 Usage examples:")
        print("  # Import simple CSV")
        print("  python scripts/batch_import_cli.py --file sample_simple.csv --frequency daily")
        print("  ")
        print("  # Import detailed CSV with specific column")
        print("  python scripts/batch_import_cli.py --file sample_detailed.csv --column ASIN --frequency daily")
        print("  ")
        print("  # Import text file")
        print("  python scripts/batch_import_cli.py --file sample_asins.txt --frequency daily")
        print("  ")
        print("  # Test import without actually importing")
        print("  python scripts/batch_import_cli.py --file sample_simple.csv --test")
        
    except Exception as e:
        print(f"❌ Error creating sample files: {e}")

if __name__ == "__main__":
    main() 