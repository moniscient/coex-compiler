# Coex Slice Syntax Implementation

**Priority:** Feature Enhancement
**Complexity:** Medium
**Dependencies:** None (builds on existing index operator)

---

## Overview

Implement Python-like slice syntax for Coex collections. Slicing provides range-based access to sequential collections (List, Array, String) while maintaining Coex's value semantics—all operations return new collections rather than mutating in place.

---

## Syntax Summary

### Read Operations (via `.getrange()`)

| Syntax | Meaning | Method Call |
|--------|---------|-------------|
| `x[i]` | Single element | `.get(i)` (existing) |
| `x[start:end]` | Elements from start to end-1 | `.getrange(start, end)` |
| `x[start:]` | Elements from start to end | `.getrange(start, len)` |
| `x[:end]` | Elements from 0 to end-1 | `.getrange(0, end)` |
| `x[:-n]` | Last n elements | `.getrange(len-n, len)` |
| `x[-n]` | Single element from end | `.get(len-n)` |

### Write Operations (via `.setrange()`)

| Syntax | Meaning | Method Call |
|--------|---------|-------------|
| `x[i] = v` | Replace single element | `.set(i, v)` (existing) |
| `x[start:end] = src` | Replace range with source | `.setrange(start, end, src)` |
| `x[start:] = src` | Replace from start to end | `.setrange(start, len, src)` |
| `x[:end] = src` | Replace from 0 to end | `.setrange(0, end, src)` |
| `x[:-n] = src` | Replace last n elements | `.setrange(len-n, len, src)` |

**All write operations return new collections** (functional update), consistent with Coex's heap immutability.

---

## Implementation Steps

### Step 1: Grammar Changes (CoexParser.g4)

#### Current Grammar (line ~373)

```antlr
postfixOp
    : DOT IDENTIFIER                                    # memberAccessOp
    | DOT IDENTIFIER LPAREN argumentList? RPAREN        # methodCallOp
    | DOT IDENTIFIER genericArgs LPAREN argumentList? RPAREN # genericMethodCallOp
    | LBRACKET expressionList RBRACKET                  # indexOp
    | LPAREN argumentList? RPAREN                       # callOp
    ;
```

#### New Grammar

```antlr
postfixOp
    : DOT IDENTIFIER                                    # memberAccessOp
    | DOT IDENTIFIER LPAREN argumentList? RPAREN        # methodCallOp
    | DOT IDENTIFIER genericArgs LPAREN argumentList? RPAREN # genericMethodCallOp
    | LBRACKET sliceOrIndex RBRACKET                    # indexOrSliceOp
    | LPAREN argumentList? RPAREN                       # callOp
    ;

// Distinguish single index from slice
sliceOrIndex
    : sliceExpr                                         # sliceAccess
    | expression                                        # singleIndex
    | expression COMMA expressionList                   # multiIndex
    ;

// Slice expression: [start:end] with optional components
sliceExpr
    : expression? COLON expression?
    ;
```

#### Update Assignment Target (line ~471)

```antlr
indexAccess
    : IDENTIFIER (DOT IDENTIFIER)* LBRACKET sliceOrIndex RBRACKET
    ;
```

After grammar changes, regenerate parser:
```bash
antlr -Dlanguage=Python3 -visitor Coex.g4
```

---

### Step 2: AST Node Additions (ast_nodes.py)

Add after the existing `IndexExpr` class (~line 296):

```python
@dataclass
class SliceExpr(Expr):
    """Slice access: obj[start:end]

    Either start or end may be None (omitted).
    Negative values are relative to collection end.
    """
    object: Expr
    start: Optional[Expr]  # None means 0
    end: Optional[Expr]    # None means len


@dataclass
class SliceAssignment(Stmt):
    """Slice assignment: obj[start:end] = source

    Replaces elements in range [start, end) with elements from source.
    Returns a new collection (value semantics).
    """
    target: Expr           # The collection being sliced
    start: Optional[Expr]  # None means 0
    end: Optional[Expr]    # None means len
    value: Expr            # Source collection
    op: AssignOp           # Should be ASSIGN or MOVE_ASSIGN
```

