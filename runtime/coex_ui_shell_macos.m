/**
 * Coex UI Platform Shell - macOS Implementation
 *
 * Uses Cocoa for windowing/input and Metal for rendering.
 * Provides a native macOS experience with HiDPI support.
 */

#import <Cocoa/Cocoa.h>
#import <Metal/Metal.h>
#import <QuartzCore/CAMetalLayer.h>
#include <mach/mach_time.h>
#include <pthread.h>
#include "coex_ui_shell.h"

/* Forward declarations */
@class CoexUIWindow;
@class CoexUIView;
@class CoexUIAppDelegate;

/* Global state */
static struct {
    int initialized;
    int should_close;

    /* Window */
    CoexUIWindow* window;
    CoexUIView* view;
    CoexUIAppDelegate* app_delegate;

    /* Metal */
    id<MTLDevice> metal_device;
    CAMetalLayer* metal_layer;
    id<MTLCommandQueue> command_queue;
    id<CAMetalDrawable> current_drawable;

    /* Input state */
    double mouse_x, mouse_y;
    int mouse_buttons[3];  /* left, right, middle */
    int key_states[512];   /* simple key state array */
    int modifiers;

    /* Timing */
    uint64_t start_time;
    mach_timebase_info_data_t timebase;

    /* Event queue */
    CoexUIEvent event_queue[64];
    int event_read_idx;
    int event_write_idx;
    pthread_mutex_t event_mutex;

    /* Window properties */
    int64_t window_width, window_height;
    int64_t framebuffer_width, framebuffer_height;
    float content_scale_x, content_scale_y;

    /* Clipboard */
    char* clipboard_text;
} _ui_state;

/* ============================================================================
 * Event Queue Management
 * ============================================================================ */

static void push_event(CoexUIEvent* event) {
    pthread_mutex_lock(&_ui_state.event_mutex);
    int next_write = (_ui_state.event_write_idx + 1) % 64;
    if (next_write != _ui_state.event_read_idx) {
        _ui_state.event_queue[_ui_state.event_write_idx] = *event;
        _ui_state.event_write_idx = next_write;
    }
    pthread_mutex_unlock(&_ui_state.event_mutex);
}

/* ============================================================================
 * Custom NSView for handling input
 * ============================================================================ */

@interface CoexUIView : NSView
@property (nonatomic, assign) CAMetalLayer* metalLayer;
@end

@implementation CoexUIView

- (instancetype)initWithFrame:(NSRect)frame {
    self = [super initWithFrame:frame];
    if (self) {
        self.wantsLayer = YES;

        /* Create and configure Metal layer */
        _metalLayer = [CAMetalLayer layer];
        _metalLayer.device = _ui_state.metal_device;
        _metalLayer.pixelFormat = MTLPixelFormatBGRA8Unorm;
        _metalLayer.framebufferOnly = NO;  /* Allow reading back for screenshots */
        _metalLayer.contentsScale = [[NSScreen mainScreen] backingScaleFactor];
        self.layer = _metalLayer;
    }
    return self;
}

- (BOOL)acceptsFirstResponder {
    return YES;
}

- (BOOL)canBecomeKeyView {
    return YES;
}

- (BOOL)wantsUpdateLayer {
    return YES;
}

- (void)updateLayer {
    /* Metal layer is auto-updated */
}

- (void)setFrameSize:(NSSize)newSize {
    [super setFrameSize:newSize];

    /* Update Metal layer size */
    CGFloat scale = _metalLayer.contentsScale;
    _metalLayer.drawableSize = CGSizeMake(newSize.width * scale, newSize.height * scale);

    _ui_state.window_width = (int64_t)newSize.width;
    _ui_state.window_height = (int64_t)newSize.height;
    _ui_state.framebuffer_width = (int64_t)(newSize.width * scale);
    _ui_state.framebuffer_height = (int64_t)(newSize.height * scale);

    /* Push resize event */
    CoexUIEvent event = {0};
    event.type = COEX_UI_EVENT_RESIZE;
    event.data.resize.width = _ui_state.framebuffer_width;
    event.data.resize.height = _ui_state.framebuffer_height;
    push_event(&event);
}

/* --------------------------------------------------------------------------
 * Mouse Events
 * -------------------------------------------------------------------------- */

