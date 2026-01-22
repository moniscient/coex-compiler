/**
 * Debug test - prints JSON result on each button click
 */

#include "coex_ui.h"
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

int main(void) {
    printf("=== UI Debug Test ===\n\n");

    const char* config = "{"
        "\"title\": \"Debug Test\","
        "\"width\": 400,"
        "\"height\": 300"
    "}";

    if (!coex_ui_init(config)) {
        fprintf(stderr, "Failed to initialize UI\n");
        return 1;
    }

    printf("Click buttons to see JSON output.\n");
    printf("Close window to exit.\n\n");

    /* Simple layout with just buttons */
    const char* layout = "{"
        "\"type\": \"window\","
        "\"title\": \"Debug\","
        "\"children\": ["
            "{ \"type\": \"text\", \"text\": \"Click buttons:\" },"
            "{ \"type\": \"button\", \"label\": \"Button A\", \"action\": \"action_a\" },"
            "{ \"type\": \"button\", \"label\": \"Button B\", \"action\": \"action_b\" }"
        "]"
    "}";

    const char* state = "{}";
    int frame = 0;

    while (!coex_ui_should_close()) {
        const char* result = coex_ui_render_json(layout, state);

        if (result) {
            /* Check if result has any content beyond empty state */
            if (strstr(result, "_pending_action") || strstr(result, "\"events\":[{")) {
                printf("[Frame %d] Result: %s\n", frame, result);
            }
            coex_ui_free_json(result);
        }

        frame++;
    }

    printf("\n=== Done (frames: %d) ===\n", frame);

    coex_ui_shutdown();
    return 0;
}
