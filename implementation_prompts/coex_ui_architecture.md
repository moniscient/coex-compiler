# Coex UI System Architecture

## Overview

The Coex UI system provides cross-platform graphical user interface capabilities using a JSON-driven, immediate-mode architecture. The system is built on two proven technologies: Dear ImGui for widget logic and layout, and Skia for rendering. This combination delivers high performance, cross-platform consistency, and a clean separation between UI definition and application logic.

## Design Principles

**JSON as the Single Source of Truth**

All UI state lives in a json object owned by the programmer. The UI system does not maintain hidden widget state. Each render call reads the current json state, produces a frame, and returns any state modifications as a new json object. This aligns with Coex's persistent data structure philosophy—state changes produce new values rather than mutating existing ones.

**Separation of Concerns**

UI layout and structure are defined as json data, which can be created by designers using visual tools, loaded from files, fetched from servers, or constructed programmatically. Programmers provide behavior bindings (what happens when buttons are clicked) and state bindings (which json fields map to which widgets). Neither designers nor programmers need deep knowledge of the other's domain.

**Immediate Mode Rendering**

The UI is reconstructed every frame from the json description. This eliminates state synchronization bugs, simplifies reasoning about UI behavior, and maps naturally to reactive programming patterns. Despite rebuilding the UI each frame, performance is excellent because Dear ImGui produces optimized vertex buffers with minimal draw calls.

## System Architecture

```
┌─────────────────────────────────────────────────────────────────────────┐
│                         Application Layer                               │
│  ┌─────────────────────────────────────────────────────────────────┐    │
│  │  layout: json          state: json           actions: Map       │    │
│  │  (UI structure)        (UI values)           (callbacks)        │    │
│  └─────────────────────────────────────────────────────────────────┘    │
└─────────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
┌─────────────────────────────────────────────────────────────────────────┐
│                         ui Module (Coex)                                │
│  ┌─────────────────────────────────────────────────────────────────┐    │
│  │  ui.render(layout, state, actions) -> json                      │    │
│  │  - Walks layout json                                            │    │
│  │  - Emits Dear ImGui calls                                       │    │
│  │  - Collects state changes                                       │    │
│  │  - Returns new state json                                       │    │
│  └─────────────────────────────────────────────────────────────────┘    │
└─────────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
┌─────────────────────────────────────────────────────────────────────────┐
│                         Dear ImGui (C/C++)                              │
│  ┌─────────────────────────────────────────────────────────────────┐    │
│  │  - Processes widget logic                                       │    │
│  │  - Handles input (mouse, keyboard, gamepad)                     │    │
│  │  - Computes layout                                              │    │
│  │  - Produces vertex buffers + draw commands                      │    │
│  └─────────────────────────────────────────────────────────────────┘    │
└─────────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
┌─────────────────────────────────────────────────────────────────────────┐
│                         Skia (C++)                                      │
│  ┌─────────────────────────────────────────────────────────────────┐    │
│  │  - Receives vertex buffers from ImGui                           │    │
│  │  - Renders textured triangles                                   │    │
│  │  - Outputs to GPU surface or software buffer                    │    │
│  └─────────────────────────────────────────────────────────────────┘    │
└─────────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
┌─────────────────────────────────────────────────────────────────────────┐
│                         Platform Shell                                  │
│  ┌───────────┐  ┌───────────┐  ┌───────────┐  ┌───────────┐             │
│  │  Windows  │  │   macOS   │  │   Linux   │  │    Web    │             │
│  │  (Win32)  │  │  (Cocoa)  │  │(X11/Wylnd)│  │(Emscriptn)│             │
│  └───────────┘  └───────────┘  └───────────┘  └───────────┘             │
│  - Window management                                                    │
│  - Input event collection                                               │
│  - GPU context (Metal, Vulkan, OpenGL, WebGL)                           │
└─────────────────────────────────────────────────────────────────────────┘
```

## JSON Layout Schema

UI layouts are defined as json objects with a hierarchical widget structure. Each widget has a `type` field and type-specific properties.

### Basic Structure

```json
{
    "type": "window",
    "title": "Application",
    "width": 800,
    "height": 600,
    "children": [
        { "type": "text", "content": "Hello, World!" },
        { "type": "button", "label": "Click Me", "action": "on_click" }
    ]
}
```

### Widget Types

#### Container Widgets

**window** - Top-level application window
```json
{
    "type": "window",
    "title": "Window Title",
    "id": "main_window",
    "width": 800,
    "height": 600,
    "menubar": true,
    "resizable": true,
    "children": []
}
```

