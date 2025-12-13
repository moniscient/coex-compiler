"""
Tests for advanced Coex features: Generics, Traits, Matrix/CA, Collections, and Lambdas.

These tests verify features that were implemented but not previously tested.
"""

import pytest


class TestGenerics:
    """Tests for generic types and functions."""

    def test_generic_type_simple(self, expect_output):
        """Generic type with single type parameter."""
        expect_output('''
type Box<T>:
    value: T
~

func main() -> int
    var b: Box<int> = Box<int>(42)
    print(b.value)
    return 0
~
''', "42\n")

    def test_generic_type_two_params(self, expect_output):
        """Generic type with two type parameters."""
        expect_output('''
type Pair<A, B>:
    first: A
    second: B
~

func main() -> int
    var p: Pair<int, int> = Pair<int, int>(10, 20)
    print(p.first + p.second)
    return 0
~
''', "30\n")

    def test_generic_function(self, expect_output):
        """Generic function with type parameter."""
        expect_output('''
func identity<T>(x: T) -> T
    return x
~

func main() -> int
    var result: int = identity<int>(42)
    print(result)
    return 0
~
''', "42\n")

    def test_generic_type_inference(self, expect_output):
        """Generic type with inferred type arguments."""
        expect_output('''
type Box<T>:
    value: T
~

func main() -> int
    var b: Box<int> = Box(99)
    print(b.value)
    return 0
~
''', "99\n")

    def test_generic_type_with_method(self, expect_output):
        """Generic type with method."""
        expect_output('''
type Box<T>:
    value: T

    func get() -> T
        return self.value
    ~
~

func main() -> int
    var b: Box<int> = Box<int>(123)
    print(b.get())
    return 0
~
''', "123\n")

    def test_generic_multiple_instantiations(self, expect_output):
        """Same generic type instantiated with different types."""
        expect_output('''
type Box<T>:
    value: T
~

func main() -> int
    var b1: Box<int> = Box<int>(10)
    var b2: Box<int> = Box<int>(20)
    print(b1.value + b2.value)
    return 0
~
''', "30\n")


class TestTraits:
    """Tests for trait declarations and structural typing."""

    def test_trait_declaration(self, expect_output):
        """Type implements trait methods."""
        expect_output('''
trait Printable:
    func describe() -> int
~

type Counter:
    value: int

    func describe() -> int
        return self.value
    ~
~

func main() -> int
    var c: Counter = Counter(42)
    print(c.describe())
    return 0
~
''', "42\n")

    def test_trait_bound_on_generic(self, expect_output):
        """Generic with trait bound."""
        expect_output('''
trait Numeric:
    func get_value() -> int
~

type Number:
    n: int

    func get_value() -> int
        return self.n
    ~
~

func double<T: Numeric>(x: T) -> int
    return x.get_value() * 2
~

func main() -> int
    var num: Number = Number(21)
    print(double<Number>(num))
    return 0
~
''', "42\n")


class TestMatrix:
    """Tests for cellular automata (matrix) declarations."""

    def test_matrix_creation(self, expect_output):
        """Create a matrix and access dimensions."""
        expect_output('''
matrix Grid[10, 10]:
    type: int
    init: 0
~

func main() -> int
    var g: Grid = Grid.new()
    print(g.width())
    return 0
~
''', "10\n")

    def test_matrix_get_set(self, expect_output):
        """Set and get matrix cell values."""
        expect_output('''
matrix Grid[5, 5]:
    type: int
    init: 0
~

func main() -> int
    var g: Grid = Grid.new()
    g.set(2, 3, 42)
    print(g.get(2, 3))
    return 0
~
''', "42\n")

    def test_matrix_initial_value(self, expect_output):
        """Matrix cells initialized to init value."""
        expect_output('''
matrix Grid[3, 3]:
    type: int
    init: 7
~

func main() -> int
    var g: Grid = Grid.new()
    print(g.get(1, 1))
    return 0
~
''', "7\n")

    def test_matrix_formula_simple(self, expect_output):
        """Matrix formula that sets all cells to constant."""
        expect_output('''
matrix Counter[2, 2]:
    type: int
    init: 0

    formula tick()
        return 1
    ~
~

func main() -> int
    var c: Counter = Counter.new()
    c.tick()
    print(c.get(0, 0) + c.get(1, 1))
    return 0
~
''', "2\n")

    def test_matrix_cell_access(self, expect_output):
        """Matrix formula using cell keyword for current value."""
        expect_output('''
matrix Grid[3, 3]:
    type: int
    init: 5

    formula double()
        return cell * 2
    ~
~

func main() -> int
    var g: Grid = Grid.new()
    g.double()
    print(g.get(1, 1))
    return 0
~
''', "10\n")


