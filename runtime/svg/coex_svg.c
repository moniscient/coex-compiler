/**
 * Coex SVG Module Implementation
 *
 * Provides SVG rendering with state bindings.
 * Uses LunaSVG for SVG parsing/rendering and integrates with the
 * existing ImGUI-based UI system.
 */

#include "coex_svg.h"
#include "lunasvg_c.h"
#include "coex_svg_texture.h"

#include <stdlib.h>
#include <stdio.h>
#include <string.h>

/* Include cJSON if available */
#ifdef COEX_UI_HAS_CJSON
#include "cJSON.h"
#define JSON_AVAILABLE 1
#else
#define JSON_AVAILABLE 0
#endif

/* ============================================================================
 * Internal Data Structures
 * ============================================================================ */

/** Maximum bindings per template */
#define MAX_BINDINGS 256

/** Maximum events per template */
#define MAX_EVENTS 64

/** Maximum templates */
#define MAX_TEMPLATES 64

/** Binding: maps element attribute to state key */
typedef struct SVGBinding {
    char* element_id;
    char* attribute;
    char* state_key;
} SVGBinding;

/** Event registration: maps element event to state key */
typedef struct SVGEvent {
    char* element_id;
    int event_type;
    char* state_key;
    /* Cached bounding box (computed once at registration) */
    float bbox_x, bbox_y, bbox_w, bbox_h;
    int bbox_valid;
    /* Hover state tracking */
    int was_hovered;
} SVGEvent;

/** SVG Template: holds document, bindings, events, and texture */
typedef struct SVGTemplate {
    int64_t handle;
    int in_use;

    lunasvg_document_t document;

    SVGBinding bindings[MAX_BINDINGS];
    int binding_count;

    SVGEvent events[MAX_EVENTS];
    int event_count;

    svg_texture_t texture;
    int texture_width;
    int texture_height;

    /* Original SVG dimensions */
    float svg_width;
    float svg_height;

    /* Dirty flag for re-rendering */
    int dirty;
} SVGTemplate;

/* ============================================================================
 * Module State
 * ============================================================================ */

static struct {
    int initialized;
    SVGTemplate templates[MAX_TEMPLATES];
    int64_t next_handle;
} _svg_state;

/* ============================================================================
 * Internal Helper Functions
 * ============================================================================ */

static SVGTemplate* get_template(int64_t handle) {
    if (handle <= 0 || handle > MAX_TEMPLATES) return NULL;
    SVGTemplate* tmpl = &_svg_state.templates[handle - 1];
    return tmpl->in_use ? tmpl : NULL;
}

static int64_t allocate_template(void) {
    for (int i = 0; i < MAX_TEMPLATES; i++) {
        if (!_svg_state.templates[i].in_use) {
            _svg_state.templates[i].in_use = 1;
            _svg_state.templates[i].handle = i + 1;
            return i + 1;
        }
    }
    return 0;
}

static void free_binding(SVGBinding* binding) {
    if (binding->element_id) { free(binding->element_id); binding->element_id = NULL; }
    if (binding->attribute) { free(binding->attribute); binding->attribute = NULL; }
    if (binding->state_key) { free(binding->state_key); binding->state_key = NULL; }
}

static void free_event(SVGEvent* event) {
    if (event->element_id) { free(event->element_id); event->element_id = NULL; }
    if (event->state_key) { free(event->state_key); event->state_key = NULL; }
}

static char* str_dup(const char* s) {
    if (!s) return NULL;
    size_t len = strlen(s);
    char* copy = (char*)malloc(len + 1);
    if (copy) {
        memcpy(copy, s, len + 1);
    }
    return copy;
}

/* Cache element bounding box for hit testing */
static void cache_element_bbox(SVGTemplate* tmpl, SVGEvent* event) {
    if (!tmpl->document || !event->element_id) return;

    lunasvg_element_t elem = lunasvg_document_get_element_by_id(
        tmpl->document, event->element_id);
    if (!elem) return;

    if (lunasvg_element_get_bounding_box(elem,
            &event->bbox_x, &event->bbox_y,
            &event->bbox_w, &event->bbox_h)) {
        event->bbox_valid = 1;
    }

    /* Note: Element handles from LunaSVG need to be freed if they were heap-allocated */
    /* The current wrapper allocates them on heap, so we need a destroy function */
    /* For now, we'll leak these - TODO: add lunasvg_element_destroy */
}

/* ============================================================================
 * Module Initialization
 * ============================================================================ */

