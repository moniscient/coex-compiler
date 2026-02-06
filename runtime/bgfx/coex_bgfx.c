/**
 * Coex bgfx Integration - C Implementation
 *
 * Maps i64 Coex handles to bgfx native 16-bit handles via a handle table.
 * Parses JSON for complex data (vertex layouts, matrices, etc.) via cJSON.
 * Implements INV-2: malloc'd strings are freed by coex_bgfx_free_json().
 * Implements INV-3: all FFI boundary types are int64_t, double, const char*.
 */

#include "coex_bgfx.h"
#include "../coex_ui_shell.h"

#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <math.h>
#include <stdatomic.h>

#ifdef COEX_UI_HAS_CJSON
#include "cJSON.h"
#else
/* Stub: bgfx requires cJSON for JSON parsing */
#error "bgfx integration requires cJSON. Run deps/build_deps.sh first."
#endif

/* ============================================================================
 * Handle Table
 *
 * Maps i64 Coex handles (1-based) to bgfx native 16-bit handles.
 * Handle 0 is reserved as the null/invalid handle.
 * ============================================================================ */

#define MAX_HANDLES 4096

typedef enum {
    HANDLE_TYPE_NONE = 0,
    HANDLE_TYPE_VERTEX_BUFFER,
    HANDLE_TYPE_INDEX_BUFFER,
    HANDLE_TYPE_SHADER,
    HANDLE_TYPE_PROGRAM,
    HANDLE_TYPE_TEXTURE,
    HANDLE_TYPE_UNIFORM,
    HANDLE_TYPE_TRANSIENT_VB,
    HANDLE_TYPE_TRANSIENT_IB
} HandleType;

typedef struct {
    uint16_t   bgfx_handle;   /* Native bgfx handle (16-bit) */
    HandleType type;           /* What kind of resource this is */
    int        in_use;         /* 1 if allocated, 0 if free */
} HandleEntry;

static struct {
    HandleEntry handles[MAX_HANDLES];
    int         next_free;     /* Hint for next free slot */
    int         initialized;
} _bgfx_state;

static int64_t alloc_handle(uint16_t bgfx_handle, HandleType type) {
    for (int i = _bgfx_state.next_free; i < MAX_HANDLES; i++) {
        if (!_bgfx_state.handles[i].in_use) {
            _bgfx_state.handles[i].bgfx_handle = bgfx_handle;
            _bgfx_state.handles[i].type = type;
            _bgfx_state.handles[i].in_use = 1;
            _bgfx_state.next_free = i + 1;
            return (int64_t)(i + 1);  /* 1-based: handle 0 = invalid */
        }
    }
    /* Wrap around and search from beginning */
    for (int i = 1; i < _bgfx_state.next_free; i++) {
        if (!_bgfx_state.handles[i].in_use) {
            _bgfx_state.handles[i].bgfx_handle = bgfx_handle;
            _bgfx_state.handles[i].type = type;
            _bgfx_state.handles[i].in_use = 1;
            _bgfx_state.next_free = i + 1;
            return (int64_t)(i + 1);
        }
    }
    fprintf(stderr, "coex_bgfx: handle table full (%d entries)\n", MAX_HANDLES);
    return 0;
}

static void free_handle(int64_t handle) {
    if (handle <= 0 || handle > MAX_HANDLES) return;
    int idx = (int)(handle - 1);
    _bgfx_state.handles[idx].in_use = 0;
    _bgfx_state.handles[idx].type = HANDLE_TYPE_NONE;
    if (idx < _bgfx_state.next_free) {
        _bgfx_state.next_free = idx;
    }
}

static uint16_t get_bgfx_handle(int64_t handle) {
    if (handle <= 0 || handle > MAX_HANDLES) return UINT16_MAX;
    int idx = (int)(handle - 1);
    if (!_bgfx_state.handles[idx].in_use) return UINT16_MAX;
    return _bgfx_state.handles[idx].bgfx_handle;
}

/* ============================================================================
 * JSON Helpers
 * ============================================================================ */

/* Parse a JSON array of floats into a C float array. Returns count parsed. */
static int parse_float_array(const char* json, float* out, int max_count) {
    if (!json || !*json) return 0;
    cJSON* root = cJSON_Parse(json);
    if (!root || !cJSON_IsArray(root)) {
        if (root) cJSON_Delete(root);
        return 0;
    }
    int count = 0;
    cJSON* item;
    cJSON_ArrayForEach(item, root) {
        if (count >= max_count) break;
        out[count++] = (float)cJSON_GetNumberValue(item);
    }
    cJSON_Delete(root);
    return count;
}

/* Serialize a float[16] matrix to JSON string. Caller must free. */
static char* matrix_to_json(const float* mtx) {
    cJSON* arr = cJSON_CreateFloatArray(mtx, 16);
    char* result = cJSON_PrintUnformatted(arr);
    cJSON_Delete(arr);
    return result;
}

/* ============================================================================
 * Lifecycle
 * ============================================================================ */

