import pytest

class TestCOWIntegration:
    """Test COW across Array and String together."""

    def test_array_of_ints_cow(self, expect_output):
        """Array<int> with COW."""
        expect_output('''
func main() -> int
    arr = [1, 2, 3].toArray()
    arr2 = arr
    arr2 = arr2.set(0, 99)
    print(arr.get(0))
    print(arr2.get(0))
    return 0
~
''', "1\n99\n")

    def test_array_string_cow(self, expect_output):
        """Array and String together with COW."""
        expect_output('''
func main() -> int
    arr = [1, 2, 3].toArray()
    s = "hello"
    arr2 = arr
    s2 = s
    arr2 = arr2.set(0, 99)
    s2 = s2 + " world"
    print(s)
    print(s2)
    print(arr.get(0))
    print(arr2.get(0))
    return 0
~
''', "hello\nhello world\n1\n99\n")

    def test_string_cow_concat(self, expect_output):
        """String COW with concatenation."""
        expect_output('''
func main() -> int
    a = "hello"
    b = a
    c = b + " world"
    print(a)
    print(b)
    print(c)
    return 0
~
''', "hello\nhello\nhello world\n")


class TestMoveOperatorIntegration:
    """Test := with all collection types."""

    def test_move_array(self, expect_output):
        """:= with Array."""
        expect_output('''
func main() -> int
    a = [1, 2, 3].toArray()
    b := a
    b = b.set(0, 99)
    print(b.get(0))
    return 0
~
''', "99\n")

    def test_move_string(self, expect_output):
        """:= with String."""
        expect_output('''
func main() -> int
    a = "hello"
    b := a
    b = b + " world"
    print(b)
    return 0
~
''', "hello world\n")

    def test_move_list(self, expect_output):
        """:= with List."""
        expect_output('''
func main() -> int
    a = [1, 2, 3]
    b := a
    b = b.append(4)
    print(b.len())
    return 0
~
''', "4\n")

    def test_move_map(self, expect_output):
        """:= with Map."""
        expect_output('''
func main() -> int
    a = {1: 10, 2: 20}
    b := a
    b = b.set(3, 30)
    print(b.len())
    return 0
~
''', "3\n")

    def test_move_set(self, expect_output):
        """:= with Set."""
        expect_output('''
func main() -> int
    a = {1, 2, 3}
    b := a
    b = b.add(4)
    print(b.len())
    return 0
~
''', "4\n")


class TestPersistentStructuresIntegration:
    """Test persistent structures working together."""

    def test_list_of_maps(self, expect_output):
        """List containing Maps."""
        expect_output('''
func main() -> int
    m1 = {1: 10}
    m2 = {2: 20}
    list = [m1, m2]
    result = list.get(0)
    print(result.get(1))
    return 0
~
''', "10\n")

    def test_map_of_lists(self, expect_output):
        """Map with List values."""
        expect_output('''
func main() -> int
    nums = [1, 2, 3]
    letters = [4, 5]
    m = {1: nums, 2: letters}
    retrieved = m.get(1)
    print(retrieved.len())
    print(retrieved.get(0))
    return 0
~
''', "3\n1\n")

    def test_set_of_strings(self, expect_output):
        """Set of strings."""
        expect_output('''
func main() -> int
    s = {"hello", "world", "hello"}
    print(s.len())
    print(s.has("hello"))
    return 0
~
''', "2\ntrue\n")

    def test_list_in_list(self, expect_output):
        """Nested lists."""
        expect_output('''
func main() -> int
    inner = [1, 2, 3]
    outer = [inner, inner]
    result = outer.get(0).get(1)
    print(result)
    return 0
~
''', "2\n")


class TestConversionsIntegration:
    """Test type conversions in complex scenarios."""

    def test_process_pipeline(self, expect_output):
        """Typical I/O processing pattern."""
        expect_output('''
func main() -> int
    input = [1, 2, 3, 4, 5].toArray()
    working = input.toList()
    working = working.append(6)
    working = working.append(7)
    output = working.toArray()
    print(output.len())
    print(output.get(6))
    return 0
~
''', "7\n7\n")

    def test_set_dedup_then_array(self, expect_output):
        """Deduplicate via Set, then to Array for processing."""
        expect_output('''
func main() -> int
    raw = [3, 1, 2, 1, 3, 2].toArray()
    unique = raw.toSet()
    result = unique.toArray()
    print(result.len())
    return 0
~
''', "3\n")

    def test_list_to_array_to_set(self, expect_output):
        """List -> Array -> Set chain."""
        expect_output('''
func main() -> int
    list = [1, 2, 2, 3, 3, 3]
    arr = list.toArray()
    s = arr.toSet()
    print(s.len())
    return 0
~
''', "3\n")


