/**
 * Coex SVG Texture - OpenGL Implementation
 *
 * Provides GPU texture management using OpenGL.
 * Textures are created with RGBA format for compatibility with
 * LunaSVG's RGBA output and ImGui's rendering.
 */

#include <stdlib.h>
#include <stdio.h>
#include <string.h>

#include "coex_svg_texture.h"

#ifdef COEX_UI_HAS_OPENGL

#include <GL/gl.h>

/* Internal texture structure */
typedef struct SVGTextureInternal {
    GLuint texture_id;
    int width;
    int height;
} SVGTextureInternal;

/* Global state */
static struct {
    int initialized;
} _svg_tex_state;

/* ============================================================================
 * Platform Integration
 * ============================================================================ */

int svg_texture_init(void* device) {
    (void)device; /* OpenGL doesn't need a device pointer */

    if (_svg_tex_state.initialized) return 1;

    /* Verify we have a valid OpenGL context */
    const GLubyte* version = glGetString(GL_VERSION);
    if (!version) {
        fprintf(stderr, "svg_texture_init: No OpenGL context available\n");
        return 0;
    }

    _svg_tex_state.initialized = 1;
    return 1;
}

void svg_texture_shutdown(void) {
    _svg_tex_state.initialized = 0;
}

int svg_texture_is_available(void) {
    return _svg_tex_state.initialized;
}

/* ============================================================================
 * Texture Lifecycle
 * ============================================================================ */

svg_texture_t svg_texture_create(int width, int height) {
    if (!_svg_tex_state.initialized) {
        fprintf(stderr, "svg_texture_create: Texture system not initialized\n");
        return NULL;
    }
    if (width <= 0 || height <= 0) {
        fprintf(stderr, "svg_texture_create: Invalid dimensions %dx%d\n", width, height);
        return NULL;
    }

    /* Allocate internal structure */
    SVGTextureInternal* tex = (SVGTextureInternal*)calloc(1, sizeof(SVGTextureInternal));
    if (!tex) {
        fprintf(stderr, "svg_texture_create: Failed to allocate texture structure\n");
        return NULL;
    }

    /* Generate OpenGL texture */
    glGenTextures(1, &tex->texture_id);
    if (tex->texture_id == 0) {
        fprintf(stderr, "svg_texture_create: Failed to generate texture\n");
        free(tex);
        return NULL;
    }

    /* Configure texture */
    glBindTexture(GL_TEXTURE_2D, tex->texture_id);
    glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MIN_FILTER, GL_LINEAR);
    glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MAG_FILTER, GL_LINEAR);
    glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_WRAP_S, GL_CLAMP_TO_EDGE);
    glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_WRAP_T, GL_CLAMP_TO_EDGE);

    /* Allocate texture storage */
    glTexImage2D(GL_TEXTURE_2D, 0, GL_RGBA8, width, height, 0,
                 GL_RGBA, GL_UNSIGNED_BYTE, NULL);

    glBindTexture(GL_TEXTURE_2D, 0);

    tex->width = width;
    tex->height = height;

    return (svg_texture_t)tex;
}

void svg_texture_destroy(svg_texture_t tex) {
    if (!tex) return;

    SVGTextureInternal* internal = (SVGTextureInternal*)tex;
    if (internal->texture_id != 0) {
        glDeleteTextures(1, &internal->texture_id);
    }
    free(internal);
}

/* ============================================================================
 * Texture Updates
 * ============================================================================ */

