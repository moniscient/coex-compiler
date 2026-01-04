# Session 3: The `:=` (Eager Assign) Operator

## Context

This is Session 3 of 10 implementing the optimized memory model for Coex.

**Completed:**
- Session 1: Array has COW with atomic refcount
- Session 2: String has COW with atomic refcount

**This Session:**
- Implement the `:=` operator for eager/deterministic assignment

**Coming Next:**
- Session 4: Persistent Vector structure for List

### The Two Assignment Operators

Coex now has two assignment operators with distinct semantics:

| Operator | Name | Behavior | Cost |
|----------|------|----------|------|
| `=` | Lazy assign | Share buffer, bump refcount | O(1) assign, maybe O(n) on later mutation |
| `:=` | Eager assign | Move if possible, copy if necessary | O(1) or O(n) now, never later |

### Why `:=` Matters

With COW (`=`), the cost of copying is unpredictable - it happens whenever you first mutate a shared value:

```coex
a = huge_data      # refcount = 1
b = a              # refcount = 2, O(1)
c = a              # refcount = 3, O(1)
# ... much later ...
b.append(x)        # SURPRISE! O(n) copy happens here
```

With `:=`, the cost is deterministic - paid upfront:

```coex
a = huge_data      # refcount = 1
b := a             # Move: refcount stays 1, a is invalidated
b.append(x)        # O(1), guaranteed no copy
b.append(y)        # O(1), guaranteed no copy
```

### `:=` Semantics: "Guarantee Sole Ownership"

The `:=` operator guarantees the destination has sole ownership (refcount = 1):
- **If source refcount == 1**: Move (transfer ownership, invalidate source)
- **If source refcount > 1**: Copy now (create independent copy with refcount 1)

Either way, after `:=`, the destination owns the data exclusively. All future mutations are in-place.

## Goals for This Session

1. Write failing tests for `:=` operator
2. Add `:=` to the grammar
3. Add AST node for move/eager assignment
4. Implement codegen for `:=`
5. Implement compile-time use-after-move detection
6. Make all tests pass

## Test-Driven Development

Write these tests FIRST in `tests/test_move_operator.py`. They should FAIL initially.

