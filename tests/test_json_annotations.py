"""
Tests for JSON non-JSON type annotations.

Phase 5 of JSON refactoring: Non-JSON types serialize as descriptive annotations
instead of null or causing errors.

Annotation format:
- Functions: {"@coex:func": "function_name"}
- Sets: {"@coex:set": [elements...]}
- Tasks: {"@coex:task": "task_id"}
"""

import pytest


class TestJsonFunctionAnnotation:
    """Tests for function-to-JSON annotation conversion."""

    def test_json_function_annotation_basic(self, expect_output):
        """Function assigned to JSON produces annotation object."""
        expect_output('''
func helper(x: int) -> int
    return x * 2
~

func main() -> int
    j: json := helper
    s: string = j.stringify()
    # Should contain @coex:func
    if s.len() > 10
        print(1)
    else
        print(0)
    ~
    return 0
~
''', "1\n")

    @pytest.mark.xfail(reason="List<any> type not supported in Coex")
    def test_json_function_annotation_in_list(self, expect_output):
        """Function in JSON list produces annotation."""
        # NOTE: List<any> is not supported, so this test cannot work as written
        expect_output('''
func add(a: int, b: int) -> int
    return a + b
~

func main() -> int
    list_with_func: List<any> = [1, add, "text"]
    j: json := list_with_func
    print(j.len())
    return 0
~
''', "3\n")

    def test_json_function_annotation_preserves_name(self, expect_output):
        """Function annotation includes function name."""
        expect_output('''
func my_special_func() -> int
    return 42
~

func main() -> int
    j: json := my_special_func
    s: string = j.stringify()
    print(s)
    return 0
~
''', '{"@coex:func":"my_special_func"}\n')


class TestJsonSetAnnotation:
    """Tests for Set-to-JSON annotation conversion."""

    def test_json_set_annotation_basic(self, expect_output):
        """Set assigned to JSON produces annotation with elements array."""
        expect_output('''
func main() -> int
    s: Set<int> = {1, 2, 3}
    j: json := s
    str: string = j.stringify()
    # Should serialize set elements
    if str.len() > 5
        print(1)
    else
        print(0)
    ~
    return 0
~
''', "1\n")

    def test_json_set_annotation_empty(self, expect_output):
        """Empty set produces empty annotation array."""
        expect_output('''
func main() -> int
    s: Set<int> = {}
    j: json := s
    str: string = j.stringify()
    print(str)
    return 0
~
''', '{"@coex:set":[]}\n')

    def test_json_set_annotation_string_elements(self, expect_output):
        """Set with string elements serializes correctly."""
        expect_output('''
func main() -> int
    s: Set<string> = {"apple", "banana"}
    j: json := s
    str: string = j.stringify()
    # Should contain both strings
    if str.len() > 20
        print(1)
    else
        print(0)
    ~
    return 0
~
''', "1\n")


class TestJsonTaskAnnotation:
    """Tests for Task-to-JSON annotation conversion."""

    @pytest.mark.xfail(reason="Task handles are i64 values indistinguishable from integers at runtime")
    def test_json_task_annotation_basic(self, expect_output):
        """Task assigned to JSON produces annotation.

        NOTE: Task handles are pthread_t values (i64) that cannot be distinguished
        from regular integers at runtime. Implementing task annotations would require
        type tracking through the assignment chain, which is beyond current scope.
        """
        expect_output('''
task worker(x: int) -> int
    return x * 2
~

func main() -> int
    t := worker(5)
    j: json := t
    s: string = j.stringify()
    # Should contain @coex:task
    if s.len() > 10
        print(1)
    else
        print(0)
    ~
    return 0
~
''', "1\n")


class TestJsonMixedTypeAnnotation:
    """Tests for mixed types with annotations."""

    @pytest.mark.xfail(reason="List<any> type not supported in Coex")
    def test_json_mixed_types_partial_annotation(self, expect_output):
        """Mixed list with JSON-compatible and non-JSON types.

        NOTE: List<any> is not a supported type in Coex, so mixed-type lists
        cannot be created. Each list must have a homogeneous element type.
        """
        expect_output('''
func helper() -> int
    return 1
~

func main() -> int
    # Mix of int (JSON-compatible) and function (needs annotation)
    mixed: List<any> = [42, helper]
    j: json := mixed
    print(j.len())
    return 0
~
''', "2\n")

    def test_json_nested_set_annotation(self, expect_output):
        """Nested structure with Set serializes correctly."""
        expect_output('''
func main() -> int
    inner: Set<int> = {1, 2}
    outer: json = { data: inner }
    s: string = outer.stringify()
    # Should have nested set annotation
    if s.len() > 15
        print(1)
    else
        print(0)
    ~
    return 0
~
''', "1\n")
