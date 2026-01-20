/**
 * coex_blas.c - BLAS wrapper for Coex linear algebra operations
 *
 * This file provides BLAS (Basic Linear Algebra Subprograms) integration
 * for Coex. On macOS, it uses Apple Accelerate framework. On Linux, it
 * can use OpenBLAS. Falls back to reference implementation if no BLAS
 * is available.
 *
 * All functions work with row-major layout (C convention) and handle
 * the conversion to BLAS's column-major expectation internally.
 */

#include <stdint.h>
#include <stdlib.h>
#include <string.h>
#include <stdio.h>
#include <math.h>

#include "coex_array.h"

#ifdef __APPLE__
#include <Accelerate/Accelerate.h>
#define HAVE_BLAS 1
#elif defined(HAVE_OPENBLAS)
#include <cblas.h>
#define HAVE_BLAS 1
#else
#define HAVE_BLAS 0
#endif

/* ========================================================================
 * GEMM - General Matrix Multiply: C = alpha * A * B + beta * C
 * ======================================================================== */

/**
 * Double-precision GEMM (DGEMM)
 *
 * Computes: C = alpha * A * B + beta * C
 *
 * Parameters:
 *   m      - rows of A and C
 *   n      - columns of B and C
 *   k      - columns of A / rows of B
 *   alpha  - scalar multiplier for A*B
 *   a      - matrix A data (row-major, m x k)
 *   b      - matrix B data (row-major, k x n)
 *   beta   - scalar multiplier for C
 *   c      - matrix C data (row-major, m x n) - OUTPUT
 */
void coex_blas_dgemm(
    int64_t m, int64_t n, int64_t k,
    double alpha,
    const double* a,
    const double* b,
    double beta,
    double* c
) {
#if HAVE_BLAS
    /* CBLAS with row-major layout */
    cblas_dgemm(
        CblasRowMajor,    /* Row-major layout (C convention) */
        CblasNoTrans,     /* Don't transpose A */
        CblasNoTrans,     /* Don't transpose B */
        (int)m, (int)n, (int)k,
        alpha,
        a, (int)k,        /* A and its leading dimension (columns for row-major) */
        b, (int)n,        /* B and its leading dimension */
        beta,
        c, (int)n         /* C and its leading dimension */
    );
#else
    /* Reference implementation - O(n^3) triple loop */
    for (int64_t i = 0; i < m; i++) {
        for (int64_t j = 0; j < n; j++) {
            double sum = beta * c[i * n + j];
            for (int64_t p = 0; p < k; p++) {
                sum += alpha * a[i * k + p] * b[p * n + j];
            }
            c[i * n + j] = sum;
        }
    }
#endif
}

/**
 * Single-precision GEMM (SGEMM)
 *
 * Same as DGEMM but uses 32-bit floats for faster GPU execution.
 */
void coex_blas_sgemm(
    int64_t m, int64_t n, int64_t k,
    float alpha,
    const float* a,
    const float* b,
    float beta,
    float* c
) {
#if HAVE_BLAS
    cblas_sgemm(
        CblasRowMajor,
        CblasNoTrans,
        CblasNoTrans,
        (int)m, (int)n, (int)k,
        alpha,
        a, (int)k,
        b, (int)n,
        beta,
        c, (int)n
    );
#else
    /* Reference implementation */
    for (int64_t i = 0; i < m; i++) {
        for (int64_t j = 0; j < n; j++) {
            float sum = beta * c[i * n + j];
            for (int64_t p = 0; p < k; p++) {
                sum += alpha * a[i * k + p] * b[p * n + j];
            }
            c[i * n + j] = sum;
        }
    }
#endif
}

/* ========================================================================
 * High-level matmul wrappers for Coex
 * These handle Array data extraction and result allocation
 * ======================================================================== */

/**
 * Matrix multiply for 2D Arrays: C = A * B
 *
 * Parameters:
 *   a_data     - pointer to A's data buffer
 *   a_rows     - rows of A
 *   a_cols     - columns of A (must equal b_rows)
 *   b_data     - pointer to B's data buffer
 *   b_rows     - rows of B
 *   b_cols     - columns of B
 *   c_data     - pointer to C's data buffer (pre-allocated, a_rows x b_cols)
 *
 * Returns 0 on success, -1 on dimension mismatch.
 */
int64_t coex_matmul_f64(
    const double* a_data, int64_t a_rows, int64_t a_cols,
    const double* b_data, int64_t b_rows, int64_t b_cols,
    double* c_data
) {
    /* Validate dimensions */
    if (a_cols != b_rows) {
        fprintf(stderr, "coex_matmul_f64: dimension mismatch: %lld x %lld cannot multiply %lld x %lld\n",
                (long long)a_rows, (long long)a_cols, (long long)b_rows, (long long)b_cols);
        return -1;
    }

    /* C = 1.0 * A * B + 0.0 * C */
    coex_blas_dgemm(a_rows, b_cols, a_cols, 1.0, a_data, b_data, 0.0, c_data);
    return 0;
}

