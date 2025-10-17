#!/bin/bash
# Installation script for SquareVerse

echo "=================================="
echo "  SquareVerse Installation"
echo "=================================="
echo ""

# Check Python version
echo "Checking Python version..."
python3 --version

if [ $? -ne 0 ]; then
    echo "Error: Python 3 is not installed!"
    echo "Please install Python 3.8 or higher."
    exit 1
fi

# Check pip
echo ""
echo "Checking pip..."
pip3 --version

if [ $? -ne 0 ]; then
    echo "Error: pip is not installed!"
    echo "Please install pip3."
    exit 1
fi

# Install requirements
echo ""
echo "Installing required packages..."
pip3 install -r requirements.txt

if [ $? -ne 0 ]; then
    echo "Error: Failed to install requirements!"
    exit 1
fi

# Check tkinter
echo ""
echo "Checking tkinter availability..."
python3 -c "import tkinter" 2>/dev/null

if [ $? -ne 0 ]; then
    echo "Warning: tkinter is not available!"
    echo ""
    echo "Please install tkinter:"
    echo "  Ubuntu/Debian: sudo apt-get install python3-tk"
    echo "  Fedora: sudo dnf install python3-tkinter"
    echo "  macOS: Included with Python from python.org"
    exit 1
fi

echo ""
echo "=================================="
echo "  Installation Complete!"
echo "=================================="
echo ""
echo "To run the simulation:"
echo "  python3 main.py"
echo ""
echo "Or for a quick demo:"
echo "  python3 demo.py"
echo ""
