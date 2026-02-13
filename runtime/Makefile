# Coex Runtime Libraries Makefile

CC = clang
CFLAGS = -O2 -fPIC -Wall -Wextra -std=c11
OBJCFLAGS = -O2 -fPIC -Wall -Wextra -fobjc-arc
AR = ar

# Detect macOS for Metal support
UNAME_S := $(shell uname -s)

# FFI Runtime
FFI_LIB = libcoex_ffi.a
FFI_OBJ = ffi_support.o

# Task Runtime (pthread-based threads)
TASK_LIB = libcoex_task.a
TASK_OBJ = coex_task.o

# Scheduler Runtime (work-stealing scheduler for lightweight tasks)
SCHEDULER_LIB = libcoex_scheduler.a
SCHEDULER_OBJ = coex_scheduler.o

# Channel Runtime (task-to-task channels)
CHANNEL_LIB = libcoex_channel.a
CHANNEL_OBJ = coex_channel.o

# String Runtime (C string conversion utilities)
STRING_LIB = libcoex_string.a
STRING_OBJ = coex_string.o

# Metal GPU Dispatch - native on macOS, stub on other platforms
METAL_LIB = libcoex_metal.a
ifeq ($(UNAME_S),Darwin)
    METAL_OBJ = coex_metal.o
    METAL_FRAMEWORKS = -framework Metal -framework Foundation -framework MetalPerformanceShaders
else
    METAL_OBJ = coex_metal_stub.o
    METAL_FRAMEWORKS =
endif

# BLAS Library - Accelerate on macOS, OpenBLAS on Linux, reference fallback
BLAS_LIB = libcoex_blas.a
BLAS_OBJ = coex_blas.o
ifeq ($(UNAME_S),Darwin)
    # Use new LAPACK interface to avoid deprecation warnings
    BLAS_CFLAGS = -DACCELERATE_NEW_LAPACK
    BLAS_FRAMEWORKS = -framework Accelerate
else
    # Try OpenBLAS on Linux, fall back to reference implementation
    BLAS_CFLAGS = $(shell pkg-config --cflags openblas 2>/dev/null && echo -DHAVE_OPENBLAS)
    BLAS_FRAMEWORKS = $(shell pkg-config --libs openblas 2>/dev/null)
endif

# UI Library - ImGui + Skia based cross-platform UI
UI_LIB = libcoex_ui.a
UI_DEPS_DIR = ../deps

# Check if UI dependencies exist
UI_DEPS_AVAILABLE := $(shell test -d $(UI_DEPS_DIR)/lib && echo yes)

ifeq ($(UI_DEPS_AVAILABLE),yes)
    UI_CFLAGS = -I$(UI_DEPS_DIR)/include -DCOEX_UI_HAS_CJSON
    UI_LDFLAGS = -L$(UI_DEPS_DIR)/lib
    # Check for ImGui
    ifneq ($(wildcard $(UI_DEPS_DIR)/lib/libcimgui.a),)
        UI_CFLAGS += -DCOEX_UI_HAS_IMGUI
    endif
    # Check for Skia
    ifneq ($(wildcard $(UI_DEPS_DIR)/lib/libskia.a),)
        UI_CFLAGS += -DCOEX_UI_HAS_SKIA
    endif
else
    UI_CFLAGS =
    UI_LDFLAGS =
endif

ifeq ($(UNAME_S),Darwin)
    UI_OBJ = coex_ui.o coex_ui_imgui.o coex_ui_shell_macos.o coex_ui_metal.o coex_ui_skia.o
    UI_FRAMEWORKS = -framework Cocoa -framework Metal -framework QuartzCore
else
    UI_OBJ = coex_ui.o coex_ui_imgui.o coex_ui_shell_linux.o coex_ui_opengl.o coex_ui_skia.o
    # Linux uses GLFW and OpenGL
    UI_CFLAGS += -DCOEX_UI_HAS_GLFW -DCOEX_UI_HAS_OPENGL
    UI_FRAMEWORKS = -lglfw3 -lGL -lX11 -lpthread -ldl -lm
endif

