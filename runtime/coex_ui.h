/**
 * Coex UI Library - Public API
 *
 * Cross-platform UI library using Dear ImGui (widgets) and Skia (rendering).
 * JSON-driven immediate mode: Coex describes UI as JSON, C renders it,
 * and returns state updates as JSON.
 *
 * Architecture:
 *   Coex App          C Runtime           Rendering
 *   ───────────────────────────────────────────────────
 *                        ┌─────────────┐
 *    layout.json  ──────>│ coex_ui.c   │───> Dear ImGui
 *    state.json   ──────>│ (interprets │───> Skia
 *                        │  JSON)      │───> Platform Shell
 *    new_state.json <────│             │<─── (Cocoa/X11)
 *    events.json   <────│             │
 *                        └─────────────┘
 */

#ifndef COEX_UI_H
#define COEX_UI_H

#include <stdint.h>

#ifdef __cplusplus
extern "C" {
#endif

/* ============================================================================
 * Initialization and Lifecycle
 * ============================================================================ */

/**
 * Initialize the UI library.
 * Creates a window and sets up rendering.
 *
 * @param config_json  Configuration JSON:
 *   {
 *     "title": "Window Title",
 *     "width": 800,
 *     "height": 600,
 *     "resizable": true,      // optional, default true
 *     "theme": "dark"         // optional: "dark" or "light"
 *   }
 * @return 1 on success, 0 on failure
 */
int64_t coex_ui_init(const char* config_json);

/**
 * Shut down the UI library and close the window.
 */
void coex_ui_shutdown(void);

/**
 * Check if the UI window should close.
 *
 * @return 1 if window should close, 0 otherwise
 */
int64_t coex_ui_should_close(void);

/**
 * Get current time since UI init in seconds.
 *
 * @return Time in seconds (high precision)
 */
double coex_ui_get_time(void);

/* ============================================================================
 * Main Render Function (JSON Interface)
 * ============================================================================ */

/**
 * Render a UI frame from JSON layout and state.
 *
 * This is the main entry point for the JSON-driven UI. It:
 * 1. Begins a new frame
 * 2. Processes events and updates input state
 * 3. Interprets the layout JSON to render ImGui widgets
 * 4. Collects state changes and events
 * 5. Renders to screen
 * 6. Returns new state and events as JSON
 *
 * @param layout_json  UI layout description (see Layout JSON Format below)
 * @param state_json   Current widget state (widget_id -> value)
 * @return JSON with updated state and events. Caller must free with coex_ui_free_json().
 *         Format: { "state": {...}, "events": [...] }
 *
 * Layout JSON Format:
 * {
 *   "type": "window",           // or "column", "row", etc.
 *   "title": "My Window",       // for windows
 *   "children": [               // nested widgets
 *     { "type": "text", "text": "Hello" },
 *     { "type": "button", "id": "btn1", "label": "Click Me" },
 *     { "type": "slider", "id": "slider1", "min": 0, "max": 100 },
 *     ...
 *   ]
 * }
 *
 * Widget Types:
 *   - window: Top-level window container
 *   - column: Vertical layout group
 *   - row: Horizontal layout group
 *   - text: Static text display
 *   - button: Clickable button
 *   - checkbox: Toggle checkbox
 *   - slider_float: Float value slider
 *   - slider_int: Integer value slider
 *   - input_text: Text input field
 *   - input_int: Integer input field
 *   - input_float: Float input field
 *   - combo: Dropdown selection
 *   - color_edit: Color picker
 *   - progress: Progress bar
 *   - tree: Tree/collapsible section
 *   - separator: Horizontal line
 *   - spacing: Vertical space
 *
 * State JSON Format (input):
 * {
 *   "slider1": 50.0,           // current slider value
 *   "checkbox1": true,         // checkbox state
 *   "input1": "hello",         // text input content
 *   ...
 * }
 *
 * Return JSON Format:
 * {
 *   "state": {                  // Updated state
 *     "slider1": 55.0,          // slider was changed
 *     "checkbox1": false,       // checkbox was toggled
 *     ...
 *   },
 *   "events": [                 // Events that occurred
 *     { "type": "click", "id": "btn1" },
 *     { "type": "change", "id": "slider1", "value": 55.0 },
 *     ...
 *   ]
 * }
 */
const char* coex_ui_render_json(const char* layout_json, const char* state_json);

/**
 * Free JSON string returned by coex_ui_render_json.
 *
 * @param json  JSON string to free
 */
void coex_ui_free_json(const char* json);

/* ============================================================================
 * Low-Level Frame Control
 * (For advanced use - normally use coex_ui_render_json instead)
 * ============================================================================ */

/**
 * Begin a new UI frame.
 * Processes events and prepares for rendering.
 */
void coex_ui_begin_frame(void);

/**
 * End the current frame and present to screen.
 */
void coex_ui_end_frame(void);

/**
 * Get pending events as JSON.
 * Events are cleared after this call.
 *
 * @return JSON array of events. Caller must free with coex_ui_free_json().
 */
const char* coex_ui_get_events_json(void);

/* ============================================================================
 * Direct Widget API
 * (For advanced use without JSON)
 * ============================================================================ */

/**
 * Begin a window.
 *
 * @param title  Window title
 * @return 1 if window is visible
 */
int64_t coex_ui_begin_window(const char* title);

/**
 * End window.
 */
void coex_ui_end_window(void);

/**
 * Display text.
 */
void coex_ui_text(const char* text);

/**
 * Display a button.
 *
 * @return 1 if clicked
 */
int64_t coex_ui_button(const char* label);

/**
 * Display a checkbox.
 *
 * @param value  Pointer to bool (will be modified if changed)
 * @return 1 if value changed
 */
int64_t coex_ui_checkbox(const char* label, int64_t* value);

/**
 * Display a float slider.
 *
 * @param value  Pointer to float value (will be modified if changed)
 * @return 1 if value changed
 */
int64_t coex_ui_slider_float(const char* label, double* value, double min, double max);

/**
 * Display an integer slider.
 *
 * @param value  Pointer to int value (will be modified if changed)
 * @return 1 if value changed
 */
int64_t coex_ui_slider_int(const char* label, int64_t* value, int64_t min, int64_t max);

/**
 * Display a text input field.
 *
 * @param buf       Text buffer (will be modified if changed)
 * @param buf_size  Size of buffer
 * @return 1 if text changed
 */
int64_t coex_ui_input_text(const char* label, char* buf, int64_t buf_size);

/**
 * Display a combo box.
 *
 * @param selected  Pointer to selected index (will be modified if changed)
 * @param items     Array of item strings
 * @param count     Number of items
 * @return 1 if selection changed
 */
int64_t coex_ui_combo(const char* label, int64_t* selected, const char* const* items, int64_t count);

/**
 * Begin horizontal layout.
 */
void coex_ui_begin_row(void);

/**
 * End horizontal layout.
 */
void coex_ui_end_row(void);

/**
 * Add spacing.
 */
void coex_ui_spacing(void);

/**
 * Add separator.
 */
void coex_ui_separator(void);

#ifdef __cplusplus
}
#endif

#endif /* COEX_UI_H */
