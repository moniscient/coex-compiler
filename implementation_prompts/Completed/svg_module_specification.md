# Coex SVG Module Implementation Specification

## 1. Overview

The SVG module provides declarative SVG rendering with state bindings, following the same patterns established by the UI module. It enables loading SVG documents created in tools like Inkscape, binding SVG element attributes to state keys, and handling user interaction through coordinated invisible ImGUI hit regions.

The SVG module imports and depends on the UI module. SVG content is rendered as textures within ImGUI windows, and input handling leverages ImGUI's existing infrastructure.

---

## 2. Module Interface

### 2.1 Public Functions

```coex
import svg

# Load an SVG document from file, returns a template handle
func svg.load(path: string) -> SVGTemplate

# Bind an SVG element's attribute to a state key
# element_id: the XML id attribute of the target element
# attribute: the SVG attribute name (e.g., "cx", "fill", "transform")  
# state_key: the key in the state frame to read from
func svg.bind(template: SVGTemplate, element_id: string, attribute: string, state_key: string)

# Bind multiple attributes for one element at once
# bindings: object mapping attribute names to state keys
func svg.bind_element(template: SVGTemplate, element_id: string, bindings: object)

# Register an event handler for an SVG element
# event: "click", "hover", "mousedown", "mouseup"
# state_key: the key in state frame to write to
func svg.on(template: SVGTemplate, element_id: string, event: string, state_key: string)

# Create an SVG image widget for use in UI layouts
# Returns a UI-compatible widget descriptor
func svg.image(template: SVGTemplate, width: int, height: int) -> object
```

### 2.2 Usage Pattern

```coex
import ui
import svg

func main() -> int
    # Initialize UI as normal
    config = { title: "SVG Demo", width: 800, height: 600 }
    ui.initialize(config)
    
    # Load and configure SVG template
    graphic = svg.load("game_sprites.svg")
    
    # Bind attributes to state keys
    svg.bind(graphic, "player", "cx", "player_x")
    svg.bind(graphic, "player", "cy", "player_y")
    svg.bind(graphic, "player", "fill", "player_color")
    
    # Or use batch binding
    svg.bind_element(graphic, "enemy", {
        cx: "enemy_x",
        cy: "enemy_y",
        opacity: "enemy_visible"
    })
    
    # Register event handlers
    svg.on(graphic, "player", "click", "player_clicked")
    svg.on(graphic, "start_button", "click", "game_start")
    svg.on(graphic, "start_button", "hover", "button_hovered")
    
    # Create UI layout including the SVG
    layout = {
        type: "window",
        title: "Game",
        children: [
            { type: "text", text: "Score: ", bind: "score" },
            svg.image(graphic, 640, 480),
            { type: "button", label: "Reset", id: "reset_btn" }
        ]
    }
    
    # Initial state
    state = "{\"player_x\": 100, \"player_y\": 100, \"player_color\": \"#00ff00\", \"enemy_x\": 300, \"enemy_y\": 200, \"enemy_visible\": 1.0, \"player_clicked\": false, \"game_start\": false, \"button_hovered\": false, \"score\": 0}"
    
    while true
        if ui.should_close()
            break
        ~
        
        # Process game logic, updating state as needed
        # ...
        
        # Render frame - SVG bindings are applied automatically
        state = ui.render(layout, state)
        
        # Reset one-shot events
        # (or let the runtime handle this automatically)
    ~
    
    return 0
~
```

---

## 3. Internal Architecture

### 3.1 Component Diagram

```
┌─────────────────────────────────────────────────────────────────┐
│                        Coex Application                          │
│  ┌─────────────┐    ┌─────────────┐    ┌─────────────────────┐  │
│  │ State Frame │◄──►│  UI Module  │◄──►│    SVG Module       │  │
│  │   (JSON)    │    │  (ImGUI)    │    │                     │  │
│  └─────────────┘    └──────┬──────┘    │  ┌───────────────┐  │  │
│                            │           │  │ SVG Templates │  │  │
│                            │           │  │ (LunaSVG doc) │  │  │
│                            │           │  └───────┬───────┘  │  │
│                            │           │          │          │  │
│                            │           │  ┌───────▼───────┐  │  │
│                            │           │  │   Bindings    │  │  │
│                            │           │  │ element→state │  │  │
│                            │           │  └───────┬───────┘  │  │
│                            │           │          │          │  │
│                            │           │  ┌───────▼───────┐  │  │
│                            │           │  │ Event Regions │  │  │
│                            │           │  │  (bbox cache) │  │  │
│                            │           │  └───────────────┘  │  │
│                            │           └─────────────────────┘  │
└────────────────────────────┼────────────────────────────────────┘
                             │
                    ┌────────▼────────┐
                    │ Platform Layer  │
                    │ Metal/GL/D3D    │
                    └─────────────────┘
```