**panel** - Collapsible panel within a window
```json
{
    "type": "panel",
    "title": "Settings",
    "id": "settings_panel",
    "collapsed": false,
    "children": []
}
```

**group** - Visual grouping without title
```json
{
    "type": "group",
    "children": []
}
```

**horizontal** - Horizontal layout container
```json
{
    "type": "horizontal",
    "spacing": 8,
    "children": []
}
```

**vertical** - Vertical layout container
```json
{
    "type": "vertical",
    "spacing": 4,
    "children": []
}
```

**tabs** - Tabbed container
```json
{
    "type": "tabs",
    "bind": "active_tab",
    "children": [
        { "type": "tab", "label": "Tab 1", "children": [] },
        { "type": "tab", "label": "Tab 2", "children": [] }
    ]
}
```

**scroll** - Scrollable region
```json
{
    "type": "scroll",
    "height": 200,
    "children": []
}
```

#### Display Widgets

**text** - Static text display
```json
{
    "type": "text",
    "content": "Static text here",
    "color": "#FFFFFF",
    "wrap": true
}
```

**text** - Dynamic text with binding
```json
{
    "type": "text",
    "bind": "status_message"
}
```

**image** - Image display
```json
{
    "type": "image",
    "source": "icon.png",
    "width": 64,
    "height": 64
}
```

**separator** - Visual separator line
```json
{
    "type": "separator"
}
```

**spacer** - Empty space
```json
{
    "type": "spacer",
    "width": 20,
    "height": 10
}
```

#### Input Widgets

**button** - Clickable button
```json
{
    "type": "button",
    "label": "Save",
    "action": "on_save",
    "enabled": true
}
```

**checkbox** - Boolean toggle
```json
{
    "type": "checkbox",
    "label": "Enable feature",
    "bind": "feature_enabled"
}
```

**radio** - Radio button group
```json
{
    "type": "radio",
    "label": "Selection",
    "bind": "selected_option",
    "options": [
        { "label": "Option A", "value": "a" },
        { "label": "Option B", "value": "b" },
        { "label": "Option C", "value": "c" }
    ]
}
```

**slider** - Numeric slider
```json
{
    "type": "slider",
    "label": "Volume",
    "bind": "volume",
    "min": 0.0,
    "max": 1.0,
    "step": 0.01
}
```

**slider_int** - Integer slider
```json
{
    "type": "slider_int",
    "label": "Count",
    "bind": "item_count",
    "min": 0,
    "max": 100
}
```

**input_text** - Single-line text input
```json
{
    "type": "input_text",
    "label": "Name",
    "bind": "user_name",
    "placeholder": "Enter your name",
    "max_length": 100
}
```

**input_text_multiline** - Multi-line text input
```json
{
    "type": "input_text_multiline",
    "label": "Description",
    "bind": "description",
    "height": 100
}
```

**input_number** - Numeric input
```json
{
    "type": "input_number",
    "label": "Amount",
    "bind": "amount",
    "min": 0,
    "max": 1000,
    "step": 1
}
```

**dropdown** - Dropdown selection
```json
{
    "type": "dropdown",
    "label": "Country",
    "bind": "selected_country",
    "options": [
        { "label": "United States", "value": "us" },
        { "label": "Canada", "value": "ca" },
        { "label": "Mexico", "value": "mx" }
    ]
}
```

**listbox** - Scrollable list selection
```json
{
    "type": "listbox",
    "label": "Files",
    "bind": "selected_file",
    "items_bind": "file_list",
    "height": 150
}
```

**color_picker** - Color selection
```json
{
    "type": "color_picker",
    "label": "Background Color",
    "bind": "bg_color",
    "alpha": true
}
```

#### Menu Widgets

**menubar** - Menu bar container
```json
{
    "type": "menubar",
    "children": [
        {
            "type": "menu",
            "label": "File",
            "children": [
                { "type": "menu_item", "label": "New", "action": "file_new", "shortcut": "Ctrl+N" },
                { "type": "menu_item", "label": "Open", "action": "file_open", "shortcut": "Ctrl+O" },
                { "type": "separator" },
                { "type": "menu_item", "label": "Exit", "action": "file_exit" }
            ]
        }
    ]
}
```

#### Data Display Widgets

**table** - Data table
```json
{
    "type": "table",
    "columns": [
        { "header": "Name", "field": "name", "width": 150 },
        { "header": "Value", "field": "value", "width": 100 },
        { "header": "Status", "field": "status", "width": 80 }
    ],
    "rows_bind": "table_data",
    "selectable": true,
    "selected_bind": "selected_row"
}
```

