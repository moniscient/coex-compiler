"""
Tests for Coex garbage collector functionality.

These tests verify that:
1. Basic allocation still works with GC headers
2. The gc() built-in function works
3. GC properly reclaims unreachable objects
4. Reachable objects survive collection
"""

import pytest


class TestGarbageCollector:
    """Tests for garbage collector functionality"""

    def test_gc_builtin_exists(self, expect_output):
        """Test that gc() built-in function can be called"""
        expect_output('''
func main() -> int
    gc()
    print(42)
    return 0
~
''', "42\n")

    def test_gc_with_basic_types(self, expect_output):
        """Test gc() with basic integer variables"""
        expect_output('''
func main() -> int
    x: int = 10
    y: int = 20
    gc()
    print(x + y)
    return 0
~
''', "30\n")

    def test_gc_multiple_calls(self, expect_output):
        """Test multiple gc() calls in sequence"""
        expect_output('''
func main() -> int
    gc()
    x: int = 5
    gc()
    y: int = 10
    gc()
    print(x + y)
    return 0
~
''', "15\n")

    def test_gc_in_loop(self, expect_output):
        """Test gc() called inside a loop"""
        expect_output('''
func main() -> int
    sum: int = 0
    for i in 0..5
        gc()
        sum = sum + i
    ~
    print(sum)
    return 0
~
''', "10\n")

    def test_gc_with_list(self, expect_output):
        """Test gc() with list allocation"""
        expect_output('''
func main() -> int
    items: List<int> = [1, 2, 3, 4, 5]
    gc()
    print(items.len())
    return 0
~
''', "5\n")

    def test_gc_with_user_type(self, expect_output):
        """Test gc() with user-defined type"""
        expect_output('''
type Point:
    x: int
    y: int
~

func main() -> int
    p: Point = Point(x: 10, y: 20)
    gc()
    print(p.x + p.y)
    return 0
~
''', "30\n")

    def test_gc_after_function_call(self, expect_output):
        """Test gc() after function that allocates"""
        expect_output('''
func make_list() -> List<int>
    return [1, 2, 3]
~

func main() -> int
    items: List<int> = make_list()
    gc()
    print(items.len())
    return 0
~
''', "3\n")

    def test_gc_preserves_nested_references(self, expect_output):
        """Test that gc() preserves nested object references"""
        expect_output('''
type Node:
    value: int
~

func main() -> int
    n1: Node = Node(value: 10)
    n2: Node = Node(value: 20)
    gc()
    print(n1.value + n2.value)
    return 0
~
''', "30\n")

    def test_gc_with_string(self, expect_output):
        """Test gc() with string values"""
        expect_output('''
func main() -> int
    s: string = "hello"
    gc()
    print(s.len())
    return 0
~
''', "5\n")

    def test_gc_with_map(self, expect_output):
        """Test gc() with map allocation"""
        expect_output('''
func main() -> int
    m: Map<int, int> = {1: 10, 2: 20}
    gc()
    print(m.get(1))
    return 0
~
''', "10\n")

    def test_gc_with_set(self, expect_output):
        """Test gc() with set allocation"""
        expect_output('''
func main() -> int
    s: Set<int> = {1, 2, 3}
    gc()
    print(s.len())
    return 0
~
''', "3\n")


class TestGCWithControlFlow:
    """Tests for GC interaction with control flow"""

    def test_gc_in_if_branch(self, expect_output):
        """Test gc() in conditional branch"""
        expect_output('''
func main() -> int
    x: int = 5
    if x > 0
        gc()
        print(1)
    else
        print(0)
    ~
    return 0
~
''', "1\n")

    def test_gc_preserves_across_if(self, expect_output):
        """Test values preserved across gc() in conditional"""
        expect_output('''
func main() -> int
    items: List<int> = [1, 2, 3]
    if true
        gc()
    ~
    print(items.len())
    return 0
~
''', "3\n")

    def test_gc_in_nested_function(self, expect_output):
        """Test gc() called from nested function"""
        expect_output('''
func trigger_gc() -> int
    gc()
    return 1
~

func main() -> int
    x: List<int> = [1, 2, 3]
    trigger_gc()
    print(x.len())
    return 0
~
''', "3\n")


