# Remove `var`, Add `const`, Make Bare Identifiers Rebindable

**Priority:** Language Design Change
**Complexity:** Medium
**Breaking Change:** Yes - removes `var` keyword

---

## Motivation

The `var` keyword creates a linguistic vs operational mismatch:

- **Linguistic expectation**: `var` implies the *value* is mutable
- **Operational reality**: In Coex, `var` means the *binding* is rebindable, but the heap value itself is always immutable

This confuses programmers from other languages where `var x = [1,2,3]` followed by `x.append(4)` mutates `x` in place. In Coex, this returns a new list and the original is unchanged—the `var` only allows `x` to be rebound to the new list.

**Solution**: Remove `var` entirely. Use `const` for the less common case (non-rebindable bindings), and make bare identifiers rebindable by default.

---

## New Semantics

### Before (Current)

```coex
x = 5           # Immutable binding - cannot reassign
var y = 10      # Rebindable binding - can reassign
y = 20          # OK
x = 6           # ERROR
```

### After (New)

```coex
x = 5           # Rebindable binding - can reassign (default)
const y = 10    # Immutable binding - cannot reassign
x = 6           # OK
y = 20          # ERROR: cannot reassign const binding
```

### Move Semantics (Unchanged)

```coex
a := b          # Move: transfers ownership, invalidates b
const c := d    # Move into const binding
```

---

## Summary of Binding Keywords

| Syntax | Rebindable? | Ownership |
|--------|-------------|-----------|
| `x = expr` | Yes | Copy (deep copy for collections) |
| `x := expr` | Yes | Move (source invalidated) |
| `const x = expr` | No | Copy |
| `const x := expr` | No | Move |

---

## Implementation Steps

### Step 1: Grammar Changes (CoexLexer.g4)

Remove `VAR` token, add `CONST` token:

```antlr
// Remove this line:
// VAR: 'var';

// Add this line:
CONST: 'const';
```

### Step 2: Grammar Changes (CoexParser.g4)

#### Update Variable Declaration Rule

Current:
```antlr
varDeclStmt
    : VAR? IDENTIFIER (COLON type)? (ASSIGN | MOVE_ASSIGN) expression NEWLINE
    ;
```

New:
```antlr
varDeclStmt
    : CONST? IDENTIFIER (COLON type)? (ASSIGN | MOVE_ASSIGN) expression NEWLINE
    ;
```

#### Update Parameter Declarations (if applicable)

Parameters are already immutable by default (copies on entry), so no change needed.

#### Update For Loop Variables

For loop variables should remain rebindable within the loop:
```antlr
forStmt
    : FOR pattern IN expression NEWLINE block blockTerminator
    ;
```
No change needed—loop variables are implicitly rebindable.

### Step 3: AST Changes (ast_nodes.py)

Update `VarDecl` node:

```python
@dataclass
class VarDecl(Stmt):
    """Variable declaration: [const] name [: type] = expr"""
    name: str
    type_annotation: Optional[Type]
    initializer: Expr
    is_const: bool = False      # NEW: True if declared with 'const'
    is_move: bool = False       # True if := was used
```

Remove or rename the `is_mutable` field if it exists. The new `is_const` field is the inverse logic:
- `is_const=False` → rebindable (was `is_mutable=True`)
- `is_const=True` → not rebindable (was `is_mutable=False`)

### Step 4: AST Builder Changes (ast_builder.py)

Update the visitor for variable declarations:

```python
def visitVarDeclStmt(self, ctx):
    """Visit variable declaration: [const] name [: type] = expr"""
    # Check for const keyword
    is_const = ctx.CONST() is not None

    # Get variable name
    name = ctx.IDENTIFIER().getText()

    # Get optional type annotation
    type_annotation = None
    if ctx.type_():
        type_annotation = self.visit(ctx.type_())

    # Get initializer expression
    initializer = self.visit(ctx.expression())

    # Check for move assignment
    is_move = ctx.MOVE_ASSIGN() is not None

    return VarDecl(
        name=name,
        type_annotation=type_annotation,
        initializer=initializer,
        is_const=is_const,
        is_move=is_move
    )
```

