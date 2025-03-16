#!/bin/bash

# PyInstaller build script for macOS arm64

# Make sure latest version of PyInstaller is installed
pip3 install -U pyinstaller

# Delete previous build
rm *.dmg

# Build executables
pyinstaller cleaner.py      --clean --optimize 2 --windowed --target-arch arm64
pyinstaller imac_color.py   --clean --optimize 2 --windowed --target-arch arm64
pyinstaller doge.py         --clean --optimize 2 --onefile  --target-arch arm64

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
