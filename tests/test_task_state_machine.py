"""
Tests for task state machine transformation.

Phase 1, Step 2: Transform task bodies into stackless state machines.
Tasks run synchronously for now (scheduler comes in Step 3).
"""

import pytest


class TestTaskStateMachine:
    """Tests for task state machine transformation."""

    def test_simple_task_no_suspension(self, expect_output):
        """Task with only formula calls has no suspension points."""
        expect_output('''
formula double(x: int) -> int
    return x * 2
~

task simple(x: int) -> int
    y = double(x)
    return y
~

func main() -> int
    print(simple(21))
    return 0
~
''', "42\n")

    def test_single_suspension_point(self, expect_output):
        """Task with one task call suspends once."""
        expect_output('''
task inner() -> int
    return 10
~

task outer(x: int) -> int
    y := inner()
    return x + y
~

func main() -> int
    print(outer(5))
    return 0
~
''', "15\n")

    def test_multiple_suspension_points(self, expect_output):
        """Task with multiple task calls suspends at each."""
        expect_output('''
task step1() -> int
    return 1
~

task step2() -> int
    return 2
~

task step3() -> int
    return 3
~

task pipeline() -> int
    a := step1()
    b := step2()
    c := step3()
    return a + b + c
~

func main() -> int
    print(pipeline())
    return 0
~
''', "6\n")

    def test_locals_preserved_across_suspension(self, expect_output):
        """Variables defined before suspension are available after."""
        expect_output('''
task get_value() -> int
    return 42
~

task uses_locals() -> int
    x = 10
    y := get_value()
    z = 20
    return x + y + z
~

func main() -> int
    print(uses_locals())
    return 0
~
''', "72\n")

    def test_conditional_suspension_true_branch(self, expect_output):
        """Suspension in if branch (true case)."""
        expect_output('''
task maybe_suspend(flag: bool) -> int
    return 100
~

task conditional(flag: bool) -> int
    if flag
        x := maybe_suspend(flag)
        return x
    else
        return 0
    ~
~

func main() -> int
    print(conditional(true))
    return 0
~
''', "100\n")

    def test_conditional_suspension_false_branch(self, expect_output):
        """Suspension in if branch (false case, no suspension)."""
        expect_output('''
task maybe_suspend(flag: bool) -> int
    return 100
~

task conditional(flag: bool) -> int
    if flag
        x := maybe_suspend(flag)
        return x
    else
        return 0
    ~
~

func main() -> int
    print(conditional(false))
    return 0
~
''', "0\n")

    def test_both_branches_suspend(self, expect_output):
        """Suspension in both branches."""
        expect_output('''
task branch_a() -> int
    return 1
~

task branch_b() -> int
    return 2
~

task both_branches(flag: bool) -> int
    if flag
        x := branch_a()
        return x
    else
        y := branch_b()
        return y
    ~
~

func main() -> int
    print(both_branches(true))
    print(both_branches(false))
    return 0
~
''', "1\n2\n")

    def test_loop_with_suspension(self, expect_output):
        """Suspension inside a loop."""
        expect_output('''
task process_item(x: int) -> int
    return x * 2
~

task loop_with_suspend() -> int
    total = 0
    for i in 0..3
        result := process_item(i)
        total = total + result
    ~
    return total
~

func main() -> int
    print(loop_with_suspend())
    return 0
~
''', "6\n")

    def test_nested_task_calls(self, expect_output):
        """Tasks calling tasks calling tasks."""
        expect_output('''
task level3() -> int
    return 1
~

task level2() -> int
    x := level3()
    return x + 1
~

task level1() -> int
    x := level2()
    return x + 1
~

func main() -> int
    print(level1())
    return 0
~
''', "3\n")


class TestTaskFrameGC:
    """Tests that task frames are properly traced by GC."""

    def test_gc_during_task_execution(self, expect_output):
        """GC can run while tasks are suspended without corruption."""
        expect_output('''
task inner_task() -> int
    gc()
    return 10
~

task allocates() -> int
    x = [1, 2, 3, 4, 5]
    y := inner_task()
    gc()
    return x.len() + y
~

func main() -> int
    print(allocates())
    return 0
~
''', "15\n")

    def test_frame_survives_gc(self, expect_output):
        """Frame data survives garbage collection."""
        expect_output('''
task get_number() -> int
    gc()
    gc()
    return 42
~

task holder() -> int
    big_list = [1, 2, 3, 4, 5, 6, 7, 8, 9, 10]
    value := get_number()
    gc()
    return big_list.len() + value
~

func main() -> int
    print(holder())
    return 0
~
''', "52\n")


class TestTaskInvariants:
    """Tests for state machine transformation invariants."""

    def test_state_starts_at_zero(self, expect_output):
        """Initial state is always 0."""
        # This is an internal invariant - test via behavior
        expect_output('''
task task_one() -> int
    return 1
~

task task_two() -> int
    return 2
~

task ordered() -> int
    a := task_one()
    b := task_two()
    return a * 10 + b
~

func main() -> int
    print(ordered())
    return 0
~
''', "12\n")

    def test_suspension_points_are_task_calls_only(self, expect_output):
        """Formula calls do not create suspension points."""
        expect_output('''
formula f1() -> int
    return 1
~

formula f2() -> int
    return 2
~

formula f3() -> int
    return 3
~

task no_suspend() -> int
    a = f1()
    b = f2()
    c = f3()
    return a + b + c
~

func main() -> int
    print(no_suspend())
    return 0
~
''', "6\n")

    def test_task_can_call_formula(self, expect_output):
        """Task can call formula (lighter kind)."""
        expect_output('''
formula pure_compute(x: int) -> int
    return x * x
~

task wrapper(x: int) -> int
    return pure_compute(x)
~

func main() -> int
    print(wrapper(7))
    return 0
~
''', "49\n")

    def test_func_can_call_task(self, expect_output):
        """Func can call task."""
        expect_output('''
task compute(x: int) -> int
    return x + 100
~

func main() -> int
    result := compute(5)
    print(result)
    return 0
~
''', "105\n")
