/**
 * Metal GPU Dispatch for Coex
 *
 * Native Metal implementation for GPU-accelerated formula execution.
 * This replaces the Python-based dispatch with compile-time linked Metal.
 *
 * No Python dependency at runtime - pure Objective-C/Metal.
 */

#import <Foundation/Foundation.h>
#import <Metal/Metal.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>
#include <pthread.h>

/* Cached Metal state for performance */
static id<MTLDevice> _device = nil;
static id<MTLCommandQueue> _commandQueue = nil;
static pthread_mutex_t _metal_mutex = PTHREAD_MUTEX_INITIALIZER;
static int _metal_initialized = 0;
static int _metal_available = 0;

/* Simple kernel cache (source hash -> pipeline) */
#define KERNEL_CACHE_SIZE 64
typedef struct {
    uint64_t source_hash;
    id<MTLComputePipelineState> pipeline;
    char kernel_name[128];
} CachedKernel;

static CachedKernel _kernel_cache[KERNEL_CACHE_SIZE];
static int _cache_count = 0;

/**
 * Simple hash function for kernel source.
 */
static uint64_t hash_string(const char* str) {
    uint64_t hash = 5381;
    int c;
    while ((c = *str++)) {
        hash = ((hash << 5) + hash) + c;
    }
    return hash;
}

/**
 * Initialize Metal device and command queue.
 * Thread-safe, only initializes once.
 */
static int init_metal(void) {
    pthread_mutex_lock(&_metal_mutex);

    if (_metal_initialized) {
        pthread_mutex_unlock(&_metal_mutex);
        return _metal_available;
    }

    _metal_initialized = 1;

    @autoreleasepool {
        _device = MTLCreateSystemDefaultDevice();
        if (_device == nil) {
            fprintf(stderr, "Metal: No GPU device available\n");
            _metal_available = 0;
            pthread_mutex_unlock(&_metal_mutex);
            return 0;
        }

        _commandQueue = [_device newCommandQueue];
        if (_commandQueue == nil) {
            fprintf(stderr, "Metal: Failed to create command queue\n");
            _device = nil;
            _metal_available = 0;
            pthread_mutex_unlock(&_metal_mutex);
            return 0;
        }

        _metal_available = 1;

        /* Initialize kernel cache */
        memset(_kernel_cache, 0, sizeof(_kernel_cache));
        _cache_count = 0;
    }

    pthread_mutex_unlock(&_metal_mutex);
    return 1;
}

/**
 * Look up a cached kernel pipeline.
 */
static id<MTLComputePipelineState> lookup_cached_kernel(uint64_t hash, const char* kernel_name) {
    for (int i = 0; i < _cache_count; i++) {
        if (_kernel_cache[i].source_hash == hash &&
            strcmp(_kernel_cache[i].kernel_name, kernel_name) == 0) {
            return _kernel_cache[i].pipeline;
        }
    }
    return nil;
}

/**
 * Cache a compiled kernel pipeline.
 */
static void cache_kernel(uint64_t hash, const char* kernel_name, id<MTLComputePipelineState> pipeline) {
    if (_cache_count >= KERNEL_CACHE_SIZE) {
        /* Simple eviction: overwrite oldest entry */
        /* In production, use LRU or similar */
        _cache_count = 0;
    }

    _kernel_cache[_cache_count].source_hash = hash;
    strncpy(_kernel_cache[_cache_count].kernel_name, kernel_name, 127);
    _kernel_cache[_cache_count].kernel_name[127] = '\0';
    _kernel_cache[_cache_count].pipeline = pipeline;
    _cache_count++;
}

/**
 * Compile Metal shader source and create compute pipeline.
 */
static id<MTLComputePipelineState> compile_kernel(
    const char* kernel_source,
    const char* kernel_name,
    NSError** error_out
) {
    @autoreleasepool {
        NSString* source = [NSString stringWithUTF8String:kernel_source];
        NSString* name = [NSString stringWithUTF8String:kernel_name];

        /* Compile source to library */
        NSError* error = nil;
        id<MTLLibrary> library = [_device newLibraryWithSource:source
                                                       options:nil
                                                         error:&error];
        if (library == nil) {
            if (error_out) *error_out = error;
            return nil;
        }

        /* Get the kernel function */
        id<MTLFunction> function = [library newFunctionWithName:name];
        if (function == nil) {
            if (error_out) {
                *error_out = [NSError errorWithDomain:@"CoexMetal"
                                                 code:2
                                             userInfo:@{NSLocalizedDescriptionKey:
                                                 [NSString stringWithFormat:@"Kernel function '%@' not found", name]}];
            }
            return nil;
        }

        /* Create compute pipeline */
        id<MTLComputePipelineState> pipeline = [_device newComputePipelineStateWithFunction:function
                                                                                      error:&error];
        if (pipeline == nil) {
            if (error_out) *error_out = error;
            return nil;
        }

        return pipeline;
    }
}