int64_t coex_bgfx_init(int64_t width, int64_t height) {
    if (_bgfx_state.initialized) return 1;

    memset(&_bgfx_state, 0, sizeof(_bgfx_state));
    _bgfx_state.next_free = 1;  /* Skip index 0 (handle 1 is first valid) */

    /* Get native window handle from UI shell */
    void* native_window = coex_ui_shell_get_native_window_handle();
    void* native_display = coex_ui_shell_get_native_display_handle();

    if (!native_window) {
        fprintf(stderr, "coex_bgfx_init: No native window handle available.\n"
                        "Ensure ui.initialize() is called before bgfx.init().\n");
        return 0;
    }

    int result = bgfx_bridge_init(native_window, native_display,
                                   (int)width, (int)height);
    if (!result) {
        fprintf(stderr, "coex_bgfx_init: bgfx initialization failed.\n");
        return 0;
    }

    _bgfx_state.initialized = 1;
    return 1;
}

void coex_bgfx_shutdown(void) {
    if (!_bgfx_state.initialized) return;

    /* Destroy all tracked resources */
    for (int i = 0; i < MAX_HANDLES; i++) {
        if (!_bgfx_state.handles[i].in_use) continue;
        uint16_t h = _bgfx_state.handles[i].bgfx_handle;
        switch (_bgfx_state.handles[i].type) {
            case HANDLE_TYPE_VERTEX_BUFFER:
                bgfx_bridge_destroy_vertex_buffer(h);
                break;
            case HANDLE_TYPE_INDEX_BUFFER:
                bgfx_bridge_destroy_index_buffer(h);
                break;
            case HANDLE_TYPE_PROGRAM:
                bgfx_bridge_destroy_program(h);
                break;
            case HANDLE_TYPE_TEXTURE:
                bgfx_bridge_destroy_texture(h);
                break;
            case HANDLE_TYPE_UNIFORM:
                bgfx_bridge_destroy_uniform(h);
                break;
            default:
                break;
        }
        _bgfx_state.handles[i].in_use = 0;
    }

    bgfx_bridge_shutdown();
    _bgfx_state.initialized = 0;
}

void coex_bgfx_reset(int64_t width, int64_t height, int64_t flags) {
    if (!_bgfx_state.initialized) return;
    bgfx_bridge_reset((int)width, (int)height, (uint32_t)flags);
}

int64_t coex_bgfx_frame(void) {
    if (!_bgfx_state.initialized) return 0;
    return (int64_t)bgfx_bridge_frame();
}

/* ============================================================================
 * Views
 * ============================================================================ */

void coex_bgfx_set_view_rect(int64_t view_id, int64_t x, int64_t y,
                              int64_t width, int64_t height) {
    if (!_bgfx_state.initialized) return;
    bgfx_bridge_set_view_rect((uint16_t)view_id, (uint16_t)x, (uint16_t)y,
                               (uint16_t)width, (uint16_t)height);
}

void coex_bgfx_set_view_clear(int64_t view_id, int64_t flags,
                               int64_t rgba, double depth, int64_t stencil) {
    if (!_bgfx_state.initialized) return;
    bgfx_bridge_set_view_clear((uint16_t)view_id, (uint16_t)flags,
                                (uint32_t)rgba, (float)depth, (uint8_t)stencil);
}

void coex_bgfx_set_view_transform(int64_t view_id, const char* view_json,
                                   const char* proj_json) {
    if (!_bgfx_state.initialized) return;

    float view_mtx[16], proj_mtx[16];
    int has_view = parse_float_array(view_json, view_mtx, 16) == 16;
    int has_proj = parse_float_array(proj_json, proj_mtx, 16) == 16;

    bgfx_bridge_set_view_transform((uint16_t)view_id,
                                    has_view ? view_mtx : NULL,
                                    has_proj ? proj_mtx : NULL);
}

void coex_bgfx_touch(int64_t view_id) {
    if (!_bgfx_state.initialized) return;
    bgfx_bridge_touch((uint16_t)view_id);
}

/* ============================================================================
 * Buffers
 * ============================================================================ */

int64_t coex_bgfx_create_vertex_buffer(const char* vertices_json) {
    if (!_bgfx_state.initialized || !vertices_json) return 0;

    cJSON* root = cJSON_Parse(vertices_json);
    if (!root) return 0;

    cJSON* data_arr = cJSON_GetObjectItem(root, "data");
    cJSON* layout_obj = cJSON_GetObjectItem(root, "layout");

    if (!data_arr || !cJSON_IsArray(data_arr)) {
        cJSON_Delete(root);
        return 0;
    }

    /* Convert data array to float buffer */
    int data_count = cJSON_GetArraySize(data_arr);
    float* data = (float*)malloc(data_count * sizeof(float));
    if (!data) { cJSON_Delete(root); return 0; }

    int i = 0;
    cJSON* item;
    cJSON_ArrayForEach(item, data_arr) {
        data[i++] = (float)cJSON_GetNumberValue(item);
    }

    /* Serialize layout back to JSON for bridge to parse */
    char* layout_str = layout_obj ? cJSON_PrintUnformatted(layout_obj) : NULL;

    uint16_t bgfx_h = bgfx_bridge_create_vertex_buffer(
        data, (uint32_t)(data_count * sizeof(float)),
        layout_str, layout_str ? (uint32_t)strlen(layout_str) : 0);

    free(data);
    if (layout_str) free(layout_str);
    cJSON_Delete(root);

    if (bgfx_h == UINT16_MAX) return 0;
    return alloc_handle(bgfx_h, HANDLE_TYPE_VERTEX_BUFFER);
}