- (void)updateMousePosition:(NSEvent*)event {
    NSPoint point = [self convertPoint:[event locationInWindow] fromView:nil];
    _ui_state.mouse_x = point.x;
    _ui_state.mouse_y = self.bounds.size.height - point.y;  /* Flip Y */
}

- (void)mouseMoved:(NSEvent*)event {
    [self updateMousePosition:event];

    CoexUIEvent ui_event = {0};
    ui_event.type = COEX_UI_EVENT_MOUSE_MOVE;
    ui_event.data.mouse_move.x = _ui_state.mouse_x;
    ui_event.data.mouse_move.y = _ui_state.mouse_y;
    push_event(&ui_event);
}

- (void)mouseDragged:(NSEvent*)event {
    [self mouseMoved:event];
}

- (void)rightMouseDragged:(NSEvent*)event {
    [self mouseMoved:event];
}

- (void)otherMouseDragged:(NSEvent*)event {
    [self mouseMoved:event];
}

- (void)mouseDown:(NSEvent*)event {
    [self updateMousePosition:event];
    _ui_state.mouse_buttons[COEX_UI_MOUSE_LEFT] = 1;

    CoexUIEvent ui_event = {0};
    ui_event.type = COEX_UI_EVENT_MOUSE_BUTTON;
    ui_event.data.mouse_button.button = COEX_UI_MOUSE_LEFT;
    ui_event.data.mouse_button.pressed = 1;
    ui_event.data.mouse_button.modifiers = _ui_state.modifiers;
    push_event(&ui_event);
}

- (void)mouseUp:(NSEvent*)event {
    [self updateMousePosition:event];
    _ui_state.mouse_buttons[COEX_UI_MOUSE_LEFT] = 0;

    CoexUIEvent ui_event = {0};
    ui_event.type = COEX_UI_EVENT_MOUSE_BUTTON;
    ui_event.data.mouse_button.button = COEX_UI_MOUSE_LEFT;
    ui_event.data.mouse_button.pressed = 0;
    ui_event.data.mouse_button.modifiers = _ui_state.modifiers;
    push_event(&ui_event);
}

- (void)rightMouseDown:(NSEvent*)event {
    [self updateMousePosition:event];
    _ui_state.mouse_buttons[COEX_UI_MOUSE_RIGHT] = 1;

    CoexUIEvent ui_event = {0};
    ui_event.type = COEX_UI_EVENT_MOUSE_BUTTON;
    ui_event.data.mouse_button.button = COEX_UI_MOUSE_RIGHT;
    ui_event.data.mouse_button.pressed = 1;
    ui_event.data.mouse_button.modifiers = _ui_state.modifiers;
    push_event(&ui_event);
}

- (void)rightMouseUp:(NSEvent*)event {
    [self updateMousePosition:event];
    _ui_state.mouse_buttons[COEX_UI_MOUSE_RIGHT] = 0;

    CoexUIEvent ui_event = {0};
    ui_event.type = COEX_UI_EVENT_MOUSE_BUTTON;
    ui_event.data.mouse_button.button = COEX_UI_MOUSE_RIGHT;
    ui_event.data.mouse_button.pressed = 0;
    ui_event.data.mouse_button.modifiers = _ui_state.modifiers;
    push_event(&ui_event);
}

- (void)otherMouseDown:(NSEvent*)event {
    [self updateMousePosition:event];
    _ui_state.mouse_buttons[COEX_UI_MOUSE_MIDDLE] = 1;

    CoexUIEvent ui_event = {0};
    ui_event.type = COEX_UI_EVENT_MOUSE_BUTTON;
    ui_event.data.mouse_button.button = COEX_UI_MOUSE_MIDDLE;
    ui_event.data.mouse_button.pressed = 1;
    ui_event.data.mouse_button.modifiers = _ui_state.modifiers;
    push_event(&ui_event);
}

- (void)otherMouseUp:(NSEvent*)event {
    [self updateMousePosition:event];
    _ui_state.mouse_buttons[COEX_UI_MOUSE_MIDDLE] = 0;

    CoexUIEvent ui_event = {0};
    ui_event.type = COEX_UI_EVENT_MOUSE_BUTTON;
    ui_event.data.mouse_button.button = COEX_UI_MOUSE_MIDDLE;
    ui_event.data.mouse_button.pressed = 0;
    ui_event.data.mouse_button.modifiers = _ui_state.modifiers;
    push_event(&ui_event);
}

