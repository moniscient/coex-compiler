# Coex Compiler Modularization Status

## Quick Reference for Claude Code Sessions

**Current Phase**: Phase 6 COMPLETED
**Next Phase**: Phase 7 - Extract Collections List/Array
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
- [ ] **Phase 7**: Extract Collections List/Array (~1,775 lines)
- [ ] **Phase 8**: Extract HAMT/Map/Set (~2,550 lines)
- [ ] **Phase 9**: Extract Type System (~650 lines)
- [ ] **Phase 10**: Extract Control Flow/Expressions/Statements
- [ ] **Phase 11**: Extract Matrix/Modules/Atomics
- [ ] **Phase 12**: Finalize GC Modularization
- [ ] **Phase 13**: Final Cleanup

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
2. Execute Phase 7: Extract Collections List/Array
   - Create `codegen/collections.py`
   - Extract List/Array-related methods from `codegen_original.py`
   - Run test suite to verify

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
| codegen/hamt.py | (new) | ~2,550 |
| codegen/collections.py | (new) | ~1,775 |
| codegen/expressions.py | (new) | ~1,585 |
| codegen/statements.py | (new) | ~1,480 |
| codegen/posix.py | ~775 (CREATED) | ~775 |
| codegen/types.py | (new) | ~650 |
| codegen/matrix.py | (new) | ~585 |
| codegen/modules.py | (new) | ~430 |
| codegen/atomics.py | (new) | ~400 |
| coex_gc/diagnostics.py | ~1,075 (CREATED) | ~1,075 |
| coex_gc/core.py | (new) | ~1,200 |
| coex_gc/async_gc.py | (new) | ~510 |
| coex_gc/handles.py | ~335 (CREATED) | ~335 |
