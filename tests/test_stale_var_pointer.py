"""
Tests for stale variable pointer after GC compaction — BUG-111.

When a reference-type local variable (List, String, Map, etc.) is stored
in an alloca as a raw pointer, GC compaction can move the object to a new
location. The handle table is updated, but the alloca still has the stale
raw pointer. If the old TLAB is munmapped (deferred cleanup in next cycle),
reading the variable crashes with a segfault.

This reproduces the Galaxian rendering loop crash: enemy_alive is READ
38 times with many JSON/string allocations between reads. If two GC cycles
pass during the rendering loop, the TLAB backing enemy_alive's pointer
is munmapped, causing a crash.
"""

import pytest


class TestStaleVarPointer:
    """Tests for stale variable pointers after GC compaction."""

    def test_list_read_after_gc_cycles(self, compile_coex):
        """Read a list variable after multiple GC cycles without reassigning it.

        This is the core Galaxian crash pattern: enemy_alive is created,
        then read many times in the rendering loop with heavy allocations
        between reads. The variable is never reassigned during the loop.
        """
        result = compile_coex('''
func main() -> int
    alive = [1, 1, 1, 1, 1, 1, 1, 1, 1, 1,
             1, 1, 1, 1, 1, 1, 1, 1, 1, 1,
             1, 1, 1, 1, 1, 1, 1, 1, 1, 1,
             1, 1, 1, 1, 1, 1, 1, 1]

    round = 0
    while round < 200
        # Force GC cycle 1 — compacts alive's list struct to new location
        gc()

        # Create garbage to fill TLABs and trigger natural GC pressure
        i = 0
        while i < 2000
            garbage = "item_" + String.from(i)
            i = i + 1
        ~

        # Force GC cycle 2 — deferred cleanup munmaps alive's old TLAB
        gc()

        # More garbage to ensure cycle 2 completes
        i = 0
        while i < 2000
            garbage = "more_" + String.from(i)
            i = i + 1
        ~

        # NOW read alive — if alloca has stale pointer to munmapped TLAB, CRASH
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
        assert result.run_success, f"Segfault reading list after GC compaction (BUG-111):\n{result.stderr}"
        assert "PASS" in result.run_output, f"Data corruption:\n{result.run_output}"

    def test_string_read_after_gc_cycles(self, compile_coex):
        """Read a string variable after multiple GC cycles without reassigning it."""
        result = compile_coex('''
func main() -> int
    msg = "hello world test string"

    round = 0
    while round < 200
        gc()
        i = 0
        while i < 2000
            garbage = "fill_" + String.from(i)
            i = i + 1
        ~
        gc()
        i = 0
        while i < 2000
            garbage = "more_" + String.from(i)
            i = i + 1
        ~

        # Read msg after GC cycles
        if msg.len() != 23
            print("FAIL: string length wrong at round ")
            print(round)
            return 1
        ~

        round = round + 1
    ~

    print("PASS")
    return 0
~
''')
        assert result.compile_success, f"Compilation failed:\n{result.compile_output}"
        assert result.run_success, f"Segfault reading string after GC compaction (BUG-111):\n{result.stderr}"
        assert "PASS" in result.run_output, f"Data corruption:\n{result.run_output}"

    def test_interleaved_list_reads_with_allocations(self, compile_coex):
        """Interleave list reads with heavy allocations — mimics Galaxian render loop."""
        result = compile_coex('''
func main() -> int
    alive = [1, 1, 1, 1, 1, 1, 1, 1, 1, 1,
             1, 1, 1, 1, 1, 1, 1, 1, 1, 1,
             1, 1, 1, 1, 1, 1, 1, 1, 1, 1,
             1, 1, 1, 1, 1, 1, 1, 1]

    frame = 0
    while frame < 100
        gc()

        # Render loop: read alive[i] with allocations between reads
        # This mimics Galaxian building JSON canvas with enemy_alive.get(i) checks
        i = 0
        total = 0
        while i < 38
            val = alive.get(i)
            total = total + val

            # Heavy allocations between reads (like JSON object building)
            label = "enemy_" + String.from(i) + "_frame_" + String.from(frame)
            pos = "x=" + String.from(i * 20) + ",y=" + String.from(i * 15)

            i = i + 1
        ~

        if total != 38
            print("FAIL: total should be 38, got ")
            print(total)
            return 1
        ~

        frame = frame + 1
    ~

    print("PASS")
    return 0
~
''')
        assert result.compile_success, f"Compilation failed:\n{result.compile_output}"
        assert result.run_success, f"Segfault in interleaved list reads (BUG-111):\n{result.stderr}"
        assert "PASS" in result.run_output, f"Data corruption:\n{result.run_output}"

    def test_list_set_then_read_after_gc(self, compile_coex):
        """Set list elements, then read after GC — combines BUG-110 and BUG-111."""
        result = compile_coex('''
func main() -> int
    alive = [1, 1, 1, 1, 1, 1, 1, 1, 1, 1,
             1, 1, 1, 1, 1, 1, 1, 1, 1, 1,
             1, 1, 1, 1, 1, 1, 1, 1, 1, 1,
             1, 1, 1, 1, 1, 1, 1, 1]

    frame = 0
    while frame < 100
        # Kill some enemies (set to 0) — like firing in Galaxian
        alive = alive.set(5, 0)
        alive = alive.set(15, 0)
        alive = alive.set(35, 0)

        gc()

        # Create garbage between set and read
        i = 0
        while i < 2000
            garbage = "frame_" + String.from(frame) + "_item_" + String.from(i)
            i = i + 1
        ~

        gc()

        i = 0
        while i < 2000
            garbage = "more_" + String.from(frame) + "_" + String.from(i)
            i = i + 1
        ~

        # Read all elements after GC cycles
        i = 0
        total = 0
        while i < 38
            total = total + alive.get(i)
            i = i + 1
        ~

        if total != 35
            print("FAIL: expected 35, got ")
            print(total)
            return 1
        ~

        # Reset killed enemies
        alive = alive.set(5, 1)
        alive = alive.set(15, 1)
        alive = alive.set(35, 1)

        frame = frame + 1
    ~

    print("PASS")
    return 0
~
''')
        assert result.compile_success, f"Compilation failed:\n{result.compile_output}"
        assert result.run_success, f"Segfault in set-then-read-after-GC (BUG-111):\n{result.stderr}"
        assert "PASS" in result.run_output, f"Data corruption:\n{result.run_output}"
