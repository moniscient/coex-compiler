/**
 * Coex UI Library - JSON Layout Interpreter
 *
 * Interprets JSON layout descriptions and renders widgets using ImGui.
 * Returns state changes and events as JSON.
 */

#include "coex_ui.h"
#include "coex_ui_shell.h"
#include "coex_ui_imgui.h"
#include "svg/coex_svg.h"
#include "svg/coex_svg_texture.h"

/* Platform-specific renderers */
#ifdef __APPLE__
#include "coex_ui_metal.h"
#else
/* OpenGL renderer for Linux */
#include "coex_ui_opengl.h"
#ifdef COEX_UI_HAS_OPENGL
#define GL_GLEXT_PROTOTYPES
#include <GL/gl.h>
#endif
#endif

/* cJSON for JSON parsing - can be included directly */
#ifdef COEX_UI_HAS_CJSON
#include "cJSON.h"
#else
/* Embedded minimal JSON parser for when cJSON is not available */
#include <stdlib.h>
#include <string.h>
#include <stdio.h>
#include <ctype.h>

/* Minimal JSON types */
typedef struct cJSON {
    struct cJSON *next, *prev;
    struct cJSON *child;
    int type;
    char *valuestring;
    double valuedouble;
    int valueint;
    char *string;
} cJSON;

#define cJSON_Invalid 0
#define cJSON_False  (1 << 0)
#define cJSON_True   (1 << 1)
#define cJSON_NULL   (1 << 2)
#define cJSON_Number (1 << 3)
#define cJSON_String (1 << 4)
#define cJSON_Array  (1 << 5)
#define cJSON_Object (1 << 6)

/* Forward declarations for minimal JSON implementation */
static cJSON* cJSON_Parse(const char* value);
static void cJSON_Delete(cJSON* item);
static char* cJSON_Print(const cJSON* item);
static cJSON* cJSON_CreateObject(void);
static cJSON* cJSON_CreateArray(void);
static cJSON* cJSON_CreateString(const char* string);
static cJSON* cJSON_CreateNumber(double num);
static cJSON* cJSON_CreateBool(int boolean);
static void cJSON_AddItemToObject(cJSON* object, const char* string, cJSON* item);
static void cJSON_AddItemToArray(cJSON* array, cJSON* item);
static cJSON* cJSON_GetObjectItem(const cJSON* object, const char* string);
static cJSON* cJSON_GetArrayItem(const cJSON* array, int index);
static int cJSON_GetArraySize(const cJSON* array);
static int cJSON_IsTrue(const cJSON* item);
static int cJSON_IsFalse(const cJSON* item);
static int cJSON_IsNumber(const cJSON* item);
static int cJSON_IsString(const cJSON* item);
static int cJSON_IsArray(const cJSON* item);
static int cJSON_IsObject(const cJSON* item);
static double cJSON_GetNumberValue(const cJSON* item);
static char* cJSON_GetStringValue(const cJSON* item);

/* Minimal JSON implementation */
static cJSON* cJSON_New_Item(void) {
    cJSON* node = (cJSON*)calloc(1, sizeof(cJSON));
    return node;
}

static const char* skip_whitespace(const char* in) {
    while (in && *in && (unsigned char)*in <= 32) in++;
    return in;
}

static const char* parse_value(cJSON* item, const char* value);

static const char* parse_string(cJSON* item, const char* str) {
    const char* ptr = str + 1;
    char* out;
    int len = 0;

    while (*ptr != '"' && *ptr) {
        if (*ptr++ == '\\') ptr++;
        len++;
    }

    out = (char*)malloc(len + 1);
    if (!out) return NULL;

    ptr = str + 1;
    char* ptr2 = out;
    while (*ptr != '"' && *ptr) {
        if (*ptr != '\\') {
            *ptr2++ = *ptr++;
        } else {
            ptr++;
            switch (*ptr) {
                case 'n': *ptr2++ = '\n'; break;
                case 't': *ptr2++ = '\t'; break;
                case 'r': *ptr2++ = '\r'; break;
                case '"': *ptr2++ = '"'; break;
                case '\\': *ptr2++ = '\\'; break;
                default: *ptr2++ = *ptr; break;
            }
            ptr++;
        }
    }
    *ptr2 = 0;

    item->type = cJSON_String;
    item->valuestring = out;
    return ptr + 1;
}

static const char* parse_number(cJSON* item, const char* num) {
    double n = 0;
    int sign = 1;

    if (*num == '-') { sign = -1; num++; }
    while (*num >= '0' && *num <= '9') n = (n * 10) + (*num++ - '0');
    if (*num == '.') {
        num++;
        double scale = 0.1;
        while (*num >= '0' && *num <= '9') {
            n += (*num++ - '0') * scale;
            scale *= 0.1;
        }
    }
    if (*num == 'e' || *num == 'E') {
        num++;
        int esign = 1;
        int e = 0;
        if (*num == '-') { esign = -1; num++; }
        else if (*num == '+') num++;
        while (*num >= '0' && *num <= '9') e = (e * 10) + (*num++ - '0');
        double scale = 1.0;
        for (int i = 0; i < e; i++) scale *= 10.0;
        n = esign > 0 ? n * scale : n / scale;
    }

    item->type = cJSON_Number;
    item->valuedouble = sign * n;
    item->valueint = (int)(sign * n);
    return num;
}

static const char* parse_array(cJSON* item, const char* value) {
    cJSON* child;
    item->type = cJSON_Array;
    value = skip_whitespace(value + 1);
    if (*value == ']') return value + 1;

    item->child = child = cJSON_New_Item();
    if (!item->child) return NULL;
    value = skip_whitespace(parse_value(child, skip_whitespace(value)));
    if (!value) return NULL;

    while (*value == ',') {
        cJSON* new_item = cJSON_New_Item();
        if (!new_item) return NULL;
        child->next = new_item;
        new_item->prev = child;
        child = new_item;
        value = skip_whitespace(parse_value(child, skip_whitespace(value + 1)));
        if (!value) return NULL;
    }

    if (*value == ']') return value + 1;
    return NULL;
}

