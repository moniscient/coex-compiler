/**
 * Coex UI OpenGL Renderer Implementation
 *
 * Renders Dear ImGui draw data using OpenGL 3.3 Core Profile.
 * Based on the standard ImGui OpenGL3 backend pattern.
 */

#include "coex_ui_opengl.h"
#include <stdio.h>
#include <string.h>
#include <stdlib.h>

/* OpenGL headers - use GLAD or similar loader in production */
#ifdef COEX_UI_HAS_OPENGL
#define GL_GLEXT_PROTOTYPES
#include <GL/gl.h>
#include <GL/glext.h>
#endif

/* Include cimgui if available */
#ifdef COEX_UI_HAS_IMGUI
#define CIMGUI_DEFINE_ENUMS_AND_STRUCTS
#include "cimgui.h"
#endif

/* Vertex shader source */
static const char* _vertex_shader_source =
    "#version 330 core\n"
    "layout (location = 0) in vec2 aPos;\n"
    "layout (location = 1) in vec2 aTexCoord;\n"
    "layout (location = 2) in vec4 aColor;\n"
    "out vec2 TexCoord;\n"
    "out vec4 Color;\n"
    "uniform mat4 uProjection;\n"
    "void main() {\n"
    "    gl_Position = uProjection * vec4(aPos, 0.0, 1.0);\n"
    "    TexCoord = aTexCoord;\n"
    "    Color = aColor;\n"
    "}\n";

/* Fragment shader source */
static const char* _fragment_shader_source =
    "#version 330 core\n"
    "in vec2 TexCoord;\n"
    "in vec4 Color;\n"
    "out vec4 FragColor;\n"
    "uniform sampler2D uTexture;\n"
    "void main() {\n"
    "    FragColor = Color * texture(uTexture, TexCoord);\n"
    "}\n";

/* Global renderer state */
static struct {
    int initialized;

#ifdef COEX_UI_HAS_OPENGL
    GLuint shader_program;
    GLuint vao;
    GLuint vbo;
    GLuint ebo;
    GLuint font_texture;

    GLint projection_loc;
    GLint texture_loc;

    GLsizei vbo_size;
    GLsizei ebo_size;
#endif
} _renderer;

#ifdef COEX_UI_HAS_OPENGL

/* Compile a shader and check for errors */
static GLuint compile_shader(GLenum type, const char* source) {
    GLuint shader = glCreateShader(type);
    glShaderSource(shader, 1, &source, NULL);
    glCompileShader(shader);

    GLint success;
    glGetShaderiv(shader, GL_COMPILE_STATUS, &success);
    if (!success) {
        char log[512];
        glGetShaderInfoLog(shader, sizeof(log), NULL, log);
        fprintf(stderr, "Shader compilation error: %s\n", log);
        glDeleteShader(shader);
        return 0;
    }
    return shader;
}

/* Link shader program and check for errors */
static GLuint link_program(GLuint vertex, GLuint fragment) {
    GLuint program = glCreateProgram();
    glAttachShader(program, vertex);
    glAttachShader(program, fragment);
    glLinkProgram(program);

    GLint success;
    glGetProgramiv(program, GL_LINK_STATUS, &success);
    if (!success) {
        char log[512];
        glGetProgramInfoLog(program, sizeof(log), NULL, log);
        fprintf(stderr, "Program link error: %s\n", log);
        glDeleteProgram(program);
        return 0;
    }
    return program;
}

#endif /* COEX_UI_HAS_OPENGL */

/* ============================================================================
 * Initialization
 * ============================================================================ */

int64_t coex_ui_opengl_init(void) {
#ifdef COEX_UI_HAS_OPENGL
    if (_renderer.initialized) return 1;

    memset(&_renderer, 0, sizeof(_renderer));

    /* Compile shaders */
    GLuint vertex_shader = compile_shader(GL_VERTEX_SHADER, _vertex_shader_source);
    if (!vertex_shader) return 0;

    GLuint fragment_shader = compile_shader(GL_FRAGMENT_SHADER, _fragment_shader_source);
    if (!fragment_shader) {
        glDeleteShader(vertex_shader);
        return 0;
    }

    /* Link program */
    _renderer.shader_program = link_program(vertex_shader, fragment_shader);
    glDeleteShader(vertex_shader);
    glDeleteShader(fragment_shader);

    if (!_renderer.shader_program) return 0;

    /* Get uniform locations */
    _renderer.projection_loc = glGetUniformLocation(_renderer.shader_program, "uProjection");
    _renderer.texture_loc = glGetUniformLocation(_renderer.shader_program, "uTexture");

    /* Create VAO, VBO, EBO */
    glGenVertexArrays(1, &_renderer.vao);
    glGenBuffers(1, &_renderer.vbo);
    glGenBuffers(1, &_renderer.ebo);

    glBindVertexArray(_renderer.vao);
    glBindBuffer(GL_ARRAY_BUFFER, _renderer.vbo);
    glBindBuffer(GL_ELEMENT_ARRAY_BUFFER, _renderer.ebo);

    /* Setup vertex attributes matching ImDrawVert:
     * - pos: float2 at offset 0
     * - uv: float2 at offset 8
     * - col: uint32 at offset 16 (as 4 normalized unsigned bytes)
     * Total stride: 20 bytes
     */
    glEnableVertexAttribArray(0);
    glVertexAttribPointer(0, 2, GL_FLOAT, GL_FALSE, 20, (void*)0);

    glEnableVertexAttribArray(1);
    glVertexAttribPointer(1, 2, GL_FLOAT, GL_FALSE, 20, (void*)8);

    glEnableVertexAttribArray(2);
    glVertexAttribPointer(2, 4, GL_UNSIGNED_BYTE, GL_TRUE, 20, (void*)16);

    glBindVertexArray(0);

    _renderer.initialized = 1;
    return 1;
#else
    fprintf(stderr, "coex_ui_opengl_init: OpenGL not available\n");
    return 0;
#endif
}

