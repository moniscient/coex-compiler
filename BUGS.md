# Coex Bug Tracker

## Bug Reporting Protocol

**Mandatory**: When encountering any unexpected behavior, test failure, or anomaly during development—even if worked around or tangential to the current task—immediately append a bug report here before continuing. Never assume a bug will be "remembered" for later.

### Workflow
1. **New bugs**: Append to the bottom of this file, above the "Next valid BUG ID" line. Use the ID shown there, then increment it.
2. **Resolved bugs**: When a bug is fixed, update its Status to "Fixed (date)" and move the entire entry to `BUGS-RESOLVED.md`. Do not reuse its BUG ID number.
3. **Next BUG ID**: The last line of this file always shows the next valid BUG ID. Update it after each insertion.

### Bug Categories
- **Parser**: Grammar issues, ANTLR parse failures
- **Semantic**: Type checking, binding resolution, trait matching
- **Codegen**: LLVM IR generation, type registry issues
- **Runtime**: Task scheduler, channel operations, coroutine behavior
- **GC**: Garbage collector, handle table, shadow stack issues
- **Stdlib**: Standard library functions, posix module

### Severity Levels
- **Critical**: Crashes, data corruption, security issues
- **High**: Correctness bugs, wrong output
- **Medium**: Performance issues, edge cases
- **Low**: Minor issues, cosmetic problems

---

## Open Bugs

<!-- Template for new bugs:

### BUG-XXX: One-line summary
- **Discovered**: YYYY-MM-DD, during [context]
- **Category**: [Parser|Semantic|Codegen|Runtime|GC|Stdlib]
- **Severity**: [Critical|High|Medium|Low]
- **Reproduction**: Steps to reproduce
- **Observed**: What actually happens
- **Expected**: What should happen
- **Hypothesis**: Theory about the cause
- **Files**: Likely involved files
- **Status**: Open

-->

### BUG-015: Non-blocking safepoints require shadow stack changes
- **Discovered**: 2025-01-17, during codebase scan
- **Category**: GC
- **Severity**: Medium
- **Reproduction**: Run concurrent GC with multiple threads doing work
- **Observed**: Threads serialize at safepoints, blocking each other
- **Expected**: Safepoints should be non-blocking for better concurrency
- **Hypothesis**: Current shadow stack design requires stop-the-world synchronization
- **Files**: `coex_gc.py`, `implementation_prompts/phase1_nonblocking_safepoints.md`
- **Status**: Open (enhancement)

### BUG-023: llvmlite thread_local attribute silently ignored
- **Discovered**: 2025-01-17, during codebase scan
- **Category**: Codegen
- **Severity**: High
- **Reproduction**: Set `variable.thread_local = 'localdynamic'` and inspect generated IR
- **Observed**: IR shows plain `global`, not `thread_local global`
- **Expected**: Variable should be thread-local in generated code
- **Hypothesis**: llvmlite library bug - attribute setter has no effect
- **Files**: `coex_gc.py` (TLS variables), all code using thread-local state
- **Status**: Open (workaround in place: use pthread TLS via ThreadEntry struct)

### BUG-033: Scheduler initialization uses mutex
- **Discovered**: 2026-01-18, during lock audit
- **Category**: Runtime
- **Severity**: Low (review for necessity)
- **Reproduction**: Scheduler lazy initialization via `coex_scheduler_ensure_init()`
- **Observed**: Uses `scheduler_init_mutex` (pthread_mutex) at `coex_scheduler.c:26`
- **Expected**: TBD - review if lock-free initialization is feasible
- **Hypothesis**: Double-checked locking pattern; mutex only held briefly during init
- **Files**: `runtime/coex_scheduler.c:26, 479-509`
- **Status**: Open (under review)

