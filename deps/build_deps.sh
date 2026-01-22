#!/bin/bash
#
# Coex UI Dependencies Build Script
#
# Downloads and builds:
#   - cimgui (Dear ImGui C wrapper)
#   - cJSON (JSON parser)
#   - Skia prebuilt binaries
#
# Output:
#   deps/lib/      - Static libraries
#   deps/include/  - Header files

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

# Detect platform
UNAME_S=$(uname -s)
UNAME_M=$(uname -m)

echo "=== Coex UI Dependencies Build ==="
echo "Platform: $UNAME_S ($UNAME_M)"
echo ""

# Create output directories
mkdir -p lib include

# -----------------------------------------------------------------------------
# cJSON - Lightweight JSON parser (MIT license)
# -----------------------------------------------------------------------------
echo "=== Building cJSON ==="

if [ ! -d "cJSON" ]; then
    echo "Cloning cJSON..."
    git clone --depth 1 https://github.com/DaveGamble/cJSON.git
fi

# cJSON is header-only with one source file - just copy
cp cJSON/cJSON.h include/
cp cJSON/cJSON.c include/
echo "cJSON headers copied to include/"

# Compile to static library
echo "Compiling cJSON..."
cc -O2 -fPIC -c include/cJSON.c -o cJSON.o
ar rcs lib/libcjson.a cJSON.o
rm -f cJSON.o
echo "cJSON built: lib/libcjson.a"
echo ""

# -----------------------------------------------------------------------------
# cimgui - C wrapper for Dear ImGui (MIT license)
# -----------------------------------------------------------------------------
echo "=== Building cimgui ==="

if [ ! -d "cimgui" ]; then
    echo "Cloning cimgui..."
    git clone --depth 1 --recursive https://github.com/cimgui/cimgui.git
fi

cd cimgui

# Build cimgui with static library
echo "Building cimgui..."
mkdir -p build
cd build

# Configure for static library
cmake .. \
    -DCMAKE_BUILD_TYPE=Release \
    -DIMGUI_STATIC=ON \
    -DCMAKE_POSITION_INDEPENDENT_CODE=ON

make -j$(nproc 2>/dev/null || sysctl -n hw.ncpu)

# Copy outputs
cp cimgui.a "$SCRIPT_DIR/lib/libcimgui.a" 2>/dev/null || \
    cp libcimgui.a "$SCRIPT_DIR/lib/" 2>/dev/null || \
    echo "Warning: Could not find cimgui library, checking alternative locations..."

cd ..

# Copy headers
cp cimgui.h "$SCRIPT_DIR/include/"
cp imgui/imgui.h "$SCRIPT_DIR/include/"
cp imgui/imconfig.h "$SCRIPT_DIR/include/"
cp imgui/imgui_internal.h "$SCRIPT_DIR/include/" 2>/dev/null || true

cd "$SCRIPT_DIR"
echo "cimgui built"
echo ""

# -----------------------------------------------------------------------------
# Skia - 2D graphics library (BSD license)
# We use prebuilt binaries because building from source is extremely complex
# -----------------------------------------------------------------------------
echo "=== Downloading Skia prebuilt ==="

# Determine Skia URL based on platform
# Using skia-build project releases for convenient prebuilts
SKIA_VERSION="m116-0"

case "$UNAME_S" in
    Darwin)
        if [ "$UNAME_M" = "arm64" ]; then
            SKIA_PLATFORM="macos-arm64"
        else
            SKIA_PLATFORM="macos-x64"
        fi
        ;;
    Linux)
        SKIA_PLATFORM="linux-x64"
        ;;
    *)
        echo "Error: Unsupported platform $UNAME_S"
        exit 1
        ;;
esac

SKIA_URL="https://github.com/nicbarker/skia-build/releases/download/$SKIA_VERSION/skia-$SKIA_PLATFORM.zip"

if [ ! -f "lib/libskia.a" ]; then
    echo "Downloading Skia from: $SKIA_URL"
    curl -L -o skia.zip "$SKIA_URL" || {
        echo ""
        echo "=== Skia download failed ==="
        echo "Skia prebuilts may not be available for your platform."
        echo "The UI library can still work with software rendering."
        echo ""
        echo "To build Skia manually, see: https://skia.org/docs/user/build/"
        echo ""
        touch lib/.skia_unavailable
    }

    if [ -f "skia.zip" ]; then
        echo "Extracting Skia..."
        mkdir -p skia
        unzip -q skia.zip -d skia

        # Find and copy library
        find skia -name "libskia.a" -exec cp {} lib/ \;

        # Copy headers
        if [ -d "skia/include" ]; then
            cp -r skia/include/* include/ 2>/dev/null || true
        fi

        rm -f skia.zip
        echo "Skia installed"
    fi
else
    echo "Skia already installed"
fi

echo ""

# -----------------------------------------------------------------------------
# Summary
# -----------------------------------------------------------------------------
echo "=== Build Summary ==="
echo ""
echo "Libraries in deps/lib/:"
ls -la lib/
echo ""
echo "Headers in deps/include/:"
ls include/ | head -20
if [ $(ls include/ | wc -l) -gt 20 ]; then
    echo "  ... and $(( $(ls include/ | wc -l) - 20 )) more"
fi
echo ""

if [ -f "lib/.skia_unavailable" ]; then
    echo "WARNING: Skia not available - software rendering only"
else
    echo "All dependencies built successfully!"
fi
echo ""
echo "To use in your project:"
echo "  CFLAGS += -I$SCRIPT_DIR/include"
echo "  LDFLAGS += -L$SCRIPT_DIR/lib -lcimgui -lcjson -lskia"
