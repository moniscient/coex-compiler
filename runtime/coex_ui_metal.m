/**
 * Coex UI Metal Renderer Implementation
 *
 * Renders Dear ImGui draw data directly using Metal.
 * Based on the standard ImGui Metal backend pattern.
 */

#import <Metal/Metal.h>
#import <simd/simd.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>

#include "coex_ui_metal.h"
#include "coex_ui_imgui.h"

/* Include cimgui if available */
#ifdef COEX_UI_HAS_IMGUI
#define CIMGUI_DEFINE_ENUMS_AND_STRUCTS
#include "cimgui.h"
#endif

/* Metal shader source */
static const char* _metal_shader_source =
    "#include <metal_stdlib>\n"
    "using namespace metal;\n"
    "\n"
    "struct Uniforms {\n"
    "    float4x4 projectionMatrix;\n"
    "};\n"
    "\n"
    "struct VertexIn {\n"
    "    float2 position [[attribute(0)]];\n"
    "    float2 texCoord [[attribute(1)]];\n"
    "    uchar4 color    [[attribute(2)]];\n"
    "};\n"
    "\n"
    "struct VertexOut {\n"
    "    float4 position [[position]];\n"
    "    float2 texCoord;\n"
    "    float4 color;\n"
    "};\n"
    "\n"
    "vertex VertexOut vertex_main(VertexIn in [[stage_in]],\n"
    "                             constant Uniforms& uniforms [[buffer(1)]]) {\n"
    "    VertexOut out;\n"
    "    out.position = uniforms.projectionMatrix * float4(in.position, 0.0, 1.0);\n"
    "    out.texCoord = in.texCoord;\n"
    "    out.color = float4(in.color) / 255.0;\n"
    "    return out;\n"
    "}\n"
    "\n"
    "fragment float4 fragment_main(VertexOut in [[stage_in]],\n"
    "                              texture2d<float> tex [[texture(0)]],\n"
    "                              sampler samp [[sampler(0)]]) {\n"
    "    return in.color * tex.sample(samp, in.texCoord);\n"
    "}\n";

/* Uniform buffer structure (must match shader) */
typedef struct {
    simd_float4x4 projectionMatrix;
} MetalUniforms;

/* Global renderer state */
static struct {
    int initialized;

    id<MTLDevice> device;
    id<MTLRenderPipelineState> pipeline;
    id<MTLDepthStencilState> depthStencil;
    id<MTLSamplerState> sampler;
    id<MTLTexture> fontTexture;

    id<MTLBuffer> vertexBuffer;
    id<MTLBuffer> indexBuffer;
    id<MTLBuffer> uniformBuffer;

    NSUInteger vertexBufferSize;
    NSUInteger indexBufferSize;
} _renderer;

/* ============================================================================
 * Initialization
 * ============================================================================ */

