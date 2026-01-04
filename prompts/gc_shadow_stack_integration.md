# Prompt: Complete Shadow Stack GC Integration for Coex Compiler

## Background

The Coex compiler had a garbage collector that used conservative stack scanning, which caused segfaults on Linux due to platform-specific stack layout assumptions. We've implemented a new **shadow stack GC** that explicitly tracks roots, avoiding any platform-specific behavior.

The GC runtime infrastructure is complete and all 402 tests pass, but **`gc_collect()` is currently a no-op** because codegen doesn't yet push/pop shadow stack frames or register roots. Your task is to integrate the shadow stack with codegen to enable actual garbage collection.

## Current State

### What's Implemented (`coex_gc.py`)

1. **Shadow Stack Frame Structure:**
   ```
   GCFrame: { i8* parent, i64 num_roots, i8** roots }
   ```
   - Linked list of frames, `gc_frame_top` points to current frame

2. **Allocation Tracking:**
   - All allocations go through `gc_alloc(size, type_id)`
   - Each allocation has 16-byte header: `{ i64 size, i32 type_id, i32 flags }`
   - Allocations tracked in linked list via `gc_alloc_list`

3. **GC Functions (all implemented):**
   - `gc_push_frame(num_roots, roots) -> frame_ptr` - Push frame onto shadow stack
   - `gc_pop_frame(frame_ptr)` - Pop frame from shadow stack
   - `gc_set_root(roots, index, value)` - Update a root slot
   - `gc_mark_object(ptr)` - Mark object as live (sets FLAG_MARK_BIT)
   - `gc_scan_roots()` - Walk shadow stack, mark all roots
   - `gc_sweep()` - Free unmarked objects from allocation list
   - `gc_collect()` - **Currently no-op** - needs to call scan_roots then sweep

4. **Helper Methods for Codegen:**
   ```python
   gc.create_frame_roots(builder, num_roots) -> i8**  # Alloca array of root slots
   gc.push_frame(builder, num_roots, roots) -> frame  # Call gc_push_frame
   gc.pop_frame(builder, frame)                       # Call gc_pop_frame
   gc.set_root(builder, roots, index, value)          # Call gc_set_root
   ```

### What's Disabled

In `_implement_gc_collect()`, the mark-sweep is commented out:
```python
def _implement_gc_collect(self):
    # Currently just returns - enable when root tracking is ready
    builder.ret_void()

    # The full implementation (enable when ready):
    # builder.call(self.gc_scan_roots, [])
    # builder.call(self.gc_sweep, [])
```

## What Needs to Be Done

### Step 1: Identify Heap Pointer Variables

Create a helper function to determine if a type is heap-allocated:
```python
def _is_heap_type(self, type_annotation) -> bool:
    """Return True if this type is heap-allocated and needs GC tracking"""
    # Heap types: List, Array, String, Map, Set, Channel, user-defined types
    # Stack types: int, float, bool, tuples of stack types
```

Types that need tracking:
- `List<T>`, `Array<T>`, `Map<K,V>`, `Set<T>`, `string`, `Channel<T>`
- User-defined types (all are heap-allocated)
- NOT: `int`, `float`, `bool`, `byte`, `char`, tuples of primitives

### Step 2: Modify `_generate_function()` (around line 7140)

For each function that contains heap pointer locals:

```python
def _generate_function(self, func: FunctionDecl):
    # ... existing setup code ...

    # NEW: Count heap pointer parameters and locals
    heap_vars = []  # List of (var_name, root_index)

    # Check parameters
    for param in func.params:
        if self._is_heap_type(param.type_annotation):
            heap_vars.append(param.name)

    # Analyze body for heap-typed var declarations
    for stmt in func.body:
        if isinstance(stmt, VarDecl) and self._is_heap_type(stmt.type_annotation):
            heap_vars.append(stmt.name)

    # Create shadow stack frame if needed
    gc_frame = None
    gc_roots = None
    if heap_vars and self.gc is not None:
        num_roots = len(heap_vars)
        gc_roots = self.gc.create_frame_roots(self.builder, num_roots)
        gc_frame = self.gc.push_frame(self.builder, num_roots, gc_roots)

        # Store mapping of var_name -> root_index
        self.gc_root_indices = {name: i for i, name in enumerate(heap_vars)}

    # ... existing parameter handling ...
    # ... existing body generation ...

    # NEW: Pop frame before each return
    # (Need to modify return handling - see Step 4)
```

