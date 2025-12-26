"""
Tests for string .len() method.

The .len() method returns the character count (UTF-8 codepoints)
for strings, consistent with how .len() returns element count for lists.
"""

import pytest


class TestStringLen:
    """Tests for .len() on strings"""

    def test_len_basic_string(self, expect_output):
        """.len() on a basic string literal"""
        expect_output('''
func main() -> int
    s: string = "hello"
    print(s.len())
    return 0
~
''', "5\n")

    def test_len_single_char(self, expect_output):
        """.len() on single character string"""
        expect_output('''
func main() -> int
    s: string = "x"
    print(s.len())
    return 0
~
''', "1\n")

    def test_len_long_string(self, expect_output):
        """.len() on a longer string"""
        expect_output('''
func main() -> int
    s: string = "hello world"
    print(s.len())
    return 0
~
''', "11\n")

    def test_len_empty_string(self, expect_output):
        """.len() on empty string"""
        expect_output('''
func main() -> int
    s: string = ""
    print(s.len())
    return 0
~
''', "0\n")

    def test_len_string_from_function(self, expect_output):
        """.len() on string returned from function"""
        expect_output('''
func get_greeting() -> string
    return "hi there"
~

func main() -> int
    s: string = get_greeting()
    print(s.len())
    return 0
~
''', "8\n")

    def test_len_string_parameter(self, expect_output):
        """.len() on string passed as parameter"""
        expect_output('''
func string_length(s: string) -> int
    return s.len()
~

func main() -> int
    print(string_length("test"))
    return 0
~
''', "4\n")


class TestStringLenInExpressions:
    """Tests for s.len() used in expressions"""

    def test_len_in_comparison(self, expect_output):
        """s.len() in comparison expression"""
        expect_output('''
func main() -> int
    s: string = "hello"
    if s.len() > 0
        print(1)
    else
        print(0)
    ~
    return 0
~
''', "1\n")

    def test_len_in_arithmetic(self, expect_output):
        """s.len() in arithmetic expression"""
        expect_output('''
func main() -> int
    s: string = "abc"
    print(s.len() * 2)
    return 0
~
''', "6\n")

    def test_len_in_range(self, expect_output):
        """s.len() used in range for loop"""
        expect_output('''
func main() -> int
    s: string = "abc"
    count: int = 0
    for i in 0..s.len()
        count = count + 1
    ~
    print(count)
    return 0
~
''', "3\n")


class TestStringLenContrast:
    """Tests showing both list and string .len() work correctly"""

    def test_list_len_works(self, expect_output):
        """Verify list .len() works"""
        expect_output('''
func main() -> int
    items: List<int> = [1, 2, 3, 4, 5]
    print(items.len())
    return 0
~
''', "5\n")

    def test_string_and_list_len_together(self, expect_output):
        """Both string and list .len() in same program"""
        expect_output('''
func main() -> int
    s: string = "hello"
    items: List<int> = [1, 2, 3]
    print(s.len())
    print(items.len())
    return 0
~
''', "5\n3\n")
