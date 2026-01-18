# Implementation Prompt: Phase 1, Step 2
# State Machine Transformation for Tasks

## Objective

Implement the compiler pass that transforms task bodies into stackless state machines. This is the core of the coroutine implementation.

## Prerequisites

- Phase 1, Step 1 complete (thread keyword working, task stubbed)
- Read `coex-task-system-spec.md` sections 4 (Coroutine Implementation) and 5 (Task State)
- Understand the existing AST structure in `ast_nodes.py`
- Understand code generation patterns in `codegen.py`

## Test-First Methodology

**Write all tests before implementing.** The state machine transformation is complex; tests define correctness.

## Invariants to Test

### Invariant 1: Simple Task Generates Valid Frame Type

A task with no suspension points still generates a frame (with just state and arguments):

```coex
# A task that only calls formulas has no suspension points
# but should still be transformed for consistency

formula double(x: int) -> int
    return x * 2
~

task simple(x: int) -> int
    y = double(x)
    return y
~

func main() -> int
    result = simple(21)
    print(result)
    return 0
~
```
Expected output: `42`

### Invariant 2: Task with One Suspension Point

```coex
task inner() -> int
    return 10
~

task outer(x: int) -> int
    y = inner()        # suspension point 1
    return x + y
~

func main() -> int
    result = outer(5)
    print(result)
    return 0
~
```
Expected output: `15`

The frame for `outer` should contain:
- `state: int` (0 = initial, 1 = after inner() completes)
- `x: int` (argument, needed after suspension)
- `y: int?` (local, populated after suspension point 1)

### Invariant 3: Task with Multiple Sequential Suspension Points

```coex
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
    a = step1()    # suspension point 1
    b = step2()    # suspension point 2
    c = step3()    # suspension point 3
    return a + b + c
~

func main() -> int
    print(pipeline())
    return 0
~
```
Expected output: `6`

### Invariant 4: Locals Across Suspension Points Are Preserved

```coex
task get_value() -> int
    return 42
~

task uses_locals() -> int
    x = 10                 # before suspension
    y = get_value()        # suspension point
    z = 20                 # after suspension
    return x + y + z       # x must survive suspension
~

func main() -> int
    print(uses_locals())
    return 0
~
```
Expected output: `72`

### Invariant 5: Only Necessary Locals Are Hoisted

```coex
task get_value() -> int
    return 5
~

task selective_hoist() -> int
    a = 1                  # used before suspension only
    b = a + 1              # used before suspension only
    c = 10                 # used after suspension - MUST hoist
    x = get_value()        # suspension point
    d = 3                  # defined after suspension - don't hoist
    return c + x + d       # c survives, d is new
~

func main() -> int
    print(selective_hoist())
    return 0
~
```
Expected output: `18`

### Invariant 6: Control Flow - If/Else with Suspension in One Branch

```coex
task maybe_suspend(flag: bool) -> int
    return 100
~

task conditional(flag: bool) -> int
    if flag
        x = maybe_suspend(flag)    # suspension point
        return x
    else
        return 0
    ~
~

func main() -> int
    print(conditional(true))
    print(conditional(false))
    return 0
~
```
Expected output:
```
100
0
```

### Invariant 7: Control Flow - If/Else with Suspension in Both Branches

```coex
task branch_a() -> int
    return 1
~

task branch_b() -> int
    return 2
~

task both_branches(flag: bool) -> int
    if flag
        x = branch_a()    # suspension point 1
        return x
    else
        y = branch_b()    # suspension point 2
        return y
    ~
~

func main() -> int
    print(both_branches(true))
    print(both_branches(false))
    return 0
~
```
Expected output:
```
1
2
```

### Invariant 8: Loop with Suspension Point

```coex
task process_item(x: int) -> int
    return x * 2
~

task loop_with_suspend() -> int
    total = 0
    for i in 0..3
        result = process_item(i)    # suspension point inside loop
        total = total + result
    ~
    return total
~

func main() -> int
    print(loop_with_suspend())
    return 0
~
```
Expected output: `6` (0*2 + 1*2 + 2*2 = 0 + 2 + 4 = 6)

### Invariant 9: Nested Task Calls

```coex
task level3() -> int
    return 1
~

task level2() -> int
    x = level3()
    return x + 1
~

task level1() -> int
    x = level2()
    return x + 1
~

func main() -> int
    print(level1())
    return 0
~
```
Expected output: `3`

### Invariant 10: Frame Is Immutable Heap Value

The generated frame must be traceable by GC. This is tested implicitly by:
- Running with GC enabled
- Forcing GC during task execution
- Verifying no crashes or corruption

