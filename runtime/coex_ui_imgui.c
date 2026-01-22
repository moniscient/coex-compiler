/**
 * Coex UI ImGui Wrapper Implementation
 *
 * Wraps cimgui (C wrapper for Dear ImGui) to provide the widget API
 * used by the JSON layout interpreter.
 */

#define CIMGUI_DEFINE_ENUMS_AND_STRUCTS
#include "coex_ui_imgui.h"

/* Check if cimgui is available */
#ifdef COEX_UI_HAS_IMGUI
#include "cimgui.h"
#endif

#include <string.h>
#include <stdlib.h>
#include <stdio.h>

/* Global ImGui context */
static int _imgui_initialized = 0;

#ifdef COEX_UI_HAS_IMGUI
static ImGuiContext* _imgui_ctx = NULL;
#endif

/* ============================================================================
 * Initialization
 * ============================================================================ */

int64_t coex_imgui_init(void) {
#ifdef COEX_UI_HAS_IMGUI
    if (_imgui_initialized) return 1;

    /* Create ImGui context */
    _imgui_ctx = igCreateContext(NULL);
    if (!_imgui_ctx) {
        fprintf(stderr, "coex_imgui_init: Failed to create ImGui context\n");
        return 0;
    }

    /* Get IO for configuration */
    ImGuiIO* io = igGetIO_Nil();

    /* Configure basic settings */
    io->ConfigFlags |= ImGuiConfigFlags_NavEnableKeyboard;

    /* Tell ImGui our backend handles textures */
    io->BackendFlags |= ImGuiBackendFlags_RendererHasTextures;

    /* Request RGBA32 format for font texture (easier to work with in Metal/OpenGL) */
    io->Fonts->TexDesiredFormat = ImTextureFormat_RGBA32;

    /* Add default font so there's something to render */
    ImFontAtlas_AddFontDefault(io->Fonts, NULL);

    /* Set default style */
    igStyleColorsDark(NULL);

    _imgui_initialized = 1;
    return 1;
#else
    fprintf(stderr, "coex_imgui_init: ImGui not available (compile with COEX_UI_HAS_IMGUI)\n");
    return 0;
#endif
}

void coex_imgui_shutdown(void) {
#ifdef COEX_UI_HAS_IMGUI
    if (!_imgui_initialized) return;

    igDestroyContext(_imgui_ctx);
    _imgui_ctx = NULL;
    _imgui_initialized = 0;
#endif
}

void coex_imgui_new_frame_scaled(int64_t width, int64_t height, float scale_x, float scale_y, double delta_time) {
#ifdef COEX_UI_HAS_IMGUI
    if (!_imgui_initialized) return;

    ImGuiIO* io = igGetIO_Nil();
    io->DisplaySize.x = (float)width;
    io->DisplaySize.y = (float)height;
    io->DisplayFramebufferScale.x = scale_x;
    io->DisplayFramebufferScale.y = scale_y;
    io->DeltaTime = delta_time > 0.0 ? (float)delta_time : 1.0f / 60.0f;

    igNewFrame();
#endif
}

void coex_imgui_new_frame(int64_t width, int64_t height, double delta_time) {
    coex_imgui_new_frame_scaled(width, height, 1.0f, 1.0f, delta_time);
}

void coex_imgui_render(void) {
#ifdef COEX_UI_HAS_IMGUI
    if (!_imgui_initialized) return;
    igRender();
#endif
}

void* coex_imgui_get_draw_data(void) {
#ifdef COEX_UI_HAS_IMGUI
    if (!_imgui_initialized) return NULL;
    return igGetDrawData();
#else
    return NULL;
#endif
}

/* ============================================================================
 * Input Handling
 * ============================================================================ */

void coex_imgui_io_set_mouse_pos(double x, double y) {
#ifdef COEX_UI_HAS_IMGUI
    if (!_imgui_initialized) return;
    ImGuiIO* io = igGetIO_Nil();
    ImGuiIO_AddMousePosEvent(io, (float)x, (float)y);
#endif
}

void coex_imgui_io_set_mouse_down(int64_t button, int64_t pressed) {
#ifdef COEX_UI_HAS_IMGUI
    if (!_imgui_initialized) return;
    if (button < 0 || button >= 5) return;
    ImGuiIO* io = igGetIO_Nil();
    ImGuiIO_AddMouseButtonEvent(io, (int)button, pressed ? true : false);
#endif
}

