/**
 * Metal Dispatch Stub for Coex GPU Offload
 *
 * This file provides the C interface that compiled Coex binaries link against.
 * The actual Metal dispatch is implemented in Python (metal_runtime.py) and
 * registered at runtime via coex_register_metal_dispatch().
 *
 * This stub allows:
 * 1. Compiled binaries to call coex_metal_dispatch() without linking Metal
 * 2. Runtime registration of the Python callback
 * 3. Graceful no-op if Metal is not available
 */

#include <stdint.h>
#include <stdio.h>
#include <string.h>

#include "coex_array.h"

/* Dispatch function signature */
typedef void (*coex_metal_dispatch_fn)(
    const char* kernel_source,
    const char* kernel_name,
    void* input_buffer,
    int64_t element_count,
    void* output_buffer,
    int64_t element_size
);

/* Registered dispatch implementation (set by Python runtime) */
static coex_metal_dispatch_fn _dispatch_impl = NULL;

/* Flag to suppress repeated warnings */
static int _warned_no_dispatch = 0;

/**
 * Register the Metal dispatch implementation.
 *
 * Called by Python runtime to set up the callback.
 *
 * @param fn Pointer to dispatch function
 */
void coex_register_metal_dispatch(coex_metal_dispatch_fn fn) {
    _dispatch_impl = fn;
    _warned_no_dispatch = 0;  /* Reset warning flag on new registration */
}

/**
 * Check if Metal dispatch is registered.
 *
 * @return 1 if registered, 0 otherwise
 */
int coex_metal_dispatch_available(void) {
    return _dispatch_impl != NULL;
}

/**
 * Dispatch a Metal compute kernel.
 *
 * This function is called by compiled Coex code to execute GPU kernels.
 * If no dispatch implementation is registered, it leaves the output
 * buffer unchanged (which should be zero-initialized by the caller).
 *
 * @param kernel_source MSL kernel source code (null-terminated)
 * @param kernel_name   Name of the kernel function (null-terminated)
 * @param input_buffer  Pointer to input data
 * @param element_count Number of elements to process
 * @param output_buffer Pointer to output buffer (must be pre-allocated)
 * @param element_size  Size of each element in bytes
 */
void coex_metal_dispatch(
    const char* kernel_source,
    const char* kernel_name,
    void* input_buffer,
    int64_t element_count,
    void* output_buffer,
    int64_t element_size
) {
    if (_dispatch_impl != NULL) {
        /* Call registered Python implementation */
        _dispatch_impl(
            kernel_source,
            kernel_name,
            input_buffer,
            element_count,
            output_buffer,
            element_size
        );
    } else {
        /* No dispatch registered - warn once and leave output as-is */
        if (!_warned_no_dispatch) {
            fprintf(stderr, "Warning: coex_metal_dispatch called but no implementation registered\n");
            fprintf(stderr, "         GPU offload disabled, using zeros for output\n");
            _warned_no_dispatch = 1;
        }
        /* Zero-initialize output as fallback */
        memset(output_buffer, 0, element_count * element_size);
    }
}

/**
 * Clear the dispatch registration.
 *
 * Primarily for testing purposes.
 */
void coex_metal_dispatch_clear(void) {
    _dispatch_impl = NULL;
    _warned_no_dispatch = 0;
}

/* ========================================================================
 * Metal matmul stubs (non-macOS platforms)
 * ========================================================================
 * These functions are declared as extern in linalg.coex but are only
 * implemented in coex_metal.m (Objective-C) on macOS. On Linux and other
 * platforms, we provide these stub implementations that return NULL to
 * indicate GPU acceleration is not available.
 * ======================================================================== */

static int _warned_no_metal_matmul = 0;

/**
 * Stub for GPU matrix multiplication (float64 arrays).
 * On non-macOS platforms, Metal is not available.
 *
 * @param a  Input matrix A (unused)
 * @param b  Input matrix B (unused)
 * @return   Always returns NULL (GPU not available)
 */
CoexArray* coex_metal_matmul(const CoexArray* a, const CoexArray* b) {
    (void)a;  /* Suppress unused parameter warning */
    (void)b;
    if (!_warned_no_metal_matmul) {
        fprintf(stderr, "Warning: coex_metal_matmul called but Metal is not available on this platform\n");
        fprintf(stderr, "         Use matmul_f64() or matmul_f32() for CPU-based matrix multiplication\n");
        _warned_no_metal_matmul = 1;
    }
    return NULL;
}

/**
 * Stub for GPU matrix multiplication (native float32 arrays).
 * On non-macOS platforms, Metal is not available.
 *
 * @param a  Input matrix A (unused)
 * @param b  Input matrix B (unused)
 * @return   Always returns NULL (GPU not available)
 */
CoexArray* coex_metal_matmul_f32_native(const CoexArray* a, const CoexArray* b) {
    (void)a;  /* Suppress unused parameter warning */
    (void)b;
    if (!_warned_no_metal_matmul) {
        fprintf(stderr, "Warning: coex_metal_matmul_f32_native called but Metal is not available on this platform\n");
        fprintf(stderr, "         Use matmul_cpu_f32() for CPU-based float32 matrix multiplication\n");
        _warned_no_metal_matmul = 1;
    }
    return NULL;
}
