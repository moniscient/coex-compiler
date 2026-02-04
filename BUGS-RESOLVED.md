# Coex Resolved Bugs Archive

This file contains bugs that have been fixed or resolved. They are moved here from BUGS.md to reduce context size when working on active bugs.

---

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

### Bug Count Summary (as of 2026-01-30)
- **Open**: 11 bugs (BUG-015, BUG-016, BUG-023, BUG-033, BUG-035, BUG-036, BUG-042, BUG-043, BUG-044, BUG-050, BUG-057, BUG-058)
- **Resolved**: 48 bugs (including BUG-004: CAS-based thread-safe TLAB allocation)

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

