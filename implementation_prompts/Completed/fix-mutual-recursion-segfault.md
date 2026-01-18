# Fix Mutual Recursion Segfault in Task Coroutines

## Problem Statement

The test `tests/test_task_to_task.py::TestRecursion::test_mutual_recursion` crashes with a segmentation fault when two task functions call each other recursively.

## Reproduction

```coex
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
```

Expected output: `1` (since 10 is even)
Actual result: Segmentation fault (exit code 139)

## Compile and Run

```bash
python3 coexc.py /tmp/test_mutual.coex -o /tmp/test_mutual
/tmp/test_mutual
```

## Background

Task functions in Coex are compiled into stackless coroutines using a state machine transformation:

1. Each task gets a "frame" struct containing:
   - `__state`: Current state in the state machine
   - `__resolved`: Value from completed child task
   - `__waiter`: Parent task pointer
   - Parameters and hoisted local variables

2. Each task gets a "step function" that:
   - Takes (frame_ptr, resolved_value, out_result)
   - Executes one step based on current state
   - Returns either TASK_RESULT_DONE or TASK_RESULT_SPAWN

3. The scheduler runs tasks by calling their step functions

## Key Files

- `task_transform.py` - Transforms task functions into state machines
- `task_analysis.py` - Finds suspension points (task calls) in task bodies
- `runtime/coex_scheduler.c` - Work-stealing scheduler that executes tasks
- `runtime/coex_scheduler.h` - Scheduler data structures

## Investigation Steps

1. **Generate LLVM IR** to see what's being compiled:
   ```bash
   python3 coexc.py /tmp/test_mutual.coex --emit-ir > /tmp/mutual.ll
   ```
   Look for `is_even_step` and `is_odd_step` functions.

2. **Check frame layout** - Add debug output in `task_transform.py`:
   - In `_build_task_frame_info()`, print field_indices for each task
   - Verify both `is_even` and `is_odd` have correct frame structures

3. **Check step function generation** - The mutual recursion means:
   - `is_even` calls `is_odd` (suspension point)
   - `is_odd` calls `is_even` (suspension point)
   - Both have if/else with early return in one branch

4. **Add scheduler debug output**:
   ```c
   // In coex_scheduler_run_task():
   fprintf(stderr, "DEBUG: task=%p step_fn=%p frame=%p\n",
           task, task->step_fn, task->frame);
   ```

5. **Check for null pointers** - The segfault might be:
   - Null step_fn pointer
   - Null or invalid frame pointer
   - Stack overflow from deep recursion (10 levels shouldn't cause this)

## Likely Causes

### 1. Forward Reference Issue
When `is_even` is compiled, `is_odd` may not have its step function generated yet (and vice versa). Check if:
- Step function pointers are resolved correctly
- Frame info for the callee task is available when spawning

### 2. Conditional Suspension Handling
Both tasks have:
```coex
if n == 0
    return <value>  # No suspension
~
return other_task(n - 1)  # Suspension point
```

The state machine must handle:
- State 0: Check condition, either return early OR spawn child
- State 1: Resume after child completes, return its result

Check `_generate_conditional_state_0()` in `task_transform.py`.

### 3. Return Type Handling
Both tasks return `bool`, but the scheduler uses `int64_t` for resolved values. Verify:
- Bool values are properly widened to i64
- The step function returns the correct type in TaskResult

### 4. Task Registration Order
In `codegen/functions.py`, tasks are registered via `register_task_function()`.
With mutual recursion, ensure both tasks are registered before either is generated.

## Testing the Fix

```bash
# Run the specific test
python3 -m pytest tests/test_task_to_task.py::TestRecursion::test_mutual_recursion -v

# Run all recursion tests
python3 -m pytest tests/test_task_to_task.py::TestRecursion -v

# Run all task tests
python3 -m pytest tests/test_task_to_task.py -v
```

## Related Code Patterns

For reference, simple recursion works (single task calling itself):
```coex
task factorial(n: int) -> int
    if n <= 1
        return 1
    ~
    return n * factorial(n - 1)
~
```

The difference with mutual recursion is the cross-reference between two separate task functions.

## Success Criteria

1. `test_mutual_recursion` passes
2. No regressions in other task tests
3. Deep mutual recursion works (test with larger values like `is_even(100)`)