---

### Step 3: AST Builder Updates (ast_builder.py)

Add visitor for the new grammar rules:

```python
def visitIndexOrSliceOp(self, ctx):
    """Handle both index and slice access."""
    # Get the object from the parent context (postfixExpr)
    obj = self.visit(ctx.parentCtx.getChild(0))

    slice_or_index = ctx.sliceOrIndex()

    # Check which alternative matched
    if hasattr(slice_or_index, 'sliceAccess') and slice_or_index.sliceAccess():
        # Slice: obj[start:end]
        slice_ctx = slice_or_index.sliceAccess().sliceExpr()

        # sliceExpr is: expression? COLON expression?
        children = list(slice_ctx.getChildren())
        start = None
        end = None

        # Parse based on COLON position
        colon_idx = next(i for i, c in enumerate(children)
                        if getattr(c, 'symbol', None) and c.symbol.text == ':')

        if colon_idx > 0:
            start = self.visit(children[0])
        if colon_idx < len(children) - 1:
            end = self.visit(children[colon_idx + 1])

        return SliceExpr(object=obj, start=start, end=end)

    elif hasattr(slice_or_index, 'singleIndex') and slice_or_index.singleIndex():
        # Single index: obj[i]
        index = self.visit(slice_or_index.singleIndex().expression())
        return IndexExpr(object=obj, indices=[index])

    elif hasattr(slice_or_index, 'multiIndex') and slice_or_index.multiIndex():
        # Multi-index: obj[i, j]
        exprs = slice_or_index.multiIndex()
        indices = [self.visit(exprs.expression())]
        indices.extend(self.visit(e) for e in exprs.expressionList().expression())
        return IndexExpr(object=obj, indices=indices)

    return obj
```

Update assignment visitor to detect slice assignment:

```python
def visitAssignment(self, ctx):
    """Handle assignment, including slice assignment."""
    target = self.visit(ctx.assignmentTarget())
    value = self.visit(ctx.expression())
    op = self._get_assign_op(ctx.assignOp())

    # Check if target is a slice expression
    if isinstance(target, SliceExpr):
        return SliceAssignment(
            target=target.object,
            start=target.start,
            end=target.end,
            value=value,
            op=op
        )

    return Assignment(target=target, value=value, op=op)
```

---

### Step 4: Codegen - Expression Handler (codegen.py)

Add to `_generate_expression()` (around line 11280):

```python
elif isinstance(expr, SliceExpr):
    return self._generate_slice(expr)
```

Implement `_generate_slice()`:

```python
def _generate_slice(self, expr: SliceExpr) -> ir.Value:
    """Generate code for slice read: obj[start:end]

    Calls .getrange(start, end) on the object.
    Handles negative indices and omitted bounds.
    """
    obj = self._generate_expression(expr.object)
    i64 = ir.IntType(64)

    # Get collection length for bounds normalization
    length = self._get_collection_length(obj)

    # Normalize start
    if expr.start is None:
        start = ir.Constant(i64, 0)
    else:
        start = self._generate_expression(expr.start)
        start = self._normalize_slice_index(start, length)

    # Normalize end
    if expr.end is None:
        end = length
    else:
        end = self._generate_expression(expr.end)
        end = self._normalize_slice_index(end, length)

    # Dispatch to .getrange() method
    type_name = self._get_type_name_from_ptr(obj.type)
    if type_name and type_name in self.type_methods:
        method_map = self.type_methods[type_name]
        if "getrange" in method_map:
            mangled = method_map["getrange"]
            func = self.functions[mangled]
            return self.builder.call(func, [obj, start, end])

    raise RuntimeError(f"Type '{type_name}' does not support slice access (no getrange method)")


def _normalize_slice_index(self, index: ir.Value, length: ir.Value) -> ir.Value:
    """Normalize a slice index, handling negative values.

    If index < 0, returns length + index (i.e., -1 becomes length-1).
    """
    i64 = ir.IntType(64)
    zero = ir.Constant(i64, 0)

    is_negative = self.builder.icmp_signed("<", index, zero)
    normalized = self.builder.add(length, index)

    return self.builder.select(is_negative, normalized, index)


def _get_collection_length(self, obj: ir.Value) -> ir.Value:
    """Get the length of a collection for slice bounds normalization."""
    type_name = self._get_type_name_from_ptr(obj.type)

    if type_name == "List":
        return self.builder.call(self.list_len, [obj])
    elif type_name == "Array":
        return self.builder.call(self.array_len, [obj])
    elif type_name == "String":
        return self.builder.call(self.string_len, [obj])
    elif type_name and type_name in self.type_methods:
        if "len" in self.type_methods[type_name]:
            mangled = self.type_methods[type_name]["len"]
            func = self.functions[mangled]
            return self.builder.call(func, [obj])

    return ir.Constant(ir.IntType(64), 0)
```

---

### Step 5: Codegen - Statement Handler (codegen.py)

Add to `_generate_statement()` (around line 9134):

```python
elif isinstance(stmt, SliceAssignment):
    self._generate_slice_assignment(stmt)
```

Implement `_generate_slice_assignment()`:

```python
def _generate_slice_assignment(self, stmt: SliceAssignment):
    """Generate code for slice assignment: obj[start:end] = source

    Calls .setrange(start, end, source) on the object.
    Returns a new collection (value semantics).
    """
    obj = self._generate_expression(stmt.target)
    source = self._generate_expression(stmt.value)
    i64 = ir.IntType(64)

    # Get collection length for bounds normalization
    length = self._get_collection_length(obj)

    # Normalize start
    if stmt.start is None:
        start = ir.Constant(i64, 0)
    else:
        start = self._generate_expression(stmt.start)
        start = self._normalize_slice_index(start, length)

    # Normalize end
    if stmt.end is None:
        end = length
    else:
        end = self._generate_expression(stmt.end)
        end = self._normalize_slice_index(end, length)

    # Dispatch to .setrange() method
    type_name = self._get_type_name_from_ptr(obj.type)
    if type_name and type_name in self.type_methods:
        method_map = self.type_methods[type_name]
        if "setrange" in method_map:
            mangled = method_map["setrange"]
            func = self.functions[mangled]
            new_collection = self.builder.call(func, [obj, start, end, source])

            # Store back to the variable (value semantics)
            if isinstance(stmt.target, Identifier):
                var_name = stmt.target.name
                if var_name in self.locals:
                    self.builder.store(new_collection, self.locals[var_name])
                elif var_name in self.globals:
                    self.builder.store(new_collection, self.globals[var_name])
            return

    raise RuntimeError(f"Type '{type_name}' does not support slice assignment (no setrange method)")
```

---

### Step 6: Runtime Methods - List (codegen.py)

Add to `_create_list_helpers()`:

```python
# list_getrange(list: List*, start: i64, end: i64) -> List*
list_getrange_ty = ir.FunctionType(list_ptr, [list_ptr, i64, i64])
self.list_getrange = ir.Function(self.module, list_getrange_ty, name="coex_list_getrange")

# list_setrange(list: List*, start: i64, end: i64, source: List*) -> List*
list_setrange_ty = ir.FunctionType(list_ptr, [list_ptr, i64, i64, list_ptr])
self.list_setrange = ir.Function(self.module, list_setrange_ty, name="coex_list_setrange")

self._implement_list_getrange()
self._implement_list_setrange()
```

Register in method table (in `_register_list_methods()`):

