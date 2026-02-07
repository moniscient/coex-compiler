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


class TestGCSafepointDelegation:
    """Tests for BUG-088: safepoint delegates collection to GC thread."""

    def test_safepoint_triggered_gc_preserves_data(self, expect_output):
        """Test that automatic GC triggered via safepoint preserves live data.

        Creates enough allocations to exceed GC_THRESHOLD (100000), triggering
        an automatic GC via safepoint. Verifies that live data survives the
        collection that is now delegated to the GC thread.
        """
        expect_output('''
func allocate_garbage(n: int) -> int
    for i in 0..n
        temp: List<int> = [i, i + 1, i + 2]
    ~
    return n
~

func main() -> int
    live_data: List<int> = [10, 20, 30, 40, 50]
    allocate_garbage(50000)
    print(live_data.len())
    print(live_data.get(2))
    allocate_garbage(50000)
    print(live_data.len())
    print(live_data.get(4))
    return 0
~
''', "5\n30\n5\n50\n")

    def test_safepoint_gc_with_nested_structures(self, expect_output):
        """Test safepoint-triggered GC with nested heap structures.

        Allocates enough to trigger safepoint GC while keeping nested
        structures (maps, lists) alive. Verifies the GC thread correctly
        traces through nested references.
        """
        expect_output('''
func make_garbage() -> int
    for i in 0..60000
        temp: List<int> = [i]
    ~
    return 0
~

func main() -> int
    m: Map<int, int> = {1: 100, 2: 200, 3: 300}
    make_garbage()
    print(m.get(2))
    s: List<int> = [7, 8, 9]
    make_garbage()
    print(s.get(1))
    print(m.get(3))
    return 0
~
''', "200\n8\n300\n")

    def test_gc_json_stringify_in_loop(self, expect_output):
        """Test gc() with json stringify in a loop (BUG-103 regression)"""
        expect_output('''
func main() -> int
    frame = 0
    while frame < 20
        frame = frame + 1
        gc()
        x: json = { type: "test", value: frame }
        s: string = x.stringify()
        if frame == 20
            print(s)
        ~
    ~
    return 0
~
''', '{"value":20,"type":"test"}\n')

    def test_gc_json_stringify_after_gc(self, expect_output):
        """Test gc() after json stringify doesn't corrupt next iteration"""
        expect_output('''
func main() -> int
    frame = 0
    while frame < 20
        frame = frame + 1
        x: json = { type: "test", value: frame }
        s: string = x.stringify()
        gc()
        if frame == 20
            print(s)
        ~
    ~
    return 0
~
''', '{"value":20,"type":"test"}\n')

    def test_gc_nested_json_in_loop(self, expect_output):
        """Test gc() with nested json objects in a loop"""
        expect_output('''
func main() -> int
    frame = 0
    while frame < 30
        frame = frame + 1
        gc()
        layout: json = {
            type: "window",
            children: [
                { type: "text", text: "SCORE: " + String.from(frame) },
                { type: "text", text: "Frame: " + String.from(frame) }
            ]
        }
        s: string = layout.stringify()
    ~
    print("ok")
    return 0
~
''', "ok\n")