### Step 3: Modify `_generate_var_decl()` and `_generate_assignment()`

When storing a heap pointer to a tracked local:

```python
def _generate_var_decl(self, stmt: VarDecl):
    # ... existing code to generate value ...

    # NEW: Update GC root if this is a heap type
    if hasattr(self, 'gc_root_indices') and stmt.name in self.gc_root_indices:
        root_idx = self.gc_root_indices[stmt.name]
        self.gc.set_root(self.builder, self.gc_roots, root_idx, value)

    # ... existing store code ...
```

Similarly for `_generate_assignment()` when assigning to a tracked variable.

### Step 4: Handle All Return Paths

Every `return` statement must pop the GC frame before returning:

```python
def _generate_return(self, stmt: ReturnStmt):
    # Generate return value first
    if stmt.value:
        ret_val = self._generate_expression(stmt.value)

    # NEW: Pop GC frame if we have one
    if hasattr(self, 'gc_frame') and self.gc_frame is not None:
        self.gc.pop_frame(self.builder, self.gc_frame)

    # Now return
    if stmt.value:
        self.builder.ret(ret_val)
    else:
        self.builder.ret_void()
```

Also handle implicit returns at function end.

### Step 5: Enable gc_collect()

Once root tracking is working, update `_implement_gc_collect()`:

```python
def _implement_gc_collect(self):
    func = self.gc_collect
    entry = func.append_basic_block("entry")
    builder = ir.IRBuilder(entry)

    # Disable GC during collection (prevent recursion)
    builder.store(ir.Constant(self.i1, 0), self.gc_enabled)

    # Mark phase
    builder.call(self.gc_scan_roots, [])

    # Sweep phase
    builder.call(self.gc_sweep, [])

    # Re-enable GC
    builder.store(ir.Constant(self.i1, 1), self.gc_enabled)

    builder.ret_void()
```

## Key Files

- `coex_gc.py` - GC runtime implementation (shadow stack ready)
- `codegen.py` - Main code generator (~12,000 lines)
  - `_generate_function()` - Line ~7140
  - `_generate_var_decl()` - Search for it
  - `_generate_assignment()` - Search for it
  - `_generate_return()` - Search for it

## Testing Strategy

1. **Start with existing GC tests:**
   ```bash
   python3 -m pytest tests/test_gc.py -v --tb=short
   ```
   These currently pass because gc_collect is a no-op. After enabling, they should still pass.

2. **Create a test that verifies collection actually happens:**
   ```coex
   func main() -> int
       # Create garbage
       for i in 0..1000
           var temp: List<int> = [1, 2, 3]
       ~

       gc()  # Should free the garbage

       # Allocate more - should reuse freed memory
       var live: List<int> = [4, 5, 6]
       print(live.len())
       return 0
   ~
   ```

3. **Run stress tests:**
   ```bash
   ./examples/stress_array_1m
   ```

4. **Test on Linux** to verify the cross-platform fix works.

## Gotchas and Warnings

1. **Don't forget implicit returns** - Functions without explicit return still need frame pop

2. **Handle early returns** - `break`/`continue` don't need frame pop, but `return` does

3. **Nested function calls** - Each function manages its own frame; frames chain correctly

4. **Parameter copies** - Parameters are deep-copied at function entry; the copy needs to be rooted, not the original

5. **Reassignment** - When a heap variable is reassigned, call `set_root` with the new value

6. **Null pointers** - `gc_mark_object` already handles null; `set_root` with null is fine

7. **The `gc_roots` array is stack-allocated** - It's valid for the function's lifetime

8. **Formula functions** - These are pure and may not need GC frames (optimization opportunity)

## Success Criteria

- All 402 existing tests pass
- `tests/test_gc.py` passes with collection enabled
- Memory is actually reclaimed (verify with a test that allocates, collects, allocates more)
- No segfaults on Linux
- Stress tests complete successfully