void coex_imgui_io_set_mouse_scroll(double x, double y) {
#ifdef COEX_UI_HAS_IMGUI
    if (!_imgui_initialized) return;
    ImGuiIO* io = igGetIO_Nil();
    ImGuiIO_AddMouseWheelEvent(io, (float)x, (float)y);
#endif
}

void coex_imgui_io_set_key(int64_t keycode, int64_t pressed) {
#ifdef COEX_UI_HAS_IMGUI
    if (!_imgui_initialized) return;
    /* Modern ImGui uses ImGuiKey enum, but we accept raw keycodes */
    /* For simplicity, only handle common keys */
    ImGuiIO* io = igGetIO_Nil();
    ImGuiKey key = ImGuiKey_None;
    if (keycode >= 'A' && keycode <= 'Z') key = ImGuiKey_A + (keycode - 'A');
    else if (keycode >= 'a' && keycode <= 'z') key = ImGuiKey_A + (keycode - 'a');
    else if (keycode >= '0' && keycode <= '9') key = ImGuiKey_0 + (keycode - '0');
    else if (keycode == 256) key = ImGuiKey_Escape;
    else if (keycode == 257) key = ImGuiKey_Enter;
    else if (keycode == 258) key = ImGuiKey_Tab;
    else if (keycode == 259) key = ImGuiKey_Backspace;
    else if (keycode == 260) key = ImGuiKey_Insert;
    else if (keycode == 261) key = ImGuiKey_Delete;
    else if (keycode == 262) key = ImGuiKey_RightArrow;
    else if (keycode == 263) key = ImGuiKey_LeftArrow;
    else if (keycode == 264) key = ImGuiKey_DownArrow;
    else if (keycode == 265) key = ImGuiKey_UpArrow;
    else if (keycode == 266) key = ImGuiKey_PageUp;
    else if (keycode == 267) key = ImGuiKey_PageDown;
    else if (keycode == 268) key = ImGuiKey_Home;
    else if (keycode == 269) key = ImGuiKey_End;
    if (key != ImGuiKey_None) {
        ImGuiIO_AddKeyEvent(io, key, pressed ? true : false);
    }
#endif
}

void coex_imgui_io_add_char(uint32_t codepoint) {
#ifdef COEX_UI_HAS_IMGUI
    if (!_imgui_initialized) return;
    ImGuiIO_AddInputCharacter(igGetIO_Nil(), codepoint);
#endif
}

void coex_imgui_io_set_modifiers(int64_t ctrl, int64_t shift, int64_t alt, int64_t super) {
#ifdef COEX_UI_HAS_IMGUI
    if (!_imgui_initialized) return;
    ImGuiIO* io = igGetIO_Nil();
    ImGuiIO_AddKeyEvent(io, ImGuiMod_Ctrl, ctrl ? true : false);
    ImGuiIO_AddKeyEvent(io, ImGuiMod_Shift, shift ? true : false);
    ImGuiIO_AddKeyEvent(io, ImGuiMod_Alt, alt ? true : false);
    ImGuiIO_AddKeyEvent(io, ImGuiMod_Super, super ? true : false);
#endif
}

int64_t coex_imgui_wants_keyboard(void) {
#ifdef COEX_UI_HAS_IMGUI
    if (!_imgui_initialized) return 0;
    return igGetIO_Nil()->WantCaptureKeyboard ? 1 : 0;
#else
    return 0;
#endif
}

int64_t coex_imgui_wants_mouse(void) {
#ifdef COEX_UI_HAS_IMGUI
    if (!_imgui_initialized) return 0;
    return igGetIO_Nil()->WantCaptureMouse ? 1 : 0;
#else
    return 0;
#endif
}

/* ============================================================================
 * Container Widgets
 * ============================================================================ */

int64_t coex_imgui_begin_window(const char* label, int64_t flags) {
#ifdef COEX_UI_HAS_IMGUI
    if (!_imgui_initialized) return 0;

    ImGuiWindowFlags imgui_flags = 0;
    if (flags & COEX_IMGUI_WINDOW_NO_TITLE_BAR) imgui_flags |= ImGuiWindowFlags_NoTitleBar;
    if (flags & COEX_IMGUI_WINDOW_NO_RESIZE) imgui_flags |= ImGuiWindowFlags_NoResize;
    if (flags & COEX_IMGUI_WINDOW_NO_MOVE) imgui_flags |= ImGuiWindowFlags_NoMove;
    if (flags & COEX_IMGUI_WINDOW_NO_SCROLLBAR) imgui_flags |= ImGuiWindowFlags_NoScrollbar;
    if (flags & COEX_IMGUI_WINDOW_NO_BACKGROUND) imgui_flags |= ImGuiWindowFlags_NoBackground;
    if (flags & COEX_IMGUI_WINDOW_ALWAYS_AUTO_RESIZE) imgui_flags |= ImGuiWindowFlags_AlwaysAutoResize;

    return igBegin(label, NULL, imgui_flags) ? 1 : 0;
#else
    return 0;
#endif
}

