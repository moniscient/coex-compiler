import pytest

class TestMoveOperator:
    """Test the := (eager assign / move) operator."""

    def test_move_basic(self, expect_output):
        """:= transfers ownership, original can't be used."""
        expect_output('''
func main() -> int
    list: List<int> = [1, 2, 3]
    a: Array<int> = list.packed()
    b := a
    print(b.get(0))
    print(b.len())
    return 0
~
''', "1\n3\n")

    def test_move_then_mutate_no_copy(self, expect_output):
        """After move, mutations are always in-place (O(1))."""
        expect_output('''
func main() -> int
    list: List<int> = [1, 2, 3]
    a: Array<int> = list.packed()
    b := a
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
    a: string = "hello"
    b := a
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
    list: List<int> = [1, 2, 3]
    a: Array<int> = list.packed()
    b: Array<int> = a
    c := a
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
    list: List<int> = [1, 2, 3]
    a: Array<int> = list.packed()
    b: Array<int> = a
    c := a
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
    local := data
    local = local.set(0, 100)
    return local.get(0)
~

func main() -> int
    list: List<int> = [1, 2, 3]
    arr: Array<int> = list.packed()
    result: int = process(arr)
    print(result)
    print(arr.get(0))
    return 0
~
''', "100\n1\n")

    def test_move_var_declaration(self, expect_output):
        """declaration with := ."""
        expect_output('''
func main() -> int
    list1: List<int> = [1, 2, 3]
    a: Array<int> = list1.packed()
    b := a
    b.set(0, 10)
    list2: List<int> = [4, 5, 6]
    b := list2.packed()
    print(b.get(0))
    return 0
~
''', "4\n")

    def test_move_chain(self, expect_output):
        """Chain of moves."""
        expect_output('''
func main() -> int
    list: List<int> = [1, 2, 3]
    a: Array<int> = list.packed()
    b := a
    c := b
    d := c
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
    list1: List<int> = [1, 2, 3]
    a1: Array<int> = list1.packed()
    b1: Array<int> = a1
    b1 = b1.set(0, 10)
    print(a1.get(0))

    list2: List<int> = [1, 2, 3]
    a2: Array<int> = list2.packed()
    b2 := a2
    b2 = b2.set(0, 10)
    print(b2.get(0))
    return 0
~
''', "1\n10\n")


class TestUseAfterMove:
    """Test compile-time detection of use-after-move errors.

    With the ownership system:
    - `unique` bindings have sole ownership
    - `=` operator moves unique bindings (source invalidated)
    - `:=` operator copies (source preserved)
    """

    def test_use_after_move_error(self, compile_coex):
        """Using a moved unique variable should be a compile error."""
        result = compile_coex('''
func main() -> int
    unique a: Array<int> = [1, 2, 3].toArray()
    b = a
    print(a.get(0))
    return 0
~
''')
        assert not result.compile_success, "Expected compilation to fail"
        assert "moved" in result.compile_output.lower(), \
            f"Expected 'moved' in error message, got: {result.compile_output}"

    def test_use_after_move_in_expression(self, compile_coex):
        """Using moved unique variable in expression should error."""
        result = compile_coex('''
func main() -> int
    unique a: Array<int> = [1, 2, 3].toArray()
    b = a
    c: int = a.len()
    return 0
~
''')
        assert not result.compile_success, "Expected compilation to fail"
        assert "moved" in result.compile_output.lower(), \
            f"Expected 'moved' in error message, got: {result.compile_output}"

    def test_move_then_reassign_ok(self, compile_coex, expect_output):
        """Reassigning a moved unique variable should be allowed."""
        expect_output('''
func main() -> int
    unique a: Array<int> = [1, 2, 3].toArray()
    b = a
    a = [4, 5, 6].toArray()
    print(a.get(0))
    print(b.get(0))
    return 0
~
''', "4\n1\n")

    def test_conditional_move_error(self, compile_coex):
        """Move in one branch, use in another should error."""
        result = compile_coex('''
func main() -> int
    unique a: Array<int> = [1, 2, 3].toArray()
    if true
        b = a
    ~
    print(a.get(0))
    return 0
~
''')
        assert not result.compile_success, "Expected compilation to fail"
        # Either "moved" or "may or may not be moved" in error
        assert "moved" in result.compile_output.lower(), \
            f"Expected 'moved' in error message, got: {result.compile_output}"

    def test_copy_preserves_source(self, expect_output):
        """Copy operator := should preserve source binding."""
        expect_output('''
func main() -> int
    unique a: Array<int> = [1, 2, 3].toArray()
    b := a
    print(a.len())
    print(b.len())
    return 0
~
''', "3\n3\n")

    def test_move_in_loop_error(self, compile_coex):
        """Moving unique binding inside loop should error."""
        result = compile_coex('''
func main() -> int
    unique a: Array<int> = [1, 2, 3].toArray()
    for i in 0..3
        b = a
    ~
    return 0
~
''')
        assert not result.compile_success, "Expected compilation to fail"
        assert "loop" in result.compile_output.lower() or "moved" in result.compile_output.lower(), \
            f"Expected 'loop' or 'moved' in error message, got: {result.compile_output}"

    def test_copy_in_loop_ok(self, expect_output):
        """Copy operator := inside loop should work."""
        expect_output('''
func main() -> int
    unique a: Array<int> = [1, 2, 3].toArray()
    for i in 0..3
        b := a
        print(b.len())
    ~
    print(a.len())
    return 0
~
''', "3\n3\n3\n3\n")