```python
self.type_methods["List"]["getrange"] = "coex_list_getrange"
self.type_methods["List"]["setrange"] = "coex_list_setrange"
```

#### Implement `_implement_list_getrange()`:

```python
def _implement_list_getrange(self):
    """Implement list_getrange: return new list with elements [start, end)."""
    func = self.list_getrange
    func.args[0].name = "list"
    func.args[1].name = "start"
    func.args[2].name = "end"

    entry = func.append_basic_block("entry")
    builder = ir.IRBuilder(entry)

    i64 = ir.IntType(64)
    i32 = ir.IntType(32)
    zero = ir.Constant(i64, 0)

    src_list = func.args[0]
    start = func.args[1]
    end = func.args[2]

    # Get source list length and element size
    src_len = builder.call(self.list_len, [src_list])
    elem_size_ptr = builder.gep(src_list, [ir.Constant(i32, 0), ir.Constant(i32, 5)], inbounds=True)
    elem_size = builder.load(elem_size_ptr)

    # Clamp start to [0, len]
    start_neg = builder.icmp_signed("<", start, zero)
    start_over = builder.icmp_signed(">", start, src_len)
    start_clamped = builder.select(start_neg, zero, builder.select(start_over, src_len, start))

    # Clamp end to [start, len]
    end_under = builder.icmp_signed("<", end, start_clamped)
    end_over = builder.icmp_signed(">", end, src_len)
    end_clamped = builder.select(end_under, start_clamped, builder.select(end_over, src_len, end))

    # Calculate result length
    result_len = builder.sub(end_clamped, start_clamped)

    # Create new empty list
    new_list = builder.call(self.list_new, [elem_size])

    # Loop: copy elements from start to end
    loop_header = func.append_basic_block("loop_header")
    loop_body = func.append_basic_block("loop_body")
    loop_exit = func.append_basic_block("loop_exit")

    i_ptr = builder.alloca(i64, name="i")
    builder.store(zero, i_ptr)
    result_ptr = builder.alloca(self.list_struct.as_pointer(), name="result")
    builder.store(new_list, result_ptr)
    builder.branch(loop_header)

    builder.position_at_end(loop_header)
    i = builder.load(i_ptr)
    cond = builder.icmp_signed("<", i, result_len)
    builder.cbranch(cond, loop_body, loop_exit)

    builder.position_at_end(loop_body)
    src_idx = builder.add(start_clamped, i)
    elem_ptr = builder.call(self.list_get, [src_list, src_idx])
    current_result = builder.load(result_ptr)
    new_result = builder.call(self.list_append, [current_result, elem_ptr, elem_size])
    builder.store(new_result, result_ptr)
    next_i = builder.add(i, ir.Constant(i64, 1))
    builder.store(next_i, i_ptr)
    builder.branch(loop_header)

    builder.position_at_end(loop_exit)
    final_result = builder.load(result_ptr)
    builder.ret(final_result)
```

#### Implement `_implement_list_setrange()`:

