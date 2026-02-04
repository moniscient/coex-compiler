"""
Tests for JSON value semantics verification.

Phase 3 of JSON refactoring: Verify JSON implements value semantics correctly.
JSON operations return new values; the original is unchanged.

Includes test for BUG-070 fix (json_set_index elem_size).
"""

class TestJsonValueSemantics:
    """Verify JSON maintains value semantics through immutability."""

    def test_json_assignment_from_list_is_independent(self, expect_output):
        """JSON created from list is independent from original list."""
        expect_output('''
func main() -> int
    original_list = [1, 2, 3]
    j: json := original_list

    # Modify original list
    original_list = original_list.set(0, 100)

    # JSON unchanged - get first element
    elem: json = j[0]
    val: int = elem as int
    print(val)
    # List changed
    print(original_list.get(0))
    return 0
~
''', "1\n100\n")

    def test_json_assignment_from_map_is_independent(self, expect_output):
        """JSON created from map is independent from original map."""
        expect_output('''
func main() -> int
    original_map: Map<string, int> = {"age": 30}
    j: json := original_map

    # Modify original map
    original_map = original_map.set("age", 40)

    # JSON unchanged - check value
    age_json: json = j.get("age")
    print(age_json as int)
    # Map changed
    print(original_map.get("age"))
    return 0
~
''', "30\n40\n")

    def test_json_to_json_assignment_is_independent(self, expect_output):
        """JSON assigned to another json variable is independent."""
        expect_output('''
func main() -> int
    j1: json = { name: "Alice", age: 30 }
    j2: json = j1

    # Modify j1
    j1 = j1.set("age", 40)

    # j2 unchanged
    j1_age: json = j1.get("age")
    j2_age: json = j2.get("age")
    print(j1_age as int)
    print(j2_age as int)
    return 0
~
''', "40\n30\n")

    def test_json_nested_independence(self, expect_output):
        """Nested JSON structures maintain independence."""
        expect_output('''
func main() -> int
    inner: json = { value: 42 }
    outer: json = { data: inner }

    # Modify inner through outer
    inner_get: json = outer.get("data")
    new_inner: json = inner_get.set("value", 999)
    outer_modified: json = outer.set("data", new_inner)

    # Original outer unchanged
    orig_data: json = outer.get("data")
    orig_value: json = orig_data.get("value")
    print(orig_value as int)
    # Modified outer has new value
    mod_data: json = outer_modified.get("data")
    mod_value: json = mod_data.get("value")
    print(mod_value as int)
    return 0
~
''', "42\n999\n")

    def test_json_multiple_assignments_all_independent(self, expect_output):
        """Multiple variables assigned from same JSON are all independent."""
        expect_output('''
func main() -> int
    original: json = { value: 10 }
    copy1: json = original
    copy2: json = original
    copy3: json = original

    # Modify copy1
    copy1 = copy1.set("value", 100)

    # All others unchanged
    v_orig: json = original.get("value")
    v_c2: json = copy2.get("value")
    v_c3: json = copy3.get("value")
    v_c1: json = copy1.get("value")
    print(v_orig as int)
    print(v_c2 as int)
    print(v_c3 as int)
    print(v_c1 as int)
    return 0
~
''', "10\n10\n10\n100\n")

    def test_json_safe_for_concurrent_simulation(self, expect_output):
        """Simulated concurrent access: each iteration gets independent copy."""
        expect_output('''
func main() -> int
    base: json = { value: 0 }
    results: List<json> = []

    for i in 0..3
        modified: json = base.set("value", i * 10)
        results = results.append(modified)
    ~

    # Each result has its own value
    r0: json = results[0]
    r1: json = results[1]
    r2: json = results[2]
    v0: json = r0.get("value")
    v1: json = r1.get("value")
    v2: json = r2.get("value")
    print(v0 as int)
    print(v1 as int)
    print(v2 as int)
    # Base unchanged
    bv: json = base.get("value")
    print(bv as int)
    return 0
~
''', "0\n10\n20\n0\n")

    def test_json_from_shared_source_is_independent(self, expect_output):
        """JSON values derived from shared source are independent."""
        expect_output('''
func main() -> int
    source: json = { a: 1, b: 2, c: 3 }

    # Create multiple derived values
    with_a_100: json = source.set("a", 100)
    with_b_200: json = source.set("b", 200)

    # Each derived value is independent
    sa: json = source.get("a")
    sb: json = source.get("b")
    a100_a: json = with_a_100.get("a")
    a100_b: json = with_a_100.get("b")
    b200_a: json = with_b_200.get("a")
    b200_b: json = with_b_200.get("b")
    print(sa as int)
    print(sb as int)
    print(a100_a as int)
    print(a100_b as int)
    print(b200_a as int)
    print(b200_b as int)
    return 0
~
''', "1\n2\n100\n2\n1\n200\n")