/**
 * Matrix multiply for 2D Arrays (32-bit): C = A * B
 */
int64_t coex_matmul_f32(
    const float* a_data, int64_t a_rows, int64_t a_cols,
    const float* b_data, int64_t b_rows, int64_t b_cols,
    float* c_data
) {
    if (a_cols != b_rows) {
        fprintf(stderr, "coex_matmul_f32: dimension mismatch\n");
        return -1;
    }

    coex_blas_sgemm(a_rows, b_cols, a_cols, 1.0f, a_data, b_data, 0.0f, c_data);
    return 0;
}

/* ========================================================================
 * DOT Product - Vector inner product
 * ======================================================================== */

/**
 * Double-precision dot product: x · y
 */
double coex_blas_ddot(int64_t n, const double* x, const double* y) {
#if HAVE_BLAS
    return cblas_ddot((int)n, x, 1, y, 1);
#else
    double sum = 0.0;
    for (int64_t i = 0; i < n; i++) {
        sum += x[i] * y[i];
    }
    return sum;
#endif
}

/**
 * Single-precision dot product
 */
float coex_blas_sdot(int64_t n, const float* x, const float* y) {
#if HAVE_BLAS
    return cblas_sdot((int)n, x, 1, y, 1);
#else
    float sum = 0.0f;
    for (int64_t i = 0; i < n; i++) {
        sum += x[i] * y[i];
    }
    return sum;
#endif
}

/* ========================================================================
 * GEMV - Matrix-Vector multiply: y = alpha * A * x + beta * y
 * ======================================================================== */

/**
 * Double-precision matrix-vector multiply
 */
void coex_blas_dgemv(
    int64_t m, int64_t n,
    double alpha,
    const double* a,
    const double* x,
    double beta,
    double* y
) {
#if HAVE_BLAS
    cblas_dgemv(
        CblasRowMajor,
        CblasNoTrans,
        (int)m, (int)n,
        alpha,
        a, (int)n,
        x, 1,
        beta,
        y, 1
    );
#else
    for (int64_t i = 0; i < m; i++) {
        double sum = beta * y[i];
        for (int64_t j = 0; j < n; j++) {
            sum += alpha * a[i * n + j] * x[j];
        }
        y[i] = sum;
    }
#endif
}

/**
 * Single-precision matrix-vector multiply
 */
void coex_blas_sgemv(
    int64_t m, int64_t n,
    float alpha,
    const float* a,
    const float* x,
    float beta,
    float* y
) {
#if HAVE_BLAS
    cblas_sgemv(
        CblasRowMajor,
        CblasNoTrans,
        (int)m, (int)n,
        alpha,
        a, (int)n,
        x, 1,
        beta,
        y, 1
    );
#else
    for (int64_t i = 0; i < m; i++) {
        float sum = beta * y[i];
        for (int64_t j = 0; j < n; j++) {
            sum += alpha * a[i * n + j] * x[j];
        }
        y[i] = sum;
    }
#endif
}

/* ========================================================================
 * AXPY - Scaled vector addition: y = alpha * x + y
 * ======================================================================== */

void coex_blas_daxpy(int64_t n, double alpha, const double* x, double* y) {
#if HAVE_BLAS
    cblas_daxpy((int)n, alpha, x, 1, y, 1);
#else
    for (int64_t i = 0; i < n; i++) {
        y[i] += alpha * x[i];
    }
#endif
}

void coex_blas_saxpy(int64_t n, float alpha, const float* x, float* y) {
#if HAVE_BLAS
    cblas_saxpy((int)n, alpha, x, 1, y, 1);
#else
    for (int64_t i = 0; i < n; i++) {
        y[i] += alpha * x[i];
    }
#endif
}

/* ========================================================================
 * SCAL - Vector scaling: x = alpha * x
 * ======================================================================== */

void coex_blas_dscal(int64_t n, double alpha, double* x) {
#if HAVE_BLAS
    cblas_dscal((int)n, alpha, x, 1);
#else
    for (int64_t i = 0; i < n; i++) {
        x[i] *= alpha;
    }
#endif
}

void coex_blas_sscal(int64_t n, float alpha, float* x) {
#if HAVE_BLAS
    cblas_sscal((int)n, alpha, x, 1);
#else
    for (int64_t i = 0; i < n; i++) {
        x[i] *= alpha;
    }
#endif
}

/* ========================================================================
 * NRM2 - Euclidean norm: ||x||_2
 * ======================================================================== */