```coex
task allocates() -> int
    x = [1, 2, 3, 4, 5]    # heap allocation
    y = inner_task()        # suspension point
    gc()                    # force GC while frame exists
    return x.len() + y
~

task inner_task() -> int
    gc()                    # force GC
    return 10
~

func main() -> int
    print(allocates())
    return 0
~
```
Expected output: `15`

## Implementation Steps

### Step 1: Create Suspension Point Analysis Pass

Create `task_analysis.py`:

```python
"""
Analyze task bodies to identify suspension points and locals that span them.
"""

from dataclasses import dataclass
from typing import List, Set, Dict
from ast_nodes import *

@dataclass
class SuspensionPoint:
    """A point where a task may suspend"""
    node: ASTNode           # The AST node (task call, channel op, etc.)
    state_id: int           # Unique state number
    live_before: Set[str]   # Variables live before this point
    live_after: Set[str]    # Variables needed after this point

@dataclass 
class TaskAnalysis:
    """Result of analyzing a task body"""
    function_name: str
    parameters: List[Parameter]
    return_type: Type
    suspension_points: List[SuspensionPoint]
    hoisted_locals: Dict[str, Type]  # Locals that must be in frame
    
def analyze_task(func: FunctionDecl) -> TaskAnalysis:
    """
    Analyze a task to find suspension points and determine frame layout.
    """
    # Implementation here
    pass

def find_suspension_points(body: List[Statement]) -> List[SuspensionPoint]:
    """
    Walk AST to find all suspension points (task calls, channel ops).
    """
    pass

def compute_live_variables(body: List[Statement], suspension_points: List[SuspensionPoint]) -> Dict[str, Set[str]]:
    """
    Compute which variables are live across each suspension point.
    """
    pass
```

### Step 2: Create Frame Type Generator

Add to `task_analysis.py` or new `frame_generator.py`:

```python
@dataclass
class FrameField:
    name: str
    type: Type
    optional: bool  # True if populated after some suspension point

@dataclass
class FrameType:
    name: str                    # e.g., "ProcessFrame"
    fields: List[FrameField]
    
def generate_frame_type(analysis: TaskAnalysis) -> FrameType:
    """
    Generate the frame type for a task based on analysis.
    
    Frame always contains:
    - state: int (state machine position)
    - All parameters (needed for restart)
    - Hoisted locals (those that span suspension points)
    """
    fields = [
        FrameField("state", IntType(), optional=False)
    ]
    
    # Add parameters
    for param in analysis.parameters:
        fields.append(FrameField(param.name, param.type, optional=False))
    
    # Add hoisted locals (as optionals)
    for name, type in analysis.hoisted_locals.items():
        fields.append(FrameField(name, type, optional=True))
    
    return FrameType(
        name=f"{analysis.function_name}Frame",
        fields=fields
    )
```

### Step 3: Create Step Function Generator

```python
@dataclass
class StateCase:
    state_id: int
    code: List[Statement]        # Code to execute in this state
    next_action: TaskResult      # What to return (Spawn, Done, etc.)

def generate_step_function(analysis: TaskAnalysis, frame_type: FrameType) -> FunctionDecl:
    """
    Generate the step function that implements the state machine.
    
    func {name}_step(frame: {FrameType}, resolved: Value?) -> TaskResult<T>
        match frame.state
            case 0: ...
            case 1: ...
        ~
    ~
    """
    pass

def partition_body(body: List[Statement], suspension_points: List[SuspensionPoint]) -> List[StateCase]:
    """
    Split the task body into segments between suspension points.
    Each segment becomes a case in the state machine.
    """
    pass
```

### Step 4: Integrate with Code Generator

In `codegen.py`:

1. Detect task function kind
2. Run task analysis
3. Generate frame type (as internal struct)
4. Generate step function
5. Generate entry point that creates initial frame

```python
def _generate_task_function(self, node: FunctionDecl):
    """Generate code for a task (stackless coroutine)"""
    
    # Analyze task body
    analysis = analyze_task(node)
    
    # Generate frame type
    frame_type = generate_frame_type(analysis)
    self._generate_frame_struct(frame_type)
    
    # Generate step function  
    step_func = generate_step_function(analysis, frame_type)
    self._generate_function(step_func)
    
    # Generate entry point
    self._generate_task_entry(node, frame_type, step_func)
```

### Step 5: Handle Variable Name Preservation

When hoisting locals to frame:
- Use original names: `filtered`, `doubled`, `sum`
- For name conflicts (same name in different scopes), mangle: `x__0`, `x__1`

```python
def mangle_name(name: str, scope_id: int) -> str:
    if scope_id == 0:
        return name
    return f"{name}__{scope_id}"
```

