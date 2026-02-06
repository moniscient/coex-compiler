# bgfx 3D Graphics Library Integration for Coex

## Overview

Add `import bgfx` as a new library following the exact same pattern as `import svg`. bgfx provides cross-platform 3D rendering (Metal/Vulkan/D3D12) that coexists with ImGui for GUI controls.

## Design Invariants

These invariants govern all design decisions across every file in this integration.

### INV-1: Value Semantics / Immutable Heap

Coex is a value-semantics language with an immutable heap. All data visible to Coex code is immutable once created. The C FFI layer must **copy** data into Coex-managed memory (the immutable heap) — it never hands Coex a mutable pointer. This means:

- Every C function that returns data to Coex must return a **new value** (int64_t, double, or a freshly-allocated `const char*` string that gets copied into the immutable heap by the codegen layer).
- Handles (int64_t) are the primary mechanism for referring to mutable GPU-side state (buffers, textures, programs) without violating value semantics — the handle is an immutable integer; the mutable state lives entirely on the C/GPU side.
- No Coex-visible value is ever mutated in place. State changes produce new values.

### INV-2: FFI Membrane / Memory Ownership

The C FFI is a membrane. C functions `malloc()` their own data and pass results to Coex. Once the codegen layer copies the result into the immutable heap, **the C side must `free()` the original**. Concretely:

- Any C function returning `const char*` (e.g., JSON strings, renderer name) must allocate with `malloc()`. The codegen copies the string into the Coex heap, then calls a corresponding `_free` function (e.g., `coex_bgfx_free_json(ptr)`) or the wrapper handles it.
- The `lib/bgfx.coex` wrapper functions are responsible for calling the free function after capturing the return value. Pattern:
  ```
  func get_caps() -> json
      result_str = coex_bgfx_get_caps_json()   # C mallocs
      parsed = json.parse(result_str)            # copied into Coex heap
      coex_bgfx_free_json(result_str)            # free C-side allocation
      return parsed                              # immutable Coex value
  ~
  ```
- Vertex/index buffer data passed **into** C functions is consumed immediately — bgfx copies it to GPU memory, so the C layer needs no persistent allocation for inbound data.
- Handle table entries are freed when `destroy_*` is called. The handle integer in Coex becomes a dangling reference (using it after destroy is a programmer error, returns 0/error).

### INV-3: 64-bit Primitives

Use 64-bit types everywhere at the FFI boundary:

- All integer parameters and return values: `int64_t`
- All floating-point parameters and return values: `double`
- **Exception**: GPU-internal data only. Vertex buffer data, index buffer data, texture pixel data, and shader uniforms may use 32-bit or 16-bit types **internally on the GPU side** where bit width directly affects GPU memory bandwidth and shader performance. These smaller types never appear at the FFI boundary — they exist only inside the `const void*` data blobs passed to buffer/texture creation functions.
- bgfx's native 16-bit handles are wrapped in int64_t at the FFI boundary (via the handle table).

### INV-4: JSON for Complex Objects

Any structured or compound data crossing the FFI membrane uses JSON (stringified `const char*`):

- Vertex layout specifications: `{"attribs":[{"name":"Position","type":"Float","num":3}, ...]}`
- Matrix data (float[16]): `"[1.0,0.0,0.0,0.0, 0.0,1.0,0.0,0.0, ...]"`
- Renderer capabilities: full JSON object
- View transform matrices passed as JSON-encoded arrays
- The C layer parses inbound JSON with cJSON (already a dependency). Outbound JSON is built with `snprintf` or cJSON and `malloc`'d (see INV-2).

---

## New Files