void coex_imgui_end_window(void) {
#ifdef COEX_UI_HAS_IMGUI
    if (!_imgui_initialized) return;
    igEnd();
#endif
}

void coex_imgui_begin_horizontal(void) {
#ifdef COEX_UI_HAS_IMGUI
    /* ImGui doesn't have explicit horizontal groups, use columns */
    /* For now, do nothing - handled via same_line */
#endif
}

void coex_imgui_end_horizontal(void) {
#ifdef COEX_UI_HAS_IMGUI
    /* End horizontal group */
#endif
}

void coex_imgui_spacing(void) {
#ifdef COEX_UI_HAS_IMGUI
    if (!_imgui_initialized) return;
    igSpacing();
#endif
}

void coex_imgui_same_line(void) {
#ifdef COEX_UI_HAS_IMGUI
    if (!_imgui_initialized) return;
    igSameLine(0, -1);
#endif
}

void coex_imgui_separator(void) {
#ifdef COEX_UI_HAS_IMGUI
    if (!_imgui_initialized) return;
    igSeparator();
#endif
}

void coex_imgui_push_item_width(double width) {
#ifdef COEX_UI_HAS_IMGUI
    if (!_imgui_initialized) return;
    igPushItemWidth((float)width);
#endif
}

void coex_imgui_pop_item_width(void) {
#ifdef COEX_UI_HAS_IMGUI
    if (!_imgui_initialized) return;
    igPopItemWidth();
#endif
}

/* ============================================================================
 * Basic Widgets
 * ============================================================================ */

void coex_imgui_text(const char* text) {
#ifdef COEX_UI_HAS_IMGUI
    if (!_imgui_initialized || !text) return;
    igTextUnformatted(text, NULL);
#endif
}

void coex_imgui_text_colored(const char* text, float r, float g, float b, float a) {
#ifdef COEX_UI_HAS_IMGUI
    if (!_imgui_initialized || !text) return;
    ImVec4 color = {r, g, b, a};
    igTextColored(color, "%s", text);
#endif
}

void coex_imgui_text_wrapped(const char* text) {
#ifdef COEX_UI_HAS_IMGUI
    if (!_imgui_initialized || !text) return;
    igTextWrapped("%s", text);
#endif
}

int64_t coex_imgui_button(const char* label) {
#ifdef COEX_UI_HAS_IMGUI
    if (!_imgui_initialized || !label) return 0;
    ImVec2 size = {0, 0};
    return igButton(label, size) ? COEX_IMGUI_RESULT_CLICKED : 0;
#else
    return 0;
#endif
}

int64_t coex_imgui_button_sized(const char* label, double width, double height) {
#ifdef COEX_UI_HAS_IMGUI
    if (!_imgui_initialized || !label) return 0;
    ImVec2 size = {(float)width, (float)height};
    return igButton(label, size) ? COEX_IMGUI_RESULT_CLICKED : 0;
#else
    return 0;
#endif
}

int64_t coex_imgui_small_button(const char* label) {
#ifdef COEX_UI_HAS_IMGUI
    if (!_imgui_initialized || !label) return 0;
    return igSmallButton(label) ? COEX_IMGUI_RESULT_CLICKED : 0;
#else
    return 0;
#endif
}

int64_t coex_imgui_checkbox(const char* label, int* value) {
#ifdef COEX_UI_HAS_IMGUI
    if (!_imgui_initialized || !label || !value) return 0;
    bool bool_val = *value != 0;
    bool changed = igCheckbox(label, &bool_val);
    *value = bool_val ? 1 : 0;
    return changed ? COEX_IMGUI_RESULT_CHANGED : 0;
#else
    return 0;
#endif
}

int64_t coex_imgui_radio_button(const char* label, int active) {
#ifdef COEX_UI_HAS_IMGUI
    if (!_imgui_initialized || !label) return 0;
    return igRadioButton_Bool(label, active != 0) ? COEX_IMGUI_RESULT_CLICKED : 0;
#else
    return 0;
#endif
}

/* ============================================================================
 * Input Widgets
 * ============================================================================ */

