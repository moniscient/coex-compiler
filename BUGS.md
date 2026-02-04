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

### BUG-016: gc_async() race condition requires TLAB
- **Discovered**: 2025-01-17, during codebase scan
- **Category**: GC
- **Severity**: Medium
- **Reproduction**: Use `gc_async()` with concurrent allocations
- **Observed**: Race condition causes undefined behavior
- **Expected**: Async GC should run safely in background
- **Hypothesis**: Allocation list access races with async GC thread without TLABs
- **Files**: `coex_gc.py` (gc_async implementation)
- **Status**: Open (blocked on Phase 4 TLAB implementation)
- **Note**: Tests currently pass (xpassed) but architectural race condition remains

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

## Resolved Bugs

### BUG-089: Float list values corrupted when returned from function
- **Discovered**: 2025-01-18, during GEMM benchmark development
- **Category**: Codegen
- **Severity**: Critical
- **Reproduction**: 
  ```coex
  func gemm(a: [float], b: [float]) -> [float]
      result: [float] = []
      for i in 0..2
          val: float = compute(a, b, i)  # val prints correctly here
          result = result.append(val)
      ~
      return result
  ~
  
  func main() -> int
      c = gemm(a, b)
      v: float = c.get(0)  # v is corrupted (e.g., 4620706744243609600.0)
      return 0
  ~
  ```
- **Observed**: Float values computed correctly inside function but read as corrupted values (appear to be bit-reinterpreted) after function returns
- **Expected**: Float list values should maintain integrity across function boundaries
- **Hypothesis**: Type confusion between float32/float64 or handle/pointer in list return path
- **Files**: `codegen/core.py`, `codegen/collections.py`
- **Status**: Open

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

### BUG-058: LLVM domination error with repeated variable declarations in if-blocks
- **Discovered**: 2026-01-28, during Galaxian game implementation
- **Category**: Codegen
- **Severity**: High
- **Reproduction**:
  ```coex
  func main() -> int
      i = 0
      while i < 10
          if i % 2 == 0
              row = i / 2
              col = i % 5
              print(row)
          ~
          if i % 3 == 0
              row = i / 3    # Same variable name as above
              col = i % 4    # Same variable name as above
              print(col)
          ~
          i = i + 1
      ~
      return 0
  ~
  ```
- **Observed**: LLVM IR verification error:
  ```
  Instruction does not dominate all uses!
    %row = alloca i64, align 8
    store i64 %.XXX, i64* %row, align 8
  ```
- **Expected**: Variables with the same name in different if-blocks should create separate allocas or be scoped correctly
- **Hypothesis**: The codegen creates new allocas for each variable declaration inside if-blocks, but LLVM requires all allocas to be in the entry block for proper dominance. When the same variable name is used in multiple non-nested if-blocks within a loop, the allocas are placed in different basic blocks, causing dominance violations.
- **Files**: `codegen/statements.py` (variable declaration handling), `codegen/flow_control.py` (if/while generation)
- **Workaround**: Declare all loop-scoped variables once before the loop or at the top of the while body, then reassign them in the if-blocks rather than re-declaring
- **Status**: Open

### BUG-071: Map.remove() with string keys doesn't use string-aware function
- **Discovered**: 2026-01-29, during JSON refactoring test implementation
- **Category**: Codegen
- **Severity**: Medium
- **Reproduction**:
  ```coex
  func main() -> int
      m: Map<string, int> = {"a": 1, "b": 2}
      m2: Map<string, int> = m.remove("b")
      print(m2.len())  # Still prints 2 instead of 1
      return 0
  ~
  ```
- **Observed**: `map.remove("b")` returns original map unchanged for string keys
- **Expected**: Should return new map with key removed
- **Root Cause**: In `codegen/expressions.py:2045`, the special handling for Map with string keys only covers `get`, `has`, and `set` methods - not `remove`. The `remove` method falls through to `coex_map_remove` which expects an i64 key, not a string pointer.
- **Files**: `codegen/expressions.py:2045-2069`
- **Status**: Open
- **Workaround**: Use integer keys for maps when using `.remove()`

