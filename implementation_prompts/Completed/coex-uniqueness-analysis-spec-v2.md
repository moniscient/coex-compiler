# Coex Uniqueness Analysis: Specification and Implementation

## 1. Overview and Motivation

Coex is a value-semantics language where all heap data is immutable. This provides strong safety guarantees but creates a performance challenge: operations like `set.add(element)` must conceptually create a new Set rather than mutating the existing one. Naively implemented, this results in O(n) allocations for n modifications, creating severe GC pressure and poor cache behavior.

The sieve of Eratosthenes benchmark demonstrates this pathology starkly. The inner loop `composites = composites.add(mult)` executes hundreds of thousands of times per segment, and each iteration currently allocates a new wrapper object plus new HAMT path nodes. Profiling shows the majority of execution time is spent in allocation and garbage collection rather than useful computation.

Uniqueness analysis (also called linearity analysis) solves this problem by recognizing when a value has exactly one reference. When the compiler can prove that no other binding can observe a value, mutation becomes semantically equivalent to copy-then-modify—the optimization is unobservable. The binding `composites = composites.add(mult)` can be lowered to an in-place mutation when `composites` is dead after the right-hand side is evaluated.

This document specifies a uniqueness analysis pass for the Coex compiler that identifies opportunities for in-place mutation and defines the code generation transformations to exploit them.

## 2. Coex Memory Architecture

### 2.1 Confirmed Object Layout

All Coex heap objects follow a uniform wrapper-and-storage pattern:

```
Handle Table
    │
    ▼
Wrapper Object (via gc_alloc → handle → deref)
    │
    ├── field1: i64
    ├── field2: i64
    ├── ...
    └── ptr/root: i64 (raw pointer to storage, NOT a handle)
                   │
                   ▼
            Underlying Storage (also gc_alloc'd, has its own handle)
```

Each GC-allocated object has its handle stored in its header's forward field, enabling pointer-to-handle recovery during GC tracing.

### 2.2 Type-Specific Layouts

**Set and Map (HAMT-based):**
```
Handle → Set/Map wrapper
            │
            ├── root: i64 (raw pointer to HAMT root node)
            ├── len: i64
            └── flags: i64
                 │
                 ▼
            HAMT Node (gc_alloc'd, has handle in header)
                 │
                 ├── bitmap: i64
                 └── children: i64* (array of raw tagged pointers)
                          │
                    ┌─────┴─────┐
                    ▼           ▼
               Child Node    Leaf (tagged: bit 0 = 1)
```

HAMT nodes use raw pointers internally (not handles) for performance. Leaves are tagged with bit 0 set. GC marking traverses raw pointers and recovers handles via `gc_ptr_to_handle()` from object headers.

**List (Persistent Vector):**
```
Handle → List wrapper
            │
            ├── root: i64 (raw pointer to tree root)
            ├── len: i64
            ├── tail: i64 (optional tail buffer pointer)
            └── shift: i64 (tree depth indicator)
                 │
                 ▼
            Tree Nodes (32-way branching)
                 │
                 └── elements at leaves
```

**String:**
```
Handle → String wrapper
            │
            ├── data: i64 (raw pointer to byte storage)
            ├── len: i64
            └── hash: i64 (cached hash, optional)
                 │
                 ▼
            Contiguous byte array
```

**Array:**
```
Handle → Array wrapper
            │
            ├── data: i64 (raw pointer to element storage)
            ├── len: i64
            └── capacity: i64
                 │
                 ▼
            Contiguous element array
```

**User-Defined Types (UDTs):**
```
Handle → UDT wrapper
            │
            ├── field1: i64 (value or handle)
            ├── field2: i64
            └── ...
```

UDTs may contain primitive values directly or handles to other heap objects.

### 2.3 Implications for Optimization

The uniform wrapper pattern means the optimization strategy is **type-agnostic**:

1. Every type has a wrapper object pointed to by a handle
2. Update operations allocate a new wrapper and (for collections) new internal structure
3. When the binding is unique, the wrapper can be mutated in place
4. Internal structure optimization (e.g., HAMT path mutation) is a separate, more aggressive phase

## 3. Definitions and Terminology

**Binding**: An association between an identifier and a value within a scope. In Coex, bindings are established by assignment (`x = expr`), parameter passing, and for-loop iteration variables.

