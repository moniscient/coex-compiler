# Modularization Step 1: Extract String Implementation

## Target Module: `codegen/strings.py`

## Current State

- `codegen/strings.py` exists (518 lines) but only contains delegation stubs
- Real implementations are in `codegen_original.py` lines 2602-5055 (~2453 lines)
- All 30 `_implement_string_*` methods delegate back to codegen_original.py

## Methods to Extract

From `codegen_original.py`, move these methods to `codegen/strings.py`:

| Line | Method | Lines of Code |
|------|--------|---------------|
| 2602 | `_create_string_type` | ~200 |
| 2802 | `_implement_string_data` | ~33 |
| 2835 | `_implement_string_new` | ~57 |
| 2892 | `_implement_string_from_literal` | ~100 |
| 2992 | `_implement_string_len` | ~17 |
| 3009 | `_implement_string_size` | ~21 |
| 3030 | `_implement_string_byte_size` | ~17 |
| 3047 | `_implement_string_get` | ~48 |
| 3095 | `_implement_string_slice` | ~124 |
| 3219 | `_implement_string_concat` | ~87 |
| 3306 | `_implement_string_join_list` | ~212 |
| 3518 | `_implement_string_eq` | ~77 |
| 3595 | `_implement_string_contains` | ~107 |
| 3702 | `_implement_string_print` | ~35 |
| 3737 | `_implement_string_debug` | ~35 |
| 3772 | `_implement_string_copy` | ~16 |
| 3788 | `_implement_string_deep_copy` | ~71 |
| 3859 | `_implement_string_hash` | ~84 |
| 3943 | `_implement_string_setrange` | ~123 |
| 4066 | `_implement_string_to_int` | ~79 |
| 4145 | `_implement_string_to_float` | ~64 |
| 4209 | `_implement_string_to_int_hex` | ~65 |
| 4274 | `_implement_string_from_int` | ~33 |
| 4307 | `_implement_string_from_float` | ~34 |
| 4341 | `_implement_string_from_bool` | ~40 |
| 4381 | `_implement_string_from_hex` | ~33 |
| 4414 | `_implement_string_from_bytes` | ~108 |
| 4522 | `_implement_string_to_bytes` | ~86 |
| 4608 | `_implement_string_split` | ~160 |
| 4768 | `_implement_string_validjson` | ~32 |
| 5001 | `_register_string_methods` | ~55 |

## Instructions

### Step 1: Copy implementations to strings.py

For each method listed above:
1. Copy the method body from `codegen_original.py`
2. Replace `self.` references with appropriate property accessors
3. The class already has property accessors for common attributes

Example transformation:
```python
# In codegen_original.py:
def _implement_string_len(self):
    func = self.string_len
    entry = func.append_basic_block("entry")
    builder = ir.IRBuilder(entry)
    ...

# In strings.py (use existing properties):
def _implement_string_len(self):
    func = self.string_len  # Uses @property accessor
    entry = func.append_basic_block("entry")
    builder = ir.IRBuilder(entry)
    ...
```

### Step 2: Update delegation stubs to be real implementations

Replace the delegation stubs like:
```python
def _implement_string_len(self):
    self.codegen._implement_string_len()
```

With the actual implementation code.

### Step 3: Delete methods from codegen_original.py

After copying, delete lines 2602-5055 from `codegen_original.py`.

### Step 4: Update codegen_original.py references

The `_create_string_type` call in codegen_original.py should already use:
```python
self._strings.create_string_type()
```

Verify this is the case and that `create_string_type` in strings.py calls the local implementations.

### Step 5: Run tests

```bash
python3 -m pytest tests/test_strings.py tests/test_slices.py -v
python3 -m pytest tests/ -q  # Full suite
```

## Verification Tests

```bash
# strings.py should now have real implementations
grep -c "ir.IRBuilder" codegen/strings.py
# BEFORE: 0
# AFTER:  ~150+

# strings.py should be much larger
wc -l codegen/strings.py
# BEFORE: 518
# AFTER:  ~2500+

# codegen_original.py should be smaller
wc -l codegen_original.py
# BEFORE: ~18920 (after cleanup step 0)
# AFTER:  ~16467 (reduced by ~2453 lines)

# No string implementation methods in codegen_original.py
grep -c "def _implement_string_\|def _create_string_type\|def _register_string_methods" codegen_original.py
# EXPECTED: 0

# No more delegation calls in strings.py
grep -c "self.codegen._implement_string" codegen/strings.py
# EXPECTED: 0

# All string tests pass
python3 -m pytest tests/test_strings.py tests/test_slices.py -v
# EXPECTED: All pass

# Full suite passes
python3 -m pytest tests/ -q
# EXPECTED: 942 passed
```

## Success Criteria

- [ ] `codegen/strings.py` has 150+ `ir.IRBuilder` uses
- [ ] `codegen/strings.py` is ~2500+ lines
- [ ] `codegen_original.py` reduced by ~2453 lines
- [ ] Zero `_implement_string_*` methods in codegen_original.py
- [ ] Zero delegation calls (`self.codegen._implement_string`) in strings.py
- [ ] All string/slice tests pass
- [ ] All 942 tests pass

## Common Issues

1. **Missing property accessors**: If a method uses `self.something` that doesn't have a property accessor in StringGenerator, add one.

2. **Circular imports**: Use `TYPE_CHECKING` pattern for type hints:
   ```python
   from typing import TYPE_CHECKING
   if TYPE_CHECKING:
       from codegen_original import CodeGenerator
   ```

3. **Module-level functions**: Some helper functions might need to move too. Check for any functions called only by string methods.