static const char* parse_object(cJSON* item, const char* value) {
    cJSON* child;
    item->type = cJSON_Object;
    value = skip_whitespace(value + 1);
    if (*value == '}') return value + 1;

    item->child = child = cJSON_New_Item();
    if (!item->child) return NULL;
    value = skip_whitespace(parse_string(child, skip_whitespace(value)));
    if (!value) return NULL;
    child->string = child->valuestring;
    child->valuestring = NULL;
    if (*value != ':') return NULL;
    value = skip_whitespace(parse_value(child, skip_whitespace(value + 1)));
    if (!value) return NULL;

    while (*value == ',') {
        cJSON* new_item = cJSON_New_Item();
        if (!new_item) return NULL;
        child->next = new_item;
        new_item->prev = child;
        child = new_item;
        value = skip_whitespace(parse_string(child, skip_whitespace(value + 1)));
        if (!value) return NULL;
        child->string = child->valuestring;
        child->valuestring = NULL;
        if (*value != ':') return NULL;
        value = skip_whitespace(parse_value(child, skip_whitespace(value + 1)));
        if (!value) return NULL;
    }

    if (*value == '}') return value + 1;
    return NULL;
}

static const char* parse_value(cJSON* item, const char* value) {
    if (!value) return NULL;
    if (!strncmp(value, "null", 4)) { item->type = cJSON_NULL; return value + 4; }
    if (!strncmp(value, "false", 5)) { item->type = cJSON_False; return value + 5; }
    if (!strncmp(value, "true", 4)) { item->type = cJSON_True; return value + 4; }
    if (*value == '"') return parse_string(item, value);
    if (*value == '-' || (*value >= '0' && *value <= '9')) return parse_number(item, value);
    if (*value == '[') return parse_array(item, value);
    if (*value == '{') return parse_object(item, value);
    return NULL;
}

static cJSON* cJSON_Parse(const char* value) {
    cJSON* c = cJSON_New_Item();
    if (!c) return NULL;
    if (!parse_value(c, skip_whitespace(value))) {
        cJSON_Delete(c);
        return NULL;
    }
    return c;
}

static void cJSON_Delete(cJSON* item) {
    cJSON* next;
    while (item) {
        next = item->next;
        if (item->child) cJSON_Delete(item->child);
        if (item->valuestring) free(item->valuestring);
        if (item->string) free(item->string);
        free(item);
        item = next;
    }
}

/* Simple JSON printer */
static void print_value(cJSON* item, char** buf, int* len, int* cap);

static void ensure_capacity(char** buf, int* len, int* cap, int need) {
    while (*cap < *len + need + 1) {
        *cap = *cap * 2;
        *buf = (char*)realloc(*buf, *cap);
    }
}

static void append_str(char** buf, int* len, int* cap, const char* s) {
    int slen = strlen(s);
    ensure_capacity(buf, len, cap, slen);
    memcpy(*buf + *len, s, slen);
    *len += slen;
    (*buf)[*len] = 0;
}

static void print_string(const char* s, char** buf, int* len, int* cap) {
    append_str(buf, len, cap, "\"");
    while (*s) {
        if (*s == '"' || *s == '\\') {
            ensure_capacity(buf, len, cap, 2);
            (*buf)[(*len)++] = '\\';
        }
        ensure_capacity(buf, len, cap, 1);
        (*buf)[(*len)++] = *s++;
    }
    (*buf)[*len] = 0;
    append_str(buf, len, cap, "\"");
}

static void print_number(double d, char** buf, int* len, int* cap) {
    char num[64];
    if (d == (int)d) snprintf(num, sizeof(num), "%d", (int)d);
    else snprintf(num, sizeof(num), "%g", d);
    append_str(buf, len, cap, num);
}

static void print_value(cJSON* item, char** buf, int* len, int* cap) {
    if (!item) { append_str(buf, len, cap, "null"); return; }

    switch (item->type) {
        case cJSON_NULL: append_str(buf, len, cap, "null"); break;
        case cJSON_False: append_str(buf, len, cap, "false"); break;
        case cJSON_True: append_str(buf, len, cap, "true"); break;
        case cJSON_Number: print_number(item->valuedouble, buf, len, cap); break;
        case cJSON_String: print_string(item->valuestring, buf, len, cap); break;
        case cJSON_Array: {
            append_str(buf, len, cap, "[");
            cJSON* child = item->child;
            while (child) {
                print_value(child, buf, len, cap);
                child = child->next;
                if (child) append_str(buf, len, cap, ",");
            }
            append_str(buf, len, cap, "]");
            break;
        }
        case cJSON_Object: {
            append_str(buf, len, cap, "{");
            cJSON* child = item->child;
            while (child) {
                print_string(child->string, buf, len, cap);
                append_str(buf, len, cap, ":");
                print_value(child, buf, len, cap);
                child = child->next;
                if (child) append_str(buf, len, cap, ",");
            }
            append_str(buf, len, cap, "}");
            break;
        }
    }
}

static char* cJSON_Print(const cJSON* item) {
    int len = 0, cap = 256;
    char* buf = (char*)malloc(cap);
    buf[0] = 0;
    print_value((cJSON*)item, &buf, &len, &cap);
    return buf;
}

static cJSON* cJSON_CreateObject(void) {
    cJSON* item = cJSON_New_Item();
    if (item) item->type = cJSON_Object;
    return item;
}

static cJSON* cJSON_CreateArray(void) {
    cJSON* item = cJSON_New_Item();
    if (item) item->type = cJSON_Array;
    return item;
}

static cJSON* cJSON_CreateString(const char* string) {
    cJSON* item = cJSON_New_Item();
    if (item) {
        item->type = cJSON_String;
        item->valuestring = strdup(string);
    }
    return item;
}

static cJSON* cJSON_CreateNumber(double num) {
    cJSON* item = cJSON_New_Item();
    if (item) {
        item->type = cJSON_Number;
        item->valuedouble = num;
        item->valueint = (int)num;
    }
    return item;
}

static cJSON* cJSON_CreateBool(int boolean) {
    cJSON* item = cJSON_New_Item();
    if (item) item->type = boolean ? cJSON_True : cJSON_False;
    return item;
}

static void cJSON_AddItemToObject(cJSON* object, const char* string, cJSON* item) {
    if (!object || !item) return;
    item->string = strdup(string);
    if (!object->child) {
        object->child = item;
    } else {
        cJSON* child = object->child;
        while (child->next) child = child->next;
        child->next = item;
        item->prev = child;
    }
}

