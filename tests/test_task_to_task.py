"""
Tests for Task-to-Task Execution

These tests verify that tasks can call other tasks with proper:
- Suspension at call points
- Result delivery to correct waiter
- Frame state preservation across suspensions
- Recursive task calls
"""
import pytest


class TestTaskCalling:
    """Tests for task-to-task calls"""

    def test_simple_call(self, expect_output):
        """Task calls another task and receives result"""
        expect_output('''
task callee() -> int
    return 42
~

task caller() -> int
    x := callee()
    return x + 1
~

func main() -> int
    print(caller())
    return 0
~
''', "43\n")

    def test_multiple_calls(self, expect_output):
        """Task makes multiple calls to other tasks"""
        expect_output('''
task produce(x: int) -> int
    return x * 10
~

task consumer() -> int
    a := produce(1)
    b := produce(2)
    c := produce(3)
    return a + b + c
~

func main() -> int
    print(consumer())
    return 0
~
''', "60\n")

    def test_call_chain(self, expect_output):
        """Chain of task calls"""
        expect_output('''
task add1(x: int) -> int
    return x + 1
~

task add2(x: int) -> int
    y := add1(x)
    return y + 2
~

task add3(x: int) -> int
    y := add2(x)
    return y + 3
~

func main() -> int
    print(add3(10))
    return 0
~
''', "16\n")


class TestExecutionOrder:
    """Tests for correct execution ordering"""

    def test_sequential_prints(self, expect_output):
        """Tasks execute in correct order"""
        expect_output('''
task step1() -> int
    print(1)
    return 1
~

task step2() -> int
    print(2)
    return 2
~

task ordered() -> int
    a := step1()
    b := step2()
    return a + b
~

func main() -> int
    result := ordered()
    print(result)
    return 0
~
''', "1\n2\n3\n")

    def test_nested_order(self, expect_output):
        """Nested calls maintain order"""
        expect_output('''
task inner() -> int
    print(2)
    return 2
~

task outer() -> int
    print(1)
    x := inner()
    print(3)
    return x
~

func main() -> int
    result := outer()
    print(result)
    return 0
~
''', "1\n2\n3\n2\n")


class TestStatePreservation:
    """Tests for frame state preservation across suspensions"""

    def test_locals_survive_suspension(self, expect_output):
        """Local variables preserved across task call"""
        expect_output('''
task get_value() -> int
    return 100
~

task uses_locals() -> int
    x = 10
    y = 20
    z := get_value()
    return x + y + z
~

func main() -> int
    print(uses_locals())
    return 0
~
''', "130\n")

    def test_multiple_locals_multiple_suspensions(self, expect_output):
        """Multiple locals across multiple suspensions"""
        expect_output('''
task fetch(n: int) -> int
    return n * n
~

task complex_calc() -> int
    a = 1
    b := fetch(2)
    c = 3
    d := fetch(4)
    e = 5
    return a + b + c + d + e
~

func main() -> int
    print(complex_calc())
    return 0
~
''', "29\n")  # 1 + 4 + 3 + 16 + 5


class TestResultDelivery:
    """Tests for correct result delivery to waiters"""

    def test_result_to_correct_parent(self, expect_output):
        """Each result goes to correct parent"""
        expect_output('''
task make_ten() -> int
    return 10
~

task make_twenty() -> int
    return 20
~

task uses_ten() -> int
    x := make_ten()
    return x + 1
~

task uses_twenty() -> int
    y := make_twenty()
    return y + 1
~

func main() -> int
    a := uses_ten()
    b := uses_twenty()
    print(a)
    print(b)
    return 0
~
''', "11\n21\n")

    def test_interleaved_results(self, expect_output):
        """Results delivered correctly when tasks interleave"""
        expect_output('''
task slow(id: int) -> int
    total = 0
    for i in 0..100
        total = total + i
    ~
    return id
~

task a_task() -> int
    x := slow(1)
    return x * 10
~

task b_task() -> int
    y := slow(2)
    return y * 10
~

func main() -> int
    ra := a_task()
    rb := b_task()
    print(ra)
    print(rb)
    return 0
~
''', "10\n20\n")


class TestRecursion:
    """Tests for recursive task calls"""

    def test_factorial(self, expect_output):
        """Recursive factorial"""
        expect_output('''
task factorial(n: int) -> int
    if n <= 1
        return 1
    ~
    sub := factorial(n - 1)
    return n * sub
~

func main() -> int
    print(factorial(5))
    return 0
~
''', "120\n")

    def test_fibonacci(self, expect_output):
        """Recursive fibonacci (tree recursion)"""
        expect_output('''
task fib(n: int) -> int
    if n <= 1
        return n
    ~
    a := fib(n - 1)
    b := fib(n - 2)
    return a + b
~

func main() -> int
    print(fib(10))
    return 0
~
''', "55\n")

    def test_mutual_recursion(self, expect_output):
        """Mutually recursive tasks"""
        expect_output('''
task is_even(n: int) -> bool
    if n == 0
        return true
    ~
    return is_odd(n - 1)
~

task is_odd(n: int) -> bool
    if n == 0
        return false
    ~
    return is_even(n - 1)
~

func main() -> int
    if is_even(10)
        print(1)
    else
        print(0)
    ~
    return 0
~
''', "1\n")


class TestTaskFromFunc:
    """Tests for calling tasks from func context"""

    def test_func_calls_task(self, expect_output):
        """Func can call task and get result"""
        expect_output('''
task compute(x: int) -> int
    return x * 2
~

func main() -> int
    result := compute(21)
    print(result)
    return 0
~
''', "42\n")

    def test_func_calls_multiple_tasks(self, expect_output):
        """Func can call multiple tasks"""
        expect_output('''
task double(x: int) -> int
    return x * 2
~

task triple(x: int) -> int
    return x * 3
~

func main() -> int
    a := double(10)
    b := triple(10)
    print(a)
    print(b)
    return 0
~
''', "20\n30\n")
