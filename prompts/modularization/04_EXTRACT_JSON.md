# Modularization Step 4: Extract JSON Implementation

## Target Module: `codegen/json.py`

## Current State

- `codegen/json.py` exists (511 lines) but only contains delegation stubs
- Real implementations are in `codegen_original.py` lines 8229-10029 (~1800 lines)
- All 30 methods delegate back to codegen_original.py

## Methods to Extract

| Line | Method |
|------|--------|
| 8229 | `_create_json_type` |
| 8448 | `_implement_json_new_null` |
| 8474 | `_implement_json_new_bool` |
| 8502 | `_implement_json_new_int` |
| 8529 | `_implement_json_new_float` |
| 8557 | `_implement_json_new_string` |
| 8585 | `_implement_json_new_array` |
| 8613 | `_implement_json_new_object` |
| 8641 | `_implement_json_get_tag` |
| 8655 | `_implement_json_get_field` |
| 8712 | `_implement_json_get_index` |
| 8772 | `_implement_json_is_null` |
| 8785 | `_implement_json_is_bool` |
| 8798 | `_implement_json_is_int` |
| 8811 | `_implement_json_is_float` |
| 8824 | `_implement_json_is_string` |
| 8837 | `_implement_json_is_array` |
| 8850 | `_implement_json_is_object` |
| 8863 | `_implement_json_len` |
| 8910 | `_implement_json_has` |
| 8942 | `_implement_json_set_field` |
| 8983 | `_implement_json_set_index` |
| 9024 | `_implement_json_append` |
| 9065 | `_implement_json_remove` |
| 9101 | `_implement_json_keys` |
| 9138 | `_implement_json_values` |
| 9175 | `_implement_json_stringify` |
| 9269 | `_get_or_create_global_string` |
| 9289 | `_stringify_array` |
| 9365 | `_stringify_object` |
| 9455 | `_implement_json_pretty` |
| 9483 | `_implement_json_pretty_internal` |
| 9588 | `_make_indent_string` |
| 9632 | `_pretty_array` |
| 9726 | `_pretty_object` |
| 9832 | `_implement_json_parse` |
| 9964 | `_register_json_methods` |

## Instructions

### Step 1: Copy all JSON implementations to json.py

### Step 2: Replace delegation stubs with real implementations

### Step 3: Delete lines 8229-10029 from codegen_original.py

### Step 4: Verify entry point

```python
# In codegen_original.py, should see:
self._json.create_json_type()
```

### Step 5: Run tests

```bash
python3 -m pytest tests/test_json.py -v
python3 -m pytest tests/ -q
```

## Verification Tests

```bash
# json.py should now have real implementations
grep -c "ir.IRBuilder" codegen/json.py
# BEFORE: 0
# AFTER:  ~200+

# json.py should be much larger
wc -l codegen/json.py
# BEFORE: 511
# AFTER:  ~2000+

# codegen_original.py should be smaller
wc -l codegen_original.py
# BEFORE: ~11112 (after step 3)
# AFTER:  ~9312 (reduced by ~1800 lines)

# No JSON implementation methods in codegen_original.py
grep -c "def _implement_json_\|def _create_json_type\|def _stringify_\|def _pretty_\|def _register_json_methods" codegen_original.py
# EXPECTED: 0

# No more delegation calls in json.py
grep -c "self.codegen._implement_json" codegen/json.py
# EXPECTED: 0

# All JSON tests pass
python3 -m pytest tests/test_json.py -v
# EXPECTED: 60 tests pass (59 pass, 1 xfail expected)

# Full suite passes
python3 -m pytest tests/ -q
# EXPECTED: 942 passed
```

## Success Criteria

- [ ] `codegen/json.py` has 200+ `ir.IRBuilder` uses
- [ ] `codegen/json.py` is ~2000+ lines
- [ ] `codegen_original.py` reduced by ~1800 lines
- [ ] Zero JSON `_implement_*` methods in codegen_original.py
- [ ] Zero delegation calls in json.py
- [ ] All JSON tests pass
- [ ] All 942 tests pass