int64_t coex_ui_metal_init(void* metal_device) {
    if (_renderer.initialized) return 1;
    if (!metal_device) return 0;

    memset((void*)&_renderer, 0, sizeof(_renderer));
    _renderer.device = (__bridge id<MTLDevice>)metal_device;

    @autoreleasepool {
        NSError* error = nil;

        /* Compile shaders */
        id<MTLLibrary> library = [_renderer.device
            newLibraryWithSource:[NSString stringWithUTF8String:_metal_shader_source]
                         options:nil
                           error:&error];

        if (!library) {
            fprintf(stderr, "coex_ui_metal_init: Failed to compile shaders: %s\n",
                    [[error localizedDescription] UTF8String]);
            return 0;
        }

        id<MTLFunction> vertexFunc = [library newFunctionWithName:@"vertex_main"];
        id<MTLFunction> fragmentFunc = [library newFunctionWithName:@"fragment_main"];

        if (!vertexFunc || !fragmentFunc) {
            fprintf(stderr, "coex_ui_metal_init: Failed to find shader functions\n");
            return 0;
        }

        /* Create vertex descriptor matching ImDrawVert */
        MTLVertexDescriptor* vertexDesc = [MTLVertexDescriptor vertexDescriptor];

        /* Position: float2 at offset 0 */
        vertexDesc.attributes[0].format = MTLVertexFormatFloat2;
        vertexDesc.attributes[0].offset = 0;
        vertexDesc.attributes[0].bufferIndex = 0;

        /* TexCoord: float2 at offset 8 */
        vertexDesc.attributes[1].format = MTLVertexFormatFloat2;
        vertexDesc.attributes[1].offset = 8;
        vertexDesc.attributes[1].bufferIndex = 0;

        /* Color: uchar4 at offset 16 */
        vertexDesc.attributes[2].format = MTLVertexFormatUChar4;
        vertexDesc.attributes[2].offset = 16;
        vertexDesc.attributes[2].bufferIndex = 0;

        /* Stride = sizeof(ImDrawVert) = 20 bytes */
        vertexDesc.layouts[0].stride = 20;
        vertexDesc.layouts[0].stepRate = 1;
        vertexDesc.layouts[0].stepFunction = MTLVertexStepFunctionPerVertex;

        /* Create pipeline state */
        MTLRenderPipelineDescriptor* pipelineDesc = [[MTLRenderPipelineDescriptor alloc] init];
        pipelineDesc.vertexFunction = vertexFunc;
        pipelineDesc.fragmentFunction = fragmentFunc;
        pipelineDesc.vertexDescriptor = vertexDesc;
        pipelineDesc.colorAttachments[0].pixelFormat = MTLPixelFormatBGRA8Unorm;

        /* Enable alpha blending */
        pipelineDesc.colorAttachments[0].blendingEnabled = YES;
        pipelineDesc.colorAttachments[0].sourceRGBBlendFactor = MTLBlendFactorSourceAlpha;
        pipelineDesc.colorAttachments[0].destinationRGBBlendFactor = MTLBlendFactorOneMinusSourceAlpha;
        pipelineDesc.colorAttachments[0].rgbBlendOperation = MTLBlendOperationAdd;
        pipelineDesc.colorAttachments[0].sourceAlphaBlendFactor = MTLBlendFactorOne;
        pipelineDesc.colorAttachments[0].destinationAlphaBlendFactor = MTLBlendFactorOneMinusSourceAlpha;
        pipelineDesc.colorAttachments[0].alphaBlendOperation = MTLBlendOperationAdd;

        _renderer.pipeline = [_renderer.device newRenderPipelineStateWithDescriptor:pipelineDesc
                                                                              error:&error];
        if (!_renderer.pipeline) {
            fprintf(stderr, "coex_ui_metal_init: Failed to create pipeline: %s\n",
                    [[error localizedDescription] UTF8String]);
            return 0;
        }

        /* Create depth stencil state (no depth testing for UI) */
        MTLDepthStencilDescriptor* depthDesc = [[MTLDepthStencilDescriptor alloc] init];
        depthDesc.depthCompareFunction = MTLCompareFunctionAlways;
        depthDesc.depthWriteEnabled = NO;
        _renderer.depthStencil = [_renderer.device newDepthStencilStateWithDescriptor:depthDesc];

        /* Create sampler */
        MTLSamplerDescriptor* samplerDesc = [[MTLSamplerDescriptor alloc] init];
        samplerDesc.minFilter = MTLSamplerMinMagFilterLinear;
        samplerDesc.magFilter = MTLSamplerMinMagFilterLinear;
        samplerDesc.mipFilter = MTLSamplerMipFilterNotMipmapped;
        samplerDesc.sAddressMode = MTLSamplerAddressModeRepeat;
        samplerDesc.tAddressMode = MTLSamplerAddressModeRepeat;
        _renderer.sampler = [_renderer.device newSamplerStateWithDescriptor:samplerDesc];

        /* Create uniform buffer */
        _renderer.uniformBuffer = [_renderer.device newBufferWithLength:sizeof(MetalUniforms)
                                                                options:MTLResourceStorageModeShared];

        _renderer.initialized = 1;
    }

    return 1;
}

void coex_ui_metal_shutdown(void) {
    if (!_renderer.initialized) return;

    _renderer.pipeline = nil;
    _renderer.depthStencil = nil;
    _renderer.sampler = nil;
    _renderer.fontTexture = nil;
    _renderer.vertexBuffer = nil;
    _renderer.indexBuffer = nil;
    _renderer.uniformBuffer = nil;
    _renderer.device = nil;

    _renderer.initialized = 0;
}

