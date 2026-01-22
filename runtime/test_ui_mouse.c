/**
 * Mouse debug test - shows mouse state in real-time
 */

#include "coex_ui.h"
#include "coex_ui_shell.h"
#include "coex_ui_imgui.h"
#include <stdio.h>
#include <stdlib.h>

int main(void) {
    printf("=== Mouse Debug Test ===\n\n");

    const char* config = "{"
        "\"title\": \"Mouse Debug\","
        "\"width\": 400,"
        "\"height\": 300"
    "}";

    if (!coex_ui_init(config)) {
        fprintf(stderr, "Failed to initialize UI\n");
        return 1;
    }

    printf("Move mouse and click to see state.\n");
    printf("Close window to exit.\n\n");

    int frame = 0;
    int last_button = 0;

    while (!coex_ui_should_close()) {
        coex_ui_begin_frame();

        /* Get mouse state */
        double mx, my;
        coex_ui_shell_get_mouse_pos(&mx, &my);
        int64_t button0 = coex_ui_shell_get_mouse_button(0);
        int64_t button1 = coex_ui_shell_get_mouse_button(1);
        int64_t button2 = coex_ui_shell_get_mouse_button(2);

        /* Print on mouse click/release */
        if (button0 != last_button) {
            printf("[Frame %d] Mouse: (%.1f, %.1f) Buttons: %lld %lld %lld\n",
                   frame, mx, my, button0, button1, button2);
            last_button = button0;
        }

        /* Draw simple UI with button */
        if (coex_ui_begin_window("Test")) {
            char buf[128];
            snprintf(buf, sizeof(buf), "Mouse: (%.0f, %.0f)", mx, my);
            coex_ui_text(buf);
            snprintf(buf, sizeof(buf), "Buttons: %lld %lld %lld", button0, button1, button2);
            coex_ui_text(buf);

            coex_ui_spacing();

            if (coex_ui_button("Click Me!")) {
                printf("[Frame %d] BUTTON CLICKED!\n", frame);
            }
        }
        coex_ui_end_window();

        coex_ui_end_frame();
        frame++;
    }

    printf("\n=== Done (frames: %d) ===\n", frame);

    coex_ui_shutdown();
    return 0;
}
