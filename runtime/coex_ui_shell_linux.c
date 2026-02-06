/**
 * Coex UI Platform Shell - Linux Implementation
 *
 * Uses GLFW for windowing/input and OpenGL for rendering context.
 * Provides the same API as the macOS implementation.
 */

#include "coex_ui_shell.h"
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>
#include <pthread.h>

#ifdef COEX_UI_HAS_GLFW
#include <GLFW/glfw3.h>
#ifdef __linux__
#define GLFW_EXPOSE_NATIVE_X11
#include <GLFW/glfw3native.h>
#endif
#endif

/* Global state */
static struct {
    int initialized;
    int should_close;

#ifdef COEX_UI_HAS_GLFW
    GLFWwindow* window;
#endif

    /* Input state */
    double mouse_x, mouse_y;
    int mouse_buttons[3];  /* left, right, middle */
    int key_states[512];   /* simple key state array */
    int modifiers;

    /* Timing */
    double start_time;

    /* Event queue */
    CoexUIEvent event_queue[64];
    int event_read_idx;
    int event_write_idx;
    pthread_mutex_t event_mutex;

    /* Window properties */
    int64_t window_width, window_height;
    int64_t framebuffer_width, framebuffer_height;
    float content_scale_x, content_scale_y;

    /* Clipboard */
    char* clipboard_text;
} _ui_state;

/* ============================================================================
 * Event Queue Management
 * ============================================================================ */

static void push_event(CoexUIEvent* event) {
    pthread_mutex_lock(&_ui_state.event_mutex);
    int next_write = (_ui_state.event_write_idx + 1) % 64;
    if (next_write != _ui_state.event_read_idx) {
        _ui_state.event_queue[_ui_state.event_write_idx] = *event;
        _ui_state.event_write_idx = next_write;
    }
    pthread_mutex_unlock(&_ui_state.event_mutex);
}

#ifdef COEX_UI_HAS_GLFW

/* ============================================================================
 * GLFW Callbacks
 * ============================================================================ */

static void glfw_error_callback(int error, const char* description) {
    fprintf(stderr, "GLFW Error %d: %s\n", error, description);
}

static void glfw_window_close_callback(GLFWwindow* window) {
    (void)window;
    _ui_state.should_close = 1;

    CoexUIEvent event = {0};
    event.type = COEX_UI_EVENT_CLOSE;
    push_event(&event);
}

static void glfw_framebuffer_size_callback(GLFWwindow* window, int width, int height) {
    (void)window;
    _ui_state.framebuffer_width = width;
    _ui_state.framebuffer_height = height;

    CoexUIEvent event = {0};
    event.type = COEX_UI_EVENT_RESIZE;
    event.data.resize.width = width;
    event.data.resize.height = height;
    push_event(&event);
}

static void glfw_window_size_callback(GLFWwindow* window, int width, int height) {
    (void)window;
    _ui_state.window_width = width;
    _ui_state.window_height = height;
}

static void glfw_window_focus_callback(GLFWwindow* window, int focused) {
    (void)window;
    CoexUIEvent event = {0};
    event.type = COEX_UI_EVENT_FOCUS;
    event.data.focus.focused = focused;
    push_event(&event);
}

static void glfw_cursor_pos_callback(GLFWwindow* window, double xpos, double ypos) {
    (void)window;
    _ui_state.mouse_x = xpos;
    _ui_state.mouse_y = ypos;

    CoexUIEvent event = {0};
    event.type = COEX_UI_EVENT_MOUSE_MOVE;
    event.data.mouse_move.x = xpos;
    event.data.mouse_move.y = ypos;
    push_event(&event);
}

static void glfw_mouse_button_callback(GLFWwindow* window, int button, int action, int mods) {
    (void)window;
    (void)mods;

    int coex_button = -1;
    if (button == GLFW_MOUSE_BUTTON_LEFT) coex_button = COEX_UI_MOUSE_LEFT;
    else if (button == GLFW_MOUSE_BUTTON_RIGHT) coex_button = COEX_UI_MOUSE_RIGHT;
    else if (button == GLFW_MOUSE_BUTTON_MIDDLE) coex_button = COEX_UI_MOUSE_MIDDLE;

    if (coex_button >= 0 && coex_button < 3) {
        _ui_state.mouse_buttons[coex_button] = (action == GLFW_PRESS);

        CoexUIEvent event = {0};
        event.type = COEX_UI_EVENT_MOUSE_BUTTON;
        event.data.mouse_button.button = coex_button;
        event.data.mouse_button.pressed = (action == GLFW_PRESS);
        event.data.mouse_button.modifiers = _ui_state.modifiers;
        push_event(&event);
    }
}

