/**
 * LunaSVG C Wrapper Implementation
 *
 * Provides C-compatible wrapper functions around the LunaSVG C++ library.
 * When COEX_SVG_HAS_LUNASVG is not defined, provides stub implementations
 * that return appropriate error values.
 */

#include "lunasvg_c.h"
#include <stdlib.h>
#include <string.h>

#ifdef COEX_SVG_HAS_LUNASVG

#include <lunasvg.h>
#include <memory>
#include <string>

using namespace lunasvg;

/* ============================================================================
 * Internal Helper Functions
 * ============================================================================ */

static inline Document* doc_cast(lunasvg_document_t doc) {
    return static_cast<Document*>(doc);
}

static inline Element* elem_cast(lunasvg_element_t elem) {
    return static_cast<Element*>(elem);
}

static inline Bitmap* bmp_cast(lunasvg_bitmap_t bmp) {
    return static_cast<Bitmap*>(bmp);
}

/* ============================================================================
 * Document Lifecycle
 * ============================================================================ */

lunasvg_document_t lunasvg_document_load_from_file(const char* filename) {
    if (!filename) return nullptr;

    auto doc = Document::loadFromFile(filename);
    if (!doc) return nullptr;

    // Transfer ownership to raw pointer
    return doc.release();
}

lunasvg_document_t lunasvg_document_load_from_data(const char* data, size_t length) {
    if (!data) return nullptr;

    std::unique_ptr<Document> doc;
    if (length == 0) {
        doc = Document::loadFromData(data);
    } else {
        doc = Document::loadFromData(data, length);
    }

    if (!doc) return nullptr;
    return doc.release();
}

void lunasvg_document_destroy(lunasvg_document_t doc) {
    if (doc) {
        delete doc_cast(doc);
    }
}

/* ============================================================================
 * Document Properties
 * ============================================================================ */

float lunasvg_document_width(lunasvg_document_t doc) {
    if (!doc) return 0.0f;
    return doc_cast(doc)->width();
}

float lunasvg_document_height(lunasvg_document_t doc) {
    if (!doc) return 0.0f;
    return doc_cast(doc)->height();
}

int lunasvg_document_get_viewbox(lunasvg_document_t doc,
                                  float* x, float* y, float* w, float* h) {
    if (!doc || !x || !y || !w || !h) return 0;

    auto box = doc_cast(doc)->boundingBox();
    *x = box.x;
    *y = box.y;
    *w = box.w;
    *h = box.h;
    return 1;
}

/* ============================================================================
 * Element Access
 * ============================================================================ */

lunasvg_element_t lunasvg_document_get_element_by_id(lunasvg_document_t doc,
                                                      const char* id) {
    if (!doc || !id) return nullptr;

    auto elem = doc_cast(doc)->getElementById(id);
    if (elem.isNull()) return nullptr;

    // Store element in a heap-allocated wrapper
    // Note: Element is a value type, we need to copy it
    Element* heap_elem = new Element(elem);
    return heap_elem;
}

lunasvg_element_t lunasvg_document_root(lunasvg_document_t doc) {
    if (!doc) return nullptr;

    auto root = doc_cast(doc)->documentElement();
    if (root.isNull()) return nullptr;

    Element* heap_elem = new Element(root);
    return heap_elem;
}

/* ============================================================================
 * Element Properties
 * ============================================================================ */

int lunasvg_element_set_attribute(lunasvg_element_t elem,
                                   const char* name,
                                   const char* value) {
    if (!elem || !name || !value) return 0;

    elem_cast(elem)->setAttribute(name, value);
    return 1;
}

char* lunasvg_element_get_attribute(lunasvg_element_t elem, const char* name) {
    if (!elem || !name) return nullptr;

    const std::string& value = elem_cast(elem)->getAttribute(name);
    if (value.empty()) return nullptr;

    char* result = static_cast<char*>(malloc(value.length() + 1));
    if (result) {
        strcpy(result, value.c_str());
    }
    return result;
}

int lunasvg_element_has_attribute(lunasvg_element_t elem, const char* name) {
    if (!elem || !name) return 0;
    return elem_cast(elem)->hasAttribute(name) ? 1 : 0;
}