int64_t coex_imgui_input_text(const char* label, char* buf, int64_t buf_size, int64_t flags) {
#ifdef COEX_UI_HAS_IMGUI
    if (!_imgui_initialized || !label || !buf) return 0;

    ImGuiInputTextFlags imgui_flags = 0;
    if (flags & COEX_IMGUI_INPUT_TEXT_READONLY) imgui_flags |= ImGuiInputTextFlags_ReadOnly;
    if (flags & COEX_IMGUI_INPUT_TEXT_PASSWORD) imgui_flags |= ImGuiInputTextFlags_Password;
    if (flags & COEX_IMGUI_INPUT_TEXT_ENTER_RETURNS_TRUE) imgui_flags |= ImGuiInputTextFlags_EnterReturnsTrue;

    return igInputText(label, buf, (size_t)buf_size, imgui_flags, NULL, NULL) ? COEX_IMGUI_RESULT_CHANGED : 0;
#else
    return 0;
#endif
}

int64_t coex_imgui_input_text_multiline(const char* label, char* buf, int64_t buf_size,
                                         double width, double height, int64_t flags) {
#ifdef COEX_UI_HAS_IMGUI
    if (!_imgui_initialized || !label || !buf) return 0;

    ImGuiInputTextFlags imgui_flags = 0;
    if (flags & COEX_IMGUI_INPUT_TEXT_READONLY) imgui_flags |= ImGuiInputTextFlags_ReadOnly;

    ImVec2 size = {(float)width, (float)height};
    return igInputTextMultiline(label, buf, (size_t)buf_size, size, imgui_flags, NULL, NULL) ? COEX_IMGUI_RESULT_CHANGED : 0;
#else
    return 0;
#endif
}

int64_t coex_imgui_input_int(const char* label, int64_t* value) {
#ifdef COEX_UI_HAS_IMGUI
    if (!_imgui_initialized || !label || !value) return 0;
    int int_val = (int)*value;
    bool changed = igInputInt(label, &int_val, 1, 100, 0);
    *value = int_val;
    return changed ? COEX_IMGUI_RESULT_CHANGED : 0;
#else
    return 0;
#endif
}

int64_t coex_imgui_input_float(const char* label, double* value) {
#ifdef COEX_UI_HAS_IMGUI
    if (!_imgui_initialized || !label || !value) return 0;
    float float_val = (float)*value;
    bool changed = igInputFloat(label, &float_val, 0.0f, 0.0f, "%.3f", 0);
    *value = float_val;
    return changed ? COEX_IMGUI_RESULT_CHANGED : 0;
#else
    return 0;
#endif
}

/* ============================================================================
 * Sliders
 * ============================================================================ */

int64_t coex_imgui_slider_float(const char* label, double* value, double min, double max) {
#ifdef COEX_UI_HAS_IMGUI
    if (!_imgui_initialized || !label || !value) return 0;
    float float_val = (float)*value;
    bool changed = igSliderFloat(label, &float_val, (float)min, (float)max, "%.3f", 0);
    *value = float_val;
    return changed ? COEX_IMGUI_RESULT_CHANGED : 0;
#else
    return 0;
#endif
}

int64_t coex_imgui_slider_int(const char* label, int64_t* value, int64_t min, int64_t max) {
#ifdef COEX_UI_HAS_IMGUI
    if (!_imgui_initialized || !label || !value) return 0;
    int int_val = (int)*value;
    bool changed = igSliderInt(label, &int_val, (int)min, (int)max, "%d", 0);
    *value = int_val;
    return changed ? COEX_IMGUI_RESULT_CHANGED : 0;
#else
    return 0;
#endif
}

int64_t coex_imgui_vslider_float(const char* label, double width, double height,
                                  double* value, double min, double max) {
#ifdef COEX_UI_HAS_IMGUI
    if (!_imgui_initialized || !label || !value) return 0;
    float float_val = (float)*value;
    ImVec2 size = {(float)width, (float)height};
    bool changed = igVSliderFloat(label, size, &float_val, (float)min, (float)max, "%.3f", 0);
    *value = float_val;
    return changed ? COEX_IMGUI_RESULT_CHANGED : 0;
#else
    return 0;
#endif
}

/* ============================================================================
 * Selection Widgets
 * ============================================================================ */

