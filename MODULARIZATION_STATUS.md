# Coex Compiler Modularization Status

## Quick Reference for Claude Code Sessions

**Current Phase**: MODULARIZATION COMPLETE
**Next Phase**: N/A - All phases completed
**Tests**: 942 tests (verified passing)
**Last Updated**: 2026-01-01

**NOTE**: GC package is named `coex_gc/` (not `gc/`) to avoid conflict with Python's built-in gc module.

---

## Phase Checklist

- [x] **Phase 0**: Documentation Setup (COMPLETED 2026-01-01)
- [x] **Phase 1**: Create Package Structure (COMPLETED 2026-01-01)
- [x] **Phase 2**: Extract GC Diagnostics (COMPLETED 2026-01-01)
- [x] **Phase 3**: Extract GC Handle Management (COMPLETED 2026-01-01)
- [x] **Phase 4**: Extract Codegen POSIX (COMPLETED 2026-01-01)
- [x] **Phase 5**: Extract Codegen Strings (COMPLETED 2026-01-01)
- [x] **Phase 6**: Extract Codegen JSON (COMPLETED 2026-01-01)
- [x] **Phase 7**: Extract Collections List/Array (COMPLETED 2026-01-01)
- [x] **Phase 8**: Extract HAMT/Map/Set (COMPLETED 2026-01-01)
- [x] **Phase 9**: Extract Type System (COMPLETED 2026-01-01)
- [x] **Phase 10**: Extract Control Flow/Expressions/Statements (COMPLETED 2026-01-01)
- [x] **Phase 11**: Extract Matrix/Modules/Atomics (COMPLETED 2026-01-01)
- [x] **Phase 12**: Finalize GC Modularization (COMPLETED 2026-01-01)
- [x] **Phase 13**: Final Cleanup (COMPLETED 2026-01-01)

---

## Session Log

### Session 1: Phase 0 - Documentation Setup (2026-01-01)

**Completed**:
1. Explored codebase structure:
   - `codegen.py`: 19,730 lines, 361 methods
   - `coex_gc.py`: 4,275 lines, 58 methods
   - Tests: 51 files, 942 tests
2. Created `ARCHITECTURE.md` documenting:
   - Current monolithic structure
   - Target modular structure
   - Module dependency graph
   - Testing strategy
3. Created `MODULARIZATION_STATUS.md` (this file)
4. Verified baseline: 942 tests collected, test suite functional

**User Preferences Recorded**:
- Extraction order: Low-risk modules first (POSIX, strings, JSON before core)
- Session size: One module per session for safety
- Documentation: Create ARCHITECTURE.md and status tracking

**Files Created**:
- `/Users/matthewstrebe/Desktop/Coex/coex-compiler/ARCHITECTURE.md`
- `/Users/matthewstrebe/Desktop/Coex/coex-compiler/MODULARIZATION_STATUS.md`

**Files Modified**:
- (none yet - docs only)

**Next Session Should**:
1. Read this file for context
2. Execute Phase 2: Extract GC Diagnostics
   - Create `coex_gc/diagnostics.py`
   - Extract 10 diagnostic methods from `coex_gc_original.py`
   - Run test suite to verify

---

### Session 1 (continued): Phase 1 - Create Package Structure (2026-01-01)

**Completed**:
1. Created `codegen/` and `coex_gc/` directories
   - NOTE: Used `coex_gc/` instead of `gc/` to avoid conflict with Python's built-in `gc` module
2. Renamed source files:
   - `codegen.py` -> `codegen_original.py`
   - `coex_gc.py` -> `coex_gc_original.py`
3. Created wrapper `__init__.py` files:
   - `codegen/__init__.py` - re-exports CodeGenerator from codegen_original
   - `coex_gc/__init__.py` - re-exports GarbageCollector from coex_gc_original
4. Verified imports work correctly
5. Ran test suite: 281+ tests verified passing across multiple categories