```python
import pytest

class TestMoveOperator:
    """Test the := (eager assign / move) operator."""

    def test_move_basic(self, expect_output):
        """:= transfers ownership, original can't be used."""
        expect_output('''
func main() -> int
    a: Array<int> = [1, 2, 3]
    b := a
    print(b.get(0))
    print(b.len())
    return 0
~
''', "1\n3\n")

    def test_move_then_mutate_no_copy(self, expect_output):
        """After move, mutations are always in-place."""
        expect_output('''
func main() -> int
    a: Array<int> = [1, 2, 3]
    b := a
    b.set(0, 10)
    b.set(1, 20)
    b.append(4)
    print(b.get(0))
    print(b.get(1))
    print(b.len())
    return 0
~
''', "10\n20\n4\n")

    def test_move_string(self, expect_output):
        """:= works with strings."""
        expect_output('''
func main() -> int
    a = "hello"
    b := a
    b = b + " world"
    print(b)
    return 0
~
''', "hello world\n")

    def test_eager_copy_when_shared(self, expect_output):
        """When source is shared, := copies immediately."""
        expect_output('''
func main() -> int
    a: Array<int> = [1, 2, 3]
    b = a
    c := a
    c.set(0, 99)
    print(a.get(0))
    print(b.get(0))
    print(c.get(0))
    return 0
~
''', "1\n1\n99\n")

    def test_move_in_function(self, expect_output):
        """:= works inside functions."""
        expect_output('''
func process(data: Array<int>) -> int
    local := data
    local.set(0, 100)
    return local.get(0)
~

func main() -> int
    arr: Array<int> = [1, 2, 3]
    result = process(arr)
    print(result)
    print(arr.get(0))
    return 0
~
''', "100\n1\n")

    def test_move_var_declaration(self, expect_output):
        """var declaration with := ."""
        expect_output('''
func main() -> int
    a: Array<int> = [1, 2, 3]
    var b := a
    b.set(0, 10)
    b := [4, 5, 6]
    print(b.get(0))
    return 0
~
''', "4\n")

    def test_move_chain(self, expect_output):
        """Chain of moves."""
        expect_output('''
func main() -> int
    a: Array<int> = [1, 2, 3]
    b := a
    c := b
    d := c
    d.set(0, 99)
    print(d.get(0))
    return 0
~
''', "99\n")

    def test_lazy_vs_eager_comparison(self, expect_output):
        """Compare = and := behavior."""
        expect_output('''
func main() -> int
    a1: Array<int> = [1, 2, 3]
    b1 = a1
    b1.set(0, 10)
    print(a1.get(0))

    a2: Array<int> = [1, 2, 3]
    b2 := a2
    b2.set(0, 10)
    print(b2.get(0))
    return 0
~
''', "1\n10\n")

class TestUseAfterMove:
    """Test compile-time detection of use-after-move errors."""

    def test_use_after_move_error(self, compile_coex):
        """Using a moved variable should be a compile error."""
        result = compile_coex('''
func main() -> int
    a: Array<int> = [1, 2, 3]
    b := a
    print(a.get(0))
    return 0
~
''')
        assert result.returncode != 0
        assert "moved" in result.stderr.lower() or "use after move" in result.stderr.lower()

    def test_use_after_move_in_expression(self, compile_coex):
        """Using moved variable in expression should error."""
        result = compile_coex('''
func main() -> int
    a: Array<int> = [1, 2, 3]
    b := a
    c = a.len()
    return 0
~
''')
        assert result.returncode != 0
        assert "moved" in result.stderr.lower() or "use after move" in result.stderr.lower()

    def test_move_then_reassign_ok(self, compile_coex, expect_output):
        """Reassigning a moved variable should be allowed."""
        expect_output('''
func main() -> int
    a: Array<int> = [1, 2, 3]
    b := a
    a = [4, 5, 6]
    print(a.get(0))
    print(b.get(0))
    return 0
~
''', "4\n1\n")

    def test_conditional_move_error(self, compile_coex):
        """Move in one branch, use in another should error."""
        result = compile_coex('''
func main() -> int
    a: Array<int> = [1, 2, 3]
    if true
        b := a
    ~
    print(a.get(0))
    return 0
~
''')
        assert result.returncode != 0
```

## Implementation Steps

### Step 1: Add `:=` to Grammar

In `Coex.g4`, add the `:=` operator:

```antlr
// In assignment statement or expression
assignmentStmt
    : target '=' expression
    | target ':=' expression   // NEW: move/eager assign
    ;

// Or if assignment is an expression:
assignmentExpr
    : target ('=' | ':=') expression
    ;
```

Regenerate parser:
```bash
antlr -Dlanguage=Python3 -visitor Coex.g4
```

### Step 2: Add AST Node

In `ast_nodes.py`, modify or add:

```python
@dataclass
class Assignment:
    target: Expression
    value: Expression
    is_move: bool = False  # True for :=, False for =

# Or add separate node:
@dataclass
class MoveAssignment:
    target: Expression
    value: Expression
```

### Step 3: Update AST Builder

In `ast_builder.py`, handle the new syntax:

```python
def visitAssignmentStmt(self, ctx):
    target = self.visit(ctx.target())
    value = self.visit(ctx.expression())
    is_move = ctx.MOVE_ASSIGN() is not None  # or check for ':='
    return Assignment(target, value, is_move=is_move)
```

### Step 4: Track Moved Variables

Add tracking in codegen to detect use-after-move:

```python
class CodeGenerator:
    def __init__(self, ...):
        # ...
        self.moved_variables: Set[str] = set()  # Variables that have been moved from

    def _check_not_moved(self, var_name: str, location):
        """Raise error if variable has been moved."""
        if var_name in self.moved_variables:
            raise CompileError(f"Use of moved variable '{var_name}'", location)

    def _mark_moved(self, var_name: str):
        """Mark variable as moved (invalid for further use)."""
        self.moved_variables.add(var_name)

    def _unmark_moved(self, var_name: str):
        """Variable reassigned, no longer moved."""
        self.moved_variables.discard(var_name)
```

