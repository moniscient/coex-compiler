"""
Tests for undeclared identifier and undefined method error detection.

These tests verify the compiler properly reports errors for:
- Using undeclared variables
- Compound assignment on undeclared variables
- Method calls on undeclared objects
- Calling undefined methods on types
"""

import pytest


class TestUndeclaredIdentifier:
    """Tests for basic undeclared identifier errors."""

    def test_undeclared_variable_in_expression(self, expect_compile_error):
        """Test error when using undeclared variable in expression"""
        expect_compile_error('''
func main() -> int
    x = undeclared_var + 1
    return 0
~
''', "Undeclared identifier 'undeclared_var'")

    def test_undeclared_variable_in_print(self, expect_compile_error):
        """Test error when printing undeclared variable"""
        expect_compile_error('''
func main() -> int
    print(unknown)
    return 0
~
''', "Undeclared identifier 'unknown'")

    def test_undeclared_in_condition(self, expect_compile_error):
        """Test error when using undeclared variable in if condition"""
        expect_compile_error('''
func main() -> int
    if missing_var > 0
        print(1)
    ~
    return 0
~
''', "Undeclared identifier 'missing_var'")


class TestCompoundAssignmentErrors:
    """Tests for compound assignment on undeclared variables."""

    def test_plus_assign_undeclared(self, expect_compile_error):
        """Test error on += with undeclared variable"""
        expect_compile_error('''
func main() -> int
    total += 1
    return 0
~
''', "Undeclared identifier 'total'")

    def test_minus_assign_undeclared(self, expect_compile_error):
        """Test error on -= with undeclared variable"""
        expect_compile_error('''
func main() -> int
    counter -= 5
    return 0
~
''', "Undeclared identifier 'counter'")

    def test_times_assign_undeclared(self, expect_compile_error):
        """Test error on *= with undeclared variable"""
        expect_compile_error('''
func main() -> int
    value *= 2
    return 0
~
''', "Undeclared identifier 'value'")


class TestMethodCallErrors:
    """Tests for method calls on undeclared objects."""

    def test_method_call_undeclared_object(self, expect_compile_error):
        """Test error when calling method on undeclared object"""
        expect_compile_error('''
func main() -> int
    dst_handle.write("hello")
    return 0
~
''', "Undeclared identifier 'dst_handle'")

    def test_member_access_undeclared_object(self, expect_compile_error):
        """Test error when accessing member of undeclared object"""
        expect_compile_error('''
func main() -> int
    x = some_struct.field
    return 0
~
''', "Undeclared identifier 'some_struct'")


class TestUndefinedMethodErrors:
    """Tests for calling undefined methods on types."""

    def test_undefined_method_on_posix(self, expect_compile_error):
        """Test error when calling non-existent method on posix"""
        expect_compile_error('''
func main(args: [string], stdin: posix, stdout: posix, stderr: posix) -> int
    src: Result<posix, string> = posix.open("test.txt", "r")
    handle: posix = src.unwrap()
    chunk: Result<string, string> = handle.readall()
    return 0
~
''', "Undefined method 'readall' on type 'posix'")

    def test_undefined_method_on_list(self, expect_compile_error):
        """Test error when calling non-existent method on list"""
        expect_compile_error('''
func main() -> int
    nums = [1, 2, 3]
    nums.push(4)
    return 0
~
''', "Undefined method 'push' on type 'List'")

    def test_undefined_method_on_string(self, expect_compile_error):
        """Test error when calling non-existent method on string"""
        expect_compile_error('''
func main() -> int
    s = "hello"
    x = s.length()
    return 0
~
''', "Undefined method 'length' on type 'String'")


class TestDeclaredVariablesWork:
    """Verify that declared variables still work correctly."""

    def test_simple_assignment_declares(self, expect_output):
        """Test that simple = creates a new variable"""
        expect_output('''
func main() -> int
    x = 42
    print(x)
    return 0
~
''', "42\n")

    def test_compound_after_declare(self, expect_output):
        """Test that compound assignment works after declaration"""
        expect_output('''
func main() -> int
    x = 10
    x += 5
    print(x)
    return 0
~
''', "15\n")

    def test_typed_declaration(self, expect_output):
        """Test typed declaration followed by compound assignment"""
        expect_output('''
func main() -> int
    total: int = 0
    total += 100
    print(total)
    return 0
~
''', "100\n")


class TestScopeErrors:
    """Tests for variable scoping errors - using variables outside their declaring scope."""

    def test_variable_from_if_block_not_visible(self, expect_compile_error):
        """Variable declared in if block should not be visible outside"""
        expect_compile_error('''
func main() -> int
    x = 5
    if x > 0
        data: int = 42
    ~
    print(data)
    return 0
~
''', "Undeclared identifier 'data'")

    def test_variable_from_else_block_not_visible(self, expect_compile_error):
        """Variable declared in else block should not be visible outside"""
        expect_compile_error('''
func main() -> int
    x = 5
    if x < 0
        a = 1
    else
        result: int = 100
    ~
    print(result)
    return 0
~
''', "Undeclared identifier 'result'")

    def test_variable_from_elif_block_not_visible(self, expect_compile_error):
        """Variable declared in else-if block should not be visible outside"""
        expect_compile_error('''
func main() -> int
    x = 2
    if x == 1
        a = 1
    else if x == 2
        value: int = 50
    else
        a = 3
    ~
    print(value)
    return 0
~
''', "Undeclared identifier 'value'")

    def test_variable_visible_in_same_scope(self, expect_output):
        """Variable declared at function level should be visible throughout function"""
        expect_output('''
func main() -> int
    data: int = 42
    if data > 0
        print(data)
    ~
    print(data)
    return 0
~
''', "42\n42\n")

    def test_variable_can_be_modified_in_if_block(self, expect_output):
        """Variable declared outside if block can be modified inside"""
        expect_output('''
func main() -> int
    data: int = 10
    if true
        data = 20
    ~
    print(data)
    return 0
~
''', "20\n")
