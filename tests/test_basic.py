"""
Tests for basic arithmetic, variables, and expressions.

These tests verify fundamental compiler functionality:
- Integer and float arithmetic
- Variable declarations and assignments
- Comparison and logical operators
- Global variables
"""

import pytest


class TestIntegerArithmetic:
    """Tests for integer arithmetic operations."""
    
    def test_addition(self, expect_output):
        expect_output('''
func main() -> int
    print(2 + 3)
    return 0
~
''', "5\n")
    
    def test_subtraction(self, expect_output):
        expect_output('''
func main() -> int
    print(10 - 4)
    return 0
~
''', "6\n")
    
    def test_multiplication(self, expect_output):
        expect_output('''
func main() -> int
    print(6 * 7)
    return 0
~
''', "42\n")
    
    def test_division(self, expect_output):
        expect_output('''
func main() -> int
    print(20 / 4)
    return 0
~
''', "5\n")
    
    def test_modulo(self, expect_output):
        expect_output('''
func main() -> int
    print(17 % 5)
    return 0
~
''', "2\n")
    
    def test_negation(self, expect_output):
        expect_output('''
func main() -> int
    print(-42)
    return 0
~
''', "-42\n")
    
    def test_precedence_mul_before_add(self, expect_output):
        expect_output('''
func main() -> int
    print(2 + 3 * 4)
    return 0
~
''', "14\n")
    
    def test_parentheses_override_precedence(self, expect_output):
        expect_output('''
func main() -> int
    print((2 + 3) * 4)
    return 0
~
''', "20\n")
    
    def test_complex_expression(self, expect_output):
        expect_output('''
func main() -> int
    print(((10 - 2) * 3 + 6) / 2)
    return 0
~
''', "15\n")
    
    def test_hex_literal(self, expect_output):
        expect_output('''
func main() -> int
    print(0xFF)
    return 0
~
''', "255\n")
    
    def test_binary_literal(self, expect_output):
        expect_output('''
func main() -> int
    print(0b1010)
    return 0
~
''', "10\n")


class TestFloatArithmetic:
    """Tests for floating-point arithmetic."""
    
    def test_float_addition(self, expect_output):
        expect_output('''
func main() -> int
    print(1.5 + 2.5)
    return 0
~
''', "4.000000\n")
    
    def test_float_multiplication(self, expect_output):
        expect_output('''
func main() -> int
    print(2.5 * 4.0)
    return 0
~
''', "10.000000\n")


class TestVariables:
    """Tests for variable declarations and assignments."""
    
    def test_var_declaration(self, expect_output):
        expect_output('''
func main() -> int
    var x: int = 42
    print(x)
    return 0
~
''', "42\n")
    
    def test_var_mutation(self, expect_output):
        expect_output('''
func main() -> int
    var x: int = 10
    x = 20
    print(x)
    return 0
~
''', "20\n")
    
    def test_compound_plus_assign(self, expect_output):
        expect_output('''
func main() -> int
    var x: int = 10
    x += 5
    print(x)
    return 0
~
''', "15\n")
    
    def test_compound_minus_assign(self, expect_output):
        expect_output('''
func main() -> int
    var x: int = 20
    x -= 7
    print(x)
    return 0
~
''', "13\n")
    
    def test_compound_star_assign(self, expect_output):
        expect_output('''
func main() -> int
    var x: int = 6
    x *= 7
    print(x)
    return 0
~
''', "42\n")
    
    def test_multiple_variables(self, expect_output):
        expect_output('''
func main() -> int
    var a: int = 10
    var b: int = 20
    var c: int = a + b
    print(c)
    return 0
~
''', "30\n")
    
    def test_variable_in_expression(self, expect_output):
        expect_output('''
func main() -> int
    var x: int = 5
    var y: int = 3
    print(x * y + 2)
    return 0
~
''', "17\n")