**Liveness**: A binding is *live* at a program point if there exists a control flow path from that point to a use of the binding. A binding is *dead* at a point if no such path exists.

**Unique reference**: A reference to a heap object is *unique* if it is the only reference to that object. When a binding holds a unique reference, the object can be safely mutated without violating value semantics because no other code can observe the mutation.

**Consuming use**: A use of a binding that renders it dead. After a consuming use, the binding's value is no longer accessible. Assignment to the same binding (rebinding) is a consuming use of the previous value.

**Non-consuming use**: A use that does not render the binding dead, such as passing it as an argument while also using it later.

**Wrapper object**: The heap object directly referenced by a handle. Contains metadata and pointers to underlying storage.

**Update operation**: A method or operation that conceptually returns a modified copy of an object. Includes collection methods (`add`, `put`, `append`), string operations (`concat`, `replace`), and potentially UDT update syntax.

**Wrapper mutation**: The optimization of modifying a wrapper object's fields in place rather than allocating a new wrapper. Applicable when the binding is unique.

**Storage mutation**: The more aggressive optimization of modifying underlying storage (HAMT nodes, tree nodes) in place. Requires additional uniqueness tracking at the storage level.

## 4. Language Constructs and Their Effects on Uniqueness

### 4.1 Binding Introduction

Bindings are introduced by:

1. **Local assignment**: `x = expr` — If `expr` produces a fresh value (allocation, literal, or consuming use of another unique binding), then `x` holds a unique reference.

2. **Function parameters**: Parameters receive copies of argument values. For reference types (all heap-allocated types in Coex), the parameter initially shares the reference with the caller's argument. Thus parameters are *not* unique at function entry unless the caller's argument was consumed by the call.

3. **For-loop variables**: `for x in collection` — The iteration variable `x` receives successive elements. These are *not* unique because the collection retains references to its elements.

4. **Pattern matching**: `match expr { case Pattern(x, y) => ... }` — Bound variables receive references to components of the matched value. Uniqueness depends on whether the scrutinee was unique.

### 4.2 Binding Consumption

A binding's reference is consumed (and potentially becomes unique for transfer) when:

1. **Rebinding**: `x = f(x)` — The old value of `x` is consumed by `f`, and `x` is rebound to the result. If `x` was the only reference to its value, and `f` is an update operation, the old value can be mutated in place.

2. **Last use**: The final use of a binding before it goes out of scope or is rebinding. This use is consuming.

3. **Explicit move** (if supported): A syntactic marker indicating the programmer intends to transfer ownership. Coex's current warning system suggests moves but does not enforce them; this analysis makes moves implicit based on dataflow.

### 4.3 Non-Consuming Uses

Uses that do not consume the binding:

1. **Multiple uses in expression**: `f(x, x)` — Both uses require the same value; neither can consume it.

2. **Use followed by later use**: If `x` is used on line 5 and again on line 10 with no intervening rebinding, the line-5 use is non-consuming.

3. **Escape to heap**: If `x` is stored in a data structure (`list.append(x)` where `list` survives), `x`'s referent now has multiple references.

4. **Escape via return**: `return x` — The value escapes to the caller; it is no longer unique within this function.

5. **Escape via channel/concurrent construct**: Sending a value on a channel or passing it to a spawned task transfers it to another execution context.

## 5. Dataflow Analysis Specification

The uniqueness analysis is a backward dataflow analysis that computes, for each program point, which bindings hold their last reference to their value (i.e., which bindings are "dead after this point").

### 5.1 Lattice

For each binding `b`, we track a boolean: `is_last_use[b]`. The lattice per binding is `{true, false}` with `true` meaning "this is definitively the last use" and `false` meaning "there may be later uses."

At a join point (control flow merge), we take the *meet*: a use is a last-use only if it is the last use on *all* paths. Thus: `is_last_use = is_last_use_path1 AND is_last_use_path2`.

### 5.2 Transfer Functions

We process statements in reverse order (backward analysis). For each statement `S`:

**Assignment** `x = expr`:
- After processing: `is_last_use[x] = true` (the previous value of `x` is dead after this point)
- Process `expr` to determine uses of other bindings within it
- If `expr` mentions binding `y`, mark whether this is `y`'s last use based on subsequent liveness