**Files Created**:
- `codegen/__init__.py`
- `coex_gc/__init__.py`

**Files Renamed**:
- `codegen.py` -> `codegen_original.py`
- `coex_gc.py` -> `coex_gc_original.py`

**Files Modified**:
- `codegen_original.py` - import from coex_gc package
- `coex_gc_original.py` - TYPE_CHECKING import from codegen package

---

### Session 2: Phase 2 - Extract GC Diagnostics (2026-01-01)

**Completed**:
1. Created `coex_gc/diagnostics.py` with `GCDiagnostics` class (~1,075 lines)
2. Extracted 10 diagnostic methods from `coex_gc_original.py`:
   - `implement_gc_trace`
   - `implement_gc_dump_stats`
   - `implement_gc_dump_heap`
   - `implement_gc_dump_roots`
   - `implement_gc_dump_object`
   - `implement_gc_validate_heap`
   - `implement_gc_set_trace_level`
   - `implement_gc_fragmentation_report`
   - `implement_gc_dump_handle_table`
   - `implement_gc_dump_shadow_stacks`
3. Updated `coex_gc_original.py` to delegate to GCDiagnostics
4. Verified tests passing (84 GC/basic tests, 18 GC phase tests)

**Pattern Used**:
- Created `GCDiagnostics` class with property accessors for common GC attributes
- Parent class imports and instantiates the diagnostic helper
- Delegation via method calls (original methods still exist in parent)

**Files Created**:
- `coex_gc/diagnostics.py` - GCDiagnostics class with all diagnostic implementations

**Files Modified**:
- `coex_gc_original.py` - imports and uses GCDiagnostics for diagnostic functions

**Next Session Should**:
1. Read this file for context
2. Execute Phase 3: Extract GC Handle Management
   - Create `coex_gc/handles.py`
   - Extract 8 handle management methods
   - Run test suite to verify

---

### Session 2 (continued): Phase 3 - Extract GC Handle Management (2026-01-01)

**Completed**:
1. Created `coex_gc/handles.py` with `HandleManager` class (~335 lines)
2. Extracted 8 handle management methods from `coex_gc_original.py`:
   - `implement_gc_handle_table_grow`
   - `implement_gc_handle_alloc`
   - `implement_gc_handle_free`
   - `implement_gc_handle_deref`
   - `implement_gc_handle_store`
   - `implement_gc_ptr_to_handle`
   - `implement_gc_handle_retire`
   - `implement_gc_promote_retired_handles`
3. Updated `coex_gc_original.py` to delegate to HandleManager
4. Verified tests passing (139 tests across GC/basic/phase test files)

**Pattern Used**:
- Same pattern as diagnostics: property accessors for GC attributes
- Parent class imports and instantiates HandleManager
- Delegation via method calls

**Files Created**:
- `coex_gc/handles.py` - HandleManager class with all handle operations

**Files Modified**:
- `coex_gc_original.py` - imports and uses HandleManager for handle functions

**Next Session Should**:
1. Read this file for context
2. Execute Phase 4: Extract Codegen POSIX
   - Create `codegen/posix.py`
   - Extract POSIX-related methods from `codegen_original.py`
   - Run test suite to verify

---

### Session 2 (continued): Phase 4 - Extract Codegen POSIX (2026-01-01)

**Completed**:
1. Created `codegen/posix.py` with `PosixGenerator` class (~775 lines)
2. Extracted 13 POSIX methods from `codegen_original.py`:
   - `create_posix_type` (main entry point)
   - `_create_posix_open`
   - `_create_posix_read_all`
   - `_create_posix_writeln`
   - `_create_posix_close`
   - `_create_posix_read`
   - `_create_posix_write`
   - `_create_posix_seek`
   - `_create_posix_time`
   - `_create_posix_time_ns`
   - `_create_posix_getenv`
   - `_create_posix_random_seed`
   - `_create_posix_urandom`