### Step 5: Implement `:=` Codegen

For move assignment:

```python
def _generate_move_assignment(self, node):
    target_name = node.target.name
    source_value = self._generate_expression(node.value)
    source_name = node.value.name if isinstance(node.value, Identifier) else None

    # Get refcount of source
    refcount_ptr = self._get_refcount_ptr(source_value)
    refcount = builder.load(refcount_ptr)

    # Check if sole owner
    is_sole = builder.icmp_unsigned('==', refcount, ir.Constant(ir.IntType(64), 1))

    with builder.if_else(is_sole) as (then, otherwise):
        with then:
            # Move: just transfer pointer, don't touch refcount
            # Mark source as moved
            result_move = source_value
        with otherwise:
            # Copy: create new value with refcount 1
            # Decref source (we're taking our share)
            result_copy = self._deep_copy(source_value)
            self._decref(source_value)

    result = builder.phi(...)  # or use alloca

    # Store in target
    self._store_value(target_name, result)

    # Mark source as moved (compile-time tracking)
    if source_name:
        self._mark_moved(source_name)
```

### Step 6: Handle Edge Cases

**Reassignment clears moved status:**
```python
def _generate_assignment(self, node):
    # ... generate assignment ...

    # Variable is now valid again
    self._unmark_moved(target_name)
```

**Function parameters:**
When a value is passed to a function via `:=`, the caller's variable is moved.

**Conditional moves:**
If a variable is moved in one branch, it's considered moved for all paths after the conditional.

## Technical Notes

### The Refcount Check

At runtime, `:=` checks the refcount:
```
if refcount == 1:
    # Sole owner: just transfer pointer (move)
    # Caller is invalidated at compile time
else:
    # Shared: copy now to get refcount 1
    # Decref original (remove our share)
```

### Compile-Time vs Runtime

- **Compile-time**: Track which variables have been moved from, reject use-after-move
- **Runtime**: Check refcount to decide move vs copy

The compile-time check catches bugs. The runtime check determines the actual operation.

### Scope and Control Flow

Use-after-move tracking must handle:
- Nested scopes (moved in inner scope = moved in outer)
- Conditionals (moved in any branch = might be moved)
- Loops (moved in loop body = moved after loop)

Conservative approach: if moved on any path, consider moved.

### Interaction with COW

`:=` and `=` use the same underlying COW mechanism:
- Both share refcounted buffers
- `=` just bumps refcount (deferred copy)
- `:=` checks refcount and either moves or copies immediately

## Success Criteria

1. All tests in `test_move_operator.py` pass
2. `:=` guarantees sole ownership (refcount = 1) after assignment
3. Move (refcount was 1): no copy, source invalidated
4. Eager copy (refcount > 1): copy now, both valid
5. Compile-time use-after-move detection
6. Reassignment clears moved status
7. All existing tests pass (Sessions 1-2)

## What This Enables

After this session:
- Programmers can choose deterministic performance with `:=`
- "Pay now, never later" semantics
- Clear ownership transfer for APIs
- Foundation ready for persistent data structures (Sessions 4-8)

## Files to Modify

- `Coex.g4` - Add `:=` syntax
- `ast_nodes.py` - Add move assignment node
- `ast_builder.py` - Parse `:=`
- `codegen.py` - Implement `:=` codegen and use-after-move tracking
- `tests/test_move_operator.py` - New test file (write first!)

## Running Tests

```bash
# Regenerate parser after grammar changes
antlr -Dlanguage=Python3 -visitor Coex.g4

# Write tests first, verify they fail
python3 -m pytest tests/test_move_operator.py -v --tb=short

# After implementation
python3 -m pytest tests/test_move_operator.py -v --tb=short

# Verify no regressions
python3 -m pytest tests/ -v --tb=short
```
