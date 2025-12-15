import pytest

class TestMoveOperator:
    """Test the := (eager assign / move) operator."""

    def test_move_basic(self, expect_output):
        """:= transfers ownership, original can't be used."""
        expect_output('''
func main() -> int
    var list: List<int> = [1, 2, 3]
    var a: Array<int> = list.packed()
    var b := a
    print(b.get(0))
    print(b.len())
    return 0
~
''', "1\n3\n")

    def test_move_then_mutate_no_copy(self, expect_output):
        """After move, mutations are always in-place (O(1))."""
        expect_output('''
func main() -> int
    var list: List<int> = [1, 2, 3]
    var a: Array<int> = list.packed()
    var b := a
    b = b.set(0, 10)
    b = b.set(1, 20)
    b = b.append(4)
    print(b.get(0))
    print(b.get(1))
    print(b.len())
    return 0
~
''', "10\n20\n4\n")

    def test_move_string(self, expect_output):
        """:= works with strings."""
        expect_output('''
func main() -> int
    var a: string = "hello"
    var b := a
    b = b + " world"
    print(b)
    return 0
~
''', "hello world\n")

    def test_eager_copy_when_shared(self, expect_output):
        """When source is shared, := copies immediately, giving c its own copy."""
        # After c := a, a is invalidated (can't use a anymore)
        # But b still has its shared reference from before the move
        # c gets an independent copy (refcount = 1)
        expect_output('''
func main() -> int
    var list: List<int> = [1, 2, 3]
    var a: Array<int> = list.packed()
    var b: Array<int> = a
    var c := a
    c = c.set(0, 99)
    print(b.get(0))
    print(c.get(0))
    return 0
~
''', "1\n99\n")

    def test_eager_copy_gives_sole_ownership(self, expect_output):
        """Verify := with mutation returns new value.

        With GC-based memory (no refcounting), all mutations return new arrays.
        You must capture the result to see the change.
        """
        expect_output('''
func main() -> int
    var list: List<int> = [1, 2, 3]
    var a: Array<int> = list.packed()
    var b: Array<int> = a
    var c := a
    c = c.set(0, 99)
    print(c.get(0))
    print(b.get(0))
    return 0
~
''', "99\n1\n")

    def test_move_in_function(self, expect_output):
        """:= works inside functions."""
        expect_output('''
func process(data: Array<int>) -> int
    var local := data
    local = local.set(0, 100)
    return local.get(0)
~

func main() -> int
    var list: List<int> = [1, 2, 3]
    var arr: Array<int> = list.packed()
    var result: int = process(arr)
    print(result)
    print(arr.get(0))
    return 0
~
''', "100\n1\n")

    def test_move_var_declaration(self, expect_output):
        """var declaration with := ."""
        expect_output('''
func main() -> int
    var list1: List<int> = [1, 2, 3]
    var a: Array<int> = list1.packed()
    var b := a
    b.set(0, 10)
    var list2: List<int> = [4, 5, 6]
    b := list2.packed()
    print(b.get(0))
    return 0
~
''', "4\n")

    def test_move_chain(self, expect_output):
        """Chain of moves."""
        expect_output('''
func main() -> int
    var list: List<int> = [1, 2, 3]
    var a: Array<int> = list.packed()
    var b := a
    var c := b
    var d := c
    d = d.set(0, 99)
    print(d.get(0))
    return 0
~
''', "99\n")

    def test_lazy_vs_eager_comparison(self, expect_output):
        """Compare = and := behavior.

        With GC-based memory, both = and := share pointers.
        All mutations return new arrays, so you must capture the result.
        """
        expect_output('''
func main() -> int
    var list1: List<int> = [1, 2, 3]
    var a1: Array<int> = list1.packed()
    var b1: Array<int> = a1
    b1 = b1.set(0, 10)
    print(a1.get(0))

    var list2: List<int> = [1, 2, 3]
    var a2: Array<int> = list2.packed()
    var b2 := a2
    b2 = b2.set(0, 10)
    print(b2.get(0))
    return 0
~
''', "1\n10\n")


class TestUseAfterMove:
    """Test compile-time detection of use-after-move errors."""

    def test_use_after_move_error(self, compile_coex):
        """Using a moved variable should be a compile error."""
        result = compile_coex('''
func main() -> int
    var list: List<int> = [1, 2, 3]
    var a: Array<int> = list.packed()
    var b := a
    print(a.get(0))
    return 0
~
''')
        assert not result.compile_success, "Expected compilation to fail"
        assert "moved" in result.compile_output.lower() or "use after move" in result.compile_output.lower(), \
            f"Expected 'moved' or 'use after move' in error message, got: {result.compile_output}"

    def test_use_after_move_in_expression(self, compile_coex):
        """Using moved variable in expression should error."""
        result = compile_coex('''
func main() -> int
    var list: List<int> = [1, 2, 3]
    var a: Array<int> = list.packed()
    var b := a
    var c: int = a.len()
    return 0
~
''')
        assert not result.compile_success, "Expected compilation to fail"
        assert "moved" in result.compile_output.lower() or "use after move" in result.compile_output.lower(), \
            f"Expected 'moved' or 'use after move' in error message, got: {result.compile_output}"

    def test_move_then_reassign_ok(self, compile_coex, expect_output):
        """Reassigning a moved variable should be allowed."""
        expect_output('''
func main() -> int
    var list1: List<int> = [1, 2, 3]
    var a: Array<int> = list1.packed()
    var b := a
    var list2: List<int> = [4, 5, 6]
    a = list2.packed()
    print(a.get(0))
    print(b.get(0))
    return 0
~
''', "4\n1\n")

    def test_conditional_move_error(self, compile_coex):
        """Move in one branch, use in another should error."""
        result = compile_coex('''
func main() -> int
    var list: List<int> = [1, 2, 3]
    var a: Array<int> = list.packed()
    if true
        var b := a
    ~
    print(a.get(0))
    return 0
~
''')
        assert not result.compile_success, "Expected compilation to fail"