static void cJSON_AddItemToArray(cJSON* array, cJSON* item) {
    if (!array || !item) return;
    if (!array->child) {
        array->child = item;
    } else {
        cJSON* child = array->child;
        while (child->next) child = child->next;
        child->next = item;
        item->prev = child;
    }
}

static cJSON* cJSON_GetObjectItem(const cJSON* object, const char* string) {
    if (!object || !string) return NULL;
    cJSON* child = object->child;
    while (child) {
        if (child->string && strcmp(child->string, string) == 0) return child;
        child = child->next;
    }
    return NULL;
}

static cJSON* cJSON_GetArrayItem(const cJSON* array, int index) {
    if (!array) return NULL;
    cJSON* child = array->child;
    while (child && index > 0) {
        child = child->next;
        index--;
    }
    return child;
}

static int cJSON_GetArraySize(const cJSON* array) {
    if (!array) return 0;
    int count = 0;
    cJSON* child = array->child;
    while (child) { count++; child = child->next; }
    return count;
}

static int cJSON_IsTrue(const cJSON* item) { return item && (item->type == cJSON_True); }
static int cJSON_IsFalse(const cJSON* item) { return item && (item->type == cJSON_False); }
static int cJSON_IsNumber(const cJSON* item) { return item && (item->type == cJSON_Number); }
static int cJSON_IsString(const cJSON* item) { return item && (item->type == cJSON_String); }
static int cJSON_IsArray(const cJSON* item) { return item && (item->type == cJSON_Array); }
static int cJSON_IsObject(const cJSON* item) { return item && (item->type == cJSON_Object); }
static double cJSON_GetNumberValue(const cJSON* item) { return item ? item->valuedouble : 0; }
static char* cJSON_GetStringValue(const cJSON* item) { return item ? item->valuestring : NULL; }

#endif /* COEX_UI_HAS_CJSON */

#include <stdlib.h>
#include <string.h>
#include <stdio.h>

/* ============================================================================
 * Global State
 * ============================================================================ */

static struct {
    int initialized;
    int font_texture_created;  /* Deferred font texture creation flag */
    double last_frame_time;
    cJSON* pending_events;

    /* Text input buffers (widget_id -> buffer) */
    struct {
        char* id;
        char* buffer;
        int buffer_size;
        int initialized;  /* Set to 1 after first initialization from state */
    } text_buffers[64];
    int text_buffer_count;
} _ui_state;

/* ============================================================================
 * Helper Functions
 * ============================================================================ */

static const char* get_string(cJSON* obj, const char* key, const char* def) {
    cJSON* item = cJSON_GetObjectItem(obj, key);
    if (cJSON_IsString(item)) return cJSON_GetStringValue(item);
    return def;
}

static double get_number(cJSON* obj, const char* key, double def) {
    cJSON* item = cJSON_GetObjectItem(obj, key);
    if (cJSON_IsNumber(item)) return cJSON_GetNumberValue(item);
    return def;
}

static int get_bool(cJSON* obj, const char* key, int def) {
    cJSON* item = cJSON_GetObjectItem(obj, key);
    if (cJSON_IsTrue(item)) return 1;
    if (cJSON_IsFalse(item)) return 0;
    return def;
}

static char* get_text_buffer(const char* id, int size, int* needs_init) {
    if (!id) return NULL;
    if (needs_init) *needs_init = 0;

    /* Look for existing buffer */
    for (int i = 0; i < _ui_state.text_buffer_count; i++) {
        if (strcmp(_ui_state.text_buffers[i].id, id) == 0) {
            /* Grow buffer if needed */
            if (_ui_state.text_buffers[i].buffer_size < size) {
                _ui_state.text_buffers[i].buffer = realloc(
                    _ui_state.text_buffers[i].buffer, size);
                _ui_state.text_buffers[i].buffer_size = size;
            }
            /* Check if needs initialization */
            if (needs_init && !_ui_state.text_buffers[i].initialized) {
                *needs_init = 1;
                _ui_state.text_buffers[i].initialized = 1;
            }
            return _ui_state.text_buffers[i].buffer;
        }
    }

    /* Create new buffer */
    if (_ui_state.text_buffer_count < 64) {
        int idx = _ui_state.text_buffer_count++;
        _ui_state.text_buffers[idx].id = strdup(id);
        _ui_state.text_buffers[idx].buffer = calloc(size, 1);
        _ui_state.text_buffers[idx].buffer_size = size;
        _ui_state.text_buffers[idx].initialized = 1;
        if (needs_init) *needs_init = 1;  /* New buffer needs initialization */
        return _ui_state.text_buffers[idx].buffer;
    }

    return NULL;
}

static void add_event(const char* type, const char* id, cJSON* value) {
    cJSON* event = cJSON_CreateObject();
    cJSON_AddItemToObject(event, "type", cJSON_CreateString(type));
    if (id) cJSON_AddItemToObject(event, "id", cJSON_CreateString(id));
    if (value) cJSON_AddItemToObject(event, "value", value);
    cJSON_AddItemToArray(_ui_state.pending_events, event);
}

/* ============================================================================
 * JSON Helper - Replace or Add Item
 * ============================================================================ */

/* Replace an existing key's value, or add if it doesn't exist.
 * This avoids duplicate keys in the JSON object. */
static void cJSON_ReplaceOrAddItemToObject(cJSON* object, const char* key, cJSON* item) {
    if (!object || !key || !item) return;

    /* Search for existing item with this key */
    cJSON* existing = object->child;
    cJSON* prev = NULL;

    while (existing) {
        if (existing->string && strcmp(existing->string, key) == 0) {
            /* Found existing key - replace the value */
            item->string = strdup(key);
            item->next = existing->next;
            item->prev = existing->prev;

            if (prev) {
                prev->next = item;
            } else {
                object->child = item;
            }

            if (existing->next) {
                existing->next->prev = item;
            }

            /* Free the old item */
            existing->next = NULL;
            existing->prev = NULL;
            cJSON_Delete(existing);
            return;
        }
        prev = existing;
        existing = existing->next;
    }

    /* Key not found - add new item */
    cJSON_AddItemToObject(object, key, item);
}

/* ============================================================================
 * Widget Rendering
 * ============================================================================ */

static void render_widget(cJSON* widget, cJSON* state, cJSON* new_state);

