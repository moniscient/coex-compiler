# Coex FFI Runtime Library Makefile

CC = clang
CFLAGS = -O2 -fPIC -Wall -Wextra -std=c11
AR = ar

# Output
LIB = libcoex_ffi.a
OBJ = ffi_support.o

all: $(LIB)

$(LIB): $(OBJ)
	$(AR) rcs $@ $^

ffi_support.o: ffi_support.c ffi_support.h
	$(CC) $(CFLAGS) -c -o $@ $<

clean:
	rm -f $(OBJ) $(LIB)

.PHONY: all clean