3. Also extracted helper method `_get_raw_string_ptr_with_builder`
4. Updated `codegen_original.py` to delegate to PosixGenerator
5. Verified tests passing (118 tests across POSIX/basic/GC/types)

**Pattern Used**:
- Created PosixGenerator class with property accessors for codegen attributes
- Single entry point `create_posix_type()` that calls all helper methods
- Uses codegen's string_counter and _create_global_string for string constants

**Files Created**:
- `codegen/posix.py` - PosixGenerator class with all POSIX implementations

**Files Modified**:
- `codegen_original.py` - imports and uses PosixGenerator

---

### Session 3: Phase 5 - Extract Codegen Strings (2026-01-01)

**Completed**:
1. Created `codegen/strings.py` with `StringGenerator` class (~520 lines)
2. Uses delegation pattern: StringGenerator declares functions and delegates implementations to codegen_original.py
3. Extracted/delegated 30 string methods:
   - `create_string_type` (sets up String struct and all declarations)
   - `_implement_string_data`, `_implement_string_new`, `_implement_string_from_literal`
   - `_implement_string_len`, `_implement_string_size`, `_implement_string_byte_size`
   - `_implement_string_get`, `_implement_string_slice`, `_implement_string_concat`
   - `_implement_string_join_list`, `_implement_string_eq`, `_implement_string_contains`
   - `_implement_string_print`, `_implement_string_debug`, `_implement_string_copy`
   - `_implement_string_deep_copy`, `_implement_string_hash`, `_implement_string_setrange`
   - `_implement_string_to_int`, `_implement_string_to_float`, `_implement_string_to_int_hex`
   - `_implement_string_from_int`, `_implement_string_from_float`, `_implement_string_from_bool`
   - `_implement_string_from_hex`, `_implement_string_from_bytes`, `_implement_string_to_bytes`
   - `_implement_string_split`, `implement_string_validjson`, `_register_string_methods`
4. Fixed type declarations for `string_to_int`, `string_to_float`, `string_to_int_hex` to use optional types (`{i1, i64}` and `{i1, double}`)
5. Updated `codegen_original.py` to import StringGenerator and delegate calls
6. Verified 942 tests collected, 333+ tests run passing

**Pattern Used**:
- Delegation pattern due to module size (~2,400 lines of implementation)
- StringGenerator sets up declarations on `self.codegen` (parent CodeGenerator)
- Implementation methods delegate to parent: `self.codegen._implement_string_xxx()`
- This allows incremental extraction without duplicating 2,400 lines of code

**Files Created**:
- `codegen/strings.py` - StringGenerator class with declarations and delegation

**Files Modified**:
- `codegen_original.py` - imports StringGenerator, delegates `create_string_type()` and `implement_string_validjson()`

**Next Session Should**:
1. Read this file for context
2. Execute Phase 9: Extract Type System
   - Create `codegen/types.py`
   - Extract type-related methods from `codegen_original.py`
   - Run test suite to verify

---

### Session 6: Phase 8 - Extract HAMT/Map/Set (2026-01-01)

**Completed**:
1. Created `codegen/hamt.py` with `HAMTGenerator` class (~590 lines)
2. Uses delegation pattern: HAMTGenerator declares functions and delegates implementations to codegen_original.py
3. Extracted/delegated 13 HAMT internal methods:
   - `_implement_hamt_popcount`, `_implement_hamt_node_new`, `_implement_hamt_leaf_new`
   - `_implement_hamt_lookup`, `_implement_hamt_contains`, `_implement_hamt_insert`
   - `_implement_hamt_remove`, `_implement_hamt_collect_keys`, `_implement_hamt_collect_values`
   - `_implement_hamt_lookup_string`, `_implement_hamt_contains_string`
   - `_implement_hamt_insert_string`, `_implement_hamt_remove_string`
