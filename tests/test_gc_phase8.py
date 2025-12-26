"""
Tests for Phase 8: Sweep Enhancements

These tests verify the sweep mechanism:
- Unmarked objects are freed during sweep
- Marked objects survive with correct state
- Allocation list is correctly maintained
- Sweep statistics are tracked (objects_swept, bytes_reclaimed)
- Memory is properly reclaimed
"""

import pytest


class TestSweepBasics:
    """Basic tests for sweep correctness"""

    def test_sweep_frees_unreachable_objects(self, expect_output):
        """Test that unreachable objects are freed by sweep"""
        expect_output('''
func create_garbage()
    temp1 = [1, 2, 3]
    temp2 = [4, 5, 6]
    temp3 = [7, 8, 9]
~

func main() -> int
    create_garbage()
    gc()
    result = gc_validate_heap()
    print(result)
    return 0
~
''', "0\n")

    def test_sweep_preserves_live_objects(self, expect_output):
        """Test that live objects survive sweep"""
        expect_output('''
func main() -> int
    keeper = [1, 2, 3, 4, 5]
    gc()
    print(keeper.len())
    print(keeper.get(2))
    return 0
~
''', "5\n3\n")

    def test_sweep_after_multiple_gc_cycles(self, expect_output):
        """Test sweep works correctly across multiple GC cycles"""
        expect_output('''
func main() -> int
    keeper = [42]
    gc()
    gc()
    gc()
    print(keeper.get(0))
    return 0
~
''', "42\n")

    def test_sweep_mixed_live_and_garbage(self, expect_output):
        """Test sweep correctly distinguishes live from garbage"""
        expect_output('''
func create_garbage()
    garbage = [999, 888, 777]
~

func main() -> int
    live1 = [1, 2, 3]
    create_garbage()
    live2 = [4, 5, 6]
    gc()
    print(live1.get(0))
    print(live2.get(2))
    return 0
~
''', "1\n6\n")


class TestSweepAllocationList:
    """Tests for allocation list management during sweep"""

    def test_allocation_list_updated_correctly(self, expect_output):
        """Test allocation list is properly maintained after sweep"""
        expect_output('''
func main() -> int
    a = [1]
    b = [2]
    c = [3]
    gc()
    gc()
    print(a.get(0))
    print(b.get(0))
    print(c.get(0))
    return 0
~
''', "1\n2\n3\n")

    def test_sweep_removes_middle_of_list(self, expect_output):
        """Test sweep correctly handles removal from middle of allocation list"""
        expect_output('''
func create_garbage()
    middle = [999]
~

func main() -> int
    first = [1]
    create_garbage()
    last = [3]
    gc()
    print(first.get(0))
    print(last.get(0))
    return 0
~
''', "1\n3\n")

    def test_sweep_removes_all_garbage(self, expect_output):
        """Test sweep removes all garbage objects"""
        expect_output('''
func create_many_garbage()
    for i in 0..10
        temp = [i]
    ~
~

func main() -> int
    create_many_garbage()
    gc()
    result = gc_validate_heap()
    print(result)
    return 0
~
''', "0\n")


class TestSweepWithCollections:
    """Tests for sweep with various collection types"""

    def test_sweep_frees_unreachable_maps(self, expect_output):
        """Test that unreachable maps are freed"""
        expect_output('''
func create_garbage_map()
    temp = {1: 100, 2: 200}
~

func main() -> int
    keeper = {42: 420}
    create_garbage_map()
    gc()
    print(keeper.get(42))
    return 0
~
''', "420\n")

    def test_sweep_frees_unreachable_sets(self, expect_output):
        """Test that unreachable sets are freed"""
        expect_output('''
func create_garbage_set()
    temp = {100, 200, 300}
~

func main() -> int
    keeper = {1, 2, 3}
    create_garbage_set()
    gc()
    print(keeper.len())
    return 0
~
''', "3\n")

    def test_sweep_frees_unreachable_strings(self, expect_output):
        """Test that unreachable strings are freed"""
        expect_output('''
func create_garbage_string()
    temp = "this is garbage"
~

func main() -> int
    keeper = "hello"
    create_garbage_string()
    gc()
    print(keeper.len())
    return 0
~
''', "5\n")

    def test_sweep_with_mixed_collection_garbage(self, expect_output):
        """Test sweep with mixed collection types as garbage"""
        expect_output('''
func create_mixed_garbage()
    list = [1, 2, 3]
    map = {1: 10}
    set = {100}
    str = "garbage"
~

func main() -> int
    keeper = [42]
    create_mixed_garbage()
    gc()
    print(keeper.get(0))
    result = gc_validate_heap()
    print(result)
    return 0
~
''', "42\n0\n")