class TestJsonArraySetIndex:
    """Tests for JSON array set(index, value) - BUG-070 fix verification.

    NOTE: These tests are marked xfail because json.set() currently only
    supports string keys (object fields), not integer indices (array elements).
    This is a pre-existing limitation - BUG-070 fixed the underlying function
    but method dispatch still needs to be updated to call json_set_index for
    integer arguments.
    """

    def test_json_set_index_basic(self, expect_output):
        """Basic set(index, value) on JSON array works correctly."""
        expect_output('''
func main() -> int
    j: json := [1, 2, 3]
    j2: json = j.set(1, 42)
    e0: json = j2[0]
    e1: json = j2[1]
    e2: json = j2[2]
    print(e0 as int)
    print(e1 as int)
    print(e2 as int)
    return 0
~
''', "1\n42\n3\n")


    def test_json_set_index_preserves_original(self, expect_output):
        """set(index, value) preserves original array."""
        expect_output('''
func main() -> int
    original: json := [10, 20, 30]
    modified: json = original.set(0, 999)

    o0: json = original[0]
    o1: json = original[1]
    o2: json = original[2]
    m0: json = modified[0]
    print(o0 as int)
    print(o1 as int)
    print(o2 as int)
    print(m0 as int)
    return 0
~
''', "10\n20\n30\n999\n")


    def test_json_set_index_with_nested_json(self, expect_output):
        """set(index, value) with nested JSON value."""
        expect_output('''
func main() -> int
    inner: json = { value: 42 }
    arr: json := [1, 2, 3]
    arr2: json = arr.set(1, inner)

    e0: json = arr2[0]
    e1: json = arr2[1]
    e2: json = arr2[2]
    e1_val: json = e1.get("value")
    print(e0 as int)
    print(e1_val as int)
    print(e2 as int)
    return 0
~
''', "1\n42\n3\n")


    def test_json_set_index_multiple_operations(self, expect_output):
        """Multiple set operations create correct results."""
        expect_output('''
func main() -> int
    j: json := [0, 0, 0, 0, 0]
    j = j.set(0, 10)
    j = j.set(2, 30)
    j = j.set(4, 50)

    e0: json = j[0]
    e1: json = j[1]
    e2: json = j[2]
    e3: json = j[3]
    e4: json = j[4]
    print(e0 as int)
    print(e1 as int)
    print(e2 as int)
    print(e3 as int)
    print(e4 as int)
    return 0
~
''', "10\n0\n30\n0\n50\n")


    def test_json_set_index_stress(self, expect_output):
        """Stress test: many set operations on JSON array."""
        expect_output('''
func main() -> int
    j: json := [0, 0, 0, 0, 0, 0, 0, 0, 0, 0]

    for i in 0..10
        j = j.set(i, i * i)
    ~

    # Verify squares
    sum = 0
    for i in 0..10
        elem: json = j[i]
        val: int = elem as int
        sum = sum + val
    ~
    # 0 + 1 + 4 + 9 + 16 + 25 + 36 + 49 + 64 + 81 = 285
    print(sum)
    return 0
~
''', "285\n")


class TestJsonAppendValueSemantics:
    """Verify JSON append maintains value semantics."""

    def test_json_append_returns_new_array(self, expect_output):
        """append returns new array; original unchanged."""
        expect_output('''
func main() -> int
    original: json := [1, 2]
    extended: json := original.append(3)

    print(original.len())
    print(extended.len())
    return 0
~
''', "2\n3\n")

    def test_json_append_preserves_original_values(self, expect_output):
        """Original array values unchanged after append."""
        expect_output('''
func main() -> int
    original: json := [10, 20]
    extended: json := original.append(30)

    o0: json = original[0]
    o1: json = original[1]
    e0: json = extended[0]
    e1: json = extended[1]
    e2: json = extended[2]
    print(o0 as int)
    print(o1 as int)
    print(e0 as int)
    print(e1 as int)
    print(e2 as int)
    return 0
~
''', "10\n20\n10\n20\n30\n")

    def test_json_multiple_appends_independent(self, expect_output):
        """Multiple appends from same source create independent arrays."""
        expect_output('''
func main() -> int
    base: json := [1]
    with_a: json := base.append(100)
    with_b: json := base.append(200)

    a1: json = with_a[1]
    b1: json = with_b[1]
    print(base.len())
    print(a1 as int)
    print(b1 as int)
    return 0
~
''', "1\n100\n200\n")