# All libraries (UI is optional, only built if deps available)
LIBS = $(FFI_LIB) $(TASK_LIB) $(SCHEDULER_LIB) $(CHANNEL_LIB) $(STRING_LIB) $(METAL_LIB) $(BLAS_LIB)

all: $(LIBS)

# FFI Library
$(FFI_LIB): $(FFI_OBJ)
	$(AR) rcs $@ $^

ffi_support.o: ffi_support.c ffi_support.h
	$(CC) $(CFLAGS) -c -o $@ $<

# Task Library
$(TASK_LIB): $(TASK_OBJ)
	$(AR) rcs $@ $^

coex_task.o: coex_task.c coex_task.h
	$(CC) $(CFLAGS) -c -o $@ $<

# Scheduler Library
$(SCHEDULER_LIB): $(SCHEDULER_OBJ)
	$(AR) rcs $@ $^

coex_scheduler.o: coex_scheduler.c coex_scheduler.h
	$(CC) $(CFLAGS) -c -o $@ $<

# Channel Library
$(CHANNEL_LIB): $(CHANNEL_OBJ)
	$(AR) rcs $@ $^

coex_channel.o: coex_channel.c coex_channel.h coex_scheduler.h
	$(CC) $(CFLAGS) -c -o $@ $<

# String Library
$(STRING_LIB): $(STRING_OBJ)
	$(AR) rcs $@ $^

coex_string.o: coex_string.c coex_string.h
	$(CC) $(CFLAGS) -c -o $@ $<

# Metal Library - native implementation on macOS
$(METAL_LIB): $(METAL_OBJ)
	$(AR) rcs $@ $^

ifeq ($(UNAME_S),Darwin)
coex_metal.o: coex_metal.m coex_metal_stub.h
	$(CC) $(OBJCFLAGS) -c -o $@ $<
else
coex_metal_stub.o: coex_metal_stub.c coex_metal_stub.h coex_array.h
	$(CC) $(CFLAGS) -c -o $@ $<
endif

# BLAS Library
$(BLAS_LIB): $(BLAS_OBJ)
	$(AR) rcs $@ $^

coex_blas.o: coex_blas.c
	$(CC) $(CFLAGS) $(BLAS_CFLAGS) -c -o $@ $<

# UI Library (optional - requires deps/build_deps.sh to be run first)
$(UI_LIB): $(UI_OBJ)
	$(AR) rcs $@ $^

coex_ui.o: coex_ui.c coex_ui.h coex_ui_shell.h coex_ui_imgui.h
	$(CC) $(CFLAGS) $(UI_CFLAGS) -c -o $@ $<

coex_ui_imgui.o: coex_ui_imgui.c coex_ui_imgui.h
	$(CC) $(CFLAGS) $(UI_CFLAGS) -c -o $@ $<

coex_ui_skia.o: coex_ui_skia.cpp coex_ui_skia.h
	clang++ -O2 -fPIC -Wall -Wextra -std=c++17 $(UI_CFLAGS) -c -o $@ $<

ifeq ($(UNAME_S),Darwin)
coex_ui_shell_macos.o: coex_ui_shell_macos.m coex_ui_shell.h
	$(CC) $(OBJCFLAGS) -c -o $@ $<

coex_ui_metal.o: coex_ui_metal.m coex_ui_metal.h
	$(CC) $(OBJCFLAGS) $(UI_CFLAGS) -c -o $@ $<
else
coex_ui_shell_linux.o: coex_ui_shell_linux.c coex_ui_shell.h
	$(CC) $(CFLAGS) $(UI_CFLAGS) -c -o $@ $<

coex_ui_opengl.o: coex_ui_opengl.c coex_ui_opengl.h
	$(CC) $(CFLAGS) $(UI_CFLAGS) -c -o $@ $<
endif

# Build UI library (separate target since it requires deps)
ui: $(UI_LIB)
	@echo "UI library built: $(UI_LIB)"
	@echo "Link with: $(UI_LDFLAGS) -lcoex_ui $(UI_FRAMEWORKS)"