double coex_blas_dnrm2(int64_t n, const double* x) {
#if HAVE_BLAS
    return cblas_dnrm2((int)n, x, 1);
#else
    double sum = 0.0;
    for (int64_t i = 0; i < n; i++) {
        sum += x[i] * x[i];
    }
    return sqrt(sum);
#endif
}

float coex_blas_snrm2(int64_t n, const float* x) {
#if HAVE_BLAS
    return cblas_snrm2((int)n, x, 1);
#else
    float sum = 0.0f;
    for (int64_t i = 0; i < n; i++) {
        sum += x[i] * x[i];
    }
    return sqrtf(sum);
#endif
}

/* ========================================================================
 * Utility functions
 * ======================================================================== */

/**
 * Check if BLAS is available (for diagnostics)
 */
int coex_blas_available(void) {
    return HAVE_BLAS;
}

/**
 * Get BLAS backend name
 */
const char* coex_blas_backend(void) {
#ifdef __APPLE__
    return "Accelerate";
#elif defined(HAVE_OPENBLAS)
    return "OpenBLAS";
#else
    return "Reference";
#endif
}

/* ========================================================================
 * High-level Coex Array functions
 * These are called via extern from linalg.coex
 * ======================================================================== */

/**
 * GC allocation function (provided by codegen)
 * We need to allocate Arrays through the GC system.
 * coex_gc_alloc_arena_or_gc returns a raw pointer (i8*), which is
 * suitable for C interop. It uses arena allocation when possible.
 */
extern void* coex_gc_alloc_arena_or_gc(int64_t size, int32_t type_id);

/* GC type IDs (must match codegen) */
#define GC_TYPE_ARRAY 8
#define GC_TYPE_ARRAY_DATA 9

/* Helper macro for allocation */
#define GC_ALLOC(size, type_id) coex_gc_alloc_arena_or_gc((size), (type_id))

/**
 * Matrix multiply for 2D Coex Arrays: C = A @ B
 *
 * Takes two Array pointers for matrices A and B, returns a new Array
 * containing the matrix product.
 *
 * Parameters:
 *   a - pointer to Array struct (2D, float elements)
 *   b - pointer to Array struct (2D, float elements)
 *
 * Returns pointer to newly allocated Array (2D), or NULL on error.
 */
CoexArray* coex_linalg_matmul(const CoexArray* a, const CoexArray* b) {
    /* Validate inputs */
    if (!a || !b) {
        fprintf(stderr, "coex_linalg_matmul: null input array\n");
        return NULL;
    }

    if (a->ndim != 2 || b->ndim != 2) {
        fprintf(stderr, "coex_linalg_matmul: requires 2D arrays, got %lldD and %lldD\n",
                (long long)a->ndim, (long long)b->ndim);
        return NULL;
    }

    int64_t m = a->shape[0];  /* rows of A */
    int64_t k = a->shape[1];  /* cols of A */
    int64_t k2 = b->shape[0]; /* rows of B */
    int64_t n = b->shape[1];  /* cols of B */

    if (k != k2) {
        fprintf(stderr, "coex_linalg_matmul: dimension mismatch: %lld x %lld cannot multiply %lld x %lld\n",
                (long long)m, (long long)k, (long long)k2, (long long)n);
        return NULL;
    }

    /* Get data pointers */
    const double* a_data = (const double*)COEX_ARRAY_DATA_PTR(a);
    const double* b_data = (const double*)COEX_ARRAY_DATA_PTR(b);

    /* Allocate result array via GC */
    CoexArray* c = (CoexArray*)GC_ALLOC(sizeof(CoexArray), GC_TYPE_ARRAY);
    if (!c) {
        fprintf(stderr, "coex_linalg_matmul: failed to allocate result array\n");
        return NULL;
    }

    /* Allocate data buffer via GC */
    int64_t c_size = m * n * sizeof(double);
    double* c_data = (double*)GC_ALLOC(c_size, GC_TYPE_ARRAY_DATA);
    if (!c_data) {
        fprintf(stderr, "coex_linalg_matmul: failed to allocate result data\n");
        return NULL;
    }

    /* Initialize result array struct */
    c->handle = (int64_t)c_data;
    c->ndim = 2;
    c->shape[0] = m;
    c->shape[1] = n;
    c->shape[2] = 0;
    c->shape[3] = 0;
    c->strides[0] = n * sizeof(double);
    c->strides[1] = sizeof(double);
    c->strides[2] = 0;
    c->strides[3] = 0;
    c->offset = 0;
    c->elem_size = sizeof(double);
    c->type_id = COEX_TYPE_FLOAT;

    /* Perform GEMM: C = 1.0 * A * B + 0.0 * C */
    coex_blas_dgemm(m, n, k, 1.0, a_data, b_data, 0.0, c_data);

    return c;
}