class TestCollections:
    """Tests for list literals and operations."""

    def test_list_literal_empty(self, expect_output):
        """Empty list creation."""
        expect_output('''
func main() -> int
    var lst: List<int> = []
    print(lst.len())
    return 0
~
''', "0\n")

    def test_list_literal_with_elements(self, expect_output):
        """List literal with elements."""
        expect_output('''
func main() -> int
    var lst: List<int> = [1, 2, 3]
    print(lst.len())
    return 0
~
''', "3\n")

    def test_list_get(self, expect_output):
        """Access list elements by index."""
        expect_output('''
func main() -> int
    var lst: List<int> = [10, 20, 30]
    print(lst.get(1))
    return 0
~
''', "20\n")

    def test_list_append(self, expect_output):
        """Append to list (value semantics - returns new list)."""
        expect_output('''
func main() -> int
    var lst: List<int> = [1, 2]
    lst = lst.append(3)
    print(lst.len())
    return 0
~
''', "3\n")

    def test_list_iteration(self, expect_output):
        """Iterate over list with for loop."""
        expect_output('''
func main() -> int
    var lst: List<int> = [1, 2, 3, 4]
    var sum: int = 0
    for x in lst
        sum += x
    ~
    print(sum)
    return 0
~
''', "10\n")


class TestListComprehensions:
    """Tests for list comprehensions."""

    def test_simple_comprehension(self, expect_output):
        """Basic list comprehension."""
        expect_output('''
func main() -> int
    var lst: List<int> = [x * 2 for x in 0..3]
    print(lst.len())
    return 0
~
''', "3\n")

    def test_comprehension_with_filter(self, expect_output):
        """List comprehension with filter condition."""
        expect_output('''
func main() -> int
    var evens: List<int> = [x for x in 0..10 if x % 2 == 0]
    print(evens.len())
    return 0
~
''', "5\n")


class TestMaps:
    """Tests for map literals and operations."""

    def test_empty_map(self, expect_output):
        """Empty map creation."""
        expect_output('''
func main() -> int
    var m: Map<int, int> = {}
    print(m.len())
    return 0
~
''', "0\n")

    def test_map_literal(self, expect_output):
        """Map literal with entries."""
        expect_output('''
func main() -> int
    var m: Map<int, int> = {1: 10, 2: 20, 3: 30}
    print(m.len())
    return 0
~
''', "3\n")

    def test_map_get(self, expect_output):
        """Get value from map."""
        expect_output('''
func main() -> int
    var m: Map<int, int> = {1: 100, 2: 200}
    print(m.get(2))
    return 0
~
''', "200\n")

    def test_map_has(self, expect_output):
        """Check if key exists in map."""
        expect_output('''
func main() -> int
    var m: Map<int, int> = {5: 50, 10: 100}
    if m.has(5)
        print(1)
    ~
    if not m.has(7)
        print(2)
    ~
    return 0
~
''', "1\n2\n")

    def test_map_set(self, expect_output):
        """Set value in map (value semantics - returns new map)."""
        expect_output('''
func main() -> int
    var m: Map<int, int> = {1: 10}
    m = m.set(2, 20)
    print(m.get(2))
    return 0
~
''', "20\n")

    def test_map_remove(self, expect_output):
        """Remove key from map."""
        expect_output('''
func main() -> int
    var m: Map<int, int> = {1: 10, 2: 20}
    m.remove(1)
    print(m.len())
    return 0
~
''', "1\n")


class TestSets:
    """Tests for set literals and operations."""

    def test_set_literal(self, expect_output):
        """Set literal with elements."""
        expect_output('''
func main() -> int
    var s: Set<int> = {1, 2, 3}
    print(s.len())
    return 0
~
''', "3\n")

    def test_set_has(self, expect_output):
        """Check if element exists in set."""
        expect_output('''
func main() -> int
    var s: Set<int> = {10, 20, 30}
    if s.has(20)
        print(1)
    ~
    if not s.has(25)
        print(2)
    ~
    return 0
~
''', "1\n2\n")

    def test_set_add(self, expect_output):
        """Add element to set (value semantics - returns new set)."""
        expect_output('''
func main() -> int
    var s: Set<int> = {1, 2}
    s = s.add(3)
    print(s.len())
    return 0
~
''', "3\n")

    def test_set_remove(self, expect_output):
        """Remove element from set."""
        expect_output('''
func main() -> int
    var s: Set<int> = {1, 2, 3}
    s.remove(2)
    print(s.len())
    return 0
~
''', "2\n")

    def test_set_no_duplicates(self, expect_output):
        """Set should not allow duplicates."""
        expect_output('''
func main() -> int
    var s: Set<int> = {1, 1, 2, 2, 3}
    print(s.len())
    return 0
~
''', "3\n")


