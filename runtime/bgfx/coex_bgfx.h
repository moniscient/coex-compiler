/**
 * Coex bgfx Integration - C API Header
 *
 * Cross-platform 3D rendering via bgfx (Metal/Vulkan/OpenGL/D3D).
 * All functions use int64_t/double/const char* at the FFI boundary (INV-3).
 * Handles are i64 indices into an internal handle table.
 * JSON strings returned by this API must be freed with coex_bgfx_free_json().
 */

#ifndef COEX_BGFX_H
#define COEX_BGFX_H

#include <stdint.h>

#ifdef __cplusplus
extern "C" {
#endif

/* ============================================================================
 * Lifecycle
 * ============================================================================ */

/**
 * Initialize bgfx with the given window dimensions.
 * Must be called after coex_ui_shell_init() since it uses the shell's window.
 *
 * @param width   Window width in pixels
 * @param height  Window height in pixels
 * @return 1 on success, 0 on failure
 */
int64_t coex_bgfx_init(int64_t width, int64_t height);

/**
 * Shut down bgfx and release all resources.
 */
void coex_bgfx_shutdown(void);

/**
 * Reset the backbuffer (e.g., after window resize).
 *
 * @param width   New width
 * @param height  New height
 * @param flags   Reset flags (0 for defaults, 0x80 for vsync)
 */
void coex_bgfx_reset(int64_t width, int64_t height, int64_t flags);

/**
 * Advance to the next frame. Must be called once per frame.
 *
 * @return Current frame number
 */
int64_t coex_bgfx_frame(void);

/* ============================================================================
 * Views
 * ============================================================================ */

/**
 * Set view rectangle (viewport).
 *
 * @param view_id  View ID (0-255)
 * @param x        Left position
 * @param y        Top position
 * @param width    Width
 * @param height   Height
 */
void coex_bgfx_set_view_rect(int64_t view_id, int64_t x, int64_t y,
                              int64_t width, int64_t height);

/**
 * Set view clear flags, color, depth, and stencil.
 *
 * @param view_id  View ID
 * @param flags    Clear flags (1=color, 2=depth, 4=stencil)
 * @param rgba     Clear color as 0xRRGGBBAA
 * @param depth    Clear depth (0.0-1.0)
 * @param stencil  Clear stencil value (0-255)
 */
void coex_bgfx_set_view_clear(int64_t view_id, int64_t flags,
                               int64_t rgba, double depth, int64_t stencil);

/**
 * Set view transform (view and projection matrices as JSON float[16] arrays).
 *
 * @param view_id      View ID
 * @param view_json    JSON array of 16 floats (view matrix), or "" for identity
 * @param proj_json    JSON array of 16 floats (projection matrix), or "" for identity
 */
void coex_bgfx_set_view_transform(int64_t view_id, const char* view_json,
                                   const char* proj_json);

/**
 * Submit an empty primitive for a view (ensures view is processed).
 *
 * @param view_id  View ID
 */
void coex_bgfx_touch(int64_t view_id);

/* ============================================================================
 * Buffers
 * ============================================================================ */

/**
 * Create a vertex buffer from JSON data.
 *
 * @param vertices_json  JSON object: { "layout": {...}, "data": [...] }
 *   layout: { "attribs": [{"name":"Position","type":"Float","num":3}, ...] }
 *   data: flat array of vertex data as floats
 * @return Handle (i64) or 0 on failure
 */
int64_t coex_bgfx_create_vertex_buffer(const char* vertices_json);

/**
 * Create an index buffer from JSON data.
 *
 * @param indices_json  JSON object: { "data": [...], "is_32bit": false }
 *   data: array of index values
 *   is_32bit: true for 32-bit indices (default: 16-bit)
 * @return Handle (i64) or 0 on failure
 */
int64_t coex_bgfx_create_index_buffer(const char* indices_json);

/**
 * Allocate a transient vertex buffer (valid for one frame only).
 *
 * @param num_vertices   Number of vertices
 * @param layout_json    JSON layout specification
 * @return Handle (i64) or 0 on failure
 */
int64_t coex_bgfx_alloc_transient_vertex_buffer(int64_t num_vertices,
                                                  const char* layout_json);

/**
 * Allocate a transient index buffer (valid for one frame only).
 *
 * @param num_indices  Number of indices
 * @param is_32bit     1 for 32-bit indices, 0 for 16-bit
 * @return Handle (i64) or 0 on failure
 */
int64_t coex_bgfx_alloc_transient_index_buffer(int64_t num_indices,
                                                 int64_t is_32bit);

/**
 * Destroy a vertex buffer.
 *
 * @param handle  Vertex buffer handle
 */
void coex_bgfx_destroy_vertex_buffer(int64_t handle);

/**
 * Destroy an index buffer.
 *
 * @param handle  Index buffer handle
 */
void coex_bgfx_destroy_index_buffer(int64_t handle);

/* ============================================================================
 * Shaders & Programs
 * ============================================================================ */

/**
 * Load a shader from a file path.
 *
 * @param path  Path to compiled shader binary (.bin)
 * @return Handle (i64) or 0 on failure
 */
int64_t coex_bgfx_load_shader(const char* path);

/**
 * Create a rendering program from vertex and fragment shaders.
 *
 * @param vertex_handle    Vertex shader handle
 * @param fragment_handle  Fragment shader handle
 * @return Program handle (i64) or 0 on failure
 */
int64_t coex_bgfx_create_program(int64_t vertex_handle, int64_t fragment_handle);

/**
 * Create a compute program.
 *
 * @param compute_handle  Compute shader handle
 * @return Program handle (i64) or 0 on failure
 */
int64_t coex_bgfx_create_compute_program(int64_t compute_handle);

/**
 * Destroy a program.
 *
 * @param handle  Program handle
 */
void coex_bgfx_destroy_program(int64_t handle);

/* ============================================================================
 * Textures
 * ============================================================================ */

/**
 * Create a 2D texture.
 *
 * @param width    Texture width
 * @param height   Texture height
 * @param has_mips 1 if texture has mipmaps
 * @param format   Texture format (bgfx format enum value)
 * @param flags    Texture flags
 * @param data_json JSON array of pixel data bytes, or "" for empty texture
 * @return Handle (i64) or 0 on failure
 */
int64_t coex_bgfx_create_texture_2d(int64_t width, int64_t height,
                                     int64_t has_mips, int64_t format,
                                     int64_t flags, const char* data_json);

/**
 * Update a region of a 2D texture.
 *
 * @param handle     Texture handle
 * @param layer      Layer (0 for 2D textures)
 * @param mip        Mip level
 * @param x          X offset
 * @param y          Y offset
 * @param width      Update width
 * @param height     Update height
 * @param data_json  JSON array of pixel data bytes
 */
void coex_bgfx_update_texture_2d(int64_t handle, int64_t layer, int64_t mip,
                                  int64_t x, int64_t y, int64_t width,
                                  int64_t height, const char* data_json);

/**
 * Destroy a texture.
 *
 * @param handle  Texture handle
 */
void coex_bgfx_destroy_texture(int64_t handle);

/* ============================================================================
 * Uniforms
 * ============================================================================ */

/**
 * Create a uniform.
 *
 * @param name  Uniform name
 * @param type  Uniform type (0=sampler, 1=vec4, 2=mat3, 3=mat4)
 * @param num   Number of elements (1 for non-array)
 * @return Handle (i64) or 0 on failure
 */
int64_t coex_bgfx_create_uniform(const char* name, int64_t type, int64_t num);

/**
 * Set a uniform value.
 *
 * @param handle      Uniform handle
 * @param value_json  JSON array of float values
 * @param num         Number of elements
 */
void coex_bgfx_set_uniform(int64_t handle, const char* value_json, int64_t num);

/**
 * Destroy a uniform.
 *
 * @param handle  Uniform handle
 */
void coex_bgfx_destroy_uniform(int64_t handle);

/* ============================================================================
 * Drawing
 * ============================================================================ */

/**
 * Set render state.
 *
 * @param state  State flags (bitfield)
 * @param rgba   Blend factor (0 for default)
 */
void coex_bgfx_set_state(int64_t state, int64_t rgba);

/**
 * Set model transform matrix.
 *
 * @param mtx_json  JSON array of 16 floats (4x4 matrix)
 * @return Index into transform cache
 */
int64_t coex_bgfx_set_transform(const char* mtx_json);

/**
 * Set vertex buffer for rendering.
 *
 * @param stream          Stream index (0-3)
 * @param handle          Vertex buffer handle
 * @param start_vertex    First vertex
 * @param num_vertices    Number of vertices (0 = all)
 */
void coex_bgfx_set_vertex_buffer(int64_t stream, int64_t handle,
                                  int64_t start_vertex, int64_t num_vertices);

/**
 * Set transient vertex buffer for rendering.
 *
 * @param stream        Stream index (0-3)
 * @param handle        Transient vertex buffer handle
 * @param start_vertex  First vertex
 * @param num_vertices  Number of vertices
 */
void coex_bgfx_set_transient_vertex_buffer(int64_t stream, int64_t handle,
                                            int64_t start_vertex,
                                            int64_t num_vertices);

/**
 * Set index buffer for rendering.
 *
 * @param handle       Index buffer handle
 * @param first_index  First index
 * @param num_indices  Number of indices (0 = all)
 */
void coex_bgfx_set_index_buffer(int64_t handle, int64_t first_index,
                                 int64_t num_indices);

/**
 * Set transient index buffer for rendering.
 *
 * @param handle       Transient index buffer handle
 * @param first_index  First index
 * @param num_indices  Number of indices
 */
void coex_bgfx_set_transient_index_buffer(int64_t handle, int64_t first_index,
                                           int64_t num_indices);

/**
 * Set texture for rendering.
 *
 * @param stage           Texture stage (0-15)
 * @param uniform_handle  Sampler uniform handle
 * @param texture_handle  Texture handle
 * @param flags           Texture sampling flags (0 for default)
 */
void coex_bgfx_set_texture(int64_t stage, int64_t uniform_handle,
                            int64_t texture_handle, int64_t flags);

/**
 * Submit draw call.
 *
 * @param view_id         View ID
 * @param program_handle  Program handle
 * @param depth           Depth for sorting (0 = default)
 * @param flags           Discard flags (0xFF = discard all state)
 */
void coex_bgfx_submit(int64_t view_id, int64_t program_handle,
                       int64_t depth, int64_t flags);

/* ============================================================================
 * Compute
 * ============================================================================ */

/**
 * Set compute buffer binding.
 *
 * @param stage   Compute stage (0-15)
 * @param handle  Buffer handle
 * @param access  Access mode (0=read, 1=write, 2=readwrite)
 */
void coex_bgfx_set_compute_buffer(int64_t stage, int64_t handle, int64_t access);

/**
 * Dispatch a compute job.
 *
 * @param view_id         View ID
 * @param program_handle  Compute program handle
 * @param num_x           Number of groups in X
 * @param num_y           Number of groups in Y
 * @param num_z           Number of groups in Z
 * @param flags           Discard flags
 */
void coex_bgfx_dispatch(int64_t view_id, int64_t program_handle,
                         int64_t num_x, int64_t num_y, int64_t num_z,
                         int64_t flags);

/* ============================================================================
 * Debug
 * ============================================================================ */

/**
 * Set debug flags.
 *
 * @param flags  Debug flags (1=wireframe, 2=IFH, 4=stats, 8=text)
 */
void coex_bgfx_set_debug(int64_t flags);

/**
 * Print debug text at grid position.
 *
 * @param x     Column
 * @param y     Row
 * @param attr  Color attribute (0x0f = white on black)
 * @param text  Text to print
 */
void coex_bgfx_dbg_text(int64_t x, int64_t y, int64_t attr, const char* text);

/**
 * Clear the debug text buffer.
 */
void coex_bgfx_dbg_text_clear(void);

/**
 * Get the name of the active renderer.
 *
 * @return Renderer name string (caller must free with coex_bgfx_free_json)
 */
const char* coex_bgfx_get_renderer_name(void);

/**
 * Get renderer capabilities as JSON.
 *
 * @return JSON string with caps info (caller must free with coex_bgfx_free_json)
 */
const char* coex_bgfx_get_caps_json(void);

/* ============================================================================
 * Math Helpers
 * ============================================================================ */

/**
 * Create a look-at view matrix.
 *
 * @param eye_json     JSON array [x,y,z] - camera position
 * @param at_json      JSON array [x,y,z] - look-at target
 * @param up_json      JSON array [x,y,z] - up vector (default [0,1,0])
 * @return JSON array of 16 floats (caller must free with coex_bgfx_free_json)
 */
const char* coex_bgfx_mtx_look_at(const char* eye_json, const char* at_json,
                                    const char* up_json);

/**
 * Create a perspective projection matrix.
 *
 * @param fovy    Field of view in degrees (vertical)
 * @param aspect  Aspect ratio (width/height)
 * @param near_   Near clipping plane
 * @param far_    Far clipping plane
 * @return JSON array of 16 floats (caller must free with coex_bgfx_free_json)
 */
const char* coex_bgfx_mtx_proj(double fovy, double aspect, double near_,
                                double far_);

/**
 * Create an orthographic projection matrix.
 *
 * @param left    Left edge
 * @param right   Right edge
 * @param bottom  Bottom edge
 * @param top     Top edge
 * @param near_   Near clipping plane
 * @param far_    Far clipping plane
 * @return JSON array of 16 floats (caller must free with coex_bgfx_free_json)
 */
const char* coex_bgfx_mtx_ortho(double left, double right, double bottom,
                                  double top, double near_, double far_);

/**
 * Create a rotation matrix from euler angles.
 *
 * @param ax  Rotation around X in radians
 * @param ay  Rotation around Y in radians
 * @param az  Rotation around Z in radians
 * @return JSON array of 16 floats (caller must free with coex_bgfx_free_json)
 */
const char* coex_bgfx_mtx_rotate_xyz(double ax, double ay, double az);

/* ============================================================================
 * Scene Observer API
 *
 * Declarative scene description: Coex code builds a scene as JSON, publishes
 * it via set_scene(), and the main thread renders it each frame. Enables safe
 * concurrent scene construction from Coex tasks.
 *
 * Thread safety: set_scene() is thread-safe (uses atomic exchange).
 * All other observer functions must be called on the main thread.
 * ============================================================================ */

/**
 * Publish a scene description for the observer to render.
 * Thread-safe: can be called from any thread (worker tasks).
 * The JSON is copied internally; caller retains ownership.
 *
 * @param scene_json  JSON string describing the scene (views, objects, debug)
 */
void coex_bgfx_set_scene(const char* scene_json);

/**
 * Enter observer mode. Call on main thread before the render loop.
 *
 * @return 1 on success, 0 on failure
 */
int64_t coex_bgfx_begin_observer(void);

/**
 * Exit observer mode. Call on main thread after the render loop.
 * Frees pending and current scene data.
 */
void coex_bgfx_end_observer(void);

/**
 * Render one frame in observer mode. Call on main thread each frame.
 * Consumes the latest pending scene (if any), translates JSON to bgfx
 * draw calls, and calls bgfx::frame().
 *
 * @return Current frame number
 */
int64_t coex_bgfx_observer_frame(void);

/* ============================================================================
 * Memory Management
 * ============================================================================ */

/**
 * Free a JSON string returned by bgfx API functions.
 * Must be called for every string returned by get_caps_json, mtx_*, etc.
 *
 * @param json_str  String to free (safe to pass NULL)
 */
void coex_bgfx_free_json(const char* json_str);

/* ============================================================================
 * State Constants (for coex_bgfx_set_state)
 * ============================================================================ */

#define COEX_BGFX_STATE_WRITE_R          (0x0000000000000001ULL)
#define COEX_BGFX_STATE_WRITE_G          (0x0000000000000002ULL)
#define COEX_BGFX_STATE_WRITE_B          (0x0000000000000004ULL)
#define COEX_BGFX_STATE_WRITE_A          (0x0000000000000008ULL)
#define COEX_BGFX_STATE_WRITE_Z          (0x0000004000000000ULL)
#define COEX_BGFX_STATE_WRITE_RGB        (COEX_BGFX_STATE_WRITE_R | COEX_BGFX_STATE_WRITE_G | COEX_BGFX_STATE_WRITE_B)
#define COEX_BGFX_STATE_WRITE_MASK       (COEX_BGFX_STATE_WRITE_RGB | COEX_BGFX_STATE_WRITE_A | COEX_BGFX_STATE_WRITE_Z)
#define COEX_BGFX_STATE_DEPTH_TEST_LESS  (0x0000000000000010ULL)
#define COEX_BGFX_STATE_CULL_CW         (0x0000001000000000ULL)
#define COEX_BGFX_STATE_CULL_CCW        (0x0000002000000000ULL)
#define COEX_BGFX_STATE_MSAA            (0x0100000000000000ULL)
#define COEX_BGFX_STATE_DEFAULT         (COEX_BGFX_STATE_WRITE_MASK | COEX_BGFX_STATE_DEPTH_TEST_LESS | COEX_BGFX_STATE_CULL_CW | COEX_BGFX_STATE_MSAA)

/* ============================================================================
 * Internal Bridge Functions (called by coex_bgfx.c, implemented in bgfx_c_bridge.cpp)
 * ============================================================================ */

int  bgfx_bridge_init(void* native_window, void* native_display,
                       int width, int height);
void bgfx_bridge_shutdown(void);
void bgfx_bridge_reset(int width, int height, uint32_t flags);
int  bgfx_bridge_frame(void);

void bgfx_bridge_set_view_rect(uint16_t view_id, uint16_t x, uint16_t y,
                                uint16_t w, uint16_t h);
void bgfx_bridge_set_view_clear(uint16_t view_id, uint16_t flags,
                                 uint32_t rgba, float depth, uint8_t stencil);
void bgfx_bridge_set_view_transform(uint16_t view_id, const float* view_mtx,
                                     const float* proj_mtx);
void bgfx_bridge_touch(uint16_t view_id);

uint16_t bgfx_bridge_create_vertex_buffer(const void* data, uint32_t size,
                                           const void* layout_data, uint32_t layout_size);
uint16_t bgfx_bridge_create_index_buffer(const void* data, uint32_t size,
                                          int is_32bit);
void bgfx_bridge_destroy_vertex_buffer(uint16_t handle);
void bgfx_bridge_destroy_index_buffer(uint16_t handle);

uint16_t bgfx_bridge_load_shader(const char* path);
uint16_t bgfx_bridge_create_program(uint16_t vs, uint16_t fs);
uint16_t bgfx_bridge_create_compute_program(uint16_t cs);
void bgfx_bridge_destroy_program(uint16_t handle);

uint16_t bgfx_bridge_create_texture_2d(uint16_t w, uint16_t h, int has_mips,
                                        int format, uint64_t flags,
                                        const void* data, uint32_t data_size);
void bgfx_bridge_update_texture_2d(uint16_t handle, uint16_t layer,
                                    uint8_t mip, uint16_t x, uint16_t y,
                                    uint16_t w, uint16_t h,
                                    const void* data, uint32_t data_size);
void bgfx_bridge_destroy_texture(uint16_t handle);

uint16_t bgfx_bridge_create_uniform(const char* name, int type, uint16_t num);
void bgfx_bridge_set_uniform(uint16_t handle, const void* value, uint16_t num);
void bgfx_bridge_destroy_uniform(uint16_t handle);

void bgfx_bridge_set_state(uint64_t state, uint32_t rgba);
uint32_t bgfx_bridge_set_transform(const float* mtx);
void bgfx_bridge_set_vertex_buffer(uint8_t stream, uint16_t handle,
                                    uint32_t start, uint32_t num);
void bgfx_bridge_set_index_buffer(uint16_t handle, uint32_t first, uint32_t num);
void bgfx_bridge_set_texture(uint8_t stage, uint16_t uniform, uint16_t texture,
                              uint32_t flags);
void bgfx_bridge_submit(uint16_t view_id, uint16_t program, uint32_t depth,
                         uint8_t flags);

void bgfx_bridge_set_compute_buffer(uint8_t stage, uint16_t handle, int access);
void bgfx_bridge_dispatch(uint16_t view_id, uint16_t program,
                           uint32_t num_x, uint32_t num_y, uint32_t num_z,
                           uint8_t flags);

void bgfx_bridge_set_debug(uint32_t flags);
void bgfx_bridge_dbg_text_printf(uint16_t x, uint16_t y, uint8_t attr,
                                  const char* text);
void bgfx_bridge_dbg_text_clear(void);
const char* bgfx_bridge_get_renderer_name(void);
const char* bgfx_bridge_get_caps_json(void);

void bgfx_bridge_mtx_look_at(float* result, const float* eye,
                               const float* at, const float* up);
void bgfx_bridge_mtx_proj(float* result, float fovy, float aspect,
                            float near_, float far_, int homogeneous_ndc);
void bgfx_bridge_mtx_ortho(float* result, float left, float right,
                             float bottom, float top, float near_, float far_,
                             float offset, int homogeneous_ndc);
void bgfx_bridge_mtx_rotate_xyz(float* result, float ax, float ay, float az);

/* Transient buffer bridge functions */
int  bgfx_bridge_alloc_transient_vb(void** out_data, uint32_t num,
                                      const void* layout_data, uint32_t layout_size);
int  bgfx_bridge_alloc_transient_ib(void** out_data, uint32_t num, int is_32bit);
void bgfx_bridge_set_transient_vertex_buffer(uint8_t stream, uint32_t start,
                                              uint32_t num);
void bgfx_bridge_set_transient_index_buffer(uint32_t first, uint32_t num);

#ifdef __cplusplus
}
#endif

#endif /* COEX_BGFX_H */
