/**
 * Coex SVG Texture - Metal Implementation
 *
 * Provides GPU texture management using Apple Metal.
 * Textures are created with RGBA8Unorm format for compatibility with
 * LunaSVG's RGBA output and ImGui's rendering.
 */

#import <Metal/Metal.h>
#import <CoreFoundation/CoreFoundation.h>
#include <stdlib.h>
#include <stdio.h>

#include "coex_svg_texture.h"

/* Internal texture structure - use void* to avoid ARC complications */
typedef struct SVGTextureInternal {
    void* texture;  /* Actually id<MTLTexture>, retained manually */
    int width;
    int height;
} SVGTextureInternal;

/* Global state */
static struct {
    int initialized;
    id<MTLDevice> device;
} _svg_tex_state;

/* ============================================================================
 * Platform Integration
 * ============================================================================ */

int svg_texture_init(void* device) {
    if (_svg_tex_state.initialized) return 1;
    if (!device) return 0;

    _svg_tex_state.device = (__bridge id<MTLDevice>)device;
    _svg_tex_state.initialized = 1;
    return 1;
}

void svg_texture_shutdown(void) {
    _svg_tex_state.device = nil;
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

    /* Create texture descriptor - no autoreleasepool needed since newTexture returns retained */
    MTLTextureDescriptor* desc = [MTLTextureDescriptor
        texture2DDescriptorWithPixelFormat:MTLPixelFormatRGBA8Unorm
                                     width:(NSUInteger)width
                                    height:(NSUInteger)height
                                 mipmapped:NO];
    desc.usage = MTLTextureUsageShaderRead;
    desc.storageMode = MTLStorageModeShared;

    /* Create the texture - newTextureWithDescriptor returns a retained object */
    id<MTLTexture> mtlTexture = [_svg_tex_state.device newTextureWithDescriptor:desc];
    if (!mtlTexture) {
        fprintf(stderr, "svg_texture_create: Failed to create Metal texture\n");
        return NULL;
    }

    /* Allocate internal structure */
    SVGTextureInternal* tex = (SVGTextureInternal*)calloc(1, sizeof(SVGTextureInternal));
    if (!tex) {
        fprintf(stderr, "svg_texture_create: Failed to allocate texture structure\n");
        return NULL;
    }

    /* Store the texture - use CFBridgingRetain to transfer ownership out of ARC */
    tex->texture = (void*)CFBridgingRetain(mtlTexture);
    tex->width = width;
    tex->height = height;

    return (svg_texture_t)tex;
}

void svg_texture_destroy(svg_texture_t tex) {
    if (!tex) return;

    SVGTextureInternal* internal = (SVGTextureInternal*)tex;
    /* Release the retained texture */
    if (internal->texture) {
        CFRelease((CFTypeRef)internal->texture);
        internal->texture = NULL;
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

    @autoreleasepool {
        id<MTLTexture> mtlTex = (__bridge id<MTLTexture>)internal->texture;
        MTLRegion region = MTLRegionMake2D(0, 0, (NSUInteger)width, (NSUInteger)height);
        [mtlTex replaceRegion:region
                  mipmapLevel:0
                    withBytes:rgba
                  bytesPerRow:(NSUInteger)stride];
    }

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

    @autoreleasepool {
        id<MTLTexture> mtlTex = (__bridge id<MTLTexture>)internal->texture;
        MTLRegion region = MTLRegionMake2D((NSUInteger)x, (NSUInteger)y,
                                           (NSUInteger)width, (NSUInteger)height);
        [mtlTex replaceRegion:region
                  mipmapLevel:0
                    withBytes:rgba
                  bytesPerRow:(NSUInteger)stride];
    }

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
    /* ImGui uses the texture pointer directly as ImTextureID on Metal */
    return internal->texture;
}
