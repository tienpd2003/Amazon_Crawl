#!/bin/bash

echo ""
echo "========================================"
echo "   Amazon Product Crawler - Starter"
echo "========================================"
echo ""

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Check if Python is installed
if ! command -v python3 &> /dev/null; then
    echo -e "${RED}[ERROR]${NC} Python 3 is not installed or not in PATH"
    echo "Please install Python 3.8+ using your package manager"
    echo "Ubuntu/Debian: sudo apt-get install python3 python3-pip"
    echo "MacOS: brew install python3"
    exit 1
fi

# Check Python version
python_version=$(python3 -c 'import sys; print(".".join(map(str, sys.version_info[:2])))')
required_version="3.8"

if [ "$(printf '%s\n' "$required_version" "$python_version" | sort -V | head -n1)" != "$required_version" ]; then
    echo -e "${RED}[ERROR]${NC} Python $python_version is installed, but Python $required_version+ is required"
    exit 1
fi

# Check if pip is available
if ! command -v pip3 &> /dev/null; then
    echo -e "${RED}[ERROR]${NC} pip3 is not installed"
    echo "Please install pip3 using your package manager"
    exit 1
fi

# Check if requirements are installed
echo -e "${BLUE}[INFO]${NC} Checking dependencies..."
if ! pip3 show fastapi &> /dev/null; then
    echo -e "${YELLOW}[INFO]${NC} Installing dependencies..."
    pip3 install -r requirements.txt
    if [ $? -ne 0 ]; then
        echo -e "${RED}[ERROR]${NC} Failed to install dependencies"
        exit 1
    fi
fi

# Check if Chrome is installed
if ! command -v google-chrome &> /dev/null && ! command -v chromium-browser &> /dev/null; then
    echo -e "${YELLOW}[WARNING]${NC} Chrome/Chromium browser not found"
    echo "Installing Chrome/Chromium for Selenium:"
    echo "Ubuntu/Debian: sudo apt-get install google-chrome-stable"
    echo "MacOS: brew install --cask google-chrome"
    echo ""
fi

# Setup database if first run
if [ ! -f "amazon_crawler.db" ]; then
    echo -e "${BLUE}[INFO]${NC} First run detected, setting up database..."
    python3 main.py setup
    if [ $? -ne 0 ]; then
        echo -e "${RED}[ERROR]${NC} Database setup failed"
        exit 1
    fi
fi

# Start the application
echo -e "${GREEN}[INFO]${NC} Starting Amazon Crawler..."
echo -e "${GREEN}[INFO]${NC} Dashboard will be available at: http://127.0.0.1:8000"
echo -e "${GREEN}[INFO]${NC} Press Ctrl+C to stop the application"
echo ""

# Make sure to use python3
python3 main.py web

echo ""
echo -e "${BLUE}[INFO]${NC} Application stopped" 