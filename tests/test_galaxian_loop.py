"""
Faithful reproduction of the Galaxian rendering loop to isolate crash.

The Galaxian game crashes within 10 seconds of firing. This test
reproduces the EXACT code pattern: enemy_alive list reads interleaved
with JSON object construction and canvas_children appends.
"""

import pytest


class TestGalaxianLoop:
    """Reproduce the Galaxian rendering crash pattern."""

    def test_render_loop_with_json_and_firing(self, compile_coex):
        """Simulate the Galaxian rendering loop with firing + JSON canvas building."""
        result = compile_coex('''
func main() -> int
    # 38-element enemy list, same as Galaxian
    enemy_alive = [1, 1, 1, 1, 1, 1, 1, 1, 1, 1,
                   1, 1, 1, 1, 1, 1, 1, 1, 1, 1,
                   1, 1, 1, 1, 1, 1, 1, 1, 1, 1,
                   1, 1, 1, 1, 1, 1, 1, 1]

    frame = 0
    while frame < 500
        # Simulate firing: kill one enemy per frame (like Galaxian bullet hitting)
        if frame > 5
            kill_idx = frame % 38
            enemy_alive = enemy_alive.set(kill_idx, 0)
        ~

        # === RENDERING LOOP ===
        # Build canvas_children JSON array — exact Galaxian pattern
        canvas_children: json := []

        # Enemy rendering: read enemy_alive.get(i) with JSON allocs between
        i = 0
        while i < 38
            if enemy_alive.get(i) == 1
                ex = 80 + (i % 10) * 40
                ey = 60 + (i / 10) * 36

                canvas_children = canvas_children.append({
                    type: "svg_image",
                    id: "enemy_" + String.from(i),
                    width: 24,
                    height: 24,
                    offsetX: ex,
                    offsetY: ey
                })
            ~
            i = i + 1
        ~

        # Player ship
        canvas_children = canvas_children.append({
            type: "svg_image",
            id: "player",
            width: 40,
            height: 32,
            offsetX: 300,
            offsetY: 440
        })

        # Reset killed enemies for next frame (like wave reset)
        if frame > 5
            reset_idx = (frame - 3) % 38
            enemy_alive = enemy_alive.set(reset_idx, 1)
        ~

        frame = frame + 1
    ~

    print("PASS")
    return 0
~
''')
        assert result.compile_success, f"Compilation failed:\n{result.compile_output}"
        assert result.run_success, f"Segfault in Galaxian render loop:\n{result.stderr}"
        assert "PASS" in result.run_output, f"Wrong output:\n{result.run_output}"

    def test_json_append_loop_stress(self, compile_coex):
        """Stress test json.append in a loop — the core Galaxian pattern."""
        result = compile_coex('''
func main() -> int
    round = 0
    while round < 200
        children: json := []

        i = 0
        while i < 50
            children = children.append({
                type: "rect",
                id: "item_" + String.from(i),
                x: i * 10,
                y: i * 5
            })
            i = i + 1
        ~

        round = round + 1
    ~

    print("PASS")
    return 0
~
''')
        assert result.compile_success, f"Compilation failed:\n{result.compile_output}"
        assert result.run_success, f"Segfault in json.append loop:\n{result.stderr}"
        assert "PASS" in result.run_output, f"Wrong output:\n{result.run_output}"