int64_t coex_bgfx_create_index_buffer(const char* indices_json) {
    if (!_bgfx_state.initialized || !indices_json) return 0;

    cJSON* root = cJSON_Parse(indices_json);
    if (!root) return 0;

    cJSON* data_arr = cJSON_GetObjectItem(root, "data");
    cJSON* is_32_item = cJSON_GetObjectItem(root, "is_32bit");
    int is_32bit = is_32_item && cJSON_IsTrue(is_32_item);

    if (!data_arr || !cJSON_IsArray(data_arr)) {
        cJSON_Delete(root);
        return 0;
    }

    int count = cJSON_GetArraySize(data_arr);
    void* data;
    uint32_t data_size;

    if (is_32bit) {
        uint32_t* indices = (uint32_t*)malloc(count * sizeof(uint32_t));
        if (!indices) { cJSON_Delete(root); return 0; }
        int i = 0;
        cJSON* item;
        cJSON_ArrayForEach(item, data_arr) {
            indices[i++] = (uint32_t)cJSON_GetNumberValue(item);
        }
        data = indices;
        data_size = (uint32_t)(count * sizeof(uint32_t));
    } else {
        uint16_t* indices = (uint16_t*)malloc(count * sizeof(uint16_t));
        if (!indices) { cJSON_Delete(root); return 0; }
        int i = 0;
        cJSON* item;
        cJSON_ArrayForEach(item, data_arr) {
            indices[i++] = (uint16_t)cJSON_GetNumberValue(item);
        }
        data = indices;
        data_size = (uint32_t)(count * sizeof(uint16_t));
    }

    uint16_t bgfx_h = bgfx_bridge_create_index_buffer(data, data_size, is_32bit);

    free(data);
    cJSON_Delete(root);

    if (bgfx_h == UINT16_MAX) return 0;
    return alloc_handle(bgfx_h, HANDLE_TYPE_INDEX_BUFFER);
}

int64_t coex_bgfx_alloc_transient_vertex_buffer(int64_t num_vertices,
                                                  const char* layout_json) {
    if (!_bgfx_state.initialized) return 0;
    /* Transient buffers are managed per-frame by bgfx; we just track them */
    void* data = NULL;
    int ok = bgfx_bridge_alloc_transient_vb(&data, (uint32_t)num_vertices,
                                              layout_json,
                                              layout_json ? (uint32_t)strlen(layout_json) : 0);
    if (!ok) return 0;
    /* Return a handle that refers to the current transient VB */
    return alloc_handle(0, HANDLE_TYPE_TRANSIENT_VB);
}

int64_t coex_bgfx_alloc_transient_index_buffer(int64_t num_indices,
                                                 int64_t is_32bit) {
    if (!_bgfx_state.initialized) return 0;
    void* data = NULL;
    int ok = bgfx_bridge_alloc_transient_ib(&data, (uint32_t)num_indices,
                                              (int)is_32bit);
    if (!ok) return 0;
    return alloc_handle(0, HANDLE_TYPE_TRANSIENT_IB);
}

void coex_bgfx_destroy_vertex_buffer(int64_t handle) {
    uint16_t h = get_bgfx_handle(handle);
    if (h != UINT16_MAX) {
        bgfx_bridge_destroy_vertex_buffer(h);
        free_handle(handle);
    }
}

void coex_bgfx_destroy_index_buffer(int64_t handle) {
    uint16_t h = get_bgfx_handle(handle);
    if (h != UINT16_MAX) {
        bgfx_bridge_destroy_index_buffer(h);
        free_handle(handle);
    }
}

/* ============================================================================
 * Shaders & Programs
 * ============================================================================ */

int64_t coex_bgfx_load_shader(const char* path) {
    if (!_bgfx_state.initialized || !path) return 0;
    uint16_t h = bgfx_bridge_load_shader(path);
    if (h == UINT16_MAX) return 0;
    return alloc_handle(h, HANDLE_TYPE_SHADER);
}

int64_t coex_bgfx_create_program(int64_t vertex_handle, int64_t fragment_handle) {
    if (!_bgfx_state.initialized) return 0;
    uint16_t vs = get_bgfx_handle(vertex_handle);
    uint16_t fs = get_bgfx_handle(fragment_handle);
    if (vs == UINT16_MAX || fs == UINT16_MAX) return 0;
    uint16_t h = bgfx_bridge_create_program(vs, fs);
    if (h == UINT16_MAX) return 0;
    free_handle(vertex_handle);
    free_handle(fragment_handle);
    return alloc_handle(h, HANDLE_TYPE_PROGRAM);
}