int svg_texture_update(svg_texture_t tex, const uint8_t* rgba,
                       int width, int height, int stride) {
    if (!tex || !rgba) return 0;

    SVGTextureInternal* internal = (SVGTextureInternal*)tex;

    /* Verify dimensions match */
    if (width != internal->width || height != internal->height) {
        fprintf(stderr, "svg_texture_update: Dimension mismatch (%dx%d vs %dx%d)\n",
                width, height, internal->width, internal->height);
        return 0;
    }

    glBindTexture(GL_TEXTURE_2D, internal->texture_id);

    /* Handle stride - if stride matches expected, upload directly */
    int expected_stride = width * 4;
    if (stride == expected_stride) {
        glTexSubImage2D(GL_TEXTURE_2D, 0, 0, 0, width, height,
                        GL_RGBA, GL_UNSIGNED_BYTE, rgba);
    } else {
        /* Row-by-row upload for non-standard stride */
        glPixelStorei(GL_UNPACK_ROW_LENGTH, stride / 4);
        glTexSubImage2D(GL_TEXTURE_2D, 0, 0, 0, width, height,
                        GL_RGBA, GL_UNSIGNED_BYTE, rgba);
        glPixelStorei(GL_UNPACK_ROW_LENGTH, 0);
    }

    glBindTexture(GL_TEXTURE_2D, 0);

    return 1;
}

int svg_texture_update_region(svg_texture_t tex, const uint8_t* rgba,
                              int x, int y, int width, int height, int stride) {
    if (!tex || !rgba) return 0;

    SVGTextureInternal* internal = (SVGTextureInternal*)tex;

    /* Bounds checking */
    if (x < 0 || y < 0 ||
        x + width > internal->width ||
        y + height > internal->height) {
        fprintf(stderr, "svg_texture_update_region: Region out of bounds\n");
        return 0;
    }

    glBindTexture(GL_TEXTURE_2D, internal->texture_id);

    int expected_stride = width * 4;
    if (stride == expected_stride) {
        glTexSubImage2D(GL_TEXTURE_2D, 0, x, y, width, height,
                        GL_RGBA, GL_UNSIGNED_BYTE, rgba);
    } else {
        glPixelStorei(GL_UNPACK_ROW_LENGTH, stride / 4);
        glTexSubImage2D(GL_TEXTURE_2D, 0, x, y, width, height,
                        GL_RGBA, GL_UNSIGNED_BYTE, rgba);
        glPixelStorei(GL_UNPACK_ROW_LENGTH, 0);
    }

    glBindTexture(GL_TEXTURE_2D, 0);

    return 1;
}

/* ============================================================================
 * Texture Properties
 * ============================================================================ */

int svg_texture_width(svg_texture_t tex) {
    if (!tex) return 0;
    return ((SVGTextureInternal*)tex)->width;
}

int svg_texture_height(svg_texture_t tex) {
    if (!tex) return 0;
    return ((SVGTextureInternal*)tex)->height;
}

void* svg_texture_get_imgui_id(svg_texture_t tex) {
    if (!tex) return NULL;
    SVGTextureInternal* internal = (SVGTextureInternal*)tex;
    /* ImGui uses the GLuint texture ID cast to void* */
    return (void*)(uintptr_t)internal->texture_id;
}

#else /* !COEX_UI_HAS_OPENGL */

/* Stub implementations when OpenGL is not available */

int svg_texture_init(void* device) {
    (void)device;
    fprintf(stderr, "svg_texture_init: OpenGL not available\n");
    return 0;
}

void svg_texture_shutdown(void) {}

int svg_texture_is_available(void) { return 0; }

svg_texture_t svg_texture_create(int width, int height) {
    (void)width; (void)height;
    return NULL;
}

void svg_texture_destroy(svg_texture_t tex) { (void)tex; }

int svg_texture_update(svg_texture_t tex, const uint8_t* rgba,
                       int width, int height, int stride) {
    (void)tex; (void)rgba; (void)width; (void)height; (void)stride;
    return 0;
}

int svg_texture_update_region(svg_texture_t tex, const uint8_t* rgba,
                              int x, int y, int width, int height, int stride) {
    (void)tex; (void)rgba; (void)x; (void)y; (void)width; (void)height; (void)stride;
    return 0;
}

int svg_texture_width(svg_texture_t tex) { (void)tex; return 0; }
int svg_texture_height(svg_texture_t tex) { (void)tex; return 0; }
void* svg_texture_get_imgui_id(svg_texture_t tex) { (void)tex; return NULL; }

#endif /* COEX_UI_HAS_OPENGL */