### BUG-035: Global work queue uses mutex
- **Discovered**: 2026-01-18, during lock audit
- **Category**: Runtime
- **Severity**: Medium (review for necessity)
- **Reproduction**: Tasks submitted from main thread use global queue
- **Observed**: Uses `global_queue_mutex` at `coex_scheduler.c:39`
- **Expected**: TBD - review if lock-free queue is feasible
- **Hypothesis**: Protects global deque during push/steal; could use lock-free MPSC
- **Files**: `runtime/coex_scheduler.c:39, 209-211, 570-572, 607-609, 638-640, 723-725, 795-797`
- **Status**: Open (under review)

### BUG-036: Deque resize uses lock
- **Discovered**: 2026-01-18, during lock audit
- **Category**: Runtime
- **Severity**: Low (review for necessity)
- **Reproduction**: Chase-Lev deque grows when full
- **Observed**: Uses `resize_lock` in Deque struct at `coex_scheduler.h:80`
- **Expected**: TBD - review if resize can be lock-free
- **Hypothesis**: Required for safe buffer reallocation while stealers active
- **Files**: `runtime/coex_scheduler.h:80`, `runtime/coex_scheduler.c:70-77, 108-111`
- **Status**: Open (under review)

### BUG-042: Channel synchronization uses mutex
- **Discovered**: 2026-01-18, during lock audit
- **Category**: Runtime
- **Severity**: Medium (review for necessity)
- **Reproduction**: Channels used from func/thread context
- **Observed**: Uses `mutex` + `cond` in ChannelSync at `coex_channel.h:63-64`
- **Expected**: TBD - review if lock-free channel is feasible
- **Hypothesis**: Required for blocking receive; could use lock-free for send
- **Files**: `runtime/coex_channel.h:63-64`, `runtime/coex_channel.c:172-174, 184-216, 222-265, 272-274`
- **Status**: Open (under review)

### BUG-043: GC main mutex for handle allocation
- **Discovered**: 2026-01-18, during lock audit
- **Category**: GC
- **Severity**: Medium (review for necessity)
- **Reproduction**: Handle allocation slow path, async GC coordination
- **Observed**: Uses `gc_mutex` at `coex_gc.py:568`
- **Expected**: TBD - review scope of mutex protection
- **Hypothesis**: Protects handle table growth, free list refill, GC coordination
- **Files**: `coex_gc.py:568, 1426-1428, 1956-1985, 2258-2262, 3925-3967, 4085-4212, 7792-7855`
- **Status**: Open (under review)

### BUG-044: GC registry mutex for thread tracking
- **Discovered**: 2026-01-18, during lock audit
- **Category**: GC
- **Severity**: Low (review for necessity)
- **Reproduction**: Thread registration/unregistration during GC
- **Observed**: Uses `gc_registry_mutex` at `coex_gc.py:696-699`
- **Expected**: TBD - protects thread registry during iteration
- **Hypothesis**: Required for safe iteration while threads register/unregister
- **Files**: `coex_gc.py:696-699, 1514-1519, 1747-1765, 1817-1888, 3032-3198, 3326-3372, 5578-5930, 6376-6480`
- **Status**: Open (under review)

### BUG-081: Galaxian crash - raw pointers stored where GC handles expected
- **Discovered**: 2026-01-31, during Galaxian stress testing
- **Category**: GC/Codegen
- **Severity**: Critical
- **Reproduction**: Run Galaxian for 2000+ frames (previously crashed at ~1000 frames)
- **Observed**: Segfault in `coex_gc_handle_deref` when GC tries to mark TaggedValues containing raw pointers
- **Expected**: Should run indefinitely without crash
- **Root Cause**: Multiple code paths store raw pointers (via `ptrtoint`) where the GC expects handles

**PARTIAL FIX APPLIED (2026-01-31)** - Game now runs 3x longer (2000 frames vs 1000):

1. **Array<ref_type> subscript access** (`codegen/expressions.py:1023-1051`)
   - Arrays of reference types (string, List, etc.) store handles, not raw pointers
   - Retrieval code was loading handle as if it were a pointer
   - **Fix**: Load handle (i64), then call `gc_handle_deref` to get pointer
   - Also fixed 2D array indexing at lines 1000-1035

