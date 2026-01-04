# Modularization Step 6: Extract Statements Implementation

## Target Module: `codegen/statements.py`

## Current State

- `codegen/statements.py` exists (234 lines) but only contains delegation stubs
- Real implementations are scattered in `codegen_original.py` lines 13374-15900 (~2526 lines)
- All 33 methods delegate back to codegen_original.py

## Methods to Extract

### Core Statement Methods (lines 13374-14560)

| Line | Method |
|------|--------|
| 13374 | `_generate_statement` |
| 13411 | `_generate_var_decl` |
| 13731 | `_generate_var_reassignment` |
| 13792 | `_infer_tuple_info` |
| 13813 | `_generate_tuple_destructure` |
| 13855 | `_cast_value` |
| 13924 | `_generate_assignment` |
| 14168 | `_generate_tuple_assignment` |
| 14188 | `_generate_immutable_field_assignment` |
| 14298 | `_generate_slice_assignment` |
| 14361 | `_get_lvalue` |
| 14393 | `_generate_return` |
| 14449 | `_generate_print` |
| 14504 | `_generate_debug` |

### Control Flow Methods (lines 14560-15900)

| Line | Method |
|------|--------|
| 14560 | `_generate_if` |
| 14631 | `_to_bool` |
| 14654 | `_generate_while` |
| 14707 | `_generate_cycle` |
| 14808 | `_find_cycle_declared_vars` |
| 14843 | `_in_cycle_context` |
| 14847 | `_get_cycle_context` |
| 14857 | `_loop_needs_nursery` |
| 14866 | `_has_collection_mutations` |
| 14920 | `_get_loop_carried_vars` |
| 14942 | `_collect_var_usage` |
| 14981 | `_collect_expr_reads` |
| 15031 | `_estimate_nursery_size` |
| 15057 | `_copy_collection_to_main_heap` |
| 15097 | `_generate_for` |
| 15139 | `_generate_range_for` |
| 15283 | `_generate_range_expr_for` |
| 15409 | `_generate_list_for` |
| 15493 | `_generate_array_for` |
| 15570 | `_generate_map_for` |
| 15655 | `_generate_set_for` |
| 15740 | `_generate_for_assign` |
| 15750 | `_generate_break` |
| 15755 | `_generate_continue` |
| 15760 | `_generate_match` |
| 15801 | `_generate_pattern_match` |

### Deep Copy Methods (also used by statements, lines 4930-5000)

| Line | Method |
|------|--------|
| 4930 | `_generate_move_or_eager_copy` |
| 4944 | `_generate_deep_copy` |
| 4961 | `_generate_list_deep_copy` |
| 4969 | `_generate_set_deep_copy` |
| 4977 | `_generate_map_deep_copy` |
| 4985 | `_generate_array_deep_copy` |
| 4993 | `_generate_type_deep_copy` |

## Instructions

### Step 1: Copy all statement implementations to statements.py

### Step 2: Replace delegation stubs with real implementations

### Step 3: Delete the extracted methods from codegen_original.py

Note: Some methods like `_cast_value` are used by both statements and expressions. Put them in statements.py and have expressions.py call them via `self.codegen._statements._cast_value()` or add them as shared utilities.

### Step 4: Run tests

```bash
python3 -m pytest tests/test_control_flow.py tests/test_basic.py -v
python3 -m pytest tests/ -q
```

## Verification Tests

```bash
# statements.py should now have real implementations
grep -c "ir.IRBuilder" codegen/statements.py
# BEFORE: 0
# AFTER:  ~300+

# statements.py should be much larger
wc -l codegen/statements.py
# BEFORE: 234
# AFTER:  ~2700+

# codegen_original.py should be smaller
wc -l codegen_original.py
# BEFORE: ~9114 (after step 5)
# AFTER:  ~6588 (reduced by ~2526 lines)

# No statement generation methods in codegen_original.py
grep -c "def _generate_statement\|def _generate_var_decl\|def _generate_assignment\|def _generate_if\|def _generate_while\|def _generate_for\|def _generate_match" codegen_original.py
# EXPECTED: 0

# No more delegation calls in statements.py
grep -c "self.codegen._generate_" codegen/statements.py
# EXPECTED: 0 (or very few for shared utilities)

# All control flow tests pass
python3 -m pytest tests/test_control_flow.py -v
# EXPECTED: All pass

# Full suite passes
python3 -m pytest tests/ -q
# EXPECTED: 942 passed
```

## Success Criteria

- [ ] `codegen/statements.py` has 300+ `ir.IRBuilder` uses
- [ ] `codegen/statements.py` is ~2700+ lines
- [ ] `codegen_original.py` reduced by ~2526 lines
- [ ] Zero statement `_generate_*` methods in codegen_original.py
- [ ] Minimal delegation calls in statements.py
- [ ] All control flow tests pass
- [ ] All 942 tests pass