**tree** - Hierarchical tree view
```json
{
    "type": "tree",
    "nodes_bind": "tree_data",
    "selected_bind": "selected_node"
}
```

**progress** - Progress bar
```json
{
    "type": "progress",
    "bind": "progress_value",
    "min": 0,
    "max": 100,
    "show_text": true
}
```

#### Dialog Widgets

**popup** - Modal popup
```json
{
    "type": "popup",
    "id": "confirm_dialog",
    "title": "Confirm",
    "visible_bind": "show_confirm",
    "children": [
        { "type": "text", "content": "Are you sure?" },
        { "type": "horizontal", "children": [
            { "type": "button", "label": "Yes", "action": "confirm_yes" },
            { "type": "button", "label": "No", "action": "confirm_no" }
        ]}
    ]
}
```

**tooltip** - Hover tooltip
```json
{
    "type": "tooltip",
    "target": "widget_id",
    "content": "This is helpful information"
}
```

### Binding Syntax

Widgets connect to state via the `bind` property, which specifies a path into the state json:

```json
{ "type": "slider", "bind": "audio.volume" }
```

This binds to `state.audio.volume`. When the slider moves, the render function returns a new state with the updated value at that path.

For read-only display, use `bind`. For actions (button clicks, menu selections), use `action` which references a key in the actions map.

### Conditional Rendering

Widgets can be conditionally shown based on state:

```json
{
    "type": "panel",
    "title": "Advanced Options",
    "visible_if": "show_advanced"
}
```

The `visible_if` property references a boolean in the state json.

### Dynamic Lists

For rendering lists of items:

```json
{
    "type": "foreach",
    "items_bind": "todo_items",
    "item_var": "item",
    "index_var": "i",
    "template": {
        "type": "horizontal",
        "children": [
            { "type": "checkbox", "bind": "item.completed" },
            { "type": "text", "bind": "item.title" },
            { "type": "button", "label": "Delete", "action": "delete_item", "action_data": "i" }
        ]
    }
}
```

## State Management

### State Structure

Application state is a json object containing all values that widgets read and write:

```coex
state: json = {
    # Form values
    user_name: "",
    email: "",
    
    # UI state
    active_tab: 0,
    show_advanced: false,
    
    # Data
    items: [
        { id: 1, title: "First item", completed: false },
        { id: 2, title: "Second item", completed: true }
    ],
    
    # Selection state
    selected_item: null
}
```

### State Updates

The render function returns a new state with any modifications:

```coex
func main() -> int
    state: json = initial_state()
    layout: json = json(posix.read_file("app.ui.json"))
    
    ui.init()
    
    loop
        # Render returns new state with any changes
        state = ui.render(layout, state, actions)
        
        if ui.should_close()
            break
        ~
    ~
    
    ui.shutdown()
    return 0
~
```

Because json is a persistent data structure, this is efficient—only changed paths are copied.

### Action Handlers

Actions are functions invoked when buttons are clicked or menu items selected:

```coex
actions: Map<string, func(json) -> json> = {
    "add_item": func(state: json) -> json
        new_item: json = { id: next_id(), title: "New Item", completed: false }
        return state.set("items", state.items.append(new_item))
    ~,
    
    "delete_item": func(state: json) -> json
        index: int = state.action_data as int
        return state.set("items", state.items.remove(index))
    ~,
    
    "save": func(state: json) -> json
        save_to_file(state)
        return state
    ~
}
```

Actions receive the current state and return the new state. This keeps all state transitions explicit and testable.

## Input Handling

Dear ImGui uses a simple input model: the application feeds raw input state each frame, and ImGui internally handles all hit testing, click detection, drag tracking, and focus management.

### Input Flow

```
Platform Shell                    Dear ImGui                     Widget Return Values
─────────────────────────────────────────────────────────────────────────────────────

Mouse at (324, 156) ─────────────► io.MousePos = (324, 156)       
                                                                  
Left button pressed ─────────────► io.MouseDown[0] = true         
                                                                  
Left button released ────────────► io.MouseDown[0] = false        
                                                                  
                                   [ImGui processes frame]        
                                   [Checks: mouse over button?]   
                                   [Checks: click started here?]  
                                   [Checks: click ended here?]    
                                                                  
                                   Button("Save") ────────────────► returns true!
```

### What Gets Fed to ImGui

Each frame, the platform shell provides raw input state to ImGui's IO structure:

```coex
# Mouse position (screen coordinates relative to window)
igIOSetMousePos(mouse_x, mouse_y)

# Mouse button states (up to 5 buttons)
igIOSetMouseDown(0, left_button_pressed)    # Left
igIOSetMouseDown(1, right_button_pressed)   # Right
igIOSetMouseDown(2, middle_button_pressed)  # Middle

# Mouse wheel (vertical and horizontal)
igIOSetMouseWheel(wheel_y)
igIOSetMouseWheelH(wheel_x)

# Keyboard modifiers
igIOSetKeyCtrl(ctrl_pressed)
igIOSetKeyShift(shift_pressed)
igIOSetKeyAlt(alt_pressed)
igIOSetKeySuper(super_pressed)  # Cmd on Mac, Win key on Windows

# Individual key states
igIOSetKeyDown(key_code, is_pressed)

# Text input (for text fields - Unicode characters)
igIOAddInputCharacter(unicode_codepoint)
```

### ImGui's Internal Hit Testing

When you call a widget function, ImGui automatically:

1. Knows the widget's screen rectangle (computed during layout)
2. Checks if `io.MousePos` is inside that rectangle
3. Tracks mouse button state transitions across frames
4. Determines if a click started AND ended on this widget
5. Returns true only when the interaction is complete

```coex
# ImGui tracks all of this internally:
# - Is mouse currently hovering this widget?
# - Did mouse button press start on this widget?
# - Did mouse button release on this widget?
# - Is this widget currently being dragged?
# - Does this widget have keyboard focus?

if button("Save")
    # Returns true on the frame when:
    # 1. Mouse is over button AND
    # 2. Left mouse button was just released AND
    # 3. The click originally started on this same button
    # 
    # This prevents "click tunneling" where you click elsewhere
    # and drag onto a button before releasing
~

changed, value: (bool, float) = slider("Volume", current, 0.0, 1.0)
if changed
    # Returns true every frame while dragging
    # 'value' is updated based on mouse x position relative to slider
~
```

### Widget Interaction States

After rendering a widget, ImGui can report its interaction state:

```coex
button("My Button")

# Query states of the last widget
is_hovered: bool = igIsItemHovered()   # Mouse is over widget
is_active: bool = igIsItemActive()     # Widget is being interacted with
is_focused: bool = igIsItemFocused()   # Widget has keyboard focus
is_clicked: bool = igIsItemClicked()   # Widget was just clicked
is_edited: bool = igIsItemEdited()     # Widget value changed this frame
```

### Exposing Hover State in JSON Layout

The layout system can expose hover information for tooltips and visual feedback:

```json
{
    "type": "button",
    "label": "Hover Me",
    "action": "on_click",
    "tooltip": "Click to save your changes"
}
```

The tooltip is automatically shown when ImGui detects the mouse hovering over the button.

For more complex hover behavior:

```json
{
    "type": "button",
    "id": "help_button",
    "label": "?",
    "on_hover_enter": "show_help_panel",
    "on_hover_exit": "hide_help_panel"
}
```

### Tracking UI State in the State Object

The render function can optionally populate a special `_ui` section with interaction state:

```coex
# After rendering, state might contain:
state: json = {
    _ui: {
        hovered: "save_button",      # ID of currently hovered widget
        focused: "name_input",       # ID of widget with keyboard focus
        active: "volume_slider"      # ID of widget being interacted with
    },
    # ... application state
}
```

This allows the application to react to UI state in the next frame if needed.

### Frame Cycle with Input

The complete frame cycle including input handling:

```coex
func ui.render(layout: json, state: json, actions: Map<string, func(json) -> json>) -> json
    # 1. Collect input from platform shell
    feed_input_to_imgui()
    
    # 2. Start ImGui frame (processes input, prepares for widgets)
    igNewFrame()
    
    # 3. Walk layout json, emit widget calls
    #    Each widget function internally checks mouse/keyboard state
    #    Buttons return true when clicked
    #    Sliders/inputs modify bound values when dragged/edited
    new_state: json = render_widget_tree(layout, state, actions)
    
    # 4. End ImGui frame, finalize layout, generate draw commands
    igRender()
    
    # 5. Get draw data and render with Skia
    draw_data: pointer = igGetDrawData()
    render_with_skia(draw_data)
    
    # 6. Present to screen (
    coex_ui_shell_present()
    
    return new_state
~

func feed_input_to_imgui() -> ()
    # Get mouse position from platform
    x: float = 0.0
    y: float = 0.0
    coex_ui_shell_get_mouse_pos(x.ptr(), y.ptr())
    igIOSetMousePos(x, y)
    
    # Get mouse button states
    igIOSetMouseDown(0, coex_ui_shell_get_mouse_button(0))
    igIOSetMouseDown(1, coex_ui_shell_get_mouse_button(1))
    igIOSetMouseDown(2, coex_ui_shell_get_mouse_button(2))
    
    # Get mouse wheel
    igIOSetMouseWheel(coex_ui_shell_get_mouse_wheel())
    
    # Get keyboard state
    # (platform shell tracks key states and text input)
    coex_ui_shell_feed_keyboard_to_imgui()
~
```

