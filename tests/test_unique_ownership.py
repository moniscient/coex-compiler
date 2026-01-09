"""Tests for unique ownership system per coex-unique-ownership-spec.md

These tests define the expected behavior of:
- unique variable declarations
- Move semantics (= operator on unique bindings)
- Copy semantics (:= operator)
- Borrow parameters
- Unique parameters and return types
- Control flow (branches, loops)
"""
import pytest


class TestUniqueDeclaration:
    """Test unique variable declarations."""

    def test_unique_array_declaration(self, expect_output):
        """Unique array can be declared and used."""
        expect_output('''
func main() -> int
    unique arr: Array<int> = [1, 2, 3]
    print(arr.len())
    return 0
~
''', "3\n")

    def test_unique_string_declaration(self, expect_output):
        """Unique string can be declared and used."""
        expect_output('''
func main() -> int
    unique name: string = "hello"
    print(name.len())
    return 0
~
''', "5\n")

    def test_unique_inferred_type(self, expect_output):
        """Unique with inferred type works."""
        expect_output('''
func main() -> int
    unique data = [1, 2, 3]
    print(data.len())
    return 0
~
''', "3\n")

    def test_unique_rebinding(self, expect_output):
        """Unique binding can be rebound to itself."""
        expect_output('''
func main() -> int
    unique arr: Array<int> = [1, 2, 3]
    arr = arr.append(4)
    print(arr.len())
    return 0
~
''', "4\n")


class TestMoveSemantics:
    """Test move semantics with = operator on unique bindings."""

    def test_move_invalidates_source(self, compile_coex):
        """Using moved unique binding should be compile error."""
        result = compile_coex('''
func main() -> int
    unique arr: Array<int> = [1, 2, 3]
    other = arr
    print(arr.len())
    return 0
~
''', run=False)
        assert not result.compile_success, "Expected compilation to fail"
        assert "moved" in result.compile_output.lower(), \
            f"Expected 'moved' in error, got: {result.compile_output}"

    def test_move_destination_valid(self, expect_output):
        """Destination of move is valid."""
        expect_output('''
func main() -> int
    unique arr: Array<int> = [1, 2, 3]
    other = arr
    print(other.len())
    return 0
~
''', "3\n")

    def test_double_move_error(self, compile_coex):
        """Cannot move same binding twice."""
        result = compile_coex('''
func main() -> int
    unique arr: Array<int> = [1, 2, 3]
    a = arr
    b = arr
    return 0
~
''', run=False)
        assert not result.compile_success, "Expected compilation to fail"
        assert "moved" in result.compile_output.lower(), \
            f"Expected 'moved' in error, got: {result.compile_output}"

    def test_move_then_use_in_expression(self, compile_coex):
        """Using moved binding in expression is error."""
        result = compile_coex('''
func main() -> int
    unique arr: Array<int> = [1, 2, 3]
    other = arr
    x = arr.get(0) + 1
    return 0
~
''', run=False)
        assert not result.compile_success
        assert "moved" in result.compile_output.lower()


class TestCopySemantics:
    """Test copy semantics with := operator."""

    def test_copy_preserves_source(self, expect_output):
        """Source remains valid after := copy."""
        expect_output('''
func main() -> int
    unique arr: Array<int> = [1, 2, 3]
    copy := arr
    print(arr.len())
    print(copy.len())
    return 0
~
''', "3\n3\n")

    def test_unique_copy_creates_unique(self, expect_output):
        """unique target := source creates independent unique."""
        expect_output('''
func main() -> int
    unique arr: Array<int> = [1, 2, 3]
    unique other := arr
    other = other.append(4)
    print(arr.len())
    print(other.len())
    return 0
~
''', "3\n4\n")

    def test_copy_then_modify_both(self, expect_output):
        """After copy, both can be independently modified."""
        expect_output('''
func main() -> int
    unique a: Array<int> = [1]
    unique b := a
    a = a.append(2)
    b = b.append(3)
    print(a.len())
    print(b.len())
    return 0
~
''', "2\n2\n")