| File | Purpose |
|------|---------|
| `lib/bgfx.coex` | Coex API: extern declarations + wrapper functions (handles INV-2 free pattern) |
| `runtime/bgfx/coex_bgfx.h` | C API header (all params int64_t/double/const char* per INV-3) |
| `runtime/bgfx/coex_bgfx.c` | Core implementation: handle table, init, views, draw calls, math helpers, JSON parsing |
| `runtime/bgfx/bgfx_c_bridge.cpp` | Thin C++ bridge calling bgfx C99 API (extern "C") |
| `runtime/bgfx/coex_bgfx_imgui.cpp` | Renders ImDrawData via bgfx transient buffers on view 255 |
| `examples/bgfx_hello.coex` | Minimal test: clear screen + debug text + ImGui controls |

## Modified Files

| File | Change |
|------|--------|
| `deps/build_deps.sh` | Add bgfx/bx/bimg clone + build (static libs) |
| `runtime/Makefile` | Add `libcoex_bgfx.a` target with object rules |
| `runtime/coex_ui_shell.h` | Add `coex_ui_shell_get_native_window_handle()` and `_display_handle()` |
| `runtime/coex_ui_shell_macos.m` | Implement native window handle getter (returns NSWindow) |
| `runtime/coex_ui_shell_linux.c` | Implement native window handle getter (returns X11 Window via GLFW) |
| `codegen/core.py` | Add `uses_bgfx()` detection method after `uses_ui()` |
| `coexc.py` | Add bgfx linking block (libcoex_bgfx.a + libbgfx.a + libbimg.a + libbx.a) |

## C API Surface (`coex_bgfx.h`)

All parameters use `int64_t` / `double` / `const char*` per INV-3. All returned strings are `malloc`'d and must be freed per INV-2.

### Lifecycle
- `coex_bgfx_init(int64_t width, int64_t height) -> int64_t` -- Init bgfx with existing UI window (auto-selects Metal/Vulkan/D3D12)
- `coex_bgfx_shutdown() -> void` -- Free all resources, clear handle table
- `coex_bgfx_reset(int64_t width, int64_t height) -> void` -- Handle window resize
- `coex_bgfx_frame() -> int64_t` -- Advance frame, returns frame number

### Views (0-254 for user, 255 reserved for ImGui overlay)
- `coex_bgfx_set_view_rect(int64_t view_id, int64_t x, int64_t y, int64_t w, int64_t h) -> void`
- `coex_bgfx_set_view_clear(int64_t view_id, int64_t flags, int64_t rgba, double depth, int64_t stencil) -> void`
- `coex_bgfx_set_view_transform(int64_t view_id, const char* view_json, const char* proj_json) -> void` -- JSON float[16] arrays per INV-4
- `coex_bgfx_touch(int64_t view_id) -> void`

### Buffers
- `coex_bgfx_create_vertex_buffer(const char* data, int64_t size, const char* layout_json) -> int64_t` -- data is raw bytes; layout is JSON per INV-4; GPU-internal vertex components may be 32-bit floats per INV-3 exception
- `coex_bgfx_create_index_buffer(const char* data, int64_t size, int64_t is_32) -> int64_t` -- GPU indices may be 16-bit per INV-3 exception
- `coex_bgfx_alloc_transient_vertex_buffer(int64_t num, const char* layout_json) -> int64_t`
- `coex_bgfx_alloc_transient_index_buffer(int64_t num, int64_t is_32) -> int64_t`
- `coex_bgfx_destroy_vertex_buffer(int64_t handle) -> void` -- frees handle table entry
- `coex_bgfx_destroy_index_buffer(int64_t handle) -> void`

### Shaders & Programs
- `coex_bgfx_load_shader(const char* path) -> int64_t` -- Load pre-compiled .bin shader file; C reads file, passes to bgfx, frees file buffer
- `coex_bgfx_create_program(int64_t vs, int64_t fs, int64_t destroy_shaders) -> int64_t`
- `coex_bgfx_create_compute_program(int64_t cs, int64_t destroy) -> int64_t`
- `coex_bgfx_destroy_program(int64_t handle) -> void`