void coex_ui_opengl_shutdown(void) {
#ifdef COEX_UI_HAS_OPENGL
    if (!_renderer.initialized) return;

    if (_renderer.font_texture) {
        glDeleteTextures(1, &_renderer.font_texture);
    }
    if (_renderer.vbo) {
        glDeleteBuffers(1, &_renderer.vbo);
    }
    if (_renderer.ebo) {
        glDeleteBuffers(1, &_renderer.ebo);
    }
    if (_renderer.vao) {
        glDeleteVertexArrays(1, &_renderer.vao);
    }
    if (_renderer.shader_program) {
        glDeleteProgram(_renderer.shader_program);
    }

    memset(&_renderer, 0, sizeof(_renderer));
#endif
}

/* ============================================================================
 * Font Texture
 * ============================================================================ */

int64_t coex_ui_opengl_create_fonts_texture(void) {
#if defined(COEX_UI_HAS_IMGUI) && defined(COEX_UI_HAS_OPENGL)
    if (!_renderer.initialized) return 0;

    ImGuiIO* io = igGetIO_Nil();

    /* Get font texture data from the TexData member */
    ImTextureData* texData = io->Fonts->TexData;
    if (!texData || !texData->Pixels) {
        fprintf(stderr, "coex_ui_opengl_create_fonts_texture: No font texture data available\n");
        return 0;
    }

    int width = texData->Width;
    int height = texData->Height;
    unsigned char* pixels = texData->Pixels;
    int bytesPerPixel = texData->BytesPerPixel;

    /* Create OpenGL texture */
    glGenTextures(1, &_renderer.font_texture);
    glBindTexture(GL_TEXTURE_2D, _renderer.font_texture);

    /* Set texture parameters */
    glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MIN_FILTER, GL_LINEAR);
    glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MAG_FILTER, GL_LINEAR);
    glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_WRAP_S, GL_CLAMP_TO_EDGE);
    glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_WRAP_T, GL_CLAMP_TO_EDGE);

    /* Upload texture data */
    if (bytesPerPixel == 4) {
        glTexImage2D(GL_TEXTURE_2D, 0, GL_RGBA, width, height, 0, GL_RGBA, GL_UNSIGNED_BYTE, pixels);
    } else if (bytesPerPixel == 1) {
        glTexImage2D(GL_TEXTURE_2D, 0, GL_RED, width, height, 0, GL_RED, GL_UNSIGNED_BYTE, pixels);
        /* Swizzle for alpha-only textures */
        GLint swizzle[] = { GL_ONE, GL_ONE, GL_ONE, GL_RED };
        glTexParameteriv(GL_TEXTURE_2D, GL_TEXTURE_SWIZZLE_RGBA, swizzle);
    }

    glBindTexture(GL_TEXTURE_2D, 0);

    /* Store texture ID in ImGui */
    ImTextureData_SetTexID(texData, (ImTextureID)(uintptr_t)_renderer.font_texture);

    return 1;
#else
    return 0;
#endif
}

void coex_ui_opengl_invalidate_fonts_texture(void) {
#if defined(COEX_UI_HAS_IMGUI) && defined(COEX_UI_HAS_OPENGL)
    if (_renderer.font_texture) {
        glDeleteTextures(1, &_renderer.font_texture);
        _renderer.font_texture = 0;
    }
    ImGuiIO* io = igGetIO_Nil();
    if (io->Fonts->TexData) {
        ImTextureData_SetTexID(io->Fonts->TexData, (ImTextureID)0);
    }
#endif
}

/* ============================================================================
 * Rendering
 * ============================================================================ */

