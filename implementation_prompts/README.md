# Coex Memory Model Implementation Prompts

This directory contains 10 session prompts for implementing the optimized memory model for Coex. Each prompt is designed to be self-contained and executable by a fresh Claude instance.

## Design Summary

### Collection Types & Sharing Strategy

| Type | Structure | Sharing | Assignment | Mutation Cost |
|------|-----------|---------|------------|---------------|
| List | Persistent Vector | Structural sharing | O(1) new root | O(log₃₂ n) path copy |
| Map | HAMT | Structural sharing | O(1) new root | O(log₃₂ n) path copy |
| Set | HAMT | Structural sharing | O(1) new root | O(log₃₂ n) path copy |
| Array | Contiguous | COW (atomic refcount) | O(1) refcount bump | O(n) if shared |
| String | Contiguous | COW (atomic refcount) | O(1) refcount bump | O(n) if shared |

### Assignment Operators

| Operator | Name | Behavior | Guarantee |
|----------|------|----------|-----------|
| `=` | Lazy assign | Share now, maybe copy later | None - cost at mutation if shared |
| `:=` | Eager assign | Move if possible, copy if necessary | Sole ownership, no future COW |

### Struct Layouts

**Array:**
```
| data* | refcount | len | cap | elem_size |
| i8*   | i64      | i64 | i64 | i64       |
```

**String:**
```
| data* | refcount | len | size | cap |
| i8*   | i64      | i64 | i64  | i64 |
```
- len = UTF-8 codepoint count
- size = byte count

## Session Order

Execute these sessions in order. Each builds on the previous.

### Phase 1: COW Foundation

1. **[SESSION_01_COW_ARRAY.md](SESSION_01_COW_ARRAY.md)** - Add COW to Array type
2. **[SESSION_02_COW_STRING.md](SESSION_02_COW_STRING.md)** - Add COW to String type
3. **[SESSION_03_MOVE_OPERATOR.md](SESSION_03_MOVE_OPERATOR.md)** - Implement `:=` operator

### Phase 2: Persistent Data Structures

4. **[SESSION_04_PERSISTENT_VECTOR_STRUCTURE.md](SESSION_04_PERSISTENT_VECTOR_STRUCTURE.md)** - List structure & reads
5. **[SESSION_05_PERSISTENT_VECTOR_MUTATIONS.md](SESSION_05_PERSISTENT_VECTOR_MUTATIONS.md)** - List mutations
6. **[SESSION_06_HAMT_MAP_STRUCTURE.md](SESSION_06_HAMT_MAP_STRUCTURE.md)** - Map structure & reads
7. **[SESSION_07_HAMT_MAP_MUTATIONS.md](SESSION_07_HAMT_MAP_MUTATIONS.md)** - Map mutations
8. **[SESSION_08_HAMT_SET.md](SESSION_08_HAMT_SET.md)** - Set implementation

### Phase 3: Integration

9. **[SESSION_09_TYPE_CONVERSIONS.md](SESSION_09_TYPE_CONVERSIONS.md)** - Collection conversions
10. **[SESSION_10_INTEGRATION.md](SESSION_10_INTEGRATION.md)** - Integration testing & polish

## Test-Driven Approach

Each session follows TDD:
1. Write failing tests FIRST
2. Implement until tests pass
3. Run full suite to verify no regressions

```bash
# Run tests for a specific session
python3 -m pytest tests/test_cow_array.py -v --tb=short

# Run full test suite
python3 -m pytest tests/ -v --tb=short
```

## Key Files

- `codegen.py` - Main implementation target (~6800 lines)
- `Coex.g4` - Grammar (modified for `:=` operator)
- `ast_nodes.py` - AST node definitions
- `ast_builder.py` - Parse tree to AST

## Expected Outcome

After all 10 sessions:

1. **Array/String**: COW with atomic refcount
2. **List**: Persistent Vector (32-way trie)
3. **Map**: HAMT (32-way trie with bitmap)
4. **Set**: HAMT (shared with Map)
5. **`:=` operator**: Move semantics with compile-time use-after-move detection
6. **Conversions**: List↔Array, Set↔Array, Map↔Zip

Value semantics preserved throughout:
- Assignment is always cheap O(1)
- Mutations are efficient O(log n) or O(n) COW
- No aliasing visible to programmer
- Safe for concurrent access
