/**
 * Coex UI ImGui Wrapper Header
 *
 * C wrapper for Dear ImGui functionality.
 * Used by the JSON layout interpreter to render widgets.
 */

#ifndef COEX_UI_IMGUI_H
#define COEX_UI_IMGUI_H

#include <stdint.h>

#ifdef __cplusplus
extern "C" {
#endif

/* Widget result flags */
#define COEX_IMGUI_RESULT_CLICKED    (1 << 0)
#define COEX_IMGUI_RESULT_CHANGED    (1 << 1)
#define COEX_IMGUI_RESULT_HOVERED    (1 << 2)
#define COEX_IMGUI_RESULT_ACTIVATED  (1 << 3)
#define COEX_IMGUI_RESULT_DEACTIVATED (1 << 4)

/* Window flags */
#define COEX_IMGUI_WINDOW_NO_TITLE_BAR    (1 << 0)
#define COEX_IMGUI_WINDOW_NO_RESIZE       (1 << 1)
#define COEX_IMGUI_WINDOW_NO_MOVE         (1 << 2)
#define COEX_IMGUI_WINDOW_NO_SCROLLBAR    (1 << 3)
#define COEX_IMGUI_WINDOW_NO_BACKGROUND   (1 << 4)
#define COEX_IMGUI_WINDOW_ALWAYS_AUTO_RESIZE (1 << 5)

/* Input text flags */
#define COEX_IMGUI_INPUT_TEXT_READONLY    (1 << 0)
#define COEX_IMGUI_INPUT_TEXT_PASSWORD    (1 << 1)
#define COEX_IMGUI_INPUT_TEXT_MULTILINE   (1 << 2)
#define COEX_IMGUI_INPUT_TEXT_ENTER_RETURNS_TRUE (1 << 3)

/**
 * Initialize ImGui context.
 * Must be called after platform shell is initialized.
 *
 * @return 1 on success, 0 on failure
 */
int64_t coex_imgui_init(void);

/**
 * Shutdown ImGui and free resources.
 */
void coex_imgui_shutdown(void);

/**
 * Start a new ImGui frame.
 * Must be called once per frame before any widget calls.
 *
 * @param width   Display width
 * @param height  Display height
 * @param delta_time  Time since last frame in seconds
 */
void coex_imgui_new_frame(int64_t width, int64_t height, double delta_time);

/**
 * End ImGui frame and generate draw data.
 */
void coex_imgui_render(void);

/**
 * Get draw data for rendering.
 * Valid until next call to coex_imgui_new_frame.
 *
 * @return Opaque pointer to ImDrawData
 */
void* coex_imgui_get_draw_data(void);

/* ============================================================================
 * Input handling
 * ============================================================================ */

/**
 * Report mouse position to ImGui.
 */
void coex_imgui_io_set_mouse_pos(double x, double y);

/**
 * Report mouse button state to ImGui.
 */
void coex_imgui_io_set_mouse_down(int64_t button, int64_t pressed);

/**
 * Report mouse scroll to ImGui.
 */
void coex_imgui_io_set_mouse_scroll(double x, double y);

/**
 * Report key state to ImGui.
 */
void coex_imgui_io_set_key(int64_t keycode, int64_t pressed);

/**
 * Report character input to ImGui.
 */
void coex_imgui_io_add_char(uint32_t codepoint);

/**
 * Report modifier key state.
 */
void coex_imgui_io_set_modifiers(int64_t ctrl, int64_t shift, int64_t alt, int64_t super);

/**
 * Check if ImGui wants keyboard input.
 */
int64_t coex_imgui_wants_keyboard(void);

/**
 * Check if ImGui wants mouse input.
 */
int64_t coex_imgui_wants_mouse(void);

/* ============================================================================
 * Container widgets
 * ============================================================================ */

/**
 * Begin a window.
 *
 * @param label  Window title/ID
 * @param flags  Window flags
 * @return 1 if window is visible and should be rendered, 0 otherwise
 */
int64_t coex_imgui_begin_window(const char* label, int64_t flags);

/**
 * End current window.
 */
void coex_imgui_end_window(void);

/**
 * Begin horizontal layout group.
 */
void coex_imgui_begin_horizontal(void);

/**
 * End horizontal layout group.
 */
void coex_imgui_end_horizontal(void);

/**
 * Add spacing between widgets.
 */
void coex_imgui_spacing(void);

/**
 * Add same-line continuation.
 */
void coex_imgui_same_line(void);

/**
 * Add separator line.
 */
void coex_imgui_separator(void);

/**
 * Push item width for subsequent widgets.
 */
void coex_imgui_push_item_width(double width);

/**
 * Pop item width.
 */
void coex_imgui_pop_item_width(void);

/* ============================================================================
 * Basic widgets
 * ============================================================================ */

/**
 * Display text.
 *
 * @param text  Text to display
 */
void coex_imgui_text(const char* text);

/**
 * Display colored text.
 *
 * @param text  Text to display
 * @param r,g,b,a  Color (0.0-1.0)
 */
void coex_imgui_text_colored(const char* text, float r, float g, float b, float a);

/**
 * Display wrapped text.
 */
void coex_imgui_text_wrapped(const char* text);

/**
 * Create a button.
 *
 * @param label  Button text
 * @return COEX_IMGUI_RESULT_CLICKED if clicked
 */
int64_t coex_imgui_button(const char* label);

/**
 * Create a button with specific size.
 */
int64_t coex_imgui_button_sized(const char* label, double width, double height);

/**
 * Create a small button (no frame padding).
 */
int64_t coex_imgui_small_button(const char* label);

/**
 * Create a checkbox.
 *
 * @param label  Checkbox label
 * @param value  Pointer to bool value
 * @return COEX_IMGUI_RESULT_CHANGED if value changed
 */
int64_t coex_imgui_checkbox(const char* label, int* value);

/**
 * Create a radio button.
 *
 * @param label  Radio button label
 * @param active  1 if this is the selected option
 * @return COEX_IMGUI_RESULT_CLICKED if clicked
 */
int64_t coex_imgui_radio_button(const char* label, int active);

/* ============================================================================
 * Input widgets
 * ============================================================================ */

/**
 * Create a text input field.
 *
 * @param label  Input label
 * @param buf    Buffer for text (will be modified in place)
 * @param buf_size  Size of buffer
 * @param flags  Input text flags
 * @return COEX_IMGUI_RESULT_CHANGED if text was modified
 */
int64_t coex_imgui_input_text(const char* label, char* buf, int64_t buf_size, int64_t flags);

/**
 * Create a multiline text input.
 */
int64_t coex_imgui_input_text_multiline(const char* label, char* buf, int64_t buf_size,
                                         double width, double height, int64_t flags);

/**
 * Create an integer input field.
 *
 * @param label  Input label
 * @param value  Pointer to int value
 * @return COEX_IMGUI_RESULT_CHANGED if value changed
 */
int64_t coex_imgui_input_int(const char* label, int64_t* value);

/**
 * Create a float input field.
 */
int64_t coex_imgui_input_float(const char* label, double* value);

/* ============================================================================
 * Sliders
 * ============================================================================ */

/**
 * Create a float slider.
 *
 * @param label  Slider label
 * @param value  Pointer to float value
 * @param min    Minimum value
 * @param max    Maximum value
 * @return COEX_IMGUI_RESULT_CHANGED if value changed
 */
int64_t coex_imgui_slider_float(const char* label, double* value, double min, double max);

/**
 * Create an integer slider.
 */
int64_t coex_imgui_slider_int(const char* label, int64_t* value, int64_t min, int64_t max);

/**
 * Create a vertical slider.
 */
int64_t coex_imgui_vslider_float(const char* label, double width, double height,
                                  double* value, double min, double max);

/* ============================================================================
 * Selection widgets
 * ============================================================================ */

/**
 * Create a combo box (dropdown).
 *
 * @param label  Combo label
 * @param current_item  Pointer to selected index
 * @param items  Null-terminated array of item strings
 * @param items_count  Number of items
 * @return COEX_IMGUI_RESULT_CHANGED if selection changed
 */
int64_t coex_imgui_combo(const char* label, int64_t* current_item,
                          const char* const* items, int64_t items_count);

/**
 * Begin a combo box for custom content.
 *
 * @param label  Combo label
 * @param preview  Preview text shown when closed
 * @return 1 if combo is open, 0 otherwise
 */
int64_t coex_imgui_begin_combo(const char* label, const char* preview);

/**
 * End combo box.
 */
void coex_imgui_end_combo(void);

/**
 * Create a selectable item (for lists).
 *
 * @param label  Item text
 * @param selected  1 if item is selected
 * @return COEX_IMGUI_RESULT_CLICKED if clicked
 */
int64_t coex_imgui_selectable(const char* label, int selected);

/* ============================================================================
 * Color widgets
 * ============================================================================ */

/**
 * Create a color edit widget (RGB).
 *
 * @param label  Widget label
 * @param color  Array of 3 floats (r,g,b, 0.0-1.0)
 * @return COEX_IMGUI_RESULT_CHANGED if color changed
 */
int64_t coex_imgui_color_edit3(const char* label, float* color);

/**
 * Create a color edit widget (RGBA).
 *
 * @param label  Widget label
 * @param color  Array of 4 floats (r,g,b,a, 0.0-1.0)
 * @return COEX_IMGUI_RESULT_CHANGED if color changed
 */
int64_t coex_imgui_color_edit4(const char* label, float* color);

/* ============================================================================
 * Progress widgets
 * ============================================================================ */

/**
 * Display a progress bar.
 *
 * @param fraction  Progress (0.0-1.0)
 * @param width     Width (-1 for default)
 * @param height    Height (-1 for default)
 * @param overlay   Optional overlay text
 */
void coex_imgui_progress_bar(double fraction, double width, double height, const char* overlay);

/* ============================================================================
 * Tree/Collapsing widgets
 * ============================================================================ */

/**
 * Create a collapsing header.
 *
 * @param label  Header text
 * @return 1 if section is open, 0 if collapsed
 */
int64_t coex_imgui_collapsing_header(const char* label);

/**
 * Begin a tree node.
 *
 * @param label  Node text
 * @return 1 if node is open, 0 if collapsed
 */
int64_t coex_imgui_tree_node(const char* label);

/**
 * End a tree node. Only call if coex_imgui_tree_node returned 1.
 */
void coex_imgui_tree_pop(void);

/* ============================================================================
 * ID management (for dynamic widgets)
 * ============================================================================ */

/**
 * Push string ID onto the ID stack.
 */
void coex_imgui_push_id_str(const char* str_id);

/**
 * Push integer ID onto the ID stack.
 */
void coex_imgui_push_id_int(int64_t int_id);

/**
 * Pop ID from the stack.
 */
void coex_imgui_pop_id(void);

/* ============================================================================
 * Style
 * ============================================================================ */

/**
 * Set the current style to dark theme.
 */
void coex_imgui_style_colors_dark(void);

/**
 * Set the current style to light theme.
 */
void coex_imgui_style_colors_light(void);

/**
 * Push a style color.
 *
 * @param idx  Color index (ImGuiCol_*)
 * @param r,g,b,a  Color values (0.0-1.0)
 */
void coex_imgui_push_style_color(int64_t idx, float r, float g, float b, float a);

/**
 * Pop style colors.
 */
void coex_imgui_pop_style_color(int64_t count);

/**
 * Push a style variable (float).
 */
void coex_imgui_push_style_var_float(int64_t idx, double val);

/**
 * Push a style variable (vec2).
 */
void coex_imgui_push_style_var_vec2(int64_t idx, double x, double y);

/**
 * Pop style variables.
 */
void coex_imgui_pop_style_var(int64_t count);

/* ============================================================================
 * Font Atlas
 * ============================================================================ */

/**
 * Build the font atlas and get texture data.
 * Call this before creating the font texture in the renderer.
 *
 * @param out_pixels      Receives pointer to pixel data (owned by ImGui, don't free)
 * @param out_width       Receives texture width
 * @param out_height      Receives texture height
 * @param out_bytes_per_pixel  Receives bytes per pixel (1 for alpha, 4 for RGBA)
 * @return 1 on success, 0 on failure
 */
int64_t coex_imgui_get_font_tex_data_rgba32(
    unsigned char** out_pixels,
    int* out_width,
    int* out_height,
    int* out_bytes_per_pixel
);

/**
 * Set the font texture ID after creating the texture.
 * This tells ImGui what texture handle to use when rendering text.
 *
 * @param texture_id  Opaque texture handle (platform-specific)
 */
void coex_imgui_set_font_tex_id(void* texture_id);

#ifdef __cplusplus
}
#endif

#endif /* COEX_UI_IMGUI_H */