class TestBorrowChecking:
    """Test borrow checking for borrowed parameters."""

    def test_borrow_read_access_ok(self, expect_output):
        """Borrowed binding allows read access."""
        expect_output('''
func sum_array(borrow arr: Array<int>) -> int
    total = 0
    for i in 0..arr.len()
        total = total + arr.get(i)
    ~
    return total
~

func main() -> int
    a: Array<int> = [1, 2, 3, 4, 5].toArray()
    result = sum_array(a)
    print(result)
    print(a.len())
    return 0
~
''', "15\n5\n")

    def test_cannot_return_borrowed(self, compile_coex):
        """Cannot return borrowed binding."""
        result = compile_coex('''
func try_return(borrow arr: Array<int>) -> Array<int>
    return arr
~

func main() -> int
    a: Array<int> = [1, 2, 3].toArray()
    result = try_return(a)
    return 0
~
''')
        assert not result.compile_success, "Expected compilation to fail"
        assert "borrowed" in result.compile_output.lower(), \
            f"Expected 'borrowed' in error message, got: {result.compile_output}"

    def test_cannot_move_borrowed(self, compile_coex):
        """Cannot move borrowed binding."""
        result = compile_coex('''
func try_move(borrow arr: Array<int>) -> int
    b = arr
    return b.len()
~

func main() -> int
    a: Array<int> = [1, 2, 3].toArray()
    result = try_move(a)
    return 0
~
''')
        assert not result.compile_success, "Expected compilation to fail"
        assert "borrowed" in result.compile_output.lower(), \
            f"Expected 'borrowed' in error message, got: {result.compile_output}"

    def test_cannot_store_borrowed(self, compile_coex):
        """Cannot store borrowed binding with copy operator."""
        result = compile_coex('''
func try_store(borrow arr: Array<int>) -> int
    b := arr
    return b.len()
~

func main() -> int
    a: Array<int> = [1, 2, 3].toArray()
    result = try_store(a)
    return 0
~
''')
        assert not result.compile_success, "Expected compilation to fail"
        assert "borrowed" in result.compile_output.lower(), \
            f"Expected 'borrowed' in error message, got: {result.compile_output}"

    def test_borrow_does_not_invalidate_caller(self, expect_output):
        """Passing to borrow param does not invalidate caller's binding."""
        expect_output('''
func inspect(borrow arr: Array<int>) -> int
    return arr.len()
~

func main() -> int
    unique a: Array<int> = [1, 2, 3].toArray()
    len1 = inspect(a)
    len2 = inspect(a)
    print(len1)
    print(len2)
    print(a.len())
    return 0
~
''', "3\n3\n3\n")


class TestUniqueRebinding:
    """Test rebinding unique bindings (valid patterns)."""

    def test_unique_loop_rebinding(self, expect_output):
        """Rebinding unique var in loop body is valid (arr = arr.append(x))."""
        expect_output('''
func main() -> int
    unique arr: Array<int> = [].toArray()
    for i in 0..5
        arr = arr.append(i)
    ~
    print(arr.len())
    return 0
~
''', "5\n")

    def test_unique_self_update(self, expect_output):
        """Self-update pattern with unique binding."""
        expect_output('''
func main() -> int
    unique arr: Array<int> = [1, 2, 3].toArray()
    arr = arr.set(0, 10)
    arr = arr.set(1, 20)
    print(arr.get(0))
    print(arr.get(1))
    return 0
~
''', "10\n20\n")

    def test_move_on_all_branches_ok(self, expect_output):
        """Moving on all branches is valid."""
        expect_output('''
func main() -> int
    unique a: Array<int> = [1, 2, 3].toArray()
    if true
        b = a
        print(b.len())
    else
        c = a
        print(c.len())
    ~
    return 0
~
''', "3\n")


class TestCopyToNonUnique:
    """Test copying from unique to non-unique bindings."""

    def test_copy_unique_to_regular(self, expect_output):
        """Copy from unique to regular binding."""
        expect_output('''
func main() -> int
    unique a: Array<int> = [1, 2, 3].toArray()
    b := a
    b = b.set(0, 99)
    print(a.get(0))
    print(b.get(0))
    return 0
~
''', "1\n99\n")

    def test_copy_in_function_call(self, expect_output):
        """Copy operator in function parameter context."""
        expect_output('''
func process(arr: Array<int>) -> int
    return arr.len()
~

func main() -> int
    unique a: Array<int> = [1, 2, 3].toArray()
    result = process(a)
    print(result)
    print(a.len())
    return 0
~
''', "3\n3\n")