### Drag and Drop

ImGui provides built-in drag and drop support. The JSON layout can express this declaratively:

```json
{
    "type": "list",
    "items_bind": "inventory_items",
    "item_template": {
        "type": "horizontal",
        "draggable": true,
        "drag_type": "inventory_item",
        "drag_data_bind": "item.id",
        "children": [
            { "type": "image", "bind": "item.icon" },
            { "type": "text", "bind": "item.name" }
        ]
    }
}
```

```json
{
    "type": "panel",
    "title": "Equipment",
    "drop_target": true,
    "accept_types": ["inventory_item"],
    "on_drop": "equip_item"
}
```

When an item is dragged from the list and dropped on the equipment panel, the `equip_item` action is invoked with the dragged item's ID available in `state.action_data`.

### Mouse Cursor

ImGui can request different mouse cursors based on context (resize handles, text input, etc.). The platform shell responds to these requests:

```coex
func update_cursor() -> ()
    cursor: int = igGetMouseCursor()
    match cursor
        case IMGUI_CURSOR_ARROW:
            coex_ui_shell_set_cursor(CURSOR_ARROW)
        ~
        case IMGUI_CURSOR_TEXT_INPUT:
            coex_ui_shell_set_cursor(CURSOR_IBEAM)
        ~
        case IMGUI_CURSOR_RESIZE_NS:
            coex_ui_shell_set_cursor(CURSOR_RESIZE_VERTICAL)
        ~
        case IMGUI_CURSOR_RESIZE_EW:
            coex_ui_shell_set_cursor(CURSOR_RESIZE_HORIZONTAL)
        ~
        case IMGUI_CURSOR_HAND:
            coex_ui_shell_set_cursor(CURSOR_HAND)
        ~
        case _:
            coex_ui_shell_set_cursor(CURSOR_ARROW)
        ~
    ~
~
```

### Focus and Keyboard Navigation

ImGui handles keyboard focus automatically. Tab moves between focusable widgets, Enter activates buttons, arrow keys navigate within widgets (sliders, lists), and Escape closes popups.

The layout can influence focus behavior:

```json
{
    "type": "input_text",
    "id": "search_field",
    "bind": "search_query",
    "autofocus": true
}
```

The `autofocus` property requests initial keyboard focus when the UI appears.

### Input Consumption

ImGui tracks whether it wants to consume input, which is useful when embedding UI in a game or 3D application:

```coex
# After rendering UI, check if ImGui wants input
if ui.wants_keyboard()
    # Don't process keyboard for game controls
~

if ui.wants_mouse()
    # Don't process mouse for camera/game controls
~
```

This allows the UI to coexist with other input consumers without conflicts.

## The ui Module API

### Initialization and Shutdown

```coex
# Initialize the UI system
# Creates window, initializes ImGui and Skia
func ui.init(config: json) -> Result<(), string>

# Configuration options
config: json = {
    title: "My Application",
    width: 1280,
    height: 720,
    resizable: true,
    vsync: true,
    high_dpi: true,
    theme: "dark"  # or "light", "classic"
}

# Shutdown the UI system
func ui.shutdown() -> ()
```

### Main Render Loop

```coex
# Render one frame
# Returns new state with any modifications from user interaction
func ui.render(
    layout: json, 
    state: json, 
    actions: Map<string, func(json) -> json>
) -> json

# Check if window close was requested
func ui.should_close() -> bool

# Request window close
func ui.request_close() -> ()
```

### Layout Loading

```coex
# Load layout from json (already parsed)
func ui.set_layout(layout: json) -> ()

# Validate layout structure
func ui.validate_layout(layout: json) -> Result<(), [string]>
```

### Theming

