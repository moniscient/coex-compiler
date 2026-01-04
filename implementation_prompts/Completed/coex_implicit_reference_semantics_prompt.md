# Coex Implicit Reference Semantics Implementation

## Overview

Coex enforces heap immutability as a foundational invariant: once an object is allocated on the heap, its contents cannot change. This guarantee enables a profound simplification of value semantics: since no binding can observe mutations through another binding (because there are no mutations), physical copying becomes unnecessary for correctness. The programmer continues thinking in terms of independent values, while the runtime passes references everywhere.

This prompt directs you to modify `codegen.py` to implement **implicit reference semantics** for all heap-allocated types. The observable semantics remain unchanged (value semantics from the programmer's perspective), but the implementation passes references rather than copying data. This is a pure optimization that exploits immutability.

**Current state:** We are using single-threaded pointer-based GC (not handle-based). All changes should work with direct pointers and the existing shadow stack GC infrastructure.

## The Core Insight

In a mutable system, the distinction between "pass by value" (copy) and "pass by reference" (share) matters because aliasing can cause spooky action at a distance. Two bindings to the same mutable object can observe each other's modifications.

In an immutable system, this distinction evaporates. Two bindings to the same immutable object behave identically to two bindings to independent copies—neither can observe mutations because mutations don't exist. The programmer's mental model (value semantics) is preserved regardless of whether we copy or share.

## Scope of Changes

### 1. Function Parameter Passing (Eliminate Entry Copies)

**Current behavior:** When a function receives a heap-allocated parameter, `_generate_function` and `_monomorphize_function` call `_needs_parameter_copy()` and `_generate_deep_copy()` to create an independent copy at function entry.

**New behavior:** Never copy heap objects at function entry. The callee receives the same pointer the caller provided. Since the callee cannot mutate the object, this is semantically identical to copying.

**Files to modify:** `codegen.py`

**Functions to modify:**
- `_needs_parameter_copy()`: Should return `False` for all types. Keep the function for documentation but have it always return False.
- `_generate_function()`: Remove the parameter copying logic (lines ~9411-9414)
- `_monomorphize_function()`: Remove the parameter copying logic (lines ~8626-8628)

**Code change pattern:**
```python
def _needs_parameter_copy(self, coex_type: Type) -> bool:
    """Check if a parameter type needs to be copied on function entry.
    
    With immutable heap semantics, function parameters never need copying.
    The callee receives a reference to the same immutable object, which is
    semantically identical to receiving an independent copy.
    
    This function is retained for documentation; it always returns False.
    """
    return False
```

### 2. Assignment Semantics (Unify `=` and `:=` for Heap Objects)

**Current behavior:** 
- `=` triggers deep copy via `_generate_deep_copy()`
- `:=` triggers `_generate_move_or_eager_copy()` which already just returns the value

**New behavior:**
- Both `=` and `:=` simply share the reference for heap objects
- `:=` continues to invalidate the source binding (use-after-move check) as programmer intent documentation
- The deep copy path is eliminated for normal assignment

**Functions to modify:**
- `_generate_deep_copy()`: For heap types, simply return the value unchanged. Keep recursive structure for documentation but make it a no-op.
- `_generate_assignment()`: Remove the copy/move distinction for heap objects (the existing code paths converge)
- `_generate_var_decl()`: Similar simplification

**Key locations in `_generate_assignment()` (~lines 10037-10067):**
```python
# Current code calls _generate_deep_copy or _generate_move_or_eager_copy
# New code: for heap types, just use the value directly

if coex_type and self._is_heap_type(coex_type):
    # Immutable heap: sharing reference is equivalent to copying
    # No copy needed; GC keeps object alive while reachable
    pass  # value remains unchanged
elif coex_type and isinstance(coex_type, NamedType) and coex_type.name in self.type_fields:
    # User-defined types on heap: same treatment
    pass
# ... rest of assignment logic
```

### 3. Collection Copy Functions (Make Them Identity)

The runtime functions like `list_copy`, `set_copy`, `map_copy`, `array_copy`, and `string_copy` should become identity functions that simply return their input. Some already do this (like `string_copy`).

**Functions to modify in codegen.py:**

For each `_implement_*_copy` function, ensure it returns the source pointer unchanged:

```python
def _implement_list_copy(self):
    """List copy returns the same pointer - lists are immutable and GC-managed.
    
    Since lists are immutable (mutation operations return new lists),
    there's no need to deep copy. The GC keeps the list alive as long as
    it's reachable. This enables efficient structural sharing.
    """
    func = self.list_copy
    func.args[0].name = "src"
    
    entry = func.append_basic_block("entry")
    builder = ir.IRBuilder(entry)
    
    # Simply return the same pointer - GC handles memory
    builder.ret(func.args[0])
```

Apply this pattern to:
- `_implement_list_copy()` 
- `_implement_set_copy()` (already returns value in some paths)
- `_implement_map_copy()` (verify current behavior)
- `_implement_array_copy()`

Note: `_implement_string_copy()` already does this correctly (lines 2917-2931).

### 4. Deep Copy Functions (Convert to Identity)

The `_generate_*_deep_copy` helper functions should become identity operations:

- `_generate_list_deep_copy()` → return `src` unchanged
- `_generate_set_deep_copy()` → return `src` unchanged  
- `_generate_array_deep_copy()` → return `src` unchanged
- `_generate_type_deep_copy()` → return `value` unchanged

The recursive infrastructure can be retained but short-circuited at the top level:

```python
def _generate_list_deep_copy(self, src: ir.Value, elem_type: Type) -> ir.Value:
    """Deep copy a list.
    
    With immutable heap semantics, deep copy is unnecessary.
    Sharing the reference is semantically equivalent.
    """
    return src
```

### 5. The Master `_generate_deep_copy()` Function

This is the main dispatch point. Modify it to return values unchanged for heap types:

```python
def _generate_deep_copy(self, value: ir.Value, coex_type: Type) -> ir.Value:
    """Generate code to 'deep-copy' a value based on its Coex type.
    
    With immutable heap semantics, heap-allocated values don't need copying.
    Sharing references is semantically equivalent to copying because no
    binding can observe mutations through another binding.
    
    Primitives remain unchanged (they're already value types).
    Heap types (strings, collections, user types) return unchanged.
    """
    # Primitives have value semantics already (stack-allocated)
    if self._is_primitive_coex_type(coex_type):
        return value
    
    # All heap types: no copy needed, return as-is
    # Includes: String, List, Set, Map, Array, user-defined types
    return value
```

### 6. Retain Move Semantics Tracking (`:=` Operator)

The `:=` operator serves a documentation purpose: it signals that the programmer is "done" with the source binding. Continue tracking moved variables and reporting use-after-move errors, but don't change the actual code generation (which already just passes the reference).

The existing `moved_vars` set and use-after-move checking in `_generate_assignment()` should remain:

```python
# Mark source as moved AFTER we've read its value
if move_source_name:
    self.moved_vars.add(move_source_name)
```

And the check in `_generate_expression()` for `Identifier`:
```python
if name in self.moved_vars:
    raise RuntimeError(f"Use of moved variable '{name}'")
```

### 7. Verify GC Root Tracking Remains Correct

The shadow stack GC infrastructure must continue to work correctly. When a function receives a heap pointer (now without copying), that pointer must still be registered as a GC root.

Verify that in `_generate_function()` and `_monomorphize_function()`:
1. Heap parameters are still detected via `_is_heap_type()`
2. Parameters are still registered in `gc_root_indices`
3. `gc.set_root()` is still called with the parameter value

The key change is that `param_value` is now just `llvm_param` (no copy), but the GC registration remains the same:

```python
# Allocate parameters (no copy needed for heap types due to immutability)
for i, param in enumerate(func.params):
    llvm_param = llvm_func.args[i]
    llvm_param.name = param.name
    
    # No deep copy needed - immutable heap guarantees value semantics
    param_value = llvm_param
    
    alloca = self.builder.alloca(llvm_param.type, name=param.name)
    self.builder.store(param_value, alloca)
    self.locals[param.name] = alloca
    
    # Register parameter as GC root if it's a heap type
    # (unchanged - still needed for GC correctness)
    if param.name in self.gc_root_indices and self.gc is not None:
        root_idx = self.gc_root_indices[param.name]
        self.gc.set_root(self.builder, self.gc_roots, root_idx, param_value)
```

## Implementation Order

1. **Start with `_needs_parameter_copy()`**: Make it return `False` unconditionally. This is the simplest change and immediately eliminates parameter copying.

2. **Modify `_generate_deep_copy()`**: Have it return the value unchanged for all heap types. This is the central dispatch point.

3. **Update the `_implement_*_copy()` runtime functions**: Make `list_copy`, `set_copy`, `map_copy`, `array_copy` return their input unchanged (like `string_copy` already does).

4. **Simplify `_generate_*_deep_copy()` helpers**: Convert to identity functions.

5. **Clean up `_generate_assignment()` and `_generate_var_decl()`**: Remove now-dead code paths that distinguish copy vs. move for heap types.

6. **Verify GC integration**: Run tests to ensure GC roots are still tracked correctly and no memory leaks occur.

## Testing Strategy

After implementation, verify:

1. **Basic correctness**: Programs that use assignment and function calls produce the same output as before.

2. **Value semantics preserved**: Modifying a "copy" through mutation operations still produces independent results:
   ```coex
   a = [1, 2, 3]
   b = a           # b shares reference with a
   b = b.append(4) # b now points to NEW list [1,2,3,4]
   # a still points to [1,2,3] - value semantics preserved
   ```

3. **GC correctness**: Objects remain alive while referenced, are collected when unreachable.

4. **Move semantics**: Use-after-move still raises compile errors.

5. **Performance**: Large structure passing should be dramatically faster (O(1) vs O(n)).

## Documentation Updates

After implementation, update comments in `codegen.py` to reflect the new semantics:

- Document that value semantics are implemented via reference sharing due to immutability
- Explain that `=` and `:=` are semantically equivalent for heap objects
- Note that `:=` serves as programmer intent documentation (source binding invalidation)
- Reference the heap immutability invariant as the enabling feature

## What NOT to Change

- **Primitive types**: `int`, `float`, `bool`, `byte`, `char` remain value types (stack-allocated). No changes needed.
- **Tuple handling**: Tuples are stack-allocated aggregates. Their current handling is correct.
- **Mutation operations**: Operations like `list.append()`, `map.set()`, etc. must continue to return NEW objects. This is what makes reference sharing safe.
- **Use-after-move checking**: Continue enforcing this for `:=` operator.
- **GC shadow stack**: The infrastructure remains unchanged; only the values being tracked change (references instead of copies).

## Summary of Key Code Changes

| Location | Current | New |
|----------|---------|-----|
| `_needs_parameter_copy()` | Returns True for heap types | Returns False always |
| `_generate_deep_copy()` | Dispatches to copy functions | Returns value unchanged |
| `_generate_list_deep_copy()` | Builds new list with copied elements | Returns src unchanged |
| `_implement_list_copy()` | Creates new list structure | Returns src unchanged |
| `_implement_array_copy()` | Copies array data | Returns src unchanged |
| Function parameter handling | Copies heap parameters | Uses parameters directly |
| `_generate_assignment()` | Different paths for copy/move | Unified path (reference sharing) |

## Expected Benefits

1. **Performance**: Function calls with large structures become O(1) instead of O(n)
2. **Memory**: Reduced allocation pressure from eliminated copies
3. **Simplicity**: Codegen logic simplifies significantly
4. **Consistency**: All heap types handled uniformly

The programmer-visible semantics remain unchanged. This is a pure internal optimization enabled by the immutability guarantee.