### BUG-073: json.as_string() returns quoted form for parsed strings
- **Discovered**: 2026-01-29, during JSON value semantics test development
- **Category**: Runtime
- **Severity**: Medium
- **Reproduction**:
```coex
func main() -> int
    j: json = json.parse("\"hello\"")
    print(j.as_string())    # Prints "hello" (with quotes)
    return 0
~
```
- **Observed**: `as_string()` returns `"hello"` (with surrounding quotes)
- **Expected**: `as_string()` should return `hello` (raw string value without quotes)
- **Root Cause**: `json.parse()` likely stores the string with its JSON representation (including quotes), and `as_string()` returns this verbatim instead of stripping quotes.
- **Files**: `runtime/coex_json.c` (json_parse, json_as_string)
- **Status**: Open
- **Note**: May be related to BUG-072 - parser may be storing raw JSON tokens instead of parsed values

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

### BUG-082: first/most/parallel-for return wrong values instead of task results
- **Discovered**: 2026-02-04, during CI failure analysis
- **Category**: Codegen
- **Severity**: High
- **Reproduction**: Any program using `first`, `most`, or `for..in` with task dispatch. Example:
  ```coex
  task double(x: int) -> int
      return x * 2
  ~
  func main() -> int
      result = first i in [21]
          double(i)
      ~
      print(result)   # Prints "2" instead of "42"
      return 0
  ~
  ```
- **Observed**: `first` returns small integers (1, 2) unrelated to the computed result. `most` returns partial/wrong sums. Parallel `for..in` map returns 0 or the iteration count instead of accumulated results. The returned values suggest the iteration index or list length is being returned rather than the actual task result.
- **Expected**: `first` should return the result of the first task to complete. `most` should return a list of results from all completed tasks. Parallel `for..in` should collect mapped results.
- **Hypothesis**: The codegen for structured concurrency collection (`first`/`most`/`for..in`) is reading the wrong field from the task closure or result slot. The task result is being stored but the collection code reads the iteration variable or an internal counter instead.
- **Files**: `codegen/core.py` or `codegen/expressions.py` (first/most/for-collection codegen), `runtime/coex_task.c` (task result storage)
- **Affected Tests** (22 tests, marked xfail):
  - `test_first_most.py`: test_first_single_element, test_first_with_computation, test_first_result_is_correct_value, test_most_single_element, test_most_multiple_elements, test_most_large_collection, test_most_sum_results
  - `test_thread_concurrency.py`: test_parallel_map_simple, test_parallel_map_order_preserved, test_parallel_map_with_computation, test_parallel_map_single_element, test_first_single_item, test_first_larger_collection, test_most_larger_collection, test_most_single_item, test_first_with_loop_tasks
  - `test_thread_kind.py`: test_thread_parallel_for, test_thread_first
  - `test_fire_and_forget.py`: test_for_collection_unchanged, test_first_unchanged
  - `test_complex_first_most.py`: test_first_with_if_else, test_first_with_multiple_conditions, test_first_with_local_computation, test_most_with_if_else, test_most_with_local_vars, test_first_with_computation_in_body (these 6 in CI-ignored file)
- **Status**: Open

### BUG-083: User-defined kind handler substitution crashes at runtime
- **Discovered**: 2026-02-04, during CI failure analysis
- **Category**: Codegen
- **Severity**: Medium
- **Reproduction**: Define a `template` kind with curly-brace or positional substitution and call it:
  ```coex
  template greet(name: string) -> string:
      Hello, {name}!
  ~
  func main() -> int
      result = greet("World")
      print(result)
      return 0
  ~
  ```
- **Observed**: Compiles successfully but crashes at runtime (execution failed, no output).
- **Expected**: Should print `Hello, World!`
- **Hypothesis**: The handler substitution codegen produces code that segfaults, likely due to incorrect string interpolation or missing runtime support for the template kind's body expansion.
- **Files**: `codegen/core.py` or `codegen/functions.py` (user-defined kind handler dispatch)
- **Affected Tests** (2 tests, marked xfail):
  - `test_user_defined_kinds.py`: test_curly_brace_substitution, test_positional_substitution
- **Status**: Open

