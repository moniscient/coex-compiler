# Coex Bug Tracker

## Bug Reporting Protocol

**Mandatory**: When encountering any unexpected behavior, test failure, or anomaly during development—even if worked around or tangential to the current task—immediately append a bug report here before continuing. Never assume a bug will be "remembered" for later.

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

### BUG-004: GC race condition with parallel Set allocations
- **Discovered**: 2025-01-17, during codebase scan
- **Category**: GC
- **Severity**: Critical
- **Reproduction**: Run parallel tasks that allocate Sets (e.g., parallel sieve tests)
- **Observed**: Non-deterministic crashes during concurrent Set allocation
- **Expected**: Concurrent Set allocations should be thread-safe
- **Hypothesis**: GC allocation list or Set internals lack proper synchronization
- **Files**: `coex_gc.py`, `tests/test_thread_stress.py`
- **Status**: Open


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

### BUG-064: Library modules cannot call ui.render() with String values in JSON
- **Discovered**: 2026-01-28, during heapwatch implementation
- **Category**: Codegen
- **Severity**: Medium
- **Reproduction**: Create a library that imports ui and calls ui.render() with a JSON panel
  containing String struct values (from String.from()):
  ```coex
  import ui

  func render_panel() -> int
      value = String.from(42)
      panel: json = {
          type: "text",
          text: value  # String struct, not string literal
      }
      ui.render(panel, "{}")  # CRASH
      return 1
  ~
  ```
- **Observed**: Segmentation fault (signal 11) when running the compiled program
- **Expected**: String struct values should be convertible to JSON string values
- **Hypothesis**: When a String struct (not a string literal) is used as a JSON field value,
  the struct pointer is embedded directly instead of extracting the string value. This causes
  issues when the JSON is serialized via stringify() for the C runtime.
- **Workaround**: Use console output via print() instead of ui.render() for library modules
  that need to display dynamic values
- **Files**: `codegen/json_type.py` (JSON literal construction), `codegen/expressions.py`
- **Status**: Open

### BUG-066: Promoted arena values not surviving GC after formula return
- **Discovered**: 2026-01-29, during BUG-065 fix verification
- **Category**: GC
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
  The list pointer appears invalid (points to freed memory / text segment area).
- **Expected**: Values returned from formulas should survive GC if they are stored in
  local variables that are tracked in the shadow stack.
- **Root Cause Analysis**:
  1. Formula `make_data()` allocates `[100, 200, 300]` in the arena
  2. On return, `gc_promote_to_heap` is called to copy the list to the GC heap
  3. `gc_promote_to_heap` internally calls `gc_alloc()` which returns a HANDLE (i64)
  4. BUT: `gc_promote_to_heap` dereferences the handle and returns a raw POINTER (i8*)
  5. The handle is LOST - never stored in the shadow stack
  6. Caller (`main`) stores the returned pointer in `items`, but this is a raw pointer
  7. The shadow stack stores HANDLES, not pointers. Without the handle, the GC
     cannot find this object during root scanning.
  8. When `gc()` runs, it doesn't see the promoted object as a root
  9. The object is swept and freed
  10. Accessing `items.len()` crashes because the memory was freed
- **Hypothesis**: The type system mismatch between handle-based GC (shadow stack stores
  i64 handles) and function return values (List* pointers) means promoted values
  fall through the cracks. The promoted object has a handle, but it's never exposed
  to the caller.
- **Possible Fixes**:
  1. Change `gc_promote_to_heap` to return the handle instead of the pointer. Caller
     can store handle in shadow stack and dereference when needed.
  2. Add a "pointer-to-handle" lookup table so the caller can recover the handle from
     the returned pointer.
  3. Change how formula return values work to use handles instead of pointers.
  4. Have the promotion code also register the handle in the calling function's
     shadow stack (would require passing the caller's frame info).
- **Files**: `coex_gc.py` (gc_promote_to_heap), `codegen/statements.py` (return handling)
- **Status**: Open

---

## Resolved Bugs

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

### Bug Count Summary (as of 2026-01-28)
- **Open**: 14 bugs (BUG-004, BUG-015, BUG-016, BUG-023, BUG-033, BUG-035, BUG-036, BUG-042, BUG-043, BUG-044, BUG-050, BUG-057, BUG-058, BUG-064)
- **Resolved**: 45 bugs (including BUG-059: json.append fix, BUG-060: TLAB reclamation, BUG-061: GC JSON struct fix, BUG-062: handle table leak fix, BUG-063: library nested imports)

### Lock Audit Bugs (BUG-033 to BUG-044)
- **Resolved (by design)**: BUG-034, BUG-037, BUG-038, BUG-039, BUG-040, BUG-041 - condition variable mutexes mandated by POSIX
- **Open (under review)**: BUG-033, BUG-035, BUG-036, BUG-042, BUG-043, BUG-044 - data structure protection locks

### BUG-033: Float list values corrupted when returned from function
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

### BUG-072: json.parse() stores all numbers as floats, as_int() doesn't convert
- **Discovered**: 2026-01-29, during JSON value semantics test development
- **Category**: Runtime
- **Severity**: High
- **Reproduction**:
```coex
func main() -> int
    j: json = json.parse("[1,2,3]")
    e0: json = j[0]
    print(e0.as_int())    # Prints 4607182418800017408 (float bits for 1.0)
    return 0
~
```
- **Observed**: `as_int()` returns garbage (IEEE 754 bit representation of float value)
- **Expected**: `as_int()` should return the integer value (1)
- **Root Cause**: `json.parse()` stores all numbers as floats (JSON_TYPE_FLOAT) even integers. However, `json_as_int()` doesn't check the type and convert - it just reinterprets the raw bits as int64.
- **Files**: `runtime/coex_json.c` (json_parse, json_as_int)
- **Status**: Open
- **Workaround**: Use `as_float()` and cast to int, or avoid parsing + extracting integers

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
- **Root Cause**: Method dispatch in `codegen/expressions.py` routes all `.set()` calls to `json_set_field` which expects a string key. There's no overload resolution to call `json_set_index` when the first argument is an integer.
- **Files**: `codegen/expressions.py` (generate_method_call), `codegen/json_type.py`
- **Status**: Open
- **Workaround**: Use bracket notation for reading (`j[i]`), but there's no workaround for setting by index - must rebuild array with append

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
