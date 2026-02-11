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




---

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

### BUG-117: LLVM 20 (llvmlite >=0.45.0) causes heap corruption and silent crashes
- **Discovered**: 2026-02-10, during Linux CI investigation
- **Category**: Codegen
- **Severity**: Critical
- **Reproduction**: Run `test_gc_auto_trigger_multiple_cycles` or `test_list_set_38_elements_tail_and_tree` on Linux with llvmlite >=0.45.0 (which uses LLVM 20 with the new PipelineTuningOptions pass manager)
- **Observed**: On Linux CI (Python 3.11, llvmlite 0.46.0/LLVM 20): `test_gc_auto_trigger_multiple_cycles` silently crashes (empty output); `test_list_set_38_elements_tail_and_tree` gets `malloc(): unaligned tcache chunk detected` (glibc heap corruption). Both pass on macOS (llvmlite 0.43.0/LLVM 14).
- **Expected**: Tests should pass with any supported llvmlite version
- **Hypothesis**: LLVM 20's new optimization pipeline is more aggressive and may exploit undefined behavior in our IR, particularly: (1) ptrtoint→arithmetic→inttoptr roundtrips that lose pointer provenance, (2) plain (non-atomic) initial loads on atomically-modified alloc_list pointers (data race UB in C11 memory model), (3) possible other UB patterns that LLVM 14 doesn't exploit.
- **Root causes to investigate**:
  - All `ptrtoint → sub → inttoptr` patterns for header access (widespread in coex_gc.py). Should use `gep` with negative offset to preserve provenance.
  - Plain loads at gc_alloc_to_thread_list:6525, gc_sweep:6668, prepend_survivors:6953 racing with atomic CAS operations on same memory. Should be `load_atomic(..., ordering='monotonic')`.
  - Any other UB patterns exposed by LLVM 20's stricter optimization.
- **Workaround**: Pin llvmlite to <0.45.0 in requirements.txt
- **Files**: coex_gc.py (ptrtoint/inttoptr patterns, atomic ordering), codegen/core.py (compile_to_object LLVM 20 path), requirements.txt
- **Status**: Open (workaround in place: llvmlite pinned to <0.45.0)

---

**Next valid BUG ID: BUG-120**
