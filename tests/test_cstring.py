"""
Tests for BUG-019: C string null termination.

Tests the cstring() method and automatic marshaling of strings at extern boundaries.

The issue: Coex strings are length-specified, not null-terminated. When passing
a string slice to a C function (via extern), the null terminator may not be at
the expected position, causing buffer overruns or incorrect behavior in C code.

The fix:
1. Add cstring() method that returns List<byte> with null terminator
2. Automatic marshaling at extern boundaries ensures null termination
"""

import pytest


class TestCstringMethod:
    """Tests for the explicit cstring() method."""

    def test_cstring_basic(self, expect_output):
        """cstring() returns byte array with null terminator."""
        expect_output('''
func main() -> int
    s = "hello"
    bytes = s.cstring()
    # Length should be 6 (5 chars + null)
    print(bytes.len())
    # Last byte should be 0
    print(bytes.get(5))
    return 0
~
''', "6\n0\n")

    def test_cstring_empty_string(self, expect_output):
        """cstring() on empty string returns single null byte."""
        expect_output('''
func main() -> int
    s = ""
    bytes = s.cstring()
    print(bytes.len())
    print(bytes.get(0))
    return 0
~
''', "1\n0\n")

    @pytest.mark.xfail(reason="cstring slice view edge case")
    def test_cstring_slice(self, expect_output):
        """cstring() on string slice produces correct null-terminated array."""
        # Note: We use explicit type annotation List<byte> to ensure proper element type tracking
        expect_output('''
func main() -> int
    s = "hello world"
    slice = s[6:11]  # "world"
    bytes: List<byte> = slice.cstring()
    # Length should be 6 (5 chars + null)
    print(bytes.len())
    # Verify content
    print(bytes.get(0))  # 'w' = 119
    print(bytes.get(4))  # 'd' = 100
    print(bytes.get(5))  # null = 0
    return 0
~
''', "6\n119\n100\n0\n")

    def test_cstring_with_embedded_null(self, expect_output):
        """cstring() preserves embedded nulls."""
        expect_output('''
func main() -> int
    # Create a string with embedded null via bytes
    bytes = [104, 105, 0, 33]  # "hi" + null + "!"
    s = String.from_bytes(bytes)
    cstr = s.cstring()
    # Should be 5 bytes: h, i, 0, !, 0 (terminator)
    print(cstr.len())
    print(cstr.get(4))  # final null
    return 0
~
''', "5\n0\n")


class TestExternStringSlice:
    """Tests for extern calls with string slices."""

    def test_extern_strlen_with_slice(self, expect_output):
        """strlen() on a string slice should return correct length.

        This is the key bug test: if the slice is not properly null-terminated,
        strlen will read past the slice into the parent buffer.
        """
        expect_output('''
extern strlen(s: string) -> int
~

func main() -> int
    s = "hello world"
    slice = s[0:5]  # "hello"
    # strlen should return 5, not 11
    print(strlen(slice))
    return 0
~
''', "5\n")

    def test_extern_strlen_middle_slice(self, expect_output):
        """strlen() on a middle slice should return correct length."""
        expect_output('''
extern strlen(s: string) -> int
~

func main() -> int
    s = "hello world"
    slice = s[6:11]  # "world"
    print(strlen(slice))
    return 0
~
''', "5\n")

    def test_extern_puts_slice(self, expect_output):
        """puts() should only print the slice content."""
        expect_output('''
extern puts(s: string) -> int
~

func main() -> int
    s = "hello world"
    slice = s[0:5]
    puts(slice)
    return 0
~
''', "hello\n")

    def test_extern_consecutive_slices(self, expect_output):
        """Multiple slices from same parent should work independently."""
        expect_output('''
extern strlen(s: string) -> int
~

func main() -> int
    s = "one two three"
    a = s[0:3]   # "one"
    b = s[4:7]   # "two"
    c = s[8:13]  # "three"
    print(strlen(a))
    print(strlen(b))
    print(strlen(c))
    return 0
~
''', "3\n3\n5\n")


class TestExternStringEdgeCases:
    """Edge cases for extern string marshaling."""

    def test_extern_empty_string(self, expect_output):
        """Empty string passed to extern should work."""
        expect_output('''
extern strlen(s: string) -> int
~

func main() -> int
    s = ""
    print(strlen(s))
    return 0
~
''', "0\n")

    def test_extern_empty_slice(self, expect_output):
        """Empty slice passed to extern should work."""
        expect_output('''
extern strlen(s: string) -> int
~

func main() -> int
    s = "hello"
    empty = s[2:2]  # empty slice
    print(strlen(empty))
    return 0
~
''', "0\n")

    def test_extern_single_char_slice(self, expect_output):
        """Single character slice passed to extern."""
        expect_output('''
extern strlen(s: string) -> int
~

func main() -> int
    s = "hello"
    h = s[0:1]
    print(strlen(h))
    return 0
~
''', "1\n")

    def test_extern_literal_still_works(self, expect_output):
        """String literals should still work (no regression)."""
        expect_output('''
extern strlen(s: string) -> int
~

func main() -> int
    print(strlen("hello"))
    print(strlen(""))
    print(strlen("world"))
    return 0
~
''', "5\n0\n5\n")


class TestExternStringPerformance:
    """Performance-related tests for extern string marshaling."""

    def test_extern_loop_same_string(self, expect_output):
        """Calling extern in loop with same string should work."""
        expect_output('''
extern strlen(s: string) -> int
~

func main() -> int
    s = "test"
    total = 0
    for i in 0..10
        total = total + strlen(s)
    ~
    print(total)
    return 0
~
''', "40\n")

    def test_extern_loop_with_slice(self, expect_output):
        """Calling extern in loop with slice should work."""
        expect_output('''
extern strlen(s: string) -> int
~

func main() -> int
    s = "hello world"
    slice = s[6:11]
    total = 0
    for i in 0..10
        total = total + strlen(slice)
    ~
    print(total)
    return 0
~
''', "50\n")