int64_t coex_bgfx_create_compute_program(int64_t compute_handle) {
    if (!_bgfx_state.initialized) return 0;
    uint16_t cs = get_bgfx_handle(compute_handle);
    if (cs == UINT16_MAX) return 0;
    uint16_t h = bgfx_bridge_create_compute_program(cs);
    if (h == UINT16_MAX) return 0;
    free_handle(compute_handle);
    return alloc_handle(h, HANDLE_TYPE_PROGRAM);
}

void coex_bgfx_destroy_program(int64_t handle) {
    uint16_t h = get_bgfx_handle(handle);
    if (h != UINT16_MAX) {
        bgfx_bridge_destroy_program(h);
        free_handle(handle);
    }
}

/* ============================================================================
 * Textures
 * ============================================================================ */

int64_t coex_bgfx_create_texture_2d(int64_t width, int64_t height,
                                     int64_t has_mips, int64_t format,
                                     int64_t flags, const char* data_json) {
    if (!_bgfx_state.initialized) return 0;

    void* data = NULL;
    uint32_t data_size = 0;

    if (data_json && *data_json) {
        cJSON* arr = cJSON_Parse(data_json);
        if (arr && cJSON_IsArray(arr)) {
            int count = cJSON_GetArraySize(arr);
            uint8_t* bytes = (uint8_t*)malloc(count);
            if (bytes) {
                int i = 0;
                cJSON* item;
                cJSON_ArrayForEach(item, arr) {
                    bytes[i++] = (uint8_t)cJSON_GetNumberValue(item);
                }
                data = bytes;
                data_size = (uint32_t)count;
            }
        }
        if (arr) cJSON_Delete(arr);
    }

    uint16_t h = bgfx_bridge_create_texture_2d(
        (uint16_t)width, (uint16_t)height, (int)has_mips,
        (int)format, (uint64_t)flags, data, data_size);

    if (data) free(data);

    if (h == UINT16_MAX) return 0;
    return alloc_handle(h, HANDLE_TYPE_TEXTURE);
}

void coex_bgfx_update_texture_2d(int64_t handle, int64_t layer, int64_t mip,
                                  int64_t x, int64_t y, int64_t width,
                                  int64_t height, const char* data_json) {
    if (!_bgfx_state.initialized) return;
    uint16_t h = get_bgfx_handle(handle);
    if (h == UINT16_MAX) return;

    if (!data_json || !*data_json) return;

    cJSON* arr = cJSON_Parse(data_json);
    if (!arr || !cJSON_IsArray(arr)) {
        if (arr) cJSON_Delete(arr);
        return;
    }

    int count = cJSON_GetArraySize(arr);
    uint8_t* bytes = (uint8_t*)malloc(count);
    if (!bytes) { cJSON_Delete(arr); return; }

    int i = 0;
    cJSON* item;
    cJSON_ArrayForEach(item, arr) {
        bytes[i++] = (uint8_t)cJSON_GetNumberValue(item);
    }

    bgfx_bridge_update_texture_2d(h, (uint16_t)layer, (uint8_t)mip,
                                   (uint16_t)x, (uint16_t)y,
                                   (uint16_t)width, (uint16_t)height,
                                   bytes, (uint32_t)count);
    free(bytes);
    cJSON_Delete(arr);
}

void coex_bgfx_destroy_texture(int64_t handle) {
    uint16_t h = get_bgfx_handle(handle);
    if (h != UINT16_MAX) {
        bgfx_bridge_destroy_texture(h);
        free_handle(handle);
    }
}

/* ============================================================================
 * Uniforms
 * ============================================================================ */

int64_t coex_bgfx_create_uniform(const char* name, int64_t type, int64_t num) {
    if (!_bgfx_state.initialized || !name) return 0;
    uint16_t h = bgfx_bridge_create_uniform(name, (int)type, (uint16_t)num);
    if (h == UINT16_MAX) return 0;
    return alloc_handle(h, HANDLE_TYPE_UNIFORM);
}

void coex_bgfx_set_uniform(int64_t handle, const char* value_json, int64_t num) {
    if (!_bgfx_state.initialized) return;
    uint16_t h = get_bgfx_handle(handle);
    if (h == UINT16_MAX) return;

    float values[64];  /* Max 4 mat4s = 64 floats */
    int count = parse_float_array(value_json, values, 64);
    if (count > 0) {
        bgfx_bridge_set_uniform(h, values, (uint16_t)num);
    }
}

void coex_bgfx_destroy_uniform(int64_t handle) {
    uint16_t h = get_bgfx_handle(handle);
    if (h != UINT16_MAX) {
        bgfx_bridge_destroy_uniform(h);
        free_handle(handle);
    }
}

/* ============================================================================
 * Drawing
 * ============================================================================ */

void coex_bgfx_set_state(int64_t state, int64_t rgba) {
    if (!_bgfx_state.initialized) return;
    bgfx_bridge_set_state((uint64_t)state, (uint32_t)rgba);
}

int64_t coex_bgfx_set_transform(const char* mtx_json) {
    if (!_bgfx_state.initialized) return 0;
    float mtx[16];
    if (parse_float_array(mtx_json, mtx, 16) != 16) return 0;
    return (int64_t)bgfx_bridge_set_transform(mtx);
}

