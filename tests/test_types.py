"""
Tests for tuples, enums, and pattern matching.

These tests verify:
- Tuple construction and element access
- Tuple destructuring
- Enum type definitions
- Match statements
"""

import pytest


class TestTuples:
    """Tests for tuple construction and access."""
    
    def test_tuple_construction(self, expect_output):
        expect_output('''
func main() -> int
    var pair: (int, int) = (10, 20)
    print(pair.0)
    return 0
~
''', "10\n")
    
    def test_tuple_second_element(self, expect_output):
        expect_output('''
func main() -> int
    var pair: (int, int) = (10, 20)
    print(pair.1)
    return 0
~
''', "20\n")
    
    def test_tuple_three_elements(self, expect_output):
        expect_output('''
func main() -> int
    var triple: (int, int, int) = (1, 2, 3)
    print(triple.0 + triple.1 + triple.2)
    return 0
~
''', "6\n")
    
    def test_tuple_in_expression(self, expect_output):
        expect_output('''
func main() -> int
    var p: (int, int) = (3, 4)
    var sum: int = p.0 * p.0 + p.1 * p.1
    print(sum)
    return 0
~
''', "25\n")
    
    def test_tuple_destructuring(self, expect_output):
        expect_output('''
func main() -> int
    var pair: (int, int) = (5, 7)
    (a, b) = pair
    print(a + b)
    return 0
~
''', "12\n")


class TestTupleFunctions:
    """Tests for tuples with functions."""
    
    def test_function_returns_tuple(self, expect_output):
        expect_output('''
func make_pair(x: int) -> (int, int)
    return (x, x * 2)
~

func main() -> int
    var p: (int, int) = make_pair(5)
    print(p.1)
    return 0
~
''', "10\n")
    
    def test_tuple_param(self, expect_output):
        expect_output('''
func sum_pair(p: (int, int)) -> int
    return p.0 + p.1
~

func main() -> int
    var pair: (int, int) = (10, 20)
    print(sum_pair(pair))
    return 0
~
''', "30\n")


class TestEnums:
    """Tests for enum types."""

    def test_simple_enum(self, expect_output):
        expect_output('''
type Color:
    case Red
    case Green
    case Blue
~

func main() -> int
    var c: Color = Color.Green
    match c
        case Green:
            print(2)
        ~
        case Red:
            print(1)
        ~
        case Blue:
            print(3)
        ~
    ~
    return 0
~
''', "2\n")

    def test_enum_with_data(self, expect_output):
        expect_output('''
type Option:
    case Some(value: int)
    case None
~

func main() -> int
    var opt: Option = Option.Some(42)
    match opt
        case Some(v):
            print(v)
        ~
        case None:
            print(0)
        ~
    ~
    return 0
~
''', "42\n")

    def test_enum_none_case(self, expect_output):
        expect_output('''
type Option:
    case Some(value: int)
    case None
~

func main() -> int
    var opt: Option = Option.None
    match opt
        case Some(v):
            print(v)
        ~
        case None:
            print(-1)
        ~
    ~
    return 0
~
''', "-1\n")


class TestMatchStatement:
    """Tests for match statements."""
    
    def test_match_literal(self, expect_output):
        expect_output('''
func main() -> int
    var x: int = 2
    match x
        case 1:
            print(10)
        ~
        case 2:
            print(20)
        ~
        case 3:
            print(30)
        ~
    ~
    return 0
~
''', "20\n")
    
    def test_match_with_default(self, expect_output):
        # Note: Coex uses a catch-all variable (not _) for default match cases
        expect_output('''
func main() -> int
    var x: int = 99
    match x
        case 1:
            print(10)
        ~
        case 2:
            print(20)
        ~
        case other:
            print(0)
        ~
    ~
    return 0
~
''', "0\n")


class TestConditionalExpression:
    """Tests for conditional (ternary) expressions."""
    
    def test_conditional_simple(self, expect_output):
        expect_output('''
func main() -> int
    var result: int = 5 > 3 ? 1 ; 0
    print(result)
    return 0
~
''', "1\n")
    
    def test_conditional_as_argument(self, expect_output):
        expect_output('''
func main() -> int
    var x: int = 10
    print(x > 0 ? x ; 0)
    return 0
~
''', "10\n")


class TestUserDefinedTypes:
    """Tests for user-defined struct types."""
    
    def test_simple_type(self, expect_output):
        expect_output('''
type Point:
    x: int
    y: int
~

func main() -> int
    var p: Point = Point(3, 4)
    print(p.x + p.y)
    return 0
~
''', "7\n")
    
    def test_type_method(self, expect_output):
        expect_output('''
type Counter:
    value: int

    func get() -> int
        return self.value
    ~
~

func main() -> int
    var c: Counter = Counter(42)
    print(c.get())
    return 0
~
''', "42\n")


class TestUDTValueSemantics:
    """Tests that user-defined types have proper value semantics."""

    def test_udt_assignment_copies(self, expect_output):
        """Assigning a UDT should create an independent copy."""
        expect_output('''
type Point:
    x: int
    y: int
~

func main() -> int
    var a: Point = Point(1, 2)
    var b: Point = a
    b.x = 99
    print(a.x)
    print(b.x)
    return 0
~
''', "1\n99\n")

    def test_udt_with_list_field_copies(self, expect_output):
        """UDT with list field should deep copy the list."""
        expect_output('''
type Container:
    items: List<int>
~

func main() -> int
    var a: Container = Container([1, 2, 3])
    var b: Container = a
    b.items = b.items.append(99)
    print(a.items.len())
    print(b.items.len())
    return 0
~
''', "3\n4\n")

    def test_udt_parameter_isolated(self, expect_output):
        """UDT parameter modifications should not affect caller."""
        expect_output('''
type Point:
    x: int
    y: int
~

func modify_point(p: Point) -> int
    p.x = 99
    return p.x
~

func main() -> int
    var original: Point = Point(1, 2)
    var result: int = modify_point(original)
    print(original.x)
    print(result)
    return 0
~
''', "1\n99\n")

    def test_udt_with_list_parameter_isolated(self, expect_output):
        """UDT with list field passed as parameter should be deep copied."""
        expect_output('''
type Container:
    items: List<int>
~

func modify_container(c: Container) -> int
    c.items = c.items.append(99)
    return c.items.len()
~

func main() -> int
    var original: Container = Container([1, 2, 3])
    var new_len: int = modify_container(original)
    print(original.items.len())
    print(new_len)
    return 0
~
''', "3\n4\n")
