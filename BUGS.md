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

**Investigation Notes (2026-02-04)**:
1. **False positives in strings.py**: String data buffer storage (`owner_handle` field) intentionally uses raw pointers via `ptrtoint`. These are NOT violations because:
   - String data can be arena-allocated (FLAG_ARENA, no handle, bulk-freed)
   - Arena allocations don't support `gc_ptr_to_handle` - they have no forward field
   - The string struct tracks the data buffer; data is read back via `inttoptr`

2. **Result type complexity**: Result stores reference types via `_cast_value(ptr, i64)` which uses `ptrtoint`. Fixing this requires:
   - Change `_cast_value` to use `gc_ptr_to_handle` when target is i64 and source is a reference type pointer
   - Update `Result.unwrap` and similar to use `gc_handle_deref` instead of `inttoptr`
   - Both changes must happen together or the code will crash

3. **Audit criteria refinement**: Only flag `ptrtoint` on GC-allocated objects (not arena-allocated data buffers). Key distinction:
   - GC-allocated: TYPE_STRING, TYPE_LIST, TYPE_MAP, TYPE_ARRAY, user types → need handles
   - Arena-allocated data: TYPE_STRING_DATA, TYPE_LIST_TAIL, etc. → raw pointers OK

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

**Next valid BUG ID: BUG-099**
