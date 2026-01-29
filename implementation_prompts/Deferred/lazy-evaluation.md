# Coex Lazy Evaluation for Formulas

## Overview

Coex formulas support lazy evaluation, enabling deferred computation that aligns with how mathematicians and scientists think about expressions. A formula invocation does not immediately compute its result; instead, it produces a *thunk*—a suspended computation that executes only when its value is required. This design preserves Coex's value semantics while providing the benefits of lazy evaluation: avoiding unnecessary computation and enabling natural expression of mathematical relationships.

## Design Principles

Lazy evaluation in Coex adheres to three core principles derived from the language's broader philosophy:

**Value semantics preservation.** Thunks behave like values. Assignment copies the handle, and each handle maintains independent evaluation state. There is no shared mutable state between copies of a thunk, eliminating concurrency hazards at the cost of potential recomputation.

**Purity guarantees correctness.** Because formulas are pure (no side effects, no external state access), the order and number of evaluations cannot affect program correctness. Computing the same thunk twice yields identical results, making recomputation safe if not always optimal.

**Immutable heap integration.** Thunks reside on the immutable heap. The thunk object itself—containing captured values and a code pointer—never changes after creation. Evaluation produces a new value; it does not mutate the thunk in place.

## Thunk Representation

A thunk consists of two components stored as a heap object:

1. **Code pointer**: A reference to the compiled formula code that will compute the result.

2. **Captured environment**: A value-copied snapshot of all free variables referenced by the formula at the point of suspension. Because Coex uses value semantics, this snapshot is a deep copy—subsequent changes to variables in the original scope do not affect the thunk's captured values.

A handle to a thunk contains:

- A pointer to the thunk's heap object
- An evaluation state flag: either `Suspended` or `Evaluated`
- If evaluated, the computed result value (or a pointer to it for non-primitive types)

```
Handle {
    heap_ptr: Pointer<Thunk>
    state: Suspended | Evaluated(value)
}
```

The thunk heap object remains immutable throughout its lifetime. Evaluation transitions the *handle's* state, not the thunk itself.

## Thunk Creation

A thunk is created when a formula is invoked outside of a context that immediately requires its value. The compiler determines suspension points based on usage context.

**Suspending contexts** (thunk created):
- Assignment to a variable: `x = some_formula(args)`
- Passing as an argument to a non-strict parameter
- Collection construction: `[formula1(a), formula2(b), formula3(c)]`

**Forcing contexts** (immediate evaluation):
- Strict primitive operations: `+`, `-`, `*`, `/`, comparisons
- Pattern matching that inspects the value
- Passing to `extern` functions (C FFI requires concrete values)
- Return from a `func` or `task` (formulas may remain suspended)
- Explicit force via the `:=` operator

### Example

```coex
formula expensive(x: float) -> float {
    # Assume this involves significant computation
    return sin(x) * cos(x) + sqrt(abs(x)) * log(x + 1.0)
}

func example() {
    a = expensive(1.0)    # Creates thunk, does not compute
    b = expensive(2.0)    # Creates thunk, does not compute
    
    if condition {
        return a + b      # Forces both thunks, computes results
    } else {
        return 0.0        # Neither thunk ever evaluated
    }
}
```

## Thunk Evaluation (Forcing)

When a thunk's value is required, the runtime *forces* the thunk:

1. Check the handle's state.
2. If `Evaluated(value)`, return the cached value immediately.
3. If `Suspended`:
   a. Invoke the formula code with the captured environment.
   b. Transition the handle's state to `Evaluated(result)`.
   c. Return the result.

Forcing is a local operation affecting only the specific handle being forced. Other handles pointing to the same underlying thunk heap object are not affected.

### The `:=` Operator for Explicit Forcing

To explicitly force a thunk, use the `:=` operator:

```coex
x = expensive(1.0)     # Thunk created
y := x                 # Forces x, y holds the concrete value
```