- (void)scrollWheel:(NSEvent*)event {
    CoexUIEvent ui_event = {0};
    ui_event.type = COEX_UI_EVENT_MOUSE_SCROLL;
    ui_event.data.mouse_scroll.x_offset = [event scrollingDeltaX];
    ui_event.data.mouse_scroll.y_offset = [event scrollingDeltaY];
    push_event(&ui_event);
}

/* --------------------------------------------------------------------------
 * Keyboard Events
 * -------------------------------------------------------------------------- */

static int translate_keycode(unsigned short keycode) {
    /* macOS virtual key codes to our key codes */
    switch (keycode) {
        case 0x35: return COEX_UI_KEY_ESCAPE;
        case 0x24: return COEX_UI_KEY_ENTER;
        case 0x30: return COEX_UI_KEY_TAB;
        case 0x33: return COEX_UI_KEY_BACKSPACE;
        case 0x72: return COEX_UI_KEY_INSERT;
        case 0x75: return COEX_UI_KEY_DELETE;
        case 0x7C: return COEX_UI_KEY_RIGHT;
        case 0x7B: return COEX_UI_KEY_LEFT;
        case 0x7D: return COEX_UI_KEY_DOWN;
        case 0x7E: return COEX_UI_KEY_UP;
        case 0x74: return COEX_UI_KEY_PAGE_UP;
        case 0x79: return COEX_UI_KEY_PAGE_DOWN;
        case 0x73: return COEX_UI_KEY_HOME;
        case 0x77: return COEX_UI_KEY_END;
        case 0x7A: return COEX_UI_KEY_F1;
        case 0x78: return COEX_UI_KEY_F1 + 1;
        case 0x63: return COEX_UI_KEY_F1 + 2;
        case 0x76: return COEX_UI_KEY_F1 + 3;
        case 0x60: return COEX_UI_KEY_F1 + 4;
        case 0x61: return COEX_UI_KEY_F1 + 5;
        case 0x62: return COEX_UI_KEY_F1 + 6;
        case 0x64: return COEX_UI_KEY_F1 + 7;
        case 0x65: return COEX_UI_KEY_F1 + 8;
        case 0x6D: return COEX_UI_KEY_F1 + 9;
        case 0x67: return COEX_UI_KEY_F1 + 10;
        case 0x6F: return COEX_UI_KEY_F12;
        default: return -1;
    }
}

static int translate_modifiers(NSEventModifierFlags flags) {
    int mods = 0;
    if (flags & NSEventModifierFlagShift) mods |= COEX_UI_MOD_SHIFT;
    if (flags & NSEventModifierFlagControl) mods |= COEX_UI_MOD_CTRL;
    if (flags & NSEventModifierFlagOption) mods |= COEX_UI_MOD_ALT;
    if (flags & NSEventModifierFlagCommand) mods |= COEX_UI_MOD_SUPER;
    return mods;
}

- (void)flagsChanged:(NSEvent*)event {
    _ui_state.modifiers = translate_modifiers([event modifierFlags]);
}

- (void)keyDown:(NSEvent*)event {
    _ui_state.modifiers = translate_modifiers([event modifierFlags]);

    int keycode = translate_keycode([event keyCode]);
    if (keycode >= 0 && keycode < 512) {
        _ui_state.key_states[keycode] = 1;
    }

    /* Also try to get ASCII value */
    NSString* chars = [event characters];
    if ([chars length] > 0) {
        unichar c = [chars characterAtIndex:0];
        if (c < 128) {
            _ui_state.key_states[(int)c] = 1;
            keycode = (int)c;
        }
    }

    CoexUIEvent ui_event = {0};
    ui_event.type = COEX_UI_EVENT_KEY;
    ui_event.data.key.keycode = keycode;
    ui_event.data.key.scancode = [event keyCode];
    ui_event.data.key.pressed = 1;
    ui_event.data.key.modifiers = _ui_state.modifiers;
    push_event(&ui_event);

    /* Also generate character event for text input */
    if ([chars length] > 0) {
        unichar c = [chars characterAtIndex:0];
        if (c >= 32 && c != 127) {  /* Printable characters */
            CoexUIEvent char_event = {0};
            char_event.type = COEX_UI_EVENT_CHAR;
            char_event.data.character.codepoint = c;
            push_event(&char_event);
        }
    }
}

