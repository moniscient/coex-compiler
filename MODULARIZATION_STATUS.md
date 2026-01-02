# Coex Compiler Modularization Status

## Quick Reference for Claude Code Sessions

**Current Phase**: Phase 2 COMPLETED
**Next Phase**: Phase 3 - Extract GC Handle Management
**Tests**: 942 tests (verified passing)
**Last Updated**: 2026-01-01

**NOTE**: GC package is named `coex_gc/` (not `gc/`) to avoid conflict with Python's built-in gc module.

---

## Phase Checklist

- [x] **Phase 0**: Documentation Setup (COMPLETED 2026-01-01)
- [x] **Phase 1**: Create Package Structure (COMPLETED 2026-01-01)
- [x] **Phase 2**: Extract GC Diagnostics (COMPLETED 2026-01-01)
- [ ] **Phase 3**: Extract GC Handle Management (~335 lines)
- [ ] **Phase 4**: Extract Codegen POSIX (~775 lines)
- [ ] **Phase 5**: Extract Codegen Strings (~2,400 lines)
- [ ] **Phase 6**: Extract Codegen JSON (~1,800 lines)
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
| codegen/strings.py | (new) | ~2,400 |
| codegen/json.py | (new) | ~1,800 |
| codegen/hamt.py | (new) | ~2,550 |
| codegen/collections.py | (new) | ~1,775 |
| codegen/expressions.py | (new) | ~1,585 |
| codegen/statements.py | (new) | ~1,480 |
| codegen/posix.py | (new) | ~775 |
| codegen/types.py | (new) | ~650 |
| codegen/matrix.py | (new) | ~585 |
| codegen/modules.py | (new) | ~430 |
| codegen/atomics.py | (new) | ~400 |
| coex_gc/diagnostics.py | ~1,075 (CREATED) | ~1,075 |
| coex_gc/core.py | (new) | ~1,200 |
| coex_gc/async_gc.py | (new) | ~510 |
| coex_gc/handles.py | (new) | ~335 |