```coex
# Set color theme
func ui.set_theme(theme: string) -> ()  # "dark", "light", "classic"

# Custom colors
func ui.set_colors(colors: json) -> ()

colors: json = {
    background: "#1E1E1E",
    text: "#FFFFFF",
    primary: "#007ACC",
    secondary: "#3E3E42",
    accent: "#0E639C",
    error: "#F44747",
    warning: "#CCA700",
    success: "#89D185"
}

# Custom fonts
func ui.load_font(name: string, path: string, size: float) -> Result<(), string>
func ui.set_default_font(name: string) -> ()
```

### Utility Functions

```coex
# Get window dimensions
func ui.window_size() -> (int, int)

# Get mouse position
func ui.mouse_position() -> (float, float)

# Check if UI wants keyboard/mouse input
# (useful when embedding in game/3D app)
func ui.wants_keyboard() -> bool
func ui.wants_mouse() -> bool

# Clipboard
func ui.clipboard_get() -> string
func ui.clipboard_set(text: string) -> ()

# File dialogs
func ui.open_file_dialog(filters: [string]) -> string?
func ui.save_file_dialog(default_name: string, filters: [string]) -> string?
func ui.select_folder_dialog() -> string?
```

## Platform Integration

### Platform Shells

Each platform requires a shell that provides window management and a rendering context. The shells are implemented in platform-native code and linked with the Coex application.

**Windows (Win32 + Direct3D/Vulkan)**
```
coex_ui_shell_windows.lib
- CreateWindow with WS_OVERLAPPEDWINDOW
- Direct3D 11/12 or Vulkan context
- WM_* message handling for input
```

**macOS (Cocoa + Metal)**
```
coex_ui_shell_macos.dylib
- NSWindow / NSView
- Metal rendering context
- NSEvent handling for input
```

**Linux (X11/Wayland + OpenGL/Vulkan)**
```
coex_ui_shell_linux.so
- GLFW or SDL for window management
- OpenGL 3.3+ or Vulkan context
- X11/Wayland input handling
```

**Web (Emscripten + WebGL)**
```
coex_ui_shell_web.js + .wasm
- HTML5 Canvas element
- WebGL 2.0 context
- DOM event handling for input
- requestAnimationFrame for render loop
```

### Shell API

The shells expose a minimal C API that the ui module calls:

```c
// Initialization
int coex_ui_shell_init(const char* title, int width, int height, int flags);
void coex_ui_shell_shutdown(void);

// Frame management
void coex_ui_shell_begin_frame(void);
void coex_ui_shell_end_frame(void);
int coex_ui_shell_should_close(void);

// Input state
void coex_ui_shell_get_mouse_pos(float* x, float* y);
int coex_ui_shell_get_mouse_button(int button);
int coex_ui_shell_get_key(int key);
const char* coex_ui_shell_get_text_input(void);

// Rendering surface
void* coex_ui_shell_get_skia_surface(void);
void coex_ui_shell_present(void);

// Window management
void coex_ui_shell_get_window_size(int* width, int* height);
void coex_ui_shell_set_window_size(int width, int height);
void coex_ui_shell_set_window_title(const char* title);

// Clipboard
const char* coex_ui_shell_clipboard_get(void);
void coex_ui_shell_clipboard_set(const char* text);
```

## Implementation Layers

### Layer 1: C Bindings to Dear ImGui

The ui module uses extern declarations to call Dear ImGui's C API (cimgui):

```coex
# imgui.coex - Low-level ImGui bindings

extern func igCreateContext() -> pointer
extern func igDestroyContext(ctx: pointer) -> ()
extern func igNewFrame() -> ()
extern func igRender() -> ()
extern func igGetDrawData() -> pointer

extern func igBegin(name: string, open: pointer, flags: int) -> bool
extern func igEnd() -> ()
extern func igButton(label: string) -> bool
extern func igSliderFloat(label: string, v: pointer, min: float, max: float) -> bool
extern func igInputText(label: string, buf: pointer, buf_size: int, flags: int) -> bool
extern func igCheckbox(label: string, v: pointer) -> bool
# ... etc
```

### Layer 2: Coex Widget Wrappers

Higher-level Coex functions wrap the C bindings with Coex-native types:

```coex
# widgets.coex - Coex-friendly widget functions

func button(label: string) -> bool
    return igButton(label)
~

func slider(label: string, value: float, min: float, max: float) -> (bool, float)
    buf: [float] = [value]
    changed: bool = igSliderFloat(label, buf.ptr(), min, max)
    return (changed, buf[0])
~

func checkbox(label: string, value: bool) -> (bool, bool)
    buf: [bool] = [value]
    changed: bool = igCheckbox(label, buf.ptr())
    return (changed, buf[0])
~

func input_text(label: string, value: string, max_len: int) -> (bool, string)
    buf: [byte] = value.to_bytes().resize(max_len)
    changed: bool = igInputText(label, buf.ptr(), max_len, 0)
    return (changed, string.from_bytes(buf))
~
```