**Expression statement** `expr`:
- Process `expr` to mark uses of bindings

**If statement** `if cond then S1 else S2`:
- Analyze `S1` and `S2` independently
- At the merge point (before the `if`), join the liveness information
- Process `cond`

**While loop** `while cond do S`:
- Iterate to fixed point: the loop body may use bindings that are also used after the loop
- A use inside the loop is *not* a last use if the binding is live at loop entry (because the loop may iterate again)

**For loop** `for x in collection do S`:
- Similar to while: uses of bindings inside `S` are not last uses if those bindings are live at loop entry
- The collection expression is evaluated once; its bindings' uses are outside the loop

**Return** `return expr`:
- Process `expr`; any binding mentioned is *not* a last use (it escapes)

**Task spawn** `task_call(args...)`:
- Arguments escape to concurrent context; not last uses

### 5.3 Handling Update Patterns

The critical pattern to recognize is:

```
x = x.update_method(args...)
```

After backward analysis, if we determine that:
1. The right-hand side's use of `x` is the last use of the old `x`
2. `update_method` is an update operation (returns same type as receiver)
3. None of `args` alias `x`

Then this statement can be transformed to use wrapper mutation.

### 5.4 Aliasing Considerations

Coex's immutable heap simplifies alias analysis significantly. Since values cannot be mutated through one reference and observed through another, the main aliasing concern is ensuring we don't destroy a value that is still reachable through another path.

Key cases:

1. **Parameter aliasing**: If a function receives two parameters that might alias (point to the same object), neither can be treated as unique within the function without additional analysis.

2. **Structural aliasing**: If `x = y`, then both bindings reference the same object. A use of `x` prevents `y` from being unique (and vice versa).

3. **Closure capture**: Coex does not support closures with captured variables, so this is not a concern.

4. **Collection elements**: Elements retrieved from a collection are not unique because the collection retains the reference.

## 6. Update Operation Detection

### 6.1 Type-Agnostic Approach

Rather than maintaining an explicit registry of update methods per type, the analysis can infer update operations from method signatures:

**An update operation is any method on type `T` that:**
1. Takes `self` (the receiver) as input
2. Returns type `T` (same type as receiver)
3. Is called in the pattern `x = x.method(args...)`

This inference-based approach automatically covers:
- All collection types (Set, Map, List)
- String operations
- Array operations
- User-defined types with update methods

### 6.2 Known Update Operations

For documentation and potential fast-path optimization, here are the known update operations:

**Set:**
- `add(element) -> Set`
- `remove(element) -> Set`
- `union(other) -> Set`
- `intersection(other) -> Set`
- `difference(other) -> Set`

**Map:**
- `put(key, value) -> Map`
- `remove(key) -> Map`
- `merge(other) -> Map`

**List:**
- `append(element) -> List`
- `prepend(element) -> List`
- `concat(other) -> List`
- `set_at(index, element) -> List`
- `remove_at(index) -> List`

**String:**
- `concat(other) -> String`
- `replace(old, new) -> String`
- `substring(start, end) -> String`
- `trim() -> String`
- `upper() -> String`
- `lower() -> String`

**Array:**
- `set_at(index, element) -> Array`
- `append(element) -> Array`
- `resize(new_size) -> Array`

**UDTs:**
- Any method returning the same UDT type
- Functional update syntax (if supported): `record.{field = new_value}`

## 7. Implementation Structure

The analysis integrates into the existing Coex compiler pipeline as a new pass between semantic analysis and code generation.

### 7.1 Phase Placement

```
Source → Lexer → Parser → AST Construction → Type Checking → 
  → Uniqueness Analysis (NEW) → Code Generation → LLVM Optimization → Binary
```

The uniqueness analysis requires type information (to identify return types) and produces annotations consumed by code generation.

### 7.2 Data Structures

**UseInfo**: Attached to each AST node representing a variable use.
```
UseInfo:
    binding: Symbol          # The binding being used
    is_last_use: bool        # True if this is definitively the last use
    is_update_receiver: bool # True if this is the receiver of an update method
```

**UpdateCandidate**: Identifies a statement eligible for wrapper mutation.
```
UpdateCandidate:
    statement: AssignmentNode
    receiver_binding: Symbol
    method_name: str
    receiver_type: Type
    can_mutate_in_place: bool
```

