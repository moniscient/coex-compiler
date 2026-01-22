/**
 * Coex UI OpenGL Renderer
 *
 * Renders Dear ImGui draw data using OpenGL 3.3 Core Profile.
 * Linux equivalent of coex_ui_metal.m.
 */

#ifndef COEX_UI_OPENGL_H
#define COEX_UI_OPENGL_H

#include <stdint.h>

#ifdef __cplusplus
extern "C" {
#endif

/**
 * Initialize the OpenGL renderer.
 * Must be called after the platform shell is initialized.
 *
 * @return 1 on success, 0 on failure
 */
int64_t coex_ui_opengl_init(void);

/**
 * Shutdown the OpenGL renderer and free resources.
 */
void coex_ui_opengl_shutdown(void);

/**
 * Create font texture atlas from ImGui font data.
 * Must be called after ImGui context is created and fonts are loaded.
 *
 * @return 1 on success, 0 on failure
 */
int64_t coex_ui_opengl_create_fonts_texture(void);

/**
 * Render ImGui draw data using OpenGL.
 *
 * @param imgui_draw_data    ImDrawData pointer from igGetDrawData()
 * @param framebuffer_width  Framebuffer width in pixels
 * @param framebuffer_height Framebuffer height in pixels
 */
void coex_ui_opengl_render(
    void* imgui_draw_data,
    int64_t framebuffer_width,
    int64_t framebuffer_height
);

/**
 * Invalidate font texture (call when fonts change).
 */
void coex_ui_opengl_invalidate_fonts_texture(void);

#ifdef __cplusplus
}
#endif

#endif /* COEX_UI_OPENGL_H */