int64_t coex_svg_init(void* graphics_device) {
    if (_svg_state.initialized) return 1;

    memset(&_svg_state, 0, sizeof(_svg_state));
    _svg_state.initialized = 1;
    _svg_state.next_handle = 1;

    /* Initialize texture system (optional - SVG loading works without it) */
    if (graphics_device) {
        if (!svg_texture_init(graphics_device)) {
            fprintf(stderr, "coex_svg_init: Texture system unavailable (SVG loading still works)\n");
        }
    }

    return 1;
}

void coex_svg_shutdown(void) {
    if (!_svg_state.initialized) return;

    /* Destroy all templates */
    for (int i = 0; i < MAX_TEMPLATES; i++) {
        if (_svg_state.templates[i].in_use) {
            coex_svg_destroy(i + 1);
        }
    }

    svg_texture_shutdown();
    _svg_state.initialized = 0;
}

int64_t coex_svg_is_available(void) {
    return lunasvg_is_available();
}

/* ============================================================================
 * SVG Template Lifecycle
 * ============================================================================ */

int64_t coex_svg_load(const char* path) {
    if (!_svg_state.initialized) {
        fprintf(stderr, "coex_svg_load: Module not initialized\n");
        return 0;
    }
    if (!path) return 0;

    lunasvg_document_t doc = lunasvg_document_load_from_file(path);
    if (!doc) {
        fprintf(stderr, "coex_svg_load: Failed to load '%s'\n", path);
        return 0;
    }

    int64_t handle = allocate_template();
    if (!handle) {
        fprintf(stderr, "coex_svg_load: No free template slots\n");
        lunasvg_document_destroy(doc);
        return 0;
    }

    SVGTemplate* tmpl = get_template(handle);
    tmpl->document = doc;
    tmpl->svg_width = lunasvg_document_width(doc);
    tmpl->svg_height = lunasvg_document_height(doc);
    tmpl->dirty = 1;

    return handle;
}

int64_t coex_svg_load_from_data(const char* data, int64_t length) {
    if (!_svg_state.initialized || !data) return 0;

    lunasvg_document_t doc = lunasvg_document_load_from_data(data, (size_t)length);
    if (!doc) {
        fprintf(stderr, "coex_svg_load_from_data: Failed to parse SVG data\n");
        return 0;
    }

    int64_t handle = allocate_template();
    if (!handle) {
        lunasvg_document_destroy(doc);
        return 0;
    }

    SVGTemplate* tmpl = get_template(handle);
    tmpl->document = doc;
    tmpl->svg_width = lunasvg_document_width(doc);
    tmpl->svg_height = lunasvg_document_height(doc);
    tmpl->dirty = 1;

    return handle;
}

void coex_svg_destroy(int64_t handle) {
    SVGTemplate* tmpl = get_template(handle);
    if (!tmpl) return;

    /* Free bindings */
    for (int i = 0; i < tmpl->binding_count; i++) {
        free_binding(&tmpl->bindings[i]);
    }

    /* Free events */
    for (int i = 0; i < tmpl->event_count; i++) {
        free_event(&tmpl->events[i]);
    }

    /* Free texture */
    if (tmpl->texture) {
        svg_texture_destroy(tmpl->texture);
    }

    /* Free document */
    if (tmpl->document) {
        lunasvg_document_destroy(tmpl->document);
    }

    memset(tmpl, 0, sizeof(SVGTemplate));
}

/* ============================================================================
 * Template Properties
 * ============================================================================ */

double coex_svg_width(int64_t handle) {
    SVGTemplate* tmpl = get_template(handle);
    return tmpl ? (double)tmpl->svg_width : 0.0;
}

double coex_svg_height(int64_t handle) {
    SVGTemplate* tmpl = get_template(handle);
    return tmpl ? (double)tmpl->svg_height : 0.0;
}

/* ============================================================================
 * State Bindings
 * ============================================================================ */

int64_t coex_svg_bind(int64_t handle, const char* element_id,
                      const char* attribute, const char* state_key) {
    SVGTemplate* tmpl = get_template(handle);
    if (!tmpl || !element_id || !attribute || !state_key) return 0;

    if (tmpl->binding_count >= MAX_BINDINGS) {
        fprintf(stderr, "coex_svg_bind: Maximum bindings reached\n");
        return 0;
    }

    /* Verify element exists */
    lunasvg_element_t elem = lunasvg_document_get_element_by_id(tmpl->document, element_id);
    if (!elem) {
        fprintf(stderr, "coex_svg_bind: Element '%s' not found\n", element_id);
        return 0;
    }

    SVGBinding* binding = &tmpl->bindings[tmpl->binding_count++];
    binding->element_id = str_dup(element_id);
    binding->attribute = str_dup(attribute);
    binding->state_key = str_dup(state_key);

    return 1;
}