**FunctionAnalysis**: Per-function analysis results.
```
FunctionAnalysis:
    update_candidates: List[UpdateCandidate]
    binding_liveness: Map[Symbol, Set[ProgramPoint]]  # For debugging/verification
```

### 7.3 Algorithm Outline

```
function analyze_function(func: FunctionNode) -> FunctionAnalysis:
    # Phase 1: Build control flow graph
    cfg = build_cfg(func.body)
    
    # Phase 2: Compute liveness (standard backward dataflow)
    liveness = compute_liveness(cfg)
    
    # Phase 3: Identify last uses
    for each use in all_uses(func.body):
        use.is_last_use = not live_after(use.program_point, use.binding, liveness)
    
    # Phase 4: Find update candidates
    candidates = []
    for each assignment in assignments(func.body):
        if is_update_pattern(assignment):
            # Check: x = x.method(...) where method returns typeof(x)
            receiver_use = get_receiver_use(assignment.rhs)
            if receiver_use.is_last_use and receiver_use.binding == assignment.target:
                if not aliases_with_args(receiver_use.binding, assignment.rhs.args):
                    candidates.append(UpdateCandidate(
                        statement=assignment,
                        receiver_binding=receiver_use.binding,
                        method_name=assignment.rhs.method_name,
                        receiver_type=receiver_use.binding.type,
                        can_mutate_in_place=True
                    ))
    
    return FunctionAnalysis(update_candidates=candidates, ...)

function is_update_pattern(assignment: AssignmentNode) -> bool:
    # Pattern: x = x.method(args...)
    if assignment.rhs is not MethodCall:
        return false
    if assignment.rhs.receiver is not Identifier:
        return false
    if assignment.rhs.receiver.name != assignment.target.name:
        return false
    # Check return type matches receiver type
    if assignment.rhs.method.return_type != assignment.rhs.receiver.type:
        return false
    return true
```

## 8. Code Generation Transformation

### 8.1 Non-Optimized Code Generation (Current)

For `composites = composites.add(mult)`:

```llvm
; Load current wrapper via handle
%old_handle = load i64, %composites_slot
%old_wrapper = call i8* @gc_handle_deref(i64 %old_handle)

; Call immutable add - allocates new HAMT nodes and new wrapper
%new_handle = call i64 @set_add(i64 %old_handle, i64 %mult_val)

; Store new handle
store i64 %new_handle, %composites_slot

; Old wrapper and orphaned HAMT nodes become garbage
```

### 8.2 Optimized Code Generation (Wrapper Mutation)

When the analysis determines the binding is unique:

```llvm
; Load current wrapper via handle (will be mutated)
%handle = load i64, %composites_slot
%wrapper = call i8* @gc_handle_deref(i64 %handle)

; Call update operation that mutates wrapper in place
; This still allocates new HAMT path nodes via structural sharing
; but reuses the wrapper object
call void @set_add_inplace(i8* %wrapper, i64 %mult_val)

; Handle unchanged - no store needed (or store same value for clarity)
; No new wrapper allocated, old HAMT path nodes become garbage
```

### 8.3 Implementation of In-Place Update Operations

Each type needs an in-place variant of its update operations. For Set:

```python
def _implement_set_add_inplace(self):
    """
    set_add_inplace(wrapper: i8*, element: i64) -> void
    
    Mutates wrapper in place:
    1. Compute new HAMT root via standard structural-sharing add
    2. Update wrapper.root to point to new root
    3. Increment wrapper.len
    
    No new wrapper allocated; handle remains valid.
    """
    # Get wrapper fields
    wrapper_ptr = # function argument
    old_root = self.builder.load(self._gep(wrapper_ptr, 0))  # root field
    old_len = self.builder.load(self._gep(wrapper_ptr, 1))   # len field
    element = # function argument
    
    # Compute new root (allocates new path nodes, shares unchanged subtrees)
    hash_val = self._compute_hash(element)
    new_root = self._hamt_insert(old_root, hash_val, element)
    
    # Mutate wrapper in place
    self.builder.store(new_root, self._gep(wrapper_ptr, 0))
    new_len = self.builder.add(old_len, ir.Constant(ir.IntType(64), 1))
    self.builder.store(new_len, self._gep(wrapper_ptr, 1))
    
    # No return value; wrapper mutated in place
    self.builder.ret_void()
```

