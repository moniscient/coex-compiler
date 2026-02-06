/**
 * Coex SVG Texture Abstraction
 *
 * Platform-agnostic interface for creating and managing GPU textures
 * used by the SVG module to display rendered SVG content.
 *
 * Implementations:
 *   - coex_svg_texture_metal.m (macOS)
 *   - coex_svg_texture_opengl.c (Linux)
 */

#ifndef COEX_SVG_TEXTURE_H
#define COEX_SVG_TEXTURE_H

#include <stdint.h>

#ifdef __cplusplus
extern "C" {
#endif

/** Opaque handle to a platform texture */
typedef void* svg_texture_t;

/* ============================================================================
 * Texture Lifecycle
 * ============================================================================ */

/**
 * Create a new texture with the specified dimensions.
 * The texture is initially empty (undefined contents).
 *
 * @param width   Texture width in pixels
 * @param height  Texture height in pixels
 * @return Texture handle, or NULL on failure
 */
svg_texture_t svg_texture_create(int width, int height);

/**
 * Destroy a texture and free GPU resources.
 * Safe to call with NULL.
 *
 * @param tex  Texture handle
 */
void svg_texture_destroy(svg_texture_t tex);

/* ============================================================================
 * Texture Updates
 * ============================================================================ */

/**
 * Update texture contents from RGBA pixel data.
 * The pixel data must be at least (height * stride) bytes.
 *
 * @param tex     Texture handle
 * @param rgba    RGBA pixel data (4 bytes per pixel)
 * @param width   Image width (must match texture width)
 * @param height  Image height (must match texture height)
 * @param stride  Bytes per row (typically width * 4)
 * @return 1 on success, 0 on failure
 */
int svg_texture_update(svg_texture_t tex, const uint8_t* rgba,
                       int width, int height, int stride);

/**
 * Update a sub-region of the texture.
 * Useful for partial updates when only part of the SVG changed.
 *
 * @param tex     Texture handle
 * @param rgba    RGBA pixel data for the region
 * @param x       Region X offset
 * @param y       Region Y offset
 * @param width   Region width
 * @param height  Region height
 * @param stride  Bytes per row of source data
 * @return 1 on success, 0 on failure
 */
int svg_texture_update_region(svg_texture_t tex, const uint8_t* rgba,
                              int x, int y, int width, int height, int stride);

/* ============================================================================
 * Texture Properties
 * ============================================================================ */

/**
 * Get texture width.
 *
 * @param tex  Texture handle
 * @return Width in pixels, or 0 if tex is NULL
 */
int svg_texture_width(svg_texture_t tex);

/**
 * Get texture height.
 *
 * @param tex  Texture handle
 * @return Height in pixels, or 0 if tex is NULL
 */
int svg_texture_height(svg_texture_t tex);

/**
 * Get the ImGui texture ID for this texture.
 * This can be passed to ImGui::Image() for rendering.
 *
 * @param tex  Texture handle
 * @return ImTextureID (platform-specific), or NULL if tex is NULL
 */
void* svg_texture_get_imgui_id(svg_texture_t tex);

/* ============================================================================
 * Platform Integration
 * ============================================================================ */

/**
 * Initialize the texture subsystem.
 * Must be called after the graphics backend is initialized.
 *
 * @param device  Platform graphics device:
 *                - Metal: id<MTLDevice>
 *                - OpenGL: ignored (uses current context)
 * @return 1 on success, 0 on failure
 */
int svg_texture_init(void* device);

/**
 * Shutdown the texture subsystem.
 * All textures should be destroyed before calling this.
 */
void svg_texture_shutdown(void);

/**
 * Check if texture system is initialized and available.
 *
 * @return 1 if available, 0 if not
 */
int svg_texture_is_available(void);

#ifdef __cplusplus
}
#endif

#endif /* COEX_SVG_TEXTURE_H */
