/**
 * UI Widget Test
 *
 * Tests that widgets return proper events and state changes:
 * - Button click returns action in state._pending_action
 * - Slider changes return new value in state
 * - Checkbox toggles return new value in state
 */

#include "coex_ui.h"
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

int main(void) {
    printf("=== Coex UI Widget Test ===\n\n");

    const char* config = "{"
        "\"title\": \"Widget Test\","
        "\"width\": 500,"
        "\"height\": 400"
    "}";

    if (!coex_ui_init(config)) {
        fprintf(stderr, "Failed to initialize UI\n");
        return 1;
    }

    printf("Window opened.\n");
    printf("Instructions:\n");
    printf("  - Click 'Increment' button - should print 'increment' action\n");
    printf("  - Click 'Decrement' button - should print 'decrement' action\n");
    printf("  - Move the slider - should print value changes\n");
    printf("  - Toggle the checkbox - should print state changes\n");
    printf("  - Close window to exit\n\n");

    /* Layout JSON with multiple widgets */
    const char* layout = "{"
        "\"type\": \"window\","
        "\"title\": \"Widget Test\","
        "\"children\": ["
            "{ \"type\": \"text\", \"text\": \"Counter Demo\" },"
            "{ \"type\": \"text\", \"id\": \"counter_display\", \"bind\": \"counter\" },"
            "{ \"type\": \"row\", \"children\": ["
                "{ \"type\": \"button\", \"id\": \"inc_btn\", \"label\": \"Increment\", \"action\": \"increment\" },"
                "{ \"type\": \"button\", \"id\": \"dec_btn\", \"label\": \"Decrement\", \"action\": \"decrement\" }"
            "]},"
            "{ \"type\": \"separator\" },"
            "{ \"type\": \"text\", \"text\": \"Slider Test\" },"
            "{ \"type\": \"slider_float\", \"id\": \"test_slider\", \"label\": \"Value\", \"min\": 0, \"max\": 100 },"
            "{ \"type\": \"separator\" },"
            "{ \"type\": \"text\", \"text\": \"Checkbox Test\" },"
            "{ \"type\": \"checkbox\", \"id\": \"test_checkbox\", \"label\": \"Enable feature\" }"
        "]"
    "}";

    /* Initial state */
    const char* state = "{"
        "\"counter\": 0,"
        "\"test_slider\": 50.0,"
        "\"test_checkbox\": false"
    "}";

    /* Track counter value */
    int counter = 0;
    int frame_count = 0;
    int events_received = 0;

    while (!coex_ui_should_close()) {
        /* Render frame and get result */
        const char* result = coex_ui_render_json(layout, state);

        if (result) {
            /* Check for events in the result */
            /* Simple string search for demonstration */
            if (strstr(result, "\"_pending_action\"")) {
                if (strstr(result, "\"increment\"")) {
                    counter++;
                    printf("[Frame %d] Button action: increment -> counter = %d\n", frame_count, counter);
                    events_received++;
                } else if (strstr(result, "\"decrement\"")) {
                    counter--;
                    printf("[Frame %d] Button action: decrement -> counter = %d\n", frame_count, counter);
                    events_received++;
                }
            }

            /* Check for slider changes */
            if (strstr(result, "\"test_slider\"") && strstr(result, "\"change\"")) {
                printf("[Frame %d] Slider changed (check result for value)\n", frame_count);
                events_received++;
            }

            /* Check for checkbox changes */
            if (strstr(result, "\"test_checkbox\"") && strstr(result, "\"change\"")) {
                printf("[Frame %d] Checkbox toggled\n", frame_count);
                events_received++;
            }

            /* Update state with new counter value */
            static char new_state[512];
            snprintf(new_state, sizeof(new_state),
                "{\"counter\": %d, \"test_slider\": 50.0, \"test_checkbox\": false}",
                counter);
            state = new_state;

            coex_ui_free_json(result);
        }

        frame_count++;
    }

    printf("\n=== Test Complete ===\n");
    printf("Total frames: %d\n", frame_count);
    printf("Events received: %d\n", events_received);
    printf("Final counter value: %d\n", counter);

    if (events_received > 0) {
        printf("\nWidget test PASSED - events were received\n");
    } else {
        printf("\nWidget test INCOMPLETE - no events received (did you click buttons?)\n");
    }

    coex_ui_shutdown();
    return 0;
}
