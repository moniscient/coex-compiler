/*
 * Coex String Runtime Support Implementation
 *
 * Provides C-side utilities for creating Coex strings from C strings.
 * See coex_string.h for API documentation.
 */

#include "coex_string.h"
#include <stdlib.h>
#include <string.h>
#include <stdio.h>

/* ========================================================================
 * External GC Functions (provided by codegen)
 * ======================================================================== */

/*
 * GC allocation function.
 * Allocates memory on the GC heap.
 *
 * Returns raw pointer (i8*) suitable for C interop.
 */
extern void* coex_gc_alloc_arena_or_gc(int64_t size, int32_t type_id);

/*
 * Get the GC handle for an object from its raw pointer.
 * Reads the handle from the object's header forward field.
 * Returns 0 if ptr is NULL.
 */
extern int64_t coex_gc_ptr_to_handle(void* ptr);

/*
 * Dereference a GC handle to get the current raw pointer.
 * Returns NULL if handle is 0.
 */
extern void* coex_gc_handle_deref(int64_t handle);

/* ========================================================================
 * Internal Helpers
 * ======================================================================== */

/*
 * Count UTF-8 codepoints in a buffer.
 *
 * UTF-8 encoding:
 *   0xxxxxxx - 1 byte (ASCII)
 *   110xxxxx - 2 byte start
 *   1110xxxx - 3 byte start
 *   11110xxx - 4 byte start
 *   10xxxxxx - continuation byte (not counted)
 */
int64_t coex_utf8_codepoint_count(const char* data, size_t byte_len) {
    if (!data || byte_len == 0) {
        return 0;
    }

    int64_t count = 0;
    const unsigned char* p = (const unsigned char*)data;
    const unsigned char* end = p + byte_len;

    while (p < end) {
        unsigned char c = *p;
        if ((c & 0x80) == 0) {
            /* ASCII: 0xxxxxxx */
            count++;
            p++;
        } else if ((c & 0xE0) == 0xC0) {
            /* 2-byte: 110xxxxx */
            count++;
            p += 2;
        } else if ((c & 0xF0) == 0xE0) {
            /* 3-byte: 1110xxxx */
            count++;
            p += 3;
        } else if ((c & 0xF8) == 0xF0) {
            /* 4-byte: 11110xxx */
            count++;
            p += 4;
        } else if ((c & 0xC0) == 0x80) {
            /* Continuation byte (shouldn't happen at start) - skip */
            p++;
        } else {
            /* Invalid UTF-8 - treat as single byte */
            count++;
            p++;
        }
    }

    return count;
}

/*
 * Internal: Create a CoexString from byte data.
 * Does not free the source data.
 */
static CoexString* string_create_internal(const char* data, size_t byte_len) {
    /* Allocate String struct (32 bytes) */
    CoexString* str = (CoexString*)coex_gc_alloc_arena_or_gc(
        sizeof(CoexString), GC_TYPE_STRING);
    if (!str) {
        return NULL;
    }

    /* Save handle for str BEFORE second allocation.
     * The second GC allocation can trigger compaction, moving str. */
    int64_t str_handle = coex_gc_ptr_to_handle(str);

    /* Allocate data buffer (byte_len + 1 for null terminator) */
    size_t alloc_size = byte_len + 1;
    char* data_buf = (char*)coex_gc_alloc_arena_or_gc(
        (int64_t)alloc_size, GC_TYPE_STRING_DATA);
    if (!data_buf) {
        return NULL;
    }

    /* Re-derive str pointer — second alloc may have triggered compaction */
    str = (CoexString*)coex_gc_handle_deref(str_handle);

    /* Get handle for data buffer */
    int64_t data_handle = coex_gc_ptr_to_handle(data_buf);

    /* Copy data */
    if (byte_len > 0) {
        memcpy(data_buf, data, byte_len);
    }
    /* Null terminator for C interop */
    data_buf[byte_len] = '\0';

    /* Count UTF-8 codepoints */
    int64_t codepoint_count = coex_utf8_codepoint_count(data, byte_len);

    /* Initialize String struct — owner_handle stores GC handle, not raw pointer */
    str->owner_handle = data_handle;
    str->offset = 0;
    str->len = codepoint_count;
    str->size = (int64_t)byte_len;

    return str;
}

/* ========================================================================
 * Public API
 * ======================================================================== */

CoexString* coex_string_from_cstring_take(char* c_str) {
    if (!c_str) {
        return NULL;
    }

    size_t byte_len = strlen(c_str);
    CoexString* str = string_create_internal(c_str, byte_len);

    /* Free the original C string (we took ownership) */
    free(c_str);

    return str;
}

CoexString* coex_string_from_cstring_copy(const char* c_str) {
    if (!c_str) {
        return NULL;
    }

    size_t byte_len = strlen(c_str);
    return string_create_internal(c_str, byte_len);
}

CoexString* coex_string_from_raw_bytes(const char* data, size_t byte_len) {
    if (!data && byte_len > 0) {
        return NULL;
    }

    /* Handle empty string case */
    if (byte_len == 0) {
        return string_create_internal("", 0);
    }

    return string_create_internal(data, byte_len);
}

const char* coex_string_get_data(const CoexString* str) {
    if (!str) {
        return NULL;
    }

    /* Get data pointer from owner_handle (GC handle) and apply offset */
    char* base = (char*)coex_gc_handle_deref(str->owner_handle);
    return base + str->offset;
}

int64_t coex_string_get_size(const CoexString* str) {
    if (!str) {
        return 0;
    }
    return str->size;
}

int64_t coex_string_get_len(const CoexString* str) {
    if (!str) {
        return 0;
    }
    return str->len;
}