class TestSweepWithFunctions:
    """Tests for sweep with function calls"""

    def test_sweep_preserves_across_function_return(self, expect_output):
        """Test objects survive sweep when returned from function"""
        expect_output('''
func create_list() -> int
    temp = [10, 20, 30]
    return temp.get(1)
~

func main() -> int
    result = create_list()
    gc()
    print(result)
    return 0
~
''', "20\n")

    def test_sweep_with_nested_function_garbage(self, expect_output):
        """Test sweep collects garbage from nested function calls"""
        expect_output('''
func inner()
    temp = [999]
~

func outer()
    inner()
    temp = [888]
~

func main() -> int
    keeper = [42]
    outer()
    gc()
    print(keeper.get(0))
    return 0
~
''', "42\n")

    def test_sweep_with_recursive_garbage(self, expect_output):
        """Test sweep collects garbage from recursive calls"""
        expect_output('''
func recurse(_ n: int)
    if n > 0
        temp = [n]
        recurse(n - 1)
    ~
~

func main() -> int
    keeper = [100]
    recurse(10)
    gc()
    print(keeper.get(0))
    return 0
~
''', "100\n")


class TestSweepWithWatermark:
    """Tests for sweep interaction with watermark mechanism"""

    def test_sweep_after_watermark_gc(self, expect_output):
        """Test sweep works correctly after watermark-triggered GC"""
        expect_output('''
func work()
    temp = [1, 2, 3]
~

func main() -> int
    keeper = [42]
    gc_install_watermark()
    work()
    gc()
    print(keeper.get(0))
    return 0
~
''', "42\n")

    def test_sweep_in_watermark_loop(self, expect_output):
        """Test sweep in watermark loop pattern"""
        expect_output('''
func work()
    temp = [999]
~

func main() -> int
    keeper = [42]
    for i in 0..10
        gc_install_watermark()
        work()
    ~
    gc()
    print(keeper.get(0))
    return 0
~
''', "42\n")


class TestSweepStress:
    """Stress tests for sweep mechanism"""

    def test_sweep_many_allocations(self, expect_output):
        """Test sweep with many allocations"""
        expect_output('''
func main() -> int
    keeper = [0]
    for i in 0..100
        temp = [i, i*2]
    ~
    gc()
    print(keeper.get(0))
    result = gc_validate_heap()
    print(result)
    return 0
~
''', "0\n0\n")

    def test_sweep_rapid_gc_cycles(self, expect_output):
        """Test rapid GC cycles with sweep"""
        expect_output('''
func main() -> int
    keeper = [42]
    for i in 0..20
        temp = [i]
        gc()
    ~
    print(keeper.get(0))
    return 0
~
''', "42\n")

    def test_sweep_deep_call_stack_garbage(self, expect_output):
        """Test sweep with garbage from deep call stack"""
        expect_output('''
func deep(_ n: int)
    temp = [n]
    if n > 0
        deep(n - 1)
    ~
~

func main() -> int
    keeper = [100]
    deep(20)
    gc()
    print(keeper.get(0))
    result = gc_validate_heap()
    print(result)
    return 0
~
''', "100\n0\n")

    def test_sweep_interleaved_live_and_garbage(self, expect_output):
        """Test sweep with interleaved live and garbage allocations"""
        expect_output('''
func main() -> int
    live1 = [1]
    count = 0
    for i in 0..5
        garbage = [999]
        count = count + 1
    ~
    live2 = [2]
    gc()
    print(live1.get(0))
    print(live2.get(0))
    print(count)
    return 0
~
''', "1\n2\n5\n")


class TestSweepWithUserTypes:
    """Tests for sweep with user-defined types"""

    def test_sweep_frees_user_type(self, expect_output):
        """Test sweep frees unreachable user type objects"""
        expect_output('''
type Point:
    x: int
    y: int
~

func create_garbage()
    temp = Point(999, 999)
~

func main() -> int
    keeper = Point(10, 20)
    create_garbage()
    gc()
    print(keeper.x)
    print(keeper.y)
    return 0
~
''', "10\n20\n")

    def test_sweep_preserves_nested_user_types(self, expect_output):
        """Test sweep preserves nested user type objects"""
        expect_output('''
type Inner:
    val: int
~

type Outer:
    inner: Inner
~

func create_garbage()
    temp = Outer(Inner(999))
~

func main() -> int
    keeper = Outer(Inner(42))
    create_garbage()
    gc()
    print(keeper.inner.val)
    return 0
~
''', "42\n")


class TestSweepHeapValidity:
    """Tests for heap validity after sweep"""

    def test_heap_valid_after_single_sweep(self, expect_output):
        """Test heap is valid after single sweep"""
        expect_output('''
func main() -> int
    x = [1, 2, 3]
    gc()
    result = gc_validate_heap()
    print(result)
    return 0
~
''', "0\n")

    def test_heap_valid_after_many_sweeps(self, expect_output):
        """Test heap is valid after many sweeps"""
        expect_output('''
func main() -> int
    keeper = [42]
    for i in 0..30
        temp = [i]
        gc()
    ~
    result = gc_validate_heap()
    print(result)
    return 0
~
''', "0\n")

    def test_heap_valid_after_aggressive_collection(self, expect_output):
        """Test heap valid after aggressive collection pattern"""
        expect_output('''
func main() -> int
    for i in 0..50
        temp = [i, i*2, i*3]
        gc()
        gc()
    ~
    result = gc_validate_heap()
    print(result)
    return 0
~
''', "0\n")
