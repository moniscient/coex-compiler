/*
 * Coex FFI Support Library
 *
 * Provides runtime support for foreign function interface calls:
 * - FFI instance management (isolation per func/task)
 * - Handle table for opaque pointer management
 * - GC coordination (safe points)
 * - Resource backpressure handling
 *
 * Each FFI instance is isolated with its own:
 * - Handle table (maps int64 handles to C pointers)
 * - Arena allocator for temporary allocations
 * - State tracking for GC coordination
 */

#ifndef COEX_FFI_SUPPORT_H
#define COEX_FFI_SUPPORT_H

#include <stdint.h>
#include <stddef.h>

#ifdef __cplusplus
extern "C" {
#endif

/* ========================================================================
 * FFI Instance Management
 * ======================================================================== */

/*
 * Create a new FFI instance.
 *
 * Each func that uses FFI gets an instance at entry. Tasks get their
 * own isolated instances. Nested func calls share the parent's instance.
 *
 * @param library_name  Name of the library (for debugging/logging)
 * @return Instance ID (> 0) on success, negative on error
 *
 * Error returns:
 *   -1: Maximum instances reached (resource exhaustion)
 *   -2: Memory allocation failed
 */
int64_t coex_ffi_instance_create(const char* library_name);

/*
 * Destroy an FFI instance.
 *
 * Frees all handles and arena memory associated with the instance.
 * Safe to call even if instance doesn't exist (no-op).
 *
 * @param instance_id  The instance ID returned by create
 */
void coex_ffi_instance_destroy(int64_t instance_id);

/*
 * Get the arena allocator for an instance.
 *
 * Arena memory is automatically freed when the instance is destroyed.
 * Use for temporary allocations within an FFI call.
 *
 * @param instance_id  The instance ID
 * @return Pointer to arena, or NULL if invalid instance
 */
void* coex_ffi_instance_get_arena(int64_t instance_id);

/*
 * Check if an instance ID is valid.
 *
 * @param instance_id  The instance ID to check
 * @return 1 if valid, 0 if invalid
 */
int coex_ffi_instance_valid(int64_t instance_id);


/* ========================================================================
 * Handle Table (per-instance opaque handle management)
 * ======================================================================== */

/*
 * Allocate a handle for a C pointer.
 *
 * The handle can be passed back to Coex as an int64 and later
 * converted back to the pointer. Handles are instance-local.
 *
 * @param instance_id  The FFI instance
 * @param ptr          The C pointer to wrap
 * @return Handle (> 0) on success, negative on error
 *
 * Error returns:
 *   -1: Invalid instance
 *   -2: Handle table full
 *   -3: NULL pointer not allowed
 */
int64_t coex_ffi_handle_alloc(int64_t instance_id, void* ptr);

/*
 * Get the C pointer for a handle.
 *
 * @param instance_id  The FFI instance
 * @param handle       The handle returned by alloc
 * @return The C pointer, or NULL if invalid handle
 */
void* coex_ffi_handle_get(int64_t instance_id, int64_t handle);

/*
 * Free a handle.
 *
 * The pointer is no longer accessible via this handle.
 * Does NOT free the underlying memory - caller must do that.
 *
 * @param instance_id  The FFI instance
 * @param handle       The handle to free
 */
void coex_ffi_handle_free(int64_t instance_id, int64_t handle);

/*
 * Free a handle and the underlying pointer.
 *
 * Calls free() on the pointer and releases the handle.
 *
 * @param instance_id  The FFI instance
 * @param handle       The handle to free
 */
void coex_ffi_handle_free_ptr(int64_t instance_id, int64_t handle);


/* ========================================================================
 * GC Coordination
 * ======================================================================== */

/*
 * Mark thread as entering FFI code.
 *
 * The GC treats this as a safe point - it can proceed with collection
 * while the thread is in foreign code (FFI only has copies of data).
 *
 * @param instance_id  The FFI instance
 */
void coex_ffi_enter(int64_t instance_id);

/*
 * Mark thread as exiting FFI code.
 *
 * Thread returns to Coex managed code.
 *
 * @param instance_id  The FFI instance
 */
void coex_ffi_exit(int64_t instance_id);

/*
 * Check if current thread is in FFI code.
 *
 * @return 1 if in FFI, 0 otherwise
 */
int coex_ffi_in_foreign_code(void);


/* ========================================================================
 * Resource Backpressure
 * ======================================================================== */

/*
 * Error code for resource exhaustion.
 * Programs can check for this in select/match.
 */
#define COEX_FFI_RESOURCE_EXHAUSTED (-100)

/*
 * Check if FFI resources can be allocated.
 *
 * Call before creating instances under memory pressure.
 *
 * @param estimated_size  Estimated memory needed
 * @return 0 if OK, COEX_FFI_RESOURCE_EXHAUSTED if under pressure
 */
int coex_ffi_can_allocate(size_t estimated_size);

/*
 * Get number of active FFI instances.
 *
 * Useful for debugging and monitoring.
 *
 * @return Number of active instances
 */
int64_t coex_ffi_instance_count(void);


/* ========================================================================
 * Arena Allocation (for temporary FFI allocations)
 * ======================================================================== */

/*
 * Allocate memory from an instance's arena.
 *
 * Memory is automatically freed when instance is destroyed.
 * Use for temporary buffers during FFI calls.
 *
 * @param instance_id  The FFI instance
 * @param size         Bytes to allocate
 * @return Pointer to memory, or NULL on failure
 */
void* coex_ffi_arena_alloc(int64_t instance_id, size_t size);

/*
 * Reset arena (free all arena allocations).
 *
 * Call between FFI calls to reuse arena memory.
 *
 * @param instance_id  The FFI instance
 */
void coex_ffi_arena_reset(int64_t instance_id);


#ifdef __cplusplus
}
#endif

#endif /* COEX_FFI_SUPPORT_H */