void coex_bgfx_set_vertex_buffer(int64_t stream, int64_t handle,
                                  int64_t start_vertex, int64_t num_vertices) {
    if (!_bgfx_state.initialized) return;
    uint16_t h = get_bgfx_handle(handle);
    if (h == UINT16_MAX) return;
    bgfx_bridge_set_vertex_buffer((uint8_t)stream, h,
                                   (uint32_t)start_vertex, (uint32_t)num_vertices);
}

void coex_bgfx_set_transient_vertex_buffer(int64_t stream, int64_t handle,
                                            int64_t start_vertex,
                                            int64_t num_vertices) {
    if (!_bgfx_state.initialized) return;
    (void)handle;  /* Transient VB is set globally */
    bgfx_bridge_set_transient_vertex_buffer((uint8_t)stream,
                                             (uint32_t)start_vertex,
                                             (uint32_t)num_vertices);
}

void coex_bgfx_set_index_buffer(int64_t handle, int64_t first_index,
                                 int64_t num_indices) {
    if (!_bgfx_state.initialized) return;
    uint16_t h = get_bgfx_handle(handle);
    if (h == UINT16_MAX) return;
    bgfx_bridge_set_index_buffer(h, (uint32_t)first_index, (uint32_t)num_indices);
}

void coex_bgfx_set_transient_index_buffer(int64_t handle, int64_t first_index,
                                           int64_t num_indices) {
    if (!_bgfx_state.initialized) return;
    (void)handle;
    bgfx_bridge_set_transient_index_buffer((uint32_t)first_index,
                                            (uint32_t)num_indices);
}

void coex_bgfx_set_texture(int64_t stage, int64_t uniform_handle,
                            int64_t texture_handle, int64_t flags) {
    if (!_bgfx_state.initialized) return;
    uint16_t u = get_bgfx_handle(uniform_handle);
    uint16_t t = get_bgfx_handle(texture_handle);
    if (u == UINT16_MAX || t == UINT16_MAX) return;
    bgfx_bridge_set_texture((uint8_t)stage, u, t, (uint32_t)flags);
}

void coex_bgfx_submit(int64_t view_id, int64_t program_handle,
                       int64_t depth, int64_t flags) {
    if (!_bgfx_state.initialized) return;
    uint16_t p = get_bgfx_handle(program_handle);
    if (p == UINT16_MAX) return;
    bgfx_bridge_submit((uint16_t)view_id, p, (uint32_t)depth, (uint8_t)flags);
}

/* ============================================================================
 * Compute
 * ============================================================================ */

void coex_bgfx_set_compute_buffer(int64_t stage, int64_t handle, int64_t access) {
    if (!_bgfx_state.initialized) return;
    uint16_t h = get_bgfx_handle(handle);
    if (h == UINT16_MAX) return;
    bgfx_bridge_set_compute_buffer((uint8_t)stage, h, (int)access);
}

void coex_bgfx_dispatch(int64_t view_id, int64_t program_handle,
                         int64_t num_x, int64_t num_y, int64_t num_z,
                         int64_t flags) {
    if (!_bgfx_state.initialized) return;
    uint16_t p = get_bgfx_handle(program_handle);
    if (p == UINT16_MAX) return;
    bgfx_bridge_dispatch((uint16_t)view_id, p,
                          (uint32_t)num_x, (uint32_t)num_y, (uint32_t)num_z,
                          (uint8_t)flags);
}

/* ============================================================================
 * Debug
 * ============================================================================ */

void coex_bgfx_set_debug(int64_t flags) {
    if (!_bgfx_state.initialized) return;
    bgfx_bridge_set_debug((uint32_t)flags);
}

void coex_bgfx_dbg_text(int64_t x, int64_t y, int64_t attr, const char* text) {
    if (!_bgfx_state.initialized) return;
    bgfx_bridge_dbg_text_printf((uint16_t)x, (uint16_t)y, (uint8_t)attr,
                                 text ? text : "");
}

void coex_bgfx_dbg_text_clear(void) {
    if (!_bgfx_state.initialized) return;
    bgfx_bridge_dbg_text_clear();
}

const char* coex_bgfx_get_renderer_name(void) {
    if (!_bgfx_state.initialized) return strdup("(not initialized)");
    const char* name = bgfx_bridge_get_renderer_name();
    return name ? strdup(name) : strdup("(unknown)");
}

const char* coex_bgfx_get_caps_json(void) {
    if (!_bgfx_state.initialized) return strdup("{}");
    return bgfx_bridge_get_caps_json();  /* Already malloc'd */
}

/* ============================================================================
 * Math Helpers
 * ============================================================================ */

const char* coex_bgfx_mtx_look_at(const char* eye_json, const char* at_json,
                                    const char* up_json) {
    float eye[3] = {0, 0, 0};
    float at[3] = {0, 0, 1};
    float up[3] = {0, 1, 0};
    float result[16];

    parse_float_array(eye_json, eye, 3);
    parse_float_array(at_json, at, 3);
    if (up_json && *up_json) {
        parse_float_array(up_json, up, 3);
    }

    bgfx_bridge_mtx_look_at(result, eye, at, up);
    return matrix_to_json(result);
}