/* ============================================================================
 * Font Texture
 * ============================================================================ */

int64_t coex_ui_metal_create_fonts_texture(void) {
#ifdef COEX_UI_HAS_IMGUI
    if (!_renderer.initialized) return 0;

    @autoreleasepool {
        /* Get font texture data via the imgui wrapper */
        unsigned char* pixels = NULL;
        int width = 0, height = 0, bytesPerPixel = 0;

        if (!coex_imgui_get_font_tex_data_rgba32(&pixels, &width, &height, &bytesPerPixel)) {
            fprintf(stderr, "coex_ui_metal_create_fonts_texture: Failed to get font texture data\n");
            return 0;
        }

        if (!pixels || width <= 0 || height <= 0) {
            fprintf(stderr, "coex_ui_metal_create_fonts_texture: Invalid font texture data\n");
            return 0;
        }

        printf("Font texture: %dx%d, %d bytes per pixel\n", width, height, bytesPerPixel);

        /* Determine pixel format based on source format */
        MTLPixelFormat pixelFormat;
        unsigned char* uploadPixels = pixels;
        unsigned char* convertedPixels = NULL;
        int uploadBytesPerPixel = bytesPerPixel;

        if (bytesPerPixel == 1) {
            /* Alpha8 format - convert to RGBA32 for proper rendering */
            /* Each alpha byte becomes (255, 255, 255, alpha) */
            pixelFormat = MTLPixelFormatRGBA8Unorm;
            uploadBytesPerPixel = 4;
            convertedPixels = (unsigned char*)malloc(width * height * 4);
            if (!convertedPixels) {
                fprintf(stderr, "coex_ui_metal_create_fonts_texture: Failed to allocate conversion buffer\n");
                return 0;
            }
            for (int i = 0; i < width * height; i++) {
                convertedPixels[i * 4 + 0] = 255;           /* R */
                convertedPixels[i * 4 + 1] = 255;           /* G */
                convertedPixels[i * 4 + 2] = 255;           /* B */
                convertedPixels[i * 4 + 3] = pixels[i];     /* A */
            }
            uploadPixels = convertedPixels;
            printf("Converted Alpha8 to RGBA32\n");
        } else if (bytesPerPixel == 4) {
            /* Already RGBA32 */
            pixelFormat = MTLPixelFormatRGBA8Unorm;
        } else {
            fprintf(stderr, "coex_ui_metal_create_fonts_texture: Unsupported bytes per pixel: %d\n", bytesPerPixel);
            return 0;
        }

        /* Create Metal texture */
        MTLTextureDescriptor* texDesc = [MTLTextureDescriptor
            texture2DDescriptorWithPixelFormat:pixelFormat
                                         width:width
                                        height:height
                                     mipmapped:NO];
        texDesc.usage = MTLTextureUsageShaderRead;
        texDesc.storageMode = MTLStorageModeShared;

        _renderer.fontTexture = [_renderer.device newTextureWithDescriptor:texDesc];
        if (!_renderer.fontTexture) {
            fprintf(stderr, "coex_ui_metal_create_fonts_texture: Failed to create texture\n");
            if (convertedPixels) free(convertedPixels);
            return 0;
        }

        /* Upload pixel data */
        MTLRegion region = MTLRegionMake2D(0, 0, width, height);
        [_renderer.fontTexture replaceRegion:region
                                 mipmapLevel:0
                                   withBytes:uploadPixels
                                 bytesPerRow:width * uploadBytesPerPixel];

        /* Free conversion buffer if we allocated one */
        if (convertedPixels) free(convertedPixels);

        /* Store texture ID in ImGui */
        coex_imgui_set_font_tex_id((__bridge void*)_renderer.fontTexture);
    }

    return 1;
#else
    return 0;
#endif
}

void coex_ui_metal_invalidate_fonts_texture(void) {
#ifdef COEX_UI_HAS_IMGUI
    _renderer.fontTexture = nil;
    coex_imgui_set_font_tex_id(NULL);
#endif
}

