/**
 * Coex SVG Module - Public API
 *
 * Provides SVG rendering with state bindings for the Coex UI system.
 * SVG documents can have elements bound to state keys, enabling
 * reactive updates when state changes.
 *
 * Architecture:
 *   Coex App                SVG Module              Rendering
 *   ────────────────────────────────────────────────────────────
 *                           ┌──────────────┐
 *   svg.load(path) ────────>│ coex_svg.c   │──> LunaSVG (parse)
 *   svg.bind(elem, attr) ──>│              │
 *   svg.on(elem, event) ───>│              │
 *                           │              │
 *   render_frame(state) ───>│ Apply binds  │──> Bitmap
 *   <── updated_state ──────│ Hit test     │──> Texture
 *                           └──────────────┘──> ImGui Image
 *
 * Usage:
 *   1. Load SVG: handle = coex_svg_load("file.svg")
 *   2. Set up bindings: coex_svg_bind(handle, "myCircle", "fill", "circleColor")
 *   3. Register events: coex_svg_on(handle, "myButton", COEX_SVG_EVENT_CLICK, "buttonClicked")
 *   4. Each frame: updated_state = coex_svg_render_frame(handle, state, x, y, w, h)
 *   5. Cleanup: coex_svg_destroy(handle)
 */

#ifndef COEX_SVG_H
#define COEX_SVG_H

#include <stdint.h>