void coex_ui_opengl_render(
    void* imgui_draw_data,
    int64_t framebuffer_width,
    int64_t framebuffer_height
) {
#if defined(COEX_UI_HAS_IMGUI) && defined(COEX_UI_HAS_OPENGL)
    if (!_renderer.initialized) return;
    if (!imgui_draw_data) return;

    ImDrawData* draw_data = (ImDrawData*)imgui_draw_data;

    /* Avoid rendering if minimized */
    if (draw_data->DisplaySize.x <= 0 || draw_data->DisplaySize.y <= 0) return;
    if (draw_data->TotalVtxCount == 0) return;

    /* Save OpenGL state */
    GLint last_program; glGetIntegerv(GL_CURRENT_PROGRAM, &last_program);
    GLint last_texture; glGetIntegerv(GL_TEXTURE_BINDING_2D, &last_texture);
    GLint last_array_buffer; glGetIntegerv(GL_ARRAY_BUFFER_BINDING, &last_array_buffer);
    GLint last_element_array_buffer; glGetIntegerv(GL_ELEMENT_ARRAY_BUFFER_BINDING, &last_element_array_buffer);
    GLint last_vertex_array; glGetIntegerv(GL_VERTEX_ARRAY_BINDING, &last_vertex_array);
    GLint last_viewport[4]; glGetIntegerv(GL_VIEWPORT, last_viewport);
    GLint last_scissor_box[4]; glGetIntegerv(GL_SCISSOR_BOX, last_scissor_box);
    GLboolean last_blend = glIsEnabled(GL_BLEND);
    GLboolean last_cull_face = glIsEnabled(GL_CULL_FACE);
    GLboolean last_depth_test = glIsEnabled(GL_DEPTH_TEST);
    GLboolean last_scissor_test = glIsEnabled(GL_SCISSOR_TEST);

    /* Setup render state */
    glEnable(GL_BLEND);
    glBlendEquation(GL_FUNC_ADD);
    glBlendFuncSeparate(GL_SRC_ALPHA, GL_ONE_MINUS_SRC_ALPHA, GL_ONE, GL_ONE_MINUS_SRC_ALPHA);
    glDisable(GL_CULL_FACE);
    glDisable(GL_DEPTH_TEST);
    glEnable(GL_SCISSOR_TEST);

    /* Setup viewport */
    glViewport(0, 0, (GLsizei)framebuffer_width, (GLsizei)framebuffer_height);

    /* Setup orthographic projection matrix */
    float L = draw_data->DisplayPos.x;
    float R = draw_data->DisplayPos.x + draw_data->DisplaySize.x;
    float T = draw_data->DisplayPos.y;
    float B = draw_data->DisplayPos.y + draw_data->DisplaySize.y;

    float projection[4][4] = {
        { 2.0f / (R - L),     0.0f,              0.0f, 0.0f },
        { 0.0f,               2.0f / (T - B),    0.0f, 0.0f },
        { 0.0f,               0.0f,             -1.0f, 0.0f },
        { (R + L) / (L - R),  (T + B) / (B - T), 0.0f, 1.0f }
    };

    /* Use shader program */
    glUseProgram(_renderer.shader_program);
    glUniformMatrix4fv(_renderer.projection_loc, 1, GL_FALSE, &projection[0][0]);
    glUniform1i(_renderer.texture_loc, 0);

    glBindVertexArray(_renderer.vao);

    /* Grow buffers if needed */
    GLsizei vertex_size = draw_data->TotalVtxCount * sizeof(ImDrawVert);
    GLsizei index_size = draw_data->TotalIdxCount * sizeof(ImDrawIdx);

    if (vertex_size > _renderer.vbo_size) {
        _renderer.vbo_size = vertex_size + 10000 * sizeof(ImDrawVert);
        glBindBuffer(GL_ARRAY_BUFFER, _renderer.vbo);
        glBufferData(GL_ARRAY_BUFFER, _renderer.vbo_size, NULL, GL_STREAM_DRAW);
    }

    if (index_size > _renderer.ebo_size) {
        _renderer.ebo_size = index_size + 10000 * sizeof(ImDrawIdx);
        glBindBuffer(GL_ELEMENT_ARRAY_BUFFER, _renderer.ebo);
        glBufferData(GL_ELEMENT_ARRAY_BUFFER, _renderer.ebo_size, NULL, GL_STREAM_DRAW);
    }

    /* Upload vertex/index data */
    glBindBuffer(GL_ARRAY_BUFFER, _renderer.vbo);
    glBindBuffer(GL_ELEMENT_ARRAY_BUFFER, _renderer.ebo);

    ImDrawVert* vtxDst = (ImDrawVert*)glMapBuffer(GL_ARRAY_BUFFER, GL_WRITE_ONLY);
    ImDrawIdx* idxDst = (ImDrawIdx*)glMapBuffer(GL_ELEMENT_ARRAY_BUFFER, GL_WRITE_ONLY);

    if (vtxDst && idxDst) {
        for (int n = 0; n < draw_data->CmdListsCount; n++) {
            const ImDrawList* cmdList = draw_data->CmdLists.Data[n];
            memcpy(vtxDst, cmdList->VtxBuffer.Data, cmdList->VtxBuffer.Size * sizeof(ImDrawVert));
            memcpy(idxDst, cmdList->IdxBuffer.Data, cmdList->IdxBuffer.Size * sizeof(ImDrawIdx));
            vtxDst += cmdList->VtxBuffer.Size;
            idxDst += cmdList->IdxBuffer.Size;
        }
    }

    glUnmapBuffer(GL_ARRAY_BUFFER);
    glUnmapBuffer(GL_ELEMENT_ARRAY_BUFFER);

    /* Render draw lists */
    ImVec2 clipOff = draw_data->DisplayPos;
    ImVec2 clipScale = draw_data->FramebufferScale;

    unsigned int vertexOffset = 0;
    unsigned int indexOffset = 0;

    for (int n = 0; n < draw_data->CmdListsCount; n++) {
        const ImDrawList* cmdList = draw_data->CmdLists.Data[n];

        for (int cmd_i = 0; cmd_i < cmdList->CmdBuffer.Size; cmd_i++) {
            ImDrawCmd* pcmd = &cmdList->CmdBuffer.Data[cmd_i];

            if (pcmd->UserCallback) {
                /* User callback - skip for now */
                continue;
            }

            /* Calculate scissor rect */
            float clipMinX = (pcmd->ClipRect.x - clipOff.x) * clipScale.x;
            float clipMinY = (pcmd->ClipRect.y - clipOff.y) * clipScale.y;
            float clipMaxX = (pcmd->ClipRect.z - clipOff.x) * clipScale.x;
            float clipMaxY = (pcmd->ClipRect.w - clipOff.y) * clipScale.y;

            /* Clamp to framebuffer */
            if (clipMinX < 0) clipMinX = 0;
            if (clipMinY < 0) clipMinY = 0;
            if (clipMaxX > framebuffer_width) clipMaxX = framebuffer_width;
            if (clipMaxY > framebuffer_height) clipMaxY = framebuffer_height;
            if (clipMaxX <= clipMinX || clipMaxY <= clipMinY) continue;

            /* Apply scissor (note: OpenGL has origin at bottom-left) */
            glScissor(
                (GLint)clipMinX,
                (GLint)(framebuffer_height - clipMaxY),
                (GLsizei)(clipMaxX - clipMinX),
                (GLsizei)(clipMaxY - clipMinY)
            );

            /* Bind texture */
            ImTextureID texId = ImDrawCmd_GetTexID(pcmd);
            GLuint texture = (GLuint)(uintptr_t)texId;
            glBindTexture(GL_TEXTURE_2D, texture);

            /* Draw */
            glDrawElementsBaseVertex(
                GL_TRIANGLES,
                (GLsizei)pcmd->ElemCount,
                sizeof(ImDrawIdx) == 2 ? GL_UNSIGNED_SHORT : GL_UNSIGNED_INT,
                (void*)(uintptr_t)((indexOffset + pcmd->IdxOffset) * sizeof(ImDrawIdx)),
                (GLint)(vertexOffset + pcmd->VtxOffset)
            );
        }

        vertexOffset += cmdList->VtxBuffer.Size;
        indexOffset += cmdList->IdxBuffer.Size;
    }

    /* Restore OpenGL state */
    glUseProgram(last_program);
    glBindTexture(GL_TEXTURE_2D, last_texture);
    glBindBuffer(GL_ARRAY_BUFFER, last_array_buffer);
    glBindBuffer(GL_ELEMENT_ARRAY_BUFFER, last_element_array_buffer);
    glBindVertexArray(last_vertex_array);
    glViewport(last_viewport[0], last_viewport[1], last_viewport[2], last_viewport[3]);
    glScissor(last_scissor_box[0], last_scissor_box[1], last_scissor_box[2], last_scissor_box[3]);
    if (last_blend) glEnable(GL_BLEND); else glDisable(GL_BLEND);
    if (last_cull_face) glEnable(GL_CULL_FACE); else glDisable(GL_CULL_FACE);
    if (last_depth_test) glEnable(GL_DEPTH_TEST); else glDisable(GL_DEPTH_TEST);
    if (last_scissor_test) glEnable(GL_SCISSOR_TEST); else glDisable(GL_SCISSOR_TEST);
#else
    (void)imgui_draw_data;
    (void)framebuffer_width;
    (void)framebuffer_height;
#endif
}
