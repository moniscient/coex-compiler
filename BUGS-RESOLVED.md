# Coex Resolved Bugs Archive

This file contains bugs that have been fixed or resolved. They are moved here from BUGS.md to reduce context size when working on active bugs.

---

### BUG-129: Unrooted intermediate string concat results crash under GC compaction
- **Discovered**: 2026-02-12, during BREP torus octree demo
- **Category**: Codegen
- **Severity**: Critical
- **Reproduction**: Compile and run a program with deep recursive string concatenation + UDT field access that creates enough allocation pressure for 2+ GC cycles during expression evaluation. Minimal reproducer: depth-4 octree with `bbox_center` + `bbox_size` calls producing 4096 leaves with string concat chains.
- **Observed**: Segfault in `coex_string_concat + 32` (ldp from stale pointer to unmapped TLAB memory). Crash is at FIRST access to argument `a` inside `coex_string_concat` — the pointer is already stale when entering the function.
- **Expected**: String concatenation chains should work under arbitrary GC pressure.
- **Root cause**: In `generate_binary()`, `left = generate_expression(expr.left)` produces a raw `struct.String*`. Then `right = generate_expression(expr.right)` may allocate (e.g., `String.from()`, string literals), triggering GC+compaction. Compaction copies left's object to compact buffer and frees the old TLAB. The raw pointer in the LLVM register still points to the old (now unmapped) TLAB location. For chained concats `a + b + c`, the intermediate `a + b` result is a raw pointer not in any shadow stack slot.
- **Fix**: Two-part fix: (1) In `codegen/expressions.py:generate_binary()`, save left's handle via `gc_ptr_to_handle` before evaluating right, then re-derive via `gc_handle_deref` after. (2) In `coex_gc.py`, widen sweep grace period from -1 to -2 so unrooted intermediates survive 2 GC cycles (enough for any realistic expression chain).
- **Files**: codegen/expressions.py, coex_gc.py
- **Status**: Fixed (2026-02-12)

---

### BUG-130: Multiple stale pointer paths in UDT constructor and method calls under GC pressure
- **Discovered**: 2026-02-12, during BREP torus progressive demo (generation 4+ crash)
- **Category**: Codegen / GC
- **Severity**: Critical
- **Reproduction**: Run `examples/brep_torus.coex` — crashes at generation 4-5 during `subdivide_one_level` or `evaporate` with deep recursive UDT trees under GC compaction pressure.
- **Observed**: Three interrelated issues found:
  1. **Constructor stale pointer**: `_generate_type_constructor` evaluates ALL field expressions before allocating. Evaluating a LATER arg (e.g., `[]` which calls list_new) can trigger GC+compaction, making an EARLIER arg's raw pointer (e.g., BBox*) stale.
  2. **List.append stale obj**: In `generate_method_call` for `.append()`, the list object pointer `obj` is evaluated BEFORE the element expression. If the element triggers GC, `obj` becomes stale.
  3. **Missing function return type inference**: `_infer_coex_type_from_initializer` didn't look up `func_decls` for function call return types.
- **Fix**: Handles-everywhere refactoring (2026-02-13) — All non-primitive types are now i64 GC handles everywhere. Constructor args, method objects, and function results are all i64 handles that remain stable across GC cycles. No raw pointers exist to become stale. The original band-aid fixes (save-handle-before-next-arg-eval) are subsumed by the uniform i64 representation.
- **Files**: `codegen/core.py`, `codegen/expressions.py`, `codegen/statements.py`
- **Status**: Fixed (2026-02-13) — resolved by handles-everywhere refactoring

---

### BUG-127: Task returning float/double crashes with invalid ptrtoint cast
- **Discovered**: 2026-02-12, during math builtins implementation
- **Category**: Codegen
- **Severity**: High
- **Reproduction**: `task compute(x: float) -> float: return sin(x) ~` — any task returning float
- **Observed**: LLVM IR error: `invalid cast opcode for cast from 'double' to 'i64'` via `ptrtoint`
- **Expected**: Float return values should be bitcast (not ptrtoint) to i64 for task result storage
- **Fix**: Added `DoubleType`/`FloatType` handling (fpext+bitcast) in `task_transform.py` (3 sites) and `codegen/thread.py` (1 site). The receive side already had the correct bitcast-from-i64 at entry function line 2624.
- **Files**: task_transform.py, codegen/thread.py
- **Status**: Fixed (2026-02-12)

---

### BUG-124: List append through helper function segfaults at high iteration count
- **Discovered**: 2026-02-11, during frame pool verification testing
- **Category**: GC
- **Severity**: High
- **Reproduction**: `func helper(x: [int]) -> [int]; return x.append(1) ~` called 200K times in a loop: `x = helper(x)`. Works at 1K iterations, segfaults at 200K.
- **Observed**: Segmentation fault (signal 11) after ~33K-90K iterations (non-deterministic, varies with GC timing)
- **Root cause**: Birth-marking race condition + unrooted return value window.
  1. **Birth-marking race**: `gc_alloc` reads `gc_current_mark_value` with seq_cst, and the GC thread increments it with seq_cst. In the total order, the mutator's read CAN happen before the GC increment, giving the object generation value M-1 instead of M. Sweep checked `gen >= current_mark (M)`, so M-1 < M → object swept as garbage.
  2. **Unrooted window**: Between callee's `gc_segment_pop` and caller's `gc_segment_set_root`, the returned list handle is in NO shadow stack. Combined with the race, the object is neither rooted nor birth-marked → swept.
  3. **Handle retirement**: `gc_handle_retire` immediately overwrites the handle table entry. When caller later calls `gc_ptr_to_handle` on the returned pointer, the forward field reads from freed/zeroed memory → returns 0 → segfault.
- **Fix**: Changed sweep check from `gen >= current_mark` to `gen >= current_mark - 1` (one-generation grace period). Race victims with generation M-1 survive current cycle (M-1 >= M-1). Cost: objects may survive one extra cycle (minor floating garbage). Also fixed stale pointer bugs in `list_new` (handle save/re-derive between two allocations) and `list_append` merge block (re-derive from handle after list_new call).
- **Files**: coex_gc.py (sweep check at line ~6884), codegen/list.py (list_new, list_append)
- **Tests**: tests/test_bug124_list_helper.py (6 tests)
- **Status**: Fixed (2026-02-12)

---

### BUG-126: Bare field access in UDT methods broken when variable uses handle-storing alloca
- **Discovered**: 2026-02-12, during BUG-125 test development
- **Category**: Codegen
- **Severity**: Medium
- **Reproduction**: `type Accum: total: int; func add_and_get(n: int) -> int; return total + n ~; ~` — compile error: `Type of #1 arg mismatch: i64 != %"struct.Accum"*`
- **Root cause**: `method_uses_self()` only checked for explicit `self` or `SelfExpr` references. Bare field names like `total` (which resolve to implicit `self.total` at codegen time) were not detected, causing the method to be incorrectly declared as static (no `self` parameter). At the call site, the caller passed the UDT object as first arg to a function that didn't expect it → type mismatch.
- **Fix**: Added `field_names` parameter to `method_uses_self()`. When an `Identifier` matches a field name of the enclosing type, the method is treated as instance (non-static). Conservative — a local variable shadowing a field name causes a false positive (unused self param) rather than a false negative (crash).
- **Files**: codegen/functions.py (method_uses_self, declare_type_methods), codegen/core.py (_method_uses_self)
- **Status**: Fixed (2026-02-12)

---

### BUG-125: UDT method `self` pointer not GC-tracked — stale pointer after compaction
- **Discovered**: 2026-02-12, during UDT implementation audit
- **Category**: GC
- **Severity**: Critical
- **Reproduction**: Any UDT method that accesses `self.field` after an allocation that triggers GC compaction. E.g., a method that creates a new list/string then reads `self.name`.
- **Observed**: `self` is stored as a raw pointer in an alloca. After GC compaction moves the UDT object and deferred TLAB munmap frees the old memory, accessing `self.field` dereferences a stale pointer → SIGSEGV.
- **Expected**: `self` should be tracked as a GC handle in the shadow stack and re-derived via `gc_handle_deref` on every access, like all other reference-type variables.
- **Root cause**: Two separate but related issues:
  1. **Non-generic method path** (`generate_type_methods`, functions.py): Had NO GC frame at all — no `push_frame`, no `gc_root_indices`, no `var_ptr_types`. Neither `self` nor any heap-type parameters were protected.
  2. **Monomorphized method path** (`generate_method_body`, functions.py): Had a GC frame but explicitly skipped `self`. Parameters got handle storage but `self` did not.
  3. **SelfExpr** (expressions.py): `cg.builder.load(cg.locals["self"])` loaded the raw stale pointer without re-derivation.
  4. **Implicit field access** (expressions.py): `self_ptr = cg.builder.load(cg.locals["self"])` then GEPs — same stale pointer issue.
- **Fix**: Added full GC shadow stack frame to both method codegen paths. `self` is now stored as a handle-storing i64 alloca in `var_ptr_types`, with `_store_var_handle`/`_load_var_ptr` for handle↔pointer conversion. SelfExpr and implicit field access check `var_ptr_types` and re-derive via `gc_handle_deref`. Also discovered pre-existing BUG-126 (bare field access broken with handle allocas).
- **Files**: codegen/functions.py, codegen/expressions.py
- **Status**: Fixed (2026-02-12)

---