static void render_children(cJSON* widget, cJSON* state, cJSON* new_state) {
    cJSON* children = cJSON_GetObjectItem(widget, "children");
    if (!cJSON_IsArray(children)) return;

    int count = cJSON_GetArraySize(children);
    for (int i = 0; i < count; i++) {
        render_widget(cJSON_GetArrayItem(children, i), state, new_state);
    }
}

static void render_window(cJSON* widget, cJSON* state, cJSON* new_state) {
    const char* title = get_string(widget, "title", "Window");
    int64_t flags = 0;

    if (!get_bool(widget, "title_bar", 1)) flags |= COEX_IMGUI_WINDOW_NO_TITLE_BAR;
    if (!get_bool(widget, "resize", 1)) flags |= COEX_IMGUI_WINDOW_NO_RESIZE;
    if (!get_bool(widget, "move", 1)) flags |= COEX_IMGUI_WINDOW_NO_MOVE;
    if (get_bool(widget, "auto_resize", 0)) flags |= COEX_IMGUI_WINDOW_ALWAYS_AUTO_RESIZE;

    if (coex_imgui_begin_window(title, flags)) {
        render_children(widget, state, new_state);
    }
    coex_imgui_end_window();
}

static void render_column(cJSON* widget, cJSON* state, cJSON* new_state) {
    render_children(widget, state, new_state);
}

static void render_row(cJSON* widget, cJSON* state, cJSON* new_state) {
    cJSON* children = cJSON_GetObjectItem(widget, "children");
    if (!cJSON_IsArray(children)) return;

    int count = cJSON_GetArraySize(children);
    for (int i = 0; i < count; i++) {
        if (i > 0) coex_imgui_same_line();
        render_widget(cJSON_GetArrayItem(children, i), state, new_state);
    }
}

static void render_text(cJSON* widget, cJSON* state, cJSON* new_state) {
    (void)state; (void)new_state;

    const char* text = get_string(widget, "text", "");
    const char* bind = get_string(widget, "bind", NULL);

    /* If bound to state, use state value */
    if (bind) {
        cJSON* val = cJSON_GetObjectItem(state, bind);
        if (cJSON_IsString(val)) text = cJSON_GetStringValue(val);
        else if (cJSON_IsNumber(val)) {
            static char num_buf[64];
            snprintf(num_buf, sizeof(num_buf), "%g", cJSON_GetNumberValue(val));
            text = num_buf;
        }
    }

    /* Check for color */
    cJSON* color = cJSON_GetObjectItem(widget, "color");
    if (cJSON_IsArray(color) && cJSON_GetArraySize(color) >= 3) {
        float r = cJSON_GetNumberValue(cJSON_GetArrayItem(color, 0));
        float g = cJSON_GetNumberValue(cJSON_GetArrayItem(color, 1));
        float b = cJSON_GetNumberValue(cJSON_GetArrayItem(color, 2));
        float a = cJSON_GetArraySize(color) >= 4 ?
            cJSON_GetNumberValue(cJSON_GetArrayItem(color, 3)) : 1.0f;
        coex_imgui_text_colored(text, r, g, b, a);
    } else if (get_bool(widget, "wrapped", 0)) {
        coex_imgui_text_wrapped(text);
    } else {
        coex_imgui_text(text);
    }
}

static void render_button(cJSON* widget, cJSON* state, cJSON* new_state) {
    (void)state; (void)new_state;

    const char* label = get_string(widget, "label", "Button");
    const char* id = get_string(widget, "id", NULL);
    const char* action = get_string(widget, "action", NULL);

    double width = get_number(widget, "width", 0);
    double height = get_number(widget, "height", 0);

    int64_t clicked;
    if (width > 0 || height > 0) {
        clicked = coex_imgui_button_sized(label, width, height);
    } else {
        clicked = coex_imgui_button(label);
    }

    if (clicked) {
        add_event("click", id ? id : label, NULL);
        if (action) {
            cJSON_ReplaceOrAddItemToObject(new_state, "_pending_action", cJSON_CreateString(action));
        }
    }
}

static void render_checkbox(cJSON* widget, cJSON* state, cJSON* new_state) {
    const char* label = get_string(widget, "label", "Checkbox");
    const char* id = get_string(widget, "id", label);

    /* Get current value from state */
    cJSON* state_val = cJSON_GetObjectItem(state, id);
    int value = cJSON_IsTrue(state_val) ? 1 : 0;

    if (coex_imgui_checkbox(label, &value) & COEX_IMGUI_RESULT_CHANGED) {
        cJSON_ReplaceOrAddItemToObject(new_state, id, cJSON_CreateBool(value));
        add_event("change", id, cJSON_CreateBool(value));
    }
}

static void render_slider_float(cJSON* widget, cJSON* state, cJSON* new_state) {
    const char* label = get_string(widget, "label", "##slider");
    const char* id = get_string(widget, "id", label);
    double min = get_number(widget, "min", 0);
    double max = get_number(widget, "max", 100);

    /* Get current value from state */
    cJSON* state_val = cJSON_GetObjectItem(state, id);
    double value = cJSON_IsNumber(state_val) ? cJSON_GetNumberValue(state_val) : min;

    if (coex_imgui_slider_float(label, &value, min, max) & COEX_IMGUI_RESULT_CHANGED) {
        cJSON_ReplaceOrAddItemToObject(new_state, id, cJSON_CreateNumber(value));
        add_event("change", id, cJSON_CreateNumber(value));
    }
}

static void render_slider_int(cJSON* widget, cJSON* state, cJSON* new_state) {
    const char* label = get_string(widget, "label", "##slider");
    const char* id = get_string(widget, "id", label);
    int64_t min = (int64_t)get_number(widget, "min", 0);
    int64_t max = (int64_t)get_number(widget, "max", 100);

    /* Get current value from state */
    cJSON* state_val = cJSON_GetObjectItem(state, id);
    int64_t value = cJSON_IsNumber(state_val) ? (int64_t)cJSON_GetNumberValue(state_val) : min;

    if (coex_imgui_slider_int(label, &value, min, max) & COEX_IMGUI_RESULT_CHANGED) {
        cJSON_ReplaceOrAddItemToObject(new_state, id, cJSON_CreateNumber(value));
        add_event("change", id, cJSON_CreateNumber(value));
    }
}

