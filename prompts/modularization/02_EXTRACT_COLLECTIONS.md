# Modularization Step 2: Extract Collections (List/Array) Implementation

## Target Module: `codegen/collections.py`

## Current State

- `codegen/collections.py` exists (370 lines) but only contains delegation stubs
- Real implementations are in `codegen_original.py` lines 418-2601 (~2183 lines)
- All 25 `_implement_list_*` and `_implement_array_*` methods delegate back

## Methods to Extract

### List Methods (lines 418-1678)

| Line | Method |
|------|--------|
| 418 | `_create_list_helpers` |
| 478 | `_implement_list_new` |
| 538 | `_implement_list_append` |
| 942 | `_implement_list_get` |
| 1095 | `_implement_list_set` |
| 1395 | `_implement_list_len` |
| 1415 | `_implement_list_size` |
| 1446 | `_implement_list_copy` |
| 1464 | `_implement_list_getrange` |
| 1535 | `_implement_list_setrange` |
| 1655 | `_register_list_methods` |

### Array Methods (lines 1679-2193)

| Line | Method |
|------|--------|
| 1679 | `_create_array_helpers` |
| 1740 | `_implement_array_new` |
| 1791 | `_implement_array_get` |
| 1824 | `_implement_array_set` |
| 1884 | `_implement_array_append` |
| 1942 | `_implement_array_len` |
| 1961 | `_implement_array_size` |
| 1990 | `_implement_array_copy` |
| 2010 | `_implement_array_deep_copy` |
| 2088 | `_implement_array_getrange` |
| 2172 | `_register_array_methods` |

### Collection Conversion Methods (lines 2194-2601)

| Line | Method |
|------|--------|
| 2194 | `_list_to_array` |
| 2271 | `_set_to_array` |
| 2315 | `_array_to_list` |
| 2388 | `_array_to_set` |
| 2464 | `_list_to_set` |
| 2527 | `_try_implicit_collection_conversion` |
| 2581 | `_get_conversion_warning_message` |

## Instructions

### Step 1: Copy implementations to collections.py

Copy all methods listed above from `codegen_original.py` to `codegen/collections.py`.

### Step 2: Replace delegation stubs with real implementations

### Step 3: Delete lines 418-2601 from codegen_original.py

### Step 4: Verify entry points use the module

```python
# In codegen_original.py __init__, should see:
self._collections.create_list_helpers()
self._collections.create_array_helpers()
```

### Step 5: Run tests

```bash
python3 -m pytest tests/test_lists.py tests/test_collections.py -v
python3 -m pytest tests/ -q
```

## Verification Tests

```bash
# collections.py should now have real implementations
grep -c "ir.IRBuilder" codegen/collections.py
# BEFORE: 0
# AFTER:  ~200+

# collections.py should be much larger
wc -l codegen/collections.py
# BEFORE: 370
# AFTER:  ~2200+

# codegen_original.py should be smaller
wc -l codegen_original.py
# BEFORE: ~16467 (after step 1)
# AFTER:  ~14284 (reduced by ~2183 lines)

# No list/array implementation methods in codegen_original.py
grep -c "def _implement_list_\|def _implement_array_\|def _create_list_helpers\|def _create_array_helpers\|def _list_to_array\|def _array_to_list" codegen_original.py
# EXPECTED: 0

# No more delegation calls in collections.py
grep -c "self.codegen._implement_list\|self.codegen._implement_array" codegen/collections.py
# EXPECTED: 0

# All collection tests pass
python3 -m pytest tests/test_lists.py tests/test_collections.py -v
# EXPECTED: All pass

# Full suite passes
python3 -m pytest tests/ -q
# EXPECTED: 942 passed
```

## Success Criteria

- [ ] `codegen/collections.py` has 200+ `ir.IRBuilder` uses
- [ ] `codegen/collections.py` is ~2200+ lines
- [ ] `codegen_original.py` reduced by ~2183 lines
- [ ] Zero list/array `_implement_*` methods in codegen_original.py
- [ ] Zero delegation calls in collections.py
- [ ] All collection tests pass
- [ ] All 942 tests pass