# bgfx Library - 3D graphics via bgfx
BGFX_LIB = libcoex_bgfx.a
BGFX_DEPS_DIR = ../deps

# Check if bgfx dependencies exist
BGFX_DEPS_AVAILABLE := $(shell test -f $(BGFX_DEPS_DIR)/lib/libbgfx.a && echo yes)

ifeq ($(BGFX_DEPS_AVAILABLE),yes)
    BGFX_CFLAGS = -I$(BGFX_DEPS_DIR)/include -DCOEX_UI_HAS_CJSON
    BGFX_CXXFLAGS = -O2 -fPIC -Wall -std=c++20 -I$(BGFX_DEPS_DIR)/include -DCOEX_UI_HAS_CJSON -DBX_CONFIG_DEBUG=0
    ifneq ($(wildcard $(BGFX_DEPS_DIR)/lib/libcimgui.a),)
        BGFX_CFLAGS += -DCOEX_UI_HAS_IMGUI
        BGFX_CXXFLAGS += -DCOEX_UI_HAS_IMGUI -I$(BGFX_DEPS_DIR)/include
    endif
    BGFX_OBJ = bgfx/coex_bgfx.o bgfx/bgfx_c_bridge.o bgfx/coex_bgfx_imgui.o
else
    BGFX_CFLAGS =
    BGFX_CXXFLAGS =
    BGFX_OBJ =
endif

bgfx: $(BGFX_LIB)
	@echo "bgfx library built: $(BGFX_LIB)"

$(BGFX_LIB): $(BGFX_OBJ)
	$(AR) rcs $@ $^

bgfx/coex_bgfx.o: bgfx/coex_bgfx.c bgfx/coex_bgfx.h coex_ui_shell.h
	$(CC) $(CFLAGS) $(BGFX_CFLAGS) -I$(BGFX_DEPS_DIR)/include -c -o $@ $<

bgfx/bgfx_c_bridge.o: bgfx/bgfx_c_bridge.cpp bgfx/coex_bgfx.h
	clang++ $(BGFX_CXXFLAGS) -c -o $@ $<

bgfx/coex_bgfx_imgui.o: bgfx/coex_bgfx_imgui.cpp bgfx/coex_bgfx.h
	clang++ $(BGFX_CXXFLAGS) -c -o $@ $<

# Metal 3D Library (macOS only, requires UI shell)
METAL3D_LIB = libcoex_metal3d.a

ifeq ($(UNAME_S),Darwin)
METAL3D_OBJ = metal3d/coex_metal3d.o

metal3d: $(METAL3D_LIB)
	@echo "Metal 3D library built: $(METAL3D_LIB)"

$(METAL3D_LIB): $(METAL3D_OBJ)
	$(AR) rcs $@ $^

metal3d/coex_metal3d.o: metal3d/coex_metal3d.m metal3d/coex_metal3d.h coex_ui_shell.h
	$(CC) $(OBJCFLAGS) -c -o $@ $<
endif

# Test targets
test_task: test_coex_task.c coex_task.c coex_task.h
	$(CC) $(CFLAGS) -o $@ test_coex_task.c coex_task.c -lpthread

test: test_task
	./test_task

# Metal test (macOS only)
ifeq ($(UNAME_S),Darwin)
test_metal: coex_metal.m
	$(CC) $(OBJCFLAGS) -DTEST_METAL_MAIN -o $@ $< $(METAL_FRAMEWORKS)
	./test_metal
endif

clean:
	rm -f $(FFI_OBJ) $(TASK_OBJ) $(SCHEDULER_OBJ) $(CHANNEL_OBJ) coex_metal.o coex_metal_stub.o $(BLAS_OBJ) $(LIBS) test_task test_metal
	rm -f $(UI_OBJ) $(UI_LIB) coex_ui_metal.o
	rm -f bgfx/coex_bgfx.o bgfx/bgfx_c_bridge.o bgfx/coex_bgfx_imgui.o $(BGFX_LIB)
	rm -f metal3d/coex_metal3d.o $(METAL3D_LIB)

.PHONY: all test clean test_metal ui bgfx metal3d