int64_t coex_ui_metal_update_fonts_texture(void) {
#ifdef COEX_UI_HAS_IMGUI
    if (!_renderer.initialized || !_renderer.fontTexture) return 0;

    ImGuiIO* io = igGetIO_Nil();
    if (!io->Fonts || !io->Fonts->TexData) return 0;

    ImTextureData* texData = io->Fonts->TexData;

    /* Check if texture needs updating */
    if (texData->Status != ImTextureStatus_WantUpdates) {
        return 1; /* No update needed */
    }

    @autoreleasepool {
        /* Re-upload the entire texture */
        unsigned char* pixels = texData->Pixels;
        int width = texData->Width;
        int height = texData->Height;
        int bytesPerPixel = texData->BytesPerPixel;

        if (!pixels || width <= 0 || height <= 0) {
            return 0;
        }

        /* Check if texture size changed - need to recreate */
        if (width != (int)_renderer.fontTexture.width || height != (int)_renderer.fontTexture.height) {
            /* Size changed - recreate texture */
            coex_ui_metal_invalidate_fonts_texture();
            return coex_ui_metal_create_fonts_texture();
        }

        /* Same size - just update the data */
        MTLRegion region = MTLRegionMake2D(0, 0, width, height);
        [_renderer.fontTexture replaceRegion:region
                                 mipmapLevel:0
                                   withBytes:pixels
                                 bytesPerRow:width * bytesPerPixel];

        /* Mark texture as OK */
        ImTextureData_SetStatus(texData, ImTextureStatus_OK);
    }

    return 1;
#else
    return 0;
#endif
}

/* ============================================================================
 * Rendering
 * ============================================================================ */