static void glfw_scroll_callback(GLFWwindow* window, double xoffset, double yoffset) {
    (void)window;
    CoexUIEvent event = {0};
    event.type = COEX_UI_EVENT_MOUSE_SCROLL;
    event.data.mouse_scroll.x_offset = xoffset;
    event.data.mouse_scroll.y_offset = yoffset;
    push_event(&event);
}

static int translate_glfw_key(int key) {
    /* GLFW key codes already match our definitions for special keys */
    if (key >= GLFW_KEY_ESCAPE && key <= GLFW_KEY_F12) {
        return key;  /* GLFW uses same values */
    }
    /* ASCII keys */
    if (key >= 32 && key <= 127) {
        return key;
    }
    return -1;
}

static void update_modifiers(int mods) {
    _ui_state.modifiers = 0;
    if (mods & GLFW_MOD_SHIFT) _ui_state.modifiers |= COEX_UI_MOD_SHIFT;
    if (mods & GLFW_MOD_CONTROL) _ui_state.modifiers |= COEX_UI_MOD_CTRL;
    if (mods & GLFW_MOD_ALT) _ui_state.modifiers |= COEX_UI_MOD_ALT;
    if (mods & GLFW_MOD_SUPER) _ui_state.modifiers |= COEX_UI_MOD_SUPER;
}

static void glfw_key_callback(GLFWwindow* window, int key, int scancode, int action, int mods) {
    (void)window;

    update_modifiers(mods);

    int keycode = translate_glfw_key(key);
    if (keycode >= 0 && keycode < 512) {
        _ui_state.key_states[keycode] = (action != GLFW_RELEASE);
    }

    if (action != GLFW_REPEAT) {
        CoexUIEvent event = {0};
        event.type = COEX_UI_EVENT_KEY;
        event.data.key.keycode = keycode;
        event.data.key.scancode = scancode;
        event.data.key.pressed = (action == GLFW_PRESS);
        event.data.key.modifiers = _ui_state.modifiers;
        push_event(&event);
    }
}

static void glfw_char_callback(GLFWwindow* window, unsigned int codepoint) {
    (void)window;
    CoexUIEvent event = {0};
    event.type = COEX_UI_EVENT_CHAR;
    event.data.character.codepoint = codepoint;
    push_event(&event);
}

static void glfw_content_scale_callback(GLFWwindow* window, float xscale, float yscale) {
    (void)window;
    _ui_state.content_scale_x = xscale;
    _ui_state.content_scale_y = yscale;
}

#endif /* COEX_UI_HAS_GLFW */

/* ============================================================================
 * Public API Implementation
 * ============================================================================ */