class TestBorrowedParameters:
    """Test borrow parameter semantics."""

    def test_borrow_allows_read(self, expect_output):
        """Borrowed parameter can be read."""
        expect_output('''
func sum(borrow arr: Array<int>) -> int
    total = 0
    for i in 0..arr.len()
        total = total + arr.get(i)
    ~
    return total
~

func main() -> int
    unique data: Array<int> = [1, 2, 3]
    result = sum(data)
    print(result)
    return 0
~
''', "6\n")

    def test_borrow_preserves_caller_ownership(self, expect_output):
        """Caller retains ownership after borrow."""
        expect_output('''
func inspect(borrow arr: Array<int>) -> int
    return arr.len()
~

func main() -> int
    unique data: Array<int> = [1, 2, 3]
    len1 = inspect(data)
    data = data.append(4)
    len2 = inspect(data)
    print(len1)
    print(len2)
    return 0
~
''', "3\n4\n")

    def test_borrow_cannot_mutate(self, compile_coex):
        """Cannot mutate borrowed binding."""
        result = compile_coex('''
func mutate(borrow arr: Array<int>) -> int
    arr = arr.append(1)
    return arr.len()
~

func main() -> int
    unique data: Array<int> = [1, 2, 3]
    mutate(data)
    return 0
~
''', run=False)
        assert not result.compile_success, "Expected compilation to fail"
        assert "borrow" in result.compile_output.lower(), \
            f"Expected 'borrow' in error, got: {result.compile_output}"

    def test_borrow_cannot_move(self, compile_coex):
        """Cannot move borrowed binding."""
        result = compile_coex('''
func steal(borrow arr: Array<int>) -> int
    other = arr
    return other.len()
~

func main() -> int
    unique data: Array<int> = [1, 2, 3]
    steal(data)
    return 0
~
''', run=False)
        assert not result.compile_success
        assert "borrow" in result.compile_output.lower(), \
            f"Expected 'borrow' in error, got: {result.compile_output}"

    def test_borrow_cannot_return(self, compile_coex):
        """Cannot return borrowed binding."""
        result = compile_coex('''
func steal(borrow arr: Array<int>) -> Array<int>
    return arr
~

func main() -> int
    unique data: Array<int> = [1, 2, 3]
    stolen = steal(data)
    return 0
~
''', run=False)
        assert not result.compile_success
        assert "borrow" in result.compile_output.lower(), \
            f"Expected 'borrow' in error, got: {result.compile_output}"

    def test_multiple_borrows_ok(self, expect_output):
        """Can borrow same value multiple times (not simultaneously)."""
        expect_output('''
func len_of(borrow arr: Array<int>) -> int
    return arr.len()
~

func main() -> int
    unique data: Array<int> = [1, 2, 3]
    a = len_of(data)
    b = len_of(data)
    c = len_of(data)
    print(a + b + c)
    return 0
~
''', "9\n")


class TestUniqueParameters:
    """Test unique parameter semantics."""

    def test_unique_param_receives_ownership(self, expect_output):
        """Unique parameter can mutate in-place."""
        expect_output('''
func process(unique data: Array<int>) -> int
    data = data.append(4)
    return data.len()
~

func main() -> int
    unique arr: Array<int> = [1, 2, 3]
    result = process(arr)
    print(result)
    return 0
~
''', "4\n")

    def test_unique_param_invalidates_caller(self, compile_coex):
        """Caller's binding invalid after passing to unique param."""
        result = compile_coex('''
func consume(unique data: Array<int>) -> int
    return data.len()
~

func main() -> int
    unique arr: Array<int> = [1, 2, 3]
    consume(arr)
    print(arr.len())
    return 0
~
''', run=False)
        assert not result.compile_success, "Expected compilation to fail"
        assert "moved" in result.compile_output.lower(), \
            f"Expected 'moved' in error, got: {result.compile_output}"

    def test_unique_param_can_be_rebound(self, expect_output):
        """Unique parameter can be rebound within function."""
        expect_output('''
func grow(unique arr: Array<int>, count: int) -> int
    for i in 0..count
        arr = arr.append(i)
    ~
    return arr.len()
~

func main() -> int
    unique data: Array<int> = []
    result = grow(data, 5)
    print(result)
    return 0
~
''', "5\n")


class TestUniqueReturnType:
    """Test unique return type semantics."""

    def test_unique_return_type(self, expect_output):
        """Function can return unique value."""
        expect_output('''
func make_buffer(size: int) -> unique Array<int>
    unique result: Array<int> = []
    for i in 0..size
        result = result.append(i)
    ~
    return result
~

func main() -> int
    unique buf = make_buffer(5)
    print(buf.len())
    return 0
~
''', "5\n")

    def test_unique_return_to_non_unique(self, expect_output):
        """Unique return can be assigned to non-unique binding."""
        expect_output('''
func make_array() -> unique Array<int>
    unique result: Array<int> = [1, 2, 3]
    return result
~

func main() -> int
    data = make_array()
    print(data.len())
    return 0
~
''', "3\n")