void coex_ui_metal_render(
    void* command_buffer,
    void* render_target,
    void* imgui_draw_data,
    int64_t framebuffer_width,
    int64_t framebuffer_height
) {
#ifdef COEX_UI_HAS_IMGUI
    if (!_renderer.initialized) return;
    if (!command_buffer || !render_target || !imgui_draw_data) return;

    ImDrawData* draw_data = (ImDrawData*)imgui_draw_data;

    /* Avoid rendering if minimized */
    if (draw_data->DisplaySize.x <= 0 || draw_data->DisplaySize.y <= 0) return;
    if (draw_data->TotalVtxCount == 0) return;

    id<MTLCommandBuffer> cmdBuffer = (__bridge id<MTLCommandBuffer>)command_buffer;
    id<MTLTexture> target = (__bridge id<MTLTexture>)render_target;

    @autoreleasepool {
        /* Grow vertex buffer if needed */
        NSUInteger vertexSize = draw_data->TotalVtxCount * sizeof(ImDrawVert);
        if (!_renderer.vertexBuffer || _renderer.vertexBufferSize < vertexSize) {
            _renderer.vertexBufferSize = vertexSize + 10000 * sizeof(ImDrawVert);
            _renderer.vertexBuffer = [_renderer.device
                newBufferWithLength:_renderer.vertexBufferSize
                            options:MTLResourceStorageModeShared];
        }

        /* Grow index buffer if needed */
        NSUInteger indexSize = draw_data->TotalIdxCount * sizeof(ImDrawIdx);
        if (!_renderer.indexBuffer || _renderer.indexBufferSize < indexSize) {
            _renderer.indexBufferSize = indexSize + 10000 * sizeof(ImDrawIdx);
            _renderer.indexBuffer = [_renderer.device
                newBufferWithLength:_renderer.indexBufferSize
                            options:MTLResourceStorageModeShared];
        }

        /* Upload vertex/index data */
        ImDrawVert* vtxDst = (ImDrawVert*)[_renderer.vertexBuffer contents];
        ImDrawIdx* idxDst = (ImDrawIdx*)[_renderer.indexBuffer contents];

        for (int n = 0; n < draw_data->CmdListsCount; n++) {
            const ImDrawList* cmdList = draw_data->CmdLists.Data[n];
            memcpy(vtxDst, cmdList->VtxBuffer.Data, cmdList->VtxBuffer.Size * sizeof(ImDrawVert));
            memcpy(idxDst, cmdList->IdxBuffer.Data, cmdList->IdxBuffer.Size * sizeof(ImDrawIdx));
            vtxDst += cmdList->VtxBuffer.Size;
            idxDst += cmdList->IdxBuffer.Size;
        }

        /* Setup orthographic projection matrix */
        float L = draw_data->DisplayPos.x;
        float R = draw_data->DisplayPos.x + draw_data->DisplaySize.x;
        float T = draw_data->DisplayPos.y;
        float B = draw_data->DisplayPos.y + draw_data->DisplaySize.y;

        MetalUniforms* uniforms = (MetalUniforms*)[_renderer.uniformBuffer contents];
        uniforms->projectionMatrix = (simd_float4x4){{
            { 2.0f / (R - L), 0.0f, 0.0f, 0.0f },
            { 0.0f, 2.0f / (T - B), 0.0f, 0.0f },
            { 0.0f, 0.0f, -1.0f, 0.0f },
            { (R + L) / (L - R), (T + B) / (B - T), 0.0f, 1.0f }
        }};

        /* Create render pass */
        MTLRenderPassDescriptor* passDesc = [MTLRenderPassDescriptor renderPassDescriptor];
        passDesc.colorAttachments[0].texture = target;
        passDesc.colorAttachments[0].loadAction = MTLLoadActionClear;
        passDesc.colorAttachments[0].storeAction = MTLStoreActionStore;
        passDesc.colorAttachments[0].clearColor = MTLClearColorMake(0.1, 0.1, 0.1, 1.0);

        id<MTLRenderCommandEncoder> encoder = [cmdBuffer renderCommandEncoderWithDescriptor:passDesc];
        [encoder setRenderPipelineState:_renderer.pipeline];
        [encoder setDepthStencilState:_renderer.depthStencil];

        /* Set viewport */
        MTLViewport viewport = {
            .originX = 0,
            .originY = 0,
            .width = (double)framebuffer_width,
            .height = (double)framebuffer_height,
            .znear = 0.0,
            .zfar = 1.0
        };
        [encoder setViewport:viewport];

        /* Bind vertex buffer and uniforms */
        [encoder setVertexBuffer:_renderer.vertexBuffer offset:0 atIndex:0];
        [encoder setVertexBuffer:_renderer.uniformBuffer offset:0 atIndex:1];
        [encoder setFragmentSamplerState:_renderer.sampler atIndex:0];

        /* Render draw lists */
        ImVec2 clipOff = draw_data->DisplayPos;
        ImVec2 clipScale = draw_data->FramebufferScale;

        NSUInteger vertexOffset = 0;
        NSUInteger indexOffset = 0;

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

                MTLScissorRect scissor = {
                    .x = (NSUInteger)clipMinX,
                    .y = (NSUInteger)clipMinY,
                    .width = (NSUInteger)(clipMaxX - clipMinX),
                    .height = (NSUInteger)(clipMaxY - clipMinY)
                };
                [encoder setScissorRect:scissor];

                /* Bind texture - use ImDrawCmd_GetTexID for cimgui */
                ImTextureID texId = ImDrawCmd_GetTexID(pcmd);
                if (texId) {
                    id<MTLTexture> texture = (__bridge id<MTLTexture>)(void*)(uintptr_t)texId;
                    [encoder setFragmentTexture:texture atIndex:0];
                }

                /* Draw indexed triangles */
                [encoder drawIndexedPrimitives:MTLPrimitiveTypeTriangle
                                    indexCount:pcmd->ElemCount
                                     indexType:sizeof(ImDrawIdx) == 2 ? MTLIndexTypeUInt16 : MTLIndexTypeUInt32
                                   indexBuffer:_renderer.indexBuffer
                             indexBufferOffset:(indexOffset + pcmd->IdxOffset) * sizeof(ImDrawIdx)
                                 instanceCount:1
                                    baseVertex:vertexOffset + pcmd->VtxOffset
                                  baseInstance:0];
            }

            vertexOffset += cmdList->VtxBuffer.Size;
            indexOffset += cmdList->IdxBuffer.Size;
        }

        [encoder endEncoding];
    }
#else
    (void)command_buffer;
    (void)render_target;
    (void)imgui_draw_data;
    (void)framebuffer_width;
    (void)framebuffer_height;
#endif
}
