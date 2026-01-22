/**
 * Coex UI Skia Rendering Backend
 *
 * Renders Dear ImGui draw data using Skia graphics library.
 * Supports both software and GPU (Metal) rendering.
 */

#ifdef COEX_UI_HAS_SKIA

#include "include/core/SkCanvas.h"
#include "include/core/SkSurface.h"
#include "include/core/SkPaint.h"
#include "include/core/SkPath.h"
#include "include/core/SkFont.h"
#include "include/core/SkTypeface.h"
#include "include/core/SkImage.h"
#include "include/core/SkData.h"
#include "include/core/SkColorSpace.h"

#ifdef __APPLE__
#include "include/gpu/GrDirectContext.h"
#include "include/gpu/mtl/GrMtlTypes.h"
#include "include/gpu/mtl/GrMtlBackendContext.h"
#endif

extern "C" {
#include "coex_ui_skia.h"

#define CIMGUI_DEFINE_ENUMS_AND_STRUCTS
#ifdef COEX_UI_HAS_IMGUI
#include "cimgui.h"
#endif
}

#include <cstdio>
#include <cstdlib>
#include <cstring>

/* Global Skia state */
static struct {
    bool initialized;

    /* Software rendering */
    sk_sp<SkSurface> sw_surface;
    int sw_width;
    int sw_height;

    /* GPU rendering (Metal on macOS) */
#ifdef __APPLE__
    sk_sp<GrDirectContext> gr_context;
    sk_sp<SkSurface> gpu_surface;
#endif

    /* Font for text rendering */
    sk_sp<SkTypeface> typeface;
    SkFont font;
} _skia_state;

/* ============================================================================
 * Initialization
 * ============================================================================ */

extern "C" int64_t coex_ui_skia_init(void) {
    if (_skia_state.initialized) return 1;

    /* Load default typeface */
    _skia_state.typeface = SkTypeface::MakeDefault();
    _skia_state.font = SkFont(_skia_state.typeface, 13.0f);  /* ImGui default size */
    _skia_state.font.setSubpixel(true);
    _skia_state.font.setEdging(SkFont::Edging::kSubpixelAntiAlias);

    _skia_state.initialized = true;
    return 1;
}

extern "C" void coex_ui_skia_shutdown(void) {
    if (!_skia_state.initialized) return;

    _skia_state.sw_surface.reset();
#ifdef __APPLE__
    _skia_state.gpu_surface.reset();
    _skia_state.gr_context.reset();
#endif
    _skia_state.typeface.reset();

    _skia_state.initialized = false;
}

/* ============================================================================
 * Software Surface
 * ============================================================================ */

extern "C" void* coex_ui_skia_create_sw_surface(int64_t width, int64_t height) {
    if (!_skia_state.initialized) return nullptr;

    SkImageInfo info = SkImageInfo::MakeN32Premul(width, height);
    _skia_state.sw_surface = SkSurface::MakeRaster(info);
    _skia_state.sw_width = width;
    _skia_state.sw_height = height;

    return _skia_state.sw_surface.get();
}

extern "C" void coex_ui_skia_destroy_sw_surface(void) {
    _skia_state.sw_surface.reset();
}

extern "C" void* coex_ui_skia_get_sw_canvas(void) {
    if (!_skia_state.sw_surface) return nullptr;
    return _skia_state.sw_surface->getCanvas();
}

extern "C" void coex_ui_skia_flush_sw_surface(void* pixels_out) {
    if (!_skia_state.sw_surface || !pixels_out) return;

    SkImageInfo info = SkImageInfo::MakeN32Premul(_skia_state.sw_width, _skia_state.sw_height);
    _skia_state.sw_surface->readPixels(info, pixels_out,
        _skia_state.sw_width * 4, 0, 0);
}

/* ============================================================================
 * GPU Surface (Metal on macOS)
 * ============================================================================ */