### Layer 3: JSON Layout Interpreter

The layout interpreter walks the json layout and emits widget calls:

```coex
# layout.coex - JSON layout interpreter

func render_widget(widget: json, state: json, actions: Map<string, func(json) -> json>) -> json
    match widget.type as string
        case "text":
            render_text(widget, state)
            return state
        ~
        case "button":
            if render_button(widget)
                action_name: string = widget.action as string
                if actions.has(action_name)
                    return actions.get(action_name)(state)
                ~
            ~
            return state
        ~
        case "slider":
            return render_slider(widget, state)
        ~
        case "checkbox":
            return render_checkbox(widget, state)
        ~
        case "horizontal":
            return render_horizontal(widget, state, actions)
        ~
        case "vertical":
            return render_vertical(widget, state, actions)
        ~
        # ... other widget types
        case _:
            # Unknown widget type, skip
            return state
        ~
    ~
~

func render_slider(widget: json, state: json) -> json
    label: string = widget.label as string? ?? ""
    bind_path: string = widget.bind as string
    current: float = state.get_path(bind_path) as float? ?? 0.0
    min: float = widget.min as float? ?? 0.0
    max: float = widget.max as float? ?? 1.0
    
    changed, new_value: (bool, float) = slider(label, current, min, max)
    
    if changed
        return state.set_path(bind_path, new_value)
    ~
    return state
~
```

### Layer 4: Skia Rendering Backend

The ImGui draw data is rendered via Skia:

```coex
# skia_backend.coex - Render ImGui draw data with Skia

func render_imgui_with_skia(draw_data: pointer, surface: pointer) -> ()
    canvas: pointer = skia_surface_get_canvas(surface)
    
    cmd_lists_count: int = imgui_draw_data_cmd_lists_count(draw_data)
    
    i: int = 0
    loop
        if i >= cmd_lists_count
            break
        ~
        
        cmd_list: pointer = imgui_draw_data_get_cmd_list(draw_data, i)
        render_cmd_list(canvas, cmd_list)
        
        i = i + 1
    ~
~

func render_cmd_list(canvas: pointer, cmd_list: pointer) -> ()
    # Extract vertex buffer
    vtx_buffer: pointer = imgui_draw_list_vtx_buffer(cmd_list)
    vtx_count: int = imgui_draw_list_vtx_count(cmd_list)
    
    # Extract index buffer  
    idx_buffer: pointer = imgui_draw_list_idx_buffer(cmd_list)
    idx_count: int = imgui_draw_list_idx_count(cmd_list)
    
    # Convert to Skia vertices and render
    # (positions, UVs, colors -> SkVertices)
    # Each draw command specifies clip rect and texture
    
    cmd_count: int = imgui_draw_list_cmd_count(cmd_list)
    j: int = 0
    loop
        if j >= cmd_count
            break
        ~
        
        cmd: pointer = imgui_draw_list_get_cmd(cmd_list, j)
        render_draw_cmd(canvas, cmd, vtx_buffer, idx_buffer)
        
        j = j + 1
    ~
~
```

## Example Application

### Layout File (app.ui.json)

```json
{
    "type": "window",
    "title": "Todo Application",
    "width": 600,
    "height": 400,
    "children": [
        {
            "type": "horizontal",
            "spacing": 8,
            "children": [
                {
                    "type": "input_text",
                    "bind": "new_item_text",
                    "placeholder": "Enter a new todo...",
                    "flex": 1
                },
                {
                    "type": "button",
                    "label": "Add",
                    "action": "add_item"
                }
            ]
        },
        {
            "type": "separator"
        },
        {
            "type": "scroll",
            "flex": 1,
            "children": [
                {
                    "type": "foreach",
                    "items_bind": "items",
                    "item_var": "item",
                    "index_var": "i",
                    "template": {
                        "type": "horizontal",
                        "spacing": 8,
                        "children": [
                            {
                                "type": "checkbox",
                                "bind": "item.completed"
                            },
                            {
                                "type": "text",
                                "bind": "item.title",
                                "flex": 1,
                                "style_if": {
                                    "item.completed": { "strikethrough": true, "color": "#888888" }
                                }
                            },
                            {
                                "type": "button",
                                "label": "Delete",
                                "action": "delete_item",
                                "action_data_bind": "i"
                            }
                        ]
                    }
                }
            ]
        },
        {
            "type": "separator"
        },
        {
            "type": "horizontal",
            "children": [
                {
                    "type": "text",
                    "content": "Total: "
                },
                {
                    "type": "text",
                    "bind": "item_count"
                },
                {
                    "type": "spacer",
                    "flex": 1
                },
                {
                    "type": "button",
                    "label": "Clear Completed",
                    "action": "clear_completed"
                }
            ]
        }
    ]
}
```