```python
def _implement_list_setrange(self):
    """Implement list_setrange: return new list with [start, end) replaced by source."""
    func = self.list_setrange
    func.args[0].name = "list"
    func.args[1].name = "start"
    func.args[2].name = "end"
    func.args[3].name = "source"

    entry = func.append_basic_block("entry")
    builder = ir.IRBuilder(entry)

    i64 = ir.IntType(64)
    i32 = ir.IntType(32)
    zero = ir.Constant(i64, 0)

    orig_list = func.args[0]
    start = func.args[1]
    end = func.args[2]
    source = func.args[3]

    # Get lengths and element size
    orig_len = builder.call(self.list_len, [orig_list])
    source_len = builder.call(self.list_len, [source])
    elem_size_ptr = builder.gep(orig_list, [ir.Constant(i32, 0), ir.Constant(i32, 5)], inbounds=True)
    elem_size = builder.load(elem_size_ptr)

    # Clamp bounds
    start_neg = builder.icmp_signed("<", start, zero)
    start_over = builder.icmp_signed(">", start, orig_len)
    start_clamped = builder.select(start_neg, zero, builder.select(start_over, orig_len, start))

    end_under = builder.icmp_signed("<", end, start_clamped)
    end_over = builder.icmp_signed(">", end, orig_len)
    end_clamped = builder.select(end_under, start_clamped, builder.select(end_over, orig_len, end))

    # Calculate how many elements to copy from source: min(end-start, source.len())
    range_len = builder.sub(end_clamped, start_clamped)
    copy_len = builder.select(
        builder.icmp_signed("<", source_len, range_len),
        source_len,
        range_len
    )

    # Create result list
    result = builder.call(self.list_new, [elem_size])
    result_ptr = builder.alloca(self.list_struct.as_pointer(), name="result")
    builder.store(result, result_ptr)

    # Phase 1: Copy elements [0, start) from original
    phase1_header = func.append_basic_block("phase1_header")
    phase1_body = func.append_basic_block("phase1_body")
    phase1_exit = func.append_basic_block("phase1_exit")

    i_ptr = builder.alloca(i64, name="i")
    builder.store(zero, i_ptr)
    builder.branch(phase1_header)

    builder.position_at_end(phase1_header)
    i = builder.load(i_ptr)
    cond = builder.icmp_signed("<", i, start_clamped)
    builder.cbranch(cond, phase1_body, phase1_exit)

    builder.position_at_end(phase1_body)
    elem_ptr = builder.call(self.list_get, [orig_list, i])
    current = builder.load(result_ptr)
    updated = builder.call(self.list_append, [current, elem_ptr, elem_size])
    builder.store(updated, result_ptr)
    builder.store(builder.add(i, ir.Constant(i64, 1)), i_ptr)
    builder.branch(phase1_header)

    # Phase 2: Copy elements [0, copy_len) from source
    builder.position_at_end(phase1_exit)
    phase2_header = func.append_basic_block("phase2_header")
    phase2_body = func.append_basic_block("phase2_body")
    phase2_exit = func.append_basic_block("phase2_exit")

    builder.store(zero, i_ptr)
    builder.branch(phase2_header)

    builder.position_at_end(phase2_header)
    i = builder.load(i_ptr)
    cond = builder.icmp_signed("<", i, copy_len)
    builder.cbranch(cond, phase2_body, phase2_exit)

    builder.position_at_end(phase2_body)
    elem_ptr = builder.call(self.list_get, [source, i])
    current = builder.load(result_ptr)
    updated = builder.call(self.list_append, [current, elem_ptr, elem_size])
    builder.store(updated, result_ptr)
    builder.store(builder.add(i, ir.Constant(i64, 1)), i_ptr)
    builder.branch(phase2_header)

    # Phase 3: Copy elements [end, orig_len) from original
    builder.position_at_end(phase2_exit)
    phase3_header = func.append_basic_block("phase3_header")
    phase3_body = func.append_basic_block("phase3_body")
    phase3_exit = func.append_basic_block("phase3_exit")

    builder.store(end_clamped, i_ptr)
    builder.branch(phase3_header)

    builder.position_at_end(phase3_header)
    i = builder.load(i_ptr)
    cond = builder.icmp_signed("<", i, orig_len)
    builder.cbranch(cond, phase3_body, phase3_exit)

    builder.position_at_end(phase3_body)
    elem_ptr = builder.call(self.list_get, [orig_list, i])
    current = builder.load(result_ptr)
    updated = builder.call(self.list_append, [current, elem_ptr, elem_size])
    builder.store(updated, result_ptr)
    builder.store(builder.add(i, ir.Constant(i64, 1)), i_ptr)
    builder.branch(phase3_header)

    builder.position_at_end(phase3_exit)
    final_result = builder.load(result_ptr)
    builder.ret(final_result)
```

---

