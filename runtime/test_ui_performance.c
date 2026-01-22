/**
 * UI Performance Test
 *
 * Tests rendering performance with 100+ widgets.
 * Target: Maintain 60 FPS (16.67ms per frame)
 */

#include "coex_ui.h"
#include "coex_ui_shell.h"
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <math.h>

#define NUM_SLIDERS 25
#define NUM_CHECKBOXES 25
#define NUM_BUTTONS 25
#define NUM_TEXT_ITEMS 25
#define TOTAL_WIDGETS (NUM_SLIDERS + NUM_CHECKBOXES + NUM_BUTTONS + NUM_TEXT_ITEMS)

int main(void) {
    printf("=== UI Performance Test ===\n");
    printf("Rendering %d widgets\n", TOTAL_WIDGETS);
    printf("Target: 60 FPS (16.67ms per frame)\n\n");
    fflush(stdout);

    const char* config = "{"
        "\"title\": \"Performance Test\","
        "\"width\": 800,"
        "\"height\": 600"
    "}";

    if (!coex_ui_init(config)) {
        fprintf(stderr, "Failed to initialize UI\n");
        return 1;
    }

    /* Widget state */
    double slider_values[NUM_SLIDERS];
    int64_t checkbox_values[NUM_CHECKBOXES];
    int button_clicks[NUM_BUTTONS];

    for (int i = 0; i < NUM_SLIDERS; i++) slider_values[i] = (double)i / NUM_SLIDERS * 100.0;
    for (int i = 0; i < NUM_CHECKBOXES; i++) checkbox_values[i] = i % 2;
    for (int i = 0; i < NUM_BUTTONS; i++) button_clicks[i] = 0;

    /* Performance tracking */
    int frame = 0;
    double total_frame_time = 0;
    double min_frame_time = 1000.0;
    double max_frame_time = 0.0;
    int frames_under_16ms = 0;
    int frames_under_33ms = 0;

    double start_time = coex_ui_get_time();
    double last_report_time = start_time;
    double last_frame_time = start_time;

    printf("Running for 10 seconds...\n");
    printf("Close window early to see partial results.\n\n");
    fflush(stdout);

    while (!coex_ui_should_close()) {
        double frame_start = coex_ui_get_time();

        /* Check if 10 seconds elapsed */
        if (frame_start - start_time > 10.0) {
            break;
        }

        coex_ui_begin_frame();

        /* Main window with all widgets */
        if (coex_ui_begin_window("Performance Test")) {
            char label[64];

            /* Section: Sliders */
            coex_ui_text("=== Sliders ===");
            for (int i = 0; i < NUM_SLIDERS; i++) {
                snprintf(label, sizeof(label), "Slider %d", i + 1);
                coex_ui_slider_float(label, &slider_values[i], 0.0, 100.0);
            }

            coex_ui_separator();

            /* Section: Checkboxes */
            coex_ui_text("=== Checkboxes ===");
            for (int i = 0; i < NUM_CHECKBOXES; i++) {
                snprintf(label, sizeof(label), "Checkbox %d", i + 1);
                coex_ui_checkbox(label, &checkbox_values[i]);
                if ((i + 1) % 5 != 0) coex_ui_spacing();  /* Some spacing */
            }

            coex_ui_separator();

            /* Section: Buttons */
            coex_ui_text("=== Buttons ===");
            for (int i = 0; i < NUM_BUTTONS; i++) {
                snprintf(label, sizeof(label), "Button %d (%d)", i + 1, button_clicks[i]);
                if (coex_ui_button(label)) {
                    button_clicks[i]++;
                }
                if ((i + 1) % 5 != 0) coex_ui_spacing();
            }

            coex_ui_separator();

            /* Section: Text items */
            coex_ui_text("=== Text Items ===");
            for (int i = 0; i < NUM_TEXT_ITEMS; i++) {
                snprintf(label, sizeof(label), "Text item %d: value = %.2f", i + 1, slider_values[i % NUM_SLIDERS]);
                coex_ui_text(label);
            }

            /* Stats display */
            coex_ui_separator();
            coex_ui_text("=== Performance Stats ===");

            double elapsed = frame_start - start_time;
            double avg_fps = frame > 0 ? frame / elapsed : 0;
            double avg_frame_time = frame > 0 ? total_frame_time / frame * 1000.0 : 0;

            snprintf(label, sizeof(label), "Frame: %d | Elapsed: %.1fs", frame, elapsed);
            coex_ui_text(label);

            snprintf(label, sizeof(label), "Avg FPS: %.1f | Avg frame: %.2fms", avg_fps, avg_frame_time);
            coex_ui_text(label);

            snprintf(label, sizeof(label), "Min: %.2fms | Max: %.2fms", min_frame_time * 1000.0, max_frame_time * 1000.0);
            coex_ui_text(label);
        }
        coex_ui_end_window();

        coex_ui_end_frame();

        /* Measure frame time */
        double frame_end = coex_ui_get_time();
        double frame_time = frame_end - frame_start;

        total_frame_time += frame_time;
        if (frame_time < min_frame_time) min_frame_time = frame_time;
        if (frame_time > max_frame_time) max_frame_time = frame_time;
        if (frame_time < 0.01667) frames_under_16ms++;
        if (frame_time < 0.03333) frames_under_33ms++;

        frame++;
        last_frame_time = frame_end;

        /* Report every 2 seconds */
        if (frame_end - last_report_time > 2.0) {
            double elapsed = frame_end - start_time;
            printf("[%.1fs] Frame %d, FPS: %.1f, Avg frame: %.2fms\n",
                   elapsed, frame, frame / elapsed, (total_frame_time / frame) * 1000.0);
            fflush(stdout);
            last_report_time = frame_end;
        }
    }

    double end_time = coex_ui_get_time();
    double total_elapsed = end_time - start_time;

    printf("\n=== Performance Test Results ===\n");
    printf("Total frames: %d\n", frame);
    printf("Total time: %.2f seconds\n", total_elapsed);
    printf("Average FPS: %.1f\n", frame / total_elapsed);
    printf("Average frame time: %.2f ms\n", (total_frame_time / frame) * 1000.0);
    printf("Min frame time: %.2f ms\n", min_frame_time * 1000.0);
    printf("Max frame time: %.2f ms\n", max_frame_time * 1000.0);
    printf("Frames under 16.67ms (60 FPS): %d (%.1f%%)\n", frames_under_16ms, 100.0 * frames_under_16ms / frame);
    printf("Frames under 33.33ms (30 FPS): %d (%.1f%%)\n", frames_under_33ms, 100.0 * frames_under_33ms / frame);
    printf("\n");

    if (frame / total_elapsed >= 60.0) {
        printf("PASSED: Achieved 60+ FPS with %d widgets\n", TOTAL_WIDGETS);
    } else if (frame / total_elapsed >= 30.0) {
        printf("PARTIAL: Achieved 30+ FPS with %d widgets (target was 60)\n", TOTAL_WIDGETS);
    } else {
        printf("FAILED: Below 30 FPS with %d widgets\n", TOTAL_WIDGETS);
    }

    coex_ui_shutdown();
    return 0;
}
