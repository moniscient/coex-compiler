/**
 * Coex bgfx C++ Bridge
 *
 * Thin extern "C" wrapper around the bgfx C99 API.
 * Called by coex_bgfx.c; translates between C types and bgfx types.
 */

#include "coex_bgfx.h"

#include <bgfx/bgfx.h>
#include <bgfx/platform.h>
#include <bx/math.h>

#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <math.h>

#ifdef COEX_UI_HAS_CJSON
extern "C" {
#include "cJSON.h"
}
#endif

/* Current transient buffers (one of each active per frame) */
static bgfx::TransientVertexBuffer s_tvb;
static bgfx::TransientIndexBuffer  s_tib;
static int s_tvb_valid = 0;
static int s_tib_valid = 0;

/* ============================================================================
 * Vertex Layout Parsing
 *
 * Parses JSON layout specifications into bgfx::VertexLayout.
 * Format: { "attribs": [{"name":"Position","type":"Float","num":3}, ...] }
 * ============================================================================ */

static bgfx::Attrib::Enum parse_attrib_name(const char* name) {
    if (!name) return bgfx::Attrib::Count;
    if (strcmp(name, "Position") == 0) return bgfx::Attrib::Position;
    if (strcmp(name, "Normal") == 0)   return bgfx::Attrib::Normal;
    if (strcmp(name, "Tangent") == 0)  return bgfx::Attrib::Tangent;
    if (strcmp(name, "Bitangent") == 0) return bgfx::Attrib::Bitangent;
    if (strcmp(name, "Color0") == 0)   return bgfx::Attrib::Color0;
    if (strcmp(name, "Color1") == 0)   return bgfx::Attrib::Color1;
    if (strcmp(name, "Color2") == 0)   return bgfx::Attrib::Color2;
    if (strcmp(name, "Color3") == 0)   return bgfx::Attrib::Color3;
    if (strcmp(name, "Indices") == 0)  return bgfx::Attrib::Indices;
    if (strcmp(name, "Weight") == 0)   return bgfx::Attrib::Weight;
    if (strcmp(name, "TexCoord0") == 0) return bgfx::Attrib::TexCoord0;
    if (strcmp(name, "TexCoord1") == 0) return bgfx::Attrib::TexCoord1;
    if (strcmp(name, "TexCoord2") == 0) return bgfx::Attrib::TexCoord2;
    if (strcmp(name, "TexCoord3") == 0) return bgfx::Attrib::TexCoord3;
    if (strcmp(name, "TexCoord4") == 0) return bgfx::Attrib::TexCoord4;
    if (strcmp(name, "TexCoord5") == 0) return bgfx::Attrib::TexCoord5;
    if (strcmp(name, "TexCoord6") == 0) return bgfx::Attrib::TexCoord6;
    if (strcmp(name, "TexCoord7") == 0) return bgfx::Attrib::TexCoord7;
    return bgfx::Attrib::Count;
}

static bgfx::AttribType::Enum parse_attrib_type(const char* type) {
    if (!type) return bgfx::AttribType::Count;
    if (strcmp(type, "Uint8") == 0)  return bgfx::AttribType::Uint8;
    if (strcmp(type, "Int16") == 0)  return bgfx::AttribType::Int16;
    if (strcmp(type, "Half") == 0)   return bgfx::AttribType::Half;
    if (strcmp(type, "Float") == 0)  return bgfx::AttribType::Float;
    if (strcmp(type, "Uint10") == 0) return bgfx::AttribType::Uint10;
    return bgfx::AttribType::Count;
}

