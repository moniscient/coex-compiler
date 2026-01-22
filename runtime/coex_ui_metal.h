/**
 * Coex UI Metal Renderer
 *
 * Renders Dear ImGui draw data directly using Metal.
 * This bypasses Skia for a simpler, more direct rendering path.
 */

#ifndef COEX_UI_METAL_H
#define COEX_UI_METAL_H

#include <stdint.h>

#ifdef __cplusplus
extern "C" {
#endif

/**
 * Initialize the Metal renderer.
 * Must be called after the platform shell is initialized.
 *
 * @param metal_device  MTLDevice pointer from shell
 * @return 1 on success, 0 on failure
 */
int64_t coex_ui_metal_init(void* metal_device);

/**
 * Shutdown the Metal renderer and free resources.
 */
void coex_ui_metal_shutdown(void);

/**
 * Create font texture atlas from ImGui font data.
 * Must be called after ImGui context is created and fonts are loaded.
 *
 * @return 1 on success, 0 on failure
 */
int64_t coex_ui_metal_create_fonts_texture(void);

/**
 * Render ImGui draw data to a Metal drawable.
 *
 * @param command_buffer     MTLCommandBuffer to encode into
 * @param render_target      MTLTexture to render to (from drawable)
 * @param imgui_draw_data    ImDrawData pointer from igGetDrawData()
 * @param framebuffer_width  Framebuffer width in pixels
 * @param framebuffer_height Framebuffer height in pixels
 */
void coex_ui_metal_render(
    void* command_buffer,
    void* render_target,
    void* imgui_draw_data,
    int64_t framebuffer_width,
    int64_t framebuffer_height
);

/**
 * Invalidate font texture (call when fonts change).
 */
void coex_ui_metal_invalidate_fonts_texture(void);

#ifdef __cplusplus
}
#endif

#endif /* COEX_UI_METAL_H */