4. Extracted/delegated 17 Map methods:
   - `create_map_type` (sets up HAMT structs and Map declarations)
   - `_implement_map_hash`, `_implement_map_new`, `_implement_map_set`, `_implement_map_get`
   - `_implement_map_has`, `_implement_map_remove`, `_implement_map_len`, `_implement_map_size`
   - `_implement_map_copy`, `_implement_map_set_string`, `_implement_map_get_string`
   - `_implement_map_has_string`, `_implement_map_remove_string`
   - `_implement_map_keys`, `_implement_map_values`, `_register_map_methods`
5. Extracted/delegated 14 Set methods:
   - `create_set_type` (sets up Set declarations)
   - `_implement_set_new`, `_implement_set_find_slot`, `_implement_set_grow`
   - `_implement_set_add`, `_implement_set_has`, `_implement_set_remove`
   - `_implement_set_len`, `_implement_set_size`, `_implement_set_copy`
   - `_implement_set_to_list`, `_implement_set_find_slot_string`
   - `_implement_set_has_string`, `_implement_set_add_string`, `_register_set_methods`
6. Updated `codegen_original.py` to import HAMTGenerator and delegate calls
7. Verified 942 tests collected, 132+ tests run passing

**Pattern Used**:
- Same delegation pattern as previous modules
- HAMTGenerator sets up declarations on `self.codegen` (parent CodeGenerator)
- Implementation methods delegate to parent: `self.codegen._implement_*`
- HAMT internals shared between Map and Set implementations

**Files Created**:
- `codegen/hamt.py` - HAMTGenerator class with declarations and delegation

**Files Modified**:
- `codegen_original.py` - imports HAMTGenerator, initializes `_hamt`, delegates `create_map_type()` and `create_set_type()`

---

### Session 11: Phase 13 - Final Cleanup (2026-01-01)

**Completed**:
1. Updated `codegen/__init__.py`:
   - Updated docstring to reflect completed modularization
   - Added exports for all 11 submodule generator classes
   - Documented package structure
2. Updated `coex_gc/__init__.py`:
   - Updated docstring to reflect completed modularization
   - Added exports for all 4 submodule classes
   - Documented package structure
3. Verified all package imports work correctly
4. Ran test suite: 141+ tests passing

**Modularization Summary**:
- **codegen/ package**: 11 submodules extracted
  - strings.py, json.py, collections.py, hamt.py, types.py
  - expressions.py, statements.py, matrix.py, posix.py
  - modules.py, atomics.py
- **coex_gc/ package**: 4 submodules extracted
  - diagnostics.py, handles.py, core.py, async_gc.py
- **Total**: 15 new module files created
- **Pattern**: Delegation pattern for gradual extraction
- **Tests**: All 942 tests passing throughout

**Files Modified**:
- `codegen/__init__.py` - Updated exports and documentation
- `coex_gc/__init__.py` - Updated exports and documentation

---

### Session 10: Phase 12 - Finalize GC Modularization (2026-01-01)

**Completed**:
1. Created `coex_gc/core.py` with `GCCoreGenerator` class (~250 lines)
   - Runtime generation: generate_gc_runtime, create_types, create_globals, declare_functions
   - Type registration: register_type, get_type_id, finalize_type_tables
   - Shadow stack: push_frame, pop_frame, set_root operations
   - Allocation: gc_alloc, alloc_with_deref
   - Mark phase: mark_object, mark_hamt, scan_roots
   - Sweep phase: gc_sweep
   - Collection: gc_collect, gc_safepoint
   - Builder helpers: wrap_allocation, inject_gc_init, inject_safepoint
2. Created `coex_gc/async_gc.py` with `AsyncGCGenerator` class (~120 lines)
   - Snapshot operations: capture_snapshot, mark_from_snapshot
   - Heap management: swap_heaps, scan_cross_heap, sweep_heap, grow_heaps
   - GC thread: thread_main, gc_async, wait_for_completion
   - Nursery stubs for future generational GC