static bool parse_vertex_layout(const char* json, uint32_t json_len,
                                 bgfx::VertexLayout& layout) {
    (void)json_len;
    if (!json || !*json) return false;

#ifdef COEX_UI_HAS_CJSON
    cJSON* root = cJSON_Parse(json);
    if (!root) return false;

    cJSON* attribs = cJSON_GetObjectItem(root, "attribs");
    if (!attribs || !cJSON_IsArray(attribs)) {
        cJSON_Delete(root);
        return false;
    }

    layout.begin();

    cJSON* attrib;
    cJSON_ArrayForEach(attrib, attribs) {
        cJSON* name_item = cJSON_GetObjectItem(attrib, "name");
        cJSON* type_item = cJSON_GetObjectItem(attrib, "type");
        cJSON* num_item = cJSON_GetObjectItem(attrib, "num");
        cJSON* norm_item = cJSON_GetObjectItem(attrib, "normalized");
        cJSON* as_int_item = cJSON_GetObjectItem(attrib, "as_int");

        if (!name_item || !type_item) continue;

        bgfx::Attrib::Enum attr = parse_attrib_name(cJSON_GetStringValue(name_item));
        bgfx::AttribType::Enum type = parse_attrib_type(cJSON_GetStringValue(type_item));
        uint8_t num = num_item ? (uint8_t)cJSON_GetNumberValue(num_item) : 1;
        bool normalized = norm_item && cJSON_IsTrue(norm_item);
        bool as_int = as_int_item && cJSON_IsTrue(as_int_item);

        if (attr != bgfx::Attrib::Count && type != bgfx::AttribType::Count) {
            layout.add(attr, num, type, normalized, as_int);
        }
    }

    layout.end();
    cJSON_Delete(root);
    return true;
#else
    return false;
#endif
}

/* ============================================================================
 * Lifecycle
 * ============================================================================ */

extern "C" int bgfx_bridge_init(void* native_window, void* native_display,
                                  int width, int height) {
    /* Signal single-threaded rendering mode BEFORE init.
     * Without this, bgfx creates a render thread that deadlocks
     * with macOS Cocoa main thread (Metal needs the main thread). */
    bgfx::renderFrame();

    /* Set platform data before init */
    bgfx::PlatformData pd;
    memset(&pd, 0, sizeof(pd));
    pd.nwh = native_window;
    pd.ndt = native_display;
    bgfx::setPlatformData(pd);

    bgfx::Init init;
    init.type = bgfx::RendererType::Count;  /* Auto-detect best renderer */
    init.resolution.width = (uint32_t)width;
    init.resolution.height = (uint32_t)height;
    init.resolution.reset = BGFX_RESET_VSYNC;
    init.platformData = pd;

    if (!bgfx::init(init)) {
        fprintf(stderr, "bgfx_bridge_init: bgfx::init() failed\n");
        return 0;
    }

    return 1;
}

extern "C" void bgfx_bridge_shutdown(void) {
    bgfx::shutdown();
}

extern "C" void bgfx_bridge_reset(int width, int height, uint32_t flags) {
    bgfx::reset((uint32_t)width, (uint32_t)height, flags);
}

extern "C" int bgfx_bridge_frame(void) {
    s_tvb_valid = 0;
    s_tib_valid = 0;
    /* In single-threaded mode (signaled by renderFrame() before init),
     * bgfx::frame() internally handles renderFrame(). Do NOT call
     * renderFrame() again — that causes double-rendering and crashes. */
    return (int)bgfx::frame();
}

/* ============================================================================
 * Views
 * ============================================================================ */

extern "C" void bgfx_bridge_set_view_rect(uint16_t view_id, uint16_t x,
                                            uint16_t y, uint16_t w, uint16_t h) {
    bgfx::setViewRect(view_id, x, y, w, h);
}

extern "C" void bgfx_bridge_set_view_clear(uint16_t view_id, uint16_t flags,
                                             uint32_t rgba, float depth,
                                             uint8_t stencil) {
    bgfx::setViewClear(view_id, flags, rgba, depth, stencil);
}

extern "C" void bgfx_bridge_set_view_transform(uint16_t view_id,
                                                 const float* view_mtx,
                                                 const float* proj_mtx) {
    bgfx::setViewTransform(view_id, view_mtx, proj_mtx);
}

extern "C" void bgfx_bridge_touch(uint16_t view_id) {
    bgfx::touch(view_id);
}

/* ============================================================================
 * Buffers
 * ============================================================================ */

extern "C" uint16_t bgfx_bridge_create_vertex_buffer(const void* data,
                                                       uint32_t size,
                                                       const void* layout_data,
                                                       uint32_t layout_size) {
    bgfx::VertexLayout layout;
    if (!parse_vertex_layout((const char*)layout_data, layout_size, layout)) {
        fprintf(stderr, "bgfx_bridge_create_vertex_buffer: invalid layout\n");
        return UINT16_MAX;
    }

    const bgfx::Memory* mem = bgfx::copy(data, size);
    bgfx::VertexBufferHandle h = bgfx::createVertexBuffer(mem, layout);
    return bgfx::isValid(h) ? h.idx : UINT16_MAX;
}