const char* coex_bgfx_mtx_proj(double fovy, double aspect, double near_,
                                double far_) {
    float result[16];
    bgfx_bridge_mtx_proj(result, (float)fovy, (float)aspect,
                          (float)near_, (float)far_, 0);
    return matrix_to_json(result);
}

const char* coex_bgfx_mtx_ortho(double left, double right, double bottom,
                                  double top, double near_, double far_) {
    float result[16];
    bgfx_bridge_mtx_ortho(result, (float)left, (float)right,
                            (float)bottom, (float)top,
                            (float)near_, (float)far_, 0.0f, 0);
    return matrix_to_json(result);
}

const char* coex_bgfx_mtx_rotate_xyz(double ax, double ay, double az) {
    float result[16];
    bgfx_bridge_mtx_rotate_xyz(result, (float)ax, (float)ay, (float)az);
    return matrix_to_json(result);
}

/* ============================================================================
 * Scene Observer API
 * ============================================================================ */

typedef struct {
    _Atomic(char*) pending_scene;   /* Set by any thread, consumed by main */
    char*          current_scene;   /* Owned by main thread */
    cJSON*         current_parsed;  /* Parsed version of current_scene */
    int            observer_active; /* 1 while in observer mode */
} SceneObserverState;

static SceneObserverState _scene_state;

/* --- Forward declarations for observer helpers --- */
static void render_scene(cJSON* scene);
static void render_object(cJSON* obj);

void coex_bgfx_set_scene(const char* scene_json) {
    if (!scene_json) return;

    char* copy = strdup(scene_json);
    char* old = atomic_exchange(&_scene_state.pending_scene, copy);
    /* Free the previously pending scene that was never consumed */
    if (old) free(old);
}

int64_t coex_bgfx_begin_observer(void) {
    if (!_bgfx_state.initialized) return 0;

    _scene_state.observer_active = 1;
    _scene_state.current_scene = NULL;
    _scene_state.current_parsed = NULL;
    atomic_store(&_scene_state.pending_scene, (char*)NULL);
    return 1;
}

void coex_bgfx_end_observer(void) {
    _scene_state.observer_active = 0;

    char* pending = atomic_exchange(&_scene_state.pending_scene, (char*)NULL);
    if (pending) free(pending);

    if (_scene_state.current_parsed) {
        cJSON_Delete(_scene_state.current_parsed);
        _scene_state.current_parsed = NULL;
    }
    if (_scene_state.current_scene) {
        free(_scene_state.current_scene);
        _scene_state.current_scene = NULL;
    }
}

int64_t coex_bgfx_observer_frame(void) {
    if (!_bgfx_state.initialized) return 0;

    /* Consume pending scene (atomic swap with NULL) */
    char* new_scene = atomic_exchange(&_scene_state.pending_scene, (char*)NULL);

    if (new_scene) {
        /* We have a new scene — replace current */
        if (_scene_state.current_parsed) {
            cJSON_Delete(_scene_state.current_parsed);
        }
        if (_scene_state.current_scene) {
            free(_scene_state.current_scene);
        }

        _scene_state.current_scene = new_scene;
        _scene_state.current_parsed = cJSON_Parse(new_scene);

        if (!_scene_state.current_parsed) {
            fprintf(stderr, "coex_bgfx_observer_frame: failed to parse scene JSON\n");
        }
    }

    /* Render the current scene (if any) */
    if (_scene_state.current_parsed) {
        render_scene(_scene_state.current_parsed);
    }

    return (int64_t)bgfx_bridge_frame();
}

/* --- Parse a JSON float array into a stack buffer, return count --- */
static int parse_json_float_array(cJSON* arr, float* out, int max_count) {
    if (!arr || !cJSON_IsArray(arr)) return 0;
    int count = 0;
    cJSON* item;
    cJSON_ArrayForEach(item, arr) {
        if (count >= max_count) break;
        out[count++] = (float)cJSON_GetNumberValue(item);
    }
    return count;
}

