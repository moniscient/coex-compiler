"""
Tests for Map value semantics verification.

Phase 2 of JSON refactoring: Verify Map implements value semantics correctly
via immutability. All Map operations return new values; the original is unchanged.
"""

import pytest


class TestMapValueSemantics:
    """Verify Map maintains value semantics through immutability."""

    def test_map_assignment_creates_independent_copy(self, expect_output):
        """Basic assignment: a = b; b.set() doesn't affect a."""
        expect_output('''
func main() -> int
    a = {1: 10, 2: 20, 3: 30}
    b = a
    b = b.set(1, 100)
    print(a.get(1))
    print(b.get(1))
    return 0
~
''', "10\n100\n")

    def test_map_nested_assignment_deep_independence(self, expect_output):
        """Nested maps: modifying inner map doesn't affect copies."""
        expect_output('''
func main() -> int
    inner = {"value": 42}
    a = {"first": inner, "second": inner}

    modified_inner = a.get("first").set("value", 999)
    a_modified = a.set("first", modified_inner)

    # Original a is unchanged
    print(a.get("first").get("value"))
    print(a.get("second").get("value"))

    # Modified version has new value only in "first"
    print(a_modified.get("first").get("value"))
    print(a_modified.get("second").get("value"))
    return 0
~
''', "42\n42\n999\n42\n")

    def test_map_three_level_nesting_independence(self, expect_output):
        """Three levels deep: modifications don't propagate unexpectedly."""
        expect_output('''
func main() -> int
    level3: Map<string, int> = {"deep": 42}
    level2: Map<string, Map<string, int>> = {"mid": level3}
    level1: Map<string, Map<string, Map<string, int>>> = {"top": level2}

    # Modify deepest level through level1
    l2: Map<string, Map<string, int>> = level1.get("top")
    l3: Map<string, int> = l2.get("mid")
    new_level3: Map<string, int> = l3.set("deep", 999)
    new_level2: Map<string, Map<string, int>> = l2.set("mid", new_level3)
    level1_modified: Map<string, Map<string, Map<string, int>>> = level1.set("top", new_level2)

    # Original structures unchanged
    print(level3.get("deep"))
    l2_check: Map<string, int> = level2.get("mid")
    print(l2_check.get("deep"))

    # Modified structure has new value
    l2_mod: Map<string, Map<string, int>> = level1_modified.get("top")
    l3_mod: Map<string, int> = l2_mod.get("mid")
    print(l3_mod.get("deep"))
    return 0
~
''', "42\n42\n999\n")

    def test_map_containing_list_independence(self, expect_output):
        """Map containing lists: modifying list doesn't affect original map."""
        expect_output('''
func main() -> int
    m = {"items": [1, 2, 3], "count": 3}

    # Modify the list and put it back
    modified_list = m.get("items").set(0, 100)
    m_modified = m.set("items", modified_list)

    # Original map unchanged
    print(m.get("items").get(0))
    # Modified map has new value
    print(m_modified.get("items").get(0))
    return 0
~
''', "1\n100\n")

    def test_map_assigned_to_multiple_variables(self, expect_output):
        """Four variables sharing: modifying one doesn't affect others."""
        expect_output('''
func main() -> int
    original = {"a": 1, "b": 2}
    copy1 = original
    copy2 = original
    copy3 = original

    # Modify copy1
    copy1 = copy1.set("a", 100)

    # All others unchanged
    print(original.get("a"))
    print(copy2.get("a"))
    print(copy3.get("a"))
    print(copy1.get("a"))
    return 0
~
''', "1\n1\n1\n100\n")

    def test_mixed_list_map_deep_independence(self, expect_output):
        """Complex nested structure: List of Maps with nested Lists."""
        expect_output('''
func main() -> int
    inner_list: List<int> = [10, 20, 30]
    map1: Map<string, List<int>> = {"data": inner_list}
    map2: Map<string, List<int>> = {"data": inner_list}
    container: List<Map<string, List<int>>> = [map1, map2]

    # Modify inner_list through container
    m0: Map<string, List<int>> = container.get(0)
    data0: List<int> = m0.get("data")
    modified_data: List<int> = data0.set(0, 999)
    modified_map: Map<string, List<int>> = m0.set("data", modified_data)
    container_modified: List<Map<string, List<int>>> = container.set(0, modified_map)

    # Original inner_list unchanged
    print(inner_list.get(0))
    # Original container unchanged
    m0_check: Map<string, List<int>> = container.get(0)
    d0: List<int> = m0_check.get("data")
    print(d0.get(0))
    # Modified container has change
    m0_mod: Map<string, List<int>> = container_modified.get(0)
    d0_mod: List<int> = m0_mod.get("data")
    print(d0_mod.get(0))
    return 0
~
''', "10\n10\n999\n")

    def test_shared_subtree_becomes_independent_on_mutation(self, expect_output):
        """When same subtree is in multiple places, mutation creates independent copy."""
        expect_output('''
func main() -> int
    shared = {"value": 42}
    parent = {"left": shared, "right": shared}

    # Verify both point to same logical value
    print(parent.get("left").get("value"))
    print(parent.get("right").get("value"))

    # Modify left branch
    new_left = parent.get("left").set("value", 100)
    parent_modified = parent.set("left", new_left)

    # Right branch unchanged
    print(parent_modified.get("left").get("value"))
    print(parent_modified.get("right").get("value"))
    return 0
~
''', "42\n42\n100\n42\n")


class TestMapMutationOperations:
    """Verify map mutation operations return new maps."""

    def test_map_set_returns_new_map(self, expect_output):
        """Set returns new map; original unchanged."""
        expect_output('''
func main() -> int
    original = {"a": 1}
    extended = original.set("b", 2)

    print(original.len())
    print(extended.len())
    print(original.has("b"))
    print(extended.has("b"))
    return 0
~
''', "1\n2\nfalse\ntrue\n")

    def test_map_remove_returns_new_map(self, expect_output):
        """Remove returns new map; original unchanged.

        NOTE: Uses int keys because map.remove() with string keys is
        not fully implemented (BUG-071).
        """
        expect_output('''
func main() -> int
    original: Map<int, int> = {1: 10, 2: 20}
    smaller: Map<int, int> = original.remove(2)

    print(original.len())
    print(smaller.len())
    print(original.has(2))
    print(smaller.has(2))
    return 0
~
''', "2\n1\ntrue\nfalse\n")

    def test_multiple_sets_create_independent_maps(self, expect_output):
        """Each set creates independent map."""
        expect_output('''
func main() -> int
    base = {"x": 0}
    with_a = base.set("a", 1)
    with_b = base.set("b", 2)

    print(base.len())
    print(with_a.has("a"))
    print(with_a.has("b"))
    print(with_b.has("a"))
    print(with_b.has("b"))
    return 0
~
''', "1\ntrue\nfalse\nfalse\ntrue\n")
