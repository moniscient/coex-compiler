"""
Tests for List value semantics verification.

Phase 1 of JSON refactoring: Verify List implements value semantics correctly
via immutability. All List operations return new values; the original is unchanged.
"""

import pytest


class TestListValueSemantics:
    """Verify List maintains value semantics through immutability."""

    def test_list_assignment_creates_independent_copy(self, expect_output):
        """Basic assignment: a = b; b.set() doesn't affect a."""
        expect_output('''
func main() -> int
    a = [1, 2, 3]
    b = a
    b = b.set(0, 100)
    print(a.get(0))
    print(b.get(0))
    return 0
~
''', "1\n100\n")

    def test_list_nested_assignment_deep_independence(self, expect_output):
        """Nested lists: modifying inner list in one doesn't affect copies."""
        expect_output('''
func main() -> int
    inner = [1, 2, 3]
    a = [inner, inner]
    modified_inner = a.get(0).set(0, 100)
    a = a.set(0, modified_inner)
    # a[0] is now [100, 2, 3], but a[1] should still be [1, 2, 3]
    print(a.get(0).get(0))
    print(a.get(1).get(0))
    return 0
~
''', "100\n1\n")

    def test_list_three_level_nesting_independence(self, expect_output):
        """Three levels deep: modifications don't propagate unexpectedly."""
        expect_output('''
func main() -> int
    level3: List<int> = [42]
    level2: List<List<int>> = [level3]
    level1: List<List<List<int>>> = [level2]

    # Modify deepest level through level1
    inner2: List<List<int>> = level1.get(0)
    inner3: List<int> = inner2.get(0)
    new_level3: List<int> = inner3.set(0, 999)
    new_level2: List<List<int>> = inner2.set(0, new_level3)
    level1_modified: List<List<List<int>>> = level1.set(0, new_level2)

    # Original structures unchanged
    print(level3.get(0))
    inner2_check: List<List<int>> = level2
    print(inner2_check.get(0).get(0))

    # Modified structure has new value
    inner2_mod: List<List<int>> = level1_modified.get(0)
    inner3_mod: List<int> = inner2_mod.get(0)
    print(inner3_mod.get(0))
    return 0
~
''', "42\n42\n999\n")

    def test_list_containing_map_independence(self, expect_output):
        """List of Maps: modifying map doesn't affect original list."""
        expect_output('''
func main() -> int
    m1 = {1: 100, 2: 200}
    m2 = {3: 300, 4: 400}
    list_of_maps = [m1, m2]

    # Modify first map and put it back
    modified_m1 = list_of_maps.get(0).set(1, 999)
    list_modified = list_of_maps.set(0, modified_m1)

    # Original list unchanged
    print(list_of_maps.get(0).get(1))
    # Modified list has new value
    print(list_modified.get(0).get(1))
    return 0
~
''', "100\n999\n")

    def test_list_assigned_to_multiple_variables(self, expect_output):
        """Four variables sharing: modifying one doesn't affect others."""
        expect_output('''
func main() -> int
    original = [10, 20, 30]
    copy1 = original
    copy2 = original
    copy3 = original

    # Modify copy1
    copy1 = copy1.set(0, 100)

    # All others unchanged
    print(original.get(0))
    print(copy2.get(0))
    print(copy3.get(0))
    print(copy1.get(0))
    return 0
~
''', "10\n10\n10\n100\n")

    def test_list_no_shared_mutation_in_loop(self, expect_output):
        """Simulated concurrent access: iterations don't share state."""
        expect_output('''
func main() -> int
    base = [0, 0, 0]
    results: List<List<int>> = []

    for i in 0..3
        modified = base.set(i, i * 10)
        results = results.append(modified)
    ~

    # Each result should have exactly one modified element
    print(results.get(0).get(0))
    print(results.get(0).get(1))
    print(results.get(0).get(2))
    print(results.get(1).get(0))
    print(results.get(1).get(1))
    print(results.get(2).get(2))
    return 0
~
''', "0\n0\n0\n0\n10\n20\n")

    def test_list_passed_to_function_is_independent(self, expect_output):
        """Function modification doesn't affect caller's copy."""
        expect_output('''
func modify_list(lst: List<int>) -> List<int>
    return lst.set(0, 999)
~

func main() -> int
    original = [1, 2, 3]
    modified = modify_list(original)

    print(original.get(0))
    print(modified.get(0))
    return 0
~
''', "1\n999\n")

    def test_list_returned_from_function_is_independent(self, expect_output):
        """Multiple returns from function are independent."""
        expect_output('''
func make_list() -> List<int>
    return [1, 2, 3]
~

func main() -> int
    a = make_list()
    b = make_list()

    a = a.set(0, 100)

    print(a.get(0))
    print(b.get(0))
    return 0
~
''', "100\n1\n")


class TestListAppendValueSemantics:
    """Verify append operations maintain value semantics."""

    def test_append_returns_new_list(self, expect_output):
        """Append returns new list; original unchanged."""
        expect_output('''
func main() -> int
    original = [1, 2]
    extended = original.append(3)

    print(original.len())
    print(extended.len())
    return 0
~
''', "2\n3\n")

    def test_multiple_appends_create_independent_lists(self, expect_output):
        """Each append creates independent list."""
        expect_output('''
func main() -> int
    base = [1]
    with2 = base.append(2)
    with3 = base.append(3)

    print(base.len())
    print(with2.get(1))
    print(with3.get(1))
    return 0
~
''', "1\n2\n3\n")


class TestListSliceValueSemantics:
    """Verify slice operations maintain value semantics."""

    def test_slice_shares_buffer_but_safe(self, expect_output):
        """Slices share buffer but modifications create new values."""
        expect_output('''
func main() -> int
    original = [1, 2, 3, 4, 5]
    slice1 = original[1:4]

    # Slice has correct values
    print(slice1.get(0))
    print(slice1.get(1))
    print(slice1.get(2))
    print(slice1.len())
    return 0
~
''', "2\n3\n4\n3\n")
