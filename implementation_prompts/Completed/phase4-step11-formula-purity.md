# Implementation Prompt: Phase 4, Step 11
# Formula Purity Checks

## Objective

Implement static analysis to verify that `formula` functions are pure and suitable for GPU offloading. This prepares for Phase 5 (GPU offload).

## Prerequisites

- Phases 1-3 complete (task system working)
- Read `coex-task-system-spec.md` section 2 (Function Kind Hierarchy)
- Understand what makes a function GPU-offloadable

## Test-First Methodology

**Write all tests before implementing.**

## Purity Requirements

A formula is pure if it:

1. **No I/O**: Does not call print, file operations, network, etc.
2. **No Atomics**: Does not read/write atomic variables
3. **No Mutable State**: Only uses `const` bindings (already enforced)
4. **No Side-Effect Functions**: Only calls other formulas
5. **Deterministic**: Same inputs always produce same outputs

For GPU offloading, additionally:

6. **Bounded Recursion**: Recursion depth must be statically determinable or bounded
7. **Fixed Memory**: No unbounded allocation within the formula
8. **No Pointers**: No raw memory manipulation

## Invariants to Test

### Invariant 1: Pure Formula - No Warning

```coex
formula add(a: int, b: int) -> int
    return a + b
~

func main() -> int
    print(add(1, 2))
    return 0
~
```
Expected: No warning, GPU-offloadable

### Invariant 2: Calls Print - Warning

```coex
formula impure_print(x: int) -> int
    print(x)  # Side effect!
    return x
~

func main() -> int
    return 0
~
```
Expected: Error - formula cannot have side effects

### Invariant 3: Uses Atomic - Warning

```coex
formula impure_atomic(counter: atomic_int) -> int
    return counter.load()  # Reads shared state!
~

func main() -> int
    return 0
~
```
Expected: Error - formula cannot access atomics

### Invariant 4: Calls Task - Error

```coex
task do_work() -> int
    return 42
~

formula impure_task() -> int
    return do_work()  # Calls non-formula!
~

func main() -> int
    return 0
~
```
Expected: Error - formula can only call formulas

### Invariant 5: Calls Another Formula - OK

```coex
formula helper(x: int) -> int
    return x * 2
~

formula main_formula(x: int) -> int
    return helper(x) + 1
~

func main() -> int
    print(main_formula(10))
    return 0
~
```
Expected: No warning, both GPU-offloadable

### Invariant 6: Recursive Formula - Warning for GPU

```coex
formula factorial(n: int) -> int
    if n <= 1
        return 1
    ~
    return n * factorial(n - 1)
~

func main() -> int
    print(factorial(5))
    return 0
~
```
Expected: Pure (OK), but warning for GPU (unbounded recursion)

### Invariant 7: Uses Only Const - OK

```coex
formula uses_const(x: int) -> int
    const y = x * 2
    const z = y + 1
    return z
~

func main() -> int
    print(uses_const(10))
    return 0
~
```
Expected: No warning

### Invariant 8: Var Binding Attempted - Error

```coex
formula uses_var(x: int) -> int
    y = x * 2        # Rebindable in formula!
    y = y + 1        # Rebinding
    return y
~

func main() -> int
    return 0
~
```
Expected: Error - formulas require const bindings (already enforced by language)

## Implementation

### Purity Checker

```python
class FormulaPurityChecker(ASTVisitor):
    def __init__(self):
        self.errors = []
        self.gpu_warnings = []
        self.in_formula = False
        self.current_formula = None
        
    def visit_function_decl(self, node):
        if node.kind == FORMULA:
            self.in_formula = True
            self.current_formula = node.name
            self.check_purity(node)
            self.visit(node.body)
            self.in_formula = False
        else:
            self.visit(node.body)
    
    def check_purity(self, node):
        """Check all purity constraints."""
        self.check_no_io(node)
        self.check_no_atomics(node)
        self.check_only_calls_formulas(node)
        self.check_gpu_constraints(node)
    
    def visit_call(self, node):
        if self.in_formula:
            callee_kind = self.get_callee_kind(node.callee)
            if callee_kind != FORMULA:
                self.errors.append(PurityError(
                    f"Formula '{self.current_formula}' calls {callee_kind} '{node.callee}'; formulas can only call formulas",
                    node.location
                ))
            
            # Check for I/O functions
            if node.callee in IO_FUNCTIONS:
                self.errors.append(PurityError(
                    f"Formula '{self.current_formula}' performs I/O via '{node.callee}'",
                    node.location
                ))
```

