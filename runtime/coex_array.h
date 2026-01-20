/**
 * coex_array.h - Coex Array struct definition for C FFI
 *
 * This header defines the Array struct layout used by Coex's codegen.
 * Include this header in runtime C code that needs to work with Arrays.
 */

#ifndef COEX_ARRAY_H
#define COEX_ARRAY_H

#include <stdint.h>

/**
 * Coex N-D Array struct (104 bytes = 13 i64 fields)
 *
 * Layout:
 *   Field 0: handle   - raw pointer to data buffer (stored as i64 via ptrtoint)
 *   Field 1: ndim     - number of dimensions (1, 2, 3, or 4)
 *   Field 2: shape    - dimensions [dim0, dim1, dim2, dim3]
 *   Field 3: strides  - byte strides per dimension
 *   Field 4: offset   - byte offset into buffer (for views)
 *   Field 5: elem_size - element size in bytes (8 for int/float, 1 for byte)
 *   Field 6: type_id  - element type identifier
 *
 * For 1D arrays:
 *   - ndim = 1
 *   - shape[0] = length
 *   - strides[0] = elem_size
 *
 * For 2D arrays (matrices):
 *   - ndim = 2
 *   - shape[0] = rows, shape[1] = cols
 *   - strides[0] = cols * elem_size, strides[1] = elem_size
 */
typedef struct CoexArray {
    int64_t handle;      /* Raw pointer to data buffer (via ptrtoint) */
    int64_t ndim;        /* Number of dimensions */
    int64_t shape[4];    /* Dimensions */
    int64_t strides[4];  /* Byte strides per dimension */
    int64_t offset;      /* Byte offset into buffer (for views) */
    int64_t elem_size;   /* Element size in bytes */
    int64_t type_id;     /* Element type identifier */
} CoexArray;

/* Static assert to verify struct size */
_Static_assert(sizeof(CoexArray) == 104, "CoexArray struct must be 104 bytes");

/* Helper macros for accessing array data */
#define COEX_ARRAY_DATA_PTR(arr) ((void*)((arr)->handle + (arr)->offset))
#define COEX_ARRAY_ROWS(arr) ((arr)->shape[0])
#define COEX_ARRAY_COLS(arr) ((arr)->shape[1])

/* Element type IDs (must match codegen constants) */
#define COEX_TYPE_INT       1   /* 64-bit integer (i64) */
#define COEX_TYPE_FLOAT     2   /* 64-bit float (f64) */
#define COEX_TYPE_BOOL      3   /* boolean (i8) */
#define COEX_TYPE_BYTE      4   /* byte (i8) */
#define COEX_TYPE_INT32     5   /* 32-bit integer (i32) */
#define COEX_TYPE_FLOAT32   6   /* 32-bit float (f32) */

#endif /* COEX_ARRAY_H */