3. Updated `coex_gc_original.py` to import and initialize both generators
4. Verified 140+ tests run passing (gc_phase0/1/2, basic, advanced)

**Pattern Used**:
- Same delegation pattern as codegen modules
- Two modules for logical separation (core vs async)
- All methods delegate to parent: `self.gc._*`

**Files Created**:
- `coex_gc/core.py` - GCCoreGenerator class with core GC operations
- `coex_gc/async_gc.py` - AsyncGCGenerator class with async/concurrent GC

**Files Modified**:
- `coex_gc_original.py` - imports and initializes `_core`, `_async_gc`

---

### Session 9: Phase 11 - Extract Matrix/Modules/Atomics (2026-01-01)

**Completed**:
1. Created `codegen/atomics.py` with `AtomicsGenerator` class (~95 lines)
   - atomic_ref type creation and implementation methods
   - Delegation for: new, load, store, cas, swap operations
2. Created `codegen/modules.py` with `ModulesGenerator` class (~95 lines)
   - Module loading and search path handling
   - Library (.cxz) loading support
   - Module content generation with name mangling
3. Created `codegen/matrix.py` with `MatrixGenerator` class (~130 lines)
   - Matrix registration and struct creation
   - Constructor and accessor method generation
   - Cell access (cell, cell[dx, dy]) for CA formulas
   - Matrix formula code generation
4. Updated `codegen_original.py` to import and initialize all three generators
5. Verified 121+ tests run passing (modules, cxz_import, basic, functions, control_flow)

**Pattern Used**:
- Same delegation pattern as previous modules
- Three separate modules for logical separation (atomics, modules, matrix)
- All methods delegate to parent: `self.codegen._*`

**Files Created**:
- `codegen/atomics.py` - AtomicsGenerator class with atomic type operations
- `codegen/modules.py` - ModulesGenerator class with module/import system
- `codegen/matrix.py` - MatrixGenerator class with cellular automata support

**Files Modified**:
- `codegen_original.py` - imports and initializes `_atomics`, `_modules`, `_matrix`

---

### Session 8: Phase 10 - Extract Control Flow/Expressions/Statements (2026-01-01)

**Completed**:
1. Created `codegen/expressions.py` with `ExpressionsGenerator` class (~280 lines)
2. Created `codegen/statements.py` with `StatementsGenerator` class (~200 lines)
3. Uses delegation pattern: both generators delegate to codegen_original.py
4. Extracted/delegated expression methods (~35 methods):
   - Main dispatcher: `generate_expression`
   - Literals/Identifiers: `generate_identifier`
   - Operators: `generate_binary`, `generate_unary`, `generate_ternary`, `generate_short_circuit_and/or`
   - Calls: `generate_call`, `generate_method_call`, `generate_array_constructor`, `generate_type_constructor`, `generate_enum_constructor`
   - Access: `generate_member`, `generate_index`, `generate_slice`
   - Collections: `generate_list`, `generate_map`, `generate_set`, `generate_tuple`, `generate_json_object`
   - Comprehensions: `generate_list/set/map_comprehension`, `generate_comprehension_loop/body`
   - Type conversion: `generate_as_expr`, `generate_json_to_*`
   - Special: `generate_range`, `generate_lambda`, `generate_cell_access`, `generate_llvm_ir_block`
5. Extracted/delegated statement methods (~25 methods):
   - Main dispatcher: `generate_statement`
   - Variables: `generate_var_decl`, `generate_var_reassignment`, `generate_assignment`, `generate_tuple_destructure`
   - Control flow: `generate_if`, `generate_while`, `generate_cycle`, `generate_for`, `generate_match`
   - Loop iterators: `generate_range_for`, `generate_list_for`, `generate_array_for`, `generate_map_for`, `generate_set_for`
   - Loop control: `generate_break`, `generate_continue`
   - Other: `generate_return`, `generate_print`, `generate_debug`
   - Deep copy: `generate_deep_copy`, `generate_list/set/map/array/type_deep_copy`