class TestGCMemoryReclamation:
    """Tests for memory reclamation behavior"""

    def test_gc_after_many_allocations(self, expect_output):
        """Test gc() after creating many temporary objects"""
        expect_output('''
func create_list() -> int
    temp: List<int> = [1, 2, 3, 4, 5]
    return temp.len()
~

func main() -> int
    for i in 0..10
        create_list()
    ~
    gc()
    print(42)
    return 0
~
''', "42\n")

    def test_gc_with_recursive_function(self, expect_output):
        """Test gc() after recursive function that allocates"""
        expect_output('''
func sum_to(n: int) -> int
    if n <= 0
        return 0
    ~
    return n + sum_to(n - 1)
~

func main() -> int
    result: int = sum_to(5)
    gc()
    print(result)
    return 0
~
''', "15\n")

    def test_gc_allocate_after_collecting_garbage(self, expect_output):
        """Test allocating new objects after gc() has reclaimed garbage.

        This test creates many temporary allocations, runs gc() to reclaim them,
        then tries to allocate a new object using the reclaimed memory.
        """
        expect_output('''
type Node:
    value: int
~

func create_garbage() -> int
    garbage: List<int> = [1, 2, 3, 4, 5, 6, 7, 8, 9, 10]
    return 0
~

func main() -> int
    # Create lots of garbage
    for i in 0..100
        create_garbage()
    ~

    # Collect the garbage
    gc()

    # Allocate new object - should use reclaimed memory
    node: Node = Node(value: 42)
    print(node.value)
    return 0
~
''', "42\n")


class TestGCShadowStack:
    """Tests for shadow stack GC integration"""

    def test_gc_shadow_stack_preserves_live_in_loop(self, expect_output):
        """Test that shadow stack correctly tracks variables across loop iterations.

        Creates garbage in a loop while keeping a live reference.
        The live reference should survive multiple gc() calls.
        """
        expect_output('''
func main() -> int
    live: List<int> = [1, 2, 3]

    for i in 0..10
        garbage: List<int> = [i, i+1, i+2]
        gc()
    ~

    print(live.len())
    return 0
~
''', "3\n")

    def test_gc_shadow_stack_with_nested_functions(self, expect_output):
        """Test shadow stack frames are properly pushed/popped with nested calls."""
        expect_output('''
func inner(s: string) -> int
    gc()
    return s.len()
~

func middle(s: string) -> int
    prefix: string = ">"
    gc()
    return inner(s)
~

func main() -> int
    text: string = "hello"
    result: int = middle(text)
    gc()
    print(result)
    return 0
~
''', "5\n")

    def test_gc_shadow_stack_preserves_all_live_roots(self, expect_output):
        """Test that all live variables in scope are preserved across gc()."""
        expect_output('''
func main() -> int
    a: List<int> = [1, 2, 3]
    b: Map<int, int> = {1: 10, 2: 20}
    c: Set<int> = {5, 6, 7}
    d: string = "test"

    gc()

    total: int = a.len() + b.len() + c.len() + d.len()
    print(total)
    return 0
~
''', "12\n")


class TestGCMapSetStress:
    """Stress tests for GC with Map and Set allocations.

    These tests verify that memory is properly reclaimed for HAMT-based
    collections, which use structural sharing and have complex allocation
    patterns.
    """

    def test_gc_map_stress_create_and_collect(self, expect_output):
        """Create many Maps in a loop with gc() calls - verifies HAMT marking works."""
        expect_output('''
func main() -> int
    live: Map<int, int> = {1: 100}

    for i in 0..50
        temp: Map<int, int> = {(i): i * 10}
        gc()
    ~

    print(live.get(1))
    return 0
~
''', "100\n")

    def test_gc_map_literal_then_gc(self, expect_output):
        """Test map literal construction followed by gc() - the minimal failing case."""
        expect_output('''
func main() -> int
    m: Map<int, int> = {1: 10, 2: 20, 3: 30}
    gc()
    print(m.get(1))
    print(m.get(2))
    print(m.get(3))
    return 0
~
''', "10\n20\n30\n")

    def test_gc_set_stress_create_and_collect(self, expect_output):
        """Create many Sets in a loop with gc() calls - verifies HAMT marking works."""
        expect_output('''
func main() -> int
    live: Set<int> = {100, 200, 300}

    for i in 0..50
        temp: Set<int> = {i, i + 1, i + 2}
        gc()
    ~

    print(live.len())
    return 0
~
''', "3\n")

    def test_gc_map_mutation_across_gc(self, expect_output):
        """Test map mutations interleaved with gc() calls."""
        expect_output('''
func main() -> int
    m: Map<int, int> = {1: 10}
    gc()
    m = m.set(2, 20)
    gc()
    m = m.set(3, 30)
    gc()
    print(m.len())
    print(m.get(1))
    print(m.get(2))
    print(m.get(3))
    return 0
~
''', "3\n10\n20\n30\n")

    def test_gc_reclaims_intermediate_maps(self, expect_output):
        """Verify that intermediate Map allocations are reclaimed.

        This test creates garbage by building a large map then replacing it.
        If GC properly reclaims intermediate maps, this should complete
        without running out of memory even with small allocators.
        """
        expect_output('''
func build_map(n: int) -> Map<int, int>
    m: Map<int, int> = {}
    for i in 0..n
        m = m.set(i, i * 2)
    ~
    return m
~

func main() -> int
    for round in 0..10
        temp: Map<int, int> = build_map(20)
        gc()
    ~

    final: Map<int, int> = build_map(5)
    print(final.get(3))
    return 0
~
''', "6\n")