class TestCollectionValueSemantics:
    """Tests for collection value semantics - mutation returns new collection."""

    def test_list_append_original_unchanged(self, expect_output):
        """List.append returns new list, original is unchanged."""
        expect_output('''
func main() -> int
    var a: List<int> = [1, 2, 3]
    var b: List<int> = a.append(4)
    print(a.len())
    print(b.len())
    return 0
~
''', "3\n4\n")

    def test_list_assignment_copies(self, expect_output):
        """Assigning a list creates an independent copy."""
        expect_output('''
func main() -> int
    var a: List<int> = [1, 2, 3]
    var b: List<int> = a
    b = b.append(4)
    print(a.len())
    print(b.len())
    return 0
~
''', "3\n4\n")

    def test_map_set_original_unchanged(self, expect_output):
        """Map.set returns new map, original is unchanged."""
        expect_output('''
func main() -> int
    var a: Map<int, int> = {1: 10}
    var b: Map<int, int> = a.set(2, 20)
    print(a.len())
    print(b.len())
    return 0
~
''', "1\n2\n")

    def test_map_assignment_copies(self, expect_output):
        """Assigning a map creates an independent copy."""
        expect_output('''
func main() -> int
    var a: Map<int, int> = {1: 10}
    var b: Map<int, int> = a
    b = b.set(2, 20)
    print(a.len())
    print(b.len())
    return 0
~
''', "1\n2\n")

    def test_set_add_original_unchanged(self, expect_output):
        """Set.add returns new set, original is unchanged."""
        expect_output('''
func main() -> int
    var a: Set<int> = {1, 2}
    var b: Set<int> = a.add(3)
    print(a.len())
    print(b.len())
    return 0
~
''', "2\n3\n")

    def test_set_assignment_copies(self, expect_output):
        """Assigning a set creates an independent copy."""
        expect_output('''
func main() -> int
    var a: Set<int> = {1, 2}
    var b: Set<int> = a
    b = b.add(3)
    print(a.len())
    print(b.len())
    return 0
~
''', "2\n3\n")


class TestLambdas:
    """Tests for lambda expressions."""

    def test_lambda_formula_simple(self, expect_output):
        """Simple formula lambda."""
        expect_output('''
func apply(f: formula(int) -> int, x: int) -> int
    return f(x)
~

func main() -> int
    var result: int = apply(formula(_ x: int) => x * 2, 21)
    print(result)
    return 0
~
''', "42\n")

    def test_lambda_stored_in_var(self, expect_output):
        """Lambda stored in variable."""
        expect_output('''
func main() -> int
    var double: formula(int) -> int = formula(_ x: int) => x * 2
    print(double(10))
    return 0
~
''', "20\n")

    def test_lambda_with_two_params(self, expect_output):
        """Lambda with multiple parameters."""
        expect_output('''
func main() -> int
    var add: formula(int, int) -> int = formula(_ a: int, _ b: int) => a + b
    print(add(15, 27))
    return 0
~
''', "42\n")


class TestRanges:
    """Tests for range expressions."""

    def test_range_in_for(self, expect_output):
        """Range expression in for loop."""
        expect_output('''
func main() -> int
    var sum: int = 0
    for i in 0..5
        sum += i
    ~
    print(sum)
    return 0
~
''', "10\n")

    def test_range_with_variables(self, expect_output):
        """Range with variable bounds."""
        expect_output('''
func main() -> int
    var start: int = 1
    var stop: int = 4
    var sum: int = 0
    for i in start..stop
        sum += i
    ~
    print(sum)
    return 0
~
''', "6\n")