int lunasvg_element_get_bounding_box(lunasvg_element_t elem,
                                      float* x, float* y, float* w, float* h) {
    if (!elem || !x || !y || !w || !h) return 0;

    auto box = elem_cast(elem)->getBoundingBox();
    // Check if box is valid (non-empty)
    if (box.w <= 0 || box.h <= 0) return 0;

    *x = box.x;
    *y = box.y;
    *w = box.w;
    *h = box.h;
    return 1;
}

int lunasvg_element_get_transform(lunasvg_element_t elem, float* matrix) {
    if (!elem || !matrix) return 0;

    auto transform = elem_cast(elem)->getLocalMatrix();
    matrix[0] = transform.a;
    matrix[1] = transform.b;
    matrix[2] = transform.c;
    matrix[3] = transform.d;
    matrix[4] = transform.e;
    matrix[5] = transform.f;
    return 1;
}

/* ============================================================================
 * Rendering
 * ============================================================================ */

lunasvg_bitmap_t lunasvg_document_render_to_bitmap(lunasvg_document_t doc,
                                                    int width, int height,
                                                    uint32_t bgcolor) {
    if (!doc || width <= 0 || height <= 0) return nullptr;

    Bitmap* bmp = new Bitmap(doc_cast(doc)->renderToBitmap(width, height, bgcolor));
    if (!bmp->valid()) {
        delete bmp;
        return nullptr;
    }
    return bmp;
}

lunasvg_bitmap_t lunasvg_document_render_to_bitmap_with_transform(
    lunasvg_document_t doc,
    int width, int height,
    uint32_t bgcolor,
    const float* matrix) {
    if (!doc || width <= 0 || height <= 0) return nullptr;

    // Create bitmap first
    Bitmap* bmp = new Bitmap(width, height);
    if (!bmp->valid()) {
        delete bmp;
        return nullptr;
    }

    // Clear with background color
    if (bgcolor != 0) {
        uint8_t* data = bmp->data();
        uint32_t a = (bgcolor >> 24) & 0xFF;
        uint32_t b = (bgcolor >> 16) & 0xFF;
        uint32_t g = (bgcolor >> 8) & 0xFF;
        uint32_t r = bgcolor & 0xFF;
        for (int i = 0; i < width * height; i++) {
            data[i * 4 + 0] = r;
            data[i * 4 + 1] = g;
            data[i * 4 + 2] = b;
            data[i * 4 + 3] = a;
        }
    }

    // Render with transform if provided
    if (matrix) {
        Matrix transform(matrix[0], matrix[1], matrix[2], matrix[3], matrix[4], matrix[5]);
        doc_cast(doc)->render(*bmp, transform);
    } else {
        doc_cast(doc)->render(*bmp);
    }

    return bmp;
}

lunasvg_bitmap_t lunasvg_element_render_to_bitmap(lunasvg_document_t doc,
                                                   lunasvg_element_t elem,
                                                   int width, int height,
                                                   uint32_t bgcolor) {
    if (!elem || width <= 0 || height <= 0) return nullptr;
    (void)doc; // Element has its own renderToBitmap

    Bitmap* bmp = new Bitmap(elem_cast(elem)->renderToBitmap(width, height, bgcolor));
    if (!bmp->valid()) {
        delete bmp;
        return nullptr;
    }
    return bmp;
}

/* ============================================================================
 * Bitmap Access
 * ============================================================================ */

void lunasvg_bitmap_convert_to_rgba(lunasvg_bitmap_t bmp) {
    if (!bmp) return;
    bmp_cast(bmp)->convertToRGBA();
}

uint8_t* lunasvg_bitmap_data(lunasvg_bitmap_t bmp) {
    if (!bmp) return nullptr;
    return bmp_cast(bmp)->data();
}

int lunasvg_bitmap_width(lunasvg_bitmap_t bmp) {
    if (!bmp) return 0;
    return static_cast<int>(bmp_cast(bmp)->width());
}

int lunasvg_bitmap_height(lunasvg_bitmap_t bmp) {
    if (!bmp) return 0;
    return static_cast<int>(bmp_cast(bmp)->height());
}

int lunasvg_bitmap_stride(lunasvg_bitmap_t bmp) {
    if (!bmp) return 0;
    return static_cast<int>(bmp_cast(bmp)->stride());
}

void lunasvg_bitmap_destroy(lunasvg_bitmap_t bmp) {
    if (bmp) {
        delete bmp_cast(bmp);
    }
}