int64_t coex_svg_bind_element(int64_t handle, const char* element_id,
                              const char* bindings_json) {
#if JSON_AVAILABLE
    SVGTemplate* tmpl = get_template(handle);
    if (!tmpl || !element_id || !bindings_json) return 0;

    cJSON* json = cJSON_Parse(bindings_json);
    if (!json || !cJSON_IsObject(json)) {
        if (json) cJSON_Delete(json);
        return 0;
    }

    int count = 0;
    cJSON* item;
    cJSON_ArrayForEach(item, json) {
        if (cJSON_IsString(item)) {
            if (coex_svg_bind(handle, element_id, item->string, item->valuestring)) {
                count++;
            }
        }
    }

    cJSON_Delete(json);
    return count;
#else
    (void)handle; (void)element_id; (void)bindings_json;
    return 0;
#endif
}

int64_t coex_svg_unbind(int64_t handle, const char* element_id) {
    SVGTemplate* tmpl = get_template(handle);
    if (!tmpl || !element_id) return 0;

    int removed = 0;
    int i = 0;
    while (i < tmpl->binding_count) {
        if (strcmp(tmpl->bindings[i].element_id, element_id) == 0) {
            free_binding(&tmpl->bindings[i]);
            /* Shift remaining bindings */
            for (int j = i; j < tmpl->binding_count - 1; j++) {
                tmpl->bindings[j] = tmpl->bindings[j + 1];
            }
            tmpl->binding_count--;
            removed++;
        } else {
            i++;
        }
    }

    return removed;
}

/* ============================================================================
 * Event Registration
 * ============================================================================ */

int64_t coex_svg_on(int64_t handle, const char* element_id,
                    int64_t event_type, const char* state_key) {
    SVGTemplate* tmpl = get_template(handle);
    if (!tmpl || !element_id || !state_key) return 0;

    if (tmpl->event_count >= MAX_EVENTS) {
        fprintf(stderr, "coex_svg_on: Maximum events reached\n");
        return 0;
    }

    SVGEvent* event = &tmpl->events[tmpl->event_count++];
    event->element_id = str_dup(element_id);
    event->event_type = (int)event_type;
    event->state_key = str_dup(state_key);
    event->bbox_valid = 0;
    event->was_hovered = 0;

    /* Cache bounding box */
    cache_element_bbox(tmpl, event);

    return 1;
}

int64_t coex_svg_off(int64_t handle, const char* element_id, int64_t event_type) {
    SVGTemplate* tmpl = get_template(handle);
    if (!tmpl || !element_id) return 0;

    for (int i = 0; i < tmpl->event_count; i++) {
        if (tmpl->events[i].event_type == (int)event_type &&
            strcmp(tmpl->events[i].element_id, element_id) == 0) {
            free_event(&tmpl->events[i]);
            /* Shift remaining events */
            for (int j = i; j < tmpl->event_count - 1; j++) {
                tmpl->events[j] = tmpl->events[j + 1];
            }
            tmpl->event_count--;
            return 1;
        }
    }

    return 0;
}

int64_t coex_svg_get_event_count(int64_t handle) {
    SVGTemplate* tmpl = get_template(handle);
    if (!tmpl) return 0;
    return tmpl->event_count;
}

int64_t coex_svg_get_event_info(int64_t handle, int64_t index,
                                 int64_t* event_type, const char** state_key,
                                 float* bbox_x, float* bbox_y,
                                 float* bbox_w, float* bbox_h) {
    SVGTemplate* tmpl = get_template(handle);
    if (!tmpl || index < 0 || index >= tmpl->event_count) return 0;

    SVGEvent* event = &tmpl->events[index];
    if (!event->bbox_valid) return 0;

    if (event_type) *event_type = event->event_type;
    if (state_key) *state_key = event->state_key;
    if (bbox_x) *bbox_x = event->bbox_x;
    if (bbox_y) *bbox_y = event->bbox_y;
    if (bbox_w) *bbox_w = event->bbox_w;
    if (bbox_h) *bbox_h = event->bbox_h;

    return 1;
}

/* ============================================================================
 * Apply State to Document
 * ============================================================================ */

