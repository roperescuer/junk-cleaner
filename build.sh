#!/bin/bash

cat << "EOF"
######################################
#    Build script for macOS arm64    #
######################################

Choose a build option:

1. Nuitka (Recommend)
2. PyInstaller
3. Both

EOF
read -p "Input your choose (1-3): " choice

ICON="icon.icns"
DATE=$(date +"%y%m%d")
VENV_DIR=".venv"
PIP="$(which pip3 || which pip)"
PYTHON="$(which python3 || which python)"
export PIP_DISABLE_PIP_VERSION_CHECK=1

build_nuitka() {
    echo -e "\033[32mBuilding executables with Nuitka...\033[0m"
    $PIP install -q -U nuitka rich

    # Set GUI App parameters
    GUI=(
        --standalone
        --enable-plugin=tk-inter
        --macos-create-app-bundle
        --macos-app-icon=$ICON
        --macos-app-version="${DATE}"
        --no-deployment-flag=self-execution
        --remove-output
        --quiet
        --nofollow-import-to=numpy,bz2,codecs,csv,ctypes,crypto,hashlib,ssl,socket,lzma,math,contextvars,pickle,pyexpat,zlib
        # 'decimal,random' are not included in the list above because they are used by tkinter
    )

    # Set CLI App parameters
    CLI=(
        --standalone
        --onefile
        --remove-output
        --quiet
        --nofollow-import-to=numpy,bz2,codecs,csv,ctypes,crypto,hashlib,ssl,socket,lzma,math,contextvars,pickle,pyexpat,zlib,decimal,datetime
    )

    # Build executables
    nuitka cleaner.py       "${GUI[@]}" --macos-app-name="Junk Cleaner"
    nuitka imac_color.py    "${GUI[@]}" --macos-app-name="iMac Accent Color"
    nuitka doge.py          "${CLI[@]}"

    # Move to a temporary folder
    mkdir -p tmp
    mv *.app tmp
    mv doge.bin tmp/doge

    # Create a release dmg file
    hdiutil create -ov "junk-cleaner_nuitka_rel_${DATE}_mac_arm64.dmg"\
        -volname "Junk Cleaner"\
        -srcfolder tmp/\
        -imagekey zlib-level=9

    # Cleanup
    rm -rf *.dist tmp

    # Reveal in Finder
    if [ "$choice" -ne 3 ]; then
        open -R "junk-cleaner_nuitka_rel_${DATE}_mac_arm64.dmg"
    fi
}

build_pyinstaller() {
    echo -e "\033[32mBuilding executables with PyInstaller, Please wait...\033[0m"
    $PIP install -q -U pyinstaller rich

    # Set universal parameters
    ARGS=(
        --log-level WARN
        --clean
        --optimize 2
        --target-arch arm64
    )

    # Build executables
    pyinstaller cleaner.py      "${ARGS[@]}" --windowed --icon $ICON
    pyinstaller imac_color.py   "${ARGS[@]}" --windowed --icon $ICON
    pyinstaller doge.py         "${ARGS[@]}" --onefile

    # Cleanup specs
    rm -f *.spec
    rm -rf build dist/cleaner dist/imac_color

    # Create a release dmg file
    hdiutil create -ov "junk-cleaner_pyi_rel_${DATE}_mac_arm64.dmg"\
        -volname "Junk Cleaner"\
        -srcfolder dist/\
        -imagekey zlib-level=9

    # Cleanup
    rm -rf dist

    # Reveal in Finder
    if [ "$choice" -ne 3 ]; then
        open -R "junk-cleaner_pyi_rel_${DATE}_mac_arm64.dmg"
    fi
}

setup_venv() {
    echo -e "\033[32mSetting up Python virtual environment...\033[0m"
    $PYTHON -m venv $VENV_DIR
    source $VENV_DIR/bin/activate
}

cleanup_venv() {
    echo -e "\033[32mCleaning up virtual environment...\033[0m"
    deactivate
    rm -rf $VENV_DIR
}

# command -v nuitka >/dev/null 2>&1 || pip3 install -U nuitka
# command -v pyinstaller >/dev/null 2>&1 || pip3 install -U pyinstaller

setup_venv

case $choice in
    1)
        build_nuitka
        ;;
    2)
        build_pyinstaller
        ;;
    3)
        build_nuitka
        build_pyinstaller
        ;;
    *)
        echo -e "\033[31mInvalid Choose! Available: 1-3\033[0m"
        cleanup_venv
        exit 1
        ;;
esac

cleanup_venv

if [ "$choice" -eq 3 ]; then
    open .
fi

echo -e "\033[32mBuild completed!\033[0m"