static void render_input_text(cJSON* widget, cJSON* state, cJSON* new_state) {
    const char* label = get_string(widget, "label", "##input");
    const char* id = get_string(widget, "id", label);
    int buf_size = (int)get_number(widget, "max_length", 256);

    int needs_init = 0;
    char* buf = get_text_buffer(id, buf_size, &needs_init);
    if (!buf) return;

    /* Initialize from state only on first use - don't overwrite user's typing */
    if (needs_init) {
        cJSON* state_val = cJSON_GetObjectItem(state, id);
        if (cJSON_IsString(state_val)) {
            strncpy(buf, cJSON_GetStringValue(state_val), buf_size - 1);
            buf[buf_size - 1] = 0;
        }
    }

    int64_t flags = 0;
    if (get_bool(widget, "readonly", 0)) flags |= COEX_IMGUI_INPUT_TEXT_READONLY;
    if (get_bool(widget, "password", 0)) flags |= COEX_IMGUI_INPUT_TEXT_PASSWORD;

    int result = coex_imgui_input_text(label, buf, buf_size, flags);

    /* Always update state with current buffer contents (user may be mid-edit) */
    cJSON_ReplaceOrAddItemToObject(new_state, id, cJSON_CreateString(buf));

    /* Only fire change event when edit is committed */
    if (result & COEX_IMGUI_RESULT_CHANGED) {
        add_event("change", id, cJSON_CreateString(buf));
    }
}

static void render_input_int(cJSON* widget, cJSON* state, cJSON* new_state) {
    const char* label = get_string(widget, "label", "##input");
    const char* id = get_string(widget, "id", label);

    cJSON* state_val = cJSON_GetObjectItem(state, id);
    int64_t value = cJSON_IsNumber(state_val) ? (int64_t)cJSON_GetNumberValue(state_val) : 0;

    if (coex_imgui_input_int(label, &value) & COEX_IMGUI_RESULT_CHANGED) {
        cJSON_ReplaceOrAddItemToObject(new_state, id, cJSON_CreateNumber(value));
        add_event("change", id, cJSON_CreateNumber(value));
    }
}

static void render_input_float(cJSON* widget, cJSON* state, cJSON* new_state) {
    const char* label = get_string(widget, "label", "##input");
    const char* id = get_string(widget, "id", label);

    cJSON* state_val = cJSON_GetObjectItem(state, id);
    double value = cJSON_IsNumber(state_val) ? cJSON_GetNumberValue(state_val) : 0;

    if (coex_imgui_input_float(label, &value) & COEX_IMGUI_RESULT_CHANGED) {
        cJSON_ReplaceOrAddItemToObject(new_state, id, cJSON_CreateNumber(value));
        add_event("change", id, cJSON_CreateNumber(value));
    }
}

static void render_combo(cJSON* widget, cJSON* state, cJSON* new_state) {
    const char* label = get_string(widget, "label", "##combo");
    const char* id = get_string(widget, "id", label);

    cJSON* items_arr = cJSON_GetObjectItem(widget, "items");
    if (!cJSON_IsArray(items_arr)) return;

    int count = cJSON_GetArraySize(items_arr);
    if (count == 0) return;

    /* Build items array */
    const char** items = (const char**)alloca(count * sizeof(char*));
    for (int i = 0; i < count; i++) {
        cJSON* item = cJSON_GetArrayItem(items_arr, i);
        items[i] = cJSON_IsString(item) ? cJSON_GetStringValue(item) : "";
    }

    cJSON* state_val = cJSON_GetObjectItem(state, id);
    int64_t selected = cJSON_IsNumber(state_val) ? (int64_t)cJSON_GetNumberValue(state_val) : 0;

    if (coex_imgui_combo(label, &selected, items, count) & COEX_IMGUI_RESULT_CHANGED) {
        cJSON_ReplaceOrAddItemToObject(new_state, id, cJSON_CreateNumber(selected));
        add_event("change", id, cJSON_CreateNumber(selected));
    }
}

static void render_color_edit(cJSON* widget, cJSON* state, cJSON* new_state) {
    const char* label = get_string(widget, "label", "##color");
    const char* id = get_string(widget, "id", label);
    int alpha = get_bool(widget, "alpha", 0);

    float color[4] = {0, 0, 0, 1};

    /* Get from state */
    cJSON* state_val = cJSON_GetObjectItem(state, id);
    if (cJSON_IsArray(state_val)) {
        for (int i = 0; i < 4 && i < cJSON_GetArraySize(state_val); i++) {
            color[i] = cJSON_GetNumberValue(cJSON_GetArrayItem(state_val, i));
        }
    }

    int64_t changed;
    if (alpha) {
        changed = coex_imgui_color_edit4(label, color);
    } else {
        changed = coex_imgui_color_edit3(label, color);
    }

    if (changed & COEX_IMGUI_RESULT_CHANGED) {
        cJSON* arr = cJSON_CreateArray();
        cJSON_AddItemToArray(arr, cJSON_CreateNumber(color[0]));
        cJSON_AddItemToArray(arr, cJSON_CreateNumber(color[1]));
        cJSON_AddItemToArray(arr, cJSON_CreateNumber(color[2]));
        if (alpha) cJSON_AddItemToArray(arr, cJSON_CreateNumber(color[3]));
        cJSON_ReplaceOrAddItemToObject(new_state, id, arr);
        add_event("change", id, NULL);  /* Color array already in state */
    }
}

static void render_progress(cJSON* widget, cJSON* state, cJSON* new_state) {
    (void)new_state;

    const char* bind = get_string(widget, "bind", NULL);
    double fraction = get_number(widget, "fraction", 0);
    double width = get_number(widget, "width", -1);
    double height = get_number(widget, "height", -1);
    const char* overlay = get_string(widget, "overlay", NULL);

    if (bind) {
        cJSON* val = cJSON_GetObjectItem(state, bind);
        if (cJSON_IsNumber(val)) fraction = cJSON_GetNumberValue(val);
    }

    coex_imgui_progress_bar(fraction, width, height, overlay);
}

static void render_tree(cJSON* widget, cJSON* state, cJSON* new_state) {
    const char* label = get_string(widget, "label", "Tree");

    if (coex_imgui_tree_node(label)) {
        render_children(widget, state, new_state);
        coex_imgui_tree_pop();
    }
}