#ifdef __APPLE__
extern "C" void* coex_ui_skia_create_gpu_context(void* metal_device, void* metal_queue) {
    if (!_skia_state.initialized) return nullptr;

    GrMtlBackendContext ctx;
    ctx.fDevice.retain((__bridge id<MTLDevice>)metal_device);
    ctx.fQueue.retain((__bridge id<MTLCommandQueue>)metal_queue);

    _skia_state.gr_context = GrDirectContext::MakeMetal(ctx);
    return _skia_state.gr_context.get();
}

extern "C" void coex_ui_skia_destroy_gpu_context(void) {
    _skia_state.gpu_surface.reset();
    _skia_state.gr_context.reset();
}

extern "C" void* coex_ui_skia_create_gpu_surface(void* metal_texture, int64_t width, int64_t height) {
    if (!_skia_state.gr_context) return nullptr;

    GrMtlTextureInfo texInfo;
    texInfo.fTexture.retain((__bridge id<MTLTexture>)metal_texture);

    GrBackendRenderTarget target(width, height, texInfo);

    _skia_state.gpu_surface = SkSurface::MakeFromBackendRenderTarget(
        _skia_state.gr_context.get(),
        target,
        kTopLeft_GrSurfaceOrigin,
        kBGRA_8888_SkColorType,
        nullptr,  /* color space */
        nullptr   /* surface props */
    );

    return _skia_state.gpu_surface.get();
}

extern "C" void coex_ui_skia_flush_gpu(void) {
    if (_skia_state.gr_context) {
        _skia_state.gr_context->flushAndSubmit();
    }
}
#endif /* __APPLE__ */

/* ============================================================================
 * ImGui Rendering
 * ============================================================================ */

#ifdef COEX_UI_HAS_IMGUI

static SkColor imgui_color_to_sk(ImU32 col) {
    return SkColorSetARGB(
        (col >> 24) & 0xFF,
        (col >> 0) & 0xFF,
        (col >> 8) & 0xFF,
        (col >> 16) & 0xFF
    );
}

static void render_draw_cmd(SkCanvas* canvas, const ImDrawVert* vertices,
                            const ImDrawIdx* indices, const ImDrawCmd* cmd,
                            SkPaint& paint) {
    /* Build path from triangles */
    for (unsigned int i = 0; i < cmd->ElemCount; i += 3) {
        ImDrawIdx idx0 = indices[i + 0];
        ImDrawIdx idx1 = indices[i + 1];
        ImDrawIdx idx2 = indices[i + 2];

        const ImDrawVert& v0 = vertices[idx0];
        const ImDrawVert& v1 = vertices[idx1];
        const ImDrawVert& v2 = vertices[idx2];

        /* Simple flat-shaded triangle (use v0 color for whole triangle) */
        paint.setColor(imgui_color_to_sk(v0.col));

        SkPath path;
        path.moveTo(v0.pos.x, v0.pos.y);
        path.lineTo(v1.pos.x, v1.pos.y);
        path.lineTo(v2.pos.x, v2.pos.y);
        path.close();

        canvas->drawPath(path, paint);
    }
}

extern "C" void coex_ui_skia_render_imgui(void* skia_canvas, void* imgui_draw_data) {
    SkCanvas* canvas = static_cast<SkCanvas*>(skia_canvas);
    ImDrawData* draw_data = static_cast<ImDrawData*>(imgui_draw_data);

    if (!canvas || !draw_data) return;
    if (draw_data->CmdListsCount == 0) return;

    /* Save canvas state */
    canvas->save();

    /* Set up clip rect from display area */
    SkRect display_rect = SkRect::MakeXYWH(
        draw_data->DisplayPos.x,
        draw_data->DisplayPos.y,
        draw_data->DisplaySize.x,
        draw_data->DisplaySize.y
    );
    canvas->clipRect(display_rect);

    /* Iterate command lists */
    for (int n = 0; n < draw_data->CmdListsCount; n++) {
        const ImDrawList* cmd_list = draw_data->CmdLists[n];
        const ImDrawVert* vtx_buffer = cmd_list->VtxBuffer.Data;
        const ImDrawIdx* idx_buffer = cmd_list->IdxBuffer.Data;

        for (int cmd_i = 0; cmd_i < cmd_list->CmdBuffer.Size; cmd_i++) {
            const ImDrawCmd* pcmd = &cmd_list->CmdBuffer[cmd_i];

            if (pcmd->UserCallback) {
                /* User callback (e.g., for custom rendering) */
                pcmd->UserCallback(cmd_list, pcmd);
            } else {
                /* Set clip rect */
                SkRect clip_rect = SkRect::MakeLTRB(
                    pcmd->ClipRect.x - draw_data->DisplayPos.x,
                    pcmd->ClipRect.y - draw_data->DisplayPos.y,
                    pcmd->ClipRect.z - draw_data->DisplayPos.x,
                    pcmd->ClipRect.w - draw_data->DisplayPos.y
                );

                canvas->save();
                canvas->clipRect(clip_rect);

                /* Render triangles */
                SkPaint paint;
                paint.setAntiAlias(true);
                paint.setStyle(SkPaint::kFill_Style);

                render_draw_cmd(canvas, vtx_buffer, idx_buffer + pcmd->IdxOffset, pcmd, paint);

                canvas->restore();
            }
        }
    }

    canvas->restore();
}