int64_t coex_svg_apply_state(int64_t handle, const char* state_json) {
#if JSON_AVAILABLE
    SVGTemplate* tmpl = get_template(handle);
    if (!tmpl || !state_json) return 0;

    cJSON* state = cJSON_Parse(state_json);
    if (!state || !cJSON_IsObject(state)) {
        if (state) cJSON_Delete(state);
        return 0;
    }

    int applied = 0;

    for (int i = 0; i < tmpl->binding_count; i++) {
        SVGBinding* binding = &tmpl->bindings[i];

        cJSON* value = cJSON_GetObjectItemCaseSensitive(state, binding->state_key);
        if (!value) continue;

        /* Get element */
        lunasvg_element_t elem = lunasvg_document_get_element_by_id(
            tmpl->document, binding->element_id);
        if (!elem) continue;

        /* Convert value to string */
        char value_str[256];
        if (cJSON_IsString(value)) {
            strncpy(value_str, value->valuestring, sizeof(value_str) - 1);
            value_str[sizeof(value_str) - 1] = '\0';
        } else if (cJSON_IsNumber(value)) {
            snprintf(value_str, sizeof(value_str), "%g", value->valuedouble);
        } else if (cJSON_IsBool(value)) {
            strcpy(value_str, cJSON_IsTrue(value) ? "true" : "false");
        } else {
            continue;
        }

        /* Apply to element */
        if (lunasvg_element_set_attribute(elem, binding->attribute, value_str)) {
            applied++;
            tmpl->dirty = 1;
        }
    }

    cJSON_Delete(state);
    return applied;
#else
    (void)handle; (void)state_json;
    return 0;
#endif
}

/* ============================================================================
 * Rendering
 * ============================================================================ */

int64_t coex_svg_render_to_texture(int64_t handle, int64_t width, int64_t height) {
    SVGTemplate* tmpl = get_template(handle);
    if (!tmpl || width <= 0 || height <= 0) return 0;

    /* Create or resize texture if needed */
    if (!tmpl->texture ||
        tmpl->texture_width != (int)width ||
        tmpl->texture_height != (int)height) {

        if (tmpl->texture) {
            svg_texture_destroy(tmpl->texture);
        }

        tmpl->texture = svg_texture_create((int)width, (int)height);
        if (!tmpl->texture) {
            fprintf(stderr, "coex_svg_render_to_texture: Failed to create texture\n");
            return 0;
        }

        tmpl->texture_width = (int)width;
        tmpl->texture_height = (int)height;
        tmpl->dirty = 1;
    }

    /* Only re-render if dirty */
    if (!tmpl->dirty) return 1;

    /* Render SVG to bitmap */
    lunasvg_bitmap_t bitmap = lunasvg_document_render_to_bitmap(
        tmpl->document, (int)width, (int)height, 0x00000000);
    if (!bitmap) {
        fprintf(stderr, "coex_svg_render_to_texture: Failed to render SVG\n");
        return 0;
    }

    /* Convert from ARGB32 Premultiplied to RGBA Plain for GPU texture */
    lunasvg_bitmap_convert_to_rgba(bitmap);

    /* Upload to texture */
    uint8_t* data = lunasvg_bitmap_data(bitmap);
    int stride = lunasvg_bitmap_stride(bitmap);

    int result = svg_texture_update(tmpl->texture, data,
                                     (int)width, (int)height, stride);

    lunasvg_bitmap_destroy(bitmap);

    if (result) {
        tmpl->dirty = 0;
    }

    return result;
}

void* coex_svg_get_texture_id(int64_t handle) {
    SVGTemplate* tmpl = get_template(handle);
    if (!tmpl || !tmpl->texture) return NULL;
    return svg_texture_get_imgui_id(tmpl->texture);
}

/* ============================================================================
 * Frame Rendering with Events
 * ============================================================================ */

