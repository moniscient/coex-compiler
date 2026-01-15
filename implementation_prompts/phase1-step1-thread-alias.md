# Implementation Prompt: Phase 1, Step 1
# Alias Current Task to Thread, Stub New Task

## Objective

Rename the current pthread-based `task` implementation to `thread`, adding `thread` as a keyword. Then stub out the `task` keyword for the new lightweight coroutine implementation.

## Prerequisites

- Read and understand `CLAUDE.md` for project conventions
- Read and understand `coex-task-system-spec.md` for the overall architecture
- Familiarize yourself with the current `task` implementation in `codegen.py`

## Test-First Methodology

**Write all tests before implementing.** Tests define the expected behavior and serve as documentation of invariants.

## Invariants to Test

These invariants must hold. Write tests that fail if violated:

### Invariant 1: Thread Keyword Exists and Works Like Old Task

```coex
# test_thread_basic.coex
# The 'thread' keyword should work exactly like the old 'task' keyword

thread compute(x: int) -> int
    return x * 2
~

func main() -> int
    result = compute(21)
    print(result)
    return 0
~
```
Expected output: `42`

### Invariant 2: Existing Task Tests Pass with Thread

All existing tests in `tests/` that use `task` should have parallel versions using `thread` that produce identical results. Create a test that verifies thread behaves identically to the old task semantics.

### Invariant 3: Task Keyword Parses But Is Stubbed

```coex
# test_task_stub.coex
# The 'task' keyword should parse but produce a clear error or stub behavior

task placeholder(x: int) -> int
    return x
~

func main() -> int
    return 0
~
```
This should either:
- Compile with a warning that task is not yet implemented
- Produce a compile error with a clear message about task being under development

### Invariant 4: Function Kind Hierarchy Enforced

```coex
# test_hierarchy_thread_calls_formula.coex
# Thread can call formula - should work

formula pure_add(a: int, b: int) -> int
    return a + b
~

thread worker() -> int
    return pure_add(1, 2)
~

func main() -> int
    result = worker()
    print(result)
    return 0
~
```
Expected output: `3`

```coex
# test_hierarchy_formula_cannot_call_thread.coex
# Formula cannot call thread - should fail at compile time

thread heavy_work() -> int
    return 42
~

formula bad_formula() -> int
    return heavy_work()  # ERROR: formula cannot call thread
~

func main() -> int
    return 0
~
```
Expected: Compile error indicating formula cannot call thread.

### Invariant 5: Extern Callable Only from Thread/Func

```coex
# test_extern_from_func.coex
# Func can call extern - should work

extern puts(s: string) -> int ~

func main() -> int
    puts("hello")
    return 0
~
```
Expected output: `hello`

```coex
# test_extern_from_thread.coex
# Thread can call extern - should work

extern puts(s: string) -> int ~

thread worker() -> int
    puts("from thread")
    return 0
~

func main() -> int
    worker()
    return 0
~
```
Expected output: `from thread`

## Implementation Steps

### Step 1: Update Lexer

In `Coex.g4` or `CoexLexer.g4`:

1. Add `THREAD` keyword: `THREAD : 'thread' ;`
2. Ensure `TASK` keyword remains: `TASK : 'task' ;`

### Step 2: Update Parser

In `CoexParser.g4` or the parser section of `Coex.g4`:

1. Add `THREAD` to `functionKind` rule:
   ```antlr
   functionKind
       : FORMULA
       | TASK
       | FUNC
       | THREAD
       | EXTERN
       ;
   ```

### Step 3: Regenerate Parser

```bash
antlr -Dlanguage=Python3 -visitor Coex.g4
```

### Step 4: Update AST Nodes

In `ast_nodes.py`:

1. Add `THREAD` to the `FunctionKind` enum or equivalent
2. Ensure AST builder recognizes the new keyword

### Step 5: Update AST Builder

In `ast_builder.py`:

1. Handle `THREAD` in the function kind visitor
2. Map it to the same internal representation as current `TASK`

### Step 6: Update Code Generator

In `codegen.py`:

1. Find all places that handle `TASK` function kind
2. Add `THREAD` as an alias that uses the same code path
3. For `TASK`, add a stub that either:
   - Emits a warning and falls through to thread behavior (temporary)
   - Raises a "not yet implemented" error

### Step 7: Update Function Kind Hierarchy Checking

In the appropriate module (likely `codegen.py` or a new `function_kinds.py`):

