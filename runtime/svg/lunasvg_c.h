/**
 * LunaSVG C Wrapper Header
 *
 * C-compatible wrapper for the LunaSVG C++ library.
 * Provides opaque handle types and C functions for:
 *   - Document loading and lifecycle
 *   - Element access and attribute manipulation
 *   - Bitmap rendering
 *
 * All functions are safe to call with NULL handles (they will return
 * appropriate error values).
 */

#ifndef LUNASVG_C_H
#define LUNASVG_C_H

#include <stdint.h>
#include <stddef.h>

#ifdef __cplusplus
extern "C" {
#endif

/* ============================================================================
 * Opaque Handle Types
 * ============================================================================ */

/** Opaque handle to an SVG document */
typedef void* lunasvg_document_t;

/** Opaque handle to an SVG element within a document */
typedef void* lunasvg_element_t;

/** Opaque handle to a rendered bitmap */
typedef void* lunasvg_bitmap_t;

/* ============================================================================
 * Document Lifecycle
 * ============================================================================ */

/**
 * Load an SVG document from a file.
 *
 * @param filename  Path to the SVG file
 * @return Document handle, or NULL on failure
 */
lunasvg_document_t lunasvg_document_load_from_file(const char* filename);

/**
 * Load an SVG document from a string.
 *
 * @param data    SVG content string
 * @param length  Length of data in bytes (0 to use strlen)
 * @return Document handle, or NULL on failure
 */
lunasvg_document_t lunasvg_document_load_from_data(const char* data, size_t length);

/**
 * Destroy a document and free all associated resources.
 * Safe to call with NULL.
 *
 * @param doc  Document handle
 */
void lunasvg_document_destroy(lunasvg_document_t doc);

/* ============================================================================
 * Document Properties
 * ============================================================================ */

/**
 * Get the intrinsic width of the SVG document.
 *
 * @param doc  Document handle
 * @return Width in SVG units, or 0 if doc is NULL
 */
float lunasvg_document_width(lunasvg_document_t doc);

/**
 * Get the intrinsic height of the SVG document.
 *
 * @param doc  Document handle
 * @return Height in SVG units, or 0 if doc is NULL
 */
float lunasvg_document_height(lunasvg_document_t doc);

/**
 * Get the viewBox of the document.
 *
 * @param doc  Document handle
 * @param x    Receives viewBox X origin
 * @param y    Receives viewBox Y origin
 * @param w    Receives viewBox width
 * @param h    Receives viewBox height
 * @return 1 if viewBox is available, 0 if not or doc is NULL
 */
int lunasvg_document_get_viewbox(lunasvg_document_t doc,
                                  float* x, float* y, float* w, float* h);

/* ============================================================================
 * Element Access
 * ============================================================================ */

/**
 * Find an element by its id attribute.
 *
 * @param doc  Document handle
 * @param id   Element id to find
 * @return Element handle, or NULL if not found or doc is NULL
 *
 * Note: The returned element handle is only valid while the document exists.
 */
lunasvg_element_t lunasvg_document_get_element_by_id(lunasvg_document_t doc,
                                                      const char* id);

/**
 * Get the root element of the document.
 *
 * @param doc  Document handle
 * @return Root element handle, or NULL if doc is NULL
 */
lunasvg_element_t lunasvg_document_root(lunasvg_document_t doc);

/* ============================================================================
 * Element Properties
 * ============================================================================ */

/**
 * Set an attribute on an element.
 * This modifies the document's internal state.
 *
 * @param elem  Element handle
 * @param name  Attribute name (e.g., "fill", "stroke", "transform")
 * @param value Attribute value
 * @return 1 on success, 0 if elem is NULL
 */
int lunasvg_element_set_attribute(lunasvg_element_t elem,
                                   const char* name,
                                   const char* value);

/**
 * Get an attribute value from an element.
 *
 * @param elem  Element handle
 * @param name  Attribute name
 * @return Attribute value string (owned by caller, must free), or NULL
 */
char* lunasvg_element_get_attribute(lunasvg_element_t elem, const char* name);

/**
 * Check if an element has a specific attribute.
 *
 * @param elem  Element handle
 * @param name  Attribute name
 * @return 1 if attribute exists, 0 if not or elem is NULL
 */
int lunasvg_element_has_attribute(lunasvg_element_t elem, const char* name);

/**
 * Get the bounding box of an element in SVG coordinate space.
 *
 * @param elem  Element handle
 * @param x     Receives bounding box X
 * @param y     Receives bounding box Y
 * @param w     Receives bounding box width
 * @param h     Receives bounding box height
 * @return 1 on success, 0 if elem is NULL or has no geometry
 */
int lunasvg_element_get_bounding_box(lunasvg_element_t elem,
                                      float* x, float* y, float* w, float* h);

/**
 * Get the transform matrix of an element.
 * The matrix is in the form [a, b, c, d, e, f] representing:
 *   | a c e |
 *   | b d f |
 *   | 0 0 1 |
 *
 * @param elem    Element handle
 * @param matrix  Array of 6 floats to receive the matrix
 * @return 1 on success, 0 if elem is NULL
 */
int lunasvg_element_get_transform(lunasvg_element_t elem, float* matrix);

/* ============================================================================
 * Rendering
 * ============================================================================ */

/**
 * Render the document to a bitmap.
 *
 * @param doc      Document handle
 * @param width    Output bitmap width in pixels
 * @param height   Output bitmap height in pixels
 * @param bgcolor  Background color as 0xRRGGBBAA (0x00000000 for transparent)
 * @return Bitmap handle, or NULL on failure
 */
lunasvg_bitmap_t lunasvg_document_render_to_bitmap(lunasvg_document_t doc,
                                                    int width, int height,
                                                    uint32_t bgcolor);

/**
 * Render the document to a bitmap with a transform.
 * Allows specifying a custom transformation matrix for the render.
 *
 * @param doc      Document handle
 * @param width    Output bitmap width in pixels
 * @param height   Output bitmap height in pixels
 * @param bgcolor  Background color as 0xRRGGBBAA
 * @param matrix   6-element transform matrix [a, b, c, d, e, f]
 * @return Bitmap handle, or NULL on failure
 */
lunasvg_bitmap_t lunasvg_document_render_to_bitmap_with_transform(
    lunasvg_document_t doc,
    int width, int height,
    uint32_t bgcolor,
    const float* matrix);

/**
 * Render a specific element to a bitmap.
 *
 * @param doc      Document handle (needed for rendering context)
 * @param elem     Element to render
 * @param width    Output bitmap width in pixels
 * @param height   Output bitmap height in pixels
 * @param bgcolor  Background color as 0xRRGGBBAA
 * @return Bitmap handle, or NULL on failure
 */
lunasvg_bitmap_t lunasvg_element_render_to_bitmap(lunasvg_document_t doc,
                                                   lunasvg_element_t elem,
                                                   int width, int height,
                                                   uint32_t bgcolor);

/* ============================================================================
 * Bitmap Access
 * ============================================================================ */

/**
 * Convert bitmap from ARGB32 Premultiplied to RGBA Plain format.
 * This must be called before using the bitmap data with OpenGL/Metal textures.
 *
 * @param bmp  Bitmap handle
 */
void lunasvg_bitmap_convert_to_rgba(lunasvg_bitmap_t bmp);

/**
 * Get the pixel data from a bitmap.
 * Data is in ARGB32 Premultiplied format by default.
 * Call lunasvg_bitmap_convert_to_rgba() first for RGBA format.
 *
 * @param bmp  Bitmap handle
 * @return Pointer to pixel data, or NULL if bmp is NULL
 *
 * Note: Pointer is valid only while bitmap exists.
 */
uint8_t* lunasvg_bitmap_data(lunasvg_bitmap_t bmp);

/**
 * Get the width of a bitmap.
 *
 * @param bmp  Bitmap handle
 * @return Width in pixels, or 0 if bmp is NULL
 */
int lunasvg_bitmap_width(lunasvg_bitmap_t bmp);

/**
 * Get the height of a bitmap.
 *
 * @param bmp  Bitmap handle
 * @return Height in pixels, or 0 if bmp is NULL
 */
int lunasvg_bitmap_height(lunasvg_bitmap_t bmp);

/**
 * Get the stride (bytes per row) of a bitmap.
 *
 * @param bmp  Bitmap handle
 * @return Stride in bytes, or 0 if bmp is NULL
 */
int lunasvg_bitmap_stride(lunasvg_bitmap_t bmp);

/**
 * Destroy a bitmap and free its memory.
 * Safe to call with NULL.
 *
 * @param bmp  Bitmap handle
 */
void lunasvg_bitmap_destroy(lunasvg_bitmap_t bmp);

/* ============================================================================
 * Utility Functions
 * ============================================================================ */

/**
 * Free a string allocated by this library.
 *
 * @param str  String to free (safe to call with NULL)
 */
void lunasvg_free_string(char* str);

/**
 * Check if LunaSVG is available.
 * Returns 1 if compiled with LunaSVG support, 0 if using stubs.
 */
int lunasvg_is_available(void);

/* Note: lunasvg_version() is declared in the official lunasvg.h header
 * when COEX_SVG_HAS_LUNASVG is defined. For stub builds, we don't provide
 * a version function - use lunasvg_is_available() to check availability. */

#ifdef __cplusplus
}
#endif

#endif /* LUNASVG_C_H */
