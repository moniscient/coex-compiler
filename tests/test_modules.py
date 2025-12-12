"""
Tests for module system: import and replace statements.

These tests verify module loading and qualified function calls:
- Import statements
- Qualified calls (module.function)
- Replace aliases
- Standard library modules
"""

import pytest


class TestImport:
    """Tests for import statement."""

    def test_import_math_abs(self, expect_output):
        """Test importing math module and calling math.abs"""
        expect_output('''
import math

func main() -> int
    print(math.abs(-42))
    return 0
~
''', "42\n")

    def test_import_math_max(self, expect_output):
        """Test math.max function"""
        expect_output('''
import math

func main() -> int
    print(math.max(10, 20))
    return 0
~
''', "20\n")

    def test_import_math_min(self, expect_output):
        """Test math.min function"""
        expect_output('''
import math

func main() -> int
    print(math.min(10, 20))
    return 0
~
''', "10\n")

    def test_import_math_clamp(self, expect_output):
        """Test math.clamp function"""
        expect_output('''
import math

func main() -> int
    print(math.clamp(15, 0, 10))
    return 0
~
''', "10\n")

    def test_import_math_sign(self, expect_output):
        """Test math.sign function"""
        expect_output('''
import math

func main() -> int
    print(math.sign(-5))
    print(math.sign(0))
    print(math.sign(7))
    return 0
~
''', "-1\n0\n1\n")


class TestReplace:
    """Tests for replace statement (local aliases)."""

    def test_replace_abs(self, expect_output):
        """Test replace alias for math.abs"""
        expect_output('''
import math
replace abs with math.abs

func main() -> int
    print(abs(-42))
    return 0
~
''', "42\n")

    def test_replace_multiple(self, expect_output):
        """Test multiple replace aliases"""
        expect_output('''
import math
replace abs with math.abs
replace max with math.max
replace min with math.min

func main() -> int
    print(abs(-10))
    print(max(5, 15))
    print(min(5, 15))
    return 0
~
''', "10\n15\n5\n")

    def test_replace_with_local_function(self, expect_output):
        """Test that local functions still work with replace"""
        expect_output('''
import math
replace abs with math.abs

func double(_ x: int) -> int
    return x * 2
~

func main() -> int
    print(abs(-21))
    print(double(21))
    return 0
~
''', "21\n42\n")


class TestQualifiedCalls:
    """Tests for module.function() call syntax."""

    def test_qualified_call_in_expression(self, expect_output):
        """Test qualified call as part of expression"""
        expect_output('''
import math

func main() -> int
    var x: int = math.abs(-5) + math.abs(-7)
    print(x)
    return 0
~
''', "12\n")

    def test_qualified_call_nested(self, expect_output):
        """Test nested qualified calls"""
        expect_output('''
import math

func main() -> int
    print(math.max(math.abs(-10), math.abs(-5)))
    return 0
~
''', "10\n")

    def test_mixed_qualified_and_local(self, expect_output):
        """Test mixing module functions with local functions"""
        expect_output('''
import math

func square(_ x: int) -> int
    return x * x
~

func main() -> int
    var x: int = math.abs(-3)
    print(square(x))
    return 0
~
''', "9\n")


class TestModuleErrors:
    """Tests for module error handling."""

    def test_unknown_module(self, expect_compile_error):
        """Test error on importing unknown module"""
        expect_compile_error('''
import nonexistent

func main() -> int
    return 0
~
''', "Module not found")

    def test_replace_without_import(self, expect_compile_error):
        """Test error when using replace without import"""
        expect_compile_error('''
replace abs with math.abs

func main() -> int
    return 0
~
''', "not imported")
