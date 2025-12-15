# Coex Array Stress Test Report

## Summary

Stress testing of List operations at increasing sizes. After fixing the depth > 1 bug in the persistent vector implementation, lists now work correctly up to **500,000+ elements**.

## Test Results

| Size | Status | Time |
|------|--------|------|
| 10 | PASS | < 1ms |
| 50 | PASS | < 1ms |
| 100 | PASS | < 1ms |
| 250 | PASS | < 1ms |
| 500 | PASS | < 1ms |
| 1,000 | PASS | < 1ms |
| 2,500 | PASS | < 1ms |
| 5,000 | PASS | < 1ms |
| 10,000 | PASS | < 1ms |
| 25,000 | PASS | < 1ms |
| 50,000 | PASS | < 1ms |
| 100,000 | PASS | ~43ms |
| 200,000 | PASS | ~37ms |
| 500,000 | PASS | ~82ms |
| 750,000+ | FAIL | Stack overflow in GC |

## Bug Fixed

### Root Cause (Fixed)

The persistent vector implementation in `codegen.py` originally had a hardcoded depth limit of 1, which only supported 1024 elements in the tree structure (~1056 total with tail).

### Fix Applied

Implemented full depth > 1 support with:

1. **Depth increase logic** (`codegen.py:521-561`): When `leaves_in_tree >= 32^depth`, create new root with old root at children[0] and increment depth.

2. **Path-copy insertion** (`codegen.py:563-737`): Proper multi-level tree traversal and node copying for inserting leaves at any position.

3. **GC heap increase** (`coex_gc.py:19`): Increased from 1MB to 256MB to support larger data structures.

### Capacity

The persistent vector now theoretically supports:
- Depth 1: 32 leaves × 32 elements = 1,024 elements
- Depth 2: 1,024 leaves × 32 elements = 32,768 elements
- Depth 3: 32,768 leaves × 32 elements = 1,048,576 elements
- Depth 4+: Even larger...

Practical limit is currently ~500,000 elements due to GC heap constraints (memory fragmentation and free-list traversal).

## Current Limitation

Lists above ~500,000 elements may cause stack overflow during garbage collection's free-list traversal. This is a GC implementation limitation, not a persistent vector limitation.

## Test Files

- `examples/stress_test_arrays.coex` - Main stress test (10 to 100k)
- `examples/stress_test_extreme.coex` - Extended test (100k to 1M)

## All Tests Passing

Full test suite: **402 passed**, 2 skipped, 1 xfailed, 2 xpassed
