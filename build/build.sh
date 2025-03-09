#!/bin/bash

# PyInstaller build script for macOS arm64
# Before running this script, you need run: "pip3 install pyinstaller"

# Delete previous build
rm -rf dist

# Copy source code to build directory
cp ../*.py .

# Build executables
pyinstaller cleaner.py      --clean --windowed --target-arch arm64 --icon python.icns
pyinstaller imac_color.py   --clean --windowed --target-arch arm64
pyinstaller doge.py         --clean --onefile --target-arch arm64

# Cleanup the temporary build files
rm *.spec *.py
rm -rf build dist/cleaner dist/imac_color

# Open the dist folder
open dist
