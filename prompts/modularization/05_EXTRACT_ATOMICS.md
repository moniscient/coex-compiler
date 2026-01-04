# Modularization Step 5: Extract Atomics Implementation

## Target Module: `codegen/atomics.py`

## Current State

- `codegen/atomics.py` exists (97 lines) but only contains delegation stubs
- Real implementations are in `codegen_original.py` lines 10030-10228 (~198 lines)
- All 7 methods delegate back to codegen_original.py

## Methods to Extract

| Line | Method |
|------|--------|
| 10030 | `_create_atomic_ref_type` |
| 10084 | `_implement_atomic_ref_new` |
| 10111 | `_implement_atomic_ref_load` |
| 10132 | `_implement_atomic_ref_store` |
| 10155 | `_implement_atomic_ref_cas` |
| 10188 | `_implement_atomic_ref_swap` |
| 10211 | `_register_atomic_ref_methods` |

## Instructions

### Step 1: Copy all atomic implementations to atomics.py

### Step 2: Replace delegation stubs with real implementations

### Step 3: Delete lines 10030-10228 from codegen_original.py

### Step 4: Run tests

```bash
python3 -m pytest tests/test_atomics.py -v
python3 -m pytest tests/ -q
```

## Verification Tests

```bash
# atomics.py should now have real implementations
grep -c "ir.IRBuilder" codegen/atomics.py
# BEFORE: 0
# AFTER:  ~20+

# atomics.py should be larger
wc -l codegen/atomics.py
# BEFORE: 97
# AFTER:  ~250+

# codegen_original.py should be smaller
wc -l codegen_original.py
# BEFORE: ~9312 (after step 4)
# AFTER:  ~9114 (reduced by ~198 lines)

# No atomic implementation methods in codegen_original.py
grep -c "def _implement_atomic_ref_\|def _create_atomic_ref_type\|def _register_atomic_ref_methods" codegen_original.py
# EXPECTED: 0

# No more delegation calls in atomics.py
grep -c "self.codegen._implement_atomic\|self.codegen._create_atomic" codegen/atomics.py
# EXPECTED: 0

# Full suite passes
python3 -m pytest tests/ -q
# EXPECTED: 942 passed
```

## Success Criteria

- [ ] `codegen/atomics.py` has 20+ `ir.IRBuilder` uses
- [ ] `codegen/atomics.py` is ~250+ lines
- [ ] `codegen_original.py` reduced by ~198 lines
- [ ] Zero atomic `_implement_*` methods in codegen_original.py
- [ ] Zero delegation calls in atomics.py
- [ ] All 942 tests pass