### 8.4 Type-Agnostic Code Generation

The code generation transformation is uniform across types:

```python
def generate_update_statement(self, stmt: AssignmentNode, candidate: UpdateCandidate):
    if candidate.can_mutate_in_place:
        # Emit in-place mutation
        wrapper_ptr = self.emit_handle_deref(stmt.target)
        inplace_method = self.get_inplace_variant(
            candidate.receiver_type, 
            candidate.method_name
        )
        args = [wrapper_ptr] + self.emit_args(stmt.rhs.args)
        self.builder.call(inplace_method, args)
        # Handle unchanged; no store to binding slot
    else:
        # Emit standard allocating version
        self.generate_standard_update(stmt)

def get_inplace_variant(self, type: Type, method: str) -> Function:
    """
    Returns the in-place variant of an update method.
    Naming convention: {type}_{method}_inplace
    e.g., set_add_inplace, list_append_inplace, string_concat_inplace
    """
    variant_name = f"{type.name.lower()}_{method}_inplace"
    return self.module.get_global(variant_name)
```

## 9. Phased Implementation

The optimization can be implemented in phases of increasing complexity and benefit.

### Phase 1: Wrapper Mutation (Primary Target)

**Scope:** Eliminate wrapper allocation on every update operation when binding is unique.

**Implementation:**
1. Implement uniqueness analysis (CFG, liveness, last-use marking)
2. Implement update pattern detection
3. Add in-place variants for all update operations
4. Modify code generation to emit in-place variants when applicable

**Expected benefit:** Eliminates one allocation per update operation. For the sieve benchmark with ~500,000 `add` calls per segment, this eliminates ~500,000 wrapper allocations.

**Complexity:** Moderate. Requires dataflow analysis infrastructure but no changes to HAMT/tree internals.

### Phase 2: Storage Mutation (Aggressive)

**Scope:** Additionally eliminate HAMT/tree path node allocations when the internal structure is unique.

**Implementation:**
1. Add reference counting or epoch tracking to HAMT/tree nodes
2. Implement destructive variants that mutate unique nodes in place
3. Extend in-place update operations to use destructive internals

**Expected benefit:** Eliminates O(log n) allocations per update on top of Phase 1 savings. For HAMT with 32-way branching, typically 4-7 fewer allocations per `add`.

**Complexity:** High. Requires changes to HAMT/tree implementation and careful handling of structural sharing.

### Recommendation

Implement Phase 1 first. It provides substantial benefit with moderate complexity and doesn't require touching the HAMT internals. Profile after Phase 1 to determine if Phase 2 is necessary—wrapper allocation may be the dominant cost, making Phase 2 unnecessary.

## 10. Soundness Considerations

### 10.1 Correctness Criteria

The transformation is sound if and only if:

1. **Observational equivalence**: No correct Coex program can distinguish between the optimized and unoptimized execution.

2. **No escaped mutations**: If a value escapes (via return, channel, task spawn, or storage in a long-lived structure), it must not be subsequently mutated.

3. **No aliased mutations**: If two bindings reference the same object, mutating through one must not affect observations through the other.

### 10.2 Conservative Approximations

The analysis should err on the side of caution:

1. **Loops**: A use inside a loop is *not* a last use if the binding is live after the loop or if the loop may iterate again. The key insight for the sieve pattern `x = x.add(y)` is that the use of `x` on the RHS is always the last use of the *old* value—the rebinding kills it regardless of loop iteration.

2. **Conditionals**: A use is a last-use only if it's a last-use on all paths.

3. **Function calls**: Unless the callee is analyzed and proven not to retain references, assume arguments escape.

4. **Exceptions/panics**: If a panic can occur between the wrapper mutation and completion, the partially-mutated state could be observable. In Coex, panics terminate the thread, so this is acceptable.

### 10.3 The Loop Case: Why It Works

The sieve's inner loop is:

```coex
while mult < end_val
    composites = composites.add(mult)
    mult = mult + p
~
```

For `composites = composites.add(mult)`:
- The RHS uses `composites` (the old value)
- The LHS rebinds `composites` to the result
- After this statement, the old `composites` is dead—no path exists to its use
- This is true on *every iteration*: each iteration kills the previous value