1. Implement `check_call(caller_kind, callee_kind)` that enforces:
   ```
   formula → calls: formula
   task    → calls: formula, task
   thread  → calls: formula, task, thread
   func    → calls: formula, task, thread, func
   ```

2. Implement `check_extern_call(caller_kind)` that only allows thread/func

3. Add compile-time errors for hierarchy violations

## Test Files to Create

Create these test files in `tests/test_thread_keyword.py`:

```python
import pytest

class TestThreadKeyword:
    """Tests for the new 'thread' keyword (alias of old task behavior)"""
    
    def test_thread_basic_computation(self, expect_output):
        """Thread executes and returns value"""
        expect_output('''
thread compute(x: int) -> int
    return x * 2
~

func main() -> int
    result = compute(21)
    print(result)
    return 0
~
''', "42\n")

    def test_thread_calls_formula(self, expect_output):
        """Thread can call formula (lighter kind)"""
        expect_output('''
formula add(a: int, b: int) -> int
    return a + b
~

thread worker() -> int
    return add(10, 20)
~

func main() -> int
    print(worker())
    return 0
~
''', "30\n")

    def test_thread_calls_thread(self, expect_output):
        """Thread can call another thread (same kind)"""
        expect_output('''
thread inner() -> int
    return 5
~

thread outer() -> int
    return inner() * 2
~

func main() -> int
    print(outer())
    return 0
~
''', "10\n")

    def test_func_calls_thread(self, expect_output):
        """Func can call thread (lighter kind)"""
        expect_output('''
thread compute() -> int
    return 42
~

func main() -> int
    print(compute())
    return 0
~
''', "42\n")


class TestFunctionKindHierarchy:
    """Tests that function kind calling hierarchy is enforced"""
    
    def test_formula_cannot_call_thread(self, compile_coex):
        """Formula calling thread should be compile error"""
        with pytest.raises(Exception) as exc_info:
            compile_coex('''
thread heavy() -> int
    return 1
~

formula bad() -> int
    return heavy()
~

func main() -> int
    return bad()
~
''')
        assert "formula" in str(exc_info.value).lower() or "cannot call" in str(exc_info.value).lower()

    def test_formula_cannot_call_func(self, compile_coex):
        """Formula calling func should be compile error"""
        with pytest.raises(Exception) as exc_info:
            compile_coex('''
func impure() -> int
    print(1)
    return 1
~

formula bad() -> int
    return impure()
~

func main() -> int
    return bad()
~
''')
        assert "formula" in str(exc_info.value).lower() or "cannot call" in str(exc_info.value).lower()

    def test_task_cannot_call_thread(self, compile_coex):
        """Task calling thread should be compile error (when task is implemented)"""
        # This test documents the future invariant
        # For now, if task is stubbed to thread, this may pass
        # Mark as xfail until task is properly implemented
        pytest.skip("Task not yet differentiated from thread")

    def test_task_cannot_call_extern(self, compile_coex):
        """Task calling extern should be compile error"""
        # This test documents the future invariant
        pytest.skip("Task not yet differentiated from thread")


class TestExternCalling:
    """Tests that extern is only callable from thread/func"""
    
    def test_func_calls_extern(self, expect_output):
        """Func can call extern"""
        expect_output('''
extern abs(x: int) -> int ~

func main() -> int
    print(abs(-42))
    return 0
~
''', "42\n")

    def test_formula_cannot_call_extern(self, compile_coex):
        """Formula calling extern should be compile error"""
        with pytest.raises(Exception) as exc_info:
            compile_coex('''
extern abs(x: int) -> int ~

formula bad(x: int) -> int
    return abs(x)
~

func main() -> int
    return bad(-1)
~
''')
        # Should indicate formula cannot call extern
        error_msg = str(exc_info.value).lower()
        assert "formula" in error_msg or "extern" in error_msg or "cannot call" in error_msg
```

## Verification

After implementation, run:

```bash
python3 -m pytest tests/test_thread_keyword.py -v
```

All tests should pass except those marked with `pytest.skip()` (which document future behavior).

## Success Criteria

1. `thread` keyword works identically to old `task` behavior
2. All existing tests still pass
3. Function kind hierarchy is enforced at compile time
4. `task` keyword parses but is clearly stubbed/not-yet-implemented
5. New tests in `test_thread_keyword.py` pass

## Notes

- This is a refactoring step — behavior should not change for existing code
- The goal is to free up the `task` keyword for the new lightweight implementation
- Maintain backward compatibility: if users have code using `task`, it should either still work (mapped to thread) or give a clear migration message