static void render_collapsing(cJSON* widget, cJSON* state, cJSON* new_state) {
    const char* label = get_string(widget, "label", "Section");

    if (coex_imgui_collapsing_header(label)) {
        render_children(widget, state, new_state);
    }
}

/* ImGui types for draw list rendering */
typedef struct {
    void* _TexData;      /* NULL for user textures */
    uint64_t _TexID;     /* The actual texture ID */
} ImTextureRef_c;

typedef struct {
    float x, y;
} ImVec2_c;

/* ImDrawList is opaque - we just need a pointer */
typedef void ImDrawList;

static void render_svg_image(cJSON* widget, cJSON* state, cJSON* new_state) {
    (void)state; (void)new_state;

    /* Get SVG handle - required */
    int64_t handle = (int64_t)get_number(widget, "handle", 0);
    if (handle < 1) return;

    /* Get dimensions - use SVG intrinsic size if not specified */
    double width = get_number(widget, "width", 0);
    double height = get_number(widget, "height", 0);

    if (width <= 0) width = coex_svg_width(handle);
    if (height <= 0) height = coex_svg_height(handle);
    if (width <= 0 || height <= 0) return;

    /* Render SVG to texture */
    if (!coex_svg_render_to_texture(handle, (int64_t)width, (int64_t)height)) {
        return;
    }

    /* Get the ImGui texture ID */
    void* texture_id = coex_svg_get_texture_id(handle);
    if (!texture_id) return;

    /* Get current cursor screen position for rendering */
    extern ImVec2_c igGetCursorScreenPos(void);
    ImVec2_c cursor_pos = igGetCursorScreenPos();
    float cursor_x = cursor_pos.x;
    float cursor_y = cursor_pos.y;


    /* Get the window draw list */
    extern ImDrawList* igGetWindowDrawList(void);
    ImDrawList* draw_list = igGetWindowDrawList();
    if (!draw_list) return;

    /* Create ImTextureRef for user texture */
    ImTextureRef_c tex_ref;
    tex_ref._TexData = NULL;
    tex_ref._TexID = (uint64_t)(uintptr_t)texture_id;

    ImVec2_c p_min = { cursor_x, cursor_y };
    ImVec2_c p_max = { cursor_x + (float)width, cursor_y + (float)height };
    ImVec2_c uv_min = { 0.0f, 0.0f };
    ImVec2_c uv_max = { 1.0f, 1.0f };

    /* Add image to draw list - white color (0xFFFFFFFF) */
    extern void ImDrawList_AddImage(ImDrawList* self, ImTextureRef_c tex_ref,
                                    ImVec2_c p_min, ImVec2_c p_max,
                                    ImVec2_c uv_min, ImVec2_c uv_max, uint32_t col);
    ImDrawList_AddImage(draw_list, tex_ref, p_min, p_max, uv_min, uv_max, 0xFFFFFFFF);

    /* Advance cursor with a dummy to account for the image space */
    extern void igDummy(ImVec2_c size);
    ImVec2_c dummy_size = { (float)width, (float)height };
    igDummy(dummy_size);
}

static void render_canvas(cJSON* widget, cJSON* state, cJSON* new_state) {
    /* Canvas is a container for absolutely positioned children */
    double width = get_number(widget, "width", 640);
    double height = get_number(widget, "height", 480);

    /* ImGui declarations - use ImVec2_c structs */
    extern int igBeginChild_Str(const char* str_id, ImVec2_c size, int child_flags, int window_flags);
    extern void igEndChild(void);
    extern ImVec2_c igGetCursorScreenPos(void);
    extern void igSetCursorScreenPos(ImVec2_c pos);

    /* Begin a child window for the canvas area
     * ImGuiWindowFlags_NoScrollbar = 1 << 3 = 8
     * ImGuiWindowFlags_NoScrollWithMouse = 1 << 4 = 16
     */
    ImVec2_c canvas_size = { (float)width, (float)height };
    if (igBeginChild_Str("##canvas", canvas_size, 0, 8 | 16)) {
        /* Get the screen position of the canvas origin */
        ImVec2_c canvas_origin = igGetCursorScreenPos();

        /* Render children with their offsets using screen-space positioning */
        cJSON* children = cJSON_GetObjectItem(widget, "children");
        if (cJSON_IsArray(children)) {
            int count = cJSON_GetArraySize(children);
            for (int i = 0; i < count; i++) {
                cJSON* child = cJSON_GetArrayItem(children, i);

                /* Get child's offset */
                double offsetX = get_number(child, "offsetX", 0);
                double offsetY = get_number(child, "offsetY", 0);

                /* Position cursor at absolute screen position */
                ImVec2_c pos = { canvas_origin.x + (float)offsetX, canvas_origin.y + (float)offsetY };
                igSetCursorScreenPos(pos);

                /* Render the child widget */
                render_widget(child, state, new_state);
            }
        }
    }
    igEndChild();
}

static void render_widget(cJSON* widget, cJSON* state, cJSON* new_state) {
    if (!cJSON_IsObject(widget)) return;

    const char* type = get_string(widget, "type", "");

    /* Push ID if specified */
    const char* id = get_string(widget, "id", NULL);
    if (id) coex_imgui_push_id_str(id);

    /* Render based on type */
    if (strcmp(type, "window") == 0) render_window(widget, state, new_state);
    else if (strcmp(type, "column") == 0) render_column(widget, state, new_state);
    else if (strcmp(type, "row") == 0) render_row(widget, state, new_state);
    else if (strcmp(type, "text") == 0) render_text(widget, state, new_state);
    else if (strcmp(type, "button") == 0) render_button(widget, state, new_state);
    else if (strcmp(type, "checkbox") == 0) render_checkbox(widget, state, new_state);
    else if (strcmp(type, "slider_float") == 0 || strcmp(type, "slider") == 0)
        render_slider_float(widget, state, new_state);
    else if (strcmp(type, "slider_int") == 0) render_slider_int(widget, state, new_state);
    else if (strcmp(type, "input_text") == 0 || strcmp(type, "input") == 0)
        render_input_text(widget, state, new_state);
    else if (strcmp(type, "input_int") == 0) render_input_int(widget, state, new_state);
    else if (strcmp(type, "input_float") == 0) render_input_float(widget, state, new_state);
    else if (strcmp(type, "combo") == 0) render_combo(widget, state, new_state);
    else if (strcmp(type, "color_edit") == 0 || strcmp(type, "color") == 0)
        render_color_edit(widget, state, new_state);
    else if (strcmp(type, "progress") == 0) render_progress(widget, state, new_state);
    else if (strcmp(type, "tree") == 0) render_tree(widget, state, new_state);
    else if (strcmp(type, "collapsing") == 0) render_collapsing(widget, state, new_state);
    else if (strcmp(type, "separator") == 0) coex_imgui_separator();
    else if (strcmp(type, "spacing") == 0) coex_imgui_spacing();
    else if (strcmp(type, "svg_image") == 0) render_svg_image(widget, state, new_state);
    else if (strcmp(type, "canvas") == 0) render_canvas(widget, state, new_state);

    if (id) coex_imgui_pop_id();
}