2. **Previous fixes in this session**:
   - `codegen/json_type.py:1867-1873, 1961-1971` - json_stringify storing raw pointers in temp string lists
   - `codegen/strings.py:743-751, 840-848` - string_join_list reading handles as pointers
   - `codegen/expressions.py:562-566` - `_to_i64_value` fallback for pointer types

**REMAINING ISSUE**: Game still crashes at ~2000 frames. Additional raw pointer storage likely exists.

**Investigation Strategy** (for future session):
- Focus on **low-frequency/rare code paths** (input handling, event callbacks)
- Search for `ptrtoint` patterns that store into TaggedValues or collections
- Key files with `ptrtoint` usage to audit:
  - `codegen/json_type.py` - lines 339, 870, 891, 1463, 2705, 2999, 3108, 3127, 3142, 3186, 3193, 3206, 3568
  - `codegen/posix.py` - Result<T,E> returns using ptrtoint (lines 202, 210, 273, 281, 340, 388, 462, 471, 533, 591)
  - `codegen/loops.py` - parallel task results (lines 2187, 2493, 2790, 2807)
  - `codegen/core.py` - field initialization (lines 2864, 2917)

**Handle Storage Invariant** (from CLAUDE.md):
- All stored references to GC-managed objects must be **handles** (i64 indices), never raw pointers
- Pattern: `gc_ptr_to_handle(ptr)` to store, `gc_handle_deref(handle)` to retrieve
- Type IDs >= 64 (TYPE_HEAP_BASE) indicate heap references needing GC tracing

- **Files**: `codegen/expressions.py`, `codegen/json_type.py`, `codegen/strings.py`, `codegen/loops.py`, `codegen/posix.py`
- **Status**: Partially fixed (2026-01-31) - 3x improvement, more work needed

---

## Other Bugs (lower priority, not actively tracked above)

### BUG-050: UI library shutdown segfault
- **Discovered**: 2026-01-21, during UI performance test
- **Category**: Runtime
- **Severity**: Low
- **Reproduction**: Run any UI test program (e.g., `./test_ui_performance`) and let it complete
- **Observed**: Segmentation fault (signal 11) occurs after test prints success message during `coex_ui_shutdown()`
- **Expected**: Clean shutdown without crash
- **Hypothesis**: Cleanup ordering issue - ImGui context may be destroyed before Metal renderer releases resources that depend on it, or macOS Cocoa objects are being released in wrong order
- **Files**: `runtime/coex_ui.c:coex_ui_shutdown()`, `runtime/coex_ui_imgui.c:coex_imgui_shutdown()`, `runtime/coex_ui_metal.m:coex_ui_metal_shutdown()`, `runtime/coex_ui_shell_macos.m:coex_ui_shell_shutdown()`
- **Status**: Open
- **Note**: Does not affect functionality - crash occurs after all test work completes successfully. Performance test achieves 103 FPS with 100 widgets before the shutdown crash.

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
- **Hypothesis**: The grammar only allows variable declarations inside function bodies. Top-level statements are restricted to function/type definitions and imports.
- **Files**: `Coex.g4` (grammar rules for top-level declarations), `ast_builder.py`
- **Workaround**: Define constants as local variables in each function that needs them, or use literal values directly
- **Status**: Open

### BUG-075: Deep nested list type inference fails after ~3 levels in loops
- **Discovered**: 2026-01-29, during Phase 7 list handle conversion implementation
- **Category**: Codegen
- **Severity**: Medium
- **Reproduction**:
```coex
func main() -> int
    # Build 20-level nested list in a loop
    level = [42]
    for i in 0..19
        level = [level]
    ~

    # Traverse and verify
    current = level
    for i in 0..19
        current = current.get(0)
    ~

    print(current.get(0))  # Should print 42
    return 0
~
```
- **Observed**: Prints empty line instead of `42`. The traversal completes without crashing but the final value is null/missing.
- **Expected**: Should correctly traverse 20 levels of nesting and print `42`
- **Root Cause**: Type inference for deeply nested lists in loops doesn't fully propagate. When `level = [level]` is executed repeatedly:
  1. First iteration: `level` changes from `List<int>` to `List<List<int>>`
  2. Second iteration: should become `List<List<List<int>>>`, etc.

  The type tracking via `var_coex_types` is updated per-iteration, but the type inference `_infer_type_from_expr` for `[level]` may not correctly identify the current depth of nesting. After ~3 levels, the type becomes too deeply nested for the current type inference to handle, causing `List.get()` to return incorrect element types or null handles.

  Additionally, the handle-based storage for reference types depends on correct type inference to determine when to store handles vs raw values. If the type inference fails at deep nesting levels, the read/write mismatch causes data loss.
