# Implementation Prompt: Phase 4, Step 10
# Atomic Spin Detection

## Objective

Implement static analysis to detect potentially problematic spin-waits on atomics in task context, inserting `#@` warnings into the source.

## Prerequisites

- Phases 1-3 complete (task system working)
- Read `coex-task-system-spec.md` section 10 (Static Analysis)
- Understand the `#@` warning insertion mechanism

## Test-First Methodology

**Write all tests before implementing.** The analysis must catch real problems without excessive false positives.

## Invariants to Test

### Invariant 1: Direct Atomic in Loop Condition - Warning

```coex
task bad_spin(flag: atomic_bool) -> void
    while not flag.load()
        x = 1
    ~
~
```
Expected: Warning `#@ [ATOMIC_SPIN] Loop condition depends on atomic load; may starve scheduler`

### Invariant 2: Indirect Atomic Dependency - Warning

```coex
task indirect_spin(flag: atomic_bool) -> void
    done = flag.load()
    while not done
        done = flag.load()
    ~
~
```
Expected: Warning (done depends on atomic)

### Invariant 3: Bounded Loop - No Warning

```coex
task bounded_spin(flag: atomic_bool) -> void
    for i in 0..100
        if flag.load()
            break
        ~
    ~
~
```
Expected: No warning (loop is bounded)

### Invariant 4: Thread Context - No Warning

```coex
thread thread_spin(flag: atomic_bool) -> void
    while not flag.load()
        x = 1
    ~
~
```
Expected: No warning (threads can spin safely)

### Invariant 5: Atomic in Loop Body Only - No Warning

```coex
task body_atomic(counter: atomic_int, n: int) -> void
    for i in 0..n
        counter.fetch_add(1)
    ~
~
```
Expected: No warning (atomic doesn't control loop)

## Implementation

### Core Analysis

```python
class AtomicSpinAnalyzer(ASTVisitor):
    def __init__(self):
        self.warnings = []
        self.in_task = False
        
    def visit_function_decl(self, node):
        self.in_task = (node.kind == TASK)
        self.visit(node.body)
        self.in_task = False
    
    def visit_while_stmt(self, node):
        if self.in_task and not self.is_bounded(node):
            atomics = self.find_atomic_loads(node.condition)
            if atomics:
                self.warnings.append(SpinWarning(node.location))
        self.visit(node.body)
    
    def is_bounded(self, node):
        return isinstance(node, ForStmt)
    
    def find_atomic_loads(self, expr):
        # Find .load() calls on atomic types
        pass
```

### Warning Insertion

```python
def insert_warnings(source, warnings):
    lines = source.split('\n')
    for w in sorted(warnings, key=lambda x: x.line, reverse=True):
        indent = get_indent(lines[w.line - 1])
        lines.insert(w.line - 1, f"{indent}#@ [ATOMIC_SPIN] {w.message}")
    return '\n'.join(lines)
```

## Test File

Create `tests/test_atomic_spin_detection.py`:

```python
class TestAtomicSpinDetection:
    def test_direct_atomic_warns(self, compile_with_warnings):
        source = '''
task spinner(flag: atomic_bool) -> void
    while not flag.load()
        x = 1
    ~
~
func main() -> int
    return 0
~
'''
        _, warnings = compile_with_warnings(source)
        assert len(warnings) == 1

    def test_bounded_no_warning(self, compile_with_warnings):
        source = '''
task bounded(flag: atomic_bool) -> void
    for i in 0..100
        if flag.load()
            break
        ~
    ~
~
func main() -> int
    return 0
~
'''
        _, warnings = compile_with_warnings(source)
        assert len(warnings) == 0

    def test_thread_context_no_warning(self, compile_with_warnings):
        source = '''
thread spinner(flag: atomic_bool) -> void
    while not flag.load()
        x = 1
    ~
~
func main() -> int
    return 0
~
'''
        _, warnings = compile_with_warnings(source)
        assert len(warnings) == 0
```

## Success Criteria

1. Direct atomic conditions detected
2. Bounded loops not flagged
3. Non-task contexts not flagged
4. Warnings inserted with correct `#@` format