int64_t coex_ui_shell_init(const char* title, int64_t width, int64_t height, int64_t flags) {
#ifdef COEX_UI_HAS_GLFW
    if (_ui_state.initialized) {
        return 1;  /* Already initialized */
    }

    memset(&_ui_state, 0, sizeof(_ui_state));
    pthread_mutex_init(&_ui_state.event_mutex, NULL);

    /* Initialize GLFW */
    glfwSetErrorCallback(glfw_error_callback);
    if (!glfwInit()) {
        fprintf(stderr, "coex_ui_shell_init: Failed to initialize GLFW\n");
        return 0;
    }

    /* Configure OpenGL context */
    glfwWindowHint(GLFW_CONTEXT_VERSION_MAJOR, 3);
    glfwWindowHint(GLFW_CONTEXT_VERSION_MINOR, 3);
    glfwWindowHint(GLFW_OPENGL_PROFILE, GLFW_OPENGL_CORE_PROFILE);
    glfwWindowHint(GLFW_OPENGL_FORWARD_COMPAT, GLFW_TRUE);

    /* Window hints based on flags */
    glfwWindowHint(GLFW_RESIZABLE, (flags & COEX_UI_FLAG_RESIZABLE) ? GLFW_TRUE : GLFW_FALSE);
    glfwWindowHint(GLFW_DECORATED, (flags & COEX_UI_FLAG_BORDERLESS) ? GLFW_FALSE : GLFW_TRUE);
    glfwWindowHint(GLFW_TRANSPARENT_FRAMEBUFFER, (flags & COEX_UI_FLAG_TRANSPARENT) ? GLFW_TRUE : GLFW_FALSE);
    glfwWindowHint(GLFW_FLOATING, (flags & COEX_UI_FLAG_ALWAYS_ON_TOP) ? GLFW_TRUE : GLFW_FALSE);
    glfwWindowHint(GLFW_SCALE_TO_MONITOR, (flags & COEX_UI_FLAG_HIGHDPI) ? GLFW_TRUE : GLFW_FALSE);

    /* Create window */
    GLFWmonitor* monitor = NULL;
    if (flags & COEX_UI_FLAG_FULLSCREEN) {
        monitor = glfwGetPrimaryMonitor();
    }

    _ui_state.window = glfwCreateWindow((int)width, (int)height, title, monitor, NULL);
    if (!_ui_state.window) {
        fprintf(stderr, "coex_ui_shell_init: Failed to create GLFW window\n");
        glfwTerminate();
        return 0;
    }

    /* Make context current */
    glfwMakeContextCurrent(_ui_state.window);
    glfwSwapInterval(1);  /* Enable vsync */

    /* Set callbacks */
    glfwSetWindowCloseCallback(_ui_state.window, glfw_window_close_callback);
    glfwSetFramebufferSizeCallback(_ui_state.window, glfw_framebuffer_size_callback);
    glfwSetWindowSizeCallback(_ui_state.window, glfw_window_size_callback);
    glfwSetWindowFocusCallback(_ui_state.window, glfw_window_focus_callback);
    glfwSetCursorPosCallback(_ui_state.window, glfw_cursor_pos_callback);
    glfwSetMouseButtonCallback(_ui_state.window, glfw_mouse_button_callback);
    glfwSetScrollCallback(_ui_state.window, glfw_scroll_callback);
    glfwSetKeyCallback(_ui_state.window, glfw_key_callback);
    glfwSetCharCallback(_ui_state.window, glfw_char_callback);
    glfwSetWindowContentScaleCallback(_ui_state.window, glfw_content_scale_callback);

    /* Get initial sizes */
    int w, h;
    glfwGetWindowSize(_ui_state.window, &w, &h);
    _ui_state.window_width = w;
    _ui_state.window_height = h;

    glfwGetFramebufferSize(_ui_state.window, &w, &h);
    _ui_state.framebuffer_width = w;
    _ui_state.framebuffer_height = h;

    float xscale, yscale;
    glfwGetWindowContentScale(_ui_state.window, &xscale, &yscale);
    _ui_state.content_scale_x = xscale;
    _ui_state.content_scale_y = yscale;

    /* Initialize timing */
    _ui_state.start_time = glfwGetTime();

    _ui_state.initialized = 1;
    return 1;
#else
    (void)title; (void)width; (void)height; (void)flags;
    fprintf(stderr, "coex_ui_shell_init: Linux UI requires GLFW (compile with COEX_UI_HAS_GLFW)\n");
    return 0;
#endif
}

void coex_ui_shell_shutdown(void) {
#ifdef COEX_UI_HAS_GLFW
    if (!_ui_state.initialized) return;

    if (_ui_state.clipboard_text) {
        free(_ui_state.clipboard_text);
    }

    if (_ui_state.window) {
        glfwDestroyWindow(_ui_state.window);
        _ui_state.window = NULL;
    }

    glfwTerminate();
    pthread_mutex_destroy(&_ui_state.event_mutex);
    _ui_state.initialized = 0;
#endif
}

void coex_ui_shell_begin_frame(void) {
#ifdef COEX_UI_HAS_GLFW
    /* Nothing special needed - OpenGL context is always current */
#endif
}

void coex_ui_shell_end_frame(void) {
#ifdef COEX_UI_HAS_GLFW
    if (!_ui_state.initialized || !_ui_state.window) return;
    glfwSwapBuffers(_ui_state.window);
#endif
}

