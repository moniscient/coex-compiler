"""
Tests for debug() and print() with compiler directives.

These tests verify:
- debug() outputs to stderr when debugging is enabled
- debug() is omitted when debugging is disabled (default)
- print() outputs to stdout (default enabled)
- print() is omitted when printing off directive is used
- CLI flags --debugging and --no-printing override file directives
"""

import pytest
import subprocess
import tempfile
import os


class TestDebugFunction:
    """Tests for debug() function behavior."""

    def test_debug_disabled_by_default(self, expect_output):
        """Test that debug() produces no output when debugging is not enabled"""
        expect_output('''
func main() -> int
    debug("should not appear")
    print(42)
    return 0
~
''', "42\n")

    def test_debug_enabled_with_directive(self, compile_coex):
        """Test that debug() outputs to stderr when debugging directive is present"""
        result = compile_coex('''
debugging

func main() -> int
    debug("debug message")
    return 0
~
''')
        assert result.run_success
        assert "debug message" in result.stderr

    def test_debug_on_explicit(self, compile_coex):
        """Test debugging on directive"""
        result = compile_coex('''
debugging on

func main() -> int
    debug("explicit on")
    return 0
~
''')
        assert result.run_success
        assert "explicit on" in result.stderr


class TestPrintFunction:
    """Tests for print() function behavior."""

    def test_print_enabled_by_default(self, expect_output):
        """Test that print() works by default"""
        expect_output('''
func main() -> int
    print(123)
    return 0
~
''', "123\n")

    def test_print_disabled_with_directive(self, compile_coex):
        """Test that print() is silenced with printing off directive"""
        result = compile_coex('''
printing off

func main() -> int
    print("should not appear")
    return 0
~
''')
        assert result.run_success
        assert result.stdout == ""

    def test_printing_on_explicit(self, expect_output):
        """Test printing on directive (same as default)"""
        expect_output('''
printing on

func main() -> int
    print(456)
    return 0
~
''', "456\n")


class TestCombinedDirectives:
    """Tests for combining printing and debugging directives."""

    def test_both_enabled(self, compile_coex):
        """Test both print and debug enabled"""
        result = compile_coex('''
debugging
printing

func main() -> int
    debug("stderr")
    print("stdout")
    return 0
~
''')
        assert result.run_success
        assert "stdout" in result.stdout
        assert "stderr" in result.stderr

    def test_print_only(self, compile_coex):
        """Test print enabled, debug disabled (default for debugging)"""
        result = compile_coex('''
func main() -> int
    debug("should not appear")
    print("visible")
    return 0
~
''')
        assert result.run_success
        assert "visible" in result.stdout
        assert result.stderr == "" or "should not appear" not in result.stderr

    def test_debug_only(self, compile_coex):
        """Test debug enabled, print disabled"""
        result = compile_coex('''
debugging on
printing off

func main() -> int
    debug("visible")
    print("should not appear")
    return 0
~
''')
        assert result.run_success
        assert "visible" in result.stderr
        assert result.stdout == ""


class TestDebugTypes:
    """Test debug() with different value types."""

    def test_debug_integer(self, compile_coex):
        """Test debug() with integer"""
        result = compile_coex('''
debugging

func main() -> int
    debug(42)
    return 0
~
''')
        assert result.run_success
        assert "42" in result.stderr

    def test_debug_boolean_true(self, compile_coex):
        """Test debug() with boolean true"""
        result = compile_coex('''
debugging

func main() -> int
    debug(true)
    return 0
~
''')
        assert result.run_success
        assert "true" in result.stderr

    def test_debug_boolean_false(self, compile_coex):
        """Test debug() with boolean false"""
        result = compile_coex('''
debugging

func main() -> int
    debug(false)
    return 0
~
''')
        assert result.run_success
        assert "false" in result.stderr

    def test_debug_string(self, compile_coex):
        """Test debug() with string"""
        result = compile_coex('''
debugging

func main() -> int
    debug("hello world")
    return 0
~
''')
        assert result.run_success
        assert "hello world" in result.stderr