### Step 5: Codegen Changes (codegen.py)

#### Update `_generate_var_decl()`

Replace the check for `is_mutable` with `is_const`:

**Current code** (~line 9176):
```python
def _generate_var_decl(self, stmt: VarDecl):
    # Check: var (mutable) declarations are prohibited in formulas
    if stmt.is_mutable and self.current_function is not None:
        if self.current_function.kind == FunctionKind.FORMULA:
            raise RuntimeError(
                f"Mutable variable 'var {stmt.name}' is not allowed in formula..."
            )
```

**New code**:
```python
def _generate_var_decl(self, stmt: VarDecl):
    # In formulas, all bindings must be const (no rebinding allowed)
    if not stmt.is_const and self.current_function is not None:
        if self.current_function.kind == FunctionKind.FORMULA:
            raise RuntimeError(
                f"Rebindable binding '{stmt.name}' is not allowed in formula "
                f"'{self.current_function.name}'. Use 'const {stmt.name} = ...' instead."
            )
```

#### Update Assignment Checking

In `_generate_assignment()`, add check for const bindings:

```python
def _generate_assignment(self, stmt: Assignment):
    # Check if target is a const binding
    if isinstance(stmt.target, Identifier):
        var_name = stmt.target.name
        if var_name in self.const_bindings:
            raise RuntimeError(
                f"Cannot reassign const binding '{var_name}'. "
                f"Remove 'const' from the declaration to make it rebindable."
            )

    # ... rest of existing implementation
```

Add tracking for const bindings:

```python
def __init__(self):
    # ... existing init ...
    self.const_bindings: set = set()  # Track const variable names
```

In `_generate_var_decl()`, register const bindings:

```python
def _generate_var_decl(self, stmt: VarDecl):
    # ... existing code ...

    # Track const bindings for reassignment checking
    if stmt.is_const:
        self.const_bindings.add(stmt.name)

    # ... rest of implementation
```

### Step 6: Update Formula Purity Check

Formulas should require all bindings to be `const`:

```python
def _generate_var_decl(self, stmt: VarDecl):
    # Formulas require const bindings for purity
    if self.current_function and self.current_function.kind == FunctionKind.FORMULA:
        if not stmt.is_const:
            raise RuntimeError(
                f"Formula '{self.current_function.name}' requires const bindings. "
                f"Use 'const {stmt.name} = ...' instead of '{stmt.name} = ...'."
            )
```

### Step 7: Update Error Messages

Search for all references to `var` in error messages and update:

```python
# Old:
"Mutable variable 'var {name}' is not allowed..."

# New:
"Rebindable binding '{name}' is not allowed..."
```

### Step 8: Update Tests

Update all test files that use `var`:

**Before:**
```coex
func main() -> int
    var x = 5
    x = 10
    print(x)
    return 0
~
```

**After:**
```coex
func main() -> int
    x = 5
    x = 10
    print(x)
    return 0
~
```

Tests that verify immutability should use `const`:

```coex
func main() -> int
    const x = 5
    x = 10        # Should error
    return 0
~
```

---

## Migration Guide

### For Existing Code

| Old Syntax | New Syntax | Meaning |
|------------|------------|---------|
| `x = 5` | `const x = 5` | Non-rebindable |
| `var x = 5` | `x = 5` | Rebindable |
| `var x := y` | `x := y` | Rebindable + move |

### Automated Migration

A simple regex replacement can update most code:

```bash
# Remove 'var ' prefix (note the space)
sed -i 's/\bvar //' *.coex

# No automated way to add 'const' for formerly non-var bindings
# Manual review needed for those cases
```

---

## Edge Cases

### Formula Functions

Formulas must use `const` for all bindings:

```coex
formula add(a: int, b: int) -> int
    const sum = a + b    # Required: const
    return sum
~

formula bad(a: int) -> int
    x = a + 1            # ERROR: rebindable not allowed in formula
    return x
~
```

### Loop Variables