#else /* !COEX_UI_HAS_IMGUI */

extern "C" void coex_ui_skia_render_imgui(void* skia_canvas, void* imgui_draw_data) {
    (void)skia_canvas;
    (void)imgui_draw_data;
    fprintf(stderr, "coex_ui_skia_render_imgui: ImGui not available\n");
}

#endif /* COEX_UI_HAS_IMGUI */

/* ============================================================================
 * Basic Drawing Primitives
 * ============================================================================ */

extern "C" void coex_ui_skia_clear(void* skia_canvas, float r, float g, float b, float a) {
    SkCanvas* canvas = static_cast<SkCanvas*>(skia_canvas);
    if (!canvas) return;

    canvas->clear(SkColorSetARGB(
        (uint8_t)(a * 255),
        (uint8_t)(r * 255),
        (uint8_t)(g * 255),
        (uint8_t)(b * 255)
    ));
}

extern "C" void coex_ui_skia_draw_rect(void* skia_canvas,
                                        double x, double y, double w, double h,
                                        float r, float g, float b, float a) {
    SkCanvas* canvas = static_cast<SkCanvas*>(skia_canvas);
    if (!canvas) return;

    SkPaint paint;
    paint.setColor(SkColorSetARGB(
        (uint8_t)(a * 255),
        (uint8_t)(r * 255),
        (uint8_t)(g * 255),
        (uint8_t)(b * 255)
    ));
    paint.setStyle(SkPaint::kFill_Style);
    paint.setAntiAlias(true);

    canvas->drawRect(SkRect::MakeXYWH(x, y, w, h), paint);
}

extern "C" void coex_ui_skia_draw_rounded_rect(void* skia_canvas,
                                                double x, double y, double w, double h,
                                                double radius,
                                                float r, float g, float b, float a) {
    SkCanvas* canvas = static_cast<SkCanvas*>(skia_canvas);
    if (!canvas) return;

    SkPaint paint;
    paint.setColor(SkColorSetARGB(
        (uint8_t)(a * 255),
        (uint8_t)(r * 255),
        (uint8_t)(g * 255),
        (uint8_t)(b * 255)
    ));
    paint.setStyle(SkPaint::kFill_Style);
    paint.setAntiAlias(true);

    canvas->drawRoundRect(SkRect::MakeXYWH(x, y, w, h), radius, radius, paint);
}

extern "C" void coex_ui_skia_draw_circle(void* skia_canvas,
                                          double cx, double cy, double radius,
                                          float r, float g, float b, float a) {
    SkCanvas* canvas = static_cast<SkCanvas*>(skia_canvas);
    if (!canvas) return;

    SkPaint paint;
    paint.setColor(SkColorSetARGB(
        (uint8_t)(a * 255),
        (uint8_t)(r * 255),
        (uint8_t)(g * 255),
        (uint8_t)(b * 255)
    ));
    paint.setStyle(SkPaint::kFill_Style);
    paint.setAntiAlias(true);

    canvas->drawCircle(cx, cy, radius, paint);
}