extern "C" uint16_t bgfx_bridge_create_index_buffer(const void* data,
                                                      uint32_t size,
                                                      int is_32bit) {
    const bgfx::Memory* mem = bgfx::copy(data, size);
    uint16_t flags = is_32bit ? BGFX_BUFFER_INDEX32 : 0;
    bgfx::IndexBufferHandle h = bgfx::createIndexBuffer(mem, flags);
    return bgfx::isValid(h) ? h.idx : UINT16_MAX;
}

extern "C" void bgfx_bridge_destroy_vertex_buffer(uint16_t handle) {
    bgfx::VertexBufferHandle h = {handle};
    if (bgfx::isValid(h)) bgfx::destroy(h);
}

extern "C" void bgfx_bridge_destroy_index_buffer(uint16_t handle) {
    bgfx::IndexBufferHandle h = {handle};
    if (bgfx::isValid(h)) bgfx::destroy(h);
}

/* ============================================================================
 * Transient Buffers
 * ============================================================================ */

extern "C" int bgfx_bridge_alloc_transient_vb(void** out_data, uint32_t num,
                                                const void* layout_data,
                                                uint32_t layout_size) {
    bgfx::VertexLayout layout;
    if (!parse_vertex_layout((const char*)layout_data, layout_size, layout)) {
        return 0;
    }
    if (bgfx::getAvailTransientVertexBuffer(num, layout) < num) {
        return 0;
    }
    bgfx::allocTransientVertexBuffer(&s_tvb, num, layout);
    s_tvb_valid = 1;
    if (out_data) *out_data = s_tvb.data;
    return 1;
}

extern "C" int bgfx_bridge_alloc_transient_ib(void** out_data, uint32_t num,
                                                int is_32bit) {
    if (is_32bit) {
        if (bgfx::getAvailTransientIndexBuffer(num, true) < num) return 0;
        bgfx::allocTransientIndexBuffer(&s_tib, num, true);
    } else {
        if (bgfx::getAvailTransientIndexBuffer(num, false) < num) return 0;
        bgfx::allocTransientIndexBuffer(&s_tib, num, false);
    }
    s_tib_valid = 1;
    if (out_data) *out_data = s_tib.data;
    return 1;
}

extern "C" void bgfx_bridge_set_transient_vertex_buffer(uint8_t stream,
                                                          uint32_t start,
                                                          uint32_t num) {
    if (s_tvb_valid) {
        bgfx::setVertexBuffer(stream, &s_tvb, start, num);
    }
}

extern "C" void bgfx_bridge_set_transient_index_buffer(uint32_t first,
                                                         uint32_t num) {
    if (s_tib_valid) {
        bgfx::setIndexBuffer(&s_tib, first, num);
    }
}

/* ============================================================================
 * Shaders & Programs
 * ============================================================================ */

extern "C" uint16_t bgfx_bridge_load_shader(const char* path) {
    FILE* f = fopen(path, "rb");
    if (!f) {
        fprintf(stderr, "bgfx_bridge_load_shader: cannot open '%s'\n", path);
        return UINT16_MAX;
    }

    fseek(f, 0, SEEK_END);
    long size = ftell(f);
    fseek(f, 0, SEEK_SET);

    if (size <= 0) {
        fclose(f);
        return UINT16_MAX;
    }

    const bgfx::Memory* mem = bgfx::alloc((uint32_t)size + 1);
    fread(mem->data, 1, (size_t)size, f);
    mem->data[size] = '\0';
    fclose(f);

    bgfx::ShaderHandle h = bgfx::createShader(mem);
    return bgfx::isValid(h) ? h.idx : UINT16_MAX;
}

extern "C" uint16_t bgfx_bridge_create_program(uint16_t vs, uint16_t fs) {
    bgfx::ShaderHandle vsh = {vs};
    bgfx::ShaderHandle fsh = {fs};
    bgfx::ProgramHandle h = bgfx::createProgram(vsh, fsh, true);
    return bgfx::isValid(h) ? h.idx : UINT16_MAX;
}

