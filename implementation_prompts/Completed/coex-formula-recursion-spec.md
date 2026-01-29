# Coex Formula Recursion: Implementation Specification

## Overview

This specification formalizes recursion support in `formula` function kind. Formulas are pure functions with lazy evaluation semantics. Recursion is a natural fit for pure functional programming and should be fully supported.

## Current State

Formulas may already support recursion in the current implementation. This spec formalizes the expected behavior and ensures the compiler handles recursive formulas correctly.

## Specification

### Syntax

No syntax changes required. A formula may call itself by name:

```coex
formula factorial(n: int) -> int:
    if n <= 1: 1 else: n * factorial(n - 1)
~

formula fibonacci(n: int) -> int:
    if n <= 1: n else: fibonacci(n - 1) + fibonacci(n - 2)
~
```

### Mutual Recursion

Formulas may call other formulas, including mutual recursion:

```coex
formula is_even(n: int) -> bool:
    if n == 0: true else: is_odd(n - 1)
~

formula is_odd(n: int) -> bool:
    if n == 0: false else: is_even(n - 1)
~
```

The compiler must handle forward references. If formula `A` calls formula `B` which is defined later in the source file, this must compile correctly.

### Higher-Order Formulas

Formulas may accept formulas as parameters and return formulas:

```coex
formula map(f: formula(int) -> int, xs: [int]) -> [int]:
    if len(xs) == 0:
        []
    else:
        [f(xs[0])] + map(f, xs[1..])
~

formula filter(p: formula(int) -> bool, xs: [int]) -> [int]:
    if len(xs) == 0:
        []
    else if p(xs[0]):
        [xs[0]] + filter(p, xs[1..])
    else:
        filter(p, xs[1..])
~

formula foldr(f: formula(int, int) -> int, z: int, xs: [int]) -> int:
    if len(xs) == 0:
        z
    else:
        f(xs[0], foldr(f, z, xs[1..]))
~
```

### Tail Call Optimization

The compiler SHOULD recognize tail-recursive formulas and optimize them to iterative form to avoid stack overflow:

```coex
# Tail recursive - should optimize to loop
formula factorial_tail(n: int, acc: int) -> int:
    if n <= 1: acc else: factorial_tail(n - 1, n * acc)
~

# Not tail recursive - cannot optimize
formula factorial(n: int) -> int:
    if n <= 1: 1 else: n * factorial(n - 1)
~
```

Tail call optimization is RECOMMENDED but not REQUIRED for initial implementation.

### Purity Constraints

All existing formula purity constraints remain in effect:

1. No side effects (no I/O, no printing)
2. No access to mutable state (no atomics)
3. No access to external variables from enclosing scope
4. No calling impure functions (`func`, `task`, `thread`)

Formulas may only call:
- Other formulas
- Built-in pure functions (math operations, array operations)

### Lazy Evaluation

Formula arguments are evaluated lazily. This enables patterns like:

```coex
formula if_then_else(cond: bool, then_val: int, else_val: int) -> int:
    if cond: then_val else: else_val
~

# This works because else_val is not evaluated when cond is true
result = if_then_else(true, 1, factorial(1000000))
```

The `factorial(1000000)` is never computed because it's never needed.

### Calling Hierarchy

Formulas occupy the bottom of the calling hierarchy:

```
func / task / thread
         │
         ▼ can call
      declare
         │
         ▼ can call
      formula ←──┐
         │       │
         └───────┘ (can call self and other formulas)
```

Formulas CANNOT call:
- `func`
- `task`
- `thread`
- `declare` (declare can call formula, not vice versa)

## Implementation Requirements

### 1. Parser

No changes required. The existing grammar supports function calls within function bodies.

### 2. Semantic Analysis

Verify the following during semantic analysis:

```python
class FormulaValidator:
    def validate_formula(self, formula: FormulaAST, scope: Scope):
        # Check all calls in the formula body
        for call in formula.body.find_all(FunctionCall):
            target = scope.lookup(call.name)
            
            if target is None:
                # Could be forward reference - defer resolution
                self.deferred_calls.append((formula, call))
                continue
            
            if target.kind not in (FunctionKind.FORMULA, FunctionKind.BUILTIN):
                raise PurityError(
                    f"Formula '{formula.name}' cannot call {target.kind} "
                    f"'{target.name}' - formulas may only call other formulas"
                )
        
        # Existing purity checks
        self.check_no_side_effects(formula)
        self.check_no_external_state(formula)
```

### 3. Forward Reference Resolution

After all declarations are parsed, resolve forward references:

```python
class ForwardReferenceResolver:
    def resolve(self, program: ProgramAST):
        for formula, call in self.deferred_calls:
            target = program.scope.lookup(call.name)
            
            if target is None:
                raise UndefinedError(f"Unknown function '{call.name}'")
            
            if target.kind not in (FunctionKind.FORMULA, FunctionKind.BUILTIN):
                raise PurityError(
                    f"Formula '{formula.name}' cannot call {target.kind} "
                    f"'{target.name}'"
                )
```

### 4. Code Generation

Generate recursive calls normally. The LLVM backend handles recursion natively:

```python
class FormulaCodeGenerator:
    def visit_call(self, call: FunctionCall):
        # Recursive calls work like any other call
        # LLVM handles the stack frames
        
        target = self.scope.lookup(call.name)
        
        # Evaluate arguments (lazily if implementing lazy evaluation)
        args = [self.visit(arg) for arg in call.arguments]
        
        # Generate call instruction
        return self.builder.call(target.llvm_function, args)
```

### 5. Tail Call Optimization (Optional)

If implementing TCO:

```python
class TailCallOptimizer:
    def is_tail_call(self, call: FunctionCall, formula: FormulaAST) -> bool:
        """Check if call is in tail position."""
        # A call is in tail position if:
        # 1. It's the return value of the function
        # 2. No operations happen after the call
        
        return (
            call.parent.is_return_statement and
            call.parent.expression == call
        )
    
    def optimize(self, formula: FormulaAST):
        """Convert tail-recursive formula to iterative form."""
        tail_calls = [
            call for call in formula.body.find_all(FunctionCall)
            if call.name == formula.name and self.is_tail_call(call, formula)
        ]
        
        if tail_calls and self.all_recursive_calls_are_tail(formula, tail_calls):
            return self.convert_to_loop(formula)
        
        return formula
```

## Testing

### Basic Recursion

```python
def test_factorial():
    source = """
    formula factorial(n: int) -> int:
        if n <= 1: 1 else: n * factorial(n - 1)
    ~
    
    func main():
        print(factorial(5))
    ~
    """
    assert run(source) == "120"

def test_fibonacci():
    source = """
    formula fib(n: int) -> int:
        if n <= 1: n else: fib(n - 1) + fib(n - 2)
    ~
    
    func main():
        print(fib(10))
    ~
    """
    assert run(source) == "55"
```

### Mutual Recursion

```python
def test_mutual_recursion():
    source = """
    formula is_even(n: int) -> bool:
        if n == 0: true else: is_odd(n - 1)
    ~
    
    formula is_odd(n: int) -> bool:
        if n == 0: false else: is_even(n - 1)
    ~
    
    func main():
        print(is_even(10))
        print(is_odd(10))
    ~
    """
    assert run(source) == "true\nfalse"
```

### Higher-Order Formulas

```python
def test_higher_order():
    source = """
    formula map(f: formula(int) -> int, xs: [int]) -> [int]:
        if len(xs) == 0: [] else: [f(xs[0])] + map(f, xs[1..])
    ~
    
    formula double(x: int) -> int:
        x * 2
    ~
    
    func main():
        result = map(double, [1, 2, 3, 4, 5])
        print(result)
    ~
    """
    assert run(source) == "[2, 4, 6, 8, 10]"
```

### Purity Enforcement

```python
def test_formula_cannot_call_func():
    source = """
    func impure(x: int) -> int:
        print(x)
        return x
    ~
    
    formula bad(x: int) -> int:
        impure(x)
    ~
    """
    assert_compile_error(source, "Formula 'bad' cannot call func 'impure'")

def test_formula_cannot_call_declare():
    source = """
    declare matrix_op(A: [[float32]]) -> [[float32]]:
        B[i,j] = A[i,j] * 2.0
        return B
    ~
    
    formula bad(A: [[float32]]) -> [[float32]]:
        matrix_op(A)
    ~
    """
    assert_compile_error(source, "Formula 'bad' cannot call declare 'matrix_op'")
```

### Tail Call Optimization (if implemented)

```python
def test_tail_recursion_no_stack_overflow():
    source = """
    formula sum_tail(n: int, acc: int) -> int:
        if n <= 0: acc else: sum_tail(n - 1, acc + n)
    ~
    
    func main():
        # This would overflow without TCO
        print(sum_tail(100000, 0))
    ~
    """
    # Should complete without stack overflow
    result = run(source)
    assert result == str(sum(range(100001)))
```

## Diagnostics

### Compile-time Errors

```
error: Formula 'process' cannot call func 'do_io'
  --> source.coex:15:9
   |
15 |         do_io(x)
   |         ^^^^^^^^
   |
   = note: formulas may only call other formulas and built-in pure functions
   = note: 'do_io' is a func, which may have side effects
```

### Warnings (optional)

```
warning: Non-tail recursive formula 'factorial' may cause stack overflow for large inputs
  --> source.coex:5:1
   |
 5 | formula factorial(n: int) -> int:
   | ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
   |
   = note: consider using tail-recursive form with an accumulator
   = help: formula factorial_tail(n: int, acc: int) -> int:
               if n <= 1: acc else: factorial_tail(n - 1, n * acc)
```

## Summary

This specification formalizes:

1. **Self-recursion** in formulas
2. **Mutual recursion** between formulas
3. **Higher-order formulas** (formulas as parameters and return values)
4. **Forward reference resolution** for mutually recursive formulas
5. **Purity enforcement** preventing calls to impure function kinds
6. **Tail call optimization** (recommended, not required)

The implementation should be straightforward as recursion is a natural fit for pure functions, and LLVM handles recursive calls natively.