### BUG-123: Galaxian ~3MB/min memory leak from alloc_node malloc/free churn
- **Discovered**: 2026-02-11, during Galaxian memory leak investigation
- **Category**: GC
- **Severity**: Medium
- **Reproduction**: Run Galaxian game, monitor RSS. Memory grows ~3MB/min during gameplay.
- **Observed**: RSS increases steadily. GC reclamation works correctly (live_objects stable), but ~600K malloc(32)/free() calls/sec for alloc_nodes cause macOS libmalloc to retain freed heap pages.
- **Expected**: Steady-state memory usage after initial warmup period
- **Root cause**: Every `gc_alloc` mallocs a 32-byte alloc_node struct, and every sweep frees it. macOS libmalloc retains freed heap pages in its arena (RSS doesn't decrease).
- **Fix**: Added lock-free alloc_node pool using CAS-based free list. `gc_alloc_node_pop` tries pool before malloc; `gc_alloc_node_push` returns swept nodes to pool instead of freeing. Eliminates ~600K malloc/free cycles/sec.
- **Files**: coex_gc.py (globals, pop/push functions, gc_alloc, gc_sweep, gc_dump_stats)
- **Status**: Fixed (2026-02-11)

---

### BUG-121: llvmlite `.ordering` attribute silently ignored on plain loads + mixed atomic/non-atomic UB
- **Discovered**: 2026-02-11, during Linux CI crash investigation of `test_gc_auto_trigger_multiple_cycles`
- **Category**: GC
- **Severity**: Critical
- **Reproduction**: Run `test_gc_auto_trigger_multiple_cycles` on Linux x86-64 CI — crashes silently with empty output
- **Observed**: Three instances of `load.ordering = 'acquire'` on plain `builder.load()` results produced plain (non-atomic) loads in the emitted IR. TLAB live_count re-checks before munmap were non-atomic → LLVM could optimize away re-checks → munmap of in-use TLABs → SIGSEGV. Additionally, `gc_compacting` and `gc_alloc_count` were read with plain loads from mutator threads while written atomically from the GC thread — mixed atomic/non-atomic access is UB under C11.
- **Expected**: Atomic ordering attributes should produce atomic load instructions in generated IR
- **Fix**: 6 instances fixed:
  - 3x `recheck_live.ordering = 'acquire'` → `builder.load_atomic(ptr, ordering='acquire', align=8)` (TLAB live_count in gc_sweep, gc_compact_deferred_cleanup, gc_compact_impl)
  - 1x `builder.load(gc_compacting)` → `builder.load_atomic(gc_compacting, ordering='acquire', align=8)` (safepoint)
  - 1x `builder.load(gc_alloc_count)` → `builder.load_atomic(gc_alloc_count, ordering='monotonic', align=8)` (safepoint)
  - 1x `builder.load(gc_compacting)` → `builder.load_atomic(gc_compacting, ordering='acquire', align=8)` (handle table grow)
- **Files**: coex_gc.py
- **Status**: Fixed (2026-02-11)

---

### BUG-093: Replace compile-time type inference with runtime TYPE_ID lookup where appropriate
- **Discovered**: 2026-02-04, during Channel fix discussion
- **Category**: Codegen
- **Severity**: Medium
- **Fix**: Added shared `get_runtime_type_id()` helper to `GarbageCollector` class in `coex_gc.py`. Refactored `json_type.py:_get_json_type_id()` to delegate to shared helper. Extracted `_resolve_heap_target_struct()` in `statements.py` with type annotation fallback when compile-time inference fails. Added `_get_struct_for_type_id_const()` mapping in `core.py` for future runtime dispatch.
- **Files**: `coex_gc.py`, `codegen/json_type.py`, `codegen/statements.py`, `codegen/core.py`
- **Status**: Fixed (2026-02-10)

---

### BUG-115: JSON codegen stale-pointer-across-allocation bugs (9 sites)
- **Discovered**: 2026-02-10, during json_type.py audit
- **Category**: Codegen/GC
- **Severity**: High
- **Reproduction**: Any JSON stringify, parse, set_field, to_struct, or list/map conversion under GC pressure
- **Root Cause**: 9 sites in `codegen/json_type.py` derived raw pointers via `gc_handle_deref` then used them across allocating operations. If GC compaction ran during any allocation, the raw pointer became stale.
- **Fix**: Re-derive raw pointers from GC handles after every potentially-allocating call in all 9 sites:
  1. `_stringify_object`: Re-derive `map_ptr`, `keys_list`, `key_str` from handles each loop iteration
  2. `_stringify_array`: Re-derive `list_ptr` from handle each loop iteration
  3. `_pretty_array`: Re-derive `list_ptr` from handle each loop iteration
  4. `_pretty_object`: Re-derive `map_ptr`, `keys_list`, `key_str` from handles each loop iteration
  5. `_implement_json_parse`: Re-derive `data_ptr` from `owner_handle` after `alloc_arena_or_gc` in both array and object parse blocks
  6. `generate_json_to_struct`: Re-derive `map_ptr` and `struct_ptr` from handles in field extraction loop
  7. `_convert_list_runtime_to_json_array`: Save `list_ptr` as handle, re-derive each loop iteration
  8. `convert_map_to_json_object`: Save `keys_list`/`values_list` handles, re-derive each iteration; re-derive `string_key` before `map_set_string`
  9. `_implement_json_set_field`: Move `gc_handle_deref` after `gc_promote_to_heap`
- **Files**: `codegen/json_type.py`
- **Status**: Fixed (2026-02-10)

---

### BUG-099b: Task closure result storage uses raw pointers instead of handles
- **Discovered**: 2026-02-05, during BUG-092 audit
- **Category**: Codegen/GC
- **Severity**: High
- **Reproduction**: Parallel for/first-assign/most-assign returning reference types (strings, lists, etc.) with GC pressure between task completion and result consumption
- **Observed**: `codegen/thread.py` trampoline used `ptrtoint` to store task results in closure. For reference type results, these were raw pointers, not handles. If GC compaction ran between task completion and result consumption, pointers went stale.
- **Root Cause**: Trampoline stored `ptrtoint(result)` for pointer results. TaggedValues in for-assign/most-assign always used `TV_TYPE_INT` regardless of actual return type.
- **Fix**: (1) Trampoline now calls `gc_ptr_to_handle` for heap-type pointer results, storing the handle as i64. (2) Added GC root slot for result handle in trampoline frame. (3) For-assign and most-assign TaggedValues now use `get_tv_type_id(task_decl.return_type)` for correct type tagging.
- **Files**: `codegen/thread.py`, `codegen/loops.py`
- **Status**: Fixed (2026-02-10)
- **Note**: BUG ID 099 was previously used for a different bug (task frame GC roots). This is suffixed 'b' to avoid conflict.

---

### BUG-103: gc_compact() crashes with memory corruption in game loop
- **Discovered**: 2026-02-05, during compiling and running galaxian.coex
- **Category**: GC
- **Severity**: Critical
- **Reproduction**: Auto-play Galaxian (auto-fire every 10 frames) crashes at frame 52 when first enemy destroyed.
- **Observed**: `EXC_BAD_ACCESS (KERN_INVALID_ADDRESS)` in `coex_list_get` — stale raw pointer to munmapped TLAB.
- **Root Cause**: `codegen/list.py` stored tail/root buffer references as raw pointers via `ptrtoint`. After compaction moved buffers, handle table was updated but raw pointers in list struct became stale.
- **Fix**: Converted list root (field 0) and tail (field 3) from raw pointers to GC handles. 3 write sites changed from `ptrtoint` to `gc_ptr_to_handle`, 10 read sites from `inttoptr` to `gc_handle_deref`. Simplified GC mark_list (handles loaded directly, no `inttoptr`+`gc_ptr_to_handle` round-trip). Removed TYPE_LIST from Phase 3b fixup (handles don't need fixup).
- **Files**: `codegen/list.py`, `coex_gc.py`
- **Status**: Fixed (2026-02-09)

---

### BUG-099: GC during scheduler task execution crashes — task frame not traced
- **Discovered**: 2026-02-04, during full test suite run
- **Category**: GC/Runtime
- **Severity**: High
- **Reproduction**: `python3 -m pytest tests/test_task_state_machine.py::TestTaskFrameGC::test_gc_during_task_execution -v --tb=short`
- **Observed**: Execution fails (segfault or corruption) when `gc()` is called inside a scheduler-based `task` that has a live list across a suspension point (`y := inner_task()`)
- **Expected**: GC should trace task frame slots and preserve live objects (list `x` with 5 elements) across suspension and collection
- **Root Cause**: `task_transform.py` set `cg.gc_frame = None` when generating state machine step functions, disabling ALL GC root registration. Heap-typed locals stored in the task frame were invisible to the garbage collector.
- **Fix**: Added GC shadow stack push/pop to step function entry/exit:
  1. At step function entry: push a GC frame and register all heap-typed frame fields as roots
  2. On DONE: pop the GC frame
  3. On SPAWN: intentionally leave the GC frame un-popped so roots remain registered while the child task runs (prevents collection of parent's heap objects)
  4. Zero-initialize all task frames via `memset` after `malloc` so uninitialized pointer fields are null (safe for `gc_ptr_to_handle`)
- **Files**: `task_transform.py`
- **Status**: Fixed (2026-02-04)

### BUG-100: Task frame data not preserved across multiple GC cycles
- **Discovered**: 2026-02-04, during full test suite run
- **Category**: GC/Runtime
- **Severity**: High
- **Reproduction**: `python3 -m pytest tests/test_task_state_machine.py::TestTaskFrameGC::test_frame_survives_gc -v --tb=short`
- **Observed**: Execution fails when a scheduler-based `task` calls `gc()` multiple times while holding a large list (`big_list` with 10 elements) across a suspension point
- **Expected**: Frame data (list handle) should survive multiple GC cycles while the task is suspended
- **Root Cause**: Same as BUG-099 — suspended task frames were not registered as GC roots
- **Fix**: Same fix as BUG-099
- **Files**: `task_transform.py`
- **Status**: Fixed (2026-02-04)
- **Note**: Same underlying fix as BUG-099

---

### BUG-094: Universal C FFI for malloc'd string to Coex heap string conversion
- **Discovered**: 2026-02-04, during FFI review
- **Category**: Runtime/Stdlib
- **Severity**: Medium
- **Reproduction**: Any C FFI call that returns a malloc'd string (cJSON, file I/O, etc.)
- **Observed**: Multiple FFI libraries had ad-hoc implementations for converting C strings to Coex strings, leading to inconsistency and potential memory leaks
- **Root Cause**: No universal C function existed for converting malloc'd C strings to GC-managed Coex strings. The LLVM IR function `string_from_literal` worked but wasn't callable from C code.
- **Fix**: Created universal C runtime functions in `runtime/coex_string.c`:
  1. `coex_string_from_cstring_take(char* c_str)` - Takes ownership of malloc'd C string, copies to GC heap, frees original
  2. `coex_string_from_cstring_copy(const char* c_str)` - Copies C string without freeing (caller retains ownership)
  3. `coex_string_from_raw_bytes(const char* data, size_t len)` - Creates string from byte buffer with known length
  - Added function declarations in `codegen/strings.py` for LLVM IR access
  - Updated `codegen/core.py` `_convert_from_c_type()` to use `string_from_cstring_take` for extern function returns (replacing manual copy + free)
  - Functions use `coex_gc_alloc_arena_or_gc()` for thread-safe allocation via TLAB
- **Files**:
  - New: `runtime/coex_string.c`, `runtime/coex_string.h`
  - Updated: `runtime/Makefile`, `codegen/strings.py`, `codegen/core.py`
- **Status**: Fixed (2026-02-04)

---

### BUG-075: Deep nested list type inference fails after reassignment
- **Discovered**: 2026-01-29, during value semantics stress testing
- **Category**: Codegen
- **Severity**: High
- **Reproduction**:
  ```coex
  level = [42]
  level = [level]    # level is now List<List<int>>
  current = level
  current = current.get(0)   # current should be List<int>, but type tracking fails
  print(current.get(0))       # Crashes or wrong value
  ```
- **Observed**: After reassigning a variable using its own `.get()` method, the type tracker used stale information, causing incorrect code generation for nested list access.
- **Root Cause**: Two issues:
  1. **Compile-time**: When processing `current = current.get(0)`, the type update happened BEFORE expression generation. This caused the expression generator to use the NEW type (inner element) instead of the OLD type (outer list) when generating the `.get()` call.
  2. **Runtime fallback**: For deeply nested lists where compile-time type inference fails, there was no runtime type switch to handle the TaggedValue type_id field.
- **Fix**:
  1. **Deferred type update** in `codegen/statements.py`: Compute the new element type BEFORE expression generation but apply the type update AFTER the store completes. This ensures `.get()` uses the correct outer-list type during code generation.
  2. **Runtime TYPE_ID switch** in `codegen/expressions.py`: Added switch on `type_id` from TaggedValue to handle TV_TYPE_LIST, TV_TYPE_STRING, TV_TYPE_MAP, TV_TYPE_SET, TV_TYPE_ARRAY at runtime. This provides a fallback when compile-time inference can't determine the exact nested type.
  3. **CallExpr handling**: Added handling for `CallExpr` with `MemberExpr` callee (in addition to `MethodCallExpr`) since the parser produces both forms for `obj.method(args)`.
- **Files**: `codegen/statements.py:350-410`, `codegen/expressions.py:957-1010, 2520-2570`
- **Status**: Fixed (2026-02-04)

### BUG-081: Galaxian crash - raw pointers stored where GC handles expected
- **Discovered**: 2026-01-31, during Galaxian stress testing
- **Category**: GC/Codegen
- **Severity**: Critical
- **Reproduction**: Run Galaxian for extended play sessions
- **Observed**: Segfault in `coex_gc_handle_deref` when GC tries to mark TaggedValues containing raw pointers
- **Expected**: Should run indefinitely without crash
- **Root Cause**: Multiple code paths stored raw pointers (via `ptrtoint`) where the GC expects handles. Key violations found in:
  1. Array<ref_type> subscript access - loading handles as pointers
  2. json_stringify storing raw pointers in temp string lists
  3. string_join_list reading handles as pointers
  4. `_to_i64_value` fallback for pointer types
  5. Channel send/receive not using handle storage invariant
- **Fix**: Systematic conversion to handle storage invariant across codegen:
  - `codegen/expressions.py` - Array subscript now uses `gc_handle_deref`
  - `codegen/json_type.py` - String list storage uses handles
  - `codegen/strings.py` - string_join_list properly dereferences handles
  - `codegen/channel.py` - Channel send uses `gc_ptr_to_handle` for heap types
  - `codegen/loops.py` - Parallel task results use TaggedValue with handles
- **Files**: `codegen/expressions.py`, `codegen/json_type.py`, `codegen/strings.py`, `codegen/loops.py`, `codegen/channel.py`
- **Status**: Fixed (2026-02-04)

### BUG-095: json.parse() truncates floats to integers
- **Discovered**: 2026-02-04, during xfail test cleanup
- **Category**: Codegen
- **Severity**: Medium
- **Reproduction**: `json.parse("3.14").as_float()` returns `3.0` instead of `3.14`
- **Observed**: All numeric strings were parsed using `string_to_int`, losing decimal values
- **Expected**: Floats should be parsed as floats, integers as integers
- **Root Cause**: In `_implement_json_parse()`, the `parse_number` block unconditionally used `string_to_int` and `json_new_int` for all numbers, ignoring decimal points and exponential notation.
- **Fix**: Added a scan loop to check if the number string contains '.', 'e', or 'E'. If found, parse with `string_to_float` and create with `json_new_float`. Otherwise, use the existing integer path.
- **Files**: `codegen/json_type.py:2486-2545` (`_implement_json_parse` number parsing)
- **Status**: Fixed (2026-02-04)

### BUG-016: gc_async() race condition requires TLAB
- **Discovered**: 2025-01-17, during codebase scan
- **Category**: GC
- **Severity**: Medium
- **Reproduction**: Use `gc_async()` with concurrent allocations
- **Observed**: Race condition causes undefined behavior
- **Expected**: Async GC should run safely in background
- **Root Cause**: The original hypothesis was that allocation list access raced with the async GC thread without Thread-Local Allocation Buffers (TLABs). Phase 4 of the GC implementation added TLABs with CAS-based allocation (`_implement_gc_tlab_init`, `_implement_gc_tlab_alloc`, `_implement_gc_tlab_refill`), thread-local allocation lists, and proper synchronization via mutex/condition variables for GC coordination.
- **Fix**: TLABs now provide thread-local allocation buffers that don't require locks for the fast path. Each thread allocates from its own TLAB, and only refills require mutex synchronization. The gc_async() function properly signals the background GC thread via condition variable, and allocations are safe because they go to thread-local lists that are only processed during the sweep phase under proper synchronization.
- **Files**: `coex_gc.py` (TLAB implementation in `_implement_gc_tlab_*` functions, thread list allocation in `_implement_gc_alloc_to_thread_list`)
- **Status**: Fixed (2026-02-04) - TLAB implementation complete, stress tests passing

### BUG-087: Cross-heap map references lost during GC swap
- **Discovered**: 2026-02-04, during CI failure analysis
- **Category**: GC
- **Severity**: Medium
- **Root Cause**: Storage model mismatch between codegen and GC marking. After the handle storage conversion, `Map.set()` for reference-type values stores GC handles (via `gc_ptr_to_handle`), but the GC's `_implement_gc_mark_hamt` treated all heap-type values as raw pointers and called `gc_ptr_to_handle(inttoptr(value))`. When the value was already a handle (a small integer like 5), `inttoptr(5)` created a fake pointer and `gc_ptr_to_handle` crashed trying to read the object header at address 5.
- **Fix**: Added `MAP_FLAG_VALUE_IS_HANDLE = 0x04` flag to distinguish handle-stored values (regular maps) from pointer-stored values (JSON maps). Updated `_implement_gc_mark_hamt` to branch: if HANDLE flag set, use i64 directly as handle for `gc_mark_object`; if PTR flag set, convert via `gc_ptr_to_handle` as before.
- **Files**: `codegen/hamt.py:42-43`, `codegen/conversions.py:643-644`, `coex_gc.py:3001-3035`
- **Status**: Fixed (2026-02-04)

### BUG-082: first/most/parallel-for return wrong values instead of task results
- **Discovered**: 2026-02-04, during CI failure analysis
- **Category**: Codegen
- **Severity**: High
- **Root Cause**: Two separate TaggedValue issues:
  1. **Task-based paths (7 sites)**: `list_get` returns a pointer to a TaggedValue `{i64 type_id, i64 value}`, but the code loaded the first i64 (type_id, always 1) instead of extracting the value field. Fixed by using `extract_tagged_value` at lines 1496, 1608, 1764, 1936, 2049, 2313, 2677.
  2. **Thread-based result collection (4 sites)**: Result lists were created with `elem_size = 8` (raw i64) but iterated by the standard for-loop path which expects 16-byte TaggedValue elements. This caused `extract_tagged_value` to read across element boundaries, shifting all results by one position. Fixed by changing to `TAGGED_VALUE_SIZE` (16) and wrapping results in TaggedValues before appending.
- **Files**: `codegen/loops.py` (lines 1874, 1908, 2156, 2573 for elem_size; lines 1963-1971, 2193-2200, 2814-2821, 2825-2831 for TaggedValue wrapping)
- **Status**: Fixed (2026-02-04)

### BUG-084: GC stats don't reflect per-task allocation counts in concurrent programs
- **Discovered**: 2026-02-04, during CI failure analysis
- **Category**: GC
- **Severity**: Low
- **Root Cause**: Not actually a GC stats issue. The tests used thread-based `for..in` parallel collection to spawn threads and sum results. The thread-based result collection had the same `elem_size = 8` TaggedValue bug as BUG-082. Once BUG-082's thread-based path was fixed, these tests passed — the GC stats were always reporting correctly.
- **Files**: `codegen/loops.py` (same fix as BUG-082)
- **Status**: Fixed (2026-02-04) — resolved by BUG-082 thread-path fix

### BUG-083: User-defined kind handler substitution crashes at runtime
- **Discovered**: 2026-02-04, during CI failure analysis
- **Category**: Codegen
- **Severity**: Medium
- **Root Cause**: The handler substitution code was already working correctly. The tests were incorrectly marked as xfail. The `KindFunctionDecl` code generation in `codegen/functions.py` properly builds a `KindCall` struct with name, param_names, param_values (as JSON list), and body fields, then calls the handler function. Both curly-brace (`{name}`) and positional (`$1`) substitution work via the user-defined handler function.
- **Note**: A separate issue exists in `commentary_analyzer.py` which crashes on `KindFunctionDecl` objects (missing `.kind` attribute), but this only affects the CLI path, not the test infrastructure or core codegen.
- **Files**: `codegen/functions.py:196-446`
- **Status**: Fixed (2026-02-04) — tests were already passing, removed xfail markers

### BUG-071: Map.remove() with string keys doesn't use string-aware function
- **Discovered**: 2026-01-29, during JSON refactoring test implementation
- **Category**: Codegen
- **Severity**: Medium
- **Root Cause**: In `codegen/expressions.py:2289`, the special handling for Map with string keys only covered `get`, `has`, and `set` methods — not `remove`. The `remove` method fell through to `coex_map_remove` which expects an i64 key, not a string pointer.
- **Fix**: Added `"remove"` to the method tuple and added a handler that calls `cg.map_remove_string` (which already existed in `codegen/hamt.py`).
- **Files**: `codegen/expressions.py:2289-2330`
- **Status**: Fixed (2026-02-04)

### BUG-085: String.from_bytes produces wrong characters (all bytes become 0x01)
- **Discovered**: 2026-02-04, during CI failure analysis
- **Category**: Codegen
- **Severity**: Medium
- **Root Cause**: Two TaggedValue mismatches:
  1. `String.from_bytes` (`codegen/strings.py:1675`): `list_get` returns a pointer to a TaggedValue `{i64 type_id, i64 value}`, but the code loaded a single i8 from the start, reading the type_id field (always 1 for TV_TYPE_INT) instead of the value field. Fix: use `extract_tagged_value` to get the i64 value, then `trunc` to i8.
  2. `String.to_bytes` (`codegen/strings.py:1740-1762`): Created list with `elem_size=1` and appended raw bytes, but with `USE_TAGGED_VALUES=True` all lists expect 16-byte TaggedValue elements. Fix: create list with `TAGGED_VALUE_SIZE`, wrap each byte in a TaggedValue via `create_tagged_value`, and append with `TAGGED_VALUE_SIZE`.
- **Files**: `codegen/strings.py:1674-1675, 1740-1762`
- **Status**: Fixed (2026-02-04)

### BUG-058: LLVM domination error with repeated variable declarations in if-blocks
- **Discovered**: 2026-01-28, during Galaxian game implementation
- **Category**: Codegen
- **Severity**: High
- **Root Cause**: While-loop placeholder variable pre-allocation (in `codegen/loops.py`) now creates i64 allocas in the entry block before the loop body, and inner if-blocks reuse these allocas via `generate_var_reassignment()`. This prevents the domination error since all allocas are in the entry block.
- **Status**: No longer reproducible (2026-02-04) — resolved by while-loop placeholder variable mechanism

### BUG-073: json.as_string() returns quoted form for parsed strings
- **Discovered**: 2026-01-29, during JSON value semantics test development
- **Category**: Codegen
- **Severity**: Medium
- **Root Cause**: `_implement_json_parse()` in `codegen/json_type.py:2494-2498` stored the input string including surrounding quote characters. The `as_string()` method returned this verbatim.
- **Fix**: Added `string_slice(str, 1, len-1)` to strip the surrounding quotes before calling `json_new_string`. This also fixed 5 json parse/roundtrip xfail tests and 5 json set_index xfail tests that depended on correct string parsing.
- **Files**: `codegen/json_type.py:2494-2498`
- **Status**: Fixed (2026-02-04)

### BUG-089: Float list values corrupted when returned from function
- **Discovered**: 2025-01-18, during GEMM benchmark development
- **Category**: Codegen
- **Severity**: Critical
- **Root Cause**: In TaggedValue mode, `list.get()` generates a heap path and a value path with a phi node. The heap path used `ptrtoint i8* to double`, which is invalid LLVM IR (can't ptrtoint to a floating-point type). This caused a compile-time error for any `[float]` list. Fix: convert i8* to i64 first via ptrtoint, then use `_from_i64_value` to bitcast i64 to double.
- **Fix**: Changed both occurrences (index syntax path at line ~965 and method call path at line ~2457) to use `ptrtoint(ptr, i64)` then `_from_i64_value(i64, target_type)` instead of direct `ptrtoint(ptr, target_type)`.
- **Files**: `codegen/expressions.py:960-965, 2452-2457`
- **Status**: Fixed (2026-02-04)

### BUG-086: cstring slice returns zero for byte values at non-zero offsets
- **Discovered**: 2026-02-04, during CI failure analysis
- **Category**: Codegen
- **Severity**: Low
- **Root Cause**: Same as BUG-085 — `_implement_string_cstring` created a list with `elem_size=1` and appended raw bytes, but with `USE_TAGGED_VALUES=True` all lists expect 16-byte TaggedValue elements. The `list.get()` method reads 16-byte TaggedValues, so it was reading garbage/zeros when the data was stored as 1-byte elements.
- **Fix**: Changed list creation to use `TAGGED_VALUE_SIZE`, wrapped each byte in a TaggedValue via `create_tagged_value`, and appended with `TAGGED_VALUE_SIZE`.
- **Files**: `codegen/strings.py:1961-2000`
- **Status**: Fixed (2026-02-04)

### BUG-080: Memory leak in extern string returns
- **Discovered**: 2026-01-31, during Galaxian investigation
- **Category**: Codegen
- **Severity**: Medium
- **Reproduction**: Call extern function returning string in a loop
- **Observed**: C-allocated string from extern return was never freed after copying to Coex string
- **Root Cause**: `_convert_from_c_type` called `string_from_literal` which copies the C string
  but never freed the original malloc'd memory.
- **Fix**: Added `free()` call after `string_from_literal` to release the C string
- **Files**: `codegen/core.py:1338-1355`
- **Status**: Resolved (2026-01-31)

### BUG-079: Variables assigned from method calls not GC-rooted
- **Discovered**: 2026-01-31, during Galaxian segfault investigation
- **Category**: GC
- **Severity**: Critical
- **Reproduction**: Assign result of method call on typed variable without explicit type annotation:
  ```coex
  layout: json = {...}
  layout_str = layout.stringify()  # layout_str not rooted!
  gc()
  print(layout_str.len())  # Crash - string was collected
  ```
- **Observed**: String returned from `json.stringify()` was collected by GC
- **Root Cause**: `collect_heap_vars_from_body` runs at function setup before code generation.
  When inferring the type of `layout.stringify()`, it needed to know `layout` is type `json`,
  but `var_coex_types` wasn't populated yet because variable declarations hadn't been processed.
  Type inference fell back to `int`, so `layout_str` wasn't added to heap vars.
- **Fix**: Added pre-pass in `collect_heap_vars_from_body` to collect explicit type annotations
  from all VarDecls before doing the inference pass. This allows method call return type
  inference to work correctly.
- **Files**: `codegen/functions.py:645-735`
- **Status**: Resolved (2026-01-31)

### BUG-004: GC race condition with parallel Set allocations
- **Discovered**: 2025-01-17, during codebase scan
- **Category**: GC
- **Severity**: Critical
- **Reproduction**: Run parallel tasks that allocate Sets (e.g., parallel sieve tests)
- **Observed**: Non-deterministic crashes during concurrent Set allocation
- **Expected**: Concurrent Set allocations should be thread-safe
- **Root Cause**: The TLAB (Thread-Local Allocation Buffer) bump-pointer allocation was not
  thread-safe. Multiple threads could read the same cursor value, compute their new positions,
  and both store their values - with one overwriting the other. Both threads would then think
  they had valid memory at the same address, causing data corruption.
- **Fix**: Replaced the non-atomic load-compute-store pattern in `_implement_gc_tlab_alloc`
  with an atomic compare-and-swap (CAS) loop:
  1. Load current cursor
  2. Calculate new cursor = cursor + size
  3. CAS: atomically update cursor only if it hasn't changed
  4. If CAS fails (another thread modified cursor), retry from step 1
- **Files**: `coex_gc.py` (`_implement_gc_tlab_alloc`)
- **Status**: Fixed (2026-01-30)
- **Testing**: Verified with parallel sieve tests (8 threads, 10000 elements), parallel Set
  allocation stress tests (8 threads × 5000 insertions each), all passing consistently.

### BUG-064: Library modules cannot call ui.render() with String values in JSON
- **Discovered**: 2026-01-28, during heapwatch implementation
- **Category**: Codegen
- **Severity**: Medium
- **Reproduction**:
  ```coex
  func main() -> int
      value = String.from(42)
      panel: json = {
          type: "text",
          text: value  # String struct, not string literal
      }
      print(panel.stringify())  # Expected: {"type":"text","text":"42"}
      return 0
  ~
  ```
- **Observed**: Segmentation fault or incorrect output when String struct values were used in JSON
- **Expected**: String struct values should be convertible to JSON string values
- **Root Cause**: The JSON codegen was not properly handling String struct values (from `String.from()`). The type inference for json element types returned `TV_TYPE_JSON_NULL` (6), which is below `TYPE_HEAP_BASE` (64), causing reference values to be treated as primitives and not properly dereferenced.
- **Files**: `coex_gc.py` (`get_tv_type_id`), `codegen/json_type.py`
- **Status**: Fixed (2026-01-30)
- **Resolution**:
  1. Fixed `get_tv_type_id` in coex_gc.py to return `TV_TYPE_JSON_OBJECT` (72) for json type instead of `TV_TYPE_JSON_NULL` (6)
  2. This ensures json values are recognized as heap types (type_id >= 64) and properly dereferenced when stored in collections
  3. Part of the Universal Tagged Values implementation for consistent reference type handling

### BUG-066: Promoted arena values not surviving GC after formula return
- **Discovered**: 2026-01-29, during BUG-065 fix verification
- **Category**: GC/Codegen
- **Severity**: High
- **Test**: `tests/test_gc.py::TestArenaEscapePromotion::test_formula_gc_after_return`
- **Reproduction**:
  ```coex
  formula make_data() -> List<int>
      const data = [100, 200, 300]
      return data
  ~

  func main() -> int
      const items = make_data()
      gc()  # triggers collection
      print(items.len())  # CRASH - items was freed
      return 0
  ~
  ```
- **Observed**: Segmentation fault in `coex_list_len` when accessing the list after gc().
- **Expected**: Values returned from formulas should survive GC if they are stored in
  local variables that are tracked in the shadow stack.
- **Root Cause**: The `infer_type_from_expr` function in `codegen/generics.py` did not
  handle regular function calls. When analyzing `const items = make_data()`:
  1. The type inference checked if it was a method call (MemberExpr) - no
  2. Checked if it was a type constructor (name in `type_fields`) - no
  3. Fell through to return `PrimitiveType("int")` as default

  Because `items` was inferred as `int` instead of `List<int>`, it was not identified
  as a heap type in `collect_heap_vars_from_body`. No shadow stack slot was allocated,
  so when `gc()` ran, the promoted object wasn't found as a root and was swept.

  Note: The original hypothesis about `gc_promote_to_heap` was incorrect. The promotion
  mechanism works correctly - the promoted object's handle IS stored in its forward field
  and can be recovered via `gc_ptr_to_handle` in `set_root`. The issue was that `set_root`
  was never called because no shadow stack slot was allocated.
- **Fix**: Added function call handling in `infer_type_from_expr` to check if the callee
  is a function name in `func_decls` and return its return type:
  ```python
  if func_name and hasattr(cg, 'func_decls') and func_name in cg.func_decls:
      func_decl = cg.func_decls[func_name]
      if func_decl.return_type:
          return func_decl.return_type
  ```
- **Files**: `codegen/generics.py` (infer_type_from_expr)
- **Status**: Fixed (2026-01-30)

### BUG-068: JSON array index access calls wrong function (get_field instead of get_index)
- **Discovered**: 2026-01-29, during Galaxian game debugging
- **Category**: Codegen
- **Severity**: Critical
- **Reproduction**:
  ```coex
  func main() -> int
      arr: json := []
      arr = arr.append({value: 10})
      arr = arr.append({value: 20})
      print(arr.len())     # Correctly prints 2
      elem: json = arr[0]  # Returns null instead of {value: 10}!
      print(arr.stringify())  # Correctly prints [{"value":10},{"value":20}]
      return 0
  ~
  ```
- **Observed**: `arr[0]` returns null even though the array has elements. `stringify()`
  correctly shows all elements, but index access returns null.
- **Root Cause**: In `codegen/expressions.py` `generate_index()`, there's a check for
  `type_methods["get"]` that intercepts index access for any type with a `get` method.
  JSON has `"get": "coex_json_get_field"` registered, so `arr[0]` was routed to
  `coex_json_get_field` with the integer 0 cast to a String* pointer. This function
  expects a String key, not an integer index, so it returns null.
  The proper JSON index handling at line 922-934 that correctly dispatches between
  `get_field` (string key) and `get_index` (int index) was never reached.
- **Fix**: Added a special case in `generate_index()` to skip the `type_methods["get"]`
  lookup for JSON type, allowing JSON indexing to fall through to the specialized
  handler that correctly distinguishes between string and integer indices.
- **Files**: `codegen/expressions.py` (generate_index function)
- **Status**: Fixed 2026-01-29

### BUG-069: JSON array stores pointers causing use-after-free segfault
- **Discovered**: 2026-01-29, during Galaxian game debugging
- **Category**: GC
- **Severity**: Critical
- **Reproduction**: Run Galaxian game for ~4000 frames (a few minutes). The game
  creates JSON arrays with `.append()` heavily each frame for the UI layout.
- **Observed**: Segmentation fault after approximately 4000 GC cycles. GC stats
  show normal operation (48M allocations, 48M collected, 67 live objects) but
  the crash occurs immediately after a GC cycle completes.
- **Root Cause**: `json_append` stored 8-byte **pointers** to Json objects in the
  underlying List, rather than the 16-byte Json struct values inline. When the
  inner Json objects were no longer referenced elsewhere, the GC collected them.
  The pointers in the array became dangling, and later access caused segfault.
  The GC doesn't trace through List data buffers to find nested pointers.
- **Fix**: Changed JSON array storage to store the 16-byte Json struct (tag + value)
  inline in the List instead of an 8-byte pointer. Updated:
  - `_implement_json_append`: elem_size 8 → 16, store struct not pointer
  - `_implement_json_get_index`: return pointer to inline data directly
  - `_convert_list_expr_to_json_array`: same fix for JSON array literals
  - `_convert_list_runtime_to_json_array`: same fix for runtime conversion
  - `json_from_cjson`: same fix for cJSON parsing
- **Files**: `codegen/json_type.py`
- **Status**: Fixed 2026-01-29

### BUG-065: gc() crashes after all TLAB objects are collected
- **Discovered**: 2026-01-28, during BUG-064 investigation
- **Category**: GC
- **Severity**: Medium
- **Reproduction**:
  ```coex
  func main() -> int
      print("Before gc")
      gc()  # CRASH - segfault
      print("After gc")
      return 0
  ~
  ```
- **Observed**: Segmentation fault on allocation AFTER gc() completes
- **Root Cause**: When all objects in a TLAB die during GC sweep, the TLAB is added to
  the dead list and munmap'd. However, the owning thread's ThreadEntry still has
  tlab_base/tlab_cursor/tlab_limit pointing to the freed memory. The next allocation
  tries to use these stale pointers, causing a crash.
- **Fix**: In `_implement_gc_sweep_thread_lists`, when a TLAB becomes empty (was_last),
  check if it's the current thread's TLAB. If so, reset the thread's tlab_base,
  tlab_cursor, and tlab_limit fields to NULL before munmap'ing.
- **Files**: `coex_gc.py` (gc_sweep_thread_lists)
- **Status**: Fixed 2026-01-28

### BUG-067: JSON type not recognized as heap type - causes GC to free live objects
- **Discovered**: 2026-01-29, during Galaxian game loop debugging
- **Category**: GC
- **Severity**: Critical
- **Reproduction**:
  ```coex
  func main() -> int
      frame = 0
      while frame < 100
          canvas: json := []
          i = 0
          while i < 20
              canvas = canvas.append({ id: i })
              i = i + 1
          ~
          gc()  # Frees canvas even though it's still in use!
          print(canvas.len())  # CRASH or prints 0
          frame = frame + 1
      ~
      return 0
  ~
  ```
- **Observed**: After gc(), JSON objects are freed even though they're stored in local
  variables. Accessing them crashes or returns corrupted data.
- **Root Cause**: The `is_heap_type()` function in `codegen/conversions.py` did not
  recognize `json` as a heap type. This meant JSON variables did not get shadow stack
  entries, so the GC couldn't see them as roots and would free them.
- **Fix**: Added `json` to the heap type checks in `is_heap_type()`:
  - PrimitiveType case: `if coex_type.name == "json": return True`
  - NamedType case: `if coex_type.name == "json": return True`
- **Files**: `codegen/conversions.py` (is_heap_type function)
- **Status**: Fixed 2026-01-29

### BUG-059: json.append() corrupts array when appending JSON objects
- **Discovered**: 2026-01-28, during Galaxian game implementation
- **Category**: Codegen
- **Severity**: Critical
- **Reproduction**:
  ```coex
  func main() -> int
      arr: json := []
      arr = arr.append({ name: "Alice" })
      arr = arr.append({ name: "Bob" })
      print(arr.len())       # Works: prints 2
      print(arr.stringify()) # CRASH: segfault
      return 0
  ~
  ```
- **Observed**: Appending integers works, but appending JSON objects causes corruption. `len()` returns correct value but `stringify()` crashes with segfault.
- **Expected**: JSON array should contain valid JSON object pointers after append
- **Root Cause**: In `_implement_json_append` (json_type.py:1408-1412), the code passed the JSON pointer directly to `list_append`, which copies bytes FROM that address. This copied the JSON struct's tag field instead of the pointer value.
- **Files**: `codegen/json_type.py:1381-1420` (`_implement_json_append`)
- **Status**: Fixed (2026-01-28)
- **Resolution**: Allocate stack space for the pointer, store the JSON pointer there, and pass the stack address to `list_append`. This ensures the pointer value itself is copied into the list.

### BUG-060: TLAB memory never reclaimed - causes memory leak
- **Discovered**: 2026-01-28, during Galaxian game implementation
- **Category**: GC
- **Severity**: Critical
- **Reproduction**:
  Run Galaxian game: `python3 coexc.py examples/galaxian.coex -o galaxian && ./galaxian`
- **Observed**:
  - Memory grows from <1GB to >5GB over ~37 seconds, then crashes with segfault
  - After investigation with debug counters:
    ```
    total_allocations: 13,983,049
    swept: 13,968,937 (99.9% of allocations ARE being swept)
    reclaimed_bytes: 1,204,408 (only 1.2MB of 1.2GB reclaimed!)
    tlab_freed: 13,968,937 (100% of freed objects were TLAB-allocated)
    nontlab_freed: 0
    ```
  - Objects ARE being tracked and swept, but actual memory is never freed
- **Root Cause**: 100% of allocations use TLAB (Thread-Local Allocation Buffer):
  1. Objects allocated from 256KB TLAB buffers (fast path)
  2. When objects become garbage, sweep frees the allocation NODE (24-byte tracking struct)
  3. But TLAB-allocated object MEMORY is NOT freed - it stays in the TLAB forever
  4. Code at coex_gc.py unmarked_node block has: `with builder.if_then(builder.not_(is_tlab)): free(header_ptr)`
  5. This means TLAB objects never have their memory freed
  6. Old TLABs should be freed when completely empty, but no mechanism exists to track this
- **Expected**: When all objects in a TLAB become garbage, the TLAB buffer should be reclaimed
- **Fix Required**: Implement TLAB reclamation:
  1. Track live object count per TLAB (or use bitmap)
  2. When sweeping a TLAB object, decrement the TLAB's live count
  3. When TLAB live count reaches 0, free the entire 256KB buffer
  4. Alternative: Use compaction to consolidate live objects into fewer TLABs
- **Investigation History**:
  - Initial hypothesis: `gc_alloc_to_thread_list` dropping allocations (pthread TLS issue)
  - Partial fix applied: Added global fallback when pthread_getspecific returns NULL
  - This fixed the tracking issue but revealed the deeper TLAB issue
  - Debug counters added to trace allocation, sweep, and TLAB behavior
- **Files**:
  - `coex_gc.py:5880-5895` (unmarked_node - TLAB check)
  - `coex_gc.py:4850-4960` (gc_tlab_alloc, gc_tlab_refill)
  - `coex_gc.py:5610-6040` (gc_sweep_thread_lists)
- **Status**: Fixed (2026-01-28)
- **Resolution**:
  1. Fixed gc_alloc_to_thread_list to use global tls_thread_entry fallback when pthread TLS fails
  2. Added TLAB header structure with live_count for reference counting per TLAB
  3. Extended alloc_node_type to include tlab_base pointer (field 3)
  4. Modified gc_alloc to store TLAB base and increment live_count on allocation
  5. Modified gc_tlab_init and gc_tlab_refill to initialize TLAB headers
  6. Modified gc_sweep_thread_lists to decrement live_count on sweep
  7. Implemented deferred TLAB freeing (add to dead list, free at end of sweep)
  - Memory footprint reduced from 5GB+ to ~1GB
  - ~18K TLABs (~4.5GB) properly reclaimed over 4000 frames
- **Note**: A separate crash at ~42 seconds was discovered during testing (see BUG-062)

### BUG-061: GC uses wrong struct layout for JSON marking
- **Discovered**: 2026-01-28, during Galaxian GC debugging
- **Category**: GC
- **Severity**: Medium (works on little-endian by accident)
- **Reproduction**: Any code that creates JSON objects with strings, arrays, or nested objects on a big-endian system
- **Observed**: GC's `gc_mark_object` uses `{i8, i64}` struct for JSON, but actual JSON struct is `{i64, i64}`
- **Expected**: GC should use correct struct layout matching `codegen/json_type.py:350-354`
- **Root Cause**: Comment at coex_gc.py:2991 incorrectly stated "JSON struct: { i8 tag (0), i64 value (1) }" when the actual struct (defined in json_type.py) uses i64 for both fields for alignment.
- **Impact**: On little-endian systems (x86, ARM), reading 1 byte of an 8-byte value with values 0-6 happens to work. On big-endian systems, this would read the wrong byte and fail to mark JSON children correctly.
- **Files**: `coex_gc.py:2990-3000` (mark_json block in `_implement_gc_mark_object`)
- **Status**: Fixed (2026-01-28)
- **Resolution**: Changed struct to `{i64, i64}` and comparison constant from `i8` to `i64`

### BUG-063: Library modules cannot import other libraries
- **Discovered**: 2026-01-28, during heapwatch implementation
- **Category**: Codegen
- **Severity**: Medium
- **Reproduction**: Create lib/a.coex with a function, create lib/b.coex that imports a and calls a.func()
- **Observed**: Error "Undeclared identifier 'a': variable has not been declared in this scope"
- **Expected**: Library b should be able to import and use library a
- **Root Cause**: `generate_module_contents()` in `codegen/modules.py` does not process
  `program.imports` - it only handles traits, types, kinds, and functions. Nested imports
  within library modules were completely ignored.
- **Files**: `codegen/modules.py:115-228`
- **Status**: Fixed (2026-01-28)
- **Resolution**: Added import processing at the start of `generate_module_contents()`:
  ```python
  # BUG-063 FIX: Process imports within this module first
  for imp in program.imports:
      if imp.is_library:
          self.load_library(imp.library_path, imp.module)
      else:
          self.load_module(imp.module)
  ```
  Library modules can now import other libraries. Tested with heapwatch importing ui.

### BUG-062: Handle table grows unboundedly causing crash
- **Discovered**: 2026-01-28, during BUG-060 investigation
- **Category**: GC
- **Severity**: Critical
- **Reproduction**: Run Galaxian game for ~42 seconds: `./galaxian`
- **Observed**:
  - Program crashes with SIGSEGV (exit code 139) after ~4000-4500 frames
  - Memory grows at ~10MB/sec, reaching 5-6GB before crash
  - `gc_next_handle` grows to 56M+, handle table doubles repeatedly
  - Stack overflow in macOS CFRunLoop due to excessive memory pressure
- **Expected**: Program should run indefinitely without crashing
- **Root Cause**: `gc_handle_pool_refill()` in `coex_gc.py` **never used the free list**.
  - When a thread's handle pool was empty, it always bump-allocated new handles
  - Handles retired by GC were added to the free list but never reused
  - Handle table grew: 1M -> 2M -> 4M -> 8M -> 16M -> 32M -> 64M (512MB)
  - Eventually caused memory exhaustion and stack overflow
- **Files**: `coex_gc.py` (`_implement_gc_handle_pool_refill`)
- **Status**: Fixed (2026-01-28)
- **Resolution**: Modified `gc_handle_pool_refill` to drain handles from the free list
  before falling back to bump allocation. Implementation:
  1. Lock mutex and check if free list has handles
  2. Pop handles from free list into local array (up to pool size)
  3. Give thread one handle, push rest back to free list
  4. Only use bump allocation when free list is completely empty
  - Result: `next_handle` stabilizes at ~28K, table stays at 1M
  - Memory usage stable, can run indefinitely

### BUG-054: Metal texture released prematurely causing segfault
- **Discovered**: 2026-01-22, during SVG module testing
- **Category**: Runtime
- **Severity**: Critical
- **Reproduction**: Run any SVG example on macOS with Metal backend
- **Observed**: Segfault in `coex_ui_shell_begin_frame()` when calling `[metal_layer nextDrawable]`
- **Expected**: SVG textures should remain valid until explicitly destroyed
- **Root Cause**: Metal textures were stored in a C struct field (`id<MTLTexture>`), but ARC doesn't track Objective-C objects stored in plain C struct fields. The texture was being released when the autoreleasepool drained.
- **Fix**: Changed struct to use `void*` field with explicit `CFBridgingRetain()` on creation and `CFRelease()` on destruction, bypassing ARC.
- **Files**: `runtime/svg/coex_svg_texture_metal.m`
- **Status**: Resolved 2026-01-22

### BUG-053: Heap corruption when clicking button with SVG in layout
- **Discovered**: 2026-01-22, during SVG module testing
- **Category**: Runtime
- **Severity**: Critical
- **Reproduction**: Run `svg_button_test.coex` which has both an SVG image and a button, click the button
- **Observed**: Heap corruption error: "malloc: Heap corruption detected, free list is damaged" on the frame after click
- **Expected**: Button click should work normally alongside SVG rendering
- **Root Cause**: Custom `cJSON_ReplaceOrAddItemToObject` in `coex_ui.c` performed manual linked-list manipulation that conflicted with system cJSON's internal bookkeeping. When an item was replaced, the manual list surgery corrupted cJSON's internal pointers.
- **Fix**: Rewrote function to use system cJSON's native `cJSON_HasObjectItem()` and `cJSON_ReplaceItemInObject()` instead of manual pointer manipulation.
- **Files**: `runtime/coex_ui.c`
- **Status**: Resolved 2026-01-22

### BUG-045: Metal GPU offload crashes with double types
- **Discovered**: 2026-01-18, during GPU offload testing
- **Category**: Codegen
- **Severity**: Critical
- **Reproduction**:
  ```coex
  formula compute(x: float) -> float
      return x * 2.0
  ~

  func main() -> int
      data: Array<float> = [1.0, 2.0, 3.0].toArray()
      result: Array<float> = [compute(x) for x in data]  # CRASH
      return 0
  ~
  ```
- **Observed**: Segfault in Metal's `newLibraryWithSource` with error "double is not supported in Metal"
- **Expected**: GPU offload should work with Coex's 64-bit float type
- **Root Cause**: Metal Shading Language does NOT support 64-bit types (double, long). The Metal backend was incorrectly mapping Coex's 64-bit float to Metal's `double`, causing kernel compilation to fail.
- **Files**: `codegen/formula/metal.py`, `runtime/coex_metal.m`
- **Status**: Resolved
- **Resolution**:
  1. Updated MetalBackend.TYPE_MAP to use 32-bit types (`float` instead of `double`)
  2. Modified `coex_metal_dispatch()` to convert 64-bit Coex data to 32-bit for Metal input
  3. Added conversion back from 32-bit to 64-bit for output
  4. Metal GPU offload now works correctly, with some precision loss due to 32-bit computation

### BUG-034: Worker parking uses mutex
- **Discovered**: 2026-01-18, during lock audit
- **Category**: Runtime
- **Severity**: Low
- **Observed**: Uses `parking_mutex` + `parking_cond` at `coex_scheduler.c:33-34`
- **Files**: `runtime/coex_scheduler.c:33-34, 173-204`
- **Status**: Resolved (by design)
- **Resolution**: Required by POSIX - `pthread_cond_wait` mandates a mutex companion

### BUG-037: FirstContext completion uses mutex
- **Discovered**: 2026-01-18, during lock audit
- **Category**: Runtime
- **Severity**: Low
- **Observed**: Uses `mutex` + `cond` in FirstContext at `coex_scheduler.h:92-93`
- **Files**: `runtime/coex_scheduler.h:92-93`, `runtime/coex_scheduler.c:416-441, 682-700, 728-751`
- **Status**: Resolved (by design)
- **Resolution**: Required by POSIX - `pthread_cond_wait` mandates a mutex companion

### BUG-038: MostContext completion uses mutex
- **Discovered**: 2026-01-18, during lock audit
- **Category**: Runtime
- **Severity**: Low
- **Observed**: Uses `mutex` + `cond` in MostContext at `coex_scheduler.h:106-107`
- **Files**: `runtime/coex_scheduler.h:106-107`, `runtime/coex_scheduler.c:462-467, 753-775, 800-820`
- **Status**: Resolved (by design)
- **Resolution**: Required by POSIX - `pthread_cond_wait` mandates a mutex companion

### BUG-039: SchedulerTask main thread wait uses mutex
- **Discovered**: 2026-01-18, during lock audit
- **Category**: Runtime
- **Severity**: Low
- **Observed**: Uses `main_mutex` + `main_cond` in SchedulerTask at `coex_scheduler.h:63-64`
- **Files**: `runtime/coex_scheduler.h:63-64`, `runtime/coex_scheduler.c:333-337, 559-586, 627-657`
- **Status**: Resolved (by design)
- **Resolution**: Required by POSIX - `pthread_cond_wait` mandates a mutex companion

### BUG-040: TaskClosure completion signaling uses mutex
- **Discovered**: 2026-01-18, during lock audit
- **Category**: Runtime
- **Severity**: Low
- **Observed**: Uses `mutex` + `cond` in TaskClosure at `coex_task.h:37-38`
- **Files**: `runtime/coex_task.h:37-38`, `runtime/coex_task.c:96-97, 107-108, 167-188`
- **Status**: Resolved (by design)
- **Resolution**: Required by POSIX - `pthread_cond_wait` mandates a mutex companion

### BUG-041: SharedWaiter wait_any uses mutex
- **Discovered**: 2026-01-18, during lock audit
- **Category**: Runtime
- **Severity**: Low
- **Observed**: Uses `mutex` + `cond` in SharedWaiter at `coex_task.c:37-38`
- **Files**: `runtime/coex_task.c:36-40, 210-253`
- **Status**: Resolved (by design)
- **Resolution**: Required by POSIX - `pthread_cond_wait` mandates a mutex companion

### BUG-001: Mutual recursion segfault in task coroutines
- **Discovered**: 2025-01-17, during task testing
- **Category**: Runtime
- **Severity**: Critical
- **Reproduction**: Create two tasks that call each other recursively
- **Observed**: Segmentation fault during coroutine context switch
- **Expected**: Tasks should execute mutual recursion correctly
- **Hypothesis**: Stack frame allocation was insufficient for deep recursion
- **Files**: `codegen.py` (task frame allocation)
- **Status**: Resolved (commit a55f8df)
- **Resolution**: Fixed task frame allocation size calculation

### BUG-002: Scheduler race condition in task completion
- **Discovered**: 2025-01-17, during concurrent task testing
- **Category**: Runtime
- **Severity**: Critical
- **Reproduction**: Run multiple tasks with rapid completion
- **Observed**: Race condition causing undefined behavior
- **Expected**: Clean task completion without races
- **Hypothesis**: Missing synchronization in scheduler
- **Files**: `codegen.py` (scheduler implementation)
- **Status**: Resolved (commit 2b69903)
- **Resolution**: Added proper synchronization to scheduler

### BUG-003: GC sweep disabled - memory never freed
- **Discovered**: 2025-01-17, during codebase scan
- **Category**: GC
- **Severity**: High
- **Reproduction**: Any program that allocates and calls `gc()`
- **Observed**: Sweep only clears mark bits, doesn't free memory
- **Expected**: Unmarked objects should be freed and memory reclaimed
- **Files**: `coex_gc.py` (`_implement_gc_sweep`)
- **Status**: Resolved (2025-01-17)
- **Resolution**: All 25 tests in test_gc_phase8.py pass, including `test_sweep_frees_unreachable_objects`

### BUG-005: posix.time_ns() returns incorrect values
- **Discovered**: 2025-01-17, during codebase scan
- **Category**: Stdlib
- **Severity**: High
- **Reproduction**: Call `posix.time_ns()` and compare to expected nanosecond timestamp
- **Files**: `codegen/posix.py`
- **Status**: Resolved (2026-01-19)
- **Resolution**: Fixed incorrect clock constants in `_create_posix_time_ns`:
  - Linux: Changed from 4 to 1 (CLOCK_MONOTONIC)
  - macOS: Changed from 1 to 8 (CLOCK_UPTIME_RAW for true nanosecond precision)
  - Root cause: Using wrong constants caused clock_gettime to fail silently, returning garbage values
  - Note: macOS CLOCK_REALTIME only provides microsecond precision, but CLOCK_UPTIME_RAW provides true nanosecond precision
- **Note**: Previously marked resolved on 2025-01-17 but test only checked `t > 0` which passed with garbage. Re-opened and truly fixed 2026-01-19.

### BUG-006: Channel<[int]> receive() returns unknown type
- **Discovered**: 2025-01-17, during codebase scan
- **Category**: Semantic
- **Severity**: Medium
- **Reproduction**: Create `Channel<[int]>` and call `.receive()`
- **Files**: `codegen.py` (channel implementation, type inference)
- **Status**: Resolved (2025-01-17)
- **Resolution**: All 11 tests in test_channel_inference.py pass

### BUG-007: String list printing bug
- **Discovered**: 2025-01-17, during codebase scan
- **Category**: Codegen
- **Severity**: Medium
- **Reproduction**: Create `List<string>` and print it
- **Files**: `codegen.py` (print generation, list printing)
- **Status**: Resolved (2025-01-17)
- **Resolution**: Manual testing confirms string lists work correctly: `["hello", "world", "test"]` returns correct values via `.get()`

### BUG-008: Nested list access bug
- **Discovered**: 2025-01-17, during codebase scan
- **Category**: Codegen
- **Severity**: Medium
- **Reproduction**: Create nested list like `[[1, 2], [3, 4]]` and access elements
- **Files**: `codegen.py` (subscript/index expression generation)
- **Status**: Resolved (2025-01-17)
- **Resolution**: Manual testing confirms nested list access works correctly: `outer.get(0).get(0)` returns `1`

### BUG-013: Task-to-task suspension not implemented
- **Discovered**: 2025-01-17, during codebase scan
- **Category**: Runtime
- **Severity**: High
- **Reproduction**: Have one task call another task, or nest task spawns
- **Files**: `codegen.py` (task implementation), `runtime/coex_scheduler.c`
- **Status**: Resolved (2025-01-17)
- **Resolution**: All 14 tests in test_task_to_task.py pass, including mutual recursion

### BUG-014: gc_dump_heap reads from unused global alloc list
- **Discovered**: 2025-01-17, during codebase scan
- **Category**: GC
- **Severity**: Low
- **Reproduction**: Call `gc_dump_heap()` after allocating objects
- **Files**: `coex_gc.py` (gc_dump_heap implementation)
- **Status**: Resolved (2025-01-17)
- **Resolution**: Tests pass including `test_heap_dump_shows_objects` (xpassed)

### BUG-017: Move operator tracking not implemented
- **Discovered**: 2025-01-17, during codebase scan
- **Category**: Semantic
- **Severity**: Medium
- **Reproduction**: Use `:=` move operator and then access the source variable
- **Files**: `codegen/statements.py`, `codegen/core.py`
- **Status**: Resolved (2025-01-17)
- **Resolution**: All 63 tests in test_unique_ownership.py and test_copy_operator.py pass, including use-after-move detection

### BUG-020: While loops - grammar exists, no codegen
- **Discovered**: 2025-01-17, during codebase scan
- **Category**: Codegen
- **Severity**: Medium
- **Reproduction**: Write a `while` loop in Coex code
- **Files**: `Coex.g4`, `codegen.py`
- **Status**: Resolved (2025-01-17)
- **Resolution**: All 45 tests in test_while_cycle.py and test_control_flow.py pass

### BUG-021: list.append() bug in method dispatch
- **Discovered**: 2025-01-17, during codebase scan
- **Category**: Codegen
- **Severity**: Medium
- **Reproduction**: Call `.append()` on a list
- **Files**: `codegen.py` (list method dispatch)
- **Status**: Resolved (2025-01-17)
- **Resolution**: All array append tests pass in test_array.py

### BUG-012: Task calls are synchronous, not async (bare calls now fire-and-forget)
- **Discovered**: 2025-01-17, during codebase scan
- **Category**: Runtime
- **Severity**: High
- **Reproduction**: Bare task calls should spawn and join at function exit
- **Observed**: All task calls blocked immediately
- **Expected**: Bare calls fire-and-forget, := blocks, = produces compile error
- **Files**: `codegen/statements.py`, `codegen/expressions.py`
- **Status**: Resolved (2025-01-17)
- **Resolution**: Implemented fire-and-forget semantics for bare task/thread calls:
  - Bare calls (`work()`) spawn immediately and join at function exit via nursery
  - `:=` assignment (`result := work()`) blocks immediately and returns result
  - `=` assignment (`result = work()`) is now a compile error
  - All 12 tests in test_fire_and_forget.py pass

### BUG-022: Bidirectional channels require true concurrent execution
- **Discovered**: 2025-01-17, during codebase scan
- **Category**: Runtime
- **Severity**: Medium
- **Reproduction**: Create two tasks that both send and receive on channels
- **Observed**: Hangs on blocking receive (deadlock)
- **Expected**: Both tasks should run concurrently, enabling bidirectional communication
- **Files**: `runtime/coex_channel.c`, `runtime/coex_channel.h`
- **Status**: Resolved (2026-01-17)
- **Resolution**: Fixed channel synchronization to use mutex/condvar instead of busy spin:
  - Added ChannelSync struct with pthread_mutex_t and pthread_cond_t to TaskChannel
  - Updated coex_channel_send() to lock mutex, signal condvar after buffering
  - Updated coex_channel_receive() to lock mutex, wait on condvar when buffer empty
  - All 12 tests in test_channel_inference.py pass including bidirectional channels

### BUG-019: C string null termination hack
- **Discovered**: 2025-01-17, during codebase scan
- **Category**: Codegen
- **Severity**: Medium
- **Reproduction**: Pass string slice to POSIX/FFI function (e.g., strlen on "hello world"[0:5])
- **Observed**: C function reads past slice into parent buffer (strlen returns 11 instead of 5)
- **Expected**: All strings should be safely null-terminated for C interop
- **Files**: `codegen/strings.py`, `codegen/core.py`
- **Status**: Resolved (2026-01-17)
- **Resolution**: Implemented proper C string marshaling at extern boundaries:
  - Added `cstring()` method on String type that returns null-terminated `[byte]` array
  - Updated `_convert_to_c_type()` to create stack-allocated null-terminated copies for extern calls
  - The marshaling copies string data to a temporary buffer with null terminator, safe for slice views
  - All 14 tests in test_cstring.py pass including slice edge cases

### BUG-018: GC stats not atomic in multi-threaded case
- **Discovered**: 2025-01-17, during codebase scan
- **Category**: GC
- **Severity**: Low
- **Reproduction**: Run multi-threaded program and check `gc_dump_stats()`
- **Observed**: Stats showed inconsistent values due to race conditions (98k-102k variance)
- **Expected**: Stats should be accurate even with concurrent allocations
- **Hypothesis**: Stats counters updated with plain load/store, not atomics
- **Files**: `coex_gc.py:2400-2417`, `coex_gc.py:3378-3382`
- **Status**: Resolved (2026-01-17)
- **Resolution**: Replaced load-add-store pattern with atomic_rmw operations:
  - `gc_alloc()` now uses `atomic_rmw('add', ...)` for total_allocations, total_bytes, allocations_since, bytes_since
  - `gc()` now uses `atomic_rmw('add', ...)` for collections_completed counter
  - Before fix: 16-thread test showed ~4% variance (98k-102k allocations)
  - After fix: Exactly consistent counts across all runs (128068 allocations)
  - New test file: test_gc_stats_atomic.py

### BUG-009: Matrix formula tick() not generating correct code
- **Discovered**: 2025-01-17, during codebase scan
- **Category**: Codegen
- **Severity**: Medium
- **Reproduction**: Define a matrix with a formula and call `tick()`
- **Observed**: LLVM error: `ret i64 1` in void-returning function
- **Expected**: Formula should be applied to each cell, producing new matrix state
- **Files**: `codegen/matrix.py`, `codegen/statements.py`
- **Status**: Resolved (2026-01-17)
- **Resolution**: Fixed matrix formula return statement handling:
  - Matrix formula methods are void-returning, but `return` sets cell value
  - Added `__matrix_result` alloca to capture return values
  - Modified `generate_return` to detect matrix context and store value instead of `ret`
  - Return now branches to x_loop_inc which writes value to cell
  - All 5 matrix tests pass

### BUG-010: Matrix cell keyword access not working
- **Discovered**: 2025-01-17, during codebase scan
- **Category**: Codegen
- **Severity**: Medium
- **Reproduction**: Use `cell` keyword in matrix formula to access current cell value
- **Observed**: Same LLVM error as BUG-009 (return type mismatch)
- **Expected**: `cell` should provide access to current cell value
- **Files**: `codegen/matrix.py`, `codegen/statements.py`
- **Status**: Resolved (2026-01-17)
- **Resolution**: Fixed by same change as BUG-009. The `cell` keyword was working correctly;
  the issue was that formulas using `cell` also use `return` which had the same bug.

### BUG-024: Task completion notification not optimized
- **Discovered**: 2025-01-17, during codebase scan
- **Category**: Runtime
- **Severity**: Low
- **Reproduction**: N/A - performance optimization
- **Observed**: `coex_task_wait_any` polled with 1ms timeout, only waiting on first task
- **Expected**: Immediate wake-up when any task completes
- **Files**: `runtime/coex_task.c`, `runtime/coex_task.h`
- **Status**: Resolved (2026-01-17)
- **Resolution**: Implemented shared waiter mechanism for `wait_any`:
  - Added `SharedWaiter` struct with mutex/condvar for wait groups
  - Added `shared_waiter` field to `TaskClosure` (after LLVM-visible fields)
  - `coex_task_wait_any` now registers a shared waiter with all closures
  - `coex_task_signal_complete` signals the shared waiter if present
  - All 21 first/most tests pass, eliminating 1ms polling delay

### BUG-025: GC stack overflow with large lists (500k+ elements)
- **Discovered**: 2025-01-17, during codebase scan
- **Category**: GC
- **Severity**: High
- **Reproduction**: Create list with 500,000-750,000+ elements, trigger GC
- **Observed**: Was crashing with `EXC_BAD_ACCESS` at stack addresses during GC marking
- **Expected**: GC should handle arbitrarily large collections
- **Files**: `coex_gc.py`
- **Status**: Resolved (2026-01-17)
- **Resolution**: Fixed by Phase 5 worklist-based marking implementation:
  - `gc_mark_object` now uses `gc_mark_push` to add child handles to worklist
  - `gc_mark_drain` processes worklist iteratively instead of recursive calls
  - Verified with stress tests: 750k, 1M, and 10M element lists all pass
  - All 12 GC stress tests pass including 1M allocations with nested function calls

### BUG-011: Nested UDT to JSON conversion not implemented
- **Discovered**: 2025-01-17, during codebase scan
- **Category**: Codegen
- **Severity**: Low
- **Reproduction**: Create nested user-defined types and convert to JSON
- **Observed**: Segfault when converting UDT with nested UDT/enum fields to JSON
- **Expected**: Nested types should serialize to nested JSON objects
- **Hypothesis**: JSON codegen only handles flat UDTs, not recursive traversal
- **Files**: `codegen/json_type.py` (convert_field_to_json)
- **Status**: Resolved (2026-01-17)
- **Resolution**: Fixed `convert_field_to_json` to properly handle GC handles:
  - UDT fields are stored as i64 GC handles, not raw pointers
  - Was incorrectly using `inttoptr(handle)` treating handle value as address
  - Now calls `gc_handle_deref(handle)` to get actual pointer, then bitcasts
  - Added support for nested enum fields in UDTs
  - All 62 JSON tests pass including new deeply-nested and enum tests

### BUG-026: Test files use `=` instead of `:=` for task assignment
- **Discovered**: 2026-01-17, during GPU offload implementation testing
- **Category**: Semantic
- **Severity**: Low
- **Reproduction**: Run `python3 -m pytest tests/test_scheduler.py tests/test_task_state_machine.py`
- **Observed**: 6 tests fail with error: `Cannot assign task result with '=' operator`
- **Expected**: Tests should use correct `:=` syntax for task calls
- **Files**: `tests/test_scheduler.py`, `tests/test_task_state_machine.py`
- **Status**: Resolved (2026-01-17)
- **Resolution**: Updated all task call assignments from `=` to `:=`:
  - Fixed ~25 occurrences across both test files
  - Tests were written before BUG-012 fix enforced `:=` for task assignment
  - All 34 tests now pass

### BUG-028: Array iteration in comprehensions not implemented
- **Discovered**: 2026-01-18, during GPU offload implementation testing
- **Category**: Codegen
- **Severity**: Medium
- **Reproduction**: `[f(x) for x in arr]` where `arr` is an Array<T>
- **Observed**: Loop variable `x` is not bound; falls through to "unknown iterable type" path
- **Expected**: Array iteration should work like List iteration in comprehensions
- **Files**: `codegen/comprehensions.py:210-212` - Array case falls through without binding pattern
- **Status**: Fixed (2026-01-18)
- **Resolution**: Added Array iteration support in `codegen/comprehensions.py` after List handling. Uses `array_len` and `array_get` to iterate, same pattern as List iteration.
- **Tests**: `tests/test_array_comprehension.py` - 6 passing tests covering basic iteration, filters, formulas, set/map comprehensions, and multiple clauses.

### BUG-029: MapComprehension not handled in formula offload check
- **Discovered**: 2026-01-18, during BUG-028 fix testing
- **Category**: Codegen
- **Severity**: Low
- **Reproduction**: `{x: x * 10 for x in arr}` where `arr` is an Array<T>
- **Observed**: `AttributeError: 'MapComprehension' object has no attribute 'body'` in formula offload check
- **Expected**: MapComprehension should use `key` and `value` fields instead of `body`
- **Files**: `codegen/formula/__init__.py:241` - `_check_comprehension` accesses `node.body` but MapComprehension has `node.key`/`node.value`
- **Status**: Fixed (2026-01-18)
- **Resolution**: Refactored comprehension AST nodes to use consistent field naming:
  - Renamed `body` to `value` in ListComprehension and SetComprehension (ast_nodes.py)
  - Updated ast_builder.py, codegen/comprehensions.py, codegen/formula/__init__.py, analysis/cfg.py
  - Added explicit MapComprehension handling in `_check_comprehension` to check both `key` and `value`
- **Tests**: `tests/test_array_comprehension.py::test_array_map_comprehension` now passes

### BUG-030: Array filter comprehension not working
- **Discovered**: 2026-01-18, during GPU offload testing
- **Category**: Codegen
- **Severity**: Medium
- **Reproduction**: `[x for x in arr if x % 2 == 0]` where `arr` is an Array<int> with values [0,1,2,3,4,5]
- **Observed**: Returns 6 elements instead of 3; GPU offload was ignoring the filter condition
- **Expected**: Should return only even elements [0, 2, 4]
- **Files**: `codegen/formula/__init__.py`
- **Status**: Fixed (2026-01-18)
- **Resolution**: GPU offload was incorrectly handling filtered comprehensions. The filter condition was checked for eligibility but then ignored in the kernel. Fixed by restricting GPU offload to only handle ListComprehensions without filter conditions. Comprehensions with filters now use the correct CPU path.
- **Tests**: `tests/test_array_comprehension.py::test_array_iteration_with_filter` passes

### BUG-031: Set comprehension over Array not working
- **Discovered**: 2026-01-18, during GPU offload testing
- **Category**: Codegen
- **Severity**: Medium
- **Reproduction**: `{x for x in arr}` where `arr` is an Array<int> with values [0,1,2,0,1]
- **Observed**: Returns 5 elements instead of 3 (GPU was producing Array instead of Set)
- **Expected**: Should return Set with 3 unique elements {0, 1, 2}
- **Files**: `codegen/formula/__init__.py`
- **Status**: Fixed (2026-01-18)
- **Resolution**: GPU offload was incorrectly handling SetComprehension. The GPU kernel produces an Array output, but Sets have different semantics (deduplication). Fixed by restricting GPU offload to only handle ListComprehension. Set comprehensions now use the correct CPU path which properly constructs Sets.
- **Tests**: `tests/test_array_comprehension.py::test_array_set_comprehension` passes

### BUG-032: Map comprehension over Array not working
- **Discovered**: 2026-01-18, during GPU offload testing
- **Category**: Codegen
- **Severity**: Medium
- **Reproduction**: `{x: x * 10 for x in arr}` where `arr` is an Array<int> with values [1,2,3]
- **Observed**: Returns wrong values (GPU was producing Array instead of Map)
- **Expected**: Should return map {1: 10, 2: 20, 3: 30}
- **Files**: `codegen/formula/__init__.py`
- **Status**: Fixed (2026-01-18)
- **Resolution**: GPU offload was incorrectly handling MapComprehension. The GPU kernel produces an Array output, but Maps have different semantics (key-value pairs). Fixed by restricting GPU offload to only handle ListComprehension. Map comprehensions now use the correct CPU path which properly constructs Maps.
- **Tests**: `tests/test_array_comprehension.py::test_array_map_comprehension` passes

### BUG-027: Flaky test - first with computation in body returns wrong result
- **Discovered**: 2026-01-18, during GPU offload implementation testing
- **Category**: Runtime
- **Severity**: High
- **Reproduction**: Run `python3 -m pytest tests/test_complex_first_most.py::TestComplexBodyTokenRing::test_first_with_computation_in_body`
- **Observed**: Test returns 625 (25^2) or 1225 (35^2) non-deterministically instead of 225 (15^2)
- **Expected**: Should return 225, which is (10+5)^2 - the first element's computation
- **Files**: `runtime/coex_scheduler.c`, `runtime/coex_scheduler.h`
- **Status**: Fixed (2026-01-18)
- **Resolution**: Implemented priority-based winner selection for `first` construct. When multiple tasks complete around the same time, the task with the lowest element index now wins. Key changes:
  1. Changed `has_winner` (boolean) to `winner_index` (int64, initialized to INT64_MAX) in FirstContext
  2. Modified `handle_first_completion` to use CAS loop to only allow lower-indexed tasks to become winners
  3. Added re-check of winner_index under mutex before updating winner_value to prevent race where a later task overwrites the correct value
  4. Changed `coex_scheduler_first_wait` to wait until all tasks complete, ensuring the lowest-indexed task's value is stored before returning
- **Root Cause**: When parent tasks (`__first_body_1`) completed around the same time, whichever called `handle_first_completion` first would win, regardless of element index. Additionally, the winner_value update could be overwritten by a higher-indexed task that got the mutex later.

### BUG-046: Thread-based first returns temporally first result instead of index-0 result
- **Discovered**: 2026-01-19, during GitHub CI failure on Linux
- **Category**: Codegen
- **Severity**: High
- **Reproduction**: `result = first x in [1,2,3] compute(x) ~` where `compute` is a `thread`
- **Observed**: Returns 6 (3*2) on Linux when thread 2 completes first temporally
- **Expected**: Should return 2 (1*2) - the first element's result, for deterministic behavior
- **Files**: `codegen/loops.py`
- **Status**: Fixed (2026-01-19)
- **Resolution**: The scheduler-based `first` (for `task`) was fixed in BUG-027 to use priority-based winner selection (lowest index wins). However, the thread-based `first` (for `thread`) still used `task_wait_any` to determine the winner based on temporal completion order. Fixed by:
  1. Changed result extraction to always use index 0 instead of the `wait_any` winner
  2. Changed cancel logic to never cancel index 0 (always let it complete)
  3. All threads are joined, so index 0's result is always available
- **Root Cause**: Thread-based and scheduler-based `first` implementations had divergent semantics. Thread path used temporal winner selection while scheduler path used priority-based selection.

---

## Notes

### Session Protocol
1. **Session Start**: Review BUGS.md, summarize current state
2. **Pre-Task**: Check if any open bugs interact with planned work
3. **During Development**: Bug-on-discovery rule applies (document immediately)
4. **Session End**: Review work done, ensure all encountered bugs are recorded

### External Dependencies
- llvmlite TLS issue: See BUG-023

### Bug Count Summary (as of 2026-02-04)
- **Open**: 10 bugs (BUG-015, BUG-023, BUG-033, BUG-035, BUG-036, BUG-042, BUG-043, BUG-044, BUG-050, BUG-057)
- **Resolved**: 49 bugs (including BUG-004: CAS-based TLAB allocation, BUG-016: gc_async race condition)

### Lock Audit Bugs (BUG-033 to BUG-044)
- **Resolved (by design)**: BUG-034, BUG-037, BUG-038, BUG-039, BUG-040, BUG-041 - condition variable mutexes mandated by POSIX
- **Open (under review)**: BUG-033, BUG-035, BUG-036, BUG-042, BUG-043, BUG-044 - data structure protection locks

### BUG-047: Parenthesized expression parsing fails
- **Discovered**: 2026-01-19, during Array<T> implementation testing
- **Category**: Parser/AST Builder
- **Severity**: Medium
- **Reproduction**: Test `test_parentheses_override_precedence` in test_basic.py
- **Observed**: `TypeError: 'ExpressionContext' object is not subscriptable` in ast_builder.py:1121
- **Expected**: Parenthesized expressions like `(1 + 2) * 3` should parse correctly
- **Hypothesis**: `ctx.expression()` returns ExpressionContext directly when single expression, not a list. Need to check for this case.
- **Files**: ast_builder.py:1121
- **Fix**: Changed `exprs = ctx.expression(); return self.visit_expression(exprs[0])` to `expr = ctx.expression(); return self.visit_expression(expr)` - grammar rule `LPAREN expression RPAREN` has single expression, not list
- **Status**: Fixed (2026-01-19)

### BUG-048: GPU offload marshaling used old Array layout
- **Discovered**: 2026-01-19, during GPU GEMM benchmark development
- **Category**: Codegen/GPU
- **Severity**: High
- **Reproduction**: Any formula comprehension over Array type with GPU offload enabled
- **Observed**: Segmentation fault during GPU dispatch; marshaling code tried to call `gc_handle_deref` on raw pointer
- **Expected**: GPU offload should work correctly with Arrays
- **Hypothesis**: Marshaling code in `codegen/formula/marshaling.py` was using old 5-field Array layout instead of new 13-field N-D layout
- **Files**: codegen/formula/marshaling.py
- **Fix**: Updated field indices for new layout (handle=0, ndim=1, shape=2[4], strides=3[4], offset=4, elem_size=5, type_id=6). Fixed handle field to use `inttoptr` (raw pointer stored as i64) instead of `gc_handle_deref`.
- **Status**: Fixed (2026-01-19)

### BUG-049: GPU transpiler only handled FORMULA, not FORMULA32
- **Discovered**: 2026-01-19, during GPU benchmark development
- **Category**: Codegen/GPU
- **Severity**: Medium
- **Reproduction**: Use `formula32` in a list comprehension that should GPU-offload
- **Observed**: "Cannot transpile call to 'func_name' for GPU" error, falls back to CPU
- **Expected**: Both `formula` and `formula32` should be inlinable for GPU
- **Hypothesis**: Transpiler check at line 207 only checked `FunctionKind.FORMULA`
- **Files**: codegen/formula/transpiler.py
- **Fix**: Changed check to `decl.kind in (FunctionKind.FORMULA, FunctionKind.FORMULA32)`
- **Status**: Fixed (2026-01-19)

### BUG-052: JSON array literals in objects cause crash
- **Discovered**: 2026-01-22, during BUG-051 fix testing
- **Category**: Codegen
- **Severity**: High
- **Reproduction**:
  ```coex
  func main() -> int
      j: json = { items: [1, 2, 3] }
      arr: json = j.items
      print(arr.len())  # CRASH
      return 0
  ~
  ```
- **Observed**: Segmentation fault (signal 11) when accessing array field from JSON object literal
- **Expected**: Array field should be accessible and have correct length
- **Root Cause**: `convert_list_to_json_array` used runtime heuristics to guess whether list elements were integers or JSON pointers. It tried to dereference values as pointers before checking if they were valid pointer addresses, causing crashes when dereferencing small integers like 1, 2, 3.
- **Files**: `codegen/json_type.py:convert_list_to_json_array`
- **Status**: Fixed (2026-01-22)
- **Resolution**: Completely rewrote the list-to-JSON-array conversion to use compile-time type information:
  1. For `ListExpr` (literal lists like `[1, 2, 3]`), iterate through AST elements at compile time and convert each with proper type knowledge
  2. For other lists (variables), use type inference (`_infer_type_from_expr`) to determine element type
  3. Generate type-appropriate conversion code (json_new_int for ints, json_new_float for floats, json_new_string for strings, etc.)
  4. No more runtime pointer guessing - element types are known at compile time

### BUG-055: SVG drag state keys persist after mouse release
- **Discovered**: 2026-01-23, during SVG comprehensive demo testing
- **Category**: Runtime
- **Severity**: Medium
- **Reproduction**: Run `svg_comprehensive_demo`, drag the orange box, release mouse, start second drag
- **Observed**: Box position resets to origin on second drag instead of continuing from previous position
- **Expected**: Drag position should accumulate between drag operations
- **Root Cause**: In `render_svg_image()`, the drag state keys (`{state_key}_dragging`, `_drag_dx`, `_drag_dy`) were only added when `is_item_active()` returned true, but never removed when false. Since `new_state` is initialized by copying all keys from the input state (line 1344-1350), these keys persisted forever. The Coex code's "drag ended" detection (`else` branch checking `is_dragging == 1`) never fired because `boxClicked_dragging` was still present in state.
- **Files**: `runtime/coex_ui.c:render_svg_image()`
- **Status**: Fixed (2026-01-23)
- **Resolution**: Added `else` clause to explicitly remove drag keys from `new_state` using `cJSON_DeleteItemFromObject()` when `is_item_active()` returns false. This allows the Coex code to detect the drag-end transition and commit the accumulated offset.

### BUG-051: json.parse returns empty object/array for complex JSON
- **Discovered**: 2026-01-22, during UI library JSON literal integration
- **Category**: Codegen
- **Severity**: High
- **Reproduction**:
  ```coex
  func main() -> int
      result: json = json.parse("{\"name\":\"Alice\",\"age\":30}")
      print(result.stringify())  # Prints "{}" instead of the parsed object
      return 0
  ~
  ```
- **Observed**: `json.parse` returns empty `{}` for objects and empty `[]` for arrays regardless of input content. Primitives (null, true, false, numbers) parse correctly.
- **Expected**: Full recursive parsing of JSON strings into Json objects
- **Root Cause**: The `_implement_json_parse` function in `codegen/json_type.py` had stub implementations for arrays and objects that just returned empty containers.
- **Files**: `codegen/json_type.py` (`_implement_json_parse` method, `_declare_cjson_types`, `_implement_json_from_cjson`)
- **Status**: Fixed (2026-01-22)
- **Resolution**:
  1. Declared cJSON struct type and external functions (cJSON_Parse, cJSON_Delete) in LLVM IR
  2. Implemented `coex_json_from_cjson` recursive converter that walks cJSON tree and builds Coex Json objects
  3. Updated `_implement_json_parse` to use cJSON for array/object parsing
  4. cJSON library now always linked in `coexc.py`
  5. Added 12 comprehensive tests in `tests/test_json.py::TestJsonParse`

### BUG-056: Task transform uses invalid comparison operators for icmp
- **Discovered**: 2026-01-28, during scheduler stress test development
- **Category**: Codegen
- **Severity**: Medium
- **Reproduction**:
  ```coex
  task dispatch(i: int, is_heavy: bool) -> int
      if is_heavy
          return 1
      else
          return 0
      ~
  ~

  task coordinator() -> int
      for i in 0..10
          r := dispatch(i, i % 4 == 0)  # Comparison as task argument
      ~
      return 0
  ~

  func main() -> int
      print(coordinator())
      return 0
  ~
  ```
- **Observed**: `ValueError: invalid comparison 'eq' for icmp` in llvmlite
- **Expected**: Comparison expressions should work as task call arguments
- **Root Cause**: In `task_transform.py:2362-2366`, the `_evaluate_expr_in_state_context` method uses LLVM IR predicate names (`'eq'`, `'ne'`, `'slt'`) instead of llvmlite's expected operator strings (`'=='`, `'!='`, `'<'`). The main codegen in `expressions.py` uses the correct format.
- **Files**: `task_transform.py:2360-2375`
- **Status**: Fixed (2026-01-28)
- **Resolution**: Changed comparison operator mapping from LLVM IR predicates (`'eq'`, `'ne'`, `'slt'`, etc.) to llvmlite's expected format (`'=='`, `'!='`, `'<'`, etc.). Unified the mapping for both integer and float comparisons.

### BUG-070: json_set_index uses wrong elem_size (8 instead of 16)
- **Discovered**: 2026-01-29, during JSON refactoring implementation
- **Category**: Codegen
- **Severity**: High
- **Reproduction**:
  ```coex
  func main() -> int
      j: json := [1, 2, 3]
      j2: json = j.set(1, 42)
      print(j2.get(1).as_int())  # May return corrupted data
      return 0
  ~
  ```
- **Observed**: `json_set_index` uses `elem_size = 8` (pointer size) for `list_set` call
- **Expected**: Should use `elem_size = 16` (Json struct size: tag i64 + value i64)
- **Root Cause**: The BUG-069 fix was applied to `json_append` (line 1379) but the same fix was not applied to `json_set_index` (line 1335). JSON arrays store 16-byte inline Json structs, not 8-byte pointers.
- **Files**: `codegen/json_type.py:1335`
- **Status**: Fixed (2026-01-29)
- **Resolution**: Changed `elem_size` from 8 to 16 in `_implement_json_set_index`, consistent with `json_append`.

### BUG-072: json.parse() stores all numbers as floats, as_int() doesn't convert
- **Discovered**: 2026-01-29, during JSON value semantics test development
- **Category**: Codegen
- **Severity**: High
- **Reproduction**:
```coex
func main() -> int
    j: json = json.parse("[1,2,3]")
    e0: json = j[0]
    print(e0.as_int())    # Was printing 4607182418800017408 (float bits for 1.0)
    return 0
~
```
- **Observed**: `as_int()` returned garbage (IEEE 754 bit representation of float value)
- **Expected**: `as_int()` should return the integer value (1)
- **Root Cause**: `json.parse()` stored all numbers as floats (TYPE_JSON_FLOAT) because cJSON uses doubles internally. However, `json_as_int()` didn't check the type - it just read the raw bits as int64, misinterpreting float bit patterns.
- **Files**: `codegen/json_type.py` (_implement_json_from_cjson, _implement_json_as_int, _implement_json_as_float)
- **Status**: Fixed (2026-01-30)
- **Resolution**:
  1. Updated `_implement_json_from_cjson` to detect integer values when parsing:
     - Convert double to int64 via fptosi, then back to double via sitofp
     - If values are equal and in int64 range, create TYPE_JSON_INT
     - Otherwise create TYPE_JSON_FLOAT
  2. Updated `_implement_json_as_int` to check type before returning:
     - TYPE_JSON_INT: return raw i64 value
     - TYPE_JSON_FLOAT: convert f64 to i64 via fptosi
     - Other types: return 0
  3. Updated `_implement_json_as_float` to handle both types:
     - TYPE_JSON_FLOAT: return raw f64 value (bitcast from i64)
     - TYPE_JSON_INT: convert i64 to f64 via sitofp
     - Other types: return 0.0
- **Tests**: All 74 JSON tests pass

### BUG-074: json.set() with integer index dispatches to set_field instead of set_index
- **Discovered**: 2026-01-29, during JSON value semantics test development
- **Category**: Codegen
- **Severity**: High
- **Reproduction**:
```coex
func main() -> int
    j: json := [1, 2, 3]
    j2: json = j.set(1, 42)    # Compilation error: type mismatch
    return 0
~
```
- **Observed**: Compilation error `Type of #2 arg mismatch: i64 != %"struct.String"*`
- **Expected**: `j.set(1, 42)` should dispatch to `json_set_index` and work correctly
- **Root Cause**: Two issues:
  1. Method dispatch in `codegen/expressions.py` routed all `.set()` calls to `json_set_field`
  2. `json_set_index` stored raw Json* pointers (8 bytes) instead of TaggedValues with handles
- **Files**: `codegen/expressions.py` (generate_method_call), `codegen/json_type.py`
- **Status**: Fixed (2026-01-30)
- **Resolution**:
  1. Added special handling in `expressions.py:generate_method_call` to detect `Json.set` and dispatch based on argument type (int → `json_set_index`, string → `json_set_field`)
  2. Fixed `_implement_json_set_index` in `json_type.py` to use TaggedValue with GC handle, matching `json_get_index` expectations
- **Tests**: All 74 JSON tests + 35 GC tests pass

### BUG-076: List<json> elements not surviving GC due to PVNode marking not tracing handles
- **Discovered**: 2026-01-30, during Map/Set handle storage implementation
- **Category**: GC
- **Severity**: High
- **Reproduction**:
```coex
func main() -> int
    base: json = { value: 42 }
    results: List<json> = []

    for i in 0..5
        modified: json = base.set("value", i)
        results = results.append(modified)

        if i % 2 == 0
            gc()
        ~
    ~

    # This crashes - JSON elements not properly marked
    for i in 0..5
        print(results.get(i).get("value").as_int())
    ~
    return 0
~
```
- **Observed**: Segmentation fault after GC runs. The JSON objects stored in the List are freed because they weren't marked.
- **Expected**: JSON elements should survive GC and be accessible after collection.
- **Root Cause**: After the handle storage conversion, reference type elements in Lists are stored as handles (i64 indices) rather than raw pointers. The List uses a Persistent Vector (PV) structure where:
  1. Internal PVNodes contain pointers to child PVNodes
  2. Leaf PVNodes contain the actual element data

  The `gc_mark_object` for TYPE_PV_NODE iterates through 32 children and calls `gc_ptr_to_handle` on each, assuming they are all pointers to more PVNodes. However, for leaf nodes containing reference type elements, those "children" are now handles (small integers), not pointers.

  When `gc_ptr_to_handle` is called on a handle value (like 5), it tries to dereference that small address to read the object's forward field, causing undefined behavior or returning an invalid handle. The underlying JSON objects don't get marked and are freed.

  The GC doesn't have element type information for PVNodes, so it can't distinguish between:
  - Internal nodes (children are PVNode pointers - mark as objects)
  - Leaf nodes with primitive elements (no marking needed)
  - Leaf nodes with reference type elements (children are handles - mark directly)

- **Files**:
  - `coex_gc.py` (`_implement_gc_mark_object`, mark_pv_node section)
  - `codegen/list.py` (list_new, list_append)
  - `codegen/core.py` (list_struct definition)
- **Status**: Fixed (2026-01-30)
- **Fix Implemented**:
  1. Added `TYPE_LIST_TAIL_REF` (type ID 15) for tail/leaf buffers containing reference type handles
  2. Added `flags` field (field 6) to List struct with `LIST_FLAG_ELEM_IS_REF` bit
  3. Updated `list_new` to allocate tail with correct type based on flags and zero-initialize for ref types
  4. Updated `list_append`, `list_set`, `list_getrange`, `list_setrange` to propagate flags
  5. Added `mark_list_tail_ref` block in GC to iterate and mark handles in ref-type buffers
  6. Updated all `list_new` call sites to pass appropriate flags
- **Final Resolution**: The remaining `List<json>` issue was resolved by BUG-078 fix, which corrected map value marking in `gc_mark_hamt`. All List types with reference elements now work correctly with GC.

### BUG-077: Array<string> and other reference type Arrays need handle storage updates
- **Discovered**: 2026-01-30, during Map/Set handle storage implementation
- **Category**: Codegen
- **Severity**: Medium
- **Reproduction**:
```coex
func main() -> int
    list: List<string> = ["hello", "world"]
    a: Array<string> = list.packed()
    b: Array<string> = a
    b = b.set(0, "goodbye")
    print(a.get(0))   # Works, prints "hello"
    print(b.get(0))   # Crashes
    return 0
~
```
- **Observed**: First `a.get(0)` works, but `b.get(0)` after `.set()` causes segmentation fault.
- **Expected**: Both prints should work, showing COW (copy-on-write) semantics.
- **Root Cause**: After implementing handle storage for Lists, Maps, and Sets, the Array type also needs similar updates:
  1. Array.set for reference types should store handles, not raw pointers
  2. Array.get for reference types should dereference handles
  3. Array literal generation should store handles for reference elements
  4. Array iteration (`for elem in arr`) should dereference handles
  5. list.packed() conversion should convert pointers to handles when building the Array
  6. gc_mark_array should trace handle elements appropriately

  Currently, Array operations still use the old pointer-based approach, causing mismatches when interacting with handle-based Lists.

- **Files**:
  - `codegen/array.py` (array_new_ref implementation)
  - `codegen/core.py` (Array method dispatch, _list_to_array)
  - `codegen/expressions.py` (Array.get, Array.set handlers)
  - `codegen/loops.py` (generate_array_for)
  - `codegen/conversions.py` (list_to_array)
  - `coex_gc.py` (TYPE_ARRAY_DATA_REF, mark_array_data_ref)
- **Status**: Fixed (2026-01-30)
- **Resolution**:
  1. Added `TYPE_ARRAY_DATA_REF` GC type constant for array data buffers containing reference type handles
  2. Added `array_new_ref()` helper function that allocates data buffer with TYPE_ARRAY_DATA_REF
  3. Added `mark_array_data_ref` block in `_implement_gc_mark_object` to iterate through and mark handles
  4. Updated `list_to_array()` to accept `is_ref_type` parameter and call `array_new_ref` for reference types
  5. Updated `.packed()` method call sites to detect if List has reference type elements
  6. Updated `Array.set` in expressions.py to convert pointers to handles for reference types
  7. Updated `generate_array_for` in loops.py to dereference handles when iterating reference type arrays
  8. Added `get_array_element_coex_type()` method to determine element type for iteration
- **Tests**: `tests/test_array_ref_types.py` - 8 passing, 2 xfail (parser issue with nested generics)

### BUG-078: JSON variables crash on GC - Map values treated as handles instead of pointers
- **Discovered**: 2026-01-30, during BUG-076 verification
- **Category**: GC
- **Severity**: High
- **Reproduction**:
```coex
func main() -> int
    j: json = { value: 42 }
    gc()
    print(j.get("value").as_int())
    return 0
~
```
- **Observed**: Segmentation fault during gc() when marking JSON object children. Crash in `gc_handle_deref` with pointer-sized value (e.g., 0x9403c8680) being treated as handle.
- **Expected**: JSON variable should survive GC and be accessible after collection.
- **Root Cause**: **Mismatch between map value storage and GC marking expectation**.

  In `generate_json_object()` (json_type.py), JSON values are stored in maps using:
  ```python
  json_i64 = builder.ptrtoint(json_value, i64)  # Convert pointer to i64
  map_ptr = builder.call(cg.map_set_string, [..., json_i64])  # Store raw pointer as i64
  ```

  But in `_implement_gc_mark_hamt()` (coex_gc.py), the marking code assumed values were already handles:
  ```python
  value_handle = builder.load(value_handle_ptr)  # Reads raw pointer value
  builder.call(self.gc_mark_object, [value_handle])  # Passes pointer to handle-expecting function!
  ```

  This caused gc_mark_object to treat a raw pointer as a handle, then gc_handle_deref tried to index into the handle table at an absurdly large index, causing the crash.

- **Files**:
  - `coex_gc.py` (_implement_gc_mark_hamt - value marking)
  - `codegen/json_type.py` (generate_json_object - stores pointers in maps)
- **Status**: Fixed (2026-01-30)
- **Resolution**:
  Fixed `_implement_gc_mark_hamt()` to convert map value pointers to handles before marking, matching the pattern already used for map keys:
  ```python
  value_as_ptr = builder.inttoptr(value_as_int, self.i8_ptr)
  value_handle = builder.call(self.gc_ptr_to_handle, [value_as_ptr])
  builder.call(self.gc_mark_object, [value_handle])
  ```
- **Tests**: 109 tests pass (tests/test_gc.py + tests/test_json.py)

### BUG-079: GC crashes on uninitialized buffer contents after TLAB recycling
- **Discovered**: 2026-02-03, during Galaxian game debugging
- **Category**: GC
- **Severity**: Critical
- **Reproduction**: Run Galaxian example (`galaxian_debug`) for several thousand frames under heavy allocation pressure (~3,500 allocations/frame). Crash occurs non-deterministically, typically after debug dump output to console.
- **Observed**: Segmentation fault in `gc_handle_deref` during concurrent GC mark phase. The GC dereferences a random/stale value from a handle buffer as if it were a valid handle index.
- **Expected**: GC should only trace valid handles. Newly allocated buffers should contain zeroes (null handles) in unused slots.
- **Root Cause**: **`alloc_arena_or_gc` does not zero user data area.** The GC's mark routines scan buffer contents based on buffer *capacity* (derived from the object header size field), not actual element count:

  - `mark_list_tail_tagged`: Scans `buffer_size / 16` slots (full capacity)
  - `mark_pv_node`: Scans all 32 children slots regardless of occupancy
  - `mark_hamt_node`: Scans children based on bitmap popcount (correct)
  - `TYPE_ARRAY_DATA_REF`: Scans `size / 8` slots (full capacity)

  When TLAB memory is recycled after churn, stale non-zero data from previously freed objects remains in the allocated buffer. The GC interprets these stale values as live handles and attempts to dereference them, causing a crash.

  Fresh TLAB pages from `mmap` are zero-filled by the OS, so the bug only manifests after enough allocation churn to recycle TLAB memory — explaining why it takes thousands of frames to appear.

  Debug dumps accelerate the crash because: (1) string formatting causes additional allocations that churn TLAB memory faster, and (2) I/O blocking changes thread scheduling, giving the GC thread more CPU time to race against the mutator.

- **Affected Allocation Sites (11 unzeroed sites found by audit)**:
  - `codegen/list.py:332` — PV_NODE `create_root_block` (children[1..31] unzeroed)
  - `codegen/list.py:427` — PV_NODE `copy_and_insert` (memcpy from source, but new slots unzeroed)
  - `codegen/list.py:515` — PV_NODE `push_down_block` (memcpy from source)
  - `codegen/list.py:910` — PV_NODE in `_implement_list_set` (memcpy from source)
  - `codegen/list.py:1015` — PV_NODE in `_implement_list_set` update path (memcpy from source)
  - `codegen/list.py:953` — TYPE_LIST_TAIL leaf in set path (memcpy full 32 elements)
  - `codegen/list.py:1054` — TYPE_LIST_TAIL leaf in set update path (memcpy full 32 elements)
  - `codegen/array.py:367` — TYPE_ARRAY_DATA_REF buffer (GC scans size/8 slots)
  - `codegen/hamt.py:316` — HAMT node allocation
  - `codegen/hamt.py:335` — HAMT children array
  - `codegen/hamt.py:362` — HAMT leaf allocation

- **Files**:
  - `coex_gc.py` (`_implement_gc_alloc_arena_or_gc` — allocation function)
  - `codegen/list.py` (`create_root_block` — PV_NODE allocation)
  - `codegen/array.py` (TYPE_ARRAY_DATA_REF allocation)
  - `codegen/hamt.py` (HAMT node/children/leaf allocations)
- **Status**: Fixed (2026-02-03)
- **Resolution**:
  Two fixes applied:

  1. **Site-specific fix** (`codegen/list.py:332`): Added memset to zero PV_NODE children array in `create_root_block`, matching the pattern already used in `depth_increase_block` (line 371) and `create_child_block` (line 495).

  2. **Comprehensive fix** (`coex_gc.py:6229`): Added `memset(user_ptr, 0, size)` at the phi merge point in `alloc_arena_or_gc`, zeroing ALL user data areas for every allocation regardless of type. This follows the standard approach used by Java, .NET, and Go garbage collectors. Covers all 11 affected sites and prevents future regressions from new allocation sites.

  ```python
  # Zero the user data area to prevent the GC from tracing
  # uninitialized memory.
  builder.call(self.codegen.memset, [
      user_ptr, ir.Constant(ir.IntType(8), 0), size
  ])
  ```
- **Tests**: 291 passed, 2 xfailed (pre-existing). 1 pre-existing timeout in `test_first_with_multiple_conditions` (unrelated).

### BUG-088: gc_safepoint runs collection on calling thread instead of delegating to GC thread
- **Discovered**: 2026-02-03, during Galaxian crash analysis
- **Category**: GC
- **Severity**: High
- **Reproduction**: Any program that triggers GC via safepoint threshold. The safepoint function (`coex_gc_safepoint`) calls `gc_collect()` directly on the calling thread (e.g. main thread) rather than signaling the dedicated GC thread (#1) to perform collection.
- **Observed**: When `gc_alloc_count >= GC_THRESHOLD` at a safepoint, the calling thread (often main) enters `gc_collect` directly. This means the main thread performs root scanning, marking, and sweeping — work that should be handled by the GC thread. macOS crash reports show `coex_gc_mark_object` and `coex_gc_handle_deref` on thread #0 (main), while the GC thread (#1) sleeps on `psynch_cvwait`.
- **Expected**: All GC collection should be performed by the dedicated GC thread (#1). Calling threads should only signal the GC thread to wake up, then either wait for completion or continue (depending on whether stop-the-world is needed).
- **Root Cause**: `_implement_gc_safepoint()` at line 4347 calls `gc_collect()` directly:
  ```python
  builder.position_at_end(do_gc)
  builder.call(self.gc_collect, [])  # Runs collection on calling thread!
  ```
  The GC thread (`gc_thread_main`) also calls `gc_collect()`. While a CAS on `gc_in_progress` prevents concurrent collection, running GC on the mutator thread is architecturally wrong — the mutator is both scanning its own shadow stack (which it was just modifying) and running collection logic, which increases the risk of subtle race conditions.
- **Files**:
  - `coex_gc.py` (`_implement_gc_safepoint` line 4347, `_implement_gc_thread_main` line 4925)
- **Status**: Fixed (2026-02-03)
- **Fix**: Replaced the direct `gc_collect()` call in `_implement_gc_safepoint()` with delegation to the GC thread. The safepoint now:
  1. Locks the GC mutex
  2. Sets `gc_complete = 0` (prevents `gc_wait_for_completion` from returning early)
  3. Sets `gc_trigger_requested = 1`
  4. Signals `gc_cond_start` to wake the GC thread
  5. Unlocks the mutex
  6. Calls `gc_wait_for_completion()` to block until the GC thread finishes

  The GC thread (`gc_thread_main`) already checks `gc_trigger_requested` in its main loop, so no changes were needed there. All 37 GC tests pass including 2 new tests for safepoint delegation.

### BUG-090: Stack overflow from tagged_val allocas emitted inside loop bodies
- **Discovered**: 2026-02-03, during Galaxian crash analysis (lldb showed `EXC_BAD_ACCESS code=2` at stack guard page)
- **Category**: Codegen
- **Severity**: Critical
- **Reproduction**: Run Galaxian example (`./galaxian_debug`) for ~4000 frames. Crash is `EXC_BAD_ACCESS (code=2)` — stack guard page hit. The `stp` instruction in Metal driver's `endCommand()` writes past the stack limit.
- **Observed**: Stack overflow after ~4000 game loop iterations. `create_tagged_value()` in `coex_gc.py:1696` emitted `alloca` at the current builder position (inside loop body). In LLVM IR, `alloca` inside a loop allocates new stack space every iteration without freeing. With 248 tagged_val allocas per iteration × 16 bytes = 3,968 bytes/frame, the 8MB stack exhausts after ~2,000 frames.
- **Expected**: Stack usage should be constant regardless of loop iterations.
- **Root Cause**: `coex_gc.py:1696`:
  ```python
  tv_ptr = builder.alloca(self.tagged_value_type, name="tagged_val")
  ```
  This emits the `alloca` at whatever basic block the builder is positioned in. When called from within a loop body (e.g., list literal construction inside the game loop), the alloca ends up in a loop block, causing unbounded stack growth.
- **Files**:
  - `coex_gc.py` (`create_tagged_value` line 1696)
- **Status**: Fixed (2026-02-03)
- **Resolution**: Modified `create_tagged_value` to save the builder position, position at the function's entry block, emit the alloca there, then restore the builder position. This places all tagged_val allocas in the entry block where they're allocated once at function entry, not per loop iteration.
- **Tests**: Verified via `--emit-ir`: all 248 tagged_val allocas in main are now before the first `br` instruction (entry block). Galaxian compiles and runs past the previous crash point.

### BUG-091: Map-to-JSON conversion crashes at runtime (segfault)
- **Discovered**: 2026-02-04, during stale xfail cleanup
- **Category**: Codegen
- **Severity**: High
- **Reproduction**: `j: json := original_map` where original_map is `Map<string, int>` or `Map<int, int>`, then access `j.stringify()` or `j.get("key")`
- **Observed**: Segmentation fault when accessing the converted JSON object
- **Expected**: Map should be properly converted to a JSON object with string keys and JSON values
- **Root Cause**: `convert_to_json()` in `codegen/json_type.py:2762` called `json_new_object(map_ptr)` directly, wrapping the user map as-is. But `json_new_object` expects a map where values are `ptrtoint(Json*)` pointers, not raw integers. When JSON code tried to access values (treating raw int 30 as a Json* pointer), it dereferenced an invalid address.
- **Files**: `codegen/json_type.py`
- **Status**: Fixed (2026-02-04)
- **Resolution**: Implemented `convert_map_to_json_object()` which iterates the source map via `map_keys()`/`map_values()`, converts each key to String* (using `inttoptr` for string keys or `string_from_int` for int keys), converts each value to Json* based on the inferred value type, and builds a new JSON-compatible map with proper `MAP_FLAG_KEY_IS_PTR | MAP_FLAG_VALUE_IS_PTR` flags. Also added `_convert_map_value_to_json()` helper for type-based value conversion (int, float, bool, string, list, nested map).


### BUG-050: UI library shutdown segfault
- **Discovered**: 2026-01-21, during UI performance test
- **Category**: Runtime
- **Severity**: Low
- **Reproduction**: Run any UI test program (e.g., `./test_ui_performance`) and let it complete
- **Observed**: Segmentation fault (signal 11) occurs after test prints success message during `coex_ui_shutdown()`
- **Expected**: Clean shutdown without crash
- **Root Cause**: Two issues in shutdown sequence:
  1. **Metal renderer**: Missing `@autoreleasepool` block and font texture pointer not cleared in ImGui before releasing
  2. **Shell (macOS)**: Calling `[window close]` explicitly before releasing the window corrupted the window state, causing a crash when ARC tried to release it via `window = nil`
- **Files**: `runtime/coex_ui_metal.m`, `runtime/coex_ui_shell_macos.m`
- **Status**: Fixed (2026-02-04)
- **Resolution**:
  1. **Metal shutdown**: Added `@autoreleasepool` block and call to `coex_imgui_set_font_tex_id(NULL)` before releasing font texture
  2. **Shell shutdown**: Removed explicit `[window close]` call. Instead, just release the window by setting `window = nil` - ARC handles closing properly. Also added GPU sync before releasing Metal resources, and proper ordering (release metal_layer before view since view owns the layer)

### BUG-057: Module-level constant declarations not supported
- **Discovered**: 2026-01-28, during Galaxian game implementation
- **Category**: Parser
- **Severity**: Medium
- **Reproduction**:
  ```coex
  # At module level, outside any function:
  KEY_LEFT = 263
  KEY_RIGHT = 262

  func main() -> int
      print(KEY_LEFT)
      return 0
  ~
  ```
- **Observed**: Parser error: `Syntax error: Line X:Y - mismatched input '=' expecting IDENTIFIER`
- **Expected**: Module-level constant assignments should be allowed for defining named constants
- **Files**: `Coex.g4`, `ast_nodes.py`, `ast_builder.py`, `codegen/core.py`, `codegen/expressions.py`
- **Status**: Fixed (2026-02-04)
- **Resolution**: 
  1. Added `moduleConstDecl` rule to grammar: `const IDENTIFIER ASSIGN expression`
  2. Added `ModuleConstDecl` AST node and `module_consts` field to `Program`
  3. Updated `ast_builder.py` to visit and collect module-level constants
  4. Updated `codegen/core.py` to store constants in `self.module_constants` dictionary
  5. Updated `codegen/expressions.py` to check for module constants during identifier lookup and substitute the constant value expression
  6. Supports int, float, bool, and string constants
  7. Constants are compile-time substituted (no runtime storage)

### BUG-096: posix.open creates files with wrong permissions on ARM64 macOS
- **Discovered**: 2026-02-04, during test_posix_write failure investigation
- **Category**: Codegen/Stdlib
- **Severity**: Medium
- **Reproduction**: Any posix.open() call with mode "w" on ARM64 macOS
- **Observed**: Files created with permissions `-------r--` (0004) instead of `-rw-r--r--` (0644)
- **Expected**: Files should have permissions 0644 (or 0644 & ~umask)
- **Root Cause**: Two issues:
  1. **Wrong flag values**: Code used Linux O_CREAT|O_TRUNC flags (577) instead of macOS values (1537)
  2. **Calling convention mismatch**: `open()` is a variadic function on POSIX, but was declared as non-variadic in LLVM IR. On ARM64 Darwin, variadic arguments use a different calling convention than fixed arguments, so the mode value was being read from the wrong location.
- **Fix**:
  1. Updated O_WRONLY|O_CREAT|O_TRUNC from 577 (Linux) to 1537 (macOS)
  2. Changed `open()` declaration from `FunctionType(i32, [i8_ptr, i32, i32])` to `FunctionType(i32, [i8_ptr, i32], var_arg=True)` so LLVM generates correct variadic call code
- **Files**: `codegen/posix.py:49, 176-177`
- **Status**: Fixed (2026-02-04)

---

### BUG-097: posix.open() uses macOS-only O_CREAT|O_TRUNC flag values, fails on Linux
- **Discovered**: 2026-02-04, during CI failure investigation
- **Category**: Codegen/Stdlib
- **Severity**: High
- **Reproduction**: Run `test_posix_write` on Linux — file creation fails because flags 1537 don't mean O_WRONLY|O_CREAT|O_TRUNC on Linux
- **Observed**: `posix.open("file.txt", "w")` fails on Linux because the hardcoded flag value 1537 is macOS-specific
- **Expected**: Should use platform-appropriate flag values (macOS: 1537, Linux: 577)
- **Hypothesis**: BUG-096 fix hardcoded macOS values without platform detection
- **Fix**: Added `import sys` and `sys.platform == "darwin"` check in `codegen/posix.py` to select correct flag values per platform
- **Files**: `codegen/posix.py:23, 178-181`
- **Status**: Fixed (2026-02-04)

---

### BUG-098: Race condition in coex_task_signal_complete causes hang on Linux
- **Discovered**: 2026-02-04, during CI failure investigation
- **Category**: Runtime
- **Severity**: Critical
- **Reproduction**: Run `test_first_larger_collection` on Linux — hangs due to race between task thread signaling waiter and main thread clearing waiter
- **Observed**: Task thread reads `shared_waiter` under `closure->mutex`, then releases mutex before locking `waiter->mutex`. Main thread can destroy `waiter->mutex` in between, causing undefined behavior / hang.
- **Expected**: Waiter signaling should be atomic with respect to waiter lifecycle
- **Hypothesis**: The unlock-then-relock gap between `closure->mutex` and `waiter->mutex` creates a TOCTOU race
- **Fix**: Moved waiter signaling inside the `closure->mutex` hold. Lock order (closure->mutex -> waiter->mutex) is consistent with main thread, preventing deadlock.
- **Files**: `runtime/coex_task.c:166-182`
- **Status**: Fixed (2026-02-04)

### BUG-092: Audit all heap pointer storage for handle invariant violations
- **Discovered**: 2026-02-04, during Channel fix for BUG-006
- **Category**: Codegen/GC
- **Severity**: High
- **Reproduction**: Any code path storing heap pointers in Result types, JSON maps, or using Result.ok/err with reference types, followed by GC before retrieval
- **Observed**: Multiple code paths used `ptrtoint` (raw pointer as i64) instead of `gc_ptr_to_handle` (GC handle as i64) when storing heap objects. Also discovered ResultType was missing from `is_heap_type()`, preventing Result variables from being GC-rooted.
- **Expected**: All stored references to GC-managed objects must be handles (i64 indices), never raw pointers
- **Root Cause**: Systematic use of `ptrtoint` for pointer-to-i64 conversion where handle storage was required. Additionally, `codegen/conversions.py:is_heap_type()` did not include `ResultType`, causing Result variables to never be registered as GC shadow stack roots.
- **Fix (2026-02-05)**:
  1. **posix.py** (Group 1): Changed 10 `ptrtoint` storage sites to `gc_promote_to_heap + gc_ptr_to_handle` for Result ok/err values (posix struct, strings, byte lists)
  2. **core.py + expressions.py** (Group 2): Changed `Result.unwrap()` retrieval from `inttoptr` to `gc_handle_deref + bitcast` for reference types
  3. **json_type.py** (Group 3): Changed JSON map creation to use `MAP_FLAG_VALUE_IS_HANDLE`, fixed 5+ storage sites (promote+handle), fixed 3 map retrieval sites (`gc_handle_deref`), fixed list element retrieval sites for reference types, fixed annotation/struct/enum serialization functions
  4. **expressions.py**: Added `Result.ok/err` static constructor interception to convert reference type arguments via `gc_promote_to_heap + gc_ptr_to_handle` instead of raw `ptrtoint`
  5. **conversions.py**: Added `ResultType` to `is_heap_type()` check so Result variables are tracked as GC roots in the shadow stack
  - **Important distinction**: HAMT keys stored via `hamt_collect_keys` are raw `ptrtoint` values (not handles) — `inttoptr` is correct for key retrieval. Only map VALUES in JSON maps are handles.
  - **Remaining work**: Task closure result storage (thread.py) deferred to BUG-099 due to architectural complexity requiring coordinated changes across multiple retrieval sites.
- **Files**: `codegen/posix.py`, `codegen/core.py`, `codegen/expressions.py`, `codegen/json_type.py`, `codegen/conversions.py`
- **Tests**: `tests/test_bug092_handle_storage.py` (11 new tests covering Result, JSON, and task handle storage with GC pressure)
- **Status**: Fixed (2026-02-05) — Partial fix: posix Result, JSON maps, Result.ok/err constructors. Task closure storage deferred to BUG-099.

### BUG-099: gc_compact stale raw pointers after compaction
- **Discovered**: 2026-02-05, during gc_compact implementation
- **Category**: GC
- **Severity**: Critical
- **Reproduction**: `x = [10, 20, 30]; gc_compact(); gc(); print(x.get(0))` → segfault
- **Observed**: Segfault in gc_ptr_to_handle during GC mark phase after compaction
- **Expected**: Objects should be accessible after compaction + GC
- **Hypothesis**: Compaction copies objects via memcpy, but internal raw pointer fields (List root/tail, String owner, Map/Set HAMT root) still point to OLD object locations. When GC mark traces through these stale pointers, it accesses freed memory. Also, compiled code caches raw pointers in stack allocas that become stale after compaction.
- **Files**: coex_gc.py, codegen/expressions.py
- **Fix**: Three-part fix: (1) Added pointer fixup pass in gc_compact_impl that updates internal raw pointer fields for List, String, Map, Set, Array types using gc_ptr_to_handle → gc_handle_deref pipeline. (2) Added gc_segment_get_root function and reload_roots_after_compact helper that re-dereferences handles for all live heap variables after gc_compact() call. (3) Moved gc_compact_deferred_cleanup from before mark phase to after sweep phase in gc_collect, so old memory stays valid during mark traversal.
- **Status**: Fixed (2026-02-05)

### BUG-100: gc_compact prev buffer munmapped by sweep before second compaction
- **Discovered**: 2026-02-05, during gc_compact multiple-rounds testing
- **Category**: GC
- **Severity**: Critical
- **Reproduction**: `x = [1,2,3]; gc_compact(); x = x.append(4); gc_compact()` → segfault in gc_compact_impl
- **Observed**: Segfault at the live_count poison store in gc_compact_impl on second call
- **Expected**: Multiple compaction rounds should work correctly
- **Hypothesis**: The first compaction's compact buffer is saved as gc_compact_prev_buffer. During the gc_collect() call inside the second gc_compact(), the sweep phase processes objects in buffer A. If all objects have been moved elsewhere, buffer A's live_count reaches 0, and sweep munmaps it via gc_dead_tlab_list. Then gc_compact_impl tries to poison the now-freed buffer.
- **Files**: coex_gc.py
- **Fix**: Moved the live_count poisoning from gc_compact_impl to gc_compact wrapper, so it happens BEFORE the gc_collect() call. The sentinel value (0x7FFFFFFFFFFFFFFF) prevents live_count from ever reaching 0 during sweep.
- **Status**: Fixed (2026-02-05)

### BUG-101: gc_compact fixup pass doesn't strip HAMT tag bits from Map/Set root pointers
- **Discovered**: 2026-02-05, during gc_compact stress testing
- **Category**: GC
- **Severity**: Critical
- **Reproduction**: `c = {1: 100}; gc_compact(); print(c.get(1))` → prints 0 instead of 100
- **Observed**: Map.get() returns 0 after compaction. HAMT root pointer becomes NULL.
- **Expected**: Map should return correct values after compaction
- **Hypothesis**: HAMT uses pointer tagging (bit 0 = 1 for leaf, 0 for node). The fixup pass calls `gc_ptr_to_handle(tagged_ptr)` which subtracts HEADER_SIZE from the tagged pointer, reading the wrong memory location for the forward field. This returns handle=0, so the fixup is skipped, leaving a stale pointer.
- **Files**: coex_gc.py (fixup_ptr_field in gc_compact_impl)
- **Fix**: Added `tag_mask` parameter to `fixup_ptr_field`. For Map and Set root fields, strips tag bits (AND with ~mask) before `gc_ptr_to_handle`, then restores tag bits (OR) on the new pointer. Uses `tag_mask=1` for HAMT tagged pointers.
- **Status**: Fixed (2026-02-05)

### BUG-102: gc_compact fixup pass doesn't handle PV_NODE children pointers
- **Discovered**: 2026-02-05, during gc_compact stress testing
- **Category**: GC
- **Severity**: Critical
- **Reproduction**: Build list with 100+ elements (requiring PV tree depth > 1), compact periodically, access first element → wrong value
- **Observed**: `x.get(0)` returns 95 instead of 1 after multiple compactions on a 101-element list
- **Expected**: List elements should be correctly accessible after compaction
- **Hypothesis**: PV_NODE type (TYPE_PV_NODE=10) stores 32 raw i8* children pointers. After compaction moves child PV_NODEs, the parent's children array still has stale pointers. The fixup pass only handled List/String/Map/Set/Array but not PV_NODE.
- **Files**: coex_gc.py (fixup switch in gc_compact_impl)
- **Fix**: Added TYPE_PV_NODE case to the fixup switch. Added `fixup_raw_ptr_field` helper for i8* pointer fields. Iterates all 32 PV_NODE children and fixes each non-null pointer via gc_ptr_to_handle → gc_handle_deref.
- **Status**: Fixed (2026-02-05)

### BUG-015: Non-blocking safepoints require shadow stack changes
- **Discovered**: 2025-01-17, during codebase scan
- **Category**: GC
- **Severity**: Medium
- **Reproduction**: Run concurrent GC with multiple threads doing work
- **Observed**: Threads serialize at safepoints, blocking each other
- **Expected**: Safepoints should be non-blocking for better concurrency
- **Fix**: Removed spin-wait loop in `_implement_gc_safepoint` that blocked mutator threads waiting for GC to complete. Mutators now acknowledge watermark and continue immediately. The triggering mutator also no longer waits for completion — it signals the GC thread and continues. Safety: GC scans slots [0, watermark), mutator writes to [slot_index, ...) where slot_index >= watermark. Disjoint ranges. Birth-marking ensures new allocations survive the current cycle.
- **Files**: `coex_gc.py` (`_implement_gc_safepoint`)
- **Status**: Fixed (2026-02-05)

### BUG-043: GC main mutex for handle allocation
- **Discovered**: 2026-01-18, during lock audit
- **Category**: GC
- **Severity**: Medium
- **Reproduction**: Handle allocation slow path, async GC coordination
- **Observed**: Uses `gc_mutex` for handle pool refill, malloc fallback, and GC signaling
- **Fix**: Multi-phase lock-free replacement:
  1. Handle pool refill: replaced mutex-guarded free list pop with CAS-based free list pop and atomic bump allocation (`atomic_rmw('add')` for batch of 512 handles). Table growth coordinated via CAS flag (`gc_table_growing`).
  2. Malloc fallback: removed mutex wrapper (malloc is thread-safe on all POSIX platforms).
  3. GC signaling: removed `gc_mutex` lock/unlock from `gc_safepoint` do_gc block, `gc_async`, and `gc_compact`. Use bare `pthread_cond_signal` without mutex (POSIX allows this; the GC thread's flag-check loop handles missed signals).
  4. `gc_mutex` retained only for: `gc_thread_main` idle-wait, `gc_wait_for_completion` (explicit `gc()` builtin), `gc_capture_snapshot`, and diagnostic builtins.
- **Files**: `coex_gc.py` (`_implement_gc_handle_pool_refill`, `_implement_gc_alloc`, `_implement_gc_safepoint`, `_implement_gc_async`, `_implement_gc_compact`)
- **Status**: Fixed (2026-02-05)

### BUG-044: GC registry mutex for thread tracking
- **Discovered**: 2026-01-18, during lock audit
- **Category**: GC
- **Severity**: Low
- **Reproduction**: Thread registration/unregistration during GC
- **Observed**: Uses `gc_registry_mutex` for thread registry access from both mutators and GC thread
- **Fix**: Lock-free thread registry with deferred deletion:
  1. `gc_register_thread`: CAS-based prepend to linked list with `atomic_rmw('add')` for thread count.
  2. `gc_unregister_thread`: deferred deletion — marks entry dead (watermark_active = 0xDEAD), CAS-appends to `gc_dead_threads` list, CAS-based handle return to free list. ThreadEntry memory freed by GC thread.
  3. Removed `gc_registry_mutex` from all GC thread operations: `gc_scan_roots`, `gc_sweep_thread_lists`, `gc_collect` watermark reset, `gc_wait_for_watermarks`, `gc_compact_impl`. All add dead-entry skip checks.
  4. GC thread dead-entry cleanup pass at end of `gc_collect`: CAS-steals dead list, walks main registry to unlink dead entries, frees ThreadEntry memory.
  5. `gc_registry_mutex` retained only for diagnostic builtins (`gc_dump_heap`, `gc_validate_handle_storage`).
- **Files**: `coex_gc.py` (`_implement_gc_register_thread`, `_implement_gc_unregister_thread`, `_implement_gc_scan_roots`, `_implement_gc_sweep_thread_lists`, `_implement_gc_collect`, `_implement_gc_wait_for_watermarks`, `_implement_gc_compact_impl`)
- **Status**: Fixed (2026-02-05)

### BUG-104: gc_alloc_count double-reset delays second GC trigger
- **Discovered**: 2026-02-06, during Galaxian GC watermark investigation
- **Category**: GC
- **Severity**: Critical
- **Reproduction**: Heavy allocation loop without explicit gc() calls. GC triggers once at 100K threshold, then gc_sweep's non-atomic store(0) wipes concurrent allocations, delaying next trigger.
- **Observed**: Only 1 GC cycle triggers despite ~600K+ allocations; crash occurs before second trigger
- **Expected**: GC should trigger approximately every 100K allocations
- **Fix**: Removed redundant store(0) in gc_sweep; safepoint xchg is sole reset mechanism.
- **Files**: `coex_gc.py` (gc_sweep)
- **Status**: Fixed (2026-02-06)

### BUG-105: TLAB live_count race causes premature munmap
- **Discovered**: 2026-02-06, during Galaxian GC watermark investigation
- **Category**: GC
- **Severity**: Critical
- **Reproduction**: Heavy concurrent allocation. gc_tlab_alloc CAS bumps cursor before gc_alloc increments live_count, creating a window where sweep decrements to 0 and adds TLAB to dead list.
- **Observed**: SIGSEGV when accessing objects in munmap'd TLAB
- **Expected**: TLABs with live allocations should not be freed
- **Fix**: Added atomic live_count re-check with acquire ordering before munmap; skip munmap if live_count > 0.
- **Files**: `coex_gc.py` (TLAB free loop in gc_sweep_thread_lists)
- **Status**: Fixed (2026-02-06)

### BUG-106: gc_segment_pop watermark enforcement gap
- **Discovered**: 2026-02-06, during Galaxian GC watermark investigation
- **Category**: GC
- **Severity**: High
- **Reproduction**: Deep recursion with allocation pressure. When gc_phase != 0 but watermark_active == 0 (thread hasn't hit safepoint yet), gc_segment_pop allows unrestricted slot_index lowering.
- **Observed**: GC scans slots containing stale retired handles, causing crash
- **Expected**: gc_segment_pop should acknowledge watermark when GC is active
- **Fix**: Added watermark acknowledgment in gc_segment_pop when gc_phase != 0 and watermark_active == 0: captures current slot_index as watermark, sets watermark_active = 1, then falls through to watermark check.
- **Files**: `coex_gc.py` (gc_segment_pop)
- **Status**: Fixed (2026-02-06)

### BUG-107: gc_mark_object validity threshold too low for retired handle detection
- **Discovered**: 2026-02-06, during stress test crash investigation
- **Category**: GC
- **Severity**: High
- **Reproduction**: Stress test with 600K+ allocations and deep recursion. Retired handle table entries contain free-list link integers (handle indices up to ~200K) that pass the 0x10000 (64KB) validity check.
- **Observed**: gc_mark_object dereferences retired handle, gets free-list index as pointer (~0x2f8e1), crashes with EXC_BAD_ACCESS
- **Expected**: Retired handle entries (small integers) should be detected as invalid pointers
- **Fix**: Raised validity threshold from 0x10000 (64KB) to 0x400000 (4MB). On macOS/arm64, valid heap pointers are well above this.
- **Files**: `coex_gc.py` (gc_mark_object)
- **Status**: Fixed (2026-02-06)
- **Note**: Root cause may be stale handles in shadow stack slots surviving across function calls. The threshold fix is a safety net.

---

### BUG-108: String concatenation data lost after gc_compact()
- **Discovered**: 2026-02-08, during GC concurrent verification testing
- **Category**: GC/Codegen
- **Severity**: High
- **Reproduction**: `c = a + " " + b; gc(); gc_compact(); print(c)` — prints empty string
- **Observed**: After gc() or gc_compact(), concatenated string `c` has correct `.len()` (11) but `print(c)` outputs empty. String literals `a` and `b` print correctly.
- **Expected**: `print(c)` should output "hello world"
- **Root Cause**: Type inference missing `BinaryExpr` (`codegen/generics.py:infer_type_from_expr`): `a + " " + b` is a `BinaryExpr` but the function had no case for it, defaulting to `PrimitiveType("int")`. This caused `collect_heap_vars_from_body()` to not recognize the variable as heap-allocated, so no shadow stack root was registered. The STRING and STRING_DATA objects were swept as garbage.
- **Fix**: Added `BinaryExpr`, `UnaryExpr`, `TernaryExpr` cases to `infer_type_from_expr`. Also removed STRING from compact fixup switch (owner field stores a handle since arena removal, not a raw pointer).
- **Files**: `codegen/generics.py`, `coex_gc.py`
- **Status**: Fixed (2026-02-08)

### BUG-110: list_set and list_append stale-pointer-across-allocation causes segfault
- **Discovered**: 2026-02-09, during Galaxian firing crash investigation
- **Category**: Codegen
- **Severity**: Critical
- **Reproduction**: Run Galaxian example, begin firing at enemies. Game segfaults within 10 seconds. Also reproduced by `test_list_set_with_gc_pressure` stress test.
- **Observed**: Segfault when `enemy_alive.set(i, 0)` is called under GC pressure. Game runs indefinitely without firing (no list mutations).
- **Expected**: list.set() should work correctly regardless of GC timing.
- **Root Cause**: `_implement_list_set` and `_implement_list_append` in `codegen/list.py` obtain raw pointers via `gc_handle_deref()` early in the function, then allocate new objects via `list_new` or `alloc_arena_or_gc`. These allocations can trigger GC + compaction, which moves objects to new locations. The previously-obtained raw pointers become stale and the subsequent `memcpy` reads from freed/moved memory.
- **Fix**: Re-derive all raw pointers from their handles after every allocation. 12 instances fixed across both functions: tail case, tree case tail copy, root copy, depth=1 leaf copy, depth>1 loop node copy, depth>1 leaf copy (×2 for set and append).
- **Files**: codegen/list.py
- **Status**: Fixed (2026-02-09)

### BUG-111: Local variable allocas hold stale raw pointers after GC compaction — Galaxian crash
- **Discovered**: 2026-02-09, during continued Galaxian crash investigation after BUG-110 fix
- **Category**: Codegen/GC
- **Severity**: Critical
- **Reproduction**: Any program that reads a reference-type variable (List, String, Map, Set, Array, Json) after GC compaction has moved the object AND the old TLAB has been munmapped. Specifically reproduces the Galaxian firing crash: the rendering loop reads `enemy_alive` 38 times with heavy JSON/string allocations between reads, but never reassigns it. Two GC cycles during a single frame cause the TLAB to be munmapped.
- **Observed**: Segfault reading reference-type variables after GC compaction. 4 targeted tests all crash: list read after GC cycles, string read after GC cycles, interleaved reads with allocations, set-then-read-after-GC.
- **Expected**: Variables should always return valid pointers regardless of GC compaction timing.
- **Root Cause**: `generate_identifier` in `codegen/expressions.py` loads raw pointers from variable allocas (`builder.load(cg.locals[name])`). After GC compaction moves an object and the old TLAB is munmapped (deferred cleanup in next cycle), the raw pointer in the alloca points to unmapped memory. The shadow stack has the correct handle, but it was never consulted during variable reads.
- **Fix**: Modified `generate_identifier` to re-derive reference-type pointers from the shadow stack handle on every variable read. For variables with shadow stack slots (`gc_root_indices`), the fix reads the handle via `gc_segment_get_root`, dereferences it via `gc_handle_deref` to get the current pointer, and returns the fresh pointer. This adds ~3 instructions per reference-type variable access but ensures correctness after compaction.
- **Files**: codegen/expressions.py (generate_identifier, lines 167-196)
- **Tests**: tests/test_stale_var_pointer.py (4 new tests)
- **Status**: Fixed (2026-02-09). Workaround (per-read shadow stack re-derive) properly resolved by handle-storing allocas refactor (2026-02-11): allocas now store i64 handles instead of raw pointers, so variable reads naturally produce fresh pointers via `_load_var_ptr` → `gc_handle_deref`. The 30-line BUG-111 hack in `generate_identifier` was replaced with a 3-line `_load_var_ptr` call.

---

### BUG-112: Handle table load/store missing memory ordering — ARM64 race in gc_handle_deref/gc_handle_store
- **Discovered**: 2026-02-09, during Galaxian crash investigation
- **Category**: GC
- **Severity**: Critical
- **Reproduction**: Any program with concurrent GC compaction and mutator handle dereferences on Apple Silicon (ARM64). Crash timing is highly variable (3-30 seconds) — classic store buffer reordering race.
- **Observed**: `gc_handle_deref` used plain load (no acquire) and `gc_handle_store` used plain store (no release) on handle table slots. On ARM64 weak memory model, compaction's memcpy of object data to a new location is NOT guaranteed visible to the mutator when the handle table update (pointing to new location) IS visible. Mutator reads zeroed mmap pages at new location → null pointer dereference → SIGSEGV.
- **Expected**: Handle table slot reads/writes must form release-acquire pairs so that object data is guaranteed visible when a new pointer is published.
- **Root Cause**: Compaction does `memcpy(new_loc, old_data)` then `gc_handle_store(handle, new_ptr)`. Without `release` on the store, ARM64 can reorder store buffer so handle table update is visible before memcpy data. Mutator does `ptr = gc_handle_deref(handle)`. Without `acquire` on the load, subsequent data reads see uninitialized (zeroed) mmap pages. Result: null dereference in struct field access → SIGSEGV.
- **Fix**: Changed `gc_handle_store` to use `store_atomic(..., ordering='release', align=8)`. Changed `gc_handle_deref` to use `load_atomic(..., ordering='acquire', align=8)`. Both use bitcast to `i64*` for llvmlite atomic operation compatibility.
- **Files**: `coex_gc.py` (`_implement_gc_handle_deref`, `_implement_gc_handle_store`)
- **Note**: On x86-64 (TSO memory model), plain loads/stores provide implicit acquire/release, masking this bug. Only manifests on weak-memory architectures (ARM64/Apple Silicon).
- **Status**: Fixed (2026-02-09)

---

### BUG-109: HAMT nodes lack type_id — Phase 3b pointer fixup skips them, causing stale internal pointers after compaction
- **Discovered**: 2026-02-09, during TLAB memory leak fix (attempting to re-enable TLAB freeing in Phase 3)
- **Category**: GC
- **Severity**: High
- **Reproduction**: Any program using maps or sets under GC compaction pressure. Becomes a crash when TLAB freeing is re-enabled.
- **Observed**: HAMTNode (type_id=0) and HAMT children buffers (type_id=0) were invisible to Phase 3b fixup. After compaction, internal raw pointers were stale.
- **Root Cause**: Three interrelated issues:
  1. HAMT objects allocated with type_id=0, making them invisible to Phase 3b fixup switch
  2. Phase 3b only fixed objects IN the compact buffer (range check), but newborn objects in TLABs also contain raw pointers to the prev compact buffer
  3. Phase 4 freed prev_buffer immediately, but mutators could allocate HAMT nodes with stale pointers DURING Phase 3b (race condition)
- **Fix (3 parts)**:
  1. Defined TYPE_HAMT_NODE=23, TYPE_HAMT_CHILDREN=24, TYPE_HAMT_LEAF=25, TYPE_HAMT_LEAF_KPTR=26 in coex_gc.py. Updated hamt.py to use them. Added Phase 3b fixup cases for each type.
  2. Removed the in_buffer range check from Phase 3b — now processes ALL live objects, not just those in the compact buffer.
  3. Two-generation buffer: prev_buffer kept alive for one extra cycle (gc_compact_prev_prev_buffer). Phase 4 frees prev_prev instead of prev. Next cycle's Phase 3b fixes stale pointers before the buffer is freed.
- **Files**: `coex_gc.py`, `codegen/hamt.py`, `codegen/statements.py`
- **Status**: Fixed (2026-02-09)

---

### BUG-113: In-place mutation optimization uses stale raw pointer after GC compaction
- **Discovered**: 2026-02-09, during BUG-109 HAMT compaction testing
- **Category**: Codegen/GC
- **Severity**: Critical
- **Reproduction**: `m = m.set(key, val)` after GC compaction (2 gc() cycles with garbage between them)
- **Observed**: `try_generate_inplace_update` calls `map_put_inplace` with a raw pointer loaded from the variable's alloca. After compaction, this is stale.
- **Root Cause**: In-place optimization mutates through raw pointers, but compaction changes the canonical object location. Writes go to old location; reads via handle deref see unmodified copy at new location.
- **Fix**: Initially disabled in-place optimization when GC is active (`cg.gc is not None` → return False). The normal reassignment path is correct and performance difference is negligible.
- **Files**: `codegen/statements.py` (try_generate_inplace_update)
- **Status**: Fixed (2026-02-09). In-place optimization re-enabled by handle-storing allocas refactor (2026-02-11): `_generate_inplace_call` now loads the wrapper pointer via `_load_var_handle` → `gc_handle_deref`, getting a fresh pointer that is valid after compaction. The GC guard (`if cg.gc is not None: return False`) was removed.

---

### BUG-114: Intermittent data corruption in list.set under GC pressure
- **Discovered**: 2026-02-09, during investigation of pre-existing test failures
- **Category**: GC
- **Severity**: High
- **Reproduction**: Run test_list_set_gc_stress.py::test_list_set_with_gc_pressure repeatedly. Fails ~60% of runs.
- **Observed**: `alive.get(i) != 1` after setting all 38 elements to 1. Data corruption at round 30-40.
- **Expected**: All elements should read as 1 after resetting them.
- **Root Cause**: Race between async GC Phase 3b fixup (PV_NODE raw pointer patching) and mutator reads. After compaction copies objects to new buffer and updates handle table, the mutator sees new locations via gc_handle_deref but Phase 3b hasn't yet fixed internal PV_NODE raw pointers. Mutator reads stale internal pointers → accesses wrong PV_NODE data → silent data corruption.
- **Fix**: Converted PV_NODE children and Array data handle from raw pointers to GC handles (i64). This eliminated the need for Phase 3b entirely — handles are stable across compaction (handle table updated by copy phase). Phase 3b removed.
- **Files**: `codegen/core.py`, `codegen/list.py`, `codegen/array.py`, `codegen/conversions.py`, `codegen/expressions.py`, `coex_gc.py`
- **Status**: Fixed (2026-02-10)

### BUG-116: Mixed-type map literal to JSON conversion uses wrong value types
- **Discovered**: 2026-02-10, during BUG-115 test writing
- **Category**: Codegen
- **Severity**: High
- **Reproduction**: `data: json := {"name": "test", "value": 42}; print(data.stringify())` — segfault or corrupted output
- **Observed**: Segfault or value corruption when converting map literals with mixed value types to JSON. For `{"name": "test", "value": 42}`, the integer 42 is treated as a string GC handle → `gc_handle_deref(42)` reads garbage → crash. For `{"a": 1, "b": "y"}`, string "y" is treated as an integer → corrupted value.
- **Expected**: Each value should be converted using its own compile-time type
- **Root Cause**: `convert_map_to_json_object` in `codegen/json_type.py` infers a SINGLE `value_type` from `_infer_type_from_expr` (based on the first map entry) and applies it to ALL values. For mixed-type map literals, this misapplies the wrong type to subsequent values. The runtime `map_values()` API cannot help because HAMT stores raw i64 without per-value type information — all values get the same TV type_id regardless of actual type.
- **Fix**: Added `_build_json_from_map_expr` method that intercepts `MapExpr` in `convert_to_json` and builds JSON directly from expression entries, converting each value individually with its correct compile-time type. This bypasses the broken single-type loop in `convert_map_to_json_object`.
- **Files**: `codegen/json_type.py`
- **Status**: Fixed (2026-02-10)

### BUG-118: Hardcoded macOS mmap flags in TLAB allocation break Linux
- **Discovered**: 2026-02-10, during Linux CI investigation of `test_list_set_38_elements_tail_and_tree`
- **Category**: GC
- **Severity**: Critical
- **Reproduction**: Run any GC stress test on Linux (e.g., `test_list_set_38_elements_tail_and_tree`)
- **Observed**: `malloc(): unaligned fastbin chunk detected` (glibc heap corruption). All tests pass on macOS.
- **Expected**: TLAB allocation via mmap should work on both macOS and Linux
- **Root Cause**: `gc_tlab_init` (line 6074) and `gc_tlab_refill` (line 6314) hardcoded mmap flags to `0x1002` (macOS: MAP_PRIVATE | MAP_ANON). On Linux, `0x1002` = MAP_PRIVATE (0x0002) | MAP_EXECUTABLE (0x1000, deprecated). Missing MAP_ANONYMOUS (0x0020) causes mmap with fd=-1 to fail (MAP_FAILED). ALL TLAB allocations fail, forcing every GC object through the malloc fallback path. With all objects malloc'd instead of TLAB-allocated, GC compaction/sweep interactions with malloc'd memory cause heap corruption detected by glibc's fastbin checks. Two other mmap callsites (`gc_segment_alloc` line 5474 and `gc_compact_impl` line 9930) already had correct platform-specific flags.
- **Fix**: Added `sys.platform` check to both `gc_tlab_init` and `gc_tlab_refill`, matching the existing pattern in `gc_segment_alloc` and `gc_compact_impl`: macOS uses 0x1002, Linux uses 0x0022.
- **Files**: `coex_gc.py` (lines 6070-6077, 6311-6325)
- **Status**: Fixed (2026-02-10)

### BUG-119: Stale pointer in string_new and string_from_literal after GC compaction
- **Discovered**: 2026-02-11, during Linux CI investigation
- **Category**: GC
- **Severity**: Critical
- **Reproduction**: Run `test_gc_no_explicit_gc_heavy_alloc` on Linux (150K string allocations with auto-triggered GC)
- **Observed**: Silent crash (segfault). `string_new` passes stale `data` pointer to memcpy after internal allocations trigger GC+compaction that munmaps the TLAB containing data. `string_from_literal` has same pattern: `string_ptr` stale after data buffer allocation.
- **Root Cause**: `string_new` takes a raw `data` pointer (i8*), then does two GC allocations (string struct + data buffer). Either allocation can trigger GC+compaction, moving data's TLAB. The raw pointer becomes invalid. Additionally, `string_new` can be called with null data (empty string), so gc_ptr_to_handle needs a null guard.
- **Fix**: (1) string_new: branch on null check, save data handle via gc_ptr_to_handle for non-null, phi merge, re-derive after allocations. (2) string_from_literal: save string struct handle, re-derive after data buffer allocation. (3) string_setrange: re-derive orig_data and source_data handles after allocation.
- **Files**: `codegen/strings.py` (string_new, string_from_literal, string_setrange)
- **Status**: Fixed (2026-02-11)

### BUG-033: Scheduler initialization uses mutex
- **Discovered**: 2026-01-18, during lock audit
- **Category**: Runtime
- **Severity**: Low
- **Reproduction**: Scheduler lazy initialization via `coex_scheduler_ensure_init()`
- **Observed**: Uses `scheduler_init_mutex` (pthread_mutex) at `coex_scheduler.c:26`
- **Fix**: Replaced double-checked locking with `pthread_once`. Extracted init body into `scheduler_do_init()`, replaced mutex with `pthread_once_t scheduler_init_once`. Fast path: acquire load of `scheduler_initialized` returns immediately.
- **Files**: `runtime/coex_scheduler.c`
- **Status**: Fixed (2026-02-11)

### BUG-035: Global work queue uses mutex
- **Discovered**: 2026-01-18, during lock audit
- **Category**: Runtime
- **Severity**: Medium
- **Reproduction**: Tasks submitted from main thread use global queue
- **Observed**: Uses `global_queue_mutex` at `coex_scheduler.c:39`
- **Fix**: Replaced global Chase-Lev deque + mutex with lock-free Treiber stack. Added `next` field to `SchedulerTask` struct. `global_stack_push()` uses CAS loop; `global_stack_pop()` uses CAS loop. Updated all 6 call sites: spawn_and_wait, ready_task, spawn_async, first_spawn_task, most_spawn_task, try_steal.
- **Files**: `runtime/coex_scheduler.h`, `runtime/coex_scheduler.c`
- **Status**: Fixed (2026-02-11)

### BUG-036: Deque resize uses lock
- **Discovered**: 2026-01-18, during lock audit
- **Category**: Runtime
- **Severity**: Low
- **Reproduction**: Chase-Lev deque grows when full
- **Observed**: Uses `resize_lock` in Deque struct at `coex_scheduler.h:80`
- **Fix**: Removed `resize_lock` from Deque struct and all init/destroy/usage. Only the owner thread calls `deque_push_bottom`, so no lock needed. Stealers load buffer pointer atomically; old buffers are intentionally leaked (safe for concurrent stealers). Post-grow buffer reload uses `memory_order_acquire`.
- **Files**: `runtime/coex_scheduler.h`, `runtime/coex_scheduler.c`
- **Status**: Fixed (2026-02-11)

### BUG-042: Channel synchronization uses mutex
- **Discovered**: 2026-01-18, during lock audit
- **Category**: Runtime
- **Severity**: Medium
- **Reproduction**: Channels used from func/thread context
- **Observed**: Uses `mutex` + `cond` in ChannelSync for all operations including send and try_receive
- **Fix**: Replaced ring buffer + mutex with Vyukov MPSC queue (lock-free FIFO) for values and Treiber stack for task waiters. Send is fully lock-free: mpsc_push + Treiber pop for waiter wakeup. Try_receive is fully lock-free: mpsc_try_pop. Blocking receive uses condvar only in slow path (when queue empty). Mutex retained solely for POSIX condvar API compliance.
- **Files**: `runtime/coex_channel.h`, `runtime/coex_channel.c`
- **Status**: Fixed (2026-02-11)

---

### BUG-120: C runtime coex_string.c stores raw pointers in owner_handle instead of GC handles
- **Discovered**: 2026-02-11, during Galaxian crash debugging
- **Category**: Runtime
- **Severity**: Critical
- **Reproduction**: Compile galaxian.coex and run — crashes immediately at frame 2 in gc_handle_deref
- **Observed**: SIGSEGV in coex_gc_handle_deref called from string_data. Register x0 contains a raw pointer (0x10b030338) instead of a handle index. Crash occurs when ui.render returns a string created by coex_string_from_cstring_take, which stored a raw pointer in owner_handle. Codegen's coex_string_data calls gc_handle_deref on owner_handle, expecting a GC handle.
- **Root cause**: runtime/coex_string.c was written when arena allocation existed and owner_handle stored raw pointers via ptrtoint. After arena removal (Feb 2026), all codegen switched to treating owner_handle as a GC handle, but the C runtime was never updated.
- **Fix**: (1) Added extern declarations for coex_gc_ptr_to_handle and coex_gc_handle_deref to coex_string.c. (2) string_create_internal now stores gc_ptr_to_handle(data_buf) in owner_handle and includes stale-pointer-across-allocation protection (saves string handle before second alloc, re-derives after). (3) coex_string_get_data now uses gc_handle_deref(owner_handle) instead of raw cast.
- **Files**: `runtime/coex_string.c`, `runtime/coex_string.h`
- **Status**: Fixed (2026-02-11)

---

### BUG-122: Dead task thread TLABs never freed — memory leak
- **Discovered**: 2026-02-11, during investigation of ~10MB/minute memory leak in Galaxian
- **Category**: GC
- **Severity**: Critical
- **Reproduction**: Run Galaxian or any program that spawns many short-lived task threads. Memory grows linearly over time as dead thread TLABs (256KB each) and alloc_nodes are never reclaimed.
- **Observed**: Three interrelated bugs causing permanent memory leak:
  1. **Registry corruption**: `gc_unregister_thread` reused field 11 (registry `next` pointer) for dead-list linkage via `gc_dead_threads`. This severed the registry linked list, orphaning threads registered after the dead thread — their roots were never scanned and alloc_lists were never swept.
  2. **Sweep skip**: `gc_sweep_thread_lists` skipped dead threads entirely (`watermark_active == 0xDEAD`). Dead threads' alloc_nodes were never processed, handles were never retired, TLAB live_counts never reached 0, TLABs were never munmapped.
  3. **Premature ThreadEntry free**: `gc_collect` dead cleanup freed ThreadEntry even when its alloc_list still contained unswept objects.
- **Expected**: After task threads complete and their objects become unreachable, GC should sweep dead thread allocations, retire handles, and eventually munmap TLABs.
- **Fix**: Three coordinated changes in `coex_gc.py`:
  1. Changed dead-list linkage from field 11 (registry next) to field 15 (reserved) in `_implement_gc_unregister_thread` — preserves registry linked list integrity.
  2. Removed dead-thread skip in `_implement_gc_sweep_thread_lists` — dead threads' alloc_lists are now swept normally, retiring handles and decrementing TLAB live_counts.
  3. Added alloc_list emptiness check in `_implement_gc_collect` dead cleanup — if alloc_list not empty, CAS-append back to `gc_dead_threads` for next cycle; if empty, proceed to unlink from registry and free ThreadEntry.
- **Tests**: `tests/test_dead_thread_tlab_leak.py` — 8 tests covering dead thread sweep (3), TLAB reclamation (2), stress (1), and registry integrity (2)
- **Files**: `coex_gc.py` (`_implement_gc_unregister_thread`, `_implement_gc_sweep_thread_lists`, `_implement_gc_collect`)
- **Status**: Fixed (2026-02-11)