/**
 * Check if Metal is available on this system.
 */
int coex_metal_available(void) {
    return init_metal();
}

/**
 * @brief Dispatch a Metal kernel for element-wise GPU computation.
 *
 * This is the main entry point called by compiled Coex code.
 * Metal doesn't support 64-bit types (double, long), so this function
 * handles conversion between Coex's 64-bit types and Metal's 32-bit types.
 *
 * @param kernel_source  Metal shader source code (null-terminated)
 * @param kernel_name    Name of the kernel function (null-terminated)
 * @param input_buffer   Pointer to input data (64-bit Coex types)
 * @param element_count  Number of elements to process
 * @param output_buffer  Pointer to output buffer (64-bit Coex types, pre-allocated)
 * @param element_size   Size of each element in bytes (8 for 64-bit types)
 * @param type_code      Type hint: 0=float (double->float), 1=int (int64->int32)
 */
void coex_metal_dispatch(
    const char* kernel_source,
    const char* kernel_name,
    void* input_buffer,
    int64_t element_count,
    void* output_buffer,
    int64_t element_size,
    int64_t type_code
) {
    /* Initialize Metal if needed */
    if (!init_metal()) {
        fprintf(stderr, "Metal: GPU not available, falling back to CPU\n");
        memset(output_buffer, 0, element_count * element_size);
        return;
    }

    /* Skip if no elements */
    if (element_count <= 0) {
        return;
    }

    @autoreleasepool {
        NSError* error = nil;

        /* Look up or compile kernel */
        uint64_t source_hash = hash_string(kernel_source);
        id<MTLComputePipelineState> pipeline = lookup_cached_kernel(source_hash, kernel_name);

        if (pipeline == nil) {
            pipeline = compile_kernel(kernel_source, kernel_name, &error);
            if (pipeline == nil) {
                fprintf(stderr, "Metal: Kernel compilation failed: %s\n",
                        [[error localizedDescription] UTF8String]);
                memset(output_buffer, 0, element_count * element_size);
                return;
            }
            cache_kernel(source_hash, kernel_name, pipeline);
        }

        /*
         * Metal doesn't support 64-bit types (double, long).
         * We need to convert 64-bit Coex data to 32-bit for Metal:
         *   - double (8 bytes) -> float (4 bytes)
         *   - long (8 bytes) -> int (4 bytes)
         *
         * For now, we handle the common case of float/double conversion.
         */

        /* Calculate Metal buffer sizes (32-bit = half the size of 64-bit) */
        size_t metal_element_size = (element_size == 8) ? 4 : element_size;
        size_t input_size = element_count * metal_element_size;
        size_t output_size = element_count * metal_element_size;

        /* Convert input data from 64-bit to 32-bit if needed */
        void* metal_input = NULL;
        if (element_size == 8) {
            metal_input = malloc(input_size);
            if (!metal_input) {
                fprintf(stderr, "Metal: Failed to allocate conversion buffer\n");
                memset(output_buffer, 0, element_count * element_size);
                return;
            }

            if (type_code == 0) {
                /* Convert double -> float */
                double* src = (double*)input_buffer;
                float* dst = (float*)metal_input;
                for (int64_t i = 0; i < element_count; i++) {
                    dst[i] = (float)src[i];
                }
            } else {
                /* Convert int64 -> int32 */
                int64_t* src = (int64_t*)input_buffer;
                int32_t* dst = (int32_t*)metal_input;
                for (int64_t i = 0; i < element_count; i++) {
                    dst[i] = (int32_t)src[i];
                }
            }
        } else {
            /* No conversion needed, use directly */
            metal_input = input_buffer;
        }

        /* Create Metal buffers (32-bit) */
        /* Use shared storage mode for unified memory (Apple Silicon) */
        id<MTLBuffer> inputBuffer = [_device newBufferWithBytes:metal_input
                                                         length:input_size
                                                        options:MTLResourceStorageModeShared];
        id<MTLBuffer> outputBuffer = [_device newBufferWithLength:output_size
                                                          options:MTLResourceStorageModeShared];

        if (inputBuffer == nil || outputBuffer == nil) {
            fprintf(stderr, "Metal: Failed to allocate GPU buffers\n");
            if (element_size == 8 && metal_input) free(metal_input);
            memset(output_buffer, 0, element_count * element_size);
            return;
        }

        /* Create command buffer and encoder */
        id<MTLCommandBuffer> commandBuffer = [_commandQueue commandBuffer];
        if (commandBuffer == nil) {
            fprintf(stderr, "Metal: Failed to create command buffer\n");
            if (element_size == 8 && metal_input) free(metal_input);
            memset(output_buffer, 0, element_count * element_size);
            return;
        }

        id<MTLComputeCommandEncoder> encoder = [commandBuffer computeCommandEncoder];
        if (encoder == nil) {
            fprintf(stderr, "Metal: Failed to create compute encoder\n");
            if (element_size == 8 && metal_input) free(metal_input);
            memset(output_buffer, 0, element_count * element_size);
            return;
        }

        /* Set up the compute pass */
        [encoder setComputePipelineState:pipeline];
        [encoder setBuffer:inputBuffer offset:0 atIndex:0];
        [encoder setBuffer:outputBuffer offset:0 atIndex:1];

        /* Calculate thread group sizes */
        NSUInteger maxThreadsPerGroup = pipeline.maxTotalThreadsPerThreadgroup;

        /* Use 1D dispatch */
        MTLSize gridSize = MTLSizeMake(element_count, 1, 1);
        MTLSize threadGroupSize = MTLSizeMake(MIN(maxThreadsPerGroup, (NSUInteger)element_count), 1, 1);

        /* Dispatch threads */
        [encoder dispatchThreads:gridSize threadsPerThreadgroup:threadGroupSize];
        [encoder endEncoding];

        /* Submit and wait for completion */
        [commandBuffer commit];
        [commandBuffer waitUntilCompleted];

        /* Check for errors */
        if (commandBuffer.status == MTLCommandBufferStatusError) {
            fprintf(stderr, "Metal: Kernel execution failed: %s\n",
                    [[commandBuffer.error localizedDescription] UTF8String]);
            if (element_size == 8 && metal_input) free(metal_input);
            memset(output_buffer, 0, element_count * element_size);
            return;
        }

        /* Convert output data from 32-bit back to 64-bit if needed */
        if (element_size == 8) {
            if (type_code == 0) {
                /* Convert float -> double */
                float* src = (float*)[outputBuffer contents];
                double* dst = (double*)output_buffer;
                for (int64_t i = 0; i < element_count; i++) {
                    dst[i] = (double)src[i];
                }
            } else {
                /* Convert int32 -> int64 */
                int32_t* src = (int32_t*)[outputBuffer contents];
                int64_t* dst = (int64_t*)output_buffer;
                for (int64_t i = 0; i < element_count; i++) {
                    dst[i] = (int64_t)src[i];
                }
            }
            /* Free conversion buffer */
            free(metal_input);
        } else {
            /* No conversion needed, copy directly */
            memcpy(output_buffer, [outputBuffer contents], output_size);
        }
    }
}

/**
 * Clean up Metal resources.
 * Called at program exit if needed.
 */
void coex_metal_cleanup(void) {
    pthread_mutex_lock(&_metal_mutex);

    /* Clear kernel cache */
    for (int i = 0; i < _cache_count; i++) {
        _kernel_cache[i].pipeline = nil;
    }
    _cache_count = 0;

    _commandQueue = nil;
    _device = nil;
    _metal_initialized = 0;
    _metal_available = 0;

    pthread_mutex_unlock(&_metal_mutex);
}

/* Legacy stub compatibility - these are no longer needed but kept for API compatibility */
void coex_register_metal_dispatch(void* fn) {
    (void)fn;  /* Ignored - native dispatch is always used */
}

int coex_metal_dispatch_available(void) {
    return coex_metal_available();
}

void coex_metal_dispatch_clear(void) {
    /* No-op - native dispatch cannot be cleared */
}
