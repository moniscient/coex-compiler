# Modularization Step 8: Extract Types Implementation

## Target Module: `codegen/types.py`

## Current State

- `codegen/types.py` exists (216 lines) but mostly contains delegation stubs
- Real implementations are scattered throughout `codegen_original.py`
- 17 type-related methods delegate back to codegen_original.py

## Methods to Extract

### Type Checking/Inference (scattered lines)

| Line | Method |
|------|--------|
| 4800 | `_is_primitive_coex_type` |
| 4806 | `_needs_parameter_copy` |
| 4820 | `_is_heap_type` |
| 4859 | `_compute_map_flags` |
| 4873 | `_compute_set_flags` |
| 4884 | `_is_collection_coex_type` |
| 4892 | `_get_receiver_type` |
| 4913 | `_needs_deep_copy` |
| 11278 | `_get_llvm_type` |
| 11368 | `_is_reference_type` |
| 11384 | `_get_default_value` |
| 11401 | `_get_default_value_for_llvm` |
| 12442 | `_infer_type_from_expr` |
| 12510 | `_llvm_type_to_coex` |
| 12535 | `_unify_types_with_params` |
| 12559 | `_unify_types` |
| 19585 | `_get_type_size` |
| 19598 | `_cast_value_with_builder` |

### Type Registration and Generics (lines 11833-12440)

| Line | Method |
|------|--------|
| 11833 | `_register_trait` |
| 11837 | `_check_trait_implementations` |
| 11851 | `_type_implements_trait` |
| 11866 | `_methods_compatible` |
| 11881 | `_check_trait_bound` |
| 11902 | `_primitive_implements_trait` |
| 11918 | `_register_type` |
| 11936 | `_register_concrete_type` |
| 11977 | `_substitute_type` |
| 12009 | `_mangle_generic_name` |
| 12016 | `_type_to_string` |
| 12036 | `_monomorphize_type` |
| 12081 | `_check_monomorphized_trait_implementations` |
| 12095 | `_declare_type_methods_monomorphized` |
| 12131 | `_generate_method_body` |
| 12222 | `_monomorphize_function` |
| 12357 | `_infer_type_args` |
| 12387 | `_infer_type_args_from_constructor` |
| 12427 | `_unify_type_constructor` |

### Enum Registration (lines 12581-12778)

| Line | Method |
|------|--------|
| 12581 | `_register_enum_type` |
| 12634 | `_method_uses_self` |
| 12737 | `_declare_type_methods` |
| 12778 | `_generate_type_methods` |
| 12848 | `_setup_field_aliases` |
| 12858 | `_get_field_index` |

### FFI Types (lines 12868-12909)

| Line | Method |
|------|--------|
| 12868 | `_get_c_type` |
| 12886 | `_convert_to_c_type` |
| 12900 | `_convert_from_c_type` |

## Note

This is the most complex extraction because type methods are scattered and heavily interconnected. Consider extracting in sub-phases:

1. First: type checking methods (`_is_*`, `_get_llvm_type`, `_get_type_size`)
2. Second: type inference methods (`_infer_*`, `_unify_*`)
3. Third: type registration and generics

## Instructions

### Step 1: Identify all type-related methods and their call dependencies

### Step 2: Copy implementations to types.py, maintaining internal calls

### Step 3: Delete from codegen_original.py

### Step 4: Update any external callers to use `self._types.method()`

### Step 5: Run tests

```bash
python3 -m pytest tests/test_types.py tests/test_advanced.py tests/test_generics.py -v
python3 -m pytest tests/ -q
```

## Verification Tests

```bash
# types.py should now have real implementations
grep -c "ir.IntType\|ir.FloatType\|ir.PointerType" codegen/types.py
# BEFORE: ~5
# AFTER:  ~100+

# types.py should be much larger
wc -l codegen/types.py
# BEFORE: 216
# AFTER:  ~1500+

# codegen_original.py should be smaller
wc -l codegen_original.py
# BEFORE: ~3600 (after step 7)
# AFTER:  ~2100 (reduced by ~1500 lines)

# No type system methods in codegen_original.py
grep -c "def _get_llvm_type\|def _is_primitive_coex_type\|def _infer_type_from_expr\|def _monomorphize_type" codegen_original.py
# EXPECTED: 0

# All type tests pass
python3 -m pytest tests/test_types.py tests/test_generics.py -v
# EXPECTED: All pass

# Full suite passes
python3 -m pytest tests/ -q
# EXPECTED: 942 passed
```

## Success Criteria

- [ ] `codegen/types.py` has 100+ type-related IR constructs
- [ ] `codegen/types.py` is ~1500+ lines
- [ ] `codegen_original.py` reduced by ~1500 lines
- [ ] Zero type system methods in codegen_original.py
- [ ] All type/generics tests pass
- [ ] All 942 tests pass