This aligns with `:=`'s existing semantics for tasks: it means "fully realize this computation now." For tasks, `:=` spawns and retrieves; for thunks, `:=` forces and retrieves. Both are species of deferred computation, and `:=` is the uniform operator for collapsing them to concrete values.

If `:=` is applied to an already-evaluated handle or a non-thunk value, it performs a deep copy (identity for primitives), consistent with its behavior elsewhere in the language.

## Assignment and Copying

When a thunk handle is assigned to another variable, the handle is copied but the underlying thunk heap object is shared:

```coex
x = some_formula(args)    # x holds Handle { heap_ptr: T1, state: Suspended }
y = x                     # y holds Handle { heap_ptr: T1, state: Suspended }
                          # Both point to same thunk T1
```

At this point, `x` and `y` share the same thunk heap object. However, because evaluation transitions the *handle's* state (not the thunk), forcing one does not affect the other:

```coex
result = y + 0.0          # Forces y's handle
                          # y.state -> Evaluated(computed_value)
                          # x.state remains Suspended

result2 = x + 0.0         # Forces x's handle independently
                          # Recomputes the formula (same thunk, different handle)
                          # x.state -> Evaluated(computed_value)
```

### Rationale: Independence Over Sharing

Traditional lazy evaluation systems (e.g., Haskell) use shared memoization: forcing any reference to a thunk updates the thunk in place, and all references see the cached result. This requires either:

- Single-threaded execution, or
- Synchronization primitives (locks, atomic CAS) to coordinate concurrent evaluation

Coex's approach—independent handles with per-handle memoization—provides several benefits:

1. **No synchronization required.** Each handle's state transition is purely local. No locks, no atomic operations, no risk of one thread observing a partially-evaluated thunk.

2. **Predictable behavior.** The programmer can reason locally about when computation occurs. Forcing `y` affects only `y`.

3. **Consistent value semantics.** The independence of `x` and `y` after `y = x` matches how all other Coex values behave—copies are independent.

The tradeoff is potential recomputation when multiple handles to the same thunk are forced independently. For pure formulas, this produces identical results and is therefore correct, if not always optimal.

## Interaction with Concurrency

Lazy evaluation and concurrency interact cleanly due to the independence of handles:

```coex
task parallel_compute() {
    x = expensive(1.0)
    
    # Spawn two tasks, each receiving a copy of x's handle
    a := process_a(x)     # process_a gets its own handle copy
    b := process_b(x)     # process_b gets its own handle copy
    
    return combine(a, b)
}
```

If both `process_a` and `process_b` force their copies of `x`, each computes independently. There is no race condition, no need for synchronization, and no risk of one task corrupting another's view of the thunk. The formula executes twice, but correctness is guaranteed.

### Explicit Sharing Pattern

If the programmer wants to ensure a thunk is evaluated exactly once before parallel dispatch, they can force it explicitly:

```coex
task parallel_compute_shared() {
    x = expensive(1.0)
    x_value := x          # Force once, get concrete value
    
    # Both tasks receive the concrete value, not a thunk
    a := process_a(x_value)
    b := process_b(x_value)
    
    return combine(a, b)
}
```

This pattern makes the programmer's intent explicit: compute once, share the result.

## Interaction with GPU Offload

Formulas used in comprehensions and iterators are candidates for GPU offload. When a formula appears in such a context, the runtime evaluates whether to:

1. Execute thunks lazily on CPU, or
2. Batch-evaluate via GPU dispatch

The GPU offload system forces all thunks in the input collection before dispatch (GPU kernels require concrete values). For large collections, this is typically more efficient than lazy per-element evaluation:

```coex
formula transform(x: float) -> float {
    return sin(x) * cos(x)
}

# input contains concrete values (not thunks)
results = [transform(x) for x in input]
# GPU dispatch: all transforms computed in parallel
# results contains concrete values
```