/* ============================================================================
 * Public API
 * ============================================================================ */

int64_t coex_ui_init(const char* config_json) {
    if (_ui_state.initialized) return 1;

    /* Parse config */
    cJSON* config = cJSON_Parse(config_json ? config_json : "{}");
    if (!config) {
        fprintf(stderr, "coex_ui_init: Failed to parse config JSON\n");
        return 0;
    }

    const char* title = get_string(config, "title", "Coex UI");
    int64_t width = (int64_t)get_number(config, "width", 800);
    int64_t height = (int64_t)get_number(config, "height", 600);
    int resizable = get_bool(config, "resizable", 1);
    const char* theme = get_string(config, "theme", "dark");

    int64_t flags = 0;
    if (resizable) flags |= COEX_UI_FLAG_RESIZABLE;
    flags |= COEX_UI_FLAG_HIGHDPI;

    /* Initialize platform shell */
    if (!coex_ui_shell_init(title, width, height, flags)) {
        fprintf(stderr, "coex_ui_init: Failed to initialize platform shell\n");
        cJSON_Delete(config);
        return 0;
    }

    /* Initialize ImGui */
    if (!coex_imgui_init()) {
        fprintf(stderr, "coex_ui_init: Failed to initialize ImGui\n");
        coex_ui_shell_shutdown();
        cJSON_Delete(config);
        return 0;
    }

    /* Set theme */
    if (strcmp(theme, "light") == 0) {
        coex_imgui_style_colors_light();
    } else {
        coex_imgui_style_colors_dark();
    }

#ifdef __APPLE__
    /* Initialize Metal renderer */
    void* metal_device = coex_ui_shell_get_metal_device();
    if (!coex_ui_metal_init(metal_device)) {
        fprintf(stderr, "coex_ui_init: Failed to initialize Metal renderer\n");
        coex_imgui_shutdown();
        coex_ui_shell_shutdown();
        cJSON_Delete(config);
        return 0;
    }
    /* Initialize SVG texture system with Metal device */
    if (!svg_texture_init(metal_device)) {
        fprintf(stderr, "coex_ui_init: Warning - SVG texture system failed to initialize\n");
        /* Non-fatal - SVG rendering will just not work */
    }
    /* Font texture creation is deferred until first frame */
#else
    /* Initialize OpenGL renderer */
    if (!coex_ui_opengl_init()) {
        fprintf(stderr, "coex_ui_init: Failed to initialize OpenGL renderer\n");
        coex_imgui_shutdown();
        coex_ui_shell_shutdown();
        cJSON_Delete(config);
        return 0;
    }
    /* Font texture creation is deferred until first frame */
#endif

    _ui_state.initialized = 1;
    _ui_state.font_texture_created = 0;
    _ui_state.last_frame_time = coex_ui_shell_get_time();
    _ui_state.pending_events = cJSON_CreateArray();

    cJSON_Delete(config);
    return 1;
}

void coex_ui_shutdown(void) {
    if (!_ui_state.initialized) return;

    /* Free text buffers */
    for (int i = 0; i < _ui_state.text_buffer_count; i++) {
        free(_ui_state.text_buffers[i].id);
        free(_ui_state.text_buffers[i].buffer);
    }
    _ui_state.text_buffer_count = 0;

    if (_ui_state.pending_events) {
        cJSON_Delete(_ui_state.pending_events);
        _ui_state.pending_events = NULL;
    }

#ifdef __APPLE__
    coex_ui_metal_shutdown();
#else
    coex_ui_opengl_shutdown();
#endif
    coex_imgui_shutdown();
    coex_ui_shell_shutdown();
    _ui_state.initialized = 0;
}

int64_t coex_ui_should_close(void) {
    return coex_ui_shell_should_close();
}

double coex_ui_get_time(void) {
    return coex_ui_shell_get_time();
}

void coex_ui_begin_frame(void) {
    if (!_ui_state.initialized) return;

    /* Process platform events */
    coex_ui_shell_process_events();

    /* Calculate delta time */
    double now = coex_ui_shell_get_time();
    double delta = now - _ui_state.last_frame_time;
    _ui_state.last_frame_time = now;

    /* Get window size (in points) and scale factor for HiDPI */
    int64_t width, height;
    coex_ui_shell_get_size(&width, &height);

    float scale_x, scale_y;
    coex_ui_shell_get_content_scale(&scale_x, &scale_y);

    /* Update ImGui input - mouse coords are in points */
    double mx, my;
    coex_ui_shell_get_mouse_pos(&mx, &my);
    coex_imgui_io_set_mouse_pos(mx, my);

    for (int i = 0; i < 3; i++) {
        coex_imgui_io_set_mouse_down(i, coex_ui_shell_get_mouse_button(i));
    }

    int64_t mods = coex_ui_shell_get_modifiers();
    coex_imgui_io_set_modifiers(
        mods & COEX_UI_MOD_CTRL,
        mods & COEX_UI_MOD_SHIFT,
        mods & COEX_UI_MOD_ALT,
        mods & COEX_UI_MOD_SUPER
    );

    /* Process character input events and forward to ImGui */
    CoexUIEvent event;
    while (coex_ui_shell_poll_event(&event)) {
        if (event.type == COEX_UI_EVENT_CHAR) {
            coex_imgui_io_add_char(event.data.character.codepoint);
        } else if (event.type == COEX_UI_EVENT_KEY) {
            coex_imgui_io_set_key(event.data.key.keycode, event.data.key.pressed);
        }
    }

    /* Begin platform and ImGui frames */
    coex_ui_shell_begin_frame();
    coex_imgui_new_frame_scaled(width, height, scale_x, scale_y, delta);

    /* Create font texture on first frame (after NewFrame builds the font atlas) */
    if (!_ui_state.font_texture_created) {
#ifdef __APPLE__
        if (coex_ui_metal_create_fonts_texture()) {
            _ui_state.font_texture_created = 1;
        }
#else
        if (coex_ui_opengl_create_fonts_texture()) {
            _ui_state.font_texture_created = 1;
        }
#endif
    }
}