The analysis correctly identifies this as a last-use because rebinding definitionally kills the previous value. The fact that the statement executes multiple times doesn't change this—each execution's "old value" is the previous execution's "new value," and each old value is dead after its execution.

### 10.4 Testing Strategy

1. **Semantic equivalence tests**: Run benchmarks with optimization disabled and enabled; results must match exactly.

2. **Allocation counting tests**: Verify that optimized code performs fewer allocations.

3. **Adversarial aliasing tests**: Construct scenarios where aliasing could cause unsoundness if not detected.

4. **Loop stress tests**: Test loops with various patterns of use/rebind.

## 11. Integration with Existing Compiler Passes

### 11.1 Type Checker Integration

The type checker must provide:
- Type information for each expression
- Method resolution and return type information
- This enables inference of update operations (method returning same type as receiver)

### 11.2 Warning System Integration

The existing move warnings (`#@ [MOVE] Variable 'x' is not used after...`) are a simpler, syntactic approximation of uniqueness. The dataflow analysis subsumes these warnings:
- Warnings can be generated from analysis results rather than separate logic
- Warnings become more precise (no false positives from conservative syntax-based analysis)

### 11.3 GC Integration

The uniqueness optimization reduces allocation volume, which benefits the GC:
- Fewer objects to trace
- Reduced nursery churn
- Better cache locality

The GC requires no modifications—wrapper mutation doesn't change handle validity or object reachability.

## 12. Implementation Tasks

### Task 1: Implement Control Flow Graph Construction

Build a CFG representation from the AST for a function body. Handle:
- Sequential statements (fall-through edges)
- If/else (branch and merge edges)
- While loops (back edges)
- For loops (back edges)
- Return (edge to exit node)
- Break/continue within loops

Deliverable: `cfg.py` module with `build_cfg(body: List[Statement]) -> CFG`

### Task 2: Implement Liveness Analysis

Standard backward dataflow for liveness:
- GEN[S] = variables used in S
- KILL[S] = variables defined in S
- IN[S] = GEN[S] ∪ (OUT[S] - KILL[S])
- OUT[S] = ∪ IN[successor] for all successors

Iterate to fixed point for loops.

Deliverable: `liveness.py` module with `compute_liveness(cfg: CFG) -> LivenessResult`

### Task 3: Implement Last-Use Marking

Walk AST with liveness results, marking each variable use with `is_last_use`.

Deliverable: `last_use.py` module with `mark_last_uses(func: FunctionNode, liveness: LivenessResult)`

### Task 4: Implement Update Pattern Detection

Identify statements matching `x = x.method(args)` where:
- `method` returns the same type as `x`
- The use of `x` in `x.method(...)` is marked as last-use
- Arguments don't alias `x`

Deliverable: `update_patterns.py` module with `find_update_candidates(func: FunctionNode) -> List[UpdateCandidate]`

### Task 5: Implement In-Place Update Operations

For each type with update operations, implement the in-place variant:

**Set:** `set_add_inplace`, `set_remove_inplace`, etc.
**Map:** `map_put_inplace`, `map_remove_inplace`, etc.
**List:** `list_append_inplace`, `list_prepend_inplace`, etc.
**String:** `string_concat_inplace`, etc.
**Array:** `array_set_at_inplace`, etc.

Each in-place variant:
1. Receives a raw wrapper pointer (already dereferenced from handle)
2. Computes the new internal structure (still using structural sharing)
3. Mutates the wrapper's fields to point to new structure
4. Returns void (wrapper mutated in place)

Deliverable: Updates to `codegen.py` / `hamt.py` / type-specific modules

### Task 6: Implement Code Generation Transformation

Modify code generator to:
- Check UpdateCandidate list for current statement
- Emit call to in-place variant instead of standard method
- Skip handle store (handle unchanged)

Deliverable: Updates to `codegen.py` statement generation

### Task 7: Testing and Validation

- Unit tests for CFG construction
- Unit tests for liveness analysis
- Unit tests for last-use marking (including loop cases)
- Unit tests for update pattern detection
- Integration tests comparing optimized vs. unoptimized output
- Performance benchmarks (sieve of Eratosthenes, List-heavy workloads)

Deliverable: Test suite in `tests/uniqueness/`

## 13. Example: Sieve Transformation

### Original Code