class TestControlFlow:
    """Test ownership through control flow."""

    def test_move_all_branches_valid(self, expect_output):
        """Move on all branches is valid."""
        expect_output('''
func consume(unique arr: Array<int>) -> int
    return arr.len()
~

func main() -> int
    unique arr: Array<int> = [1, 2, 3]
    result = 0
    if true
        result = consume(arr)
    else
        result = consume(arr)
    ~
    print(result)
    return 0
~
''', "3\n")

    def test_move_some_branches_error(self, compile_coex):
        """Move on only some branches is error."""
        result = compile_coex('''
func consume(unique arr: Array<int>) -> int
    return arr.len()
~

func main() -> int
    unique arr: Array<int> = [1, 2, 3]
    if true
        consume(arr)
    ~
    print(arr.len())
    return 0
~
''', run=False)
        assert not result.compile_success, "Expected compilation to fail"
        assert "moved" in result.compile_output.lower() or "branch" in result.compile_output.lower(), \
            f"Expected 'moved' or 'branch' in error, got: {result.compile_output}"

    def test_rebind_in_loop_valid(self, expect_output):
        """Rebinding unique in loop is valid."""
        expect_output('''
func main() -> int
    unique arr: Array<int> = []
    for i in 0..5
        arr = arr.append(i)
    ~
    print(arr.len())
    return 0
~
''', "5\n")

    def test_move_in_loop_error(self, compile_coex):
        """Moving unique to different binding in loop is error."""
        result = compile_coex('''
func main() -> int
    unique arr: Array<int> = [1, 2, 3]
    for i in 0..3
        other = arr
    ~
    return 0
~
''', run=False)
        assert not result.compile_success, "Expected compilation to fail"
        assert "loop" in result.compile_output.lower() or "moved" in result.compile_output.lower(), \
            f"Expected 'loop' or 'moved' in error, got: {result.compile_output}"

    def test_no_move_any_branch_valid(self, expect_output):
        """Not moving on any branch is valid."""
        expect_output('''
func main() -> int
    unique arr: Array<int> = [1, 2, 3]
    if true
        x = arr.len()
    else
        x = arr.get(0)
    ~
    print(arr.len())
    return 0
~
''', "3\n")

    def test_while_rebind_valid(self, expect_output):
        """Rebinding in while loop is valid."""
        expect_output('''
func main() -> int
    unique arr: Array<int> = []
    i = 0
    while i < 5
        arr = arr.append(i)
        i = i + 1
    ~
    print(arr.len())
    return 0
~
''', "5\n")


class TestTypeRestrictions:
    """Test type restrictions for unique."""

    def test_unique_on_int_error(self, compile_coex):
        """Unique only valid on Array and String, not int."""
        result = compile_coex('''
func main() -> int
    unique x: int = 5
    return x
~
''', run=False)
        assert not result.compile_success, "Expected compilation to fail"
        assert "unique" in result.compile_output.lower(), \
            f"Expected 'unique' in error, got: {result.compile_output}"

    def test_unique_on_float_error(self, compile_coex):
        """Unique only valid on Array and String, not float."""
        result = compile_coex('''
func main() -> int
    unique x: float = 3.14
    return 0
~
''', run=False)
        assert not result.compile_success
        assert "unique" in result.compile_output.lower()

    def test_unique_on_bool_error(self, compile_coex):
        """Unique only valid on Array and String, not bool."""
        result = compile_coex('''
func main() -> int
    unique x: bool = true
    return 0
~
''', run=False)
        assert not result.compile_success
        assert "unique" in result.compile_output.lower()


class TestInPlaceOptimization:
    """Test that unique bindings get in-place optimization."""

    def test_unique_append_inplace(self, expect_output):
        """Unique array append should be in-place (performance test)."""
        expect_output('''
func main() -> int
    unique arr: Array<int> = []
    for i in 0..10000
        arr = arr.append(i)
    ~
    print(arr.len())
    return 0
~
''', "10000\n")

    def test_unique_set_at_inplace(self, expect_output):
        """Unique array set_at should be in-place."""
        expect_output('''
func main() -> int
    unique arr: Array<int> = [0, 0, 0, 0, 0]
    for i in 0..5
        arr = arr.set_at(i, i * 10)
    ~
    print(arr.get(0))
    print(arr.get(4))
    return 0
~
''', "0\n40\n")

    def test_unique_string_operations(self, expect_output):
        """Unique string operations work."""
        expect_output('''
func main() -> int
    unique s: string = "hello"
    print(s.len())
    return 0
~
''', "5\n")


class TestComplexScenarios:
    """Test complex ownership scenarios."""

    def test_function_chain_with_unique(self, expect_output):
        """Unique value can be passed through function chain."""
        expect_output('''
func add_one(unique arr: Array<int>) -> unique Array<int>
    unique result := arr
    result = result.append(1)
    return result
~

func add_two(unique arr: Array<int>) -> unique Array<int>
    unique result := arr
    result = result.append(2)
    return result
~

func main() -> int
    unique data: Array<int> = []
    unique step1 = add_one(data)
    unique step2 = add_two(step1)
    print(step2.len())
    return 0
~
''', "2\n")

    def test_borrow_in_condition(self, expect_output):
        """Borrow can be used in condition check."""
        expect_output('''
func is_empty(borrow arr: Array<int>) -> bool
    return arr.len() == 0
~

func main() -> int
    unique data: Array<int> = []
    if is_empty(data)
        print(1)
    else
        print(0)
    ~
    data = data.append(42)
    if is_empty(data)
        print(1)
    else
        print(0)
    ~
    return 0
~
''', "1\n0\n")

    def test_nested_function_borrows(self, expect_output):
        """Multiple nested function calls with borrows."""
        expect_output('''
func get_first(borrow arr: Array<int>) -> int
    return arr.get(0)
~

func get_last(borrow arr: Array<int>) -> int
    return arr.get(arr.len() - 1)
~

func sum_ends(borrow arr: Array<int>) -> int
    return get_first(arr) + get_last(arr)
~

func main() -> int
    unique data: Array<int> = [10, 20, 30, 40]
    result = sum_ends(data)
    print(result)
    return 0
~
''', "50\n")