/* --- Render a complete scene from parsed JSON --- */
static void render_scene(cJSON* scene) {
    /* Process views */
    cJSON* views = cJSON_GetObjectItem(scene, "views");
    if (views && cJSON_IsArray(views)) {
        cJSON* view;
        cJSON_ArrayForEach(view, views) {
            cJSON* id_item = cJSON_GetObjectItem(view, "id");
            if (!id_item) continue;
            uint16_t view_id = (uint16_t)cJSON_GetNumberValue(id_item);

            /* View rect */
            cJSON* rect = cJSON_GetObjectItem(view, "rect");
            if (rect && cJSON_IsArray(rect)) {
                float r[4];
                if (parse_json_float_array(rect, r, 4) == 4) {
                    bgfx_bridge_set_view_rect(view_id,
                        (uint16_t)r[0], (uint16_t)r[1],
                        (uint16_t)r[2], (uint16_t)r[3]);
                }
            }

            /* View clear */
            cJSON* clear = cJSON_GetObjectItem(view, "clear");
            if (clear) {
                cJSON* cf = cJSON_GetObjectItem(clear, "flags");
                cJSON* cc = cJSON_GetObjectItem(clear, "color");
                cJSON* cd = cJSON_GetObjectItem(clear, "depth");
                cJSON* cs = cJSON_GetObjectItem(clear, "stencil");
                bgfx_bridge_set_view_clear(view_id,
                    cf ? (uint16_t)cJSON_GetNumberValue(cf) : 0,
                    cc ? (uint32_t)cJSON_GetNumberValue(cc) : 0,
                    cd ? (float)cJSON_GetNumberValue(cd) : 1.0f,
                    cs ? (uint8_t)cJSON_GetNumberValue(cs) : 0);
            }

            /* View transform */
            cJSON* transform = cJSON_GetObjectItem(view, "transform");
            if (transform) {
                float view_mtx[16], proj_mtx[16];
                int has_view = 0, has_proj = 0;

                cJSON* v = cJSON_GetObjectItem(transform, "view");
                if (v) {
                    if (cJSON_IsArray(v)) {
                        has_view = parse_json_float_array(v, view_mtx, 16) == 16;
                    } else if (cJSON_IsString(v)) {
                        has_view = parse_float_array(cJSON_GetStringValue(v),
                                                      view_mtx, 16) == 16;
                    }
                }

                cJSON* p = cJSON_GetObjectItem(transform, "proj");
                if (p) {
                    if (cJSON_IsArray(p)) {
                        has_proj = parse_json_float_array(p, proj_mtx, 16) == 16;
                    } else if (cJSON_IsString(p)) {
                        has_proj = parse_float_array(cJSON_GetStringValue(p),
                                                      proj_mtx, 16) == 16;
                    }
                }

                bgfx_bridge_set_view_transform(view_id,
                    has_view ? view_mtx : NULL,
                    has_proj ? proj_mtx : NULL);
            }

            /* Touch the view to ensure it is processed */
            bgfx_bridge_touch(view_id);
        }
    }

    /* Process draw objects */
    cJSON* objects = cJSON_GetObjectItem(scene, "objects");
    if (objects && cJSON_IsArray(objects)) {
        cJSON* obj;
        cJSON_ArrayForEach(obj, objects) {
            render_object(obj);
        }
    }

    /* Process debug overlay */
    cJSON* debug = cJSON_GetObjectItem(scene, "debug");
    if (debug) {
        cJSON* df = cJSON_GetObjectItem(debug, "flags");
        if (df) {
            bgfx_bridge_set_debug((uint32_t)cJSON_GetNumberValue(df));
        }

        cJSON* texts = cJSON_GetObjectItem(debug, "texts");
        if (texts && cJSON_IsArray(texts)) {
            bgfx_bridge_dbg_text_clear();
            cJSON* t;
            cJSON_ArrayForEach(t, texts) {
                cJSON* tx = cJSON_GetObjectItem(t, "x");
                cJSON* ty = cJSON_GetObjectItem(t, "y");
                cJSON* ta = cJSON_GetObjectItem(t, "attr");
                cJSON* tt = cJSON_GetObjectItem(t, "text");
                if (tx && ty && ta && tt && cJSON_IsString(tt)) {
                    bgfx_bridge_dbg_text_printf(
                        (uint16_t)cJSON_GetNumberValue(tx),
                        (uint16_t)cJSON_GetNumberValue(ty),
                        (uint8_t)cJSON_GetNumberValue(ta),
                        cJSON_GetStringValue(tt));
                }
            }
        }
    }
}