int64_t coex_ui_shell_should_close(void) {
#ifdef COEX_UI_HAS_GLFW
    if (!_ui_state.initialized || !_ui_state.window) return 1;
    return glfwWindowShouldClose(_ui_state.window) || _ui_state.should_close;
#else
    return 1;
#endif
}

int64_t coex_ui_shell_poll_event(CoexUIEvent* event) {
    if (!event) return 0;

    pthread_mutex_lock(&_ui_state.event_mutex);
    if (_ui_state.event_read_idx != _ui_state.event_write_idx) {
        *event = _ui_state.event_queue[_ui_state.event_read_idx];
        _ui_state.event_read_idx = (_ui_state.event_read_idx + 1) % 64;
        pthread_mutex_unlock(&_ui_state.event_mutex);
        return 1;
    }
    pthread_mutex_unlock(&_ui_state.event_mutex);

    return 0;
}

void coex_ui_shell_process_events(void) {
#ifdef COEX_UI_HAS_GLFW
    glfwPollEvents();
#endif
}

void coex_ui_shell_get_mouse_pos(double* x, double* y) {
    if (x) *x = _ui_state.mouse_x;
    if (y) *y = _ui_state.mouse_y;
}

int64_t coex_ui_shell_get_mouse_button(int64_t button) {
    if (button >= 0 && button < 3) {
        return _ui_state.mouse_buttons[button];
    }
    return 0;
}

int64_t coex_ui_shell_get_key(int64_t keycode) {
    if (keycode >= 0 && keycode < 512) {
        return _ui_state.key_states[keycode];
    }
    return 0;
}

int64_t coex_ui_shell_get_modifiers(void) {
    return _ui_state.modifiers;
}

void coex_ui_shell_get_size(int64_t* width, int64_t* height) {
    if (width) *width = _ui_state.window_width;
    if (height) *height = _ui_state.window_height;
}

void coex_ui_shell_get_framebuffer_size(int64_t* width, int64_t* height) {
    if (width) *width = _ui_state.framebuffer_width;
    if (height) *height = _ui_state.framebuffer_height;
}

void coex_ui_shell_get_content_scale(float* x_scale, float* y_scale) {
    if (x_scale) *x_scale = _ui_state.content_scale_x;
    if (y_scale) *y_scale = _ui_state.content_scale_y;
}

void coex_ui_shell_set_title(const char* title) {
#ifdef COEX_UI_HAS_GLFW
    if (_ui_state.window && title) {
        glfwSetWindowTitle(_ui_state.window, title);
    }
#else
    (void)title;
#endif
}

void coex_ui_shell_set_clipboard(const char* text) {
#ifdef COEX_UI_HAS_GLFW
    if (_ui_state.window && text) {
        glfwSetClipboardString(_ui_state.window, text);
    }
#else
    (void)text;
#endif
}

const char* coex_ui_shell_get_clipboard(void) {
#ifdef COEX_UI_HAS_GLFW
    if (!_ui_state.window) return NULL;

    if (_ui_state.clipboard_text) {
        free(_ui_state.clipboard_text);
        _ui_state.clipboard_text = NULL;
    }

    const char* text = glfwGetClipboardString(_ui_state.window);
    if (text) {
        _ui_state.clipboard_text = strdup(text);
        return _ui_state.clipboard_text;
    }
#endif
    return NULL;
}

double coex_ui_shell_get_time(void) {
#ifdef COEX_UI_HAS_GLFW
    return glfwGetTime() - _ui_state.start_time;
#else
    return 0.0;
#endif
}

void* coex_ui_shell_get_render_context(void) {
#ifdef COEX_UI_HAS_GLFW
    /* Return the GLFW window pointer - can be used to get OpenGL context */
    return _ui_state.window;
#else
    return NULL;
#endif
}

void* coex_ui_shell_get_native_window_handle(void) {
#if defined(COEX_UI_HAS_GLFW) && defined(__linux__)
    if (_ui_state.window) {
        return (void*)(uintptr_t)glfwGetX11Window(_ui_state.window);
    }
#endif
    return NULL;
}

void* coex_ui_shell_get_native_display_handle(void) {
#if defined(COEX_UI_HAS_GLFW) && defined(__linux__)
    return (void*)glfwGetX11Display();
#else
    return NULL;
#endif
}