## Test Files to Create

Create `tests/test_task_state_machine.py`:

```python
import pytest

class TestTaskStateMachine:
    """Tests for task state machine transformation"""
    
    def test_simple_task_no_suspension(self, expect_output):
        """Task with only formula calls has no suspension points"""
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
        """Task with one task call suspends once"""
        expect_output('''
task inner() -> int
    return 10
~

task outer(x: int) -> int
    y = inner()
    return x + y
~

func main() -> int
    print(outer(5))
    return 0
~
''', "15\n")

    def test_multiple_suspension_points(self, expect_output):
        """Task with multiple task calls suspends at each"""
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
    a = step1()
    b = step2()
    c = step3()
    return a + b + c
~

func main() -> int
    print(pipeline())
    return 0
~
''', "6\n")

    def test_locals_preserved_across_suspension(self, expect_output):
        """Variables defined before suspension are available after"""
        expect_output('''
task get_value() -> int
    return 42
~

task uses_locals() -> int
    x = 10
    y = get_value()
    z = 20
    return x + y + z
~

func main() -> int
    print(uses_locals())
    return 0
~
''', "72\n")

    def test_conditional_suspension_true_branch(self, expect_output):
        """Suspension in if branch (true case)"""
        expect_output('''
task maybe_suspend(flag: bool) -> int
    return 100
~

task conditional(flag: bool) -> int
    if flag
        x = maybe_suspend(flag)
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
        """Suspension in if branch (false case, no suspension)"""
        expect_output('''
task maybe_suspend(flag: bool) -> int
    return 100
~

task conditional(flag: bool) -> int
    if flag
        x = maybe_suspend(flag)
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
        """Suspension in both branches"""
        expect_output('''
task branch_a() -> int
    return 1
~

task branch_b() -> int
    return 2
~

task both_branches(flag: bool) -> int
    if flag
        x = branch_a()
        return x
    else
        y = branch_b()
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
        """Suspension inside a loop"""
        expect_output('''
task process_item(x: int) -> int
    return x * 2
~

task loop_with_suspend() -> int
    total = 0
    for i in 0..3
        result = process_item(i)
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
        """Tasks calling tasks calling tasks"""
        expect_output('''
task level3() -> int
    return 1
~

task level2() -> int
    x = level3()
    return x + 1
~

task level1() -> int
    x = level2()
    return x + 1
~

func main() -> int
    print(level1())
    return 0
~
''', "3\n")


class TestTaskFrameGC:
    """Tests that task frames are properly traced by GC"""
    
    def test_gc_during_task_execution(self, expect_output):
        """GC can run while tasks are suspended without corruption"""
        expect_output('''
task inner_task() -> int
    gc()
    return 10
~

task allocates() -> int
    x = [1, 2, 3, 4, 5]
    y = inner_task()
    gc()
    return x.len() + y
~

func main() -> int
    print(allocates())
    return 0
~
''', "15\n")

    def test_frame_survives_gc(self, expect_output):
        """Frame data survives garbage collection"""
        expect_output('''
task get_number() -> int
    gc()
    gc()
    return 42
~

task holder() -> int
    big_list = [1, 2, 3, 4, 5, 6, 7, 8, 9, 10]
    value = get_number()
    gc()
    return big_list.len() + value
~

func main() -> int
    print(holder())
    return 0
~
''', "52\n")


class TestTaskInvariants:
    """Tests for state machine transformation invariants"""
    
    def test_state_starts_at_zero(self, expect_output):
        """Initial state is always 0"""
        # This is an internal invariant - test via behavior
        expect_output('''
task first() -> int
    return 1
~

task second() -> int
    return 2
~

task ordered() -> int
    a = first()
    b = second()
    return a * 10 + b
~

func main() -> int
    print(ordered())
    return 0
~
''', "12\n")

    def test_suspension_points_are_task_calls_only(self, expect_output):
        """Formula calls do not create suspension points"""
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
```

## Verification

After implementation, run:

```bash
python3 -m pytest tests/test_task_state_machine.py -v
```

## Success Criteria

1. All tests pass
2. Task bodies are correctly transformed into state machines
3. Locals that span suspension points are hoisted to frame
4. Frame is properly allocated on heap and traced by GC
5. Original variable names are preserved (with mangling for conflicts)
6. Control flow (if/else, loops) with suspension points works correctly

## Notes

- This step does NOT implement the scheduler — tasks run synchronously for now
- The step function is generated but called directly, not via work-stealing
- Focus on correctness of the transformation; scheduling comes in Step 3
- The frame type is internal; users never see it directly