void coex_ui_end_frame(void) {
    if (!_ui_state.initialized) return;

    coex_imgui_render();

#ifdef __APPLE__
    /* Update font texture if needed (for dynamic glyph loading) */
    coex_ui_metal_update_fonts_texture();

    /* Render with Metal */
    void* draw_data = coex_imgui_get_draw_data();
    void* command_buffer = coex_ui_shell_create_command_buffer();
    void* render_target = coex_ui_shell_get_current_drawable_texture();

    if (draw_data && command_buffer && render_target) {
        int64_t fb_width, fb_height;
        coex_ui_shell_get_framebuffer_size(&fb_width, &fb_height);

        coex_ui_metal_render(command_buffer, render_target, draw_data, fb_width, fb_height);
        coex_ui_shell_present_and_commit(command_buffer);
    }
#else
#ifdef COEX_UI_HAS_OPENGL
    /* Render with OpenGL */
    void* draw_data = coex_imgui_get_draw_data();
    if (draw_data) {
        int64_t fb_width, fb_height;
        coex_ui_shell_get_framebuffer_size(&fb_width, &fb_height);

        /* Clear the framebuffer */
        glClearColor(0.1f, 0.1f, 0.1f, 1.0f);
        glClear(GL_COLOR_BUFFER_BIT);

        coex_ui_opengl_render(draw_data, fb_width, fb_height);
    }
#endif
#endif

    coex_ui_shell_end_frame();
}

const char* coex_ui_render_json(const char* layout_json, const char* state_json) {
    if (!_ui_state.initialized) {
        return strdup("{\"state\":{},\"events\":[]}");
    }

    /* Parse inputs */
    cJSON* layout = cJSON_Parse(layout_json ? layout_json : "{}");
    cJSON* state_input = cJSON_Parse(state_json ? state_json : "{}");

    if (!layout || !state_input) {
        if (layout) cJSON_Delete(layout);
        if (state_input) cJSON_Delete(state_input);
        return strdup("{\"state\":{},\"events\":[],\"error\":\"parse_error\"}");
    }

    /* Handle wrapped state format: {"state": {...}, "events": [...]}
     * If state_input has a "state" field, use that as the actual state */
    cJSON* state = cJSON_GetObjectItem(state_input, "state");
    if (!state) {
        state = state_input;  /* Use the input directly if not wrapped */
    }

    /* Begin frame */
    coex_ui_begin_frame();

    /* Create output containers - copy input state to preserve unchanged values */
    cJSON* new_state = cJSON_CreateObject();
    if (state && state->child) {
        cJSON* item = state->child;
        while (item) {
            if (item->string) {
                /* Copy each item from input state */
                if (cJSON_IsNumber(item)) {
                    cJSON_AddItemToObject(new_state, item->string, cJSON_CreateNumber(cJSON_GetNumberValue(item)));
                } else if (cJSON_IsTrue(item)) {
                    cJSON_AddItemToObject(new_state, item->string, cJSON_CreateBool(1));
                } else if (cJSON_IsFalse(item)) {
                    cJSON_AddItemToObject(new_state, item->string, cJSON_CreateBool(0));
                } else if (cJSON_IsString(item)) {
                    cJSON_AddItemToObject(new_state, item->string, cJSON_CreateString(cJSON_GetStringValue(item)));
                }
            }
            item = item->next;
        }
    }

    /* Clear pending events */
    cJSON_Delete(_ui_state.pending_events);
    _ui_state.pending_events = cJSON_CreateArray();

    /* Render layout */
    render_widget(layout, state, new_state);

    /* End frame */
    coex_ui_end_frame();

    /* Return just the state (not wrapped) for simpler Coex-side handling */
    char* output = cJSON_Print(new_state);

    /* Cleanup */
    cJSON_Delete(new_state);
    cJSON_Delete(layout);
    cJSON_Delete(state_input);

    return output;
}

void coex_ui_free_json(const char* json) {
    free((void*)json);
}

const char* coex_ui_get_events_json(void) {
    char* output = cJSON_Print(_ui_state.pending_events);
    cJSON_Delete(_ui_state.pending_events);
    _ui_state.pending_events = cJSON_CreateArray();
    return output;
}

/* ============================================================================
 * Direct Widget API
 * ============================================================================ */

int64_t coex_ui_begin_window(const char* title) {
    return coex_imgui_begin_window(title, 0);
}

void coex_ui_end_window(void) {
    coex_imgui_end_window();
}

void coex_ui_text(const char* text) {
    coex_imgui_text(text);
}

int64_t coex_ui_button(const char* label) {
    return coex_imgui_button(label) ? 1 : 0;
}

int64_t coex_ui_checkbox(const char* label, int64_t* value) {
    int v = *value ? 1 : 0;
    int64_t result = coex_imgui_checkbox(label, &v);
    *value = v;
    return result ? 1 : 0;
}

int64_t coex_ui_slider_float(const char* label, double* value, double min, double max) {
    return coex_imgui_slider_float(label, value, min, max) ? 1 : 0;
}

int64_t coex_ui_slider_int(const char* label, int64_t* value, int64_t min, int64_t max) {
    return coex_imgui_slider_int(label, value, min, max) ? 1 : 0;
}

int64_t coex_ui_input_text(const char* label, char* buf, int64_t buf_size) {
    return coex_imgui_input_text(label, buf, buf_size, 0) ? 1 : 0;
}

int64_t coex_ui_combo(const char* label, int64_t* selected, const char* const* items, int64_t count) {
    return coex_imgui_combo(label, selected, items, count) ? 1 : 0;
}

void coex_ui_begin_row(void) {
    coex_imgui_begin_horizontal();
}

void coex_ui_end_row(void) {
    coex_imgui_end_horizontal();
}

void coex_ui_spacing(void) {
    coex_imgui_spacing();
}

void coex_ui_separator(void) {
    coex_imgui_separator();
}
