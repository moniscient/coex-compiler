/**
 * Simple UI Test - Direct Widget API
 *
 * Tests raw ImGui widgets without the JSON layer to isolate issues.
 */

#include "coex_ui.h"
#include <stdio.h>

int main(void) {
    printf("=== Simple UI Test (Direct API) ===\n\n");

    const char* config = "{"
        "\"title\": \"Simple Test\","
        "\"width\": 400,"
        "\"height\": 300"
    "}";

    if (!coex_ui_init(config)) {
        fprintf(stderr, "Failed to initialize UI\n");
        return 1;
    }

    printf("Window opened. Click buttons to test.\n");
    printf("Close window to exit.\n\n");

    int counter = 0;
    int frame = 0;

    while (!coex_ui_should_close()) {
        coex_ui_begin_frame();

        /* Use direct widget API */
        if (coex_ui_begin_window("Test Window")) {
            coex_ui_text("Direct Widget API Test");
            coex_ui_spacing();

            /* Show counter */
            char buf[64];
            snprintf(buf, sizeof(buf), "Counter: %d", counter);
            coex_ui_text(buf);

            coex_ui_spacing();

            /* Test button */
            if (coex_ui_button("Increment")) {
                counter++;
                printf("[Frame %d] INCREMENT clicked! counter = %d\n", frame, counter);
            }

            if (coex_ui_button("Decrement")) {
                counter--;
                printf("[Frame %d] DECREMENT clicked! counter = %d\n", frame, counter);
            }

            coex_ui_spacing();
            coex_ui_separator();

            /* Test checkbox */
            static int64_t checkbox_val = 0;
            if (coex_ui_checkbox("Test Checkbox", &checkbox_val)) {
                printf("[Frame %d] Checkbox changed to: %lld\n", frame, checkbox_val);
            }

            /* Test slider */
            static double slider_val = 50.0;
            if (coex_ui_slider_float("Slider", &slider_val, 0, 100)) {
                printf("[Frame %d] Slider changed to: %.1f\n", frame, slider_val);
            }
        }
        coex_ui_end_window();

        coex_ui_end_frame();
        frame++;
    }

    printf("\n=== Test Complete ===\n");
    printf("Final counter: %d\n", counter);

    coex_ui_shutdown();
    return 0;
}
