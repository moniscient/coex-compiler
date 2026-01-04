# Modularization Step 7: Extract Expressions Implementation

## Target Module: `codegen/expressions.py`

## Current State

- `codegen/expressions.py` exists (283 lines) but only contains delegation stubs
- Real implementations are scattered in `codegen_original.py` lines 15901-18889 (~2988 lines)
- Plus additional expression-related methods in type conversion area
- All 39 methods delegate back to codegen_original.py

## Methods to Extract

### Core Expression Methods (lines 15901-17700)

| Line | Method |
|------|--------|
| 15901 | `_generate_expression` |
| 15998 | `_generate_identifier` |
| 16035 | `_generate_binary` |
| 16120 | `_generate_short_circuit_and` |
| 16146 | `_generate_short_circuit_or` |
| 16172 | `_generate_unary` |
| 16194 | `_generate_call` |
| 16489 | `_generate_array_constructor` |
| 16587 | `_generate_type_constructor` |
| 16646 | `_generate_type_new` |
| 16704 | `_find_enum_variant` |
| 16714 | `_generate_enum_constructor` |
| 16771 | `_generate_method_call` |
| 17154 | `_get_type_name_from_ptr` |
| 17167 | `_generate_member` |
| 17259 | `_get_tuple_field_info` |
| 17268 | `_get_lvalue_member` |
| 17284 | `_generate_index` |
| 17401 | `_generate_slice` |
| 17448 | `_normalize_slice_index` |
| 17461 | `_get_collection_length` |
| 17484 | `_generate_ternary` |
| 17552 | `_generate_list` |
| 17603 | `_generate_map` |
| 17641 | `_generate_set` |

### JSON Conversion Methods (lines 17674-18362)

| Line | Method |
|------|--------|
| 17674 | `_generate_json_object` |
| 17711 | `_convert_to_json` |
| 17760 | `_convert_list_to_json_array` |
| 17832 | `_convert_udt_to_json` |
| 17848 | `_convert_struct_to_json` |
| 17882 | `_convert_enum_to_json` |
| 17957 | `_convert_field_to_json` |
| 18010 | `_generate_as_expr` |
| 18091 | `_generate_non_json_as_expr` |
| 18115 | `_generate_json_to_primitive` |
| 18221 | `_generate_json_to_struct` |
| 18290 | `_generate_json_to_enum` |
| 18303 | `_generate_json_to_list` |
| 18337 | `_extract_json_value` |

### Comprehension Methods (lines 18362-18730)

| Line | Method |
|------|--------|
| 18362 | `_generate_list_comprehension` |
| 18398 | `_generate_set_comprehension` |
| 18419 | `_generate_map_comprehension` |
| 18441 | `_generate_comprehension_loop` |
| 18539 | `_generate_comprehension_range_loop` |
| 18617 | `_generate_comprehension_range_expr_loop` |
| 18688 | `_generate_comprehension_body` |
| 18730 | `_bind_pattern` |

### Other Expression Methods (lines 18759-18976)

| Line | Method |
|------|--------|
| 18759 | `_infer_list_element_type` |
| 18784 | `_get_list_element_type_for_pattern` |
| 18818 | `_get_list_element_coex_type` |
| 18840 | `_get_array_element_type_for_pattern` |
| 18865 | `_generate_tuple` |
| 18889 | `_generate_range` |
| 18895 | `_generate_lambda` |

## Instructions

### Step 1: Copy all expression implementations to expressions.py

### Step 2: Replace delegation stubs with real implementations

### Step 3: Delete the extracted methods from codegen_original.py

### Step 4: Handle shared dependencies

Some methods like `_get_type_name_from_ptr` may be called from multiple places. If so, keep them accessible via the codegen instance.

### Step 5: Run tests

```bash
python3 -m pytest tests/test_basic.py tests/test_functions.py tests/test_types.py -v
python3 -m pytest tests/ -q
```

## Verification Tests

```bash
# expressions.py should now have real implementations
grep -c "ir.IRBuilder" codegen/expressions.py
# BEFORE: 0
# AFTER:  ~400+

# expressions.py should be much larger
wc -l codegen/expressions.py
# BEFORE: 283
# AFTER:  ~3200+

# codegen_original.py should be smaller
wc -l codegen_original.py
# BEFORE: ~6588 (after step 6)
# AFTER:  ~3600 (reduced by ~2988 lines)

# No expression generation methods in codegen_original.py
grep -c "def _generate_expression\|def _generate_binary\|def _generate_call\|def _generate_method_call\|def _generate_list_comprehension" codegen_original.py
# EXPECTED: 0

# No more delegation calls in expressions.py
grep -c "self.codegen._generate_" codegen/expressions.py
# EXPECTED: 0 (or minimal for shared utilities)

# Full suite passes
python3 -m pytest tests/ -q
# EXPECTED: 942 passed
```

## Success Criteria

- [ ] `codegen/expressions.py` has 400+ `ir.IRBuilder` uses
- [ ] `codegen/expressions.py` is ~3200+ lines
- [ ] `codegen_original.py` reduced by ~2988 lines
- [ ] Zero expression `_generate_*` methods in codegen_original.py
- [ ] Minimal delegation calls in expressions.py
- [ ] All 942 tests pass
