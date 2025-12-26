"""
Tests for Result<T, E> type.

Result is a general-purpose error handling type that can be:
- Ok(value) - success with a value
- Err(error) - failure with an error

Methods:
- .is_ok() -> bool
- .is_err() -> bool
- .unwrap() -> T (panics if Err)
- .unwrap_or(default) -> T
- .unwrap_err() -> E (panics if Ok)
"""

import pytest


class TestResultBasics:
    """Basic Result construction and methods."""

    def test_result_ok_is_ok(self, expect_output):
        """Result.ok() creates an Ok variant that returns true for is_ok()."""
        expect_output('''
func main() -> int
    r: Result<int, string> = Result.ok(42)
    if r.is_ok()
        print(1)
    else
        print(0)
    ~
    return 0
~
''', "1\n")

    def test_result_ok_is_not_err(self, expect_output):
        """Result.ok() creates an Ok variant that returns false for is_err()."""
        expect_output('''
func main() -> int
    r: Result<int, string> = Result.ok(42)
    if r.is_err()
        print(1)
    else
        print(0)
    ~
    return 0
~
''', "0\n")

    def test_result_err_is_err(self, expect_output):
        """Result.err() creates an Err variant that returns true for is_err()."""
        expect_output('''
func main() -> int
    r: Result<int, string> = Result.err("failed")
    if r.is_err()
        print(1)
    else
        print(0)
    ~
    return 0
~
''', "1\n")

    def test_result_err_is_not_ok(self, expect_output):
        """Result.err() creates an Err variant that returns false for is_ok()."""
        expect_output('''
func main() -> int
    r: Result<int, string> = Result.err("failed")
    if r.is_ok()
        print(1)
    else
        print(0)
    ~
    return 0
~
''', "0\n")

    def test_result_unwrap_ok(self, expect_output):
        """unwrap() on Ok returns the value."""
        expect_output('''
func main() -> int
    r: Result<int, string> = Result.ok(42)
    print(r.unwrap())
    return 0
~
''', "42\n")

    def test_result_unwrap_or_ok(self, expect_output):
        """unwrap_or() on Ok returns the value, ignoring default."""
        expect_output('''
func main() -> int
    r: Result<int, string> = Result.ok(42)
    print(r.unwrap_or(0))
    return 0
~
''', "42\n")

    def test_result_unwrap_or_err(self, expect_output):
        """unwrap_or() on Err returns the default."""
        expect_output('''
func main() -> int
    r: Result<int, string> = Result.err("failed")
    print(r.unwrap_or(99))
    return 0
~
''', "99\n")


class TestResultMatch:
    """Pattern matching on Result."""

    def test_result_match_ok(self, expect_output):
        """Match on Ok variant extracts the value."""
        expect_output('''
func main() -> int
    r: Result<int, string> = Result.ok(42)
    match r
        case Ok(v):
            print(v)
        ~
        case Err(e):
            print(0)
        ~
    ~
    return 0
~
''', "42\n")

    def test_result_match_err(self, expect_output):
        """Match on Err variant extracts the error."""
        expect_output('''
func main() -> int
    r: Result<int, string> = Result.err("oops")
    match r
        case Ok(v):
            print(0)
        ~
        case Err(e):
            print(1)
        ~
    ~
    return 0
~
''', "1\n")


class TestResultFunctions:
    """Result used with functions."""

    def test_result_return_ok(self, expect_output):
        """Function can return Result.ok()."""
        expect_output('''
func divide(a: int, b: int) -> Result<int, string>
    if b == 0
        return Result.err("division by zero")
    ~
    return Result.ok(a / b)
~

func main() -> int
    r: Result<int, string> = divide(10, 2)
    print(r.unwrap())
    return 0
~
''', "5\n")

    def test_result_return_err(self, expect_output):
        """Function can return Result.err()."""
        expect_output('''
func divide(a: int, b: int) -> Result<int, string>
    if b == 0
        return Result.err("division by zero")
    ~
    return Result.ok(a / b)
~

func main() -> int
    r: Result<int, string> = divide(10, 0)
    if r.is_err()
        print(1)
    else
        print(0)
    ~
    return 0
~
''', "1\n")

    def test_result_chain(self, expect_output):
        """Result can be chained through multiple functions."""
        expect_output('''
func parse_int(s: string) -> Result<int, string>
    if s == "42"
        return Result.ok(42)
    ~
    return Result.err("invalid")
~

func double(x: int) -> Result<int, string>
    return Result.ok(x * 2)
~

func main() -> int
    r1: Result<int, string> = parse_int("42")
    if r1.is_ok()
        r2: Result<int, string> = double(r1.unwrap())
        print(r2.unwrap())
    ~
    return 0
~
''', "84\n")


class TestResultTypes:
    """Result with different type parameters."""

    def test_result_with_float(self, expect_output):
        """Result can hold float values."""
        expect_output('''
func main() -> int
    r: Result<float, string> = Result.ok(3.14)
    if r.is_ok()
        print(1)
    ~
    return 0
~
''', "1\n")

    def test_result_with_bool(self, expect_output):
        """Result can hold bool values."""
        expect_output('''
func main() -> int
    r: Result<bool, string> = Result.ok(true)
    if r.unwrap()
        print(1)
    else
        print(0)
    ~
    return 0
~
''', "1\n")

    def test_result_with_string(self, expect_output):
        """Result can hold string values."""
        expect_output('''
func main() -> int
    r: Result<string, string> = Result.ok("hello")
    print(r.unwrap())
    return 0
~
''', "hello\n")

    def test_result_with_int_error(self, expect_output):
        """Result can have int as error type."""
        expect_output('''
func main() -> int
    r: Result<string, int> = Result.err(404)
    if r.is_err()
        print(1)
    ~
    return 0
~
''', "1\n")
