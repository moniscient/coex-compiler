/**
 * UI Integration Test - Counter Example
 *
 * Tests the full JSON-driven UI workflow:
 * - Coex describes UI as JSON layout
 * - C runtime renders it with ImGui
 * - State changes returned as JSON
 * - Actions trigger state updates
 *
 * This matches the usage pattern from the plan.
 */

#include "coex_ui.h"
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

/* Simple JSON value extraction (for demo - real code would use cJSON) */
static int extract_int(const char* json, const char* key) {
    char search[64];
    snprintf(search, sizeof(search), "\"%s\":", key);
    const char* pos = strstr(json, search);
    if (!pos) return 0;
    pos += strlen(search);
    while (*pos == ' ') pos++;
    return atoi(pos);
}

static int has_action(const char* json, const char* action) {
    /* Look for _pending_action key */
    const char* pos = strstr(json, "\"_pending_action\"");
    if (!pos) return 0;

    /* Skip past the key and any whitespace/colon */
    pos += strlen("\"_pending_action\"");
    while (*pos == ' ' || *pos == '\t' || *pos == ':') pos++;

    /* Check if the value matches */
    if (*pos != '"') return 0;
    pos++;  /* Skip opening quote */

    size_t action_len = strlen(action);
    return strncmp(pos, action, action_len) == 0 && pos[action_len] == '"';
}

int main(void) {
    printf("=== UI Integration Test: Counter Example ===\n\n");
    fflush(stdout);

    const char* config = "{"
        "\"title\": \"Counter App\","
        "\"width\": 400,"
        "\"height\": 300"
    "}";

    if (!coex_ui_init(config)) {
        fprintf(stderr, "Failed to initialize UI\n");
        return 1;
    }

    printf("Counter app running.\n");
    printf("Click + to increment, - to decrement.\n");
    printf("Close window to exit.\n\n");
    fflush(stdout);

    /* Layout JSON - describes the UI structure */
    const char* layout = "{"
        "\"type\": \"window\","
        "\"title\": \"Counter\","
        "\"children\": ["
            "{ \"type\": \"text\", \"text\": \"Counter Value:\" },"
            "{ \"type\": \"text\", \"id\": \"display\", \"bind\": \"count\" },"
            "{ \"type\": \"spacing\" },"
            "{ \"type\": \"row\", \"children\": ["
                "{ \"type\": \"button\", \"label\": \"+\", \"action\": \"increment\" },"
                "{ \"type\": \"button\", \"label\": \"-\", \"action\": \"decrement\" },"
                "{ \"type\": \"button\", \"label\": \"Reset\", \"action\": \"reset\" }"
            "]}"
        "]"
    "}";

    /* State - the data model */
    int count = 0;
    char state_json[256];

    int frame = 0;
    int actions_processed = 0;

    while (!coex_ui_should_close()) {
        /* Build current state JSON */
        snprintf(state_json, sizeof(state_json), "{\"count\": %d}", count);

        /* Render and get result */
        const char* result = coex_ui_render_json(layout, state_json);

        if (result) {
            /* Debug: print result every 100 frames or when there's an action */
            if (frame % 100 == 0 || strstr(result, "_pending_action")) {
                printf("[Frame %d] Result: %.200s%s\n", frame, result,
                       strlen(result) > 200 ? "..." : "");
                fflush(stdout);
            }

            /* Check for actions */
            if (has_action(result, "increment")) {
                count++;
                printf("[Frame %d] Action: increment -> count = %d\n", frame, count);
                fflush(stdout);
                actions_processed++;
            }
            else if (has_action(result, "decrement")) {
                count--;
                printf("[Frame %d] Action: decrement -> count = %d\n", frame, count);
                fflush(stdout);
                actions_processed++;
            }
            else if (has_action(result, "reset")) {
                count = 0;
                printf("[Frame %d] Action: reset -> count = %d\n", frame, count);
                fflush(stdout);
                actions_processed++;
            }

            coex_ui_free_json(result);
        }

        frame++;
    }

    printf("\n=== Integration Test Complete ===\n");
    printf("Total frames: %d\n", frame);
    printf("Actions processed: %d\n", actions_processed);
    printf("Final count: %d\n", count);

    if (actions_processed > 0) {
        printf("\nIntegration test PASSED\n");
    } else {
        printf("\nIntegration test INCOMPLETE (no actions - did you click buttons?)\n");
    }

    coex_ui_shutdown();
    return 0;
}