### Textures & Uniforms
- `coex_bgfx_create_texture_2d(int64_t w, int64_t h, int64_t mips, int64_t format, const char* data, int64_t size) -> int64_t` -- pixel data may be 8/16/32-bit internally per INV-3 exception
- `coex_bgfx_update_texture_2d(int64_t handle, int64_t mip, int64_t x, int64_t y, int64_t w, int64_t h, const char* data, int64_t size) -> void`
- `coex_bgfx_destroy_texture(int64_t handle) -> void`
- `coex_bgfx_create_uniform(const char* name, int64_t type, int64_t num) -> int64_t`
- `coex_bgfx_set_uniform(int64_t handle, const char* value_json, int64_t num) -> void` -- value as JSON array per INV-4
- `coex_bgfx_destroy_uniform(int64_t handle) -> void`

### Drawing
- `coex_bgfx_set_state(int64_t state) -> void` -- Predefined presets: 0=DEFAULT, 1=ALPHA_BLEND, 2=ADDITIVE, 3=WIREFRAME
- `coex_bgfx_set_transform(const char* mtx_json) -> int64_t` -- JSON float[16] per INV-4
- `coex_bgfx_set_vertex_buffer(int64_t stream, int64_t handle) -> void`
- `coex_bgfx_set_index_buffer(int64_t handle) -> void`
- `coex_bgfx_set_texture(int64_t stage, int64_t uniform, int64_t texture) -> void`
- `coex_bgfx_submit(int64_t view_id, int64_t program, int64_t depth) -> void`

### Compute
- `coex_bgfx_set_compute_buffer(int64_t stage, int64_t handle, int64_t access) -> void`
- `coex_bgfx_dispatch(int64_t view_id, int64_t program, int64_t x, int64_t y, int64_t z) -> void`

### Debug & Query
- `coex_bgfx_set_debug(int64_t flags) -> void` -- 1=WIREFRAME, 4=STATS, 8=TEXT
- `coex_bgfx_dbg_text(int64_t x, int64_t y, int64_t attr, const char* text) -> void`
- `coex_bgfx_dbg_text_clear() -> void`
- `coex_bgfx_get_renderer_name() -> const char*` -- returns static string (no free needed)
- `coex_bgfx_get_caps_json() -> const char*` -- malloc'd, caller must free via `coex_bgfx_free_json()` per INV-2

### Math Helpers (convenience, use bx internally)
- `coex_bgfx_mtx_look_at(...12 doubles...) -> const char*` -- Returns malloc'd JSON float[16], free with `coex_bgfx_free_json()` per INV-2
- `coex_bgfx_mtx_proj(double fovy, double aspect, double near_, double far_) -> const char*` -- same
- `coex_bgfx_mtx_ortho(...6 doubles...) -> const char*` -- same
- `coex_bgfx_mtx_rotate_xyz(...6 doubles...) -> const char*` -- same

### Memory Management
- `coex_bgfx_free_json(const char* json) -> void` -- Frees any malloc'd string returned by bgfx functions (INV-2)

### Shader Approach
Shader files only (no runtime compilation, no embedded defaults). Users compile shaders externally with bgfx's `shaderc` tool to produce platform-specific `.bin` files. `load_shader()` reads these from disk.

## Handle Management

All bgfx native handles (16-bit, INV-3 exception: GPU-internal only) wrapped in `int64_t` handle table (MAX 4096), following the SVG pattern exactly. Handle types: vertex buffer, index buffer, shader, program, texture, uniform, transient VB/IB.

