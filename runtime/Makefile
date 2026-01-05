# Coex Runtime Libraries Makefile

CC = clang
CFLAGS = -O2 -fPIC -Wall -Wextra -std=c11
AR = ar

# FFI Runtime
FFI_LIB = libcoex_ffi.a
FFI_OBJ = ffi_support.o

# Task Runtime
TASK_LIB = libcoex_task.a
TASK_OBJ = coex_task.o

# All libraries
LIBS = $(FFI_LIB) $(TASK_LIB)

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

# Test targets
test_task: test_coex_task.c coex_task.c coex_task.h
	$(CC) $(CFLAGS) -o $@ test_coex_task.c coex_task.c -lpthread

test: test_task
	./test_task

clean:
	rm -f $(FFI_OBJ) $(TASK_OBJ) $(LIBS) test_task

.PHONY: all test clean
