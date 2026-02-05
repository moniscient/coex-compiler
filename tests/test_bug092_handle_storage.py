"""Tests for BUG-092: Handle storage violations.

These tests verify that heap object references stored in Result types,
JSON maps, and task closures use GC handles (not raw pointers) so they
survive garbage collection cycles.
"""

import pytest


class TestResultHandleStorage:
    """Test Result<T, E> stores and retrieves handles correctly."""

    def test_posix_open_unwrap_basic(self, expect_output, tmp_path):
        """Basic posix.open -> unwrap -> use pattern."""
        test_file = tmp_path / "test.txt"
        test_file.write_text("hello world")
        expect_output(f'''
func main() -> int
    f: Result<posix, string> = posix.open("{test_file}", "r")
    if f.is_ok()
        handle: posix = f.unwrap()
        content: Result<string, string> = handle.read_all()
        if content.is_ok()
            print(content.unwrap())
        ~
        handle.close()
    ~
    return 0
~
''', "hello world\n")

    def test_posix_result_survives_gc(self, expect_output, tmp_path):
        """Result containing posix handle must survive GC."""
        test_file = tmp_path / "test_gc.txt"
        test_file.write_text("data after gc")
        expect_output(f'''
func main() -> int
    f: Result<posix, string> = posix.open("{test_file}", "r")
    gc()
    if f.is_ok()
        handle: posix = f.unwrap()
        content: Result<string, string> = handle.read_all()
        if content.is_ok()
            print(content.unwrap())
        ~
        handle.close()
    ~
    return 0
~
''', "data after gc\n")

    def test_result_string_err_survives_gc(self, expect_output):
        """Result error string must survive GC cycle."""
        expect_output('''
func main() -> int
    f: Result<posix, string> = posix.open("/nonexistent/path/file.txt", "r")
    gc()
    if f.is_err()
        print("error caught")
    ~
    return 0
~
''', "error caught\n")

    def test_posix_read_all_string_survives_gc(self, expect_output, tmp_path):
        """String from read_all stored in Result must survive GC."""
        test_file = tmp_path / "content.txt"
        test_file.write_text("persistent content")
        expect_output(f'''
func main() -> int
    f: Result<posix, string> = posix.open("{test_file}", "r")
    if f.is_ok()
        handle: posix = f.unwrap()
        content: Result<string, string> = handle.read_all()
        gc()
        gc()
        if content.is_ok()
            print(content.unwrap())
        ~
        handle.close()
    ~
    return 0
~
''', "persistent content\n")


class TestJsonHandleStorage:
    """Test JSON map storage uses handles correctly."""

    def test_json_object_field_access(self, expect_output):
        """JSON object field access works after construction."""
        expect_output('''
func main() -> int
    j: json = { name: "alice", age: 30 }
    n: json = j["name"]
    a: json = j["age"]
    print(n.as_string())
    print(a.as_int())
    return 0
~
''', "alice\n30\n")

    def test_json_object_survives_gc(self, expect_output):
        """JSON object fields must survive GC cycle."""
        expect_output('''
func main() -> int
    j: json = { greeting: "hello", target: "world" }
    gc()
    gc()
    g: json = j["greeting"]
    t: json = j["target"]
    print(g.as_string())
    print(t.as_string())
    return 0
~
''', "hello\nworld\n")

    def test_json_nested_object_survives_gc(self, expect_output):
        """Nested JSON objects must survive GC."""
        expect_output('''
func main() -> int
    inner: json = { x: 1, y: 2 }
    outer: json = { point: inner }
    gc()
    gc()
    p: json = outer["point"]
    px: json = p["x"]
    py: json = p["y"]
    print(px.as_int())
    print(py.as_int())
    return 0
~
''', "1\n2\n")

    def test_json_set_field_survives_gc(self, expect_output):
        """JSON set_field values must survive GC."""
        expect_output('''
func main() -> int
    j: json = { a: 1 }
    j = j.set("b", "test_string")
    gc()
    gc()
    a_val: json = j["a"]
    b_val: json = j["b"]
    print(a_val.as_int())
    print(b_val.as_string())
    return 0
~
''', "1\ntest_string\n")

    def test_json_stringify_after_gc(self, expect_output):
        """JSON stringify must work after GC cycle."""
        expect_output('''
func main() -> int
    j: json = { key: "value" }
    gc()
    s: string = j.stringify()
    print(s)
    return 0
~
''', '{"key":"value"}\n')


class TestTaskResultHandleStorage:
    """Test task closure result storage uses handles correctly."""

    def test_task_returns_string(self, expect_output):
        """Task returning a string works."""
        expect_output('''
task make_greeting(name: string) -> string
    return "hello " + name
~

func main() -> int
    result := make_greeting("world")
    print(result)
    return 0
~
''', "hello world\n")

    def test_task_returns_list(self, expect_output):
        """Task returning a list works."""
        expect_output('''
task make_list(n: int) -> [int]
    result = [0]
    i = 1
    while i < n
        result = result.append(i)
        i = i + 1
    ~
    return result
~

func main() -> int
    result := make_list(5)
    print(result.len())
    return 0
~
''', "5\n")