class TestGCWatermarkEnforcement:
    """Tests for watermark enforcement in gc_segment_pop.

    Verifies that gc_segment_pop prevents slot_index from dropping below
    the watermark during active GC, ensuring roots are not missed.
    """

    def test_deep_call_stack_with_gc(self, expect_output):
        """Test gc() with deep call stack exercises the watermark blocking path.

        Deep recursion creates many shadow stack frames. gc() in the middle
        forces watermark capture at depth, then unwinding must respect it.
        """
        expect_output('''
func recurse(depth: int, data: List<int>) -> int
    if depth <= 0
        gc()
        return data.get(0) + data.get(1)
    ~
    extra: List<int> = [depth, depth + 1, depth + 2]
    result = recurse(depth - 1, data)
    return result + extra.get(0)
~

func main() -> int
    data: List<int> = [100, 200, 300]
    result = recurse(50, data)
    print(result)
    return 0
~
''', "1575\n")

    def test_gc_across_nested_function_returns(self, expect_output):
        """Test that data survives gc() when multiple functions are on the stack."""
        expect_output('''
func inner(x: List<int>) -> int
    gc()
    return x.get(0)
~

func middle(x: List<int>) -> int
    y: List<int> = [10, 20, 30]
    result = inner(x)
    return result + y.get(2)
~

func outer(x: List<int>) -> int
    z: Map<int, int> = {1: 100, 2: 200}
    result = middle(x)
    return result + z.get(1)
~

func main() -> int
    data: List<int> = [42, 43, 44]
    print(outer(data))
    return 0
~
''', "172\n")

    def test_threshold_gc_with_deep_nesting(self, expect_output):
        """Test automatic threshold-triggered GC with heavy allocation in nested functions.

        Allocates enough garbage to trigger automatic GC (threshold ~100000)
        while keeping live data across deep call stacks.
        """
        expect_output('''
func make_garbage(n: int) -> int
    for i in 0..n
        temp: List<int> = [i, i + 1]
    ~
    return n
~

func level3(data: List<int>) -> int
    make_garbage(40000)
    return data.get(0) + data.get(1)
~

func level2(data: List<int>) -> int
    extra: List<int> = [7, 8, 9]
    result = level3(data)
    make_garbage(40000)
    return result + extra.get(1)
~

func level1(data: List<int>) -> int
    m: Map<int, int> = {1: 10, 2: 20}
    result = level2(data)
    make_garbage(40000)
    return result + m.get(2)
~

func main() -> int
    live: List<int> = [100, 200, 300]
    result = level1(live)
    print(result)
    return 0
~
''', "328\n")

    def test_gc_stress_rapid_alloc_nested_calls(self, expect_output):
        """Stress test: rapid automatic GC with heavy allocation in nested functions.

        Many iterations of nested calls that each allocate enough to trigger GC,
        ensuring watermark enforcement is correct across many cycles.
        """
        expect_output('''
func allocate_and_return(n: int) -> List<int>
    for i in 0..n
        temp: List<int> = [i]
    ~
    return [n]
~

func nested_work(depth: int, acc: int) -> int
    if depth <= 0
        result: List<int> = allocate_and_return(5000)
        return acc + result.get(0)
    ~
    result: List<int> = allocate_and_return(5000)
    return nested_work(depth - 1, acc + result.get(0))
~

func main() -> int
    total = 0
    for i in 0..20
        total = total + nested_work(5, 0)
    ~
    print(total)
    return 0
~
''', "600000\n")

    def test_gc_auto_trigger_multiple_cycles(self, expect_output):
        """Test that automatic GC triggers correctly multiple times without explicit gc() calls.

        Allocates enough objects to trigger GC threshold multiple times.
        Each iteration creates ~5000 temporary lists, and with 100K threshold
        and 30 iterations, this should trigger 1-2 GC cycles automatically.
        Verifies that live data survives all cycles.
        """
        expect_output('''
func churn(n: int) -> int
    total = 0
    for i in 0..n
        temp: List<int> = [i, i+1, i+2]
        total = total + temp.get(0)
    ~
    return total
~

func main() -> int
    live: List<int> = [10, 20, 30]
    result = 0
    for round in 0..30
        result = result + churn(5000)
    ~
    print(live.get(0))
    print(live.get(1))
    print(live.get(2))
    print(result)
    return 0
~
''', "10\n20\n30\n374925000\n")

    def test_gc_no_explicit_gc_heavy_alloc(self, expect_output):
        """Test heavy allocation without any explicit gc() calls.

        Specifically targets the double-reset bug: if gc_alloc_count is
        reset twice (once by safepoint xchg, once by sweep store), the
        second GC trigger is delayed and crashes may occur before it fires.
        """
        expect_output('''
func make_garbage(n: int) -> int
    for i in 0..n
        s = "garbage_" + String.from(i)
    ~
    return n
~

func main() -> int
    total = 0
    for i in 0..50
        total = total + make_garbage(3000)
    ~
    print(total)
    return 0
~
''', "150000\n")

    def test_gc_tlab_reuse_after_sweep(self, expect_output):
        """Test that TLABs with live objects are not prematurely freed.

        Creates a pattern where some objects survive GC while others in
        the same TLAB die. The live_count check before munmap must prevent
        premature TLAB reclamation.
        """
        expect_output('''
func allocate_mixed(keeper: List<int>, n: int, tag: int) -> List<int>
    for i in 0..n
        temp: List<int> = [i * 2]
    ~
    return keeper.append(tag)
~

func main() -> int
    data: List<int> = [0]
    for round in 0..40
        data = allocate_mixed(data, 4000, round)
    ~
    print(data.len())
    print(data.get(0))
    print(data.get(40))
    return 0
~
''', "41\n0\n39\n")

    def test_gc_watermark_with_deep_recursion(self, expect_output):
        """Test watermark enforcement during deep recursion with allocation.

        When gc_phase != 0 and a thread hasn't hit safepoint yet, segment_pop
        must acknowledge the watermark. This test exercises deep call stacks
        with allocation pressure to trigger GC during active recursion.
        """
        expect_output('''
func recursive_alloc(depth: int, acc: int) -> int
    if depth <= 0
        return acc
    ~
    temp: List<int> = [depth, depth+1, depth+2]
    for i in 0..500
        garbage: List<int> = [i]
    ~
    return recursive_alloc(depth - 1, acc + temp.get(0))
~

func main() -> int
    total = 0
    for round in 0..10
        total = total + recursive_alloc(20, 0)
    ~
    print(total)
    return 0
~
''', "2100\n")

    def test_gc_list_of_strings_auto_gc(self, expect_output):
        """Test that strings in lists survive automatic GC.

        Born-marked objects (gen==current) must have children traced during marking,
        otherwise old strings (gen<current) stored in new list nodes get swept.
        This specifically tests the concurrent race where the mutator creates
        a new list containing references to old strings while GC is running.
        """
        expect_output('''
func main() -> int
    frame = 0
    keeper: List<string> = ["alive"]
    while frame < 200
        frame = frame + 1
        i = 0
        while i < 200
            s = "garbage_" + String.from(i)
            i = i + 1
        ~
        keeper = keeper.append("frame_" + String.from(frame))
    ~
    print(keeper.get(0))
    print(keeper.len())
    return 0
~
''', "alive\n201\n")

    def test_gc_list_of_strings_heavy(self, expect_output):
        """Stress test: lists of strings with heavy allocation triggering multiple GC cycles."""
        expect_output('''
func main() -> int
    frame = 0
    while frame < 100
        frame = frame + 1
        items: List<string> = []
        i = 0
        while i < 60
            items = items.append("item_" + String.from(i) + "_frame_" + String.from(frame))
            i = i + 1
        ~
        total_len = 0
        j = 0
        while j < items.len()
            s = items.get(j)
            total_len = total_len + s.len()
            j = j + 1
        ~
        if frame % 50 == 0
            print("Frame " + String.from(frame) + " ok")
        ~
    ~
    print("ok")
    return 0
~
''', "Frame 50 ok\nFrame 100 ok\nok\n")
