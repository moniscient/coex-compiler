# BUG-056: Task Transform Uses Invalid Comparison Operators for icmp

## Status

**Fixed** (2026-01-28)

## Summary

The `_evaluate_expr_in_state_context` method in `task_transform.py` used incorrect comparison operator strings when generating LLVM icmp instructions. This caused a `ValueError` when task arguments contained comparison expressions like `x == y` or `x != y`.

## Severity

**Medium** - Affected task calls with comparison expressions as arguments.

## Reproduction

```coex
task dispatch(i: int, is_heavy: bool) -> int
    if is_heavy
        return 1
    else
        return 0
    ~
~

task coordinator() -> int
    total = 0
    for i in 0..10
        r := dispatch(i, i % 4 == 0)  # <-- Triggered bug
        total = total + r
    ~
    return total
~

func main() -> int
    print(coordinator())
    return 0
~
```

## Error Output (Before Fix)

```
Internal compiler error: invalid comparison 'eq' for icmp
ValueError: invalid comparison 'eq' for icmp
```

## Root Cause

In `task_transform.py:2362-2366`, the comparison operator mapping used LLVM IR predicate names:

```python
cmp_map = {
    BinaryOp.LT: 'slt', BinaryOp.GT: 'sgt',
    BinaryOp.LE: 'sle', BinaryOp.GE: 'sge',
    BinaryOp.EQ: 'eq', BinaryOp.NE: 'ne'  # Wrong!
}
```

However, llvmlite's `icmp_signed()` method expects human-readable operator strings.

## Resolution

Changed the mapping to use the correct operator format (matching `codegen/expressions.py`):

```python
cmp_map = {
    BinaryOp.LT: '<', BinaryOp.GT: '>',
    BinaryOp.LE: '<=', BinaryOp.GE: '>=',
    BinaryOp.EQ: '==', BinaryOp.NE: '!='
}
```

Also unified the mapping for both integer and float comparisons since both `icmp_signed` and `fcmp_ordered` use the same operator strings.

## Discovered

2026-01-28 during stress test development for scheduler worker pool.

## Related Files

- `task_transform.py:2360-2370` - Fixed location
- `codegen/expressions.py:251-262` - Reference implementation