- **Files**:
  - `codegen/statements.py` (type tracking in reassignment)
  - `codegen/generics.py` (`_infer_type_from_expr` for ListExpr)
  - `codegen/expressions.py` (List.get handle dereferencing)
- **Status**: Open
- **Workaround**: Use explicit intermediate variables at each nesting level instead of reassigning the same variable in a loop. Works correctly up to ~3-4 levels of nesting.
- **Note**: This is an edge case. Normal usage patterns (2-3 levels of nesting) work correctly after the Phase 7 handle conversion fixes.





---

### BUG-092: Audit all heap pointer storage for handle invariant violations
- **Discovered**: 2026-02-04, during Channel fix for BUG-006
- **Category**: Codegen/GC
- **Severity**: High
- **Reproduction**: Any code path storing heap pointers that survives a GC cycle
- **Observed**: Channel was storing raw pointers via `ptrtoint` instead of handles. Similar violations likely exist elsewhere.
- **Expected**: All stored references to GC-managed objects must be handles (i64 indices), never raw pointers
- **Hypothesis**: Multiple code paths use `ptrtoint` to store heap pointers where `gc_ptr_to_handle` should be used

**Audit Scope** - Search for these patterns in `codegen/`:

1. **`ptrtoint` on heap struct pointers** - Check all uses of `builder.ptrtoint(value, i64)` where `value.type.pointee.name` is one of:
   - `struct.List`, `struct.Map`, `struct.Set`, `struct.Array`, `struct.String`, `struct.Json`
   - Any user-defined type struct

2. **Storage locations requiring handles**:
   - Collection elements (List, Array elements that are reference types)
   - Map keys and values that are reference types
   - Set elements that are reference types
   - Channel send/receive (FIXED in this session)
   - Struct fields containing reference types
   - TaggedValue storage for heap types
   - Any value persisted in heap-allocated structures

3. **Known problem areas from BUG-081** (partially fixed):
   - `codegen/json_type.py` - lines 339, 870, 891, 1463, 2705, 2999, 3108, 3127, 3142, 3186, 3193, 3206, 3568
   - `codegen/posix.py` - Result<T,E> returns (lines 202, 210, 273, 281, 340, 388, 462, 471, 533, 591)
   - `codegen/loops.py` - parallel task results (lines 2187, 2493, 2790, 2807)
   - `codegen/core.py` - field initialization (lines 2864, 2917)

4. **Correct pattern**:
   ```python
   # WRONG: Store raw pointer
   value_i64 = builder.ptrtoint(heap_ptr, i64)

   # CORRECT: Store handle
   value_i8 = builder.bitcast(heap_ptr, i8_ptr)
   value_handle = builder.call(cg.gc.gc_ptr_to_handle, [value_i8])
   ```

5. **Retrieval pattern**:
   ```python
   # For handle storage:
   raw_ptr = builder.call(cg.gc.gc_handle_deref, [handle])
   typed_ptr = builder.bitcast(raw_ptr, target_struct.as_pointer())

   # NOT inttoptr (that's for raw pointer storage)
   ```

