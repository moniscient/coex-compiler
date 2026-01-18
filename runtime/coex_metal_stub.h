/**
 * Metal Dispatch Stub Header for Coex GPU Offload
 *
 * Provides the C interface for Metal kernel dispatch.
 */

#ifndef COEX_METAL_STUB_H
#define COEX_METAL_STUB_H

#include <stdint.h>

#ifdef __cplusplus
extern "C" {
#endif

/* Dispatch function signature */
typedef void (*coex_metal_dispatch_fn)(
    const char* kernel_source,
    const char* kernel_name,
    void* input_buffer,
    int64_t element_count,
    void* output_buffer,
    int64_t element_size
);

/**
 * Register the Metal dispatch implementation.
 * Called by Python runtime to set up the callback.
 */
void coex_register_metal_dispatch(coex_metal_dispatch_fn fn);

/**
 * Check if Metal dispatch is registered.
 * Returns 1 if registered, 0 otherwise.
 */
int coex_metal_dispatch_available(void);

/**
 * Dispatch a Metal compute kernel.
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
);

/**
 * Clear the dispatch registration.
 * Primarily for testing purposes.
 */
void coex_metal_dispatch_clear(void);

#ifdef __cplusplus
}
#endif

#endif /* COEX_METAL_STUB_H */