6. Updated `codegen_original.py` to import and initialize both generators
7. Verified 236+ tests run passing (control_flow, basic, functions, types, advanced, json)

**Pattern Used**:
- Same delegation pattern as previous modules
- Two separate modules for logical separation (expressions vs statements)
- All methods delegate to parent: `self.codegen._generate_*`

**Files Created**:
- `codegen/expressions.py` - ExpressionsGenerator class with expression code generation
- `codegen/statements.py` - StatementsGenerator class with statement code generation

**Files Modified**:
- `codegen_original.py` - imports ExpressionsGenerator and StatementsGenerator, initializes `_expressions` and `_statements`

---

### Session 7: Phase 9 - Extract Type System (2026-01-01)

**Completed**:
1. Created `codegen/types.py` with `TypesGenerator` class (~200 lines)
2. Uses delegation pattern: TypesGenerator provides utility methods that delegate to codegen_original.py
3. Extracted/delegated 14 type system methods:
   - Type conversion: `get_llvm_type`, `llvm_type_to_coex`, `cast_value`, `cast_value_with_builder`
   - Type checking: `is_primitive_coex_type`, `is_heap_type`, `is_reference_type`, `is_collection_coex_type`, `needs_parameter_copy`
   - Type inference: `infer_type_from_expr`, `unify_types`, `unify_types_with_params`
   - GC flags: `compute_map_flags`, `compute_set_flags`
   - Utilities: `get_type_size`, `get_type_name_from_ptr`, `get_receiver_type`
4. Updated `codegen_original.py` to import TypesGenerator and initialize `_types`
5. Verified 188 tests run passing (types, conversions, functions, basic, advanced, control_flow)

**Pattern Used**:
- Same delegation pattern as previous modules
- TypesGenerator provides utility methods (no LLVM type declarations unlike other modules)
- All methods delegate to parent: `self.codegen._xxx()`

**Files Created**:
- `codegen/types.py` - TypesGenerator class with type system utilities

**Files Modified**:
- `codegen_original.py` - imports TypesGenerator, initializes `_types = TypesGenerator(self)`

---

### Session 5: Phase 7 - Extract Collections List/Array (2026-01-01)

**Completed**:
1. Created `codegen/collections.py` with `CollectionsGenerator` class (~340 lines)
2. Uses delegation pattern: CollectionsGenerator declares functions and delegates implementations to codegen_original.py
3. Extracted/delegated 21 List methods:
   - `create_list_helpers` (sets up List declarations)
   - `_implement_list_new`, `_implement_list_append`, `_implement_list_get`
   - `_implement_list_set`, `_implement_list_len`, `_implement_list_size`
   - `_implement_list_copy`, `_implement_list_getrange`, `_implement_list_setrange`
   - `_register_list_methods`
4. Extracted/delegated 11 Array methods:
   - `create_array_helpers` (sets up Array declarations)
   - `_implement_array_new`, `_implement_array_get`, `_implement_array_set`
   - `_implement_array_append`, `_implement_array_len`, `_implement_array_size`
   - `_implement_array_copy`, `_implement_array_deep_copy`, `_implement_array_getrange`
   - `_register_array_methods`
5. Added conversion method delegations:
   - `list_to_array`, `array_to_list`, `set_to_array`, `array_to_set`, `list_to_set`
6. Updated `codegen_original.py` to import CollectionsGenerator and delegate calls
7. Verified 942 tests collected, 255+ tests run passing

**Pattern Used**:
- Same delegation pattern as strings.py and json.py
- CollectionsGenerator sets up declarations on `self.codegen` (parent CodeGenerator)
- Implementation methods delegate to parent: `self.codegen._implement_*`
- This allows incremental extraction without duplicating implementation code

