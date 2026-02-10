"""
Tests for HAMT pointer fixup during GC compaction — BUG-109.

HAMT nodes (internal nodes, children buffers, and leaves) are used by
Map and Set. After GC compaction copies them to a new buffer, their
internal raw pointers (HAMTNode.children, children array entries with
tag bits, leaf key pointers for string maps) must be fixed up to point
to the new locations. Without proper type_ids and fixup, these stale
pointers cause crashes when the old TLABs are freed.
"""

import pytest


class TestHAMTCompaction:
    """Tests for HAMT internal pointer fixup during compaction."""

    def test_map_int_after_gc_compaction(self, compile_coex):
        """Integer-keyed map survives GC compaction."""
        result = compile_coex('''
func main() -> int
    m = {1: 10, 2: 20, 3: 30, 4: 40, 5: 50}

    round = 0
    while round < 200
        gc()

        # Create garbage to trigger TLAB churn
        i = 0
        while i < 500
            garbage = "fill_" + String.from(i)
            i = i + 1
        ~

        gc()

        i = 0
        while i < 500
            garbage = "more_" + String.from(i)
            i = i + 1
        ~

        # Read map after two GC cycles
        if m.get(1) != 10
            print("FAIL: m.get(1)")
            return 1
        ~
        if m.get(3) != 30
            print("FAIL: m.get(3)")
            return 1
        ~
        if m.get(5) != 50
            print("FAIL: m.get(5)")
            return 1
        ~

        round = round + 1
    ~

    print("PASS")
    return 0
~
''')
        assert result.compile_success, f"Compilation failed:\n{result.compile_output}"
        assert result.run_success, f"Segfault in int map after compaction (BUG-109):\n{result.stderr}"
        assert "PASS" in result.run_output, f"Data corruption:\n{result.run_output}"

    def test_map_string_key_after_gc_compaction(self, compile_coex):
        """String-keyed map survives GC compaction (key pointer fixup)."""
        result = compile_coex('''
func main() -> int
    m = {"alpha": 1, "beta": 2, "gamma": 3, "delta": 4}

    round = 0
    while round < 200
        gc()

        i = 0
        while i < 500
            garbage = "fill_" + String.from(i)
            i = i + 1
        ~

        gc()

        i = 0
        while i < 500
            garbage = "more_" + String.from(i)
            i = i + 1
        ~

        # Read map with string keys after compaction
        if m.get("alpha") != 1
            print("FAIL: m.get(alpha)")
            return 1
        ~
        if m.get("gamma") != 3
            print("FAIL: m.get(gamma)")
            return 1
        ~

        round = round + 1
    ~

    print("PASS")
    return 0
~
''')
        assert result.compile_success, f"Compilation failed:\n{result.compile_output}"
        assert result.run_success, f"Segfault in string-key map after compaction (BUG-109):\n{result.stderr}"
        assert "PASS" in result.run_output, f"Data corruption:\n{result.run_output}"

    def test_map_mutation_across_gc_cycles(self, compile_coex):
        """Map set/get interleaved with GC cycles."""
        result = compile_coex('''
func main() -> int
    m = {1: 100}

    round = 0
    while round < 200
        # Add entries, forcing HAMT node splits
        m = m.set(round + 10, round * 2)

        gc()

        i = 0
        while i < 500
            garbage = "item_" + String.from(i)
            i = i + 1
        ~

        gc()

        # Verify the entry we just added
        expected = round * 2
        actual = m.get(round + 10)
        if actual != expected
            print("FAIL at round ")
            print(round)
            return 1
        ~

        # Verify original entry still intact
        if m.get(1) != 100
            print("FAIL: original entry lost")
            return 1
        ~

        round = round + 1
    ~

    print("PASS")
    return 0
~
''')
        assert result.compile_success, f"Compilation failed:\n{result.compile_output}"
        assert result.run_success, f"Segfault in map mutation across GC (BUG-109):\n{result.stderr}"
        assert "PASS" in result.run_output, f"Data corruption:\n{result.run_output}"

    def test_set_after_gc_compaction(self, compile_coex):
        """Set survives GC compaction (HAMT pointer fixup)."""
        result = compile_coex('''
func main() -> int
    s = {1, 2, 3, 4, 5, 6, 7, 8, 9, 10}

    round = 0
    while round < 200
        gc()

        i = 0
        while i < 500
            garbage = "fill_" + String.from(i)
            i = i + 1
        ~

        gc()

        i = 0
        while i < 500
            garbage = "more_" + String.from(i)
            i = i + 1
        ~

        # Verify set contents after compaction
        if s.has(1) != true
            print("FAIL: s.has(1)")
            return 1
        ~
        if s.has(5) != true
            print("FAIL: s.has(5)")
            return 1
        ~
        if s.has(10) != true
            print("FAIL: s.has(10)")
            return 1
        ~
        if s.len() != 10
            print("FAIL: s.len()")
            return 1
        ~

        round = round + 1
    ~

    print("PASS")
    return 0
~
''')
        assert result.compile_success, f"Compilation failed:\n{result.compile_output}"
        assert result.run_success, f"Segfault in set after compaction (BUG-109):\n{result.stderr}"
        assert "PASS" in result.run_output, f"Data corruption:\n{result.run_output}"

    def test_json_object_after_gc_compaction(self, compile_coex):
        """JSON objects (string-key maps) survive GC compaction.

        This is the Galaxian pattern: JSON objects with string keys are
        heavily used in the rendering loop.
        """
        result = compile_coex('''
func main() -> int
    round = 0
    while round < 200
        # Build a JSON object (string-key HAMT)
        obj: json := {
            type: "rect",
            id: "item_" + String.from(round),
            x: round * 10,
            y: round * 5
        }

        gc()

        i = 0
        while i < 500
            garbage = "fill_" + String.from(i)
            i = i + 1
        ~

        gc()

        i = 0
        while i < 500
            garbage = "more_" + String.from(i)
            i = i + 1
        ~

        round = round + 1
    ~

    print("PASS")
    return 0
~
''')
        assert result.compile_success, f"Compilation failed:\n{result.compile_output}"
        assert result.run_success, f"Segfault in JSON object after compaction (BUG-109):\n{result.stderr}"
        assert "PASS" in result.run_output, f"Wrong output:\n{result.run_output}"

    def test_large_map_deep_hamt_tree(self, compile_coex):
        """Large map with deep HAMT tree (many nodes and children buffers).

        Stress test: 200 entries force multi-level HAMT tree structure,
        exercising node children pointer fixup at multiple tree levels.
        """
        result = compile_coex('''
func main() -> int
    m = {0: 0}

    # Build a large map (deep HAMT tree)
    i = 1
    while i < 200
        m = m.set(i, i * 3)
        i = i + 1
    ~

    round = 0
    while round < 50
        gc()

        i = 0
        while i < 1000
            garbage = "fill_" + String.from(i)
            i = i + 1
        ~

        gc()

        i = 0
        while i < 1000
            garbage = "more_" + String.from(i)
            i = i + 1
        ~

        # Spot-check entries after compaction
        if m.get(0) != 0
            print("FAIL: m.get(0)")
            return 1
        ~
        if m.get(50) != 150
            print("FAIL: m.get(50)")
            return 1
        ~
        if m.get(199) != 597
            print("FAIL: m.get(199)")
            return 1
        ~

        round = round + 1
    ~

    print("PASS")
    return 0
~
''')
        assert result.compile_success, f"Compilation failed:\n{result.compile_output}"
        assert result.run_success, f"Segfault in large map after compaction (BUG-109):\n{result.stderr}"
        assert "PASS" in result.run_output, f"Data corruption:\n{result.run_output}"