**Files to audit**:
- `codegen/expressions.py` - collection access, struct field access
- `codegen/statements.py` - assignments, variable storage
- `codegen/loops.py` - parallel result collection
- `codegen/json_type.py` - JSON value storage
- `codegen/hamt.py` - Map/Set key/value storage
- `codegen/strings.py` - string operations returning strings
- `codegen/posix.py` - Result type returns
- `codegen/channel.py` - FIXED this session
- `codegen/core.py` - struct field initialization

- **Files**: All files in `codegen/` directory
- **Status**: Open
- **Note**: This is a systematic audit bug. Each violation found should be fixed and noted here until all are resolved.

---

### BUG-093: Replace compile-time type inference with runtime TYPE_ID lookup where appropriate
- **Discovered**: 2026-02-04, during Channel fix discussion
- **Category**: Codegen
- **Severity**: Medium
- **Reproduction**: Code paths that use `var_coex_types`, `_infer_type_from_expr`, or `_infer_coex_type_from_initializer` to determine heap object types
- **Observed**: Many code paths use compile-time type inference to determine how to handle heap objects, but this information is already available at runtime via the TYPE_ID stored in each object's header
- **Expected**: Use runtime TYPE_ID from object headers instead of fragile compile-time type inference where the object is already allocated

**Background**:
Every GC-allocated object has a 32-byte header containing:
- Offset 0: size (i64)
- Offset 8: type_id (i64) - **this is the authoritative type**
- Offset 16: flags (i64)
- Offset 24: forward (i64)

TYPE_ID constants (from `coex_gc.py`):
```python
TYPE_LIST = 1
TYPE_STRING = 2
TYPE_MAP = 3
TYPE_SET = 5
TYPE_ARRAY = 8
TYPE_JSON_NULL = 17
TYPE_JSON_BOOL = 18
TYPE_JSON_INT = 19
TYPE_JSON_FLOAT = 20
TYPE_JSON_STRING = 21
TYPE_JSON_ARRAY = 22
TYPE_JSON_OBJECT = 23
```

**Audit Scope**:

1. **Type inference mechanisms to review**:
   - `var_coex_types` dictionary - tracks Coex types for variables
   - `_infer_type_from_expr()` in `codegen/generics.py`
   - `_infer_coex_type_from_initializer()` in `codegen/statements.py`
   - `_get_type_name_from_ptr()` - inspects LLVM pointer type

2. **When to use runtime TYPE_ID instead**:
   - When receiving a value from a generic source (Channel, collection element, etc.)
   - When the compile-time type is unknown or `any`
   - When dispatching on type for serialization (JSON stringify)
   - When the GC needs to trace/mark an object

3. **When compile-time inference is still appropriate**:
   - When the type is statically known from declarations
   - When generating type-specific method calls
   - When the value hasn't been allocated yet (literals, expressions)

4. **Pattern for runtime TYPE_ID lookup**:
   ```python
   # Get TYPE_ID from object header
   header = builder.bitcast(obj_ptr, cg.gc.header_type.as_pointer())
   type_id_ptr = builder.gep(header, [i32(0), i32(1)])  # offset 8
   type_id = builder.load(type_id_ptr)

   # Switch on type_id
   # TYPE_LIST (1) -> handle as List
   # TYPE_STRING (2) -> handle as String
   # etc.
   ```

5. **Specific code to review**:
   - `codegen/statements.py:513-545` - handle conversion for Channel.receive() currently uses inferred type
   - `codegen/statements.py:1303-1323` - return statement handle conversion
   - `codegen/expressions.py:2287` - `_get_type_name_from_ptr` for method dispatch
   - `codegen/json_type.py` - JSON serialization type dispatch
   - Any code that does `isinstance(inferred_coex_type, ListType)` checks

6. **Benefits of TYPE_ID approach**:
   - More robust - doesn't depend on type inference correctness
   - Works for dynamically-typed scenarios
   - Single source of truth (object header)
   - Already used by GC for marking

7. **Potential downsides**:
   - Slightly more runtime overhead (header read)
   - May need switch/branch for type dispatch
   - Some optimizations depend on static type knowledge