extern "C" uint16_t bgfx_bridge_create_compute_program(uint16_t cs) {
    bgfx::ShaderHandle csh = {cs};
    bgfx::ProgramHandle h = bgfx::createProgram(csh, true);
    return bgfx::isValid(h) ? h.idx : UINT16_MAX;
}

extern "C" void bgfx_bridge_destroy_program(uint16_t handle) {
    bgfx::ProgramHandle h = {handle};
    if (bgfx::isValid(h)) bgfx::destroy(h);
}

/* ============================================================================
 * Textures
 * ============================================================================ */

extern "C" uint16_t bgfx_bridge_create_texture_2d(uint16_t w, uint16_t h,
                                                    int has_mips, int format,
                                                    uint64_t flags,
                                                    const void* data,
                                                    uint32_t data_size) {
    const bgfx::Memory* mem = NULL;
    if (data && data_size > 0) {
        mem = bgfx::copy(data, data_size);
    }

    bgfx::TextureHandle th = bgfx::createTexture2D(
        w, h, has_mips != 0, 1,
        (bgfx::TextureFormat::Enum)format, flags, mem);
    return bgfx::isValid(th) ? th.idx : UINT16_MAX;
}

extern "C" void bgfx_bridge_update_texture_2d(uint16_t handle, uint16_t layer,
                                                uint8_t mip, uint16_t x,
                                                uint16_t y, uint16_t w,
                                                uint16_t h, const void* data,
                                                uint32_t data_size) {
    bgfx::TextureHandle th = {handle};
    if (!bgfx::isValid(th) || !data || data_size == 0) return;

    const bgfx::Memory* mem = bgfx::copy(data, data_size);
    bgfx::updateTexture2D(th, layer, mip, x, y, w, h, mem);
}

extern "C" void bgfx_bridge_destroy_texture(uint16_t handle) {
    bgfx::TextureHandle th = {handle};
    if (bgfx::isValid(th)) bgfx::destroy(th);
}

/* ============================================================================
 * Uniforms
 * ============================================================================ */

extern "C" uint16_t bgfx_bridge_create_uniform(const char* name, int type,
                                                 uint16_t num) {
    bgfx::UniformHandle h = bgfx::createUniform(
        name, (bgfx::UniformType::Enum)type, num);
    return bgfx::isValid(h) ? h.idx : UINT16_MAX;
}

extern "C" void bgfx_bridge_set_uniform(uint16_t handle, const void* value,
                                          uint16_t num) {
    bgfx::UniformHandle h = {handle};
    if (bgfx::isValid(h)) {
        bgfx::setUniform(h, value, num);
    }
}

extern "C" void bgfx_bridge_destroy_uniform(uint16_t handle) {
    bgfx::UniformHandle h = {handle};
    if (bgfx::isValid(h)) bgfx::destroy(h);
}

/* ============================================================================
 * Drawing
 * ============================================================================ */

extern "C" void bgfx_bridge_set_state(uint64_t state, uint32_t rgba) {
    bgfx::setState(state, rgba);
}

extern "C" uint32_t bgfx_bridge_set_transform(const float* mtx) {
    return bgfx::setTransform(mtx);
}

extern "C" void bgfx_bridge_set_vertex_buffer(uint8_t stream, uint16_t handle,
                                                uint32_t start, uint32_t num) {
    bgfx::VertexBufferHandle h = {handle};
    bgfx::setVertexBuffer(stream, h, start, num);
}

extern "C" void bgfx_bridge_set_index_buffer(uint16_t handle, uint32_t first,
                                               uint32_t num) {
    bgfx::IndexBufferHandle h = {handle};
    bgfx::setIndexBuffer(h, first, num);
}

extern "C" void bgfx_bridge_set_texture(uint8_t stage, uint16_t uniform,
                                          uint16_t texture, uint32_t flags) {
    bgfx::UniformHandle uh = {uniform};
    bgfx::TextureHandle th = {texture};
    bgfx::setTexture(stage, uh, th, flags);
}

extern "C" void bgfx_bridge_submit(uint16_t view_id, uint16_t program,
                                     uint32_t depth, uint8_t flags) {
    bgfx::ProgramHandle h = {program};
    bgfx::submit(view_id, h, depth, flags);
}