class TestCollectionSize:
    """Tests for .size() method on collections.

    .size() returns the total memory footprint in bytes:
    - List: 32 (header) + cap * elem_size
    - String: 16 (header) + byte_len
    - Map: 24 (header) + cap * 24 (MapEntry size)
    - Set: 24 (header) + cap * 16 (SetEntry size)
    """

    def test_list_size_empty(self, expect_output):
        """Empty list size (header + initial capacity * elem_size)."""
        # List header: 32 bytes, initial cap=8, elem_size=8 for int
        # Size = 32 + 8 * 8 = 96
        expect_output('''
func main() -> int
    var lst: List<int> = []
    print(lst.size())
    return 0
~
''', "96\n")

    def test_list_size_with_elements(self, expect_output):
        """List size with some elements (still within initial capacity)."""
        # Same as empty - cap doesn't change until it's exceeded
        expect_output('''
func main() -> int
    var lst: List<int> = [1, 2, 3]
    print(lst.size())
    return 0
~
''', "96\n")

    def test_string_size(self, expect_output):
        """String size (header + byte length)."""
        # String header: 16 bytes, "hello" = 5 bytes
        # Size = 16 + 5 = 21
        expect_output('''
func main() -> int
    var s: string = "hello"
    print(s.size())
    return 0
~
''', "21\n")

    def test_string_size_empty(self, expect_output):
        """Empty string size."""
        # String header: 16 bytes, empty = 0 bytes
        # Size = 16 + 0 = 16
        expect_output('''
func main() -> int
    var s: string = ""
    print(s.size())
    return 0
~
''', "16\n")

    def test_map_size_empty(self, expect_output):
        """Empty map size (header + initial capacity * entry size)."""
        # Map header: 24 bytes, initial cap=8, MapEntry=24 bytes
        # Size = 24 + 8 * 24 = 216
        expect_output('''
func main() -> int
    var m: Map<int, int> = {}
    print(m.size())
    return 0
~
''', "216\n")

    def test_map_size_with_elements(self, expect_output):
        """Map size with some elements."""
        expect_output('''
func main() -> int
    var m: Map<int, int> = {1: 10, 2: 20}
    print(m.size())
    return 0
~
''', "216\n")

    def test_set_size_empty(self, expect_output):
        """Empty set size (header + initial capacity * entry size)."""
        # Set header: 24 bytes, initial cap=8, SetEntry=16 bytes
        # Size = 24 + 8 * 16 = 152
        expect_output('''
func main() -> int
    var s: Set<int> = {1, 2, 3}
    print(s.size())
    return 0
~
''', "152\n")

    def test_size_and_len_different(self, expect_output):
        """Verify .size() and .len() return different values."""
        expect_output('''
func main() -> int
    var lst: List<int> = [1, 2, 3]
    print(lst.len())
    print(lst.size())
    return 0
~
''', "3\n96\n")


class TestParameterValueSemantics:
    """Tests that function parameters are deep-copied on entry (value semantics)."""

    def test_list_parameter_isolated(self, expect_output):
        """Modifying list parameter inside function should not affect caller."""
        expect_output('''
func modify_list(lst: List<int>) -> int
    lst = lst.append(99)
    return lst.len()
~

func main() -> int
    var original: List<int> = [1, 2, 3]
    var new_len: int = modify_list(original)
    print(original.len())
    print(new_len)
    return 0
~
''', "3\n4\n")

    def test_map_parameter_isolated(self, expect_output):
        """Modifying map parameter inside function should not affect caller."""
        expect_output('''
func modify_map(m: Map<int, int>) -> int
    m = m.set(99, 999)
    return m.len()
~

func main() -> int
    var original: Map<int, int> = {1: 10, 2: 20}
    var new_len: int = modify_map(original)
    print(original.len())
    print(new_len)
    return 0
~
''', "2\n3\n")

    def test_set_parameter_isolated(self, expect_output):
        """Modifying set parameter inside function should not affect caller."""
        expect_output('''
func modify_set(s: Set<int>) -> int
    s = s.add(99)
    return s.len()
~

func main() -> int
    var original: Set<int> = {1, 2, 3}
    var new_len: int = modify_set(original)
    print(original.len())
    print(new_len)
    return 0
~
''', "3\n4\n")

    def test_string_parameter_isolated(self, expect_output):
        """String parameter should be copied (verify it doesn't crash)."""
        expect_output('''
func use_string(s: string) -> int
    return s.len()
~

func main() -> int
    var original: string = "hello"
    print(use_string(original))
    print(original.len())
    return 0
~
''', "5\n5\n")

    @pytest.mark.xfail(reason="Nested lists have a preexisting bug - .get() crashes")
    def test_nested_list_parameter_isolated(self, expect_output):
        """Nested list modifications should not affect caller."""
        expect_output('''
func modify_nested(lst: List<List<int>>) -> int
    var inner: List<int> = lst.get(0)
    inner = inner.append(99)
    return inner.len()
~

func main() -> int
    var inner: List<int> = [1, 2]
    var outer: List<List<int>> = [inner]
    var new_len: int = modify_nested(outer)
    var orig_inner: List<int> = outer.get(0)
    print(orig_inner.len())
    print(new_len)
    return 0
~
''', "2\n3\n")