### GPU Constraint Checker

```python
def check_gpu_constraints(self, node):
    """Check constraints specific to GPU offloading."""
    
    # Check for recursion
    if self.is_recursive(node):
        if not self.has_bounded_recursion(node):
            self.gpu_warnings.append(GPUWarning(
                f"Formula '{node.name}' has unbounded recursion; not GPU-offloadable",
                node.location
            ))
    
    # Check for dynamic allocation
    if self.has_dynamic_allocation(node):
        self.gpu_warnings.append(GPUWarning(
            f"Formula '{node.name}' has dynamic allocation; not GPU-offloadable",
            node.location
        ))

def is_recursive(self, node):
    """Check if formula calls itself (directly or indirectly)."""
    calls = self.find_all_calls(node.body)
    return node.name in calls

def has_bounded_recursion(self, node):
    """Check if recursion has a static bound."""
    # Conservative: return False for now
    # Could analyze for patterns like factorial(n-1) with base case
    return False
```

### Integration

```python
def compile_with_purity_check(source):
    ast = parse(source)
    
    # Check formula purity
    checker = FormulaPurityChecker()
    checker.analyze(ast)
    
    if checker.errors:
        raise PurityError(checker.errors)
    
    # Insert GPU warnings
    if checker.gpu_warnings:
        source = insert_warnings(source, checker.gpu_warnings, tag="GPU")
    
    return compile(ast)
```

## Test File

Create `tests/test_formula_purity.py`:

```python
class TestFormulaPurity:
    def test_pure_formula_ok(self, expect_output):
        expect_output('''
formula add(a: int, b: int) -> int
    return a + b
~

func main() -> int
    print(add(1, 2))
    return 0
~
''', "3\n")

    def test_formula_calls_print_error(self, compile_coex):
        with pytest.raises(PurityError):
            compile_coex('''
formula impure(x: int) -> int
    print(x)
    return x
~

func main() -> int
    return 0
~
''')

    def test_formula_calls_task_error(self, compile_coex):
        with pytest.raises(PurityError):
            compile_coex('''
task work() -> int
    return 42
~

formula bad() -> int
    return work()
~

func main() -> int
    return 0
~
''')

    def test_formula_calls_formula_ok(self, expect_output):
        expect_output('''
formula double(x: int) -> int
    return x * 2
~

formula quadruple(x: int) -> int
    return double(double(x))
~

func main() -> int
    print(quadruple(5))
    return 0
~
''', "20\n")


class TestGPUConstraints:
    def test_recursive_formula_warns(self, compile_with_warnings):
        source = '''
formula factorial(n: int) -> int
    if n <= 1
        return 1
    ~
    return n * factorial(n - 1)
~

func main() -> int
    return 0
~
'''
        _, warnings = compile_with_warnings(source)
        assert any("GPU" in w.tag for w in warnings)

    def test_non_recursive_no_warning(self, compile_with_warnings):
        source = '''
formula simple(x: int) -> int
    return x * 2
~

func main() -> int
    return 0
~
'''
        _, warnings = compile_with_warnings(source)
        assert not any("GPU" in w.tag for w in warnings)
```

## Success Criteria

1. Pure formulas compile without error
2. Formulas calling non-formulas produce error
3. Formulas with I/O produce error
4. Formulas with atomics produce error
5. Recursive formulas get GPU warning
6. GPU warnings use `#@ [GPU]` format

## Notes

- Purity errors are hard errors (compilation fails)
- GPU warnings are advisory (compilation succeeds)
- This prepares for Phase 5 GPU offload
- Formula purity is also valuable for optimization (memoization, parallelization)