/**
 * Matrix multiply (32-bit precision): C = A @ B
 *
 * Input arrays contain 64-bit floats, narrowed to 32-bit for computation,
 * result is widened back to 64-bit.
 */
CoexArray* coex_linalg_matmul32(const CoexArray* a, const CoexArray* b) {
    /* Validate inputs */
    if (!a || !b) {
        fprintf(stderr, "coex_linalg_matmul32: null input array\n");
        return NULL;
    }

    if (a->ndim != 2 || b->ndim != 2) {
        fprintf(stderr, "coex_linalg_matmul32: requires 2D arrays\n");
        return NULL;
    }

    int64_t m = a->shape[0];
    int64_t k = a->shape[1];
    int64_t k2 = b->shape[0];
    int64_t n = b->shape[1];

    if (k != k2) {
        fprintf(stderr, "coex_linalg_matmul32: dimension mismatch\n");
        return NULL;
    }

    /* Get source data (64-bit) */
    const double* a_f64 = (const double*)COEX_ARRAY_DATA_PTR(a);
    const double* b_f64 = (const double*)COEX_ARRAY_DATA_PTR(b);

    /* Allocate temp 32-bit buffers */
    float* a_f32 = malloc(m * k * sizeof(float));
    float* b_f32 = malloc(k * n * sizeof(float));
    float* c_f32 = malloc(m * n * sizeof(float));

    if (!a_f32 || !b_f32 || !c_f32) {
        free(a_f32);
        free(b_f32);
        free(c_f32);
        fprintf(stderr, "coex_linalg_matmul32: allocation failed\n");
        return NULL;
    }

    /* Convert A and B to 32-bit */
    for (int64_t i = 0; i < m * k; i++) {
        a_f32[i] = (float)a_f64[i];
    }
    for (int64_t i = 0; i < k * n; i++) {
        b_f32[i] = (float)b_f64[i];
    }

    /* Perform 32-bit GEMM */
    coex_blas_sgemm(m, n, k, 1.0f, a_f32, b_f32, 0.0f, c_f32);

    /* Allocate result array */
    CoexArray* c = (CoexArray*)GC_ALLOC(sizeof(CoexArray), GC_TYPE_ARRAY);
    int64_t c_size = m * n * sizeof(double);
    double* c_data = (double*)GC_ALLOC(c_size, GC_TYPE_ARRAY_DATA);

    if (!c || !c_data) {
        free(a_f32);
        free(b_f32);
        free(c_f32);
        fprintf(stderr, "coex_linalg_matmul32: result allocation failed\n");
        return NULL;
    }

    /* Initialize result array */
    c->handle = (int64_t)c_data;
    c->ndim = 2;
    c->shape[0] = m;
    c->shape[1] = n;
    c->shape[2] = 0;
    c->shape[3] = 0;
    c->strides[0] = n * sizeof(double);
    c->strides[1] = sizeof(double);
    c->strides[2] = 0;
    c->strides[3] = 0;
    c->offset = 0;
    c->elem_size = sizeof(double);
    c->type_id = COEX_TYPE_FLOAT;

    /* Convert result back to 64-bit */
    for (int64_t i = 0; i < m * n; i++) {
        c_data[i] = (double)c_f32[i];
    }

    /* Free temp buffers */
    free(a_f32);
    free(b_f32);
    free(c_f32);

    return c;
}

/**
 * Dot product for 1D Arrays: x · y
 */
double coex_linalg_dot(const CoexArray* x, const CoexArray* y) {
    if (!x || !y) {
        fprintf(stderr, "coex_linalg_dot: null input\n");
        return 0.0;
    }

    if (x->ndim != 1 || y->ndim != 1) {
        fprintf(stderr, "coex_linalg_dot: requires 1D arrays\n");
        return 0.0;
    }

    int64_t n = x->shape[0];
    if (y->shape[0] != n) {
        fprintf(stderr, "coex_linalg_dot: length mismatch\n");
        return 0.0;
    }

    const double* x_data = (const double*)COEX_ARRAY_DATA_PTR(x);
    const double* y_data = (const double*)COEX_ARRAY_DATA_PTR(y);

    return coex_blas_ddot(n, x_data, y_data);
}

/**
 * Euclidean norm (L2) for 1D Array: ||x||
 */
double coex_linalg_norm(const CoexArray* x) {
    if (!x) {
        fprintf(stderr, "coex_linalg_norm: null input\n");
        return 0.0;
    }

    if (x->ndim != 1) {
        fprintf(stderr, "coex_linalg_norm: requires 1D array\n");
        return 0.0;
    }

    const double* x_data = (const double*)COEX_ARRAY_DATA_PTR(x);
    return coex_blas_dnrm2(x->shape[0], x_data);
}