- (void)keyUp:(NSEvent*)event {
    _ui_state.modifiers = translate_modifiers([event modifierFlags]);

    int keycode = translate_keycode([event keyCode]);
    if (keycode >= 0 && keycode < 512) {
        _ui_state.key_states[keycode] = 0;
    }

    NSString* chars = [event characters];
    if ([chars length] > 0) {
        unichar c = [chars characterAtIndex:0];
        if (c < 128) {
            _ui_state.key_states[(int)c] = 0;
            keycode = (int)c;
        }
    }

    CoexUIEvent ui_event = {0};
    ui_event.type = COEX_UI_EVENT_KEY;
    ui_event.data.key.keycode = keycode;
    ui_event.data.key.scancode = [event keyCode];
    ui_event.data.key.pressed = 0;
    ui_event.data.key.modifiers = _ui_state.modifiers;
    push_event(&ui_event);
}

@end

/* ============================================================================
 * Custom NSWindow for tracking close
 * ============================================================================ */

@interface CoexUIWindow : NSWindow
@end

@implementation CoexUIWindow

- (BOOL)canBecomeKeyWindow {
    return YES;
}

- (BOOL)canBecomeMainWindow {
    return YES;
}

@end

/* ============================================================================
 * App Delegate for handling app lifecycle
 * ============================================================================ */

@interface CoexUIAppDelegate : NSObject <NSApplicationDelegate, NSWindowDelegate>
@end

@implementation CoexUIAppDelegate

- (void)applicationDidFinishLaunching:(NSNotification*)notification {
    /* Activation is now handled in coex_ui_shell_init for CLI apps */
}

- (BOOL)applicationShouldTerminateAfterLastWindowClosed:(NSApplication*)sender {
    return NO;  /* We handle this ourselves */
}

- (void)windowWillClose:(NSNotification*)notification {
    _ui_state.should_close = 1;

    CoexUIEvent event = {0};
    event.type = COEX_UI_EVENT_CLOSE;
    push_event(&event);
}

- (void)windowDidBecomeKey:(NSNotification*)notification {
    CoexUIEvent event = {0};
    event.type = COEX_UI_EVENT_FOCUS;
    event.data.focus.focused = 1;
    push_event(&event);
}

- (void)windowDidResignKey:(NSNotification*)notification {
    CoexUIEvent event = {0};
    event.type = COEX_UI_EVENT_FOCUS;
    event.data.focus.focused = 0;
    push_event(&event);
}

@end

/* ============================================================================
 * Public API Implementation
 * ============================================================================ */

