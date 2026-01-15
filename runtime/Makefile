# Coex Runtime Libraries Makefile

CC = clang
CFLAGS = -O2 -fPIC -Wall -Wextra -std=c11
AR = ar

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

# All libraries
LIBS = $(FFI_LIB) $(TASK_LIB) $(SCHEDULER_LIB) $(CHANNEL_LIB)

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

# Test targets
test_task: test_coex_task.c coex_task.c coex_task.h
	$(CC) $(CFLAGS) -o $@ test_coex_task.c coex_task.c -lpthread

test: test_task
	./test_task

clean:
	rm -f $(FFI_OBJ) $(TASK_OBJ) $(SCHEDULER_OBJ) $(CHANNEL_OBJ) $(LIBS) test_task

.PHONY: all test clean
