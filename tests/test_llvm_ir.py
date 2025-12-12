"""
Tests for inline LLVM IR support.

These tests verify the llvm_ir feature that allows embedding raw LLVM IR
instructions within Coex code.
"""

import pytest


class TestLlvmIrBasic:
    """Basic inline LLVM IR tests."""

    def test_void_fence(self, expect_output):
        """Test void llvm_ir statement with memory fence"""
        expect_output('''
func main() -> int
    llvm_ir """
        fence seq_cst
        ret void
    """
    print(42)
    return 0
~
''', "42\n")

    def test_add_two_numbers(self, expect_output):
        """Test llvm_ir expression with variable bindings and return"""
        expect_output('''
func main() -> int
    var x: int = 3
    var y: int = 4
    var result: int = llvm_ir(x -> %a, y -> %b) -> %r: i64 """
        %r = add i64 %a, %b
        ret i64 %r
    """
    print(result)
    return 0
~
''', "7\n")

    def test_multiply_two_numbers(self, expect_output):
        """Test llvm_ir multiplication"""
        expect_output('''
func main() -> int
    var x: int = 6
    var y: int = 7
    var result: int = llvm_ir(x -> %a, y -> %b) -> %r: i64 """
        %r = mul i64 %a, %b
        ret i64 %r
    """
    print(result)
    return 0
~
''', "42\n")

    def test_multiply_add(self, expect_output):
        """Test llvm_ir with multiple operations"""
        expect_output('''
func main() -> int
    var a: int = 3
    var b: int = 4
    var c: int = 5
    var result: int = llvm_ir(a -> %x, b -> %y, c -> %z) -> %r: i64 """
        %t = mul i64 %x, %y
        %r = add i64 %t, %z
        ret i64 %r
    """
    print(result)
    return 0
~
''', "17\n")


class TestLlvmIrAdvanced:
    """Advanced inline LLVM IR tests."""

    def test_subtract(self, expect_output):
        """Test llvm_ir subtraction"""
        expect_output('''
func main() -> int
    var x: int = 50
    var y: int = 8
    var result: int = llvm_ir(x -> %a, y -> %b) -> %r: i64 """
        %r = sub i64 %a, %b
        ret i64 %r
    """
    print(result)
    return 0
~
''', "42\n")

    def test_bitwise_and(self, expect_output):
        """Test llvm_ir bitwise AND"""
        expect_output('''
func main() -> int
    var x: int = 0xFF
    var y: int = 0x0F
    var result: int = llvm_ir(x -> %a, y -> %b) -> %r: i64 """
        %r = and i64 %a, %b
        ret i64 %r
    """
    print(result)
    return 0
~
''', "15\n")

    def test_bitwise_or(self, expect_output):
        """Test llvm_ir bitwise OR"""
        expect_output('''
func main() -> int
    var x: int = 0xF0
    var y: int = 0x0F
    var result: int = llvm_ir(x -> %a, y -> %b) -> %r: i64 """
        %r = or i64 %a, %b
        ret i64 %r
    """
    print(result)
    return 0
~
''', "255\n")

    def test_left_shift(self, expect_output):
        """Test llvm_ir left shift"""
        expect_output('''
func main() -> int
    var x: int = 1
    var y: int = 4
    var result: int = llvm_ir(x -> %a, y -> %b) -> %r: i64 """
        %r = shl i64 %a, %b
        ret i64 %r
    """
    print(result)
    return 0
~
''', "16\n")

    def test_no_bindings(self, expect_output):
        """Test llvm_ir with no variable bindings"""
        expect_output('''
func main() -> int
    var result: int = llvm_ir -> %r: i64 """
        %r = add i64 20, 22
        ret i64 %r
    """
    print(result)
    return 0
~
''', "42\n")


class TestLlvmIrInFunction:
    """Tests for llvm_ir inside user-defined functions."""

    def test_in_helper_function(self, expect_output):
        """Test llvm_ir inside a helper function"""
        expect_output('''
func inline_add(a: int, b: int) -> int
    var result: int = llvm_ir(a -> %x, b -> %y) -> %r: i64 """
        %r = add i64 %x, %y
        ret i64 %r
    """
    return result
~

func main() -> int
    var x: int = inline_add(10, 32)
    print(x)
    return 0
~
''', "42\n")

    def test_multiple_calls(self, expect_output):
        """Test multiple calls to function with inline IR"""
        expect_output('''
func inline_mul(a: int, b: int) -> int
    var result: int = llvm_ir(a -> %x, b -> %y) -> %r: i64 """
        %r = mul i64 %x, %y
        ret i64 %r
    """
    return result
~

func main() -> int
    var x: int = inline_mul(2, 3)
    var y: int = inline_mul(x, 7)
    print(y)
    return 0
~
''', "42\n")
