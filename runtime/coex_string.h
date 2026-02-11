/*
 * Coex String Runtime Support
 *
 * Provides C-side utilities for creating Coex strings from C strings.
 * These functions properly allocate on the GC heap and handle UTF-8.
 *
 * Usage:
 *   // Takes ownership of malloc'd string (frees it after copying)
 *   CoexString* str = coex_string_from_cstring_take(malloc_str);
 *
 *   // Copies without freeing (caller retains ownership)
 *   CoexString* str = coex_string_from_cstring_copy(static_str);
 */

#ifndef COEX_STRING_H
#define COEX_STRING_H

#include <stdint.h>
#include <stddef.h>

#ifdef __cplusplus
extern "C" {
#endif

/* ========================================================================
 * String Struct Definition (must match codegen/strings.py)
 * ======================================================================== */

/*
 * CoexString - 32 byte GC-managed string structure
 *
 * Fields:
 *   owner_handle - GC handle (i64 index into handle table) for data buffer
 *   offset       - byte offset into owner's data (for slice views)
 *   len          - UTF-8 codepoint count (what .len() returns)
 *   size         - byte count of string's extent
 *
 * Note: owner_handle stores a GC handle, not a raw pointer. Use
 * coex_gc_handle_deref(owner_handle) to get the current data pointer.
 */
typedef struct CoexString {
    int64_t owner_handle;  /* Field 0: GC handle for data buffer */
    int64_t offset;        /* Field 1: byte offset into data */
    int64_t len;           /* Field 2: UTF-8 codepoint count */
    int64_t size;          /* Field 3: byte size */
} CoexString;

/* GC type IDs (must match coex_gc.py) */
#define GC_TYPE_STRING      2   /* String struct */
#define GC_TYPE_STRING_DATA 11  /* String data buffer */

/* ========================================================================
 * String Creation Functions
 * ======================================================================== */

/*
 * Create a Coex string from a malloc'd C string, taking ownership.
 *
 * This function:
 * 1. Allocates a CoexString struct on the GC heap
 * 2. Allocates a data buffer on the GC heap
 * 3. Copies the C string data (including null terminator for C interop)
 * 4. Counts UTF-8 codepoints for the len field
 * 5. Frees the original C string
 *
 * Parameters:
 *   c_str - malloc'd null-terminated C string. Ownership is transferred.
 *           The function will free() this pointer after copying.
 *           NULL is allowed and returns NULL.
 *
 * Returns:
 *   Pointer to newly allocated CoexString, or NULL on error/NULL input.
 *   The returned string is GC-managed and should not be freed manually.
 *
 * Thread safety:
 *   Safe to call from any thread. Uses thread-local allocation when available.
 */
CoexString* coex_string_from_cstring_take(char* c_str);

/*
 * Create a Coex string from a C string, copying without freeing.
 *
 * This function:
 * 1. Allocates a CoexString struct on the GC heap
 * 2. Allocates a data buffer on the GC heap
 * 3. Copies the C string data (including null terminator for C interop)
 * 4. Counts UTF-8 codepoints for the len field
 * 5. Does NOT free the original C string (caller retains ownership)
 *
 * Parameters:
 *   c_str - null-terminated C string. Caller retains ownership.
 *           NULL is allowed and returns NULL.
 *
 * Returns:
 *   Pointer to newly allocated CoexString, or NULL on error/NULL input.
 *   The returned string is GC-managed and should not be freed manually.
 *
 * Thread safety:
 *   Safe to call from any thread. Uses thread-local allocation when available.
 */
CoexString* coex_string_from_cstring_copy(const char* c_str);

/*
 * Create a Coex string from a byte buffer with known length.
 *
 * This function:
 * 1. Allocates a CoexString struct on the GC heap
 * 2. Allocates a data buffer on the GC heap (size + 1 for null terminator)
 * 3. Copies the byte data
 * 4. Adds null terminator for C interop
 * 5. Counts UTF-8 codepoints for the len field
 *
 * Parameters:
 *   data - pointer to byte data (does not need to be null-terminated)
 *   byte_len - number of bytes to copy
 *
 * Returns:
 *   Pointer to newly allocated CoexString, or NULL on error.
 *
 * Thread safety:
 *   Safe to call from any thread. Uses thread-local allocation when available.
 */
CoexString* coex_string_from_raw_bytes(const char* data, size_t byte_len);

/*
 * Get the raw data pointer from a CoexString.
 *
 * Returns pointer to the string's byte data at its offset.
 * The data is null-terminated for C interop.
 *
 * Parameters:
 *   str - pointer to CoexString
 *
 * Returns:
 *   Pointer to string data, or NULL if str is NULL.
 */
const char* coex_string_get_data(const CoexString* str);

/*
 * Get the byte length of a CoexString.
 */
int64_t coex_string_get_size(const CoexString* str);

/*
 * Get the codepoint length of a CoexString.
 */
int64_t coex_string_get_len(const CoexString* str);

/* ========================================================================
 * UTF-8 Utilities
 * ======================================================================== */

/*
 * Count UTF-8 codepoints in a byte buffer.
 *
 * Parameters:
 *   data - pointer to UTF-8 encoded bytes
 *   byte_len - number of bytes
 *
 * Returns:
 *   Number of UTF-8 codepoints (characters).
 */
int64_t coex_utf8_codepoint_count(const char* data, size_t byte_len);

#ifdef __cplusplus
}
#endif

#endif /* COEX_STRING_H */
