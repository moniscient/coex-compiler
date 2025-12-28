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


class TestStringConversions:
    """Tests for .int() and .float() conversion methods"""

    def test_string_to_int_basic(self, expect_output):
        """.int() on a numeric string (returns optional, use ?? for default)"""
        expect_output('''
func main() -> int
    s: string = "42"
    print(s.int() ?? 0)
    return 0
~
''', "42\n")

    def test_string_to_int_negative(self, expect_output):
        """.int() on a negative number string"""
        expect_output('''
func main() -> int
    s: string = "-123"
    print(s.int() ?? 0)
    return 0
~
''', "-123\n")

    def test_string_to_int_zero(self, expect_output):
        """.int() on zero string"""
        expect_output('''
func main() -> int
    s: string = "0"
    print(s.int() ?? -1)
    return 0
~
''', "0\n")

    def test_string_to_int_from_list_element(self, compile_binary):
        """.int() on a string element from a list (original use case)"""
        binary = compile_binary('''
func main(args:[string]) -> int
    num = args[1].int() ?? 0
    print(num)
    return 0
~
''')
        assert binary.compile_success, f"Compilation failed:\n{binary.compile_output}"
        proc = binary.run("99")
        assert proc.stdout.strip() == "99", f"Expected '99', got: {proc.stdout.strip()}"

    def test_string_to_float_basic(self, expect_output):
        """.float() on a decimal string"""
        expect_output('''
func main() -> int
    s: string = "3.14"
    f: float = s.float() ?? 0.0
    print(f)
    return 0
~
''', "3.140000\n")

    def test_string_to_float_integer(self, expect_output):
        """.float() on an integer string"""
        expect_output('''
func main() -> int
    s: string = "42"
    f: float = s.float() ?? 0.0
    print(f)
    return 0
~
''', "42.000000\n")

    def test_string_to_int_in_expression(self, expect_output):
        """.int() used in arithmetic expression"""
        expect_output('''
func main() -> int
    s: string = "10"
    result = (s.int() ?? 0) * 2
    print(result)
    return 0
~
''', "20\n")

    def test_string_to_int_hex(self, expect_output):
        """.int_hex() on hex string"""
        expect_output('''
func main() -> int
    s: string = "ff"
    print(s.int_hex() ?? 0)
    return 0
~
''', "255\n")

    def test_string_to_int_hex_uppercase(self, expect_output):
        """.int_hex() on uppercase hex string"""
        expect_output('''
func main() -> int
    s: string = "FF"
    print(s.int_hex() ?? 0)
    return 0
~
''', "255\n")

    def test_string_to_int_invalid_uses_fallback(self, expect_output):
        """.int() on invalid string returns nil, fallback is used"""
        expect_output('''
func main() -> int
    s: string = "abc"
    print(s.int() ?? 999)
    return 0
~
''', "999\n")

    def test_string_to_float_invalid_uses_fallback(self, expect_output):
        """.float() on invalid string returns nil, fallback is used"""
        expect_output('''
func main() -> int
    s: string = "xyz"
    f: float = s.float() ?? 1.5
    print(f)
    return 0
~
''', "1.500000\n")


class TestStringFrom:
    """Tests for String.from() static methods"""

    def test_string_from_int(self, expect_output):
        """String.from(int) converts integer to string"""
        expect_output('''
func main() -> int
    s = String.from(42)
    print(s)
    return 0
~
''', "42\n")

    def test_string_from_negative_int(self, expect_output):
        """String.from(int) with negative number"""
        expect_output('''
func main() -> int
    s = String.from(-123)
    print(s)
    return 0
~
''', "-123\n")

    def test_string_from_float(self, expect_output):
        """String.from(float) converts float to string"""
        expect_output('''
func main() -> int
    s = String.from(3.14159)
    print(s)
    return 0
~
''', "3.14159\n")

    def test_string_from_bool_true(self, expect_output):
        """String.from(true) returns 'true'"""
        expect_output('''
func main() -> int
    s = String.from(true)
    print(s)
    return 0
~
''', "true\n")

    def test_string_from_bool_false(self, expect_output):
        """String.from(false) returns 'false'"""
        expect_output('''
func main() -> int
    s = String.from(false)
    print(s)
    return 0
~
''', "false\n")

    def test_string_from_hex(self, expect_output):
        """String.from_hex(int) converts to hex string"""
        expect_output('''
func main() -> int
    s = String.from_hex(255)
    print(s)
    return 0
~
''', "ff\n")

    def test_string_from_hex_large(self, expect_output):
        """String.from_hex with large number"""
        expect_output('''
func main() -> int
    s = String.from_hex(65535)
    print(s)
    return 0
~
''', "ffff\n")

    def test_string_concatenation_with_from(self, expect_output):
        """String concatenation using String.from()"""
        expect_output('''
func main() -> int
    x = 42
    n = 100
    message = "Value: " + String.from(x) + ", Count: " + String.from(n)
    print(message)
    return 0
~
''', "Value: 42, Count: 100\n")
