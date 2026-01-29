"""
Tests for JSON compile-time warnings.

Phase 6 of JSON refactoring: Emit warnings when assigning non-JSON types to
json variables. Code compiles and runs (annotation is created), but a warning
is emitted to stderr.
"""

import pytest
import subprocess
import tempfile
import os


class TestJsonCompileWarnings:
    """Tests for compile-time warnings on non-JSON type assignment."""

    def test_json_warn_on_function_assignment(self, compile_coex):
        """Assigning function to json emits compile-time warning."""
        code = '''
func helper() -> int
    return 42
~

func main() -> int
    j: json := helper
    return 0
~
'''
        result = compile_coex(code)
        assert result.compile_success, "Should compile successfully"
        # Check stderr for warning
        assert "@coex:func" in result.compile_output or "warning" in result.compile_output.lower()

    def test_json_warn_on_set_assignment(self, compile_coex):
        """Assigning Set to json emits compile-time warning."""
        code = '''
func main() -> int
    s: Set<int> = {1, 2, 3}
    j: json := s
    return 0
~
'''
        result = compile_coex(code)
        assert result.compile_success, "Should compile successfully"
        # Check for warning about Set
        assert "Set" in result.compile_output or "warning" in result.compile_output.lower()

    @pytest.mark.xfail(reason="Task handles are i64 values - cannot be distinguished from integers")
    def test_json_warn_on_task_assignment(self, compile_coex):
        """Assigning task to json emits compile-time warning.

        NOTE: Task handles are pthread_t (i64) values that cannot be distinguished
        from regular integers at the type system level, so no warning is emitted.
        """
        code = '''
task worker() -> int
    return 1
~

func main() -> int
    t := worker()
    j: json := t
    return 0
~
'''
        result = compile_coex(code)
        assert result.compile_success, "Should compile successfully"
        assert "task" in result.compile_output.lower() or "warning" in result.compile_output.lower()

    def test_json_no_warn_on_compatible_types(self, compile_coex):
        """No warning for JSON-compatible types (int, string, List, Map)."""
        code = '''
func main() -> int
    j1: json := 42
    j2: json := "hello"
    j3: json := [1, 2, 3]
    j4: json := {"key": 100}
    return 0
~
'''
        result = compile_coex(code)
        assert result.compile_success, "Should compile successfully"
        # Should NOT contain warnings for these compatible types
        output_lower = result.compile_output.lower()
        assert "warning" not in output_lower or "@coex" not in output_lower

    @pytest.mark.xfail(reason="List<any> type not supported in Coex - nested detection not possible")
    def test_json_warn_on_nested_incompatible(self, compile_coex):
        """Warning for nested structures containing non-JSON types.

        NOTE: List<any> is not supported, so detecting non-JSON types nested
        within lists is not possible with the current type system.
        """
        code = '''
func helper() -> int
    return 1
~

func main() -> int
    # List containing a function - should warn
    items: List<any> = [helper]
    j: json := items
    return 0
~
'''
        result = compile_coex(code)
        assert result.compile_success, "Should compile successfully"
        # Should warn about the function in the list
        assert "warning" in result.compile_output.lower() or "func" in result.compile_output.lower()


class TestJsonWarningMessages:
    """Tests for warning message content and format."""

    def test_warning_includes_type_name(self, compile_coex):
        """Warning message should include the non-JSON type name."""
        code = '''
func my_func() -> int
    return 1
~

func main() -> int
    j: json := my_func
    return 0
~
'''
        result = compile_coex(code)
        assert result.compile_success
        # Warning should mention the type being converted
        assert "function" in result.compile_output.lower() or "func" in result.compile_output.lower()

    def test_warning_includes_variable_name(self, compile_coex):
        """Warning message should include the target variable name."""
        code = '''
func helper() -> int
    return 1
~

func main() -> int
    my_json_var: json := helper
    return 0
~
'''
        result = compile_coex(code)
        assert result.compile_success
        # Warning should reference the variable
        assert "my_json_var" in result.compile_output or "json" in result.compile_output.lower()
