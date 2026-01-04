# Modularization Step 0: Delete Dead Code

## Priority: FIRST (do this before any extractions)

## Problem

During the incomplete modularization, code was extracted to submodules but the original implementations were never deleted. This dead code wastes space and causes confusion.

## Dead Code Locations

### codegen_original.py

| Lines | Methods | Status |
|-------|---------|--------|
| 10504-11277 | `_create_posix_type`, `_create_posix_open`, `_create_posix_read_all`, `_create_posix_writeln`, `_create_posix_close`, `_create_posix_read`, `_create_posix_write`, `_create_posix_seek`, `_create_posix_time`, `_create_posix_time_ns`, `_create_posix_getenv`, `_create_posix_random_seed`, `_create_posix_urandom`, `_get_raw_string_ptr_with_builder` | DEAD - already in codegen/posix.py |

### coex_gc_original.py

| Lines | Methods | Status |
|-------|---------|--------|
| 3281-4205 | `_implement_gc_trace`, `_implement_gc_dump_stats`, `_implement_gc_dump_heap`, `_implement_gc_dump_roots`, `_implement_gc_dump_object`, `_implement_gc_validate_heap`, `_implement_gc_set_trace_level`, `_implement_gc_fragmentation_report`, `_implement_gc_dump_handle_table`, `_implement_gc_dump_shadow_stacks` | DEAD - already in coex_gc/diagnostics.py |
| 4358-4630 | `_implement_gc_handle_table_grow`, `_implement_gc_handle_alloc`, `_implement_gc_handle_free`, `_implement_gc_handle_deref`, `_implement_gc_handle_store`, `_implement_gc_ptr_to_handle`, `_implement_gc_handle_retire`, `_implement_gc_promote_retired_handles` | DEAD - already in coex_gc/handles.py |

## Instructions

1. **Verify the extracted versions exist and have real implementations:**
   ```bash
   grep -c "ir.IRBuilder" codegen/posix.py      # Should be ~191
   grep -c "ir.IRBuilder" coex_gc/diagnostics.py # Should be ~469
   grep -c "ir.IRBuilder" coex_gc/handles.py     # Should be ~129
   ```

2. **Verify the original methods are called via delegation:**
   ```bash
   grep "self._posix.create_posix_type" codegen_original.py       # Should find call
   grep "self._diagnostics.implement_gc" coex_gc_original.py      # Should find calls
   grep "self._handles.implement_gc" coex_gc_original.py          # Should find calls
   ```

3. **Delete the dead methods from codegen_original.py:**
   - Delete lines 10504-11277 (the `_create_posix_*` methods)
   - Keep `_get_raw_string_ptr_with_builder` if it's used elsewhere, otherwise delete

4. **Delete the dead methods from coex_gc_original.py:**
   - Delete lines 3281-4205 (the diagnostic `_implement_gc_*` methods)
   - Delete lines 4358-4630 (the handle `_implement_gc_handle_*` methods)

5. **Run tests:**
   ```bash
   python3 -m pytest tests/ -v --tb=short
   ```

## Verification Tests

After cleanup, run these commands to verify:

```bash
# codegen_original.py should be smaller
wc -l codegen_original.py
# BEFORE: ~19793 lines
# AFTER:  ~18920 lines (reduced by ~873 lines)

# coex_gc_original.py should be smaller
wc -l coex_gc_original.py
# BEFORE: ~4630 lines
# AFTER:  ~3180 lines (reduced by ~1450 lines)

# No POSIX methods should remain in codegen_original.py
grep -c "_create_posix" codegen_original.py
# EXPECTED: 0

# No diagnostic implement methods should remain in coex_gc_original.py
grep -c "_implement_gc_dump\|_implement_gc_trace\|_implement_gc_validate\|_implement_gc_set_trace\|_implement_gc_fragmentation" coex_gc_original.py
# EXPECTED: 0

# No handle implement methods should remain in coex_gc_original.py
grep -c "_implement_gc_handle_\|_implement_gc_ptr_to_handle\|_implement_gc_promote_retired" coex_gc_original.py
# EXPECTED: 0

# All 942 tests must still pass
python3 -m pytest tests/ -q
# EXPECTED: 942 passed
```

## Success Criteria

- [ ] codegen_original.py reduced by ~873 lines
- [ ] coex_gc_original.py reduced by ~1450 lines
- [ ] Zero `_create_posix_*` methods in codegen_original.py
- [ ] Zero diagnostic/handle `_implement_gc_*` methods in coex_gc_original.py
- [ ] All 942 tests pass
