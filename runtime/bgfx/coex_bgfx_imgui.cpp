/**
 * Coex bgfx ImGui Bridge
 *
 * Renders ImGui draw data via bgfx transient buffers on view 255.
 * This replaces the Metal/OpenGL ImGui backend when bgfx is active.
 *
 * View 255 (highest) renders last, so ImGui overlays everything.
 */

#include "coex_bgfx.h"

#include <bgfx/bgfx.h>
#include <bgfx/embedded_shader.h>

#include <stdio.h>
#include <string.h>

#ifdef COEX_UI_HAS_IMGUI
/* Use imgui.h directly in C++ (not cimgui.h which is the C wrapper) */
#include "imgui.h"

/* ImGui bgfx view ID - highest view renders last (on top) */
#define IMGUI_VIEW_ID 255

/* Internal state */
static struct {
    bgfx::TextureHandle     font_texture;
    bgfx::UniformHandle     font_uniform;
    bgfx::ProgramHandle     program;
    bgfx::VertexLayout      layout;
    int                      initialized;
} s_imgui_bgfx;

/* Simple embedded ImGui shaders would go here.
 * For now, we provide the structure but shaders must be loaded from .bin files.
 * In production, these would be compiled with shaderc for each backend. */

extern "C" {

/**
 * Initialize ImGui rendering with bgfx.
 * Call after bgfx_bridge_init() and after ImGui context is created.
 *
 * @param vs_path  Path to vertex shader .bin
 * @param fs_path  Path to fragment shader .bin
 * @return 1 on success, 0 on failure
 */
int coex_bgfx_imgui_init(const char* vs_path, const char* fs_path) {
    if (s_imgui_bgfx.initialized) return 1;

    /* Set up vertex layout matching ImDrawVert */
    s_imgui_bgfx.layout
        .begin()
        .add(bgfx::Attrib::Position,  2, bgfx::AttribType::Float)
        .add(bgfx::Attrib::TexCoord0, 2, bgfx::AttribType::Float)
        .add(bgfx::Attrib::Color0,    4, bgfx::AttribType::Uint8, true)
        .end();

    /* Create font texture from ImGui atlas */
    ImGuiIO& io = ImGui::GetIO();
    unsigned char* pixels;
    int width, height;
    io.Fonts->GetTexDataAsRGBA32(&pixels, &width, &height);

    s_imgui_bgfx.font_texture = bgfx::createTexture2D(
        (uint16_t)width, (uint16_t)height, false, 1,
        bgfx::TextureFormat::BGRA8, 0,
        bgfx::copy(pixels, (uint32_t)(width * height * 4)));

    if (!bgfx::isValid(s_imgui_bgfx.font_texture)) {
        fprintf(stderr, "coex_bgfx_imgui_init: failed to create font texture\n");
        return 0;
    }

    /* Create sampler uniform */
    s_imgui_bgfx.font_uniform = bgfx::createUniform(
        "s_tex", bgfx::UniformType::Sampler);

    /* Load shaders if paths provided */
    if (vs_path && fs_path) {
        bgfx::ShaderHandle vs = BGFX_INVALID_HANDLE;
        bgfx::ShaderHandle fs = BGFX_INVALID_HANDLE;

        /* Load vertex shader */
        FILE* f = fopen(vs_path, "rb");
        if (f) {
            fseek(f, 0, SEEK_END);
            long size = ftell(f);
            fseek(f, 0, SEEK_SET);
            if (size > 0) {
                const bgfx::Memory* mem = bgfx::alloc((uint32_t)size + 1);
                fread(mem->data, 1, (size_t)size, f);
                mem->data[size] = '\0';
                vs = bgfx::createShader(mem);
            }
            fclose(f);
        }

        /* Load fragment shader */
        f = fopen(fs_path, "rb");
        if (f) {
            fseek(f, 0, SEEK_END);
            long size = ftell(f);
            fseek(f, 0, SEEK_SET);
            if (size > 0) {
                const bgfx::Memory* mem = bgfx::alloc((uint32_t)size + 1);
                fread(mem->data, 1, (size_t)size, f);
                mem->data[size] = '\0';
                fs = bgfx::createShader(mem);
            }
            fclose(f);
        }

        if (bgfx::isValid(vs) && bgfx::isValid(fs)) {
            s_imgui_bgfx.program = bgfx::createProgram(vs, fs, true);
        } else {
            if (bgfx::isValid(vs)) bgfx::destroy(vs);
            if (bgfx::isValid(fs)) bgfx::destroy(fs);
            fprintf(stderr, "coex_bgfx_imgui_init: failed to load shaders\n");
            /* Continue without shaders - ImGui won't render but bgfx still works */
        }
    }

    /* Set ImGui font texture ID */
    io.Fonts->TexID = (ImTextureID)(intptr_t)s_imgui_bgfx.font_texture.idx;

    /* Configure view 255 for ImGui */
    bgfx::setViewRect(IMGUI_VIEW_ID, 0, 0, bgfx::BackbufferRatio::Equal);
    bgfx::setViewMode(IMGUI_VIEW_ID, bgfx::ViewMode::Sequential);

    s_imgui_bgfx.initialized = 1;
    return 1;
}

/**
 * Render ImGui draw data via bgfx.
 * Call after igRender() and before bgfx::frame().
 */
void coex_bgfx_imgui_render(void) {
    if (!s_imgui_bgfx.initialized) return;
    if (!bgfx::isValid(s_imgui_bgfx.program)) return;

    ImDrawData* draw_data = ImGui::GetDrawData();
    if (!draw_data || draw_data->CmdListsCount == 0) return;

    /* Set up orthographic projection for ImGui */
    float ortho[16];
    float L = draw_data->DisplayPos.x;
    float R = draw_data->DisplayPos.x + draw_data->DisplaySize.x;
    float T = draw_data->DisplayPos.y;
    float B = draw_data->DisplayPos.y + draw_data->DisplaySize.y;

    const bgfx::Caps* caps = bgfx::getCaps();
    float depth_offset = caps->homogeneousDepth ? -1.0f : 0.0f;

    memset(ortho, 0, sizeof(ortho));
    ortho[0]  = 2.0f / (R - L);
    ortho[5]  = 2.0f / (T - B);
    ortho[10] = caps->homogeneousDepth ? -1.0f / (1.0f - depth_offset) : 0.5f;
    ortho[12] = (L + R) / (L - R);
    ortho[13] = (T + B) / (B - T);
    ortho[14] = caps->homogeneousDepth ? depth_offset / (1.0f - depth_offset) : 0.5f;
    ortho[15] = 1.0f;

    bgfx::setViewTransform(IMGUI_VIEW_ID, NULL, ortho);
    bgfx::setViewRect(IMGUI_VIEW_ID, 0, 0,
                       (uint16_t)draw_data->DisplaySize.x,
                       (uint16_t)draw_data->DisplaySize.y);

    ImVec2 clip_off = draw_data->DisplayPos;

    for (int n = 0; n < draw_data->CmdListsCount; n++) {
        const ImDrawList* cmd_list = draw_data->CmdLists[n];

        /* Allocate transient buffers */
        uint32_t num_vertices = (uint32_t)cmd_list->VtxBuffer.Size;
        uint32_t num_indices = (uint32_t)cmd_list->IdxBuffer.Size;

        if (bgfx::getAvailTransientVertexBuffer(num_vertices, s_imgui_bgfx.layout) < num_vertices ||
            bgfx::getAvailTransientIndexBuffer(num_indices, sizeof(ImDrawIdx) == 4) < num_indices) {
            continue;
        }

        bgfx::TransientVertexBuffer tvb;
        bgfx::TransientIndexBuffer tib;
        bgfx::allocTransientVertexBuffer(&tvb, num_vertices, s_imgui_bgfx.layout);
        bgfx::allocTransientIndexBuffer(&tib, num_indices, sizeof(ImDrawIdx) == 4);

        memcpy(tvb.data, cmd_list->VtxBuffer.Data, num_vertices * sizeof(ImDrawVert));
        memcpy(tib.data, cmd_list->IdxBuffer.Data, num_indices * sizeof(ImDrawIdx));

        uint32_t offset = 0;
        for (int cmd_i = 0; cmd_i < cmd_list->CmdBuffer.Size; cmd_i++) {
            const ImDrawCmd* cmd = &cmd_list->CmdBuffer.Data[cmd_i];

            if (cmd->UserCallback) {
                cmd->UserCallback(cmd_list, cmd);
                continue;
            }

            /* Scissor rect */
            float clip_x = cmd->ClipRect.x - clip_off.x;
            float clip_y = cmd->ClipRect.y - clip_off.y;
            float clip_w = cmd->ClipRect.z - cmd->ClipRect.x;
            float clip_h = cmd->ClipRect.w - cmd->ClipRect.y;

            if (clip_w <= 0.0f || clip_h <= 0.0f) {
                offset += cmd->ElemCount;
                continue;
            }

            bgfx::setScissor(
                (uint16_t)clip_x, (uint16_t)clip_y,
                (uint16_t)clip_w, (uint16_t)clip_h);

            /* Set texture */
            bgfx::TextureHandle th = {(uint16_t)(intptr_t)cmd->GetTexID()};
            bgfx::setTexture(0, s_imgui_bgfx.font_uniform, th);

            /* Set state: alpha blending, no depth test, no culling */
            uint64_t state = 0
                | BGFX_STATE_WRITE_RGB
                | BGFX_STATE_WRITE_A
                | BGFX_STATE_BLEND_FUNC(BGFX_STATE_BLEND_SRC_ALPHA,
                                          BGFX_STATE_BLEND_INV_SRC_ALPHA)
                | BGFX_STATE_MSAA;
            bgfx::setState(state);

            /* Set buffers and submit */
            bgfx::setVertexBuffer(0, &tvb, 0, num_vertices);
            bgfx::setIndexBuffer(&tib, offset, cmd->ElemCount);
            bgfx::submit(IMGUI_VIEW_ID, s_imgui_bgfx.program);

            offset += cmd->ElemCount;
        }
    }
}

/**
 * Shut down ImGui bgfx rendering.
 */
void coex_bgfx_imgui_shutdown(void) {
    if (!s_imgui_bgfx.initialized) return;

    if (bgfx::isValid(s_imgui_bgfx.font_texture))
        bgfx::destroy(s_imgui_bgfx.font_texture);
    if (bgfx::isValid(s_imgui_bgfx.font_uniform))
        bgfx::destroy(s_imgui_bgfx.font_uniform);
    if (bgfx::isValid(s_imgui_bgfx.program))
        bgfx::destroy(s_imgui_bgfx.program);

    s_imgui_bgfx.initialized = 0;
}

}  /* extern "C" */

#else /* !COEX_UI_HAS_IMGUI */

/* Stubs when ImGui is not available */
extern "C" {
int  coex_bgfx_imgui_init(const char*, const char*) { return 0; }
void coex_bgfx_imgui_render(void) {}
void coex_bgfx_imgui_shutdown(void) {}
}

#endif /* COEX_UI_HAS_IMGUI */