class TestEdgeCases:
    """Test edge cases and boundary conditions."""

    def test_list_set_iteration(self, expect_output):
        """List set and iteration."""
        expect_output('''
func main() -> int
    list = [1, 2, 3]
    list = list.set(1, 99)
    for x in list
        print(x)
    ~
    return 0
~
''', "1\n99\n3\n")

    def test_single_element_collections(self, expect_output):
        """Single element collections."""
        expect_output('''
func main() -> int
    list = [42]
    map = {1: 10}
    set = {99}
    arr = [7].toArray()
    print(list.get(0))
    print(map.get(1))
    print(set.has(99))
    print(arr.get(0))
    return 0
~
''', "42\n10\ntrue\n7\n")

    def test_many_assignments(self, expect_output):
        """Many assignments (stress test refcounting)."""
        expect_output('''
func main() -> int
    a = [1, 2, 3]
    b = a
    c = b
    d = c
    e = d
    f = e
    g = f
    h = g
    print(h.len())
    return 0
~
''', "3\n")

    def test_many_mutations(self, expect_output):
        """Many mutations (stress test structural sharing)."""
        expect_output('''
func main() -> int
    m = {0: 0}
    for i in 1..50
        m = m.set(i, i * 2)
    ~
    for i in 0..25
        m = m.remove(i * 2)
    ~
    print(m.len())
    return 0
~
''', "25\n")

    def test_deep_list_chain(self, expect_output):
        """Many sequential appends."""
        expect_output('''
func main() -> int
    list = [0]
    for i in 1..100
        list = list.append(i)
    ~
    print(list.len())
    print(list.get(50))
    return 0
~
''', "100\n50\n")


class TestConcurrencyReadiness:
    """Test patterns that will be used with concurrency."""

    def test_pass_to_function_cow(self, expect_output):
        """Passing collections to functions uses COW."""
        expect_output('''
func process(data: List<int>) -> int
    data = data.set(0, 999)
    return data.get(0)
~

func main() -> int
    list = [1, 2, 3]
    result = process(list)
    print(list.get(0))
    print(result)
    return 0
~
''', "1\n999\n")

    def test_return_collection(self, expect_output):
        """Returning collections from functions."""
        expect_output('''
func make_list() -> List<int>
    result = [1, 2, 3]
    result = result.append(4)
    return result
~

func main() -> int
    list = make_list()
    print(list.len())
    print(list.get(3))
    return 0
~
''', "4\n4\n")

    def test_function_chain(self, expect_output):
        """Chain of function calls with collections."""
        expect_output('''
func add_one(list: List<int>) -> List<int>
    return list.append(1)
~

func add_two(list: List<int>) -> List<int>
    return list.append(2)
~

func main() -> int
    list = [0]
    list = add_one(list)
    list = add_two(list)
    print(list.len())
    for x in list
        print(x)
    ~
    return 0
~
''', "3\n0\n1\n2\n")


class TestMemorySafety:
    """Tests designed to catch memory issues."""

    def test_scope_exit_cleanup(self, expect_output):
        """Collections cleaned up on scope exit."""
        expect_output('''
func inner() -> int
    local = [1, 2, 3, 4, 5]
    local = local.append(6)
    return local.len()
~

func main() -> int
    result = 0
    for i in 0..100
        result = inner()
    ~
    print(result)
    return 0
~
''', "6\n")

    def test_overwrite_variable(self, expect_output):
        """Overwriting variable cleans up old value."""
        expect_output('''
func main() -> int
    x = [1, 2, 3]
    x = [4, 5, 6]
    x = [7, 8, 9]
    print(x.get(0))
    return 0
~
''', "7\n")

    def test_conditional_assignment(self, expect_output):
        """Conditional paths with different collections."""
        expect_output('''
func main() -> int
    x = [0]
    for i in 1..6
        if i % 2 == 0
            x = x.append(i)
        ~
    ~
    print(x.len())
    return 0
~
''', "3\n")

    def test_map_in_loop(self, expect_output):
        """Map operations in loop (memory stress)."""
        expect_output('''
func main() -> int
    m = {0: 0}
    for i in 1..20
        m = m.set(i, i * i)
    ~
    print(m.len())
    print(m.get(10))
    return 0
~
''', "20\n100\n")

    def test_set_in_loop(self, expect_output):
        """Set operations in loop (memory stress)."""
        expect_output('''
func main() -> int
    s = {0}
    for i in 1..20
        s = s.add(i)
    ~
    print(s.len())
    print(s.has(15))
    return 0
~
''', "20\ntrue\n")


class TestValueSemantics:
    """Verify value semantics across all operations."""

    def test_list_value_semantics(self, expect_output):
        """List modifications don't affect copies."""
        expect_output('''
func main() -> int
    a = [1, 2, 3]
    b = a
    a = a.append(4)
    print(a.len())
    print(b.len())
    return 0
~
''', "4\n3\n")

    def test_map_value_semantics(self, expect_output):
        """Map modifications don't affect copies."""
        expect_output('''
func main() -> int
    a = {1: 10}
    b = a
    a = a.set(2, 20)
    print(a.len())
    print(b.len())
    print(b.has(2))
    return 0
~
''', "2\n1\nfalse\n")

    def test_set_value_semantics(self, expect_output):
        """Set modifications don't affect copies."""
        expect_output('''
func main() -> int
    a = {1, 2}
    b = a
    a = a.add(3)
    print(a.len())
    print(b.len())
    print(b.has(3))
    return 0
~
''', "3\n2\nfalse\n")

    def test_array_value_semantics(self, expect_output):
        """Array modifications don't affect copies."""
        expect_output('''
func main() -> int
    a = [1, 2, 3].toArray()
    b = a
    a = a.set(0, 99)
    print(a.get(0))
    print(b.get(0))
    return 0
~
''', "99\n1\n")