### BUG-084: GC stats don't reflect per-task allocation counts in concurrent programs
- **Discovered**: 2026-02-04, during CI failure analysis
- **Category**: GC
- **Severity**: Low
- **Reproduction**: Spawn 8 tasks that each allocate 100 lists, then check gc_dump_stats output for total count matching 800.
- **Observed**: `gc_dump_stats()` reports `total_allocations: 6436` (internal overhead) rather than a user-visible count of 800. The test expects `"800"` to appear in the output, but the stats report raw internal allocation counts that include GC infrastructure allocations.
- **Expected**: Either the stats should report user-visible allocation counts, or the tests should match the actual stat format.
- **Hypothesis**: The tests were written expecting a per-task result aggregation pattern that doesn't exist. The GC stats count all allocations (including internal PV nodes, tagged values, etc.), not just user-level list creations.
- **Files**: `coex_gc.py` (gc_dump_stats), test expectations
- **Affected Tests** (2 tests, marked xfail):
  - `test_gc_stats_atomic.py`: test_concurrent_allocations_stats_consistent, test_stress_concurrent_allocations
- **Status**: Open

### BUG-085: String.from_bytes produces wrong characters (all bytes become 0x01)
- **Discovered**: 2026-02-04, during CI failure analysis
- **Category**: Codegen
- **Severity**: Medium
- **Reproduction**:
  ```coex
  func main() -> int
      bytes = [72, 101, 108, 108, 111]
      s = String.from_bytes(bytes)
      print(s)    # Prints "\x01\x01\x01\x01\x01" instead of "Hello"
      return 0
  ~
  ```
- **Observed**: All bytes in the output string are `0x01` regardless of input values. The string length is correct (5 chars) but every character is `\x01`.
- **Expected**: `String.from_bytes([72, 101, 108, 108, 111])` should produce `"Hello"`.
- **Hypothesis**: The byte-to-char conversion reads a boolean (nonzero → 1) or a type tag instead of the actual byte value. Likely the list element extraction is reading the TaggedValue type field (which would be 1 for TV_TYPE_INT) instead of the value field.
- **Files**: `codegen/strings.py` (String.from_bytes implementation)
- **Affected Tests** (2 tests, marked xfail):
  - `test_string_len.py`: test_string_from_bytes_ascii, test_string_bytes_ascii
- **Status**: Open

### BUG-086: cstring slice returns zero for byte values at non-zero offsets
- **Discovered**: 2026-02-04, during CI failure analysis
- **Category**: Codegen
- **Severity**: Low
- **Reproduction**:
  ```coex
  func main() -> int
      s = "world!"
      cs = s.cstring()
      print(cs.len())       # Correct: 6
      print(cs.byte_at(0))  # Returns 0, expected 119 ('w')
      print(cs.byte_at(3))  # Returns 0, expected 100 ('d')
      print(cs.byte_at(6))  # Correct: 0 (null terminator)
      return 0
  ~
  ```
- **Observed**: `cstring.byte_at()` returns 0 for all positions except possibly the null terminator. The length is correctly reported as 6.
- **Expected**: `byte_at(0)` should return 119 (`'w'`), `byte_at(3)` should return 100 (`'d'`).
- **Hypothesis**: The `byte_at` implementation may be reading from the wrong base pointer (e.g., the cstring struct header instead of the character data), or the cstring slice view's data pointer offset is not applied correctly.
- **Files**: `codegen/strings.py` (cstring byte_at or slice implementation)
- **Affected Tests** (1 test, marked xfail):
  - `test_cstring.py`: test_cstring_slice
- **Status**: Open

### BUG-087: Cross-heap map references lost during GC swap
- **Discovered**: 2026-02-04, during CI failure analysis
- **Category**: GC
- **Severity**: Medium
- **Reproduction**: Create a map with heap-allocated values (strings), trigger gc_async() to swap heaps, then access the values.
- **Observed**: Map values become inaccessible or corrupted after a heap swap triggered by gc_async().
- **Expected**: Map values should survive GC heap swaps via proper cross-heap reference tracing.
- **Hypothesis**: The cross-heap scanning in `gc_scan_cross_heap` doesn't fully trace through HAMT map node structures, missing references stored in branch nodes.
- **Files**: `coex_gc.py` (`_implement_gc_scan_cross_heap`, `_implement_gc_mark_object`)
- **Affected Tests** (1 test, marked xfail):
  - `test_gc_async.py`: test_map_with_heap_values_across_gc
- **Status**: Open

---

**Next valid BUG ID: BUG-091**