class TestScopeArena:
    """Tests for scope arena allocation (Phase 6).

    Scope arenas provide fast bump allocation for formulas. Temporary
    allocations in formulas are bulk-freed when the function returns.
    """

    def test_formula_with_temp_list(self, expect_output):
        """Test formula with temporary list that is NOT returned.

        The list should be arena-allocated and bulk-freed on return.
        """
        expect_output('''
formula sum_temp_list() -> int
    const temp = [1, 2, 3, 4, 5]
    const total = temp.len()
    return total
~

func main() -> int
    const result = sum_temp_list()
    print(result)
    return 0
~
''', "5\n")

    def test_formula_many_temp_allocations(self, expect_output):
        """Test formula with many temporary allocations.

        This stress tests arena allocation - all temps should be
        arena-allocated and bulk-freed.
        """
        expect_output('''
formula compute_sum(n: int) -> int
    const sum = 0
    const result = sum + n
    return result
~

func main() -> int
    const total = 0
    for i in 0..100
        const val = compute_sum(i)
    ~
    print(42)
    return 0
~
''', "42\n")

    def test_nested_formula_calls(self, expect_output):
        """Test nested formula calls each with their own arena scope.

        Each formula should have its own arena that is popped on return.
        """
        expect_output('''
formula inner(x: int) -> int
    const temp = x * 2
    return temp
~

formula outer(y: int) -> int
    const a = inner(y)
    const b = inner(y + 1)
    return a + b
~

func main() -> int
    const result = outer(5)
    print(result)
    return 0
~
''', "22\n")

    def test_formula_stress_no_oom(self, expect_output):
        """Stress test: Many formula calls should not cause OOM.

        Each formula call creates a temporary, but the arena is freed
        on return, so memory usage should stay bounded.
        """
        expect_output('''
formula create_temp(n: int) -> int
    const x = n * 2
    return x
~

func main() -> int
    const total = 0
    for i in 0..10000
        const val = create_temp(i)
    ~
    print(1)
    return 0
~
''', "1\n")


class TestArenaEscapePromotion:
    """Tests for arena escape promotion.

    When a formula returns a heap-allocated value (like a list, string, map),
    the value is automatically promoted from the arena to the GC heap before
    the arena is freed. This ensures the returned value survives.
    """

    def test_formula_returns_list(self, expect_output):
        """Test formula returning a list - list must be promoted to heap."""
        expect_output('''
formula make_list() -> List<int>
    const result = [1, 2, 3, 4, 5]
    return result
~

func main() -> int
    const items = make_list()
    print(items.len())
    print(items.get(0))
    print(items.get(4))
    return 0
~
''', "5\n1\n5\n")

    def test_formula_returns_string(self, expect_output):
        """Test formula returning a string - string must be promoted to heap."""
        expect_output('''
formula make_greeting(name: string) -> string
    const greeting = "Hello, " + name + "!"
    return greeting
~

func main() -> int
    const msg = make_greeting("World")
    print(msg.len())
    return 0
~
''', "13\n")

    def test_formula_returns_map(self, expect_output):
        """Test formula returning a map - map must be promoted to heap."""
        expect_output('''
formula make_map() -> Map<int, int>
    const m = {1: 10, 2: 20, 3: 30}
    return m
~

func main() -> int
    const data = make_map()
    print(data.len())
    print(data.get(1))
    print(data.get(3))
    return 0
~
''', "3\n10\n30\n")

    def test_nested_formula_returns_collection(self, expect_output):
        """Test nested formulas returning collections - all must be promoted."""
        expect_output('''
formula inner_list(n: int) -> List<int>
    const result = [n, n * 2, n * 3]
    return result
~

formula outer_wrapper(n: int) -> List<int>
    const inner = inner_list(n)
    return inner
~

func main() -> int
    const items = outer_wrapper(5)
    print(items.len())
    print(items.get(0))
    print(items.get(2))
    return 0
~
''', "3\n5\n15\n")

    def test_formula_gc_after_return(self, expect_output):
        """Test that promoted values survive GC after formula return."""
        expect_output('''
formula make_data() -> List<int>
    const data = [100, 200, 300]
    return data
~

func main() -> int
    const items = make_data()
    gc()
    print(items.len())
    print(items.get(1))
    return 0
~
''', "3\n200\n")

    def test_formula_stress_returning_lists(self, expect_output):
        """Stress test: Many formula calls returning lists.

        Tests that promotion works correctly under load and doesn't
        cause memory leaks or corruption.
        """
        expect_output('''
formula make_list_n(n: int) -> List<int>
    const result = [n, n + 1, n + 2]
    return result
~

func main() -> int
    const last_len = 0
    for i in 0..100
        const items = make_list_n(i)
        const last_len = items.len()
    ~
    print(last_len)
    gc()
    print(1)
    return 0
~
''', "3\n1\n")