### 3.2 Data Structures

#### SVGTemplate (opaque handle)

Internally contains:
- `document`: LunaSVG document pointer
- `bindings`: list of (element_id, attribute, state_key) tuples
- `events`: list of (element_id, event_type, state_key, cached_bbox) tuples
- `texture_id`: platform texture handle (0 if not yet created)
- `texture_width`, `texture_height`: current render dimensions
- `dirty`: boolean, true if bindings have changed since last render

#### Binding Entry

```c
struct SVGBinding {
    char* element_id;      // XML id of target element
    char* attribute;       // SVG attribute name
    char* state_key;       // Key in state frame
};
```

#### Event Entry

```c
struct SVGEvent {
    char* element_id;      // XML id of target element
    int event_type;        // CLICK=1, HOVER=2, MOUSEDOWN=3, MOUSEUP=4
    char* state_key;       // Key in state frame to write
    float bbox[4];         // Cached bounding box [x, y, width, height] in SVG coords
};
```

### 3.3 Render Pipeline (per frame)

```
svg_render_frame(template, state, screen_x, screen_y, width, height):
    
    # 1. Apply bindings: read state, update SVG attributes
    for binding in template.bindings:
        value = json_get(state, binding.state_key)
        if value != null:
            value_str = to_svg_value(value, binding.attribute)
            lunasvg_element_set_attribute(
                lunasvg_get_element_by_id(template.document, binding.element_id),
                binding.attribute,
                value_str
            )
    
    # 2. Render SVG to bitmap
    bitmap = lunasvg_render_to_bitmap(template.document, width, height, 0x00000000)
    
    # 3. Upload to GPU texture (create if needed, else update)
    if template.texture_id == 0:
        template.texture_id = platform_create_texture(width, height)
    platform_update_texture(template.texture_id, bitmap.data, width, height)
    lunasvg_bitmap_destroy(bitmap)
    
    # 4. Draw texture via ImGUI
    imgui_image(template.texture_id, width, height)
    
    # 5. Overlay invisible hit regions for events
    svg_viewbox = lunasvg_document_get_viewbox(template.document)
    scale_x = width / svg_viewbox.width
    scale_y = height / svg_viewbox.height
    
    for event in template.events:
        # Transform bbox from SVG coords to screen coords
        screen_bbox = {
            x: screen_x + event.bbox[0] * scale_x,
            y: screen_y + event.bbox[1] * scale_y,
            w: event.bbox[2] * scale_x,
            h: event.bbox[3] * scale_y
        }
        
        imgui_set_cursor_screen_pos(screen_bbox.x, screen_bbox.y)
        imgui_invisible_button(event.element_id, screen_bbox.w, screen_bbox.h)
        
        # Write event state
        if event.event_type == CLICK and imgui_is_item_clicked():
            json_set(state, event.state_key, true)
        elif event.event_type == HOVER:
            json_set(state, event.state_key, imgui_is_item_hovered())
        elif event.event_type == MOUSEDOWN and imgui_is_item_active():
            json_set(state, event.state_key, true)
        elif event.event_type == MOUSEUP and imgui_is_item_deactivated():
            json_set(state, event.state_key, true)
    
    return state
```

---

## 4. C FFI Layer

### 4.1 LunaSVG Bindings

The following C functions must be exposed to Coex via extern declarations:

```coex
# svg_ffi.coex - LunaSVG C bindings

# Opaque pointer types (represented as int64 in Coex)
# lunasvg_document*  -> int
# lunasvg_element    -> int  
# lunasvg_bitmap*    -> int

# Document lifecycle
extern func lunasvg_document_load_from_file(filename: string) -> int
extern func lunasvg_document_load_from_data(data: string, length: int) -> int
extern func lunasvg_document_destroy(document: int)
extern func lunasvg_document_width(document: int) -> float
extern func lunasvg_document_height(document: int) -> float

# Element access
extern func lunasvg_document_get_element_by_id(document: int, id: string) -> int
extern func lunasvg_element_set_attribute(element: int, name: string, value: string)
extern func lunasvg_element_get_attribute(element: int, name: string) -> string

# Bounding box (returns via out parameters or packed struct)
extern func lunasvg_element_get_bbox_x(element: int) -> float
extern func lunasvg_element_get_bbox_y(element: int) -> float
extern func lunasvg_element_get_bbox_width(element: int) -> float
extern func lunasvg_element_get_bbox_height(element: int) -> float

# Rendering
extern func lunasvg_document_render_to_bitmap(document: int, width: int, height: int, bgcolor: int) -> int
extern func lunasvg_bitmap_data(bitmap: int) -> int  # returns pointer to RGBA data
extern func lunasvg_bitmap_width(bitmap: int) -> int
extern func lunasvg_bitmap_height(bitmap: int) -> int
extern func lunasvg_bitmap_stride(bitmap: int) -> int
extern func lunasvg_bitmap_destroy(bitmap: int)
```

### 4.2 C Wrapper Requirements

LunaSVG's native API is C++. A thin C wrapper (`lunasvg_c.h` / `lunasvg_c.cpp`) must be created to expose the required functionality:

```c
// lunasvg_c.h
#ifndef LUNASVG_C_H
#define LUNASVG_C_H

#include <stdint.h>
#include <stddef.h>

#ifdef __cplusplus
extern "C" {
#endif

typedef void* lunasvg_document_t;
typedef void* lunasvg_element_t;
typedef void* lunasvg_bitmap_t;

// Document
lunasvg_document_t lunasvg_document_load_from_file(const char* filename);
lunasvg_document_t lunasvg_document_load_from_data(const char* data, size_t length);
void lunasvg_document_destroy(lunasvg_document_t doc);
float lunasvg_document_width(lunasvg_document_t doc);
float lunasvg_document_height(lunasvg_document_t doc);

// Element
lunasvg_element_t lunasvg_document_get_element_by_id(lunasvg_document_t doc, const char* id);
int lunasvg_element_is_null(lunasvg_element_t elem);
void lunasvg_element_set_attribute(lunasvg_element_t elem, const char* name, const char* value);
const char* lunasvg_element_get_attribute(lunasvg_element_t elem, const char* name);
void lunasvg_element_get_bounding_box(lunasvg_element_t elem, float* x, float* y, float* w, float* h);

// Bitmap
lunasvg_bitmap_t lunasvg_document_render_to_bitmap(lunasvg_document_t doc, int width, int height, uint32_t bgcolor);
uint8_t* lunasvg_bitmap_data(lunasvg_bitmap_t bmp);
int lunasvg_bitmap_width(lunasvg_bitmap_t bmp);
int lunasvg_bitmap_height(lunasvg_bitmap_t bmp);
int lunasvg_bitmap_stride(lunasvg_bitmap_t bmp);
void lunasvg_bitmap_destroy(lunasvg_bitmap_t bmp);

#ifdef __cplusplus
}
#endif

#endif // LUNASVG_C_H
```

