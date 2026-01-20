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

# All libraries
LIBS = $(FFI_LIB) $(TASK_LIB) $(SCHEDULER_LIB) $(CHANNEL_LIB) $(METAL_LIB) $(BLAS_LIB)

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

# Metal Library - native implementation on macOS
$(METAL_LIB): $(METAL_OBJ)
	$(AR) rcs $@ $^

ifeq ($(UNAME_S),Darwin)
coex_metal.o: coex_metal.m coex_metal_stub.h
	$(CC) $(OBJCFLAGS) -c -o $@ $<
else
coex_metal_stub.o: coex_metal_stub.c coex_metal_stub.h
	$(CC) $(CFLAGS) -c -o $@ $<
endif

# BLAS Library
$(BLAS_LIB): $(BLAS_OBJ)
	$(AR) rcs $@ $^

coex_blas.o: coex_blas.c
	$(CC) $(CFLAGS) $(BLAS_CFLAGS) -c -o $@ $<

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

.PHONY: all test clean test_metal