### Application Code (todo.coex)

```coex
import ui
import posix

type TodoItem:
    id: int
    title: string
    completed: bool
~

func main() -> int
    # Load layout
    layout: json = json(posix.read_file("app.ui.json"))
    
    # Initialize state
    state: json = {
        new_item_text: "",
        items: [],
        item_count: 0,
        next_id: 1
    }
    
    # Define actions
    actions: Map<string, func(json) -> json> = {
        "add_item": add_item,
        "delete_item": delete_item,
        "clear_completed": clear_completed
    }
    
    # Initialize UI
    match ui.init({ title: "Todo App", width: 600, height: 400 })
        case Ok(_):
            # continue
        ~
        case Err(msg):
            posix.print("Failed to initialize UI: {msg}")
            return 1
        ~
    ~
    
    # Main loop
    loop
        state = ui.render(layout, state, actions)
        state = update_derived_state(state)
        
        if ui.should_close()
            break
        ~
    ~
    
    ui.shutdown()
    return 0
~

func add_item(state: json) -> json
    text: string = state.new_item_text as string
    if text.len() == 0
        return state
    ~
    
    new_item: json = {
        id: state.next_id as int,
        title: text,
        completed: false
    }
    
    return state
        .set("items", state.items.append(new_item))
        .set("new_item_text", "")
        .set("next_id", (state.next_id as int) + 1)
~

func delete_item(state: json) -> json
    index: int = state.action_data as int
    items: json = state.items
    new_items: json = items.remove(index)
    return state.set("items", new_items)
~

func clear_completed(state: json) -> json
    items: [json] = state.items as [json]
    filtered: [json] = items.filter(func(item: json) -> bool
        return !(item.completed as bool)
    ~)
    return state.set("items", filtered)
~

func update_derived_state(state: json) -> json
    count: int = (state.items as [json]).len()
    return state.set("item_count", count)
~
```

## Performance Considerations

### Efficient State Updates

Because json is a persistent data structure, only the changed paths are copied during state updates. A slider moving doesn't cause the entire state tree to be recreated.

### Minimal Draw Calls

Dear ImGui batches draw calls efficiently. A typical frame results in only a handful of draw calls regardless of widget count.

### Layout Caching

While the UI is conceptually rebuilt every frame, Dear ImGui internally caches layout calculations and only recomputes when needed.

### Skip Unchanged Subtrees

The layout interpreter can skip rendering entire subtrees whose inputs haven't changed, reducing work per frame.

## Future Extensions

### Visual Layout Editor

A standalone tool that allows designers to visually construct layouts and export them as json files.

### Hot Reload

Watch layout files for changes and reload them without restarting the application, enabling rapid iteration.

### Custom Widgets

An API for registering custom widget types implemented in Coex:

```coex
ui.register_widget("my_widget", func(widget: json, state: json) -> json
    # Custom rendering and interaction logic
    return state
~)
```

### Animation System

A declarative animation system integrated with the json layout:

```json
{
    "type": "panel",
    "animate": {
        "opacity": { "from": 0, "to": 1, "duration": 0.3 }
    }
}
```

### Accessibility

Screen reader support and keyboard navigation following platform conventions.

## Dependencies

**Required:**
- Dear ImGui (MIT license) - Widget logic and layout
- Skia (BSD license) - 2D rendering
- Platform libraries (GLFW/SDL or native) - Window and input

**Build Outputs:**
- `libcoex_ui.a` / `coex_ui.lib` - Static library for linking
- Platform shell libraries per target

## Conclusion

This architecture provides a clean, data-driven approach to GUI development in Coex. By combining the immediate-mode paradigm of Dear ImGui with JSON layout definitions and Skia's rendering capabilities, we achieve:

- Cross-platform consistency (Windows, macOS, Linux, Web)
- Clear separation between design (JSON) and logic (Coex)
- Efficient rendering with minimal state synchronization
- A familiar pattern for developers coming from React/Flutter backgrounds
- Simple FFI integration via C APIs

The json-as-state model aligns with Coex's persistent data structure philosophy, making UI state management predictable and debuggable.
