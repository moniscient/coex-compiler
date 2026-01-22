/**
 * UI Window Test
 *
 * Simple test that opens a window and closes when the X button is clicked.
 */

#include "coex_ui.h"
#include <stdio.h>

int main(void) {
    printf("Initializing UI...\n");

    const char* config = "{"
        "\"title\": \"Coex UI Window Test\","
        "\"width\": 640,"
        "\"height\": 480"
    "}";

    if (!coex_ui_init(config)) {
        fprintf(stderr, "Failed to initialize UI\n");
        return 1;
    }

    printf("Window opened. Click X to close.\n");

    int frame_count = 0;
    while (!coex_ui_should_close()) {
        coex_ui_begin_frame();

        // Render a simple window with text
        if (coex_ui_begin_window("Test Window")) {
            coex_ui_text("Hello from Coex UI!");
            coex_ui_text("Click the window's X button to close.");
            coex_ui_spacing();
            if (coex_ui_button("Click Me")) {
                printf("Button clicked!\n");
            }
        }
        coex_ui_end_window();

        coex_ui_end_frame();
        frame_count++;
    }

    printf("Window closed after %d frames.\n", frame_count);

    coex_ui_shutdown();
    printf("UI shutdown complete.\n");

    return 0;
}
