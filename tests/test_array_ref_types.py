"""
Tests for Array handling of reference types (strings, Lists, Maps, etc.)
BUG-077: Array<string> and other reference type Arrays need handle storage updates
"""

import pytest


class TestArrayStringType:
    """Tests for Array<string>"""

    def test_array_string_from_list_packed(self, expect_output):
        """Basic test: convert List<string> to Array and access elements"""
        expect_output('''
func main() -> int
    list: List<string> = ["hello", "world"]
    a: Array<string> = list.packed()
    print(a.get(0))
    print(a.get(1))
    return 0
~
''', "hello\nworld\n")

    def test_array_string_set(self, expect_output):
        """Test Array.set with string elements"""
        expect_output('''
func main() -> int
    list: List<string> = ["hello", "world"]
    a: Array<string> = list.packed()
    b: Array<string> = a.set(0, "goodbye")
    print(a.get(0))
    print(b.get(0))
    return 0
~
''', "hello\ngoodbye\n")

    def test_array_string_iteration(self, expect_output):
        """Test iterating over Array<string>"""
        expect_output('''
func main() -> int
    list: List<string> = ["a", "b", "c"]
    arr: Array<string> = list.packed()
    for s in arr
        print(s)
    ~
    return 0
~
''', "a\nb\nc\n")

    def test_array_string_gc_survives(self, expect_output):
        """Test that Array<string> elements survive GC"""
        expect_output('''
func main() -> int
    list: List<string> = ["hello", "world", "test"]
    arr: Array<string> = list.packed()
    gc()
    print(arr.get(0))
    print(arr.get(1))
    print(arr.get(2))
    return 0
~
''', "hello\nworld\ntest\n")

    def test_array_string_set_gc_survives(self, expect_output):
        """Test that Array.set result survives GC"""
        expect_output('''
func main() -> int
    list: List<string> = ["one", "two"]
    a: Array<string> = list.packed()
    b: Array<string> = a.set(0, "first")
    gc()
    print(a.get(0))
    print(b.get(0))
    return 0
~
''', "one\nfirst\n")


class TestArrayListType:
    """Tests for Array<List<T>>"""

    @pytest.mark.xfail(reason="Parser error with nested generic types List<List<T>>")
    def test_array_of_lists_basic(self, expect_output):
        """Basic test: Array containing Lists"""
        expect_output('''
func main() -> int
    inner1: List<int> = [1, 2]
    inner2: List<int> = [3, 4]
    outer: List<List<int>> = [inner1, inner2]
    arr: Array<List<int>> = outer.packed()
    first: List<int> = arr.get(0)
    print(first.get(0))
    print(first.get(1))
    return 0
~
''', "1\n2\n")

    def test_array_of_lists_set(self, expect_output):
        """Test Array.set with List elements"""
        expect_output('''
func main() -> int
    inner1: List<int> = [1, 2]
    inner2: List<int> = [3, 4]
    outer: List<List<int>> = [inner1, inner2]
    arr: Array<List<int>> = outer.packed()

    new_inner: List<int> = [10, 20]
    arr2: Array<List<int>> = arr.set(0, new_inner)

    old_first: List<int> = arr.get(0)
    new_first: List<int> = arr2.get(0)

    print(old_first.get(0))
    print(new_first.get(0))
    return 0
~
''', "1\n10\n")


class TestArrayMapType:
    """Tests for Array<Map<K,V>>"""

    @pytest.mark.xfail(reason="Parser error with nested generic types List<Map<K,V>>")
    def test_array_of_maps_basic(self, expect_output):
        """Basic test: Array containing Maps"""
        expect_output('''
func main() -> int
    m1: Map<int, int> = {1: 10, 2: 20}
    m2: Map<int, int> = {3: 30, 4: 40}
    outer: List<Map<int, int>> = [m1, m2]
    arr: Array<Map<int, int>> = outer.packed()
    first: Map<int, int> = arr.get(0)
    print(first.get(1))
    print(first.get(2))
    return 0
~
''', "10\n20\n")


class TestArrayCOWSemantics:
    """Tests for Copy-On-Write semantics with reference type Arrays"""

    def test_array_string_cow_independence(self, expect_output):
        """Test that Array copies are independent (COW semantics)"""
        expect_output('''
func main() -> int
    list: List<string> = ["original"]
    a: Array<string> = list.packed()
    b: Array<string> = a.set(0, "modified")

    # Original should be unchanged
    print(a.get(0))
    # Modified copy should have new value
    print(b.get(0))
    return 0
~
''', "original\nmodified\n")

    def test_array_string_multiple_modifications(self, expect_output):
        """Test multiple modifications create independent copies"""
        expect_output('''
func main() -> int
    list: List<string> = ["a", "b", "c"]
    arr: Array<string> = list.packed()

    mod1: Array<string> = arr.set(0, "X")
    mod2: Array<string> = arr.set(1, "Y")
    mod3: Array<string> = mod1.set(2, "Z")

    # Original unchanged
    print(arr.get(0))
    print(arr.get(1))
    print(arr.get(2))

    # First mod
    print(mod1.get(0))
    print(mod1.get(1))
    print(mod1.get(2))

    # Second mod (from original)
    print(mod2.get(0))
    print(mod2.get(1))
    print(mod2.get(2))

    # Third mod (from mod1)
    print(mod3.get(0))
    print(mod3.get(1))
    print(mod3.get(2))

    return 0
~
''', "a\nb\nc\nX\nb\nc\na\nY\nc\nX\nb\nZ\n")
