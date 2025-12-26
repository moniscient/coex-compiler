import pytest

class TestArrayCOW:
    """Test Copy-on-Write semantics for Array type."""

    def test_array_creation_from_list(self, expect_output):
        """Array can be created by type conversion from List via packed()."""
        expect_output('''
func main() -> int
    list: List<int> = [1, 2, 3]
    a: Array<int> = list.packed()
    print(a.get(0))
    print(a.get(1))
    print(a.get(2))
    print(a.len())
    return 0
~
''', "1\n2\n3\n3\n")

    def test_array_assignment_shares_data(self, expect_output):
        """Assignment should not copy - both variables share buffer."""
        expect_output('''
func main() -> int
    list: List<int> = [1, 2, 3]
    a: Array<int> = list.packed()
    b: Array<int> = a
    print(b.get(0))
    print(b.get(1))
    print(b.get(2))
    return 0
~
''', "1\n2\n3\n")

    def test_array_cow_on_set(self, expect_output):
        """Mutation via set() should copy, leaving original unchanged."""
        expect_output('''
func main() -> int
    list: List<int> = [1, 2, 3]
    a: Array<int> = list.packed()
    b: Array<int> = a
    b = b.set(1, 99)
    print(a.get(1))
    print(b.get(1))
    return 0
~
''', "2\n99\n")

    def test_array_cow_on_append(self, expect_output):
        """Mutation via append() should copy, leaving original unchanged."""
        expect_output('''
func main() -> int
    list: List<int> = [1, 2]
    a: Array<int> = list.packed()
    b: Array<int> = a
    b = b.append(3)
    print(a.len())
    print(b.len())
    return 0
~
''', "2\n3\n")

    def test_array_sole_owner_no_copy(self, expect_output):
        """When sole owner (refcount=1), mutation should be in-place."""
        expect_output('''
func main() -> int
    list: List<int> = [1, 2, 3]
    a: Array<int> = list.packed()
    a = a.set(0, 10)
    a = a.set(1, 20)
    a = a.set(2, 30)
    print(a.get(0))
    print(a.get(1))
    print(a.get(2))
    return 0
~
''', "10\n20\n30\n")

    def test_array_multiple_assignments(self, expect_output):
        """Multiple assignments should all share until mutation."""
        expect_output('''
func main() -> int
    list: List<int> = [1, 2, 3]
    a: Array<int> = list.packed()
    b: Array<int> = a
    c: Array<int> = a
    d: Array<int> = b
    c = c.set(0, 99)
    print(a.get(0))
    print(b.get(0))
    print(c.get(0))
    print(d.get(0))
    return 0
~
''', "1\n1\n99\n1\n")

    def test_array_cow_independence_after_mutation(self, expect_output):
        """After COW copy, the copies are fully independent."""
        expect_output('''
func main() -> int
    list: List<int> = [1, 2]
    a: Array<int> = list.packed()
    b: Array<int> = a
    b = b.set(0, 10)
    a = a.set(0, 20)
    print(a.get(0))
    print(b.get(0))
    return 0
~
''', "20\n10\n")

    def test_array_cow_with_functions(self, expect_output):
        """COW should work correctly when passing to functions."""
        expect_output('''
func modify(arr: Array<int>) -> int
    local: Array<int> = arr.set(0, 99)
    return local.get(0)
~

func main() -> int
    list: List<int> = [1, 2, 3]
    a: Array<int> = list.packed()
    result: int = modify(a)
    print(a.get(0))
    print(result)
    return 0
~
''', "1\n99\n")

    def test_array_iteration_no_cow(self, expect_output):
        """Iteration (read-only) should not trigger copy."""
        expect_output('''
func main() -> int
    list: List<int> = [1, 2, 3]
    a: Array<int> = list.packed()
    b: Array<int> = a
    sum: int = 0
    for x in b
        sum = sum + x
    ~
    print(sum)
    print(a.get(0))
    return 0
~
''', "6\n1\n")

    def test_array_len_no_cow(self, expect_output):
        """len() is read-only, should not trigger copy."""
        expect_output('''
func main() -> int
    list: List<int> = [1, 2, 3, 4, 5]
    a: Array<int> = list.packed()
    b: Array<int> = a
    print(b.len())
    b = b.set(0, 99)
    print(a.len())
    print(b.len())
    return 0
~
''', "5\n5\n5\n")

    def test_array_of_strings(self, expect_output):
        """COW should work with Array<string>."""
        expect_output('''
func main() -> int
    list: List<string> = ["hello", "world"]
    a: Array<string> = list.packed()
    b: Array<string> = a
    b = b.set(0, "goodbye")
    print(a.get(0))
    print(b.get(0))
    return 0
~
''', "hello\ngoodbye\n")
