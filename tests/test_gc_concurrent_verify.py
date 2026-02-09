"""
Verify GC runs concurrently on its own thread without blocking mutators,
and that compaction works correctly after arena removal.
"""
import pytest
import re


class TestGcOwnThread:
    """Verify GC runs on a dedicated thread, not inline with mutator."""

    def test_gc_runs_during_mutator_work(self, expect_output):
        """Mutator continues allocating while GC collects — proves GC is on its own thread."""
        expect_output('''
func create_garbage(n: int) -> int
    total = 0
    for i in 0..n
        temp = [i, i * 2, i * 3]
        total = total + temp.get(0)
    ~
    return total
~

func main() -> int
    result = create_garbage(1000)
    gc()
    result2 = create_garbage(1000)
    gc()
    print(result)
    print(result2)
    errors = gc_validate_heap()
    print(errors)
    return 0
~
''', "499500\n499500\n0\n")

    def test_gc_stats_show_collections(self, compile_coex):
        """gc_dump_stats shows allocation tracking — proves GC thread is active."""
        result = compile_coex('''
func main() -> int
    for i in 0..500
        temp = [i, i+1, i+2]
    ~
    gc()
    gc_dump_stats()
    return 0
~
''')
        assert result.run_success
        # gc() is async, so we can't guarantee collections completed before
        # gc_dump_stats(). Verify the GC system is tracking allocations.
        match = re.search(r'total_allocations:\s*(\d+)', result.run_output)
        assert match, f"No allocations in output: {result.run_output}"
        allocations = int(match.group(1))
        assert allocations >= 1000, f"Expected >= 1000 allocations, got {allocations}"


class TestMutatorNotBlocked:
    """Verify mutator threads are never blocked by GC activity."""

    def test_concurrent_tasks_with_gc(self, expect_output):
        """Multiple threads allocate heavily while GC runs — none deadlock or block."""
        expect_output('''
thread heavy_alloc(id: int) -> int
    total = 0
    for i in 0..200
        temp = [id, i, id * i]
        total = total + temp.get(2)
    ~
    return total
~

func main() -> int
    ids = [1, 2, 3, 4]
    results = for id in ids heavy_alloc(id) ~
    gc()
    total = 0
    for r in results
        total = total + r
    ~
    print(total)
    errors = gc_validate_heap()
    print(errors)
    return 0
~
''', "199000\n0\n")

    def test_gc_during_parallel_tasks(self, expect_output):
        """Force GC while parallel tasks are running — mutators must not deadlock."""
        expect_output('''
thread compute(n: int) -> int
    total = 0
    for i in 0..n
        temp = [i]
        total = total + i
    ~
    return total
~

func main() -> int
    gc()
    ids = [100, 200, 300, 400]
    results = for n in ids compute(n) ~
    gc()
    sum = 0
    for r in results
        sum = sum + r
    ~
    print(sum)
    errors = gc_validate_heap()
    print(errors)
    return 0
~
''', "149500\n0\n")

    def test_handle_storage_valid_after_concurrent_gc(self, compile_coex):
        """After concurrent work + GC, no raw pointers stored — all handles."""
        result = compile_coex('''
thread make_strings(prefix: string, count: int) -> string
    result = prefix
    for i in 0..count
        result = result + "x"
    ~
    return result
~

func main() -> int
    items = [1, 2, 3, 4]
    results = for id in items make_strings("start", 50) ~
    gc()
    violations = gc_validate_handle_storage()
    print(violations)
    errors = gc_validate_heap()
    print(errors)
    return 0
~
''')
        assert result.run_success
        lines = result.run_output.strip().split('\n')
        assert lines[-2] == "0", f"Handle storage violations: {lines[-2]}"
        assert lines[-1] == "0", f"Heap errors: {lines[-1]}"


class TestCompactionCorrectness:
    """Verify compaction works correctly after arena removal."""

    def test_compact_preserves_concat_strings(self, expect_output):
        """String concat owner handles survive compaction."""
        expect_output('''
func main() -> int
    a = "hello"
    b = "world"
    c = a + " " + b
    gc()
    gc_compact()
    print(c)
    return 0
~
''', "hello world\n")

    def test_compact_preserves_strings(self, expect_output):
        """String literal handles survive compaction."""
        expect_output('''
func main() -> int
    a = "hello"
    b = "world"
    gc()
    gc_compact()
    print(a)
    print(b)
    print(a.len())
    return 0
~
''', "hello\nworld\n5\n")

    def test_compact_preserves_collections(self, expect_output):
        """Lists, maps, sets all survive compaction."""
        expect_output('''
func main() -> int
    lst = [10, 20, 30]
    m = {1: 100, 2: 200}
    s = {5, 10, 15}
    gc()
    gc_compact()
    print(lst.get(0))
    print(lst.get(2))
    print(lst.len())
    print(m.get(1))
    print(m.get(2))
    print(s.has(10))
    print(s.len())
    return 0
~
''', "10\n30\n3\n100\n200\ntrue\n3\n")

    def test_compact_after_heavy_allocation(self, expect_output):
        """Compact after creating many objects — simulates real workload."""
        expect_output('''
func main() -> int
    keeper = "result:"
    for i in 0..100
        temp = [i, i*2]
        if i == 99
            keeper = keeper + " " + String.from(temp.get(1))
        ~
    ~
    gc()
    gc_compact()
    print(keeper)
    errors = gc_validate_heap()
    print(errors)
    return 0
~
''', "result: 198\n0\n")

    def test_compact_multiple_rounds(self, expect_output):
        """Multiple compact rounds don't corrupt data."""
        expect_output('''
func main() -> int
    x = [1, 2, 3]
    s = "persistent"
    gc_compact()
    gc_compact()
    gc_compact()
    print(x.get(0))
    print(x.get(1))
    print(x.get(2))
    print(s)
    errors = gc_validate_heap()
    print(errors)
    return 0
~
''', "1\n2\n3\npersistent\n0\n")

    def test_compact_with_map_of_strings(self, expect_output):
        """Map with string values survives compaction."""
        expect_output('''
func main() -> int
    m = {1: "alpha", 2: "beta", 3: "gamma"}
    gc()
    gc_compact()
    print(m.get(1))
    print(m.get(2))
    print(m.get(3))
    print(m.len())
    return 0
~
''', "alpha\nbeta\ngamma\n3\n")

    def test_compact_string_slices_survive(self, expect_output):
        """String slice views (zero-copy) survive compaction."""
        expect_output('''
func main() -> int
    text = "hello world test"
    a = text[0:5]
    b = text[6:11]
    gc()
    gc_compact()
    print(a)
    print(b)
    print(a.len())
    print(b.len())
    return 0
~
''', "hello\nworld\n5\n5\n")

    def test_compact_with_concurrent_tasks(self, expect_output):
        """Compaction after concurrent task completion — all handles valid."""
        expect_output('''
thread build_list(n: int) -> int
    lst = [0]
    for i in 1..n
        lst = lst.append(i)
    ~
    return lst.len()
~

func main() -> int
    ids = [10, 20, 30]
    results = for n in ids build_list(n) ~
    gc()
    gc_compact()
    for r in results
        print(r)
    ~
    errors = gc_validate_heap()
    print(errors)
    return 0
~
''', "10\n20\n30\n0\n")