class TestComparisons:
    """Tests for comparison operators."""
    
    def test_less_than_true(self, expect_output):
        expect_output('''
func main() -> int
    if 3 < 5
        print(1)
    ~
    return 0
~
''', "1\n")
    
    def test_less_than_false(self, expect_output):
        expect_output('''
func main() -> int
    var result: int = 0
    if 5 < 3
        result = 1
    ~
    print(result)
    return 0
~
''', "0\n")
    
    def test_greater_than(self, expect_output):
        expect_output('''
func main() -> int
    if 7 > 3
        print(1)
    ~
    return 0
~
''', "1\n")
    
    def test_less_equal(self, expect_output):
        expect_output('''
func main() -> int
    if 5 <= 5
        print(1)
    ~
    return 0
~
''', "1\n")
    
    def test_greater_equal(self, expect_output):
        expect_output('''
func main() -> int
    if 5 >= 5
        print(1)
    ~
    return 0
~
''', "1\n")
    
    def test_equality_true(self, expect_output):
        expect_output('''
func main() -> int
    if 5 == 5
        print(1)
    ~
    return 0
~
''', "1\n")
    
    def test_equality_false(self, expect_output):
        expect_output('''
func main() -> int
    var result: int = 0
    if 5 == 3
        result = 1
    ~
    print(result)
    return 0
~
''', "0\n")
    
    def test_inequality(self, expect_output):
        expect_output('''
func main() -> int
    if 5 != 3
        print(1)
    ~
    return 0
~
''', "1\n")


class TestBooleanLogic:
    """Tests for boolean operators."""
    
    def test_and_true_true(self, expect_output):
        expect_output('''
func main() -> int
    if true and true
        print(1)
    ~
    return 0
~
''', "1\n")
    
    def test_and_true_false(self, expect_output):
        expect_output('''
func main() -> int
    var result: int = 0
    if true and false
        result = 1
    ~
    print(result)
    return 0
~
''', "0\n")
    
    def test_or_false_true(self, expect_output):
        expect_output('''
func main() -> int
    if false or true
        print(1)
    ~
    return 0
~
''', "1\n")
    
    def test_or_false_false(self, expect_output):
        expect_output('''
func main() -> int
    var result: int = 0
    if false or false
        result = 1
    ~
    print(result)
    return 0
~
''', "0\n")
    
    def test_not_false(self, expect_output):
        expect_output('''
func main() -> int
    if not false
        print(1)
    ~
    return 0
~
''', "1\n")
    
    def test_not_true(self, expect_output):
        expect_output('''
func main() -> int
    var result: int = 0
    if not true
        result = 1
    ~
    print(result)
    return 0
~
''', "0\n")
    
    def test_complex_boolean(self, expect_output):
        expect_output('''
func main() -> int
    if (3 < 5) and (7 > 2)
        print(1)
    ~
    return 0
~
''', "1\n")


class TestGlobalVariables:
    """Tests for global variable declarations."""
    
    def test_global_read(self, expect_output):
        expect_output('''
var MAGIC: int = 42

func main() -> int
    print(MAGIC)
    return 0
~
''', "42\n")
    
    def test_global_in_expression(self, expect_output):
        expect_output('''
var FACTOR: int = 10

func main() -> int
    var x: int = 5
    print(x * FACTOR)
    return 0
~
''', "50\n")
    
    def test_multiple_globals(self, expect_output):
        expect_output('''
var A: int = 10
var B: int = 20

func main() -> int
    print(A + B)
    return 0
~
''', "30\n")


class TestTernaryExpression:
    """Tests for ternary conditional expressions."""
    
    def test_ternary_true_branch(self, expect_output):
        expect_output('''
func main() -> int
    var x: int = true ? 10 ; 20
    print(x)
    return 0
~
''', "10\n")
    
    def test_ternary_false_branch(self, expect_output):
        expect_output('''
func main() -> int
    var x: int = false ? 10 ; 20
    print(x)
    return 0
~
''', "20\n")
    
    def test_ternary_with_comparison(self, expect_output):
        expect_output('''
func main() -> int
    var a: int = 5
    var b: int = 3
    var max: int = a > b ? a ; b
    print(max)
    return 0
~
''', "5\n")
    
    def test_ternary_nested(self, expect_output):
        expect_output('''
func main() -> int
    var x: int = 5
    var result: int = x < 0 ? -1 ; x == 0 ? 0 ; 1
    print(result)
    return 0
~
''', "1\n")