If the input collection contains thunks, they are forced as part of staging data for GPU transfer. The resulting collection contains concrete values, not thunks.

## Nested Thunks

A thunk's captured environment may itself contain thunks:

```coex
a = expensive1(1.0)       # Thunk A
b = expensive2(a)         # Thunk B captures handle to A
```

Thunk B's captured environment contains a *copy* of the handle to thunk A. When B is forced:

1. B's formula code executes.
2. If B's code requires the value of its captured `a`, it forces that handle.
3. This evaluation is local to B's copy of the handle; the original `a` handle remains in its prior state.

This behavior is consistent with value semantics: B captured a copy of `a`'s handle at thunk creation time.

## Thunk Chains and Stack Depth

Deep chains of dependent thunks can lead to deep evaluation stacks:

```coex
formula step(x: float) -> float {
    return x + 1.0
}

x0 = 0.0
x1 = step(x0)
x2 = step(x1)
x3 = step(x2)
# ... many steps ...
xN = step(x_{N-1})

result = xN + 0.0    # Forces xN, which forces x_{N-1}, etc.
```

Forcing `xN` triggers a chain of forces back to the original value. The evaluation stack grows proportionally to chain depth.

**Mitigation strategies:**

1. **Explicit forcing at intervals.** For iterative computations, periodically force intermediate results to bound chain depth.

2. **Strict accumulators.** When building up results iteratively, use eager evaluation patterns rather than thunk chains.

3. **Tail-call optimization.** The compiler may recognize and optimize certain patterns to avoid deep stacks (future enhancement).

## Memory Management

Thunks are heap-allocated and subject to garbage collection like all other Coex heap objects. A thunk becomes eligible for collection when no handles reference it.

Handle evaluation state does not affect thunk lifetime—the thunk heap object persists as long as any handle (evaluated or not) references it, because an unevaluated handle may still be forced later, requiring access to the thunk's code and captured environment.

Once all handles to a thunk have been evaluated, the thunk's captured environment values are no longer needed for *those handles*, but the thunk object persists until garbage collection determines no unevaluated handles remain.

## Summary of Guarantees

1. **Correctness.** Lazy evaluation never changes the result of a pure formula computation. Evaluation order is unobservable due to purity.

2. **Independence.** Each handle maintains independent evaluation state. Forcing one handle never affects another, even if they reference the same underlying thunk.

3. **Concurrency safety.** No synchronization is required for thunk evaluation. Concurrent forces of different handles to the same thunk are safe (they compute independently).

4. **Value semantics.** Thunk handles behave like values. Assignment copies the handle. No spooky action at a distance.

5. **Determinism.** Given the same inputs, a formula produces the same output regardless of how many times or in what order thunks are forced.

## Error Handling

If a formula raises an error during evaluation, the error propagates to the forcing context. The handle's state transitions to `Evaluated` with an error marker, and subsequent forces of that *same handle* re-raise the error without re-executing the formula.

Different handles to the same thunk may have different error states if forced in different contexts (though for pure formulas, they will consistently either all succeed or all fail with the same error).

```coex
formula might_fail(x: float) -> float {
    if x < 0.0 {
        raise Error("negative input")
    }
    return sqrt(x)
}

a = might_fail(-1.0)    # Thunk created, no error yet

try {
    result := a         # Forces, raises error
} catch e {
    # Handle error
}

# a's handle now holds the error; re-forcing raises again without recomputation
```

## Syntax Summary

| Construct | Behavior |
|-----------|----------|
| `x = formula(args)` | Creates thunk, assigns handle to `x` |
| `y = x` | Copies handle (shares underlying thunk) |
| `x + y` (primitives) | Forces both operand handles |
| `y := x` | Explicitly forces `x`, assigns concrete value to `y` |
| `[f(x) for x in items]` | May batch-evaluate via GPU; results are concrete |
| `extern` calls | All thunk arguments forced before call |
