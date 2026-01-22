/**
 * Coex UI Skia Rendering Backend Header
 *
 * C interface for Skia graphics operations.
 */

#ifndef COEX_UI_SKIA_H
#define COEX_UI_SKIA_H

#include <stdint.h>

#ifdef __cplusplus
extern "C" {
#endif

/**
 * Initialize Skia rendering.
 *
 * @return 1 on success, 0 on failure
 */
int64_t coex_ui_skia_init(void);

/**
 * Shutdown Skia and free resources.
 */
void coex_ui_skia_shutdown(void);

/* ============================================================================
 * Software Rendering
 * ============================================================================ */

/**
 * Create a software rendering surface.
 *
 * @param width   Surface width in pixels
 * @param height  Surface height in pixels
 * @return Opaque pointer to SkSurface, or NULL on failure
 */
void* coex_ui_skia_create_sw_surface(int64_t width, int64_t height);

/**
 * Destroy the software surface.
 */
void coex_ui_skia_destroy_sw_surface(void);

/**
 * Get the canvas for the software surface.
 *
 * @return Opaque pointer to SkCanvas
 */
void* coex_ui_skia_get_sw_canvas(void);

/**
 * Flush the software surface to a pixel buffer.
 *
 * @param pixels_out  Output buffer (BGRA8888 format, must be large enough)
 */
void coex_ui_skia_flush_sw_surface(void* pixels_out);

/* ============================================================================
 * GPU Rendering (Metal on macOS)
 * ============================================================================ */

#ifdef __APPLE__
/**
 * Create a GPU rendering context.
 *
 * @param metal_device  MTLDevice pointer
 * @param metal_queue   MTLCommandQueue pointer
 * @return Opaque pointer to GrDirectContext, or NULL on failure
 */
void* coex_ui_skia_create_gpu_context(void* metal_device, void* metal_queue);

/**
 * Destroy the GPU context.
 */
void coex_ui_skia_destroy_gpu_context(void);

/**
 * Create a GPU surface from a Metal texture.
 *
 * @param metal_texture  MTLTexture pointer (must be BGRA8 format)
 * @param width          Texture width
 * @param height         Texture height
 * @return Opaque pointer to SkSurface, or NULL on failure
 */
void* coex_ui_skia_create_gpu_surface(void* metal_texture, int64_t width, int64_t height);

/**
 * Flush GPU rendering and submit commands.
 */
void coex_ui_skia_flush_gpu(void);
#endif /* __APPLE__ */

/* ============================================================================
 * ImGui Rendering
 * ============================================================================ */

/**
 * Render ImGui draw data to a Skia canvas.
 *
 * @param skia_canvas     SkCanvas pointer
 * @param imgui_draw_data ImDrawData pointer from igGetDrawData()
 */
void coex_ui_skia_render_imgui(void* skia_canvas, void* imgui_draw_data);

/* ============================================================================
 * Basic Drawing Primitives
 * ============================================================================ */

/**
 * Clear the canvas with a solid color.
 */
void coex_ui_skia_clear(void* skia_canvas, float r, float g, float b, float a);

/**
 * Draw a filled rectangle.
 */
void coex_ui_skia_draw_rect(void* skia_canvas,
                             double x, double y, double w, double h,
                             float r, float g, float b, float a);

/**
 * Draw a filled rounded rectangle.
 */
void coex_ui_skia_draw_rounded_rect(void* skia_canvas,
                                     double x, double y, double w, double h,
                                     double radius,
                                     float r, float g, float b, float a);

/**
 * Draw a filled circle.
 */
void coex_ui_skia_draw_circle(void* skia_canvas,
                               double cx, double cy, double radius,
                               float r, float g, float b, float a);

/**
 * Draw a line.
 */
void coex_ui_skia_draw_line(void* skia_canvas,
                             double x1, double y1, double x2, double y2,
                             double stroke_width,
                             float r, float g, float b, float a);

/**
 * Draw text.
 */
void coex_ui_skia_draw_text(void* skia_canvas,
                             const char* text, double x, double y,
                             float r, float g, float b, float a);

#ifdef __cplusplus
}
#endif

#endif /* COEX_UI_SKIA_H */
