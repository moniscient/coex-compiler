# Modularization Step 3: Extract HAMT/Map/Set Implementation

## Target Module: `codegen/hamt.py`

## Current State

- `codegen/hamt.py` exists (724 lines) but only contains delegation stubs
- Real implementations are in `codegen_original.py` lines 5056-8228 (~3172 lines)
- All 43 methods delegate back to codegen_original.py

## Methods to Extract

### HAMT Internal Methods (lines 5307-7103)

| Line | Method |
|------|--------|
| 5307 | `_implement_hamt_popcount` |
| 5349 | `_implement_hamt_node_new` |
| 5396 | `_implement_hamt_leaf_new` |
| 5439 | `_implement_hamt_lookup` |
| 5538 | `_implement_hamt_contains` |
| 5624 | `_implement_hamt_insert` |
| 5934 | `_implement_hamt_remove` |
| 6179 | `_implement_hamt_collect_keys` |
| 6280 | `_implement_hamt_collect_values` |
| 6381 | `_implement_hamt_lookup_string` |
| 6486 | `_implement_hamt_contains_string` |
| 6579 | `_implement_hamt_insert_string` |
| 6882 | `_implement_hamt_remove_string` |

### Map Methods (lines 5056-5306 and 7104-7667)

| Line | Method |
|------|--------|
| 5056 | `_create_map_type` |
| 7104 | `_implement_map_hash` |
| 7127 | `_implement_map_new` |
| 7161 | `_implement_map_set` |
| 7230 | `_implement_map_get` |
| 7257 | `_implement_map_has` |
| 7284 | `_implement_map_remove` |
| 7351 | `_implement_map_len` |
| 7367 | `_implement_map_size` |
| 7393 | `_implement_map_copy` |
| 7411 | `_implement_map_set_string` |
| 7470 | `_implement_map_get_string` |
| 7497 | `_implement_map_has_string` |
| 7524 | `_implement_map_remove_string` |
| 7586 | `_implement_map_keys` |
| 7612 | `_implement_map_values` |
| 7638 | `_register_map_methods` |

### Set Methods (lines 7669-8228)

| Line | Method |
|------|--------|
| 7669 | `_create_set_type` |
| 7784 | `_implement_set_new` |
| 7817 | `_implement_set_find_slot` |
| 7831 | `_implement_set_grow` |
| 7844 | `_implement_set_add` |
| 7909 | `_implement_set_has` |
| 7936 | `_implement_set_remove` |
| 8000 | `_implement_set_len` |
| 8015 | `_implement_set_size` |
| 8042 | `_implement_set_copy` |
| 8060 | `_implement_set_to_list` |
| 8092 | `_implement_set_find_slot_string` |
| 8106 | `_implement_set_has_string` |
| 8134 | `_implement_set_add_string` |
| 8193 | `_register_set_methods` |

## Instructions

### Step 1: Copy all HAMT, Map, and Set implementations to hamt.py

### Step 2: Replace delegation stubs with real implementations

### Step 3: Delete lines 5056-8228 from codegen_original.py

### Step 4: Verify entry points

```python
# In codegen_original.py, should see:
self._hamt.create_map_type()
self._hamt.create_set_type()
```

### Step 5: Run tests

```bash
python3 -m pytest tests/test_maps.py tests/test_sets.py tests/test_hamt*.py -v
python3 -m pytest tests/ -q
```

## Verification Tests

```bash
# hamt.py should now have real implementations
grep -c "ir.IRBuilder" codegen/hamt.py
# BEFORE: 0
# AFTER:  ~400+

# hamt.py should be much larger
wc -l codegen/hamt.py
# BEFORE: 724
# AFTER:  ~3500+

# codegen_original.py should be smaller
wc -l codegen_original.py
# BEFORE: ~14284 (after step 2)
# AFTER:  ~11112 (reduced by ~3172 lines)

# No HAMT/Map/Set implementation methods in codegen_original.py
grep -c "def _implement_hamt_\|def _implement_map_\|def _implement_set_\|def _create_map_type\|def _create_set_type" codegen_original.py
# EXPECTED: 0

# No more delegation calls in hamt.py
grep -c "self.codegen._implement_hamt\|self.codegen._implement_map\|self.codegen._implement_set" codegen/hamt.py
# EXPECTED: 0

# All map/set tests pass
python3 -m pytest tests/test_maps.py tests/test_sets.py -v
# EXPECTED: All pass

# Full suite passes
python3 -m pytest tests/ -q
# EXPECTED: 942 passed
```

## Success Criteria

- [ ] `codegen/hamt.py` has 400+ `ir.IRBuilder` uses
- [ ] `codegen/hamt.py` is ~3500+ lines
- [ ] `codegen_original.py` reduced by ~3172 lines
- [ ] Zero HAMT/Map/Set `_implement_*` methods in codegen_original.py
- [ ] Zero delegation calls in hamt.py
- [ ] All map/set tests pass
- [ ] All 942 tests pass
