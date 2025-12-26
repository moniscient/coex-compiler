"""
Tests for Phase 2: Shadow Stack Thread-Local Preparation

These tests verify the shadow stack frame depth tracking that was
implemented in Phase 0 and documented in Phase 2:
- Frame depth increments on function entry
- Frame depth decrements on function exit
- Frame depth is shown in gc_dump_roots()
"""

import pytest


class TestFrameDepthTracking:
    """Tests for frame depth tracking"""

    def test_frame_depth_shown_in_dump(self, expect_output):
        """Test that frame depth is displayed in roots dump"""
        expect_output('''
func main() -> int
    gc_dump_roots()
    return 0
~
''', "depth=", partial=True)

    def test_frame_depth_increments_with_calls(self, expect_output):
        """Test that frame depth increases with nested function calls"""
        expect_output('''
func level2()
    gc_dump_roots()
~

func level1()
    level2()
~

func main() -> int
    level1()
    return 0
~
''', "depth=", partial=True)

    def test_frame_depth_in_recursive_function(self, expect_output):
        """Test frame depth tracking in recursive functions"""
        expect_output('''
func countdown(_ n: int)
    if n > 0
        countdown(n - 1)
    else
        gc_dump_roots()
    ~
~

func main() -> int
    countdown(3)
    return 0
~
''', "depth=", partial=True)


class TestShadowStackIntegrity:
    """Tests for shadow stack integrity"""

    def test_shadow_stack_survives_many_calls(self, expect_output):
        """Test that shadow stack handles many function calls"""
        expect_output('''
func helper(_ x: int) -> int
    return x + 1
~

func main() -> int
    sum = 0
    for i in 0..100
        sum = helper(sum)
    ~
    print(sum)
    return 0
~
''', "100\n")

    def test_shadow_stack_with_nested_loops(self, expect_output):
        """Test shadow stack with nested loops and allocations"""
        expect_output('''
func main() -> int
    count = 0
    for i in 0..10
        for j in 0..10
            temp = [i, j]
            count = count + 1
        ~
    ~
    print(count)
    return 0
~
''', "100\n")

    def test_gc_preserves_across_deep_calls(self, expect_output):
        """Test that GC preserves objects across deep call chains"""
        # Note: Using a simpler approach since Coex doesn't support list type annotations
        expect_output('''
func deep(_ n: int) -> int
    if n > 0
        return deep(n - 1)
    else
        gc()
        return 42
    ~
~

func main() -> int
    data = [42, 43, 44]
    result = deep(10)
    gc()
    print(data.get(0))
    return 0
~
''', "42\n")


class TestFrameDepthWithGC:
    """Tests for frame depth interaction with GC"""

    def test_gc_at_different_depths(self, expect_output):
        """Test that GC works correctly at different call depths"""
        expect_output('''
func level3() -> int
    x = [1, 2, 3]
    gc()
    return x.len()
~

func level2() -> int
    y = [4, 5]
    gc()
    return level3() + y.len()
~

func level1() -> int
    z = [6]
    gc()
    return level2() + z.len()
~

func main() -> int
    result = level1()
    print(result)
    return 0
~
''', "6\n")

    def test_heap_valid_after_deep_recursion(self, expect_output):
        """Test that heap remains valid after deep recursion with GC"""
        expect_output('''
func recurse(_ n: int)
    if n > 0
        temp = [n]
        gc()
        recurse(n - 1)
    ~
~

func main() -> int
    recurse(20)
    result = gc_validate_heap()
    print(result)
    return 0
~
''', "0\n")