For-loop iteration variables are implicitly rebindable (updated each iteration):

```coex
for i in 0..10
    print(i)    # i is rebound each iteration
~
```

This is fine—loop variables are managed by the loop construct, not user code.

### Shadowing

Both `const` and bare identifiers can shadow outer bindings:

```coex
x = 5
if true
    x = 10          # Shadows outer x (new binding, not reassignment)
    print(x)        # 10
~
print(x)            # 5 (outer x unchanged)
```

Wait—this is actually reassignment, not shadowing, if `x` is in scope. Need to clarify:

- **Reassignment**: `x = 10` where `x` already exists in current or outer scope
- **Shadowing**: Would require explicit syntax (not currently in Coex)

Current Coex behavior: `x = 10` reassigns if `x` exists, creates new if not.

With `const`:
- `const x = 10` always creates a new binding (shadows if name exists)
- `x = 10` reassigns if `x` exists (error if `x` is `const`)

---

## Test Cases

### Basic Rebinding

```python
def test_bare_identifier_rebindable(self, expect_output):
    expect_output('''
func main() -> int
    x = 5
    print(x)
    x = 10
    print(x)
    return 0
~
''', "5\n10\n")
```

### Const Cannot Be Reassigned

```python
def test_const_cannot_reassign(self, compile_coex):
    """Reassigning a const binding should fail."""
    with pytest.raises(Exception, match="Cannot reassign const"):
        compile_coex('''
func main() -> int
    const x = 5
    x = 10
    return 0
~
''')
```

### Formula Requires Const

```python
def test_formula_requires_const(self, compile_coex):
    """Formulas should reject rebindable bindings."""
    with pytest.raises(Exception, match="requires const"):
        compile_coex('''
formula bad() -> int
    x = 5
    return x
~

func main() -> int
    return bad()
~
''')


def test_formula_accepts_const(self, expect_output):
    """Formulas should accept const bindings."""
    expect_output('''
formula good() -> int
    const x = 5
    return x
~

func main() -> int
    print(good())
    return 0
~
''', "5\n")
```

### Move with Const

```python
def test_const_move(self, expect_output):
    expect_output('''
func main() -> int
    a = [1, 2, 3]
    const b := a
    print(b.len())
    return 0
~
''', "3\n")
```

### Const Move Cannot Reassign

```python
def test_const_move_no_reassign(self, compile_coex):
    with pytest.raises(Exception, match="Cannot reassign const"):
        compile_coex('''
func main() -> int
    a = [1, 2, 3]
    const b := a
    b = [4, 5, 6]
    return 0
~
''')
```

---

## Implementation Checklist

- [ ] Lexer: Remove `VAR` token from `CoexLexer.g4`
- [ ] Lexer: Add `CONST` token to `CoexLexer.g4`
- [ ] Parser: Update `varDeclStmt` rule in `CoexParser.g4`
- [ ] Parser: Regenerate with `antlr -Dlanguage=Python3 -visitor Coex.g4`
- [ ] AST: Rename `is_mutable` to `is_const` in `VarDecl` (invert logic)
- [ ] Builder: Update `visitVarDeclStmt` in `ast_builder.py`
- [ ] Codegen: Add `const_bindings` set to `CodeGenerator.__init__()`
- [ ] Codegen: Update `_generate_var_decl()` to track const bindings
- [ ] Codegen: Update `_generate_assignment()` to reject const reassignment
- [ ] Codegen: Update formula purity check for const requirement
- [ ] Codegen: Update all error messages referencing `var`
- [ ] Tests: Update all existing tests that use `var`
- [ ] Tests: Add new tests for `const` behavior
- [ ] Tests: Add tests for formula const requirement
- [ ] Docs: Update CLAUDE.md to reflect new syntax
- [ ] Docs: Update any specification documents

---

## Notes

- This is a breaking change—all existing `var` usage must be updated
- The semantic meaning is clearer: `const` = constant binding, bare = rebindable
- Aligns with programmer intuition about what "const" means
- Eliminates confusion about value mutability vs binding mutability