When `destroy_*` is called:
1. The bgfx native handle is destroyed
2. The handle table entry is marked free
3. The int64_t handle value in Coex becomes stale (immutable value per INV-1 — it's not zeroed out, it simply refers to nothing)

## bgfx + ImGui Coexistence

When bgfx is active, it takes over rendering from the native Metal/OpenGL backend:

1. A flag `bgfx_active` in `coex_ui.c` causes `end_frame` to skip native Metal/GL rendering
2. bgfx owns the swapchain via the shell's native window handle
3. ImGui draw data is converted to bgfx transient buffers and submitted on view 255 (highest = renders last)
4. `coex_bgfx_frame()` calls `bgfx::frame()` which presents everything

Frame loop with bgfx:
```
shell_process_events() -> imgui_new_frame() -> [user widgets] -> imgui_render()
-> [user 3D draw calls to views 0-254] -> bgfx_render_imgui(view 255) -> bgfx_frame()
```

## FFI Membrane Pattern (INV-2 Detail)

Every function returning data follows this pattern in `lib/bgfx.coex`:

```
# C side: malloc's a JSON string
# Coex wrapper: captures value, frees C allocation
func get_caps() -> json
    result_str = coex_bgfx_get_caps_json()    # C malloc'd
    parsed = json.parse(result_str)             # copied to immutable heap
    coex_bgfx_free_json(result_str)             # free C-side memory
    return parsed                               # pure Coex value
~

# For math helpers returning matrices:
func look_at(eye_x: float, ...) -> string
    result = coex_bgfx_mtx_look_at(eye_x, ...)  # C malloc'd JSON
    # codegen layer copies string to immutable heap
    # wrapper calls free:
    coex_bgfx_free_json(result)
    return result  # Coex now owns an immutable copy
~
```

Functions that only accept data (set_*, submit, dispatch) consume their arguments immediately — bgfx copies to GPU, no persistent C allocation needed. No leak risk on the inbound path.

## Build System

### deps/build_deps.sh
- Clone bx, bimg, bgfx from GitHub (depth 1)
- Build using GENie (bgfx's build tool) or bgfx.cmake for Apple Silicon
- Output: `deps/lib/libbgfx.a`, `deps/lib/libbimg.a`, `deps/lib/libbx.a`
- Headers copied to `deps/include/bgfx/`

### Makefile
- New target `bgfx:` builds `libcoex_bgfx.a` from objects in `runtime/bgfx/`
- Platform detection selects Metal frameworks (macOS) or Vulkan/GL libs (Linux)
- `BGFX_DEPS_AVAILABLE` check for conditional compilation

### Compiler Linking (coexc.py)
- `uses_bgfx()` checks for `coex_bgfx_*` extern symbols
- Links: `libcoex_bgfx.a` + `libbgfx.a` + `libbimg.a` + `libbx.a` + `-lc++`
- Nested inside `uses_ui()` block (bgfx requires shell layer)

## Implementation Order

1. **Shell layer**: Add `get_native_window_handle()` to shell header + macOS/Linux impls
2. **Build deps**: Add bgfx/bx/bimg section to `build_deps.sh`, verify it builds
3. **C API**: Create `coex_bgfx.h` header (all int64_t/double/const char* per INV-3)
4. **Implementation**: Create `coex_bgfx.c` (handle table, JSON parsing, free pattern per INV-2) and `bgfx_c_bridge.cpp`
5. **Makefile**: Add build targets, verify `libcoex_bgfx.a` compiles
6. **ImGui bridge**: Create `coex_bgfx_imgui.cpp` for ImGui-over-bgfx rendering
7. **Compiler**: Add `uses_bgfx()` to `core.py`, add linking to `coexc.py`
8. **Coex API**: Create `lib/bgfx.coex` with extern declarations + wrappers (free pattern per INV-2)

## Verification

1. `deps/build_deps.sh` completes and produces `libbgfx.a`, `libbimg.a`, `libbx.a`
2. `cd runtime && make bgfx` produces `libcoex_bgfx.a`
3. A test program `examples/bgfx_hello.coex` that:
   - Initializes UI + bgfx
   - Clears view 0 to a color
   - Prints debug text via `bgfx.dbg_text()`
   - Shows ImGui controls alongside
   - Compiles and runs: `python3 coexc.py examples/bgfx_hello.coex -o bgfx_hello && ./bgfx_hello`
4. **INV-2 verification**: No memory leaks — every `const char*` returned by C is freed after Coex captures the value
5. **INV-3 verification**: No 32-bit or 16-bit types at the FFI boundary — only int64_t, double, const char*