#ifdef __cplusplus
extern "C" {
#endif

/* ============================================================================
 * Event Types
 * ============================================================================ */

#define COEX_SVG_EVENT_CLICK      1
#define COEX_SVG_EVENT_HOVER      2
#define COEX_SVG_EVENT_MOUSEDOWN  3
#define COEX_SVG_EVENT_MOUSEUP    4
#define COEX_SVG_EVENT_MOUSEENTER 5
#define COEX_SVG_EVENT_MOUSELEAVE 6

/* ============================================================================
 * Module Initialization
 * ============================================================================ */

/**
 * Initialize the SVG module.
 * Must be called after the UI system is initialized.
 *
 * @param graphics_device  Platform graphics device (MTLDevice* or NULL for OpenGL)
 * @return 1 on success, 0 on failure
 */
int64_t coex_svg_init(void* graphics_device);

/**
 * Shutdown the SVG module and free all resources.
 * All SVG templates should be destroyed before calling this.
 */
void coex_svg_shutdown(void);

/**
 * Check if the SVG module is available.
 *
 * @return 1 if LunaSVG is available, 0 if using stubs
 */
int64_t coex_svg_is_available(void);

/* ============================================================================
 * SVG Template Lifecycle
 * ============================================================================ */

/**
 * Load an SVG file and create a template.
 *
 * @param path  Path to the SVG file
 * @return Template handle (positive integer), or 0 on failure
 */
int64_t coex_svg_load(const char* path);

/**
 * Load an SVG from a string and create a template.
 *
 * @param data    SVG content string
 * @param length  Length of data (0 to use strlen)
 * @return Template handle (positive integer), or 0 on failure
 */
int64_t coex_svg_load_from_data(const char* data, int64_t length);

/**
 * Destroy an SVG template and free all resources.
 *
 * @param handle  Template handle
 */
void coex_svg_destroy(int64_t handle);

/* ============================================================================
 * Template Properties
 * ============================================================================ */

/**
 * Get the intrinsic width of the SVG.
 *
 * @param handle  Template handle
 * @return Width in SVG units, or 0 if handle is invalid
 */
double coex_svg_width(int64_t handle);

/**
 * Get the intrinsic height of the SVG.
 *
 * @param handle  Template handle
 * @return Height in SVG units, or 0 if handle is invalid
 */
double coex_svg_height(int64_t handle);

/* ============================================================================
 * State Bindings
 * ============================================================================ */

/**
 * Bind an element attribute to a state key.
 * When the state key changes, the attribute will be updated before rendering.
 *
 * @param handle      Template handle
 * @param element_id  SVG element id attribute
 * @param attribute   SVG attribute name (e.g., "fill", "stroke", "opacity")
 * @param state_key   Key in the state object to read from
 * @return 1 on success, 0 on failure
 *
 * Example:
 *   coex_svg_bind(handle, "statusCircle", "fill", "statusColor")
 *   // When state["statusColor"] = "#ff0000", the circle turns red
 */
int64_t coex_svg_bind(int64_t handle, const char* element_id,
                      const char* attribute, const char* state_key);

/**
 * Bind multiple attributes on an element using a JSON spec.
 * More efficient than multiple coex_svg_bind calls.
 *
 * @param handle       Template handle
 * @param element_id   SVG element id attribute
 * @param bindings_json  JSON object mapping attributes to state keys
 *                       e.g., {"fill": "color", "opacity": "alpha"}
 * @return Number of bindings created, or 0 on failure
 */
int64_t coex_svg_bind_element(int64_t handle, const char* element_id,
                              const char* bindings_json);

/**
 * Remove all bindings for an element.
 *
 * @param handle      Template handle
 * @param element_id  SVG element id attribute
 * @return Number of bindings removed
 */
int64_t coex_svg_unbind(int64_t handle, const char* element_id);

/* ============================================================================
 * Event Registration
 * ============================================================================ */

/**
 * Register an event handler for an element.
 * When the event occurs, the state key will be set to true (for click events)
 * or updated with event data.
 *
 * @param handle      Template handle
 * @param element_id  SVG element id attribute
 * @param event_type  Event type (COEX_SVG_EVENT_*)
 * @param state_key   State key to update when event fires
 * @return 1 on success, 0 on failure
 *
 * Example:
 *   coex_svg_on(handle, "playButton", COEX_SVG_EVENT_CLICK, "playClicked")
 *   // When user clicks playButton, state["playClicked"] = true
 */
int64_t coex_svg_on(int64_t handle, const char* element_id,
                    int64_t event_type, const char* state_key);

/**
 * Remove an event handler.
 *
 * @param handle      Template handle
 * @param element_id  SVG element id attribute
 * @param event_type  Event type to remove
 * @return 1 if removed, 0 if not found
 */
int64_t coex_svg_off(int64_t handle, const char* element_id, int64_t event_type);

/**
 * Get the number of registered events for a template.
 *
 * @param handle  Template handle
 * @return Number of registered events
 */
int64_t coex_svg_get_event_count(int64_t handle);

/**
 * Get event info by index.
 * Used by UI module to place invisible buttons over SVG elements.
 *
 * @param handle      Template handle
 * @param index       Event index (0 to event_count-1)
 * @param event_type  Output: event type (COEX_SVG_EVENT_*)
 * @param state_key   Output: state key (pointer valid until event is removed)
 * @param bbox_x, bbox_y, bbox_w, bbox_h  Output: bounding box in SVG coordinates
 * @return 1 if valid index, 0 if out of bounds or invalid bbox
 */
int64_t coex_svg_get_event_info(int64_t handle, int64_t index,
                                 int64_t* event_type, const char** state_key,
                                 float* bbox_x, float* bbox_y,
                                 float* bbox_w, float* bbox_h);

/* ============================================================================
 * Rendering
 * ============================================================================ */

/**
 * Render the SVG and process events for one frame.
 * This is the main per-frame function that:
 *   1. Applies all bindings from state_json to element attributes
 *   2. Re-renders the SVG to a texture
 *   3. Displays the texture via ImGui
 *   4. Processes mouse events for registered elements
 *   5. Returns updated state with triggered events
 *
 * @param handle      Template handle
 * @param state_json  Current state as JSON object
 * @param screen_x    X position on screen (for hit testing)
 * @param screen_y    Y position on screen (for hit testing)
 * @param width       Display width in pixels
 * @param height      Display height in pixels
 * @return Updated state JSON with event flags, or NULL on failure
 *         Caller must free with coex_svg_free_json()
 *
 * The returned state includes all input state plus any event flags set to true
 * when events fire. Events are edge-triggered: they are set once when the
 * event occurs, not held continuously.
 */
const char* coex_svg_render_frame(int64_t handle, const char* state_json,
                                   float screen_x, float screen_y,
                                   int64_t width, int64_t height);

/**
 * Get a widget descriptor for the SVG image.
 * Returns a JSON object that can be included in a UI layout.
 *
 * @param handle  Template handle
 * @param width   Display width
 * @param height  Display height
 * @return JSON widget descriptor, or NULL on failure
 *         Caller must free with coex_svg_free_json()
 *
 * Example return:
 *   { "type": "svg_image", "handle": 1, "width": 400, "height": 300 }
 */
const char* coex_svg_image_descriptor(int64_t handle, int64_t width, int64_t height);

/**
 * Free a JSON string returned by SVG module functions.
 *
 * @param json  JSON string to free (safe to call with NULL)
 */
void coex_svg_free_json(const char* json);

/* ============================================================================
 * Direct Rendering (Advanced)
 * ============================================================================ */

/**
 * Render the SVG to an internal texture without displaying.
 * Use this for off-screen rendering or manual texture management.
 *
 * @param handle  Template handle
 * @param width   Render width in pixels
 * @param height  Render height in pixels
 * @return 1 on success, 0 on failure
 */
int64_t coex_svg_render_to_texture(int64_t handle, int64_t width, int64_t height);

/**
 * Get the ImGui texture ID for a rendered SVG.
 * Only valid after coex_svg_render_to_texture or coex_svg_render_frame.
 *
 * @param handle  Template handle
 * @return ImTextureID for use with ImGui::Image, or NULL
 */
void* coex_svg_get_texture_id(int64_t handle);

/**
 * Apply state bindings to the SVG document without rendering.
 * Useful for preparing the document before multiple render calls.
 *
 * @param handle      Template handle
 * @param state_json  State JSON object
 * @return Number of bindings applied
 */
int64_t coex_svg_apply_state(int64_t handle, const char* state_json);

/* ============================================================================
 * Utility Functions
 * ============================================================================ */

/**
 * Get element bounding box in SVG coordinates.
 *
 * @param handle      Template handle
 * @param element_id  Element id
 * @param x, y, w, h  Output bounding box
 * @return 1 if found, 0 if element not found
 */
int64_t coex_svg_get_element_bounds(int64_t handle, const char* element_id,
                                     float* x, float* y, float* w, float* h);

/**
 * Check if a point (in screen coordinates) hits an element.
 *
 * @param handle      Template handle
 * @param element_id  Element id to test
 * @param screen_x    Point X in screen coords
 * @param screen_y    Point Y in screen coords
 * @param img_x       SVG image X position on screen
 * @param img_y       SVG image Y position on screen
 * @param img_w       SVG image display width
 * @param img_h       SVG image display height
 * @return 1 if hit, 0 if not
 */
int64_t coex_svg_hit_test(int64_t handle, const char* element_id,
                          float screen_x, float screen_y,
                          float img_x, float img_y,
                          float img_w, float img_h);

#ifdef __cplusplus
}
#endif

#endif /* COEX_SVG_H */
