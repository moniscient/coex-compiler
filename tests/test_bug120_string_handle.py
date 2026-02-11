"""
Tests for BUG-120: C runtime coex_string.c must store GC handles in owner_handle.

When C runtime creates strings via coex_string_from_cstring_take (e.g., from
extern function return values), owner_handle must contain a GC handle, not a
raw pointer. Codegen's string_data calls gc_handle_deref on owner_handle.
"""
import pytest


class TestStringFromExternRoundtrip:
    """Test strings created by C extern functions are valid when read back."""

    def test_string_from_int_conversion(self, expect_output):
        """String.from(int) creates string via C runtime, exercises handle path."""
        expect_output('''
func main() -> int
    s = String.from(42)
    print(s)
    print(s.len())
    return 0
~
''', "42\n2\n")

    def test_string_concat_then_read(self, expect_output):
        """Concatenation creates new string via C runtime, read exercises handle deref."""
        expect_output('''
func main() -> int
    a = "hello"
    b = " world"
    c = a + b
    print(c)
    print(c.len())
    return 0
~
''', "hello world\n11\n")

    def test_string_survives_gc_cycle(self, expect_output):
        """String created, GC triggered, then string read — exercises handle validity."""
        expect_output('''
func main() -> int
    x = "test string"
    gc()
    gc()
    print(x)
    return 0
~
''', "test string\n")

    def test_multiple_strings_survive_gc(self, expect_output):
        """Multiple strings created, GC cycles, all strings readable."""
        expect_output('''
func main() -> int
    a = "alpha"
    b = "beta"
    c = "gamma"
    gc()
    gc()
    print(a)
    print(b)
    print(c)
    return 0
~
''', "alpha\nbeta\ngamma\n")

    def test_string_from_concat_survives_gc(self, expect_output):
        """Concatenated string (creates new string via C runtime) survives GC."""
        expect_output('''
func main() -> int
    a = "hello"
    b = " world"
    c = a + b
    gc()
    gc()
    print(c)
    return 0
~
''', "hello world\n")

    def test_string_in_loop_with_gc(self, expect_output):
        """Strings created in loop with GC pressure — exercises handle stability."""
        expect_output('''
func main() -> int
    result = ""
    i = 0
    while i < 10
        result = result + "x"
        if i % 3 == 0
            gc()
        ~
        i = i + 1
    ~
    print(result.len())
    return 0
~
''', "10\n")

    def test_json_stringify_roundtrip(self, expect_output):
        """JSON stringify returns C string, converted back to Coex string."""
        expect_output('''
func main() -> int
    j: json := 42
    s = j.stringify()
    print(s)
    return 0
~
''', "42\n")

    def test_json_object_stringify(self, expect_output):
        """JSON object stringify — more complex C string return."""
        expect_output('''
func main() -> int
    j: json := {"key": "value"}
    s = j.stringify()
    print(s)
    return 0
~
''', '{"key":"value"}\n')


class TestStringHandleStress:
    """Stress tests for string handle stability under GC pressure."""

    def test_many_strings_with_gc_cycles(self, expect_output):
        """Create many strings interleaved with GC to stress handle table."""
        expect_output('''
func main() -> int
    i = 0
    count = 0
    while i < 100
        s = "item_" + String.from(i)
        if s.len() > 0
            count = count + 1
        ~
        if i % 10 == 0
            gc()
        ~
        i = i + 1
    ~
    print(count)
    return 0
~
''', "100\n")
