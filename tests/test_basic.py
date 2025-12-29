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
    x: int = 42
    print(x)
    return 0
~
''', "42\n")
    
    def test_var_mutation(self, expect_output):
        expect_output('''
func main() -> int
    x: int = 10
    x = 20
    print(x)
    return 0
~
''', "20\n")
    
    def test_compound_plus_assign(self, expect_output):
        expect_output('''
func main() -> int
    x: int = 10
    x += 5
    print(x)
    return 0
~
''', "15\n")
    
    def test_compound_minus_assign(self, expect_output):
        expect_output('''
func main() -> int
    x: int = 20
    x -= 7
    print(x)
    return 0
~
''', "13\n")
    
    def test_compound_star_assign(self, expect_output):
        expect_output('''
func main() -> int
    x: int = 6
    x *= 7
    print(x)
    return 0
~
''', "42\n")
    
    def test_multiple_variables(self, expect_output):
        expect_output('''
func main() -> int
    a: int = 10
    b: int = 20
    c: int = a + b
    print(c)
    return 0
~
''', "30\n")
    
    def test_variable_in_expression(self, expect_output):
        expect_output('''
func main() -> int
    x: int = 5
    y: int = 3
    print(x * y + 2)
    return 0
~
''', "17\n")


class TestConstBindings:
    """Tests for const binding behavior."""

    def test_bare_identifier_rebindable(self, expect_output):
        """Bare identifier declarations are rebindable by default."""
        expect_output('''
func main() -> int
    x = 5
    print(x)
    x = 10
    print(x)
    return 0
~
''', "5\n10\n")

    def test_const_cannot_reassign(self, expect_compile_error):
        """Reassigning a const binding should fail."""
        expect_compile_error('''
func main() -> int
    const x = 5
    x = 10
    return 0
~
''', "Cannot reassign const")

    def test_const_with_type_annotation(self, expect_output):
        """Const works with type annotations."""
        expect_output('''
func main() -> int
    const x: int = 42
    print(x)
    return 0
~
''', "42\n")

    def test_const_move(self, expect_output):
        """Const binding with move operator works."""
        expect_output('''
func main() -> int
    a = [1, 2, 3]
    const b := a
    print(b.len())
    return 0
~
''', "3\n")

    def test_const_move_no_reassign(self, expect_compile_error):
        """Cannot reassign const binding even after move."""
        expect_compile_error('''
func main() -> int
    a = [1, 2, 3]
    const b := a
    b = [4, 5, 6]
    return 0
~
''', "Cannot reassign const")

    def test_rebind_after_first_declaration(self, expect_output):
        """Variable can be rebound after first declaration."""
        expect_output('''
func main() -> int
    x = 1
    x = 2
    x = 3
    print(x)
    return 0
~
''', "3\n")

    def test_const_in_expression(self, expect_output):
        """Const bindings can be used in expressions."""
        expect_output('''
func main() -> int
    const a = 10
    const b = 20
    const sum = a + b
    print(sum)
    return 0
~
''', "30\n")


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
    result: int = 0
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
    result: int = 0
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
    result: int = 0
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
    result: int = 0
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
    result: int = 0
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


class TestTernaryExpression:
    """Tests for ternary conditional expressions."""
    
    def test_ternary_true_branch(self, expect_output):
        expect_output('''
func main() -> int
    x: int = true ? 10 : 20
    print(x)
    return 0
~
''', "10\n")
    
    def test_ternary_false_branch(self, expect_output):
        expect_output('''
func main() -> int
    x: int = false ? 10 : 20
    print(x)
    return 0
~
''', "20\n")
    
    def test_ternary_with_comparison(self, expect_output):
        expect_output('''
func main() -> int
    a: int = 5
    b: int = 3
    max: int = a > b ? a : b
    print(max)
    return 0
~
''', "5\n")
    
    def test_ternary_nested(self, expect_output):
        expect_output('''
func main() -> int
    x: int = 5
    result: int = x < 0 ? -1 : x == 0 ? 0 : 1
    print(result)
    return 0
~
''', "1\n")


class TestColonBlockBegin:
    """Tests for colon as optional block-begin marker."""

    def test_function_with_colon(self, expect_output):
        """Colon can mark start of function block."""
        expect_output('''
func main() -> int: x = 1; y = 2; print(x + y); return 0 ~
''', "3\n")

    def test_if_with_colon(self, expect_output):
        """Colon can mark start of if block."""
        expect_output('''
func main() -> int: x = 5; if x > 0: print(x) ~; return 0 ~
''', "5\n")

    def test_if_else_with_colon(self, expect_output):
        """Colon works with if-else on single line."""
        expect_output('''
func main() -> int: x = -1; if x > 0: print(1) else: print(0) ~; return 0 ~
''', "0\n")

    def test_for_with_colon(self, expect_output):
        """Colon can mark start of for block."""
        expect_output('''
func main() -> int: sum = 0; for i in [1, 2, 3]: sum += i ~; print(sum); return 0 ~
''', "6\n")

    def test_while_with_colon(self, expect_output):
        """Colon can mark start of while block."""
        expect_output('''
func main() -> int: x = 3; while x > 0: print(x); x -= 1 ~; return 0 ~
''', "3\n2\n1\n")

    def test_ternary_with_colon_block(self, expect_output):
        """Ternary inside block-begin colon context works."""
        expect_output('''
func main() -> int: x = 5 > 3 ? 10 : 20; print(x); return 0 ~
''', "10\n")

    def test_ternary_as_if_condition_with_colon(self, expect_output):
        """Ternary as if condition followed by colon block-begin."""
        expect_output('''
func main() -> int: if true ? true : false: print(1) ~; return 0 ~
''', "1\n")


class TestSemicolonStatementTerminator:
    """Tests for semicolon as optional statement terminator."""

    def test_semicolon_between_statements(self, expect_output):
        """Semicolon can separate statements on the same line."""
        expect_output('''
func main() -> int
    x = 1; y = 2; z = 3
    print(x + y + z)
    return 0
~
''', "6\n")

    def test_semicolon_with_newlines(self, expect_output):
        """Semicolon works alongside newlines."""
        expect_output('''
func main() -> int
    x = 10;
    y = 20
    print(x + y)
    return 0
~
''', "30\n")

    def test_semicolon_in_if_block(self, expect_output):
        """Semicolon works in if blocks."""
        expect_output('''
func main() -> int
    x = 5
    if x > 0
        a = 1; b = 2; print(a + b)
    ~
    return 0
~
''', "3\n")

    def test_semicolon_multiple_prints(self, expect_output):
        """Multiple prints separated by semicolons."""
        expect_output('''
func main() -> int
    print(1); print(2); print(3)
    return 0
~
''', "1\n2\n3\n")

    def test_mixed_semicolons_and_newlines(self, expect_output):
        """Mix of semicolons and newlines works correctly."""
        expect_output('''
func main() -> int
    a = 1; b = 2
    c = 3; d = 4
    print(a + b + c + d)
    return 0
~
''', "10\n")


class TestNoGlobalVariables:
    """Tests that global variables are rejected."""

    def test_global_variable_rejected(self, expect_compile_error):
        """Global variables should be rejected by the parser."""
        expect_compile_error('''
var x: int = 10

func main() -> int
    return x
~
''')
