"""
Tests for complex bodies in `first` and `most` structured concurrency.

Complex bodies include:
- If/else conditionals
- Multiple statements
- Variable declarations
- Nested control flow

These should be supported by generating synthetic task functions that
execute via the work-stealing scheduler.
"""

import pytest


class TestFirstComplexBody:
    """Tests for `first` with complex bodies"""

    def test_first_with_if_else(self, expect_output):
        """First with conditional dispatch based on loop variable"""
        expect_output('''
task task_a() -> int
    return 100
~

task task_b() -> int
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
''', "100\n")

    def test_first_with_multiple_conditions(self, expect_output):
        """First with multiple conditional branches"""
        expect_output('''
task work_a() -> int
    return 10
~

task work_b() -> int
    return 20
~

task work_c() -> int
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
''', "10\n")

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
