"""
Tests for complex bodies in `first` and `most` structured concurrency.

Complex bodies include:
- If/else conditionals
- Multiple statements
- Variable declarations
- Nested control flow

These should be supported by generating synthetic task functions that
execute via the work-stealing scheduler.

Note: `first` uses racing semantics - whichever task completes first wins.
Tests must accept any valid task result, not a specific one.
"""

import pytest


class TestFirstComplexBody:
    """Tests for `first` with complex bodies"""

    def test_first_with_if_else(self, compile_coex):
        """First with conditional dispatch based on loop variable.

        Racing semantics: either task_a (100) or task_b (200) can win.
        We add random busy-wait delays to introduce non-determinism.
        """
        result = compile_coex('''
task task_a() -> int
    # Random busy-wait delay
    n = posix.random_seed() % 1000
    x = 0
    for j in 0..n
        x = x + 1
    ~
    return 100
~

task task_b() -> int
    # Random busy-wait delay
    n = posix.random_seed() % 1000
    x = 0
    for j in 0..n
        x = x + 1
    ~
    return 200
~

func main() -> int
    result = first i in [1, 2]
        if i == 1
            task_a()
        else
            task_b()
        ~
    ~
    print(result)
    return 0
~
''')
        assert result.compile_success, f"Compilation failed:\n{result.compile_output}"
        assert result.run_success, f"Execution failed:\n{result.run_output}"
        # Racing: accept either valid result
        assert result.run_output in ("100\n", "200\n"), \
            f"Expected 100 or 200, got: {result.run_output!r}"

    def test_first_with_multiple_conditions(self, compile_coex):
        """First with multiple conditional branches.

        Racing semantics: any of work_a (10), work_b (20), or work_c (30) can win.
        """
        result = compile_coex('''
task work_a() -> int
    n = posix.random_seed() % 1000
    x = 0
    for j in 0..n
        x = x + 1
    ~
    return 10
~

task work_b() -> int
    n = posix.random_seed() % 1000
    x = 0
    for j in 0..n
        x = x + 1
    ~
    return 20
~

task work_c() -> int
    n = posix.random_seed() % 1000
    x = 0
    for j in 0..n
        x = x + 1
    ~
    return 30
~

func main() -> int
    result = first i in [1, 2, 3]
        if i == 1
            work_a()
        else
            if i == 2
                work_b()
            else
                work_c()
            ~
        ~
    ~
    print(result)
    return 0
~
''')
        assert result.compile_success, f"Compilation failed:\n{result.compile_output}"
        assert result.run_success, f"Execution failed:\n{result.run_output}"
        # Racing: accept any valid result
        assert result.run_output in ("10\n", "20\n", "30\n"), \
            f"Expected 10, 20, or 30, got: {result.run_output!r}"

    def test_first_with_local_computation(self, expect_output):
        """First body with local variable computation"""
        expect_output('''
task process(x: int) -> int
    return x * 10
~

func main() -> int
    result = first i in [5]
        x = i * 2
        process(x)
    ~
    print(result)
    return 0
~
''', "100\n")


class TestMostComplexBody:
    """Tests for `most` with complex bodies"""

    def test_most_with_if_else(self, expect_output):
        """Most with conditional dispatch"""
        expect_output('''
task double(x: int) -> int
    return x * 2
~

task triple(x: int) -> int
    return x * 3
~

func main() -> int
    (results, errors) = most i in [1, 2, 3, 4]
        if i % 2 == 0
            double(i)
        else
            triple(i)
        ~
    ~
    total = 0
    for r in results
        total = total + r
    ~
    print(total)
    return 0
~
''', "24\n")  # i=1: triple(1)=3, i=2: double(2)=4, i=3: triple(3)=9, i=4: double(4)=8 → 3+4+9+8=24

    def test_most_with_local_vars(self, expect_output):
        """Most body with local variable computation"""
        expect_output('''
task compute(x: int) -> int
    return x
~

func main() -> int
    (results, errors) = most i in [1, 2, 3]
        x = i * 10
        compute(x)
    ~
    total = 0
    for r in results
        total = total + r
    ~
    print(total)
    return 0
~
''', "60\n")  # 10 + 20 + 30 = 60


class TestComplexBodyTokenRing:
    """Test complex body patterns needed for token ring benchmark"""

    def test_conditional_dispatch_three_way(self, expect_output):
        """Dispatch to different functions based on index"""
        expect_output('''
task node0() -> int
    return 0
~

task node1() -> int
    return 1
~

task node2() -> int
    return 2
~

func main() -> int
    (results, errors) = most i in [0, 1, 2]
        if i == 0
            node0()
        else
            if i == 1
                node1()
            else
                node2()
            ~
        ~
    ~
    total = 0
    for r in results
        total = total + r
    ~
    print(total)
    return 0
~
''', "3\n")  # 0 + 1 + 2 = 3

    def test_first_with_computation_in_body(self, expect_output):
        """First where body does computation before task call"""
        expect_output('''
task process(x: int) -> int
    return x * x
~

func main() -> int
    result = first i in [10, 20, 30]
        v = i + 5
        process(v)
    ~
    print(result)
    return 0
~
''', "225\n")  # First result: (10+5)^2 = 15^2 = 225