```cpp
// lunasvg_c.cpp
#include "lunasvg_c.h"
#include <lunasvg.h>
#include <string>

using namespace lunasvg;

extern "C" {

lunasvg_document_t lunasvg_document_load_from_file(const char* filename) {
    auto doc = Document::loadFromFile(filename);
    return doc.release();  // Transfer ownership
}

lunasvg_document_t lunasvg_document_load_from_data(const char* data, size_t length) {
    auto doc = Document::loadFromData(data, length);
    return doc.release();
}

void lunasvg_document_destroy(lunasvg_document_t doc) {
    delete static_cast<Document*>(doc);
}

float lunasvg_document_width(lunasvg_document_t doc) {
    return static_cast<Document*>(doc)->width();
}

float lunasvg_document_height(lunasvg_document_t doc) {
    return static_cast<Document*>(doc)->height();
}

lunasvg_element_t lunasvg_document_get_element_by_id(lunasvg_document_t doc, const char* id) {
    auto elem = static_cast<Document*>(doc)->getElementById(id);
    // Element is a value type; need to heap-allocate for C interface
    if (elem.isNull()) return nullptr;
    return new Element(elem);
}

int lunasvg_element_is_null(lunasvg_element_t elem) {
    if (!elem) return 1;
    return static_cast<Element*>(elem)->isNull() ? 1 : 0;
}

void lunasvg_element_set_attribute(lunasvg_element_t elem, const char* name, const char* value) {
    if (elem) {
        static_cast<Element*>(elem)->setAttribute(name, value);
    }
}

const char* lunasvg_element_get_attribute(lunasvg_element_t elem, const char* name) {
    if (!elem) return "";
    static thread_local std::string result;
    result = static_cast<Element*>(elem)->getAttribute(name);
    return result.c_str();
}

void lunasvg_element_get_bounding_box(lunasvg_element_t elem, float* x, float* y, float* w, float* h) {
    if (!elem) {
        *x = *y = *w = *h = 0;
        return;
    }
    auto box = static_cast<Element*>(elem)->getBoundingBox();
    *x = box.x;
    *y = box.y;
    *w = box.w;
    *h = box.h;
}

lunasvg_bitmap_t lunasvg_document_render_to_bitmap(lunasvg_document_t doc, int width, int height, uint32_t bgcolor) {
    auto bmp = static_cast<Document*>(doc)->renderToBitmap(width, height, bgcolor);
    if (bmp.isNull()) return nullptr;
    return new Bitmap(std::move(bmp));
}

uint8_t* lunasvg_bitmap_data(lunasvg_bitmap_t bmp) {
    if (!bmp) return nullptr;
    return static_cast<Bitmap*>(bmp)->data();
}

int lunasvg_bitmap_width(lunasvg_bitmap_t bmp) {
    if (!bmp) return 0;
    return static_cast<Bitmap*>(bmp)->width();
}

int lunasvg_bitmap_height(lunasvg_bitmap_t bmp) {
    if (!bmp) return 0;
    return static_cast<Bitmap*>(bmp)->height();
}

int lunasvg_bitmap_stride(lunasvg_bitmap_t bmp) {
    if (!bmp) return 0;
    return static_cast<Bitmap*>(bmp)->stride();
}

void lunasvg_bitmap_destroy(lunasvg_bitmap_t bmp) {
    delete static_cast<Bitmap*>(bmp);
}

} // extern "C"
```

---

## 5. Platform Texture Integration

### 5.1 Texture Upload Interface

Each platform backend (Metal, OpenGL, Direct3D) needs functions to:

1. Create a texture of given dimensions
2. Update texture contents from RGBA pixel data
3. Return a handle that ImGUI can use for `ImGui::Image()`

```c
// Platform-agnostic interface (implemented per-platform)
typedef void* platform_texture_t;

platform_texture_t platform_texture_create(int width, int height);
void platform_texture_update(platform_texture_t tex, const uint8_t* rgba_data, int width, int height, int stride);
void platform_texture_destroy(platform_texture_t tex);
void* platform_texture_get_imgui_id(platform_texture_t tex);  // Returns ImTextureID
```

### 5.2 Metal Implementation (macOS)

```objc
// metal_texture.m
#import <Metal/Metal.h>

static id<MTLDevice> g_device;
static id<MTLCommandQueue> g_commandQueue;

platform_texture_t platform_texture_create(int width, int height) {
    MTLTextureDescriptor* desc = [MTLTextureDescriptor texture2DDescriptorWithPixelFormat:MTLPixelFormatRGBA8Unorm
                                                                                    width:width
                                                                                   height:height
                                                                                mipmapped:NO];
    desc.usage = MTLTextureUsageShaderRead;
    id<MTLTexture> texture = [g_device newTextureWithDescriptor:desc];
    return (__bridge_retained void*)texture;
}

void platform_texture_update(platform_texture_t tex, const uint8_t* rgba_data, int width, int height, int stride) {
    id<MTLTexture> texture = (__bridge id<MTLTexture>)tex;
    MTLRegion region = MTLRegionMake2D(0, 0, width, height);
    [texture replaceRegion:region mipmapLevel:0 withBytes:rgba_data bytesPerRow:stride];
}

void platform_texture_destroy(platform_texture_t tex) {
    id<MTLTexture> texture = (__bridge_transfer id<MTLTexture>)tex;
    texture = nil;
}

void* platform_texture_get_imgui_id(platform_texture_t tex) {
    return tex;  // ImGUI Metal backend uses MTLTexture* directly
}
```