const char* coex_svg_render_frame(int64_t handle, const char* state_json,
                                   float screen_x, float screen_y,
                                   int64_t width, int64_t height) {
#if JSON_AVAILABLE
    SVGTemplate* tmpl = get_template(handle);
    if (!tmpl) return NULL;

    /* Apply state bindings */
    if (state_json) {
        coex_svg_apply_state(handle, state_json);
    }

    /* Render to texture */
    if (!coex_svg_render_to_texture(handle, width, height)) {
        return NULL;
    }

    /* Parse input state for bindings lookup (read-only) */
    cJSON* input_state = state_json ? cJSON_Parse(state_json) : NULL;

    /* Create a new object for ONLY the events we generate - don't echo back entire state */
    cJSON* events = cJSON_CreateObject();
    if (!events) {
        if (input_state) cJSON_Delete(input_state);
        return NULL;
    }

    /* Get mouse position from ImGui - this requires imgui wrapper */
    /* For now, we'll use the passed-in coordinates */
    /* TODO: integrate with coex_imgui_io functions */

    /* Process events */
    for (int i = 0; i < tmpl->event_count; i++) {
        SVGEvent* event = &tmpl->events[i];
        if (!event->bbox_valid) continue;

        /* Transform screen coordinates to SVG coordinates */
        float scale_x = tmpl->svg_width / (float)width;
        float scale_y = tmpl->svg_height / (float)height;

        /* Note: screen_x/y would be actual mouse position from ImGui */
        /* For now, this is placeholder - actual integration needs ImGui */
        int is_hovered = 0;

        /* Calculate if mouse is inside bbox */
        /* float svg_mouse_x = (screen_x - img_x) * scale_x;
           float svg_mouse_y = (screen_y - img_y) * scale_y;
           is_hovered = (svg_mouse_x >= event->bbox_x &&
                        svg_mouse_x <= event->bbox_x + event->bbox_w &&
                        svg_mouse_y >= event->bbox_y &&
                        svg_mouse_y <= event->bbox_y + event->bbox_h); */

        /* Note: Full event processing would need ImGui integration */
        /* Setting events based on event type - only add triggered events */
        switch (event->event_type) {
            case COEX_SVG_EVENT_CLICK:
                /* Would check imgui is_item_clicked */
                break;
            case COEX_SVG_EVENT_HOVER:
                if (is_hovered) {
                    cJSON_AddTrueToObject(events, event->state_key);
                }
                break;
            case COEX_SVG_EVENT_MOUSEENTER:
                if (is_hovered && !event->was_hovered) {
                    cJSON_AddTrueToObject(events, event->state_key);
                }
                break;
            case COEX_SVG_EVENT_MOUSELEAVE:
                if (!is_hovered && event->was_hovered) {
                    cJSON_AddTrueToObject(events, event->state_key);
                }
                break;
        }

        event->was_hovered = is_hovered;
        (void)scale_x;
        (void)scale_y;
    }

    if (input_state) cJSON_Delete(input_state);

    /* Return only the events object - not the entire state */
    char* result = cJSON_PrintUnformatted(events);
    cJSON_Delete(events);
    return result;
#else
    (void)handle; (void)state_json;
    (void)screen_x; (void)screen_y;
    (void)width; (void)height;
    return NULL;
#endif
}

const char* coex_svg_image_descriptor(int64_t handle, int64_t width, int64_t height) {
#if JSON_AVAILABLE
    SVGTemplate* tmpl = get_template(handle);
    if (!tmpl) return NULL;

    cJSON* desc = cJSON_CreateObject();
    cJSON_AddStringToObject(desc, "type", "svg_image");
    cJSON_AddNumberToObject(desc, "handle", (double)handle);
    cJSON_AddNumberToObject(desc, "width", (double)width);
    cJSON_AddNumberToObject(desc, "height", (double)height);

    char* result = cJSON_PrintUnformatted(desc);
    cJSON_Delete(desc);
    return result;
#else
    (void)handle; (void)width; (void)height;
    return NULL;
#endif
}

void coex_svg_free_json(const char* json) {
    if (json) {
        free((void*)json);
    }
}

/* ============================================================================
 * Utility Functions
 * ============================================================================ */

int64_t coex_svg_get_element_bounds(int64_t handle, const char* element_id,
                                     float* x, float* y, float* w, float* h) {
    SVGTemplate* tmpl = get_template(handle);
    if (!tmpl || !element_id || !x || !y || !w || !h) return 0;

    lunasvg_element_t elem = lunasvg_document_get_element_by_id(
        tmpl->document, element_id);
    if (!elem) return 0;

    return lunasvg_element_get_bounding_box(elem, x, y, w, h);
}

int64_t coex_svg_hit_test(int64_t handle, const char* element_id,
                          float screen_x, float screen_y,
                          float img_x, float img_y,
                          float img_w, float img_h) {
    SVGTemplate* tmpl = get_template(handle);
    if (!tmpl || !element_id) return 0;

    /* Get element bounds */
    float bbox_x, bbox_y, bbox_w, bbox_h;
    if (!coex_svg_get_element_bounds(handle, element_id,
                                      &bbox_x, &bbox_y, &bbox_w, &bbox_h)) {
        return 0;
    }

    /* Transform screen to SVG coordinates */
    float scale_x = tmpl->svg_width / img_w;
    float scale_y = tmpl->svg_height / img_h;

    float svg_x = (screen_x - img_x) * scale_x;
    float svg_y = (screen_y - img_y) * scale_y;

    /* Check if inside bounds */
    return (svg_x >= bbox_x && svg_x <= bbox_x + bbox_w &&
            svg_y >= bbox_y && svg_y <= bbox_y + bbox_h) ? 1 : 0;
}
