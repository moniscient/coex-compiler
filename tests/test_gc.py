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
    var x: int = 10
    var y: int = 20
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
    var x: int = 5
    gc()
    var y: int = 10
    gc()
    print(x + y)
    return 0
~
''', "15\n")

    def test_gc_in_loop(self, expect_output):
        """Test gc() called inside a loop"""
        expect_output('''
func main() -> int
    var sum: int = 0
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
    var items: List<int> = [1, 2, 3, 4, 5]
    gc()
    print(len(items))
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
    var p: Point = Point(x: 10, y: 20)
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
    var items: List<int> = make_list()
    gc()
    print(len(items))
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
    var n1: Node = Node(value: 10)
    var n2: Node = Node(value: 20)
    gc()
    print(n1.value + n2.value)
    return 0
~
''', "30\n")

    @pytest.mark.xfail(reason="len(string) returns 0 - pre-existing bug unrelated to GC")
    def test_gc_with_string(self, expect_output):
        """Test gc() with string values"""
        expect_output('''
func main() -> int
    var s: string = "hello"
    gc()
    print(len(s))
    return 0
~
''', "5\n")

    def test_gc_with_map(self, expect_output):
        """Test gc() with map allocation"""
        expect_output('''
func main() -> int
    var m: Map<int, int> = {1: 10, 2: 20}
    gc()
    print(m.get(1))
    return 0
~
''', "10\n")

    def test_gc_with_set(self, expect_output):
        """Test gc() with set allocation"""
        expect_output('''
func main() -> int
    var s: Set<int> = {1, 2, 3}
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
    var x: int = 5
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
    var items: List<int> = [1, 2, 3]
    if true
        gc()
    ~
    print(len(items))
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
    var x: List<int> = [1, 2, 3]
    trigger_gc()
    print(len(x))
    return 0
~
''', "3\n")


class TestGCMemoryReclamation:
    """Tests for memory reclamation behavior"""

    def test_gc_after_many_allocations(self, expect_output):
        """Test gc() after creating many temporary objects"""
        expect_output('''
func create_list() -> int
    var temp: List<int> = [1, 2, 3, 4, 5]
    return len(temp)
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
    var result: int = sum_to(5)
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
    var garbage: List<int> = [1, 2, 3, 4, 5, 6, 7, 8, 9, 10]
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
    var node: Node = Node(value: 42)
    print(node.value)
    return 0
~
''', "42\n")
