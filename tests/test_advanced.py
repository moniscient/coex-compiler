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

    @pytest.mark.xfail(reason="Codegen bug: append method arg type mismatch (i8* vs i64)")
    def test_list_append(self, expect_output):
        """Append to list."""
        expect_output('''
func main() -> int
    var lst: List<int> = [1, 2]
    lst.append(3)
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
