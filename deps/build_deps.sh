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
# GLFW - Cross-platform windowing library (zlib license)
# Only needed on Linux (macOS uses native Cocoa)
# -----------------------------------------------------------------------------
if [ "$UNAME_S" = "Linux" ]; then
    echo "=== Building GLFW ==="

    if [ ! -d "glfw" ]; then
        echo "Cloning GLFW..."
        git clone --depth 1 --branch 3.3.9 https://github.com/glfw/glfw.git
    fi

    cd glfw

    # Build GLFW with static library
    echo "Building GLFW..."
    mkdir -p build
    cd build

    # Configure for static library, disable examples/tests/docs
    cmake .. \
        -DCMAKE_BUILD_TYPE=Release \
        -DGLFW_BUILD_EXAMPLES=OFF \
        -DGLFW_BUILD_TESTS=OFF \
        -DGLFW_BUILD_DOCS=OFF \
        -DCMAKE_POSITION_INDEPENDENT_CODE=ON

    make -j$(nproc 2>/dev/null || echo 4)

    # Copy outputs
    cp src/libglfw3.a "$SCRIPT_DIR/lib/"

    cd ..

    # Copy headers
    cp -r include/GLFW "$SCRIPT_DIR/include/"

    cd "$SCRIPT_DIR"
    echo "GLFW built: lib/libglfw3.a"
    echo ""
else
    echo "=== Skipping GLFW (not needed on macOS) ==="
    echo ""
fi

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
# bgfx - Cross-platform rendering library (BSD 2-clause license)
# Requires: bx (base library), bimg (image library), bgfx (rendering)
# Build order: bx -> bimg -> bgfx
# -----------------------------------------------------------------------------
echo "=== Building bgfx (bx + bimg + bgfx) ==="

# Determine make target based on platform
case "$UNAME_S" in
    Darwin)
        if [ "$UNAME_M" = "arm64" ]; then
            BGFX_TARGET="osx-arm64"
        else
            BGFX_TARGET="osx-x64"
        fi
        ;;
    Linux)
        BGFX_TARGET="linux64"
        ;;
    *)
        echo "Error: Unsupported platform $UNAME_S for bgfx"
        BGFX_TARGET=""
        ;;
esac

if [ -n "$BGFX_TARGET" ] && [ ! -f "lib/libbgfx.a" ]; then
    # Clone bx (base library - required first)
    if [ ! -d "bx" ]; then
        echo "Cloning bx..."
        git clone --depth 1 https://github.com/bkaradzic/bx.git
    fi

    # Clone bimg (image library - requires bx)
    if [ ! -d "bimg" ]; then
        echo "Cloning bimg..."
        git clone --depth 1 https://github.com/bkaradzic/bimg.git
    fi

    # Clone bgfx (rendering library - requires bx and bimg)
    if [ ! -d "bgfx" ]; then
        echo "Cloning bgfx..."
        git clone --depth 1 https://github.com/bkaradzic/bgfx.git
    fi

    # Build using bgfx's makefile system
    # The bgfx makefile expects bx/ bimg/ bgfx/ as siblings
    echo "Building bgfx for target: $BGFX_TARGET..."
    cd bgfx

    # Generate projects and build
    make "$BGFX_TARGET" -j$(nproc 2>/dev/null || sysctl -n hw.ncpu) 2>&1 || {
        echo ""
        echo "=== bgfx build failed ==="
        echo "bgfx requires GENie build tools. Trying cmake fallback..."

        # Fallback: build with cmake if available
        mkdir -p build_cmake
        cd build_cmake
        cmake .. \
            -DCMAKE_BUILD_TYPE=Release \
            -DCMAKE_POSITION_INDEPENDENT_CODE=ON \
            -DBX_DIR="$SCRIPT_DIR/bx" \
            -DBIMG_DIR="$SCRIPT_DIR/bimg" \
            -DBGFX_BUILD_EXAMPLES=OFF \
            -DBGFX_BUILD_TOOLS=OFF
        make -j$(nproc 2>/dev/null || sysctl -n hw.ncpu) 2>&1 || {
            echo "bgfx cmake build also failed."
            echo "You may need to install build prerequisites."
            echo "See: https://bkaradzic.github.io/bgfx/build.html"
            cd "$SCRIPT_DIR"
            touch lib/.bgfx_unavailable
        }
        cd ..
    }

    # Find and copy output libraries
    # bgfx build outputs vary by platform and build system
    for lib_name in bgfx bimg bx; do
        found_lib=$(find . "$SCRIPT_DIR/bx" "$SCRIPT_DIR/bimg" -name "lib${lib_name}Release.a" -o -name "lib${lib_name}.a" 2>/dev/null | head -1)
        if [ -n "$found_lib" ]; then
            cp "$found_lib" "$SCRIPT_DIR/lib/lib${lib_name}.a"
            echo "Copied: lib${lib_name}.a"
        else
            echo "Warning: lib${lib_name}.a not found in build output"
        fi
    done

    # Copy headers
    mkdir -p "$SCRIPT_DIR/include/bgfx"
    mkdir -p "$SCRIPT_DIR/include/bx"
    mkdir -p "$SCRIPT_DIR/include/bimg"
    cp -r "$SCRIPT_DIR/bgfx/include/bgfx"/* "$SCRIPT_DIR/include/bgfx/" 2>/dev/null || true
    cp -r "$SCRIPT_DIR/bx/include/bx"/* "$SCRIPT_DIR/include/bx/" 2>/dev/null || true
    cp -r "$SCRIPT_DIR/bimg/include/bimg"/* "$SCRIPT_DIR/include/bimg/" 2>/dev/null || true

    cd "$SCRIPT_DIR"
    echo "bgfx build complete"
elif [ -f "lib/libbgfx.a" ]; then
    echo "bgfx already installed"
else
    echo "Skipping bgfx (unsupported platform)"
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
if [ "$UNAME_S" = "Linux" ]; then
    echo "  LDFLAGS += -L$SCRIPT_DIR/lib -lcimgui -lcjson -lglfw3 -lGL -lX11 -lpthread -ldl"
else
    echo "  LDFLAGS += -L$SCRIPT_DIR/lib -lcimgui -lcjson"
fi
