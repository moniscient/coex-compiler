/**
 * Coex UI Platform Shell - Linux Stub Implementation
 *
 * Placeholder for Linux/GLFW implementation.
 * Uses GLFW for windowing and OpenGL for rendering.
 *
 * TODO: Implement with GLFW when targeting Linux.
 */

#include "coex_ui_shell.h"
#include <stdio.h>

/* All functions return failure - not implemented yet */

int64_t coex_ui_shell_init(const char* title, int64_t width, int64_t height, int64_t flags) {
    (void)title; (void)width; (void)height; (void)flags;
    fprintf(stderr, "coex_ui_shell_init: Linux implementation not available\n");
    fprintf(stderr, "  To use UI on Linux, implement coex_ui_shell_linux.c with GLFW\n");
    return 0;
}

void coex_ui_shell_shutdown(void) {}

void coex_ui_shell_begin_frame(void) {}

void coex_ui_shell_end_frame(void) {}

int64_t coex_ui_shell_should_close(void) {
    return 1;  /* Always return "should close" since not implemented */
}

int64_t coex_ui_shell_poll_event(CoexUIEvent* event) {
    (void)event;
    return 0;
}

void coex_ui_shell_process_events(void) {}

void coex_ui_shell_get_mouse_pos(double* x, double* y) {
    if (x) *x = 0;
    if (y) *y = 0;
}

int64_t coex_ui_shell_get_mouse_button(int64_t button) {
    (void)button;
    return 0;
}

int64_t coex_ui_shell_get_key(int64_t keycode) {
    (void)keycode;
    return 0;
}

int64_t coex_ui_shell_get_modifiers(void) {
    return 0;
}

void coex_ui_shell_get_size(int64_t* width, int64_t* height) {
    if (width) *width = 0;
    if (height) *height = 0;
}

void coex_ui_shell_get_framebuffer_size(int64_t* width, int64_t* height) {
    if (width) *width = 0;
    if (height) *height = 0;
}

void coex_ui_shell_get_content_scale(float* x_scale, float* y_scale) {
    if (x_scale) *x_scale = 1.0f;
    if (y_scale) *y_scale = 1.0f;
}

void coex_ui_shell_set_title(const char* title) {
    (void)title;
}

void coex_ui_shell_set_clipboard(const char* text) {
    (void)text;
}

const char* coex_ui_shell_get_clipboard(void) {
    return NULL;
}

double coex_ui_shell_get_time(void) {
    return 0.0;
}

void* coex_ui_shell_get_render_context(void) {
    return NULL;
}