- **Files**: `codegen/statements.py`, `codegen/expressions.py`, `codegen/generics.py`, `codegen/json_type.py`, `codegen/core.py`
- **Status**: Open
- **Note**: This is an architectural improvement. Each change should be evaluated for whether runtime TYPE_ID is more appropriate than compile-time inference for that specific use case.

---

### BUG-094: Create universal thread-safe C FFI for malloc'd string to Coex heap string conversion
- **Discovered**: 2026-02-04, during FFI review
- **Category**: Runtime/Stdlib
- **Severity**: Medium
- **Reproduction**: Any C FFI call that returns a malloc'd string (cJSON, file I/O, etc.)
- **Observed**: Multiple FFI libraries have their own ad-hoc implementations for converting C strings to Coex strings, leading to inconsistency and potential memory leaks
- **Expected**: Single universal function that safely converts malloc'd C strings to Coex heap strings

**Requirements**:

1. **Function signature** (C side):
   ```c
   // Takes ownership of c_str (will free it), returns Coex String handle
   // Returns 0 (null handle) if c_str is NULL
   int64_t coex_string_from_cstring_take(char* c_str);
   ```

2. **Thread-safety requirements**:
   - Must not acquire any global locks (non-blocking)
   - Must use thread-local allocation (TLAB) when available
   - Must be safe to call from any thread, including non-Coex threads
   - Must handle the case where GC is in progress

3. **Implementation approach**:
   ```c
   int64_t coex_string_from_cstring_take(char* c_str) {
       if (c_str == NULL) return 0;

       size_t len = strlen(c_str);

       // Allocate Coex String struct (uses TLAB, non-blocking)
       // This should use the thread-safe allocation path
       int64_t string_handle = coex_gc_alloc_string(len);
       if (string_handle == 0) {
           free(c_str);  // Don't leak on allocation failure
           return 0;
       }

       // Copy data to Coex string buffer
       String* str = (String*)coex_gc_handle_deref(string_handle);
       memcpy(str->data, c_str, len);
       str->len = len;

       // Free the original C string
       free(c_str);

       return string_handle;
   }
   ```

4. **Variant for non-owned strings** (copy without free):
   ```c
   // Copies c_str, does NOT free it (caller retains ownership)
   int64_t coex_string_from_cstring_copy(const char* c_str);
   ```

5. **Libraries to update**:
   - `runtime/coex_json.c` - cJSON string returns
   - `runtime/coex_posix.c` - file read returns, getenv, etc.
   - `runtime/coex_string.c` - any C string conversions
   - `codegen/posix.py` - generated FFI calls
   - `codegen/json_type.py` - JSON parsing string extraction
   - Any future FFI libraries

6. **Current problematic patterns to replace**:
   ```c
   // WRONG: Manual allocation + copy + potential leak
   char* c_result = some_c_function();
   String* str = malloc(sizeof(String));  // Should use GC alloc
   str->data = c_result;  // Ownership unclear
   // Who frees c_result? Who frees str?

   // CORRECT: Use universal function
   char* c_result = some_c_function();
   int64_t str_handle = coex_string_from_cstring_take(c_result);
   // c_result is now freed, str_handle is GC-managed
   ```

7. **Edge cases to handle**:
   - NULL input → return null handle (0)
   - Empty string ("") → valid empty Coex string
   - Very large strings → handle allocation failure gracefully
   - Called from non-registered thread → must still work (register thread temporarily?)

8. **Testing requirements**:
   - Unit test for basic conversion
   - Test NULL handling
   - Test empty string
   - Stress test with concurrent calls from multiple threads
   - Test during GC pressure
   - Valgrind/ASAN check for no memory leaks

- **Files**:
  - New: `runtime/coex_ffi.c`, `runtime/coex_ffi.h`
  - Update: `runtime/coex_json.c`, `runtime/coex_posix.c`, `runtime/coex_string.c`
  - Update: `codegen/posix.py`, `codegen/json_type.py`, `codegen/strings.py`
- **Status**: Open

---

**Next valid BUG ID: BUG-096**