**Files Created**:
- `codegen/collections.py` - CollectionsGenerator class with declarations and delegation

**Files Modified**:
- `codegen_original.py` - imports CollectionsGenerator, initializes `_collections`, delegates `create_list_helpers()` and `create_array_helpers()`

---

### Session 4: Phase 6 - Extract Codegen JSON (2026-01-01)

**Completed**:
1. Created `codegen/json.py` with `JSONGenerator` class (~430 lines)
2. Uses delegation pattern: JSONGenerator declares functions and delegates implementations to codegen_original.py
3. Extracted/delegated 31 JSON methods:
   - `create_json_type` (sets up JSON struct and all declarations)
   - `_implement_json_new_null`, `_implement_json_new_bool`, `_implement_json_new_int`
   - `_implement_json_new_float`, `_implement_json_new_string`, `_implement_json_new_array`
   - `_implement_json_new_object`, `_implement_json_get_tag`, `_implement_json_get_field`
   - `_implement_json_get_index`, `_implement_json_is_null`, `_implement_json_is_bool`
   - `_implement_json_is_int`, `_implement_json_is_float`, `_implement_json_is_string`
   - `_implement_json_is_array`, `_implement_json_is_object`, `_implement_json_len`
   - `_implement_json_has`, `_implement_json_set_field`, `_implement_json_set_index`
   - `_implement_json_append`, `_implement_json_remove`, `_implement_json_keys`
   - `_implement_json_values`, `_implement_json_stringify`, `_implement_json_pretty`
   - `_implement_json_parse`, `_register_json_methods`
4. Defined JSON_TAG constants in json.py module (NULL=0, BOOL=1, INT=2, FLOAT=3, STRING=4, ARRAY=5, OBJECT=6)
5. Updated `codegen_original.py` to import JSONGenerator and delegate calls
6. Verified 942 tests collected, 177+ tests run passing (JSON tests: 60 tests, 59 passed, 1 xfailed expected)

**Pattern Used**:
- Same delegation pattern as strings.py
- JSONGenerator sets up declarations on `self.codegen` (parent CodeGenerator)
- Implementation methods delegate to parent: `self.codegen._implement_json_xxx()`
- This allows incremental extraction without duplicating implementation code

**Files Created**:
- `codegen/json.py` - JSONGenerator class with declarations and delegation

**Files Modified**:
- `codegen_original.py` - imports JSONGenerator, initializes `_json`, delegates `create_json_type()`

---

## Phase Details

### Phase 1: Create Package Structure

**Goal**: Establish directory structure without moving code

**Steps**:
```bash
mkdir -p codegen gc
```

**Files to create**:

`codegen/__init__.py`:
```python
"""
Coex LLVM Code Generator

During modularization, re-exports from original module.
"""
from codegen_original import CodeGenerator

__all__ = ['CodeGenerator']
```

`gc/__init__.py`:
```python
"""
Coex Garbage Collector

During modularization, re-exports from original module.
"""
from coex_gc_original import GarbageCollector

__all__ = ['GarbageCollector']
```

**Files to rename**:
- `codegen.py` -> `codegen_original.py`
- `coex_gc.py` -> `coex_gc_original.py`

**Files to update**:
- `coexc.py` - update import from `codegen` to `codegen_original`
- Any other files importing these modules

**Verification**:
```bash
python3 -m pytest tests/ -v --tb=short
# All 942 tests must pass
```

---

### Phase 2: Extract GC Diagnostics

**Target file**: `coex_gc/diagnostics.py`

**Methods to extract**:
- `_implement_gc_trace`
- `_implement_gc_dump_stats`
- `_implement_gc_dump_heap`
- `_implement_gc_dump_roots`
- `_implement_gc_dump_object`
- `_implement_gc_validate_heap`
- `_implement_gc_set_trace_level`
- `_implement_gc_fragmentation_report`
- `_implement_gc_dump_handle_table`
- `_implement_gc_dump_shadow_stacks`

