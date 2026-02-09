"""
Tests for list.set() under GC pressure — BUG-110.

list_set obtains raw pointers via gc_handle_deref before allocating new objects.
If GC + compaction runs during the allocation, the raw pointers become stale,
causing segfaults or data corruption.

This specifically reproduces the Galaxian crash: enemy_alive (38-element list)
is modified with .set() when firing. The game runs indefinitely without firing
but segfaults within 10 seconds after firing begins.
"""

import pytest


class TestListSetGCStress:
    """Stress test list.set() under GC pressure."""

    def test_list_set_38_elements_tail_and_tree(self, compile_coex):
        """Set all 38 elements repeatedly — exercises both tail (32-37) and tree (0-31) paths."""
        result = compile_coex('''
func main() -> int
    alive = [1, 1, 1, 1, 1, 1, 1, 1, 1, 1,
             1, 1, 1, 1, 1, 1, 1, 1, 1, 1,
             1, 1, 1, 1, 1, 1, 1, 1, 1, 1,
             1, 1, 1, 1, 1, 1, 1, 1]

    round = 0
    while round < 500
        # Kill all enemies (set to 0) — like Galaxian firing
        i = 0
        while i < 38
            alive = alive.set(i, 0)
            i = i + 1
        ~

        # Reset all enemies (set to 1) — like wave reset
        i = 0
        while i < 38
            alive = alive.set(i, 1)
            i = i + 1
        ~

        # Verify correctness
        i = 0
        while i < 38
            if alive.get(i) != 1
                print("FAIL at round ")
                print(round)
                return 1
            ~
            i = i + 1
        ~

        round = round + 1
    ~

    print("PASS")
    return 0
~
''')
        assert result.compile_success, f"Compilation failed:\n{result.compile_output}"
        assert result.run_success, f"Segfault during list.set stress test (BUG-110):\n{result.stderr}"
        assert "PASS" in result.run_output, f"Data corruption in list.set:\n{result.run_output}"

    def test_list_set_with_gc_pressure(self, compile_coex):
        """Set elements with explicit GC + allocation pressure between operations."""
        result = compile_coex('''
func main() -> int
    alive = [1, 1, 1, 1, 1, 1, 1, 1, 1, 1,
             1, 1, 1, 1, 1, 1, 1, 1, 1, 1,
             1, 1, 1, 1, 1, 1, 1, 1, 1, 1,
             1, 1, 1, 1, 1, 1, 1, 1]

    round = 0
    while round < 200
        # Trigger GC before modifications
        gc()

        # Kill enemies with allocation pressure between each .set()
        i = 0
        while i < 38
            alive = alive.set(i, 0)

            # Create garbage to increase GC pressure
            garbage = "round_" + String.from(round) + "_idx_" + String.from(i)

            i = i + 1
        ~

        # Trigger GC mid-operations
        gc()

        # Reset enemies
        i = 0
        while i < 38
            alive = alive.set(i, 1)
            i = i + 1
        ~

        # Verify
        i = 0
        while i < 38
            if alive.get(i) != 1
                print("FAIL at round ")
                print(round)
                return 1
            ~
            i = i + 1
        ~

        round = round + 1
    ~

    print("PASS")
    return 0
~
''')
        assert result.compile_success, f"Compilation failed:\n{result.compile_output}"
        assert result.run_success, f"Segfault during list.set with GC pressure (BUG-110):\n{result.stderr}"
        assert "PASS" in result.run_output, f"Data corruption:\n{result.run_output}"

    def test_list_set_single_element_repeated(self, compile_coex):
        """Rapidly set a single element — simulates repeated firing at same enemy."""
        result = compile_coex('''
func main() -> int
    alive = [1, 1, 1, 1, 1, 1, 1, 1, 1, 1,
             1, 1, 1, 1, 1, 1, 1, 1, 1, 1,
             1, 1, 1, 1, 1, 1, 1, 1, 1, 1,
             1, 1, 1, 1, 1, 1, 1, 1]

    round = 0
    while round < 5000
        # Toggle element 15 (tree path, in first leaf)
        alive = alive.set(15, 0)
        alive = alive.set(15, 1)

        # Toggle element 35 (tail path)
        alive = alive.set(35, 0)
        alive = alive.set(35, 1)

        round = round + 1
    ~

    # Verify both are still 1
    if alive.get(15) != 1
        print("FAIL tree element")
        return 1
    ~
    if alive.get(35) != 1
        print("FAIL tail element")
        return 1
    ~

    print("PASS")
    return 0
~
''')
        assert result.compile_success, f"Compilation failed:\n{result.compile_output}"
        assert result.run_success, f"Segfault in rapid single-element set (BUG-110):\n{result.stderr}"
        assert "PASS" in result.run_output, f"Data corruption:\n{result.run_output}"