int64_t coex_imgui_combo(const char* label, int64_t* current_item,
                          const char* const* items, int64_t items_count) {
#ifdef COEX_UI_HAS_IMGUI
    if (!_imgui_initialized || !label || !current_item || !items) return 0;
    int int_item = (int)*current_item;
    bool changed = igCombo_Str_arr(label, &int_item, items, (int)items_count, -1);
    *current_item = int_item;
    return changed ? COEX_IMGUI_RESULT_CHANGED : 0;
#else
    return 0;
#endif
}

int64_t coex_imgui_begin_combo(const char* label, const char* preview) {
#ifdef COEX_UI_HAS_IMGUI
    if (!_imgui_initialized || !label) return 0;
    return igBeginCombo(label, preview, 0) ? 1 : 0;
#else
    return 0;
#endif
}

void coex_imgui_end_combo(void) {
#ifdef COEX_UI_HAS_IMGUI
    if (!_imgui_initialized) return;
    igEndCombo();
#endif
}

int64_t coex_imgui_selectable(const char* label, int selected) {
#ifdef COEX_UI_HAS_IMGUI
    if (!_imgui_initialized || !label) return 0;
    ImVec2 size = {0, 0};
    return igSelectable_Bool(label, selected != 0, 0, size) ? COEX_IMGUI_RESULT_CLICKED : 0;
#else
    return 0;
#endif
}

/* ============================================================================
 * Color Widgets
 * ============================================================================ */

int64_t coex_imgui_color_edit3(const char* label, float* color) {
#ifdef COEX_UI_HAS_IMGUI
    if (!_imgui_initialized || !label || !color) return 0;
    return igColorEdit3(label, color, 0) ? COEX_IMGUI_RESULT_CHANGED : 0;
#else
    return 0;
#endif
}

int64_t coex_imgui_color_edit4(const char* label, float* color) {
#ifdef COEX_UI_HAS_IMGUI
    if (!_imgui_initialized || !label || !color) return 0;
    return igColorEdit4(label, color, 0) ? COEX_IMGUI_RESULT_CHANGED : 0;
#else
    return 0;
#endif
}

/* ============================================================================
 * Progress Widgets
 * ============================================================================ */

void coex_imgui_progress_bar(double fraction, double width, double height, const char* overlay) {
#ifdef COEX_UI_HAS_IMGUI
    if (!_imgui_initialized) return;
    ImVec2 size = {(float)width, (float)height};
    igProgressBar((float)fraction, size, overlay);
#endif
}

/* ============================================================================
 * Tree/Collapsing Widgets
 * ============================================================================ */

int64_t coex_imgui_collapsing_header(const char* label) {
#ifdef COEX_UI_HAS_IMGUI
    if (!_imgui_initialized || !label) return 0;
    return igCollapsingHeader_TreeNodeFlags(label, 0) ? 1 : 0;
#else
    return 0;
#endif
}

int64_t coex_imgui_tree_node(const char* label) {
#ifdef COEX_UI_HAS_IMGUI
    if (!_imgui_initialized || !label) return 0;
    return igTreeNode_Str(label) ? 1 : 0;
#else
    return 0;
#endif
}

void coex_imgui_tree_pop(void) {
#ifdef COEX_UI_HAS_IMGUI
    if (!_imgui_initialized) return;
    igTreePop();
#endif
}

/* ============================================================================
 * ID Management
 * ============================================================================ */

void coex_imgui_push_id_str(const char* str_id) {
#ifdef COEX_UI_HAS_IMGUI
    if (!_imgui_initialized || !str_id) return;
    igPushID_Str(str_id);
#endif
}

void coex_imgui_push_id_int(int64_t int_id) {
#ifdef COEX_UI_HAS_IMGUI
    if (!_imgui_initialized) return;
    igPushID_Int((int)int_id);
#endif
}

void coex_imgui_pop_id(void) {
#ifdef COEX_UI_HAS_IMGUI
    if (!_imgui_initialized) return;
    igPopID();
#endif
}

/* ============================================================================
 * Style
 * ============================================================================ */

void coex_imgui_style_colors_dark(void) {
#ifdef COEX_UI_HAS_IMGUI
    if (!_imgui_initialized) return;
    igStyleColorsDark(NULL);
#endif
}

void coex_imgui_style_colors_light(void) {
#ifdef COEX_UI_HAS_IMGUI
    if (!_imgui_initialized) return;
    igStyleColorsLight(NULL);
#endif
}

void coex_imgui_push_style_color(int64_t idx, float r, float g, float b, float a) {
#ifdef COEX_UI_HAS_IMGUI
    if (!_imgui_initialized) return;
    ImVec4 color = {r, g, b, a};
    igPushStyleColor_Vec4((ImGuiCol)idx, color);
#endif
}