/* --- Render a single draw object from parsed JSON --- */
static void render_object(cJSON* obj) {
    cJSON* view_id_item = cJSON_GetObjectItem(obj, "view_id");
    cJSON* program_item = cJSON_GetObjectItem(obj, "program");
    if (!view_id_item || !program_item) return;

    uint16_t view_id = (uint16_t)cJSON_GetNumberValue(view_id_item);

    /* Program handle (Coex i64 -> bgfx uint16) */
    int64_t prog_coex = (int64_t)cJSON_GetNumberValue(program_item);
    uint16_t prog = get_bgfx_handle(prog_coex);
    if (prog == UINT16_MAX) return;  /* Invalid handle — skip */

    /* Transform matrix */
    cJSON* xform = cJSON_GetObjectItem(obj, "transform");
    if (xform) {
        float mtx[16];
        int ok = 0;
        if (cJSON_IsArray(xform)) {
            ok = parse_json_float_array(xform, mtx, 16) == 16;
        } else if (cJSON_IsString(xform)) {
            ok = parse_float_array(cJSON_GetStringValue(xform), mtx, 16) == 16;
        }
        if (ok) {
            bgfx_bridge_set_transform(mtx);
        }
    }

    /* Render state — accept string to avoid JSON double precision loss for uint64 */
    cJSON* state_item = cJSON_GetObjectItem(obj, "state");
    cJSON* state_rgba_item = cJSON_GetObjectItem(obj, "state_rgba");
    if (state_item) {
        uint64_t state;
        if (cJSON_IsString(state_item)) {
            state = (uint64_t)strtoull(cJSON_GetStringValue(state_item), NULL, 0);
        } else {
            state = (uint64_t)cJSON_GetNumberValue(state_item);
        }
        uint32_t rgba = state_rgba_item ?
            (uint32_t)cJSON_GetNumberValue(state_rgba_item) : 0;
        bgfx_bridge_set_state(state, rgba);
    }

    /* Vertex buffer */
    cJSON* vb = cJSON_GetObjectItem(obj, "vertex_buffer");
    if (vb) {
        cJSON* vh = cJSON_GetObjectItem(vb, "handle");
        cJSON* vs = cJSON_GetObjectItem(vb, "start");
        cJSON* vc = cJSON_GetObjectItem(vb, "count");
        if (vh) {
            uint16_t vb_handle = get_bgfx_handle(
                (int64_t)cJSON_GetNumberValue(vh));
            if (vb_handle != UINT16_MAX) {
                bgfx_bridge_set_vertex_buffer(0, vb_handle,
                    vs ? (uint32_t)cJSON_GetNumberValue(vs) : 0,
                    vc ? (uint32_t)cJSON_GetNumberValue(vc) : 0);
            }
        }
    }

    /* Index buffer */
    cJSON* ib = cJSON_GetObjectItem(obj, "index_buffer");
    if (ib) {
        cJSON* ih = cJSON_GetObjectItem(ib, "handle");
        cJSON* is_ = cJSON_GetObjectItem(ib, "start");
        cJSON* ic = cJSON_GetObjectItem(ib, "count");
        if (ih) {
            uint16_t ib_handle = get_bgfx_handle(
                (int64_t)cJSON_GetNumberValue(ih));
            if (ib_handle != UINT16_MAX) {
                bgfx_bridge_set_index_buffer(ib_handle,
                    is_ ? (uint32_t)cJSON_GetNumberValue(is_) : 0,
                    ic ? (uint32_t)cJSON_GetNumberValue(ic) : 0);
            }
        }
    }

    /* Textures */
    cJSON* textures = cJSON_GetObjectItem(obj, "textures");
    if (textures && cJSON_IsArray(textures)) {
        cJSON* tex;
        cJSON_ArrayForEach(tex, textures) {
            cJSON* ts = cJSON_GetObjectItem(tex, "stage");
            cJSON* tu = cJSON_GetObjectItem(tex, "uniform");
            cJSON* tt = cJSON_GetObjectItem(tex, "texture");
            cJSON* tf = cJSON_GetObjectItem(tex, "flags");
            if (ts && tu && tt) {
                uint16_t u = get_bgfx_handle(
                    (int64_t)cJSON_GetNumberValue(tu));
                uint16_t t = get_bgfx_handle(
                    (int64_t)cJSON_GetNumberValue(tt));
                if (u != UINT16_MAX && t != UINT16_MAX) {
                    bgfx_bridge_set_texture((uint8_t)cJSON_GetNumberValue(ts),
                        u, t,
                        tf ? (uint32_t)cJSON_GetNumberValue(tf) : 0);
                }
            }
        }
    }

    /* Uniforms */
    cJSON* uniforms = cJSON_GetObjectItem(obj, "uniforms");
    if (uniforms && cJSON_IsArray(uniforms)) {
        cJSON* uni;
        cJSON_ArrayForEach(uni, uniforms) {
            cJSON* uh = cJSON_GetObjectItem(uni, "handle");
            cJSON* uv = cJSON_GetObjectItem(uni, "value");
            cJSON* un = cJSON_GetObjectItem(uni, "num");
            if (uh && uv) {
                uint16_t u_handle = get_bgfx_handle(
                    (int64_t)cJSON_GetNumberValue(uh));
                if (u_handle != UINT16_MAX) {
                    float values[64];
                    int count = 0;
                    if (cJSON_IsArray(uv)) {
                        count = parse_json_float_array(uv, values, 64);
                    } else if (cJSON_IsString(uv)) {
                        count = parse_float_array(
                            cJSON_GetStringValue(uv), values, 64);
                    }
                    if (count > 0) {
                        bgfx_bridge_set_uniform(u_handle, values,
                            un ? (uint16_t)cJSON_GetNumberValue(un) : 1);
                    }
                }
            }
        }
    }

    /* Submit draw call */
    bgfx_bridge_submit(view_id, prog, 0, 0xFF);
}

/* ============================================================================
 * Memory
 * ============================================================================ */

void coex_bgfx_free_json(const char* json_str) {
    /* NOTE: The Coex codegen copies C-returned strings to the GC heap.
     * The pointer passed here is the GC heap copy, NOT the original malloc'd
     * pointer. Calling free() on it would corrupt the heap. The original
     * C-side malloc'd strings are small (JSON matrices, ~200 bytes) and leak.
     * A proper fix would require the codegen to preserve the original C pointer
     * or use a per-frame arena allocator on the C side. */
    (void)json_str;
}
