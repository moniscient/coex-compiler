# Modularization Step 9: Extract Matrix/Cellular Automata Implementation

## Target Module: `codegen/matrix.py`

## Current State

- `codegen/matrix.py` exists (140 lines) but only contains delegation stubs
- Real implementations are in `codegen_original.py` lines 18976-19585 (~609 lines)
- 9 methods delegate back to codegen_original.py

## Methods to Extract

| Line | Method |
|------|--------|
| 18976 | `_generate_cell_access` |
| 18995 | `_generate_cell_index_access` |
| 19068 | `_generate_matrix_return` |
| 19093 | `_register_matrix` |
| 19133 | `_create_matrix_constructor` |
| 19242 | `_create_matrix_accessors` |
| 19365 | `_declare_matrix_methods` |
| 19379 | `_generate_matrix_methods` |
| 19389 | `_generate_matrix_formula` |

## Instructions

### Step 1: Copy all matrix implementations to matrix.py

### Step 2: Replace delegation stubs with real implementations

### Step 3: Delete lines 18976-19585 from codegen_original.py

### Step 4: Run tests

```bash
python3 -m pytest tests/test_matrix.py tests/test_ca.py -v
python3 -m pytest tests/ -q
```

## Verification Tests

```bash
# matrix.py should now have real implementations
grep -c "ir.IRBuilder" codegen/matrix.py
# BEFORE: 0
# AFTER:  ~50+

# matrix.py should be larger
wc -l codegen/matrix.py
# BEFORE: 140
# AFTER:  ~700+

# codegen_original.py should be smaller
wc -l codegen_original.py
# BEFORE: ~2100 (after step 8)
# AFTER:  ~1491 (reduced by ~609 lines)

# No matrix methods in codegen_original.py
grep -c "def _generate_cell\|def _register_matrix\|def _create_matrix\|def _generate_matrix" codegen_original.py
# EXPECTED: 0

# All matrix tests pass
python3 -m pytest tests/test_matrix.py -v
# EXPECTED: All pass

# Full suite passes
python3 -m pytest tests/ -q
# EXPECTED: 942 passed
```

## Success Criteria

- [ ] `codegen/matrix.py` has 50+ `ir.IRBuilder` uses
- [ ] `codegen/matrix.py` is ~700+ lines
- [ ] `codegen_original.py` reduced by ~609 lines
- [ ] Zero matrix methods in codegen_original.py
- [ ] All matrix tests pass
- [ ] All 942 tests pass
