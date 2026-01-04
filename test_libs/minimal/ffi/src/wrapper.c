/*
 * Minimal FFI Test Wrapper
 *
 * Simple C functions to test the Coex FFI infrastructure.
 */

#include <stdint.h>
#include <stdlib.h>
#include <string.h>
#include <stdio.h>

/* Simple handle storage for testing opaque handles */
#define MAX_HANDLES 64
static int64_t handle_values[MAX_HANDLES];
static int handle_in_use[MAX_HANDLES];
static int64_t next_handle = 1;

/* Add two integers */
int64_t coex_minimal_add(int64_t a, int64_t b) {
    return a + b;
}

/* Print a greeting and return length */
int64_t coex_minimal_greet(const char* name) {
    if (!name) return -1;
    printf("Hello, %s!\n", name);
    return (int64_t)strlen(name);
}

/* Create a handle storing a value */
int64_t coex_minimal_create_handle(int64_t value) {
    for (int i = 0; i < MAX_HANDLES; i++) {
        if (!handle_in_use[i]) {
            handle_in_use[i] = 1;
            handle_values[i] = value;
            return next_handle++;
        }
    }
    return -1;  /* No free slots */
}

/* Get value from handle */
int64_t coex_minimal_get_value(int64_t handle) {
    if (handle <= 0 || handle > next_handle) return -1;
    int slot = (handle - 1) % MAX_HANDLES;
    if (!handle_in_use[slot]) return -2;
    return handle_values[slot];
}

/* Free a handle */
int64_t coex_minimal_free_handle(int64_t handle) {
    if (handle <= 0 || handle > next_handle) return -1;
    int slot = (handle - 1) % MAX_HANDLES;
    if (!handle_in_use[slot]) return -2;
    handle_in_use[slot] = 0;
    handle_values[slot] = 0;
    return 0;
}