/* ============================================================================
 * Compute
 * ============================================================================ */

extern "C" void bgfx_bridge_set_compute_buffer(uint8_t stage, uint16_t handle,
                                                 int access) {
    bgfx::VertexBufferHandle h = {handle};
    bgfx::setBuffer(stage, h, (bgfx::Access::Enum)access);
}

extern "C" void bgfx_bridge_dispatch(uint16_t view_id, uint16_t program,
                                       uint32_t num_x, uint32_t num_y,
                                       uint32_t num_z, uint8_t flags) {
    bgfx::ProgramHandle h = {program};
    bgfx::dispatch(view_id, h, num_x, num_y, num_z, flags);
}

/* ============================================================================
 * Debug
 * ============================================================================ */

extern "C" void bgfx_bridge_set_debug(uint32_t flags) {
    bgfx::setDebug(flags);
}

extern "C" void bgfx_bridge_dbg_text_printf(uint16_t x, uint16_t y,
                                              uint8_t attr, const char* text) {
    bgfx::dbgTextPrintf(x, y, attr, "%s", text);
}

extern "C" void bgfx_bridge_dbg_text_clear(void) {
    bgfx::dbgTextClear();
}

extern "C" const char* bgfx_bridge_get_renderer_name(void) {
    return bgfx::getRendererName(bgfx::getRendererType());
}

extern "C" const char* bgfx_bridge_get_caps_json(void) {
#ifdef COEX_UI_HAS_CJSON
    const bgfx::Caps* caps = bgfx::getCaps();
    if (!caps) return strdup("{}");

    cJSON* obj = cJSON_CreateObject();
    cJSON_AddStringToObject(obj, "renderer",
                             bgfx::getRendererName(caps->rendererType));
    cJSON_AddNumberToObject(obj, "vendorId", caps->vendorId);
    cJSON_AddNumberToObject(obj, "deviceId", caps->deviceId);
    cJSON_AddNumberToObject(obj, "maxTextureSize",
                             caps->limits.maxTextureSize);
    cJSON_AddNumberToObject(obj, "maxViews", caps->limits.maxViews);
    cJSON_AddNumberToObject(obj, "maxFBAttachments",
                             caps->limits.maxFBAttachments);
    cJSON_AddNumberToObject(obj, "maxComputeBindings",
                             caps->limits.maxComputeBindings);
    cJSON_AddBoolToObject(obj, "homogeneousDepth", caps->homogeneousDepth);
    cJSON_AddBoolToObject(obj, "originBottomLeft", caps->originBottomLeft);

    char* result = cJSON_PrintUnformatted(obj);
    cJSON_Delete(obj);
    return result;
#else
    return strdup("{}");
#endif
}

/* ============================================================================
 * Math Helpers (using bx::math)
 * ============================================================================ */

extern "C" void bgfx_bridge_mtx_look_at(float* result, const float* eye,
                                           const float* at, const float* up) {
    bx::Vec3 eye_v = {eye[0], eye[1], eye[2]};
    bx::Vec3 at_v = {at[0], at[1], at[2]};
    bx::Vec3 up_v = up ? bx::Vec3{up[0], up[1], up[2]}
                        : bx::Vec3{0.0f, 1.0f, 0.0f};
    bx::mtxLookAt(result, eye_v, at_v, up_v);
}

extern "C" void bgfx_bridge_mtx_proj(float* result, float fovy, float aspect,
                                       float near_, float far_,
                                       int homogeneous_ndc) {
    bx::mtxProj(result, fovy, aspect, near_, far_,
                 homogeneous_ndc != 0,
                 bx::Handedness::Left);
}

extern "C" void bgfx_bridge_mtx_ortho(float* result, float left, float right,
                                        float bottom, float top, float near_,
                                        float far_, float offset,
                                        int homogeneous_ndc) {
    bx::mtxOrtho(result, left, right, bottom, top, near_, far_, offset,
                  homogeneous_ndc != 0,
                  bx::Handedness::Left);
}

extern "C" void bgfx_bridge_mtx_rotate_xyz(float* result, float ax, float ay,
                                              float az) {
    bx::mtxRotateXYZ(result, ax, ay, az);
}
