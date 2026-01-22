/**
 * Coex UI Platform Shell Interface
 *
 * Cross-platform abstraction for windowing, input, and rendering context.
 * Platform-specific implementations:
 *   - coex_ui_shell_macos.m (macOS/Cocoa/Metal)
 *   - coex_ui_shell_linux.c (Linux/GLFW/OpenGL)
 */

#ifndef COEX_UI_SHELL_H
#define COEX_UI_SHELL_H

#include <stdint.h>

#ifdef __cplusplus
extern "C" {
#endif

/* Window flags for coex_ui_shell_init */
#define COEX_UI_FLAG_RESIZABLE     (1 << 0)
#define COEX_UI_FLAG_BORDERLESS    (1 << 1)
#define COEX_UI_FLAG_FULLSCREEN    (1 << 2)
#define COEX_UI_FLAG_HIGHDPI       (1 << 3)
#define COEX_UI_FLAG_TRANSPARENT   (1 << 4)
#define COEX_UI_FLAG_ALWAYS_ON_TOP (1 << 5)

/* Mouse button codes */
#define COEX_UI_MOUSE_LEFT   0
#define COEX_UI_MOUSE_RIGHT  1
#define COEX_UI_MOUSE_MIDDLE 2

/* Key modifier flags */
#define COEX_UI_MOD_SHIFT   (1 << 0)
#define COEX_UI_MOD_CTRL    (1 << 1)
#define COEX_UI_MOD_ALT     (1 << 2)
#define COEX_UI_MOD_SUPER   (1 << 3)  /* Cmd on macOS, Win on Windows */

/* Common key codes (subset, matches GLFW values for compatibility) */
#define COEX_UI_KEY_ESCAPE       256
#define COEX_UI_KEY_ENTER        257
#define COEX_UI_KEY_TAB          258
#define COEX_UI_KEY_BACKSPACE    259
#define COEX_UI_KEY_INSERT       260
#define COEX_UI_KEY_DELETE       261
#define COEX_UI_KEY_RIGHT        262
#define COEX_UI_KEY_LEFT         263
#define COEX_UI_KEY_DOWN         264
#define COEX_UI_KEY_UP           265
#define COEX_UI_KEY_PAGE_UP      266
#define COEX_UI_KEY_PAGE_DOWN    267
#define COEX_UI_KEY_HOME         268
#define COEX_UI_KEY_END          269
#define COEX_UI_KEY_F1           290
#define COEX_UI_KEY_F12          301

/**
 * Event types returned by coex_ui_shell_poll_event
 */
typedef enum {
    COEX_UI_EVENT_NONE = 0,
    COEX_UI_EVENT_MOUSE_MOVE,
    COEX_UI_EVENT_MOUSE_BUTTON,
    COEX_UI_EVENT_MOUSE_SCROLL,
    COEX_UI_EVENT_KEY,
    COEX_UI_EVENT_CHAR,
    COEX_UI_EVENT_RESIZE,
    COEX_UI_EVENT_FOCUS,
    COEX_UI_EVENT_CLOSE
} CoexUIEventType;

/**
 * Platform-independent event structure
 */
typedef struct {
    CoexUIEventType type;
    union {
        struct {
            double x, y;
        } mouse_move;
        struct {
            int64_t button;
            int64_t pressed;
            int64_t modifiers;
        } mouse_button;
        struct {
            double x_offset, y_offset;
        } mouse_scroll;
        struct {
            int64_t keycode;
            int64_t scancode;
            int64_t pressed;
            int64_t modifiers;
        } key;
        struct {
            uint32_t codepoint;
        } character;
        struct {
            int64_t width, height;
        } resize;
        struct {
            int64_t focused;
        } focus;
    } data;
} CoexUIEvent;

/**
 * Initialize the platform shell and create a window.
 *
 * @param title   Window title (null-terminated UTF-8 string)
 * @param width   Initial window width in pixels
 * @param height  Initial window height in pixels
 * @param flags   Combination of COEX_UI_FLAG_* values
 * @return 1 on success, 0 on failure
 */
int64_t coex_ui_shell_init(const char* title, int64_t width, int64_t height, int64_t flags);

/**
 * Shut down the platform shell and destroy the window.
 */
void coex_ui_shell_shutdown(void);

/**
 * Start a new frame (clear buffers, prepare for rendering).
 * Must be called before any ImGui/Skia rendering.
 */
void coex_ui_shell_begin_frame(void);

/**
 * End the current frame and present to screen.
 * Must be called after all ImGui/Skia rendering is complete.
 */
void coex_ui_shell_end_frame(void);

/**
 * Check if the window should close (user clicked X, etc).
 *
 * @return 1 if window should close, 0 otherwise
 */
int64_t coex_ui_shell_should_close(void);

/**
 * Poll for the next event.
 *
 * @param event  Pointer to event structure to fill
 * @return 1 if an event was returned, 0 if no events pending
 */
int64_t coex_ui_shell_poll_event(CoexUIEvent* event);

/**
 * Process all pending events (call this once per frame).
 * Updates internal state for mouse position, key states, etc.
 */
void coex_ui_shell_process_events(void);

/**
 * Get current mouse position in window coordinates.
 *
 * @param x  Pointer to receive X coordinate (can be NULL)
 * @param y  Pointer to receive Y coordinate (can be NULL)
 */
void coex_ui_shell_get_mouse_pos(double* x, double* y);

/**
 * Get mouse button state.
 *
 * @param button  Button index (COEX_UI_MOUSE_LEFT/RIGHT/MIDDLE)
 * @return 1 if button is pressed, 0 otherwise
 */
int64_t coex_ui_shell_get_mouse_button(int64_t button);

/**
 * Get key state.
 *
 * @param keycode  Key code (COEX_UI_KEY_* or ASCII value)
 * @return 1 if key is pressed, 0 otherwise
 */
int64_t coex_ui_shell_get_key(int64_t keycode);

/**
 * Get current modifier key state.
 *
 * @return Combination of COEX_UI_MOD_* flags
 */
int64_t coex_ui_shell_get_modifiers(void);

/**
 * Get the window's content size (may differ from window size on HiDPI).
 *
 * @param width   Pointer to receive width (can be NULL)
 * @param height  Pointer to receive height (can be NULL)
 */
void coex_ui_shell_get_size(int64_t* width, int64_t* height);

/**
 * Get the framebuffer size (actual pixel dimensions for rendering).
 *
 * @param width   Pointer to receive width (can be NULL)
 * @param height  Pointer to receive height (can be NULL)
 */
void coex_ui_shell_get_framebuffer_size(int64_t* width, int64_t* height);

/**
 * Get the content scale (DPI scale factor).
 *
 * @param x_scale  Pointer to receive X scale (can be NULL)
 * @param y_scale  Pointer to receive Y scale (can be NULL)
 */
void coex_ui_shell_get_content_scale(float* x_scale, float* y_scale);

/**
 * Set the window title.
 *
 * @param title  New title (null-terminated UTF-8 string)
 */
void coex_ui_shell_set_title(const char* title);

/**
 * Set the clipboard text.
 *
 * @param text  Text to copy to clipboard (null-terminated UTF-8 string)
 */
void coex_ui_shell_set_clipboard(const char* text);

/**
 * Get the clipboard text.
 *
 * @return Clipboard contents as UTF-8 string (valid until next call), or NULL
 */
const char* coex_ui_shell_get_clipboard(void);

/**
 * Get time since shell init in seconds.
 *
 * @return Time in seconds (high precision)
 */
double coex_ui_shell_get_time(void);

/**
 * Get the rendering context pointer (Metal layer on macOS, GL context on Linux).
 * Used by Skia for GPU rendering.
 *
 * @return Platform-specific rendering context pointer
 */
void* coex_ui_shell_get_render_context(void);

#ifdef __cplusplus
}
#endif

#endif /* COEX_UI_SHELL_H */
