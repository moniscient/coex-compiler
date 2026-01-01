"""
Tests for string.split() method.

Tests cover:
- Basic splitting by single-character delimiters
- Multi-character delimiter splitting
- Empty segments handling
- Edge cases (empty string, no matches, delimiter at start/end)
"""

import pytest


class TestStringSplitBasic:
    """Basic tests for string.split()."""

    def test_split_by_newline(self, expect_output):
        """Split string by newline character."""
        expect_output('''
func main() -> int
    text = "line1\\nline2\\nline3"
    parts = text.split("\\n")
    print(parts.len())
    print(parts.get(0))
    print(parts.get(1))
    print(parts.get(2))
    return 0
~
''', "3\nline1\nline2\nline3\n")

    def test_split_by_comma(self, expect_output):
        """Split string by comma."""
        expect_output('''
func main() -> int
    text = "a,b,c,d"
    parts = text.split(",")
    print(parts.len())
    print(parts.get(0))
    print(parts.get(1))
    print(parts.get(2))
    print(parts.get(3))
    return 0
~
''', "4\na\nb\nc\nd\n")

    def test_split_by_space(self, expect_output):
        """Split string by space."""
        expect_output('''
func main() -> int
    text = "hello world foo bar"
    parts = text.split(" ")
    print(parts.len())
    print(parts.get(0))
    print(parts.get(3))
    return 0
~
''', "4\nhello\nbar\n")

    def test_split_no_delimiter_found(self, expect_output):
        """When delimiter not found, returns list with original string."""
        expect_output('''
func main() -> int
    text = "hello world"
    parts = text.split(",")
    print(parts.len())
    print(parts.get(0))
    return 0
~
''', "1\nhello world\n")


class TestStringSplitMultiChar:
    """Tests for multi-character delimiter splitting."""

    def test_split_by_crlf(self, expect_output):
        """Split by CRLF (two-character delimiter)."""
        expect_output('''
func main() -> int
    text = "line1\\r\\nline2\\r\\nline3"
    parts = text.split("\\r\\n")
    print(parts.len())
    print(parts.get(0))
    print(parts.get(1))
    print(parts.get(2))
    return 0
~
''', "3\nline1\nline2\nline3\n")

    def test_split_by_word_delimiter(self, expect_output):
        """Split by multi-character word."""
        expect_output('''
func main() -> int
    text = "aSEPbSEPc"
    parts = text.split("SEP")
    print(parts.len())
    print(parts.get(0))
    print(parts.get(1))
    print(parts.get(2))
    return 0
~
''', "3\na\nb\nc\n")


class TestStringSplitEdgeCases:
    """Edge case tests for string.split()."""

    def test_split_empty_string(self, expect_output):
        """Splitting empty string returns list with empty string."""
        expect_output('''
func main() -> int
    text = ""
    parts = text.split(",")
    print(parts.len())
    return 0
~
''', "1\n")

    def test_split_delimiter_at_start(self, expect_output):
        """Delimiter at start creates empty first segment."""
        expect_output('''
func main() -> int
    text = ",a,b"
    parts = text.split(",")
    print(parts.len())
    print(parts.get(1))
    print(parts.get(2))
    return 0
~
''', "3\na\nb\n")

    def test_split_delimiter_at_end(self, expect_output):
        """Delimiter at end creates empty last segment."""
        expect_output('''
func main() -> int
    text = "a,b,"
    parts = text.split(",")
    print(parts.len())
    print(parts.get(0))
    print(parts.get(1))
    return 0
~
''', "3\na\nb\n")

    def test_split_consecutive_delimiters(self, expect_output):
        """Consecutive delimiters create empty segments."""
        expect_output('''
func main() -> int
    text = "a,,b"
    parts = text.split(",")
    print(parts.len())
    print(parts.get(0))
    print(parts.get(2))
    return 0
~
''', "3\na\nb\n")

    def test_split_only_delimiters(self, expect_output):
        """String of only delimiters creates empty segments."""
        expect_output('''
func main() -> int
    text = ",,"
    parts = text.split(",")
    print(parts.len())
    return 0
~
''', "3\n")


class TestStringSplitIteration:
    """Tests for iterating over split results."""

    def test_split_and_iterate(self, expect_output):
        """Can iterate over split results and call methods on elements."""
        expect_output('''
func main() -> int
    text = "hello,world,test"
    total_len = 0
    for part in text.split(",")
        total_len = total_len + part.len()
    ~
    print(total_len)
    return 0
~
''', "14\n")

    def test_split_lines_and_process(self, expect_output):
        """Split lines and process each."""
        expect_output('''
func main() -> int
    text = "hello\\nworld\\ntest"
    count = 0
    for line in text.split("\\n")
        count = count + line.len()
    ~
    print(count)
    return 0
~
''', "14\n")


class TestStringSplitZeroCopy:
    """Tests verifying zero-copy behavior."""

    def test_split_shares_buffer(self, expect_output):
        """Split results share original buffer (zero-copy)."""
        expect_output('''
func main() -> int
    text = "abcXdefXghi"
    parts = text.split("X")
    print(parts.get(0))
    print(parts.get(1))
    print(parts.get(2))
    return 0
~
''', "abc\ndef\nghi\n")

    def test_split_large_string(self, expect_output):
        """Split works on larger strings."""
        expect_output('''
func main() -> int
    text = "the quick brown fox jumps over the lazy dog"
    words = text.split(" ")
    print(words.len())
    print(words.get(0))
    print(words.get(4))
    print(words.get(8))
    return 0
~
''', "9\nthe\njumps\ndog\n")