### Step 7: Runtime Methods - Array (codegen.py)

Similar pattern to List. Add in `_create_array_helpers()`:

```python
# array_getrange(array: Array*, start: i64, end: i64) -> Array*
array_getrange_ty = ir.FunctionType(array_ptr, [array_ptr, i64, i64])
self.array_getrange = ir.Function(self.module, array_getrange_ty, name="coex_array_getrange")

# array_setrange(array: Array*, start: i64, end: i64, source: Array*) -> Array*
array_setrange_ty = ir.FunctionType(array_ptr, [array_ptr, i64, i64, array_ptr])
self.array_setrange = ir.Function(self.module, array_setrange_ty, name="coex_array_setrange")

self._implement_array_getrange()
self._implement_array_setrange()
```

Register methods and implement similarly to list versions.

---

### Step 8: Runtime Methods - String (codegen.py)

Add in `_create_string_type()` or separate helper:

```python
# string_getrange(str: String*, start: i64, end: i64) -> String*
string_getrange_ty = ir.FunctionType(string_ptr, [string_ptr, i64, i64])
self.string_getrange = ir.Function(self.module, string_getrange_ty, name="coex_string_getrange")

# string_setrange(str: String*, start: i64, end: i64, source: String*) -> String*
string_setrange_ty = ir.FunctionType(string_ptr, [string_ptr, i64, i64, string_ptr])
self.string_setrange = ir.Function(self.module, string_setrange_ty, name="coex_string_setrange")
```

Note: String slicing is byte-based, not UTF-8 codepoint-based.

---

## Semantics Details

### Negative Index Handling

Negative indices count from the end:
- `-1` → `len - 1` (last element)
- `-n` → `len - n`

```coex
var list = [0, 1, 2, 3, 4]

list[-1]      # 4 (last element)
list[-2:]     # [3, 4] (last 2 elements)
list[:-2]     # [0, 1, 2] (all but last 2)
list[-3:-1]   # [2, 3] (3rd from end to 2nd from end)
```

### Bounds Clamping

Out-of-bounds indices are clamped to valid range (no runtime errors):

```coex
var list = [0, 1, 2]

list[0:100]   # [0, 1, 2] - end clamped to 3
list[-100:2]  # [0, 1] - start clamped to 0
list[5:10]    # [] - both beyond end, empty result
```

### Slice Assignment Length Semantics

The replacement length is `min(end - start, source.len())`:

```coex
var list = [0, 1, 2, 3, 4]

# Range is 2 elements, source has 2 elements - exact replacement
list[1:3] = [10, 20]    # [0, 10, 20, 3, 4]

# Range is 3 elements, source has 2 elements - partial replacement
list[1:4] = [10, 20]    # [0, 10, 20, 4] - only 2 elements replaced

# Range is 2 elements, source has 5 elements - truncated source
list[1:3] = [10, 20, 30, 40, 50]  # [0, 10, 20, 3, 4] - only first 2 used
```

---

## Test Cases

Create `tests/test_slice.py`:

```python
class TestSliceSyntax:
    """Test slice syntax for collections."""

    def test_list_slice_basic(self, expect_output):
        expect_output('''
func main() -> int
    var list = [0, 1, 2, 3, 4]
    var slice = list[1:4]
    print(slice.len())
    print(slice.get(0))
    print(slice.get(2))
    return 0
~
''', "3\n1\n3\n")

    def test_list_slice_open_start(self, expect_output):
        expect_output('''
func main() -> int
    var list = [0, 1, 2, 3, 4]
    var slice = list[:3]
    print(slice.len())
    print(slice.get(0))
    print(slice.get(2))
    return 0
~
''', "3\n0\n2\n")

    def test_list_slice_open_end(self, expect_output):
        expect_output('''
func main() -> int
    var list = [0, 1, 2, 3, 4]
    var slice = list[2:]
    print(slice.len())
    print(slice.get(0))
    return 0
~
''', "3\n2\n")

    def test_list_slice_negative(self, expect_output):
        expect_output('''
func main() -> int
    var list = [0, 1, 2, 3, 4]
    var last2 = list[-2:]
    print(last2.len())
    print(last2.get(0))
    print(last2.get(1))
    return 0
~
''', "2\n3\n4\n")

    def test_list_slice_negative_end(self, expect_output):
        expect_output('''
func main() -> int
    var list = [0, 1, 2, 3, 4]
    var init = list[:-2]
    print(init.len())
    print(init.get(2))
    return 0
~
''', "3\n2\n")

    def test_list_setrange_basic(self, expect_output):
        expect_output('''
func main() -> int
    var list = [0, 1, 2, 3, 4]
    list[1:3] = [10, 20]
    print(list.get(0))
    print(list.get(1))
    print(list.get(2))
    print(list.get(3))
    return 0
~
''', "0\n10\n20\n3\n")

    def test_list_setrange_open_end(self, expect_output):
        expect_output('''
func main() -> int
    var list = [0, 1, 2, 3, 4]
    list[3:] = [30, 40]
    print(list.len())
    print(list.get(3))
    print(list.get(4))
    return 0
~
''', "5\n30\n40\n")

    def test_slice_value_semantics(self, expect_output):
        expect_output('''
func main() -> int
    var original = [0, 1, 2, 3, 4]
    var slice = original[1:4]
    slice[0:1] = [99]
    print(slice.get(0))
    print(original.get(1))
    return 0
~
''', "99\n1\n")

    def test_slice_bounds_clamping(self, expect_output):
        expect_output('''
func main() -> int
    var list = [0, 1, 2]
    var slice = list[0:100]
    print(slice.len())
    return 0
~
''', "3\n")

    def test_slice_empty_result(self, expect_output):
        expect_output('''
func main() -> int
    var list = [0, 1, 2]
    var slice = list[5:10]
    print(slice.len())
    return 0
~
''', "0\n")
```

---

## Implementation Checklist

- [ ] Grammar: Add `sliceExpr` and `sliceOrIndex` rules to `CoexParser.g4`
- [ ] Grammar: Regenerate parser with `antlr -Dlanguage=Python3 -visitor Coex.g4`
- [ ] AST: Add `SliceExpr` node to `ast_nodes.py`
- [ ] AST: Add `SliceAssignment` node to `ast_nodes.py`
- [ ] Builder: Add slice visitor to `ast_builder.py`
- [ ] Builder: Update assignment visitor for slice assignment
- [ ] Codegen: Add `_generate_slice()` method
- [ ] Codegen: Add `_normalize_slice_index()` helper
- [ ] Codegen: Add `_get_collection_length()` helper
- [ ] Codegen: Add `_generate_slice_assignment()` method
- [ ] Codegen: Add `SliceExpr` case to `_generate_expression()`
- [ ] Codegen: Add `SliceAssignment` case to `_generate_statement()`
- [ ] Runtime: Implement `coex_list_getrange()`
- [ ] Runtime: Implement `coex_list_setrange()`
- [ ] Runtime: Register `getrange`/`setrange` for List type
- [ ] Runtime: Implement `coex_array_getrange()`
- [ ] Runtime: Implement `coex_array_setrange()`
- [ ] Runtime: Register `getrange`/`setrange` for Array type
- [ ] Runtime: Implement `coex_string_getrange()`
- [ ] Runtime: Implement `coex_string_setrange()`
- [ ] Runtime: Register `getrange`/`setrange` for String type
- [ ] Tests: Create `tests/test_slice.py` with all test cases
- [ ] Tests: Verify all tests pass

---

## Notes

- Step syntax `[start:end:step]` is NOT included in this implementation
- String slicing is byte-based, not UTF-8 codepoint-aware
- All slice operations maintain value semantics (return new collections)
