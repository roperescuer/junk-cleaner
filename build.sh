#!/bin/bash

# PyInstaller build script for macOS arm64

# Make sure PyInstaller is installed
pip3 install pyinstaller

# Delete previous build
rm *.dmg

# Build executables
pyinstaller cleaner.py      --clean --windowed --target-arch arm64
pyinstaller imac_color.py   --clean --windowed --target-arch arm64
pyinstaller doge.py         --clean --onefile --target-arch arm64

# Cleanup the temporary build files
rm *.spec
rm -rf build dist/cleaner dist/imac_color

# Get date as dmg file name
DATE=$(date +"%y%m%d")

# Create a release dmg file
hdiutil create -imagekey zlib-level=9 -srcfolder dist/ -ov "release_${DATE}_mac_arm64.dmg"

# Delete the dist folder
rm -rf dist

# Reveal the release dmg file in Finder
open -R "release_${DATE}_mac_arm64.dmg"