int64_t coex_ui_shell_init(const char* title, int64_t width, int64_t height, int64_t flags) {
    if (_ui_state.initialized) {
        return 1;  /* Already initialized */
    }

    memset((void*)&_ui_state, 0, sizeof(_ui_state));
    pthread_mutex_init(&_ui_state.event_mutex, NULL);

    @autoreleasepool {
        /* Initialize application */
        [NSApplication sharedApplication];

        /* Set activation policy BEFORE finishing launch - required for CLI apps */
        [NSApp setActivationPolicy:NSApplicationActivationPolicyRegular];

        /* Create app delegate */
        _ui_state.app_delegate = [[CoexUIAppDelegate alloc] init];
        [NSApp setDelegate:_ui_state.app_delegate];

        /* Finish launching to process activation */
        [NSApp finishLaunching];

        /* Get Metal device */
        _ui_state.metal_device = MTLCreateSystemDefaultDevice();
        if (!_ui_state.metal_device) {
            fprintf(stderr, "coex_ui_shell_init: Metal not available\n");
            return 0;
        }

        /* Create command queue */
        _ui_state.command_queue = [_ui_state.metal_device newCommandQueue];

        /* Calculate window style */
        NSWindowStyleMask style = NSWindowStyleMaskTitled |
                                  NSWindowStyleMaskClosable |
                                  NSWindowStyleMaskMiniaturizable;

        if (flags & COEX_UI_FLAG_RESIZABLE) {
            style |= NSWindowStyleMaskResizable;
        }
        if (flags & COEX_UI_FLAG_BORDERLESS) {
            style = NSWindowStyleMaskBorderless;
        }

        /* Create window */
        NSRect frame = NSMakeRect(100, 100, width, height);
        _ui_state.window = [[CoexUIWindow alloc] initWithContentRect:frame
                                                           styleMask:style
                                                             backing:NSBackingStoreBuffered
                                                               defer:NO];

        if (!_ui_state.window) {
            fprintf(stderr, "coex_ui_shell_init: Failed to create window\n");
            return 0;
        }

        [_ui_state.window setTitle:[NSString stringWithUTF8String:title]];
        [_ui_state.window setDelegate:_ui_state.app_delegate];
        [_ui_state.window setAcceptsMouseMovedEvents:YES];

        if (flags & COEX_UI_FLAG_ALWAYS_ON_TOP) {
            [_ui_state.window setLevel:NSFloatingWindowLevel];
        }

        /* Create view */
        _ui_state.view = [[CoexUIView alloc] initWithFrame:frame];
        [_ui_state.window setContentView:_ui_state.view];
        _ui_state.metal_layer = _ui_state.view.metalLayer;

        /* Store initial size */
        _ui_state.window_width = width;
        _ui_state.window_height = height;
        _ui_state.content_scale_x = [[NSScreen mainScreen] backingScaleFactor];
        _ui_state.content_scale_y = _ui_state.content_scale_x;
        _ui_state.framebuffer_width = width * _ui_state.content_scale_x;
        _ui_state.framebuffer_height = height * _ui_state.content_scale_y;

        /* Initialize timing */
        mach_timebase_info(&_ui_state.timebase);
        _ui_state.start_time = mach_absolute_time();

        /* Show window */
        [_ui_state.window makeKeyAndOrderFront:nil];
        [_ui_state.view.window makeFirstResponder:_ui_state.view];

        /* Activate app - required for CLI apps to receive mouse events */
        [NSApp activateIgnoringOtherApps:YES];

        /* Process pending events to complete activation */
        NSEvent* event;
        while ((event = [NSApp nextEventMatchingMask:NSEventMaskAny
                                           untilDate:[NSDate dateWithTimeIntervalSinceNow:0.01]
                                              inMode:NSDefaultRunLoopMode
                                             dequeue:YES])) {
            [NSApp sendEvent:event];
        }

        _ui_state.initialized = 1;
    }

    return 1;
}

void coex_ui_shell_shutdown(void) {
    if (!_ui_state.initialized) return;

    @autoreleasepool {
        if (_ui_state.clipboard_text) {
            free(_ui_state.clipboard_text);
        }

        [_ui_state.window close];
        _ui_state.window = nil;
        _ui_state.view = nil;
        _ui_state.metal_layer = nil;
        _ui_state.metal_device = nil;
        _ui_state.command_queue = nil;
        _ui_state.app_delegate = nil;
    }

    pthread_mutex_destroy(&_ui_state.event_mutex);
    _ui_state.initialized = 0;
}

void coex_ui_shell_begin_frame(void) {
    @autoreleasepool {
        /* Get next drawable */
        _ui_state.current_drawable = [_ui_state.metal_layer nextDrawable];
    }
}

void coex_ui_shell_end_frame(void) {
    @autoreleasepool {
        /* Clear current drawable reference - presentation is handled by Metal renderer */
        _ui_state.current_drawable = nil;
    }
}

int64_t coex_ui_shell_should_close(void) {
    return _ui_state.should_close;
}

int64_t coex_ui_shell_poll_event(CoexUIEvent* event) {
    if (!event) return 0;

    pthread_mutex_lock(&_ui_state.event_mutex);
    if (_ui_state.event_read_idx != _ui_state.event_write_idx) {
        *event = _ui_state.event_queue[_ui_state.event_read_idx];
        _ui_state.event_read_idx = (_ui_state.event_read_idx + 1) % 64;
        pthread_mutex_unlock(&_ui_state.event_mutex);
        return 1;
    }
    pthread_mutex_unlock(&_ui_state.event_mutex);

    return 0;
}