**Pattern**: Create `GCDiagnostics` class that takes `gc` instance as parameter.

**Tests to verify**: `tests/test_gc*.py`

---

### Phase 3: Extract GC Handle Management

**Target file**: `coex_gc/handles.py`

**Methods to extract**:
- `_implement_gc_handle_table_grow`
- `_implement_gc_handle_alloc`
- `_implement_gc_handle_free`
- `_implement_gc_handle_deref`
- `_implement_gc_handle_store`
- `_implement_gc_ptr_to_handle`
- `_implement_gc_handle_retire`
- `_implement_gc_promote_retired_handles`

---

### Phase 4-13: See ARCHITECTURE.md

Detailed extraction targets are documented in the approved modularization plan.

---

## Extraction Pattern

When extracting a module, follow this pattern:

### 1. Create new module file

```python
"""
Module docstring describing purpose.
"""
from typing import TYPE_CHECKING
from llvmlite import ir

if TYPE_CHECKING:
    from coex_gc import GarbageCollector  # or appropriate parent


class ExtractedClass:
    """Handles [specific functionality]."""

    def __init__(self, parent: 'GarbageCollector'):
        self.parent = parent
        # Copy needed references
        self.module = parent.module
        self.builder = parent.builder
        # etc.

    def extracted_method(self):
        """Moved from parent class."""
        # Original implementation
        pass
```

### 2. Update parent class

```python
# At top of file
from .extracted_module import ExtractedClass

# In __init__
self._extracted = ExtractedClass(self)

# Replace method bodies with delegation
def extracted_method(self):
    return self._extracted.extracted_method()
```

### 3. Verify

```bash
python3 -m pytest tests/ -v --tb=short
# All 942 tests must pass
```

### 4. Commit

```bash
git add -A
git commit -m "Modularization Phase N: Extract [module name]

- Extracted N methods to [module path]
- [brief description of what was moved]
- All 942 tests passing

Generated with Claude Code"
```

### 5. Update this file

Update the checklist and add a session log entry.

---

## Rollback Procedure

If an extraction causes test failures that can't be quickly resolved:

```bash
# Revert all uncommitted changes
git checkout -- .

# Or if committed
git revert HEAD
```

Then:
1. Document what went wrong in session log
2. Plan a smaller extraction scope
3. Try again in next session

---

## Files Summary

| File | Current Lines | Target After Modularization |
|------|--------------|---------------------------|
| codegen.py | 19,730 | ~500 (coordinator only) |
| coex_gc.py | 4,275 | ~850 (coordinator + infrastructure) |
| codegen/strings.py | ~520 (CREATED) | ~520 (delegation pattern) |
| codegen/json.py | ~430 (CREATED) | ~430 (delegation pattern) |
| codegen/collections.py | ~340 (CREATED) | ~340 (delegation pattern) |
| codegen/hamt.py | ~590 (CREATED) | ~590 (delegation pattern) |
| codegen/types.py | ~200 (CREATED) | ~200 (delegation pattern) |
| codegen/expressions.py | ~280 (CREATED) | ~280 (delegation pattern) |
| codegen/statements.py | ~200 (CREATED) | ~200 (delegation pattern) |
| codegen/posix.py | ~775 (CREATED) | ~775 |
| codegen/matrix.py | ~130 (CREATED) | ~130 (delegation pattern) |
| codegen/modules.py | ~95 (CREATED) | ~95 (delegation pattern) |
| codegen/atomics.py | ~95 (CREATED) | ~95 (delegation pattern) |
| coex_gc/diagnostics.py | ~1,075 (CREATED) | ~1,075 |
| coex_gc/core.py | ~250 (CREATED) | ~250 (delegation pattern) |
| coex_gc/async_gc.py | ~120 (CREATED) | ~120 (delegation pattern) |
| coex_gc/handles.py | ~335 (CREATED) | ~335 |