extern "C" void coex_ui_skia_draw_line(void* skia_canvas,
                                        double x1, double y1, double x2, double y2,
                                        double stroke_width,
                                        float r, float g, float b, float a) {
    SkCanvas* canvas = static_cast<SkCanvas*>(skia_canvas);
    if (!canvas) return;

    SkPaint paint;
    paint.setColor(SkColorSetARGB(
        (uint8_t)(a * 255),
        (uint8_t)(r * 255),
        (uint8_t)(g * 255),
        (uint8_t)(b * 255)
    ));
    paint.setStyle(SkPaint::kStroke_Style);
    paint.setStrokeWidth(stroke_width);
    paint.setAntiAlias(true);

    canvas->drawLine(x1, y1, x2, y2, paint);
}

extern "C" void coex_ui_skia_draw_text(void* skia_canvas,
                                        const char* text, double x, double y,
                                        float r, float g, float b, float a) {
    SkCanvas* canvas = static_cast<SkCanvas*>(skia_canvas);
    if (!canvas || !text) return;

    SkPaint paint;
    paint.setColor(SkColorSetARGB(
        (uint8_t)(a * 255),
        (uint8_t)(r * 255),
        (uint8_t)(g * 255),
        (uint8_t)(b * 255)
    ));
    paint.setAntiAlias(true);

    canvas->drawString(text, x, y, _skia_state.font, paint);
}

#else /* !COEX_UI_HAS_SKIA */

/* Stub implementations when Skia is not available */

#include <cstdio>
#include <cstdint>
#include <cstdlib>

extern "C" {

int64_t coex_ui_skia_init(void) {
    fprintf(stderr, "coex_ui_skia_init: Skia not available\n");
    return 0;
}

void coex_ui_skia_shutdown(void) {}

void* coex_ui_skia_create_sw_surface(int64_t width, int64_t height) {
    (void)width; (void)height;
    return NULL;
}

void coex_ui_skia_destroy_sw_surface(void) {}

void* coex_ui_skia_get_sw_canvas(void) { return NULL; }

void coex_ui_skia_flush_sw_surface(void* pixels_out) { (void)pixels_out; }

void coex_ui_skia_render_imgui(void* skia_canvas, void* imgui_draw_data) {
    (void)skia_canvas; (void)imgui_draw_data;
}

void coex_ui_skia_clear(void* skia_canvas, float r, float g, float b, float a) {
    (void)skia_canvas; (void)r; (void)g; (void)b; (void)a;
}

void coex_ui_skia_draw_rect(void* skia_canvas,
                             double x, double y, double w, double h,
                             float r, float g, float b, float a) {
    (void)skia_canvas; (void)x; (void)y; (void)w; (void)h;
    (void)r; (void)g; (void)b; (void)a;
}

void coex_ui_skia_draw_rounded_rect(void* skia_canvas,
                                     double x, double y, double w, double h,
                                     double radius,
                                     float r, float g, float b, float a) {
    (void)skia_canvas; (void)x; (void)y; (void)w; (void)h;
    (void)radius; (void)r; (void)g; (void)b; (void)a;
}

void coex_ui_skia_draw_circle(void* skia_canvas,
                               double cx, double cy, double radius,
                               float r, float g, float b, float a) {
    (void)skia_canvas; (void)cx; (void)cy; (void)radius;
    (void)r; (void)g; (void)b; (void)a;
}

void coex_ui_skia_draw_line(void* skia_canvas,
                             double x1, double y1, double x2, double y2,
                             double stroke_width,
                             float r, float g, float b, float a) {
    (void)skia_canvas; (void)x1; (void)y1; (void)x2; (void)y2;
    (void)stroke_width; (void)r; (void)g; (void)b; (void)a;
}

void coex_ui_skia_draw_text(void* skia_canvas,
                             const char* text, double x, double y,
                             float r, float g, float b, float a) {
    (void)skia_canvas; (void)text; (void)x; (void)y;
    (void)r; (void)g; (void)b; (void)a;
}

} /* extern "C" */

#endif /* COEX_UI_HAS_SKIA */
