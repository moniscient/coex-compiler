"""
Tests for control flow statements.

These tests verify:
- If/else if/else chains
- For loops with range
- Loop statements with break/continue
- While loops (if supported)
"""

import pytest


class TestIfStatements:
    """Tests for if/else if/else statements."""
    
    def test_if_true(self, expect_output):
        expect_output('''
func main() -> int
    if true
        print(42)
    ~
    return 0
~
''', "42\n")
    
    def test_if_false_no_else(self, expect_output):
        expect_output('''
func main() -> int
    if false
        print(42)
    ~
    print(0)
    return 0
~
''', "0\n")
    
    def test_if_else_true_branch(self, expect_output):
        expect_output('''
func main() -> int
    if true
        print(1)
    else
        print(2)
    ~
    return 0
~
''', "1\n")
    
    def test_if_else_false_branch(self, expect_output):
        expect_output('''
func main() -> int
    if false
        print(1)
    else
        print(2)
    ~
    return 0
~
''', "2\n")
    
    def test_elif_first_branch(self, expect_output):
        expect_output('''
func main() -> int
    var x: int = 1
    if x == 1
        print(10)
    else if x == 2
        print(20)
    else
        print(30)
    ~
    return 0
~
''', "10\n")
    
    def test_elif_second_branch(self, expect_output):
        expect_output('''
func main() -> int
    var x: int = 2
    if x == 1
        print(10)
    else if x == 2
        print(20)
    else
        print(30)
    ~
    return 0
~
''', "20\n")
    
    def test_elif_else_branch(self, expect_output):
        expect_output('''
func main() -> int
    var x: int = 99
    if x == 1
        print(10)
    else if x == 2
        print(20)
    else
        print(30)
    ~
    return 0
~
''', "30\n")
    
    def test_multiple_elif(self, expect_output):
        expect_output('''
func main() -> int
    var x: int = 3
    if x == 1
        print(1)
    else if x == 2
        print(2)
    else if x == 3
        print(3)
    else if x == 4
        print(4)
    else
        print(0)
    ~
    return 0
~
''', "3\n")
    
    def test_nested_if(self, expect_output):
        expect_output('''
func main() -> int
    var x: int = 5
    var y: int = 3
    if x > 0
        if y > 0
            print(1)
        ~
    ~
    return 0
~
''', "1\n")


class TestForLoops:
    """Tests for for loops."""
    
    def test_for_range_sum(self, expect_output):
        expect_output('''
func main() -> int
    var sum: int = 0
    for i in range(1, 6)
        sum += i
    ~
    print(sum)
    return 0
~
''', "15\n")
    
    def test_for_range_count(self, expect_output):
        expect_output('''
func main() -> int
    var count: int = 0
    for i in range(0, 10)
        count += 1
    ~
    print(count)
    return 0
~
''', "10\n")
    
    def test_for_range_empty(self, expect_output):
        expect_output('''
func main() -> int
    var sum: int = 0
    for i in range(5, 5)
        sum += i
    ~
    print(sum)
    return 0
~
''', "0\n")
    
    def test_for_nested(self, expect_output):
        expect_output('''
func main() -> int
    var sum: int = 0
    for i in range(1, 4)
        for j in range(1, 4)
            sum += 1
        ~
    ~
    print(sum)
    return 0
~
''', "9\n")
    
    def test_for_with_variable_bounds(self, expect_output):
        expect_output('''
func main() -> int
    var n: int = 5
    var sum: int = 0
    for i in range(0, n)
        sum += i
    ~
    print(sum)
    return 0
~
''', "10\n")


class TestLoopStatement:
    """Tests for infinite loop with break/continue."""
    
    def test_loop_with_break(self, expect_output):
        expect_output('''
func main() -> int
    var i: int = 0
    loop
        i += 1
        if i >= 5
            break
        ~
    ~
    print(i)
    return 0
~
''', "5\n")
    
    def test_loop_with_continue(self, expect_output):
        expect_output('''
func main() -> int
    var sum: int = 0
    var i: int = 0
    loop
        i += 1
        if i > 10
            break
        ~
        if i % 2 == 0
            continue
        ~
        sum += i
    ~
    print(sum)
    return 0
~
''', "25\n")
    
    def test_for_break(self, expect_output):
        expect_output('''
func main() -> int
    var last: int = 0
    for i in range(0, 100)
        last = i
        if i >= 5
            break
        ~
    ~
    print(last)
    return 0
~
''', "5\n")
    
    def test_for_continue(self, expect_output):
        expect_output('''
func main() -> int
    var sum: int = 0
    for i in range(1, 11)
        if i % 2 == 0
            continue
        ~
        sum += i
    ~
    print(sum)
    return 0
~
''', "25\n")


class TestNestedControlFlow:
    """Tests for complex nested control flow."""
    
    def test_if_in_for(self, expect_output):
        expect_output('''
func main() -> int
    var evens: int = 0
    for i in range(1, 11)
        if i % 2 == 0
            evens += 1
        ~
    ~
    print(evens)
    return 0
~
''', "5\n")

    def test_fizzbuzz_count(self, expect_output):
        # Count how many numbers 1-15 are divisible by 3 or 5
        expect_output('''
func main() -> int
    var count: int = 0
    for i in range(1, 16)
        if i % 3 == 0
            count += 1
        else if i % 5 == 0
            count += 1
        ~
    ~
    print(count)
    return 0
~
''', "7\n")