void coex_imgui_pop_style_color(int64_t count) {
#ifdef COEX_UI_HAS_IMGUI
    if (!_imgui_initialized) return;
    igPopStyleColor((int)count);
#endif
}

void coex_imgui_push_style_var_float(int64_t idx, double val) {
#ifdef COEX_UI_HAS_IMGUI
    if (!_imgui_initialized) return;
    igPushStyleVar_Float((ImGuiStyleVar)idx, (float)val);
#endif
}

void coex_imgui_push_style_var_vec2(int64_t idx, double x, double y) {
#ifdef COEX_UI_HAS_IMGUI
    if (!_imgui_initialized) return;
    ImVec2 val = {(float)x, (float)y};
    igPushStyleVar_Vec2((ImGuiStyleVar)idx, val);
#endif
}

void coex_imgui_pop_style_var(int64_t count) {
#ifdef COEX_UI_HAS_IMGUI
    if (!_imgui_initialized) return;
    igPopStyleVar((int)count);
#endif
}

/* ============================================================================
 * Font Atlas
 * ============================================================================ */

int64_t coex_imgui_get_font_tex_data_rgba32(
    unsigned char** out_pixels,
    int* out_width,
    int* out_height,
    int* out_bytes_per_pixel
) {
#ifdef COEX_UI_HAS_IMGUI
    if (!_imgui_initialized) return 0;
    if (!out_pixels || !out_width || !out_height) return 0;

    ImGuiIO* io = igGetIO_Nil();
    if (!io->Fonts) return 0;

    /* Modern cimgui uses TexData structure */
    ImTextureData* texData = io->Fonts->TexData;
    if (!texData) {
        fprintf(stderr, "coex_imgui_get_font_tex_data_rgba32: TexData is NULL\n");
        return 0;
    }

    fprintf(stderr, "DEBUG: TexData=%p, Width=%d, Height=%d, BytesPerPixel=%d, Format=%d, Pixels=%p\n",
            (void*)texData, texData->Width, texData->Height, texData->BytesPerPixel,
            (int)texData->Format, (void*)texData->Pixels);
    fprintf(stderr, "DEBUG: TexDesiredFormat=%d (RGBA32=%d, Alpha8=%d)\n",
            (int)io->Fonts->TexDesiredFormat, (int)ImTextureFormat_RGBA32, (int)ImTextureFormat_Alpha8);

    /* Dump first 32 bytes of pixel data to see what it looks like */
    if (texData->Pixels) {
        fprintf(stderr, "DEBUG: First 32 bytes of pixel data:\n");
        for (int i = 0; i < 32; i++) {
            fprintf(stderr, "%02x ", texData->Pixels[i]);
            if ((i + 1) % 16 == 0) fprintf(stderr, "\n");
        }
        /* Find first non-zero pixel */
        int firstNonZero = -1;
        for (int i = 0; i < texData->Width * texData->Height * texData->BytesPerPixel; i++) {
            if (texData->Pixels[i] != 0) {
                firstNonZero = i;
                break;
            }
        }
        fprintf(stderr, "DEBUG: First non-zero byte at offset %d\n", firstNonZero);
    }

    if (!texData->Pixels) {
        fprintf(stderr, "coex_imgui_get_font_tex_data_rgba32: Pixels is NULL\n");
        return 0;
    }

    /* Get pixel data - use direct access since GetPixels might return NULL */
    *out_pixels = texData->Pixels;
    *out_width = texData->Width;
    *out_height = texData->Height;
    if (out_bytes_per_pixel) *out_bytes_per_pixel = texData->BytesPerPixel;

    if (!*out_pixels) {
        fprintf(stderr, "coex_imgui_get_font_tex_data_rgba32: No pixel data available\n");
        return 0;
    }

    return 1;
#else
    (void)out_pixels;
    (void)out_width;
    (void)out_height;
    (void)out_bytes_per_pixel;
    return 0;
#endif
}

void coex_imgui_set_font_tex_id(void* texture_id) {
#ifdef COEX_UI_HAS_IMGUI
    if (!_imgui_initialized) return;

    ImGuiIO* io = igGetIO_Nil();
    if (io->Fonts && io->Fonts->TexData) {
        ImTextureData_SetTexID(io->Fonts->TexData, (ImTextureID)texture_id);
        /* Mark texture as ready */
        ImTextureData_SetStatus(io->Fonts->TexData, ImTextureStatus_OK);
    }
#else
    (void)texture_id;
#endif
}