```coex
task sieve_segment(segment_idx: int, start: int, end_val: int, small_primes: [int]) -> int
    composites: Set<int> = {}
    idx = 0
    while idx < small_primes.len()
        p = small_primes.get(idx)
        # ... compute first_mult ...
        mult = first_mult
        while mult < end_val
            composites = composites.add(mult)  # <-- HOT PATH
            mult = mult + p
        ~
        idx = idx + 1
    ~
    # ... count primes ...
~
```

### Analysis Results

For the inner loop statement `composites = composites.add(mult)`:

1. Pattern match: `x = x.method(args)` where `x` is `composites`, `method` is `add`
2. Type check: `Set.add` returns `Set` — same type as receiver ✓
3. Liveness: After this statement, the *old* `composites` is dead (rebinding kills it)
4. Last-use: The RHS use of `composites` is the last use of the old value ✓
5. Aliasing: `mult` is an `int` (value type), cannot alias `composites` ✓
6. Conclusion: **eligible for wrapper mutation**

### Generated Code (Before Optimization)

```llvm
loop_body:
  ; Load handle and deref to get wrapper
  %old_handle = load i64, ptr %composites_slot
  %old_wrapper = call ptr @gc_handle_deref(i64 %old_handle)
  
  ; Load mult value
  %mult_val = load i64, ptr %mult_slot
  
  ; Call set_add - allocates new wrapper + new HAMT path nodes
  %new_handle = call i64 @set_add(i64 %old_handle, i64 %mult_val)
  
  ; Store new handle
  store i64 %new_handle, ptr %composites_slot
  
  ; ... continue loop ...
```

### Generated Code (After Optimization)

```llvm
loop_body:
  ; Load handle and deref to get wrapper
  %handle = load i64, ptr %composites_slot
  %wrapper = call ptr @gc_handle_deref(i64 %handle)
  
  ; Load mult value
  %mult_val = load i64, ptr %mult_slot
  
  ; Call set_add_inplace - mutates wrapper, still allocates HAMT path nodes
  call void @set_add_inplace(ptr %wrapper, i64 %mult_val)
  
  ; Handle unchanged - no store needed
  
  ; ... continue loop ...
```

### Expected Performance Impact

**Phase 1 (Wrapper Mutation):**
- Wrapper allocations: ~500,000 → 0 per segment
- HAMT path allocations: unchanged (~500,000 × 5 nodes = ~2,500,000)
- Expected improvement: significant reduction in allocation overhead

**Phase 2 (Storage Mutation, if implemented):**
- HAMT path allocations: ~2,500,000 → near 0 (most nodes mutated in place)
- Expected improvement: dramatic further reduction

## 14. Future Extensions

### 14.1 Escape Analysis Integration

Combine uniqueness analysis with escape analysis:
- Values that don't escape can use task-local allocation
- Values that don't escape and are mutated in-place need no GC tracking until they escape

### 14.2 Interprocedural Analysis

Extend analysis across function boundaries:
- Track whether callees retain references to parameters
- Enable uniqueness to propagate through function calls
- Potentially enable in-place updates across call boundaries

### 14.3 Concurrent Uniqueness

For values transferred between tasks via channels:
- Track that send consumes the value (sender loses uniqueness)
- Receiver gains unique reference
- Enable in-place updates in receiver

## 15. Appendix: Formal Semantics

For those desiring a more rigorous treatment, the uniqueness analysis can be formalized as an abstract interpretation.

### Abstract Domain

```
AbstractState = Binding → Uniqueness
Uniqueness = { Unique, Shared, ⊥ }
```

With ordering: `⊥ ⊑ Unique ⊑ Shared`

### Abstract Operations

**Fresh allocation:** `alloc() → Unique`

**Assignment (copy):** 
```
x = y  →  state' where
    state'[x] = state[y]
    state'[y] = Shared  (if state[y] was Unique, now shared)
```

**Rebinding (update pattern):**
```
x = x.method(args)  →  state' where
    state'[x] = Unique  (old value consumed, new value fresh)
    # if state[x] was Unique, the wrapper can be mutated
```

**Control flow join:**
```
join(state1, state2)[b] = lub(state1[b], state2[b])
```

### Optimization Condition

The wrapper mutation optimization applies when:
```
state[x] = Unique  at the point of  x = x.method(args)
```

This is equivalent to saying the RHS use of `x` is a last-use.