### 5.3 OpenGL Implementation (Linux/Windows fallback)

```c
// opengl_texture.c
#include <GL/gl.h>

platform_texture_t platform_texture_create(int width, int height) {
    GLuint tex;
    glGenTextures(1, &tex);
    glBindTexture(GL_TEXTURE_2D, tex);
    glTexImage2D(GL_TEXTURE_2D, 0, GL_RGBA8, width, height, 0, GL_RGBA, GL_UNSIGNED_BYTE, NULL);
    glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MIN_FILTER, GL_LINEAR);
    glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MAG_FILTER, GL_LINEAR);
    glBindTexture(GL_TEXTURE_2D, 0);
    return (platform_texture_t)(uintptr_t)tex;
}

void platform_texture_update(platform_texture_t tex, const uint8_t* rgba_data, int width, int height, int stride) {
    GLuint gl_tex = (GLuint)(uintptr_t)tex;
    glBindTexture(GL_TEXTURE_2D, gl_tex);
    glPixelStorei(GL_UNPACK_ROW_LENGTH, stride / 4);
    glTexSubImage2D(GL_TEXTURE_2D, 0, 0, 0, width, height, GL_RGBA, GL_UNSIGNED_BYTE, rgba_data);
    glPixelStorei(GL_UNPACK_ROW_LENGTH, 0);
    glBindTexture(GL_TEXTURE_2D, 0);
}

void platform_texture_destroy(platform_texture_t tex) {
    GLuint gl_tex = (GLuint)(uintptr_t)tex;
    glDeleteTextures(1, &gl_tex);
}

void* platform_texture_get_imgui_id(platform_texture_t tex) {
    return tex;  // ImGUI OpenGL backend uses GLuint cast to void*
}
```

---

## 6. SVG Image Widget Integration

### 6.1 Widget Descriptor

The `svg.image()` function returns a widget descriptor that the UI module recognizes:

```coex
func svg.image(template: SVGTemplate, width: int, height: int) -> object
    return {
        type: "svg_image",
        template: template,
        width: width,
        height: height
    }
~
```

### 6.2 UI Module Extension

The UI module's widget renderer must handle `type: "svg_image"`:

```c
// In ui_render_widget()
case WIDGET_SVG_IMAGE: {
    SVGTemplate* tmpl = (SVGTemplate*)widget->template;
    int width = widget->width;
    int height = widget->height;
    
    // Get current cursor position for event coordinate transform
    ImVec2 screen_pos = ImGui::GetCursorScreenPos();
    
    // Render SVG and get updated state
    state = svg_render_frame(tmpl, state, screen_pos.x, screen_pos.y, width, height);
    
    break;
}
```

---

## 7. Value Conversion

### 7.1 State to SVG Attribute Conversion

Different SVG attributes expect different value formats:

| Attribute Type | State Value | SVG Value |
|---------------|-------------|-----------|
| Position (cx, cy, x, y) | number | "123.45" |
| Dimension (r, width, height) | number | "123.45" |
| Color (fill, stroke) | string "#rrggbb" | "#rrggbb" |
| Color (fill, stroke) | array [r,g,b] (0-1) | "rgb(255,128,0)" |
| Color (fill, stroke) | array [r,g,b,a] (0-1) | "rgba(255,128,0,0.5)" |
| Opacity | number (0-1) | "0.75" |
| Transform | string | passed through |
| Transform | object {translate:[x,y]} | "translate(x,y)" |
| Visibility | boolean | "visible" / "hidden" |
| Display | boolean | "inline" / "none" |