void coex_ui_shell_process_events(void) {
    @autoreleasepool {
        NSEvent* event;
        while ((event = [NSApp nextEventMatchingMask:NSEventMaskAny
                                           untilDate:nil
                                              inMode:NSDefaultRunLoopMode
                                             dequeue:YES])) {
            [NSApp sendEvent:event];
        }
    }
}

void coex_ui_shell_get_mouse_pos(double* x, double* y) {
    if (x) *x = _ui_state.mouse_x;
    if (y) *y = _ui_state.mouse_y;
}

int64_t coex_ui_shell_get_mouse_button(int64_t button) {
    if (button >= 0 && button < 3) {
        return _ui_state.mouse_buttons[button];
    }
    return 0;
}

int64_t coex_ui_shell_get_key(int64_t keycode) {
    if (keycode >= 0 && keycode < 512) {
        return _ui_state.key_states[keycode];
    }
    return 0;
}

int64_t coex_ui_shell_get_modifiers(void) {
    return _ui_state.modifiers;
}

void coex_ui_shell_get_size(int64_t* width, int64_t* height) {
    if (width) *width = _ui_state.window_width;
    if (height) *height = _ui_state.window_height;
}

void coex_ui_shell_get_framebuffer_size(int64_t* width, int64_t* height) {
    if (width) *width = _ui_state.framebuffer_width;
    if (height) *height = _ui_state.framebuffer_height;
}

void coex_ui_shell_get_content_scale(float* x_scale, float* y_scale) {
    if (x_scale) *x_scale = _ui_state.content_scale_x;
    if (y_scale) *y_scale = _ui_state.content_scale_y;
}

void coex_ui_shell_set_title(const char* title) {
    @autoreleasepool {
        if (_ui_state.window && title) {
            [_ui_state.window setTitle:[NSString stringWithUTF8String:title]];
        }
    }
}

void coex_ui_shell_set_clipboard(const char* text) {
    @autoreleasepool {
        if (!text) return;
        NSPasteboard* pasteboard = [NSPasteboard generalPasteboard];
        [pasteboard clearContents];
        [pasteboard setString:[NSString stringWithUTF8String:text]
                      forType:NSPasteboardTypeString];
    }
}

const char* coex_ui_shell_get_clipboard(void) {
    @autoreleasepool {
        if (_ui_state.clipboard_text) {
            free(_ui_state.clipboard_text);
            _ui_state.clipboard_text = NULL;
        }

        NSPasteboard* pasteboard = [NSPasteboard generalPasteboard];
        NSString* string = [pasteboard stringForType:NSPasteboardTypeString];
        if (string) {
            const char* utf8 = [string UTF8String];
            _ui_state.clipboard_text = strdup(utf8);
            return _ui_state.clipboard_text;
        }
    }
    return NULL;
}

double coex_ui_shell_get_time(void) {
    uint64_t elapsed = mach_absolute_time() - _ui_state.start_time;
    double nanos = (double)elapsed * _ui_state.timebase.numer / _ui_state.timebase.denom;
    return nanos / 1e9;
}

void* coex_ui_shell_get_render_context(void) {
    /* Return Metal layer for Skia GPU backend */
    return (__bridge void*)_ui_state.metal_layer;
}

/* ============================================================================
 * Metal API for External Rendering (returns void* for C compatibility)
 * ============================================================================ */

void* coex_ui_shell_get_metal_device(void) {
    return (__bridge void*)_ui_state.metal_device;
}

void* coex_ui_shell_get_metal_command_queue(void) {
    return (__bridge void*)_ui_state.command_queue;
}

void* coex_ui_shell_get_current_drawable_texture(void) {
    if (_ui_state.current_drawable) {
        return (__bridge void*)[_ui_state.current_drawable texture];
    }
    return NULL;
}

void* coex_ui_shell_create_command_buffer(void) {
    return (__bridge void*)[_ui_state.command_queue commandBuffer];
}

void coex_ui_shell_present_and_commit(void* command_buffer) {
    if (!command_buffer) return;

    @autoreleasepool {
        id<MTLCommandBuffer> cmdBuffer = (__bridge id<MTLCommandBuffer>)command_buffer;
        if (_ui_state.current_drawable) {
            [cmdBuffer presentDrawable:_ui_state.current_drawable];
        }
        [cmdBuffer commit];
    }
}