/* ============================================================================
 * Utility Functions
 * ============================================================================ */

void lunasvg_free_string(char* str) {
    free(str);
}

int lunasvg_is_available(void) {
    return 1;
}

// Note: lunasvg_version() is already defined in the official lunasvg.h header
// We don't redefine it here

#else /* !COEX_SVG_HAS_LUNASVG */

/* ============================================================================
 * Stub Implementations (when LunaSVG is not available)
 * ============================================================================ */

#include <stdio.h>

lunasvg_document_t lunasvg_document_load_from_file(const char* filename) {
    (void)filename;
    fprintf(stderr, "Warning: LunaSVG not available, SVG loading disabled\n");
    return NULL;
}

lunasvg_document_t lunasvg_document_load_from_data(const char* data, size_t length) {
    (void)data;
    (void)length;
    return NULL;
}

void lunasvg_document_destroy(lunasvg_document_t doc) {
    (void)doc;
}

float lunasvg_document_width(lunasvg_document_t doc) {
    (void)doc;
    return 0.0f;
}

float lunasvg_document_height(lunasvg_document_t doc) {
    (void)doc;
    return 0.0f;
}

int lunasvg_document_get_viewbox(lunasvg_document_t doc,
                                  float* x, float* y, float* w, float* h) {
    (void)doc; (void)x; (void)y; (void)w; (void)h;
    return 0;
}

lunasvg_element_t lunasvg_document_get_element_by_id(lunasvg_document_t doc,
                                                      const char* id) {
    (void)doc; (void)id;
    return NULL;
}

lunasvg_element_t lunasvg_document_root(lunasvg_document_t doc) {
    (void)doc;
    return NULL;
}

int lunasvg_element_set_attribute(lunasvg_element_t elem,
                                   const char* name,
                                   const char* value) {
    (void)elem; (void)name; (void)value;
    return 0;
}

char* lunasvg_element_get_attribute(lunasvg_element_t elem, const char* name) {
    (void)elem; (void)name;
    return NULL;
}

int lunasvg_element_has_attribute(lunasvg_element_t elem, const char* name) {
    (void)elem; (void)name;
    return 0;
}

int lunasvg_element_get_bounding_box(lunasvg_element_t elem,
                                      float* x, float* y, float* w, float* h) {
    (void)elem; (void)x; (void)y; (void)w; (void)h;
    return 0;
}

int lunasvg_element_get_transform(lunasvg_element_t elem, float* matrix) {
    (void)elem; (void)matrix;
    return 0;
}

lunasvg_bitmap_t lunasvg_document_render_to_bitmap(lunasvg_document_t doc,
                                                    int width, int height,
                                                    uint32_t bgcolor) {
    (void)doc; (void)width; (void)height; (void)bgcolor;
    return NULL;
}

lunasvg_bitmap_t lunasvg_document_render_to_bitmap_with_transform(
    lunasvg_document_t doc,
    int width, int height,
    uint32_t bgcolor,
    const float* matrix) {
    (void)doc; (void)width; (void)height; (void)bgcolor; (void)matrix;
    return NULL;
}

lunasvg_bitmap_t lunasvg_element_render_to_bitmap(lunasvg_document_t doc,
                                                   lunasvg_element_t elem,
                                                   int width, int height,
                                                   uint32_t bgcolor) {
    (void)doc; (void)elem; (void)width; (void)height; (void)bgcolor;
    return NULL;
}

void lunasvg_bitmap_convert_to_rgba(lunasvg_bitmap_t bmp) {
    (void)bmp;
}

uint8_t* lunasvg_bitmap_data(lunasvg_bitmap_t bmp) {
    (void)bmp;
    return NULL;
}

int lunasvg_bitmap_width(lunasvg_bitmap_t bmp) {
    (void)bmp;
    return 0;
}

int lunasvg_bitmap_height(lunasvg_bitmap_t bmp) {
    (void)bmp;
    return 0;
}

int lunasvg_bitmap_stride(lunasvg_bitmap_t bmp) {
    (void)bmp;
    return 0;
}

void lunasvg_bitmap_destroy(lunasvg_bitmap_t bmp) {
    (void)bmp;
}

void lunasvg_free_string(char* str) {
    (void)str;
}

int lunasvg_is_available(void) {
    return 0;
}

#endif /* COEX_SVG_HAS_LUNASVG */