```c
// svg_value_convert.c
char* svg_convert_value(const char* attribute, json_value* value) {
    static char buffer[256];
    
    // Color attributes
    if (strcmp(attribute, "fill") == 0 || strcmp(attribute, "stroke") == 0) {
        if (value->type == JSON_STRING) {
            return value->string;  // Already formatted
        } else if (value->type == JSON_ARRAY) {
            if (value->array_length == 3) {
                int r = (int)(value->array[0].number * 255);
                int g = (int)(value->array[1].number * 255);
                int b = (int)(value->array[2].number * 255);
                snprintf(buffer, sizeof(buffer), "rgb(%d,%d,%d)", r, g, b);
            } else if (value->array_length == 4) {
                int r = (int)(value->array[0].number * 255);
                int g = (int)(value->array[1].number * 255);
                int b = (int)(value->array[2].number * 255);
                float a = value->array[3].number;
                snprintf(buffer, sizeof(buffer), "rgba(%d,%d,%d,%.2f)", r, g, b, a);
            }
            return buffer;
        }
    }
    
    // Numeric attributes
    if (value->type == JSON_NUMBER) {
        snprintf(buffer, sizeof(buffer), "%.4g", value->number);
        return buffer;
    }
    
    // Boolean -> visibility
    if (strcmp(attribute, "visibility") == 0 && value->type == JSON_BOOL) {
        return value->boolean ? "visible" : "hidden";
    }
    
    // Boolean -> display
    if (strcmp(attribute, "display") == 0 && value->type == JSON_BOOL) {
        return value->boolean ? "inline" : "none";
    }
    
    // String passthrough
    if (value->type == JSON_STRING) {
        return value->string;
    }
    
    return "";
}
```

---

## 8. Event Handling Details

### 8.1 Event Types and State Updates

| Event | Trigger | State Update |
|-------|---------|--------------|
| click | Mouse button released over element | Set to `true` (one-shot) |
| hover | Mouse cursor over element | Set to `true` while hovering, `false` otherwise |
| mousedown | Mouse button pressed over element | Set to `true` (one-shot) |
| mouseup | Mouse button released over element | Set to `true` (one-shot) |

### 8.2 One-Shot Event Reset

One-shot events (click, mousedown, mouseup) must be reset to `false` after the application has had a chance to observe them. Two options:

**Option A: Application resets manually**
```coex
state = ui.render(layout, state)
if json_get(state, "player_clicked")
    # Handle click
    state = json_set(state, "player_clicked", false)
~
```

**Option B: Auto-reset at frame start**
The SVG module tracks which state keys are one-shot events and resets them at the beginning of each frame, before the application logic runs.

Recommendation: **Option A** for initial implementation (simpler, explicit), with Option B as a future convenience feature.

### 8.3 Bounding Box Caching

Bounding boxes are cached when `svg.on()` is called. If bindings could change element positions/sizes, the cache may become stale. 

For v1: Assume static bounding boxes. Document this limitation.

For v2: Optionally re-query bounding boxes each frame, or provide `svg.refresh_bounds(template)`.

---

## 9. Build Integration

### 9.1 Dependencies

- LunaSVG library (static or dynamic)
- LunaSVG C wrapper (compiled with the Coex runtime)
- Platform texture implementation (per-platform)

### 9.2 CMake Integration

```cmake
# Find or fetch LunaSVG
FetchContent_Declare(
    lunasvg
    GIT_REPOSITORY https://github.com/sammycage/lunasvg.git
    GIT_TAG v3.0.0
)
FetchContent_MakeAvailable(lunasvg)

# Build C wrapper
add_library(lunasvg_c STATIC
    lunasvg_c.cpp
)
target_link_libraries(lunasvg_c PRIVATE lunasvg::lunasvg)

# Link to Coex runtime
target_link_libraries(coex_runtime PRIVATE lunasvg_c)
```

### 9.3 File Structure

```
coex/
├── runtime/
│   ├── ui/
│   │   ├── ui_module.c
│   │   └── ...
│   ├── svg/
│   │   ├── svg_module.c        # Main module implementation
│   │   ├── svg_bindings.c      # Binding management
│   │   ├── svg_events.c        # Event handling
│   │   ├── svg_convert.c       # Value conversion
│   │   ├── lunasvg_c.h         # C wrapper header
│   │   └── lunasvg_c.cpp       # C wrapper implementation
│   └── platform/
│       ├── texture_metal.m     # macOS texture impl
│       ├── texture_opengl.c    # Linux/Windows texture impl
│       └── texture_d3d11.c     # Windows texture impl (optional)
├── stdlib/
│   └── svg.coex                # Public Coex interface
└── examples/
    └── svg_demo.coex           # Example application
```

---

## 10. Example: Complete Application

```coex
# svg_game_demo.coex
# Simple game demonstrating SVG rendering with state bindings

import ui
import svg

func main() -> int
    print("=== SVG Game Demo ===")
    
    # Initialize UI
    config = { title: "SVG Game", width: 800, height: 600 }
    result = ui.initialize(config)
    if result != 1
        print("Failed to initialize UI")
        return 1
    ~
    
    # Load game graphics
    sprites = svg.load("game_sprites.svg")
    
    # Bind player sprite
    svg.bind_element(sprites, "player", {
        cx: "player_x",
        cy: "player_y",
        fill: "player_color"
    })
    
    # Bind collectibles
    svg.bind(sprites, "coin1", "opacity", "coin1_visible")
    svg.bind(sprites, "coin2", "opacity", "coin2_visible")
    svg.bind(sprites, "coin3", "opacity", "coin3_visible")
    
    # Bind score display
    svg.bind(sprites, "score_text", "text", "score_display")
    
    # Register click events
    svg.on(sprites, "player", "click", "player_clicked")
    svg.on(sprites, "coin1", "click", "coin1_clicked")
    svg.on(sprites, "coin2", "click", "coin2_clicked")
    svg.on(sprites, "coin3", "click", "coin3_clicked")
    
    # UI layout
    layout = {
        type: "window",
        title: "Game",
        children: [
            { type: "row", children: [
                { type: "text", text: "Score: " },
                { type: "text", bind: "score" },
                { type: "spacing" },
                { type: "button", label: "Reset", id: "reset_btn" }
            ]},
            { type: "separator" },
            svg.image(sprites, 640, 480),
            { type: "separator" },
            { type: "text", text: "Click coins to collect them!", color: [0.7, 0.7, 0.7, 1.0] }
        ]
    }
    
    # Initial state
    state = "{\"player_x\": 320, \"player_y\": 240, \"player_color\": \"#00aa00\", \"coin1_visible\": 1.0, \"coin2_visible\": 1.0, \"coin3_visible\": 1.0, \"coin1_clicked\": false, \"coin2_clicked\": false, \"coin3_clicked\": false, \"player_clicked\": false, \"score\": 0, \"score_display\": \"0\"}"
    
    while true
        if ui.should_close()
            break
        ~
        
        # Game logic: check for coin collection
        score = json_get_int(state, "score")
        
        if json_get_bool(state, "coin1_clicked")
            state = json_set(state, "coin1_visible", 0.0)
            state = json_set(state, "coin1_clicked", false)
            score = score + 10
        ~
        
        if json_get_bool(state, "coin2_clicked")
            state = json_set(state, "coin2_visible", 0.0)
            state = json_set(state, "coin2_clicked", false)
            score = score + 10
        ~
        
        if json_get_bool(state, "coin3_clicked")
            state = json_set(state, "coin3_visible", 0.0)
            state = json_set(state, "coin3_clicked", false)
            score = score + 10
        ~
        
        state = json_set(state, "score", score)
        state = json_set(state, "score_display", int_to_string(score))
        
        # Render
        state = ui.render(layout, state)
    ~
    
    print("Game finished! Final score: " + int_to_string(json_get_int(state, "score")))
    return 0
~
```

---

## 11. Future Extensions (Out of Scope for v1)

- **Sprite sheets**: Load multiple SVG files, composite into single texture
- **SVG groups as units**: Bind transforms to group elements for compound sprites  
- **Drag events**: Full drag tracking with start/current/delta positions
- **Procedural SVG**: Generate SVG markup from Coex code
- **SVG text editing**: Bind text content of `<text>` elements to state
- **Performance: dirty tracking**: Skip re-render when no bound state changed
- **Performance: partial update**: Update only changed regions of large SVGs
