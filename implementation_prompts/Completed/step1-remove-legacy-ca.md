# Step 1: Remove Legacy Cellular Automata Support

## Overview

This document specifies the removal of the current `matrix` keyword, cellular automata (CA) support, and `cell` keyword from the Coex compiler. This cleanup is required before implementing the new unified `Array<T>` type with `[[]]` relative indexing syntax (see `coex-array-type-spec.md`).

---

## Rationale

The current CA implementation has several limitations:
1. **Separate `matrix` declaration syntax** - Not a proper type, can't be passed to functions
2. **`cell` keyword coupling** - Only works inside matrix formula methods
3. **Double-buffering hardcoded** - Inflexible for different use cases
4. **No GPU support** - CPU-only with nested loops

The new design uses:
- Unified `Array<T>` type that works everywhere
- `[[]]` relative indexing syntax that's explicit and uniform
- GPU acceleration via Metal/CUDA compute shaders
- CPU fallback using Coex tasks

---

## Files to Delete

### 1. `codegen/matrix.py` (entire file - 545 lines)

The MatrixGenerator class is no longer needed. Delete the entire file.

---

## Files to Modify

### 2. Grammar: `Coex.g4`

**Remove these sections:**

```antlr
// DELETE: Lines ~169-197 - Matrix declaration rules
matrixDecl
    : MATRIX IDENTIFIER matrixDimensions matrixBody
    ;

matrixDimensions
    : LBRACKET expression COMMA expression RBRACKET
    ;

matrixBody
    : NL* (matrixClause NL*)* END
    ;

matrixClause
    : matrixTypeDecl
    | matrixInitDecl
    | matrixMethodDecl
    ;

matrixTypeDecl
    : TYPE COLON typeAnnotation
    ;

matrixInitDecl
    : INIT COLON expression
    ;

matrixMethodDecl
    : FORMULA IDENTIFIER LPAREN RPAREN ARROW typeAnnotation block
    ;
```

**Remove from `primaryExpr` rule:**
```antlr
// DELETE: CELL keyword and cell[dx,dy] syntax
| CELL
| CELL LBRACKET expression COMMA expression RBRACKET
```

**Remove lexer tokens:**
```antlr
// DELETE: Line ~692
MATRIX : 'matrix' ;

// DELETE: Line ~763
CELL : 'cell' ;
```

**Update comment at top of file:**
```antlr
// DELETE from line ~11:
"- Cellular automata (matrices) with parallel cell updates"
```

---

### 3. Grammar: `CoexLexer.g4` (if using split grammar)

**Remove:**
```antlr
MATRIX : 'matrix' ;
CELL : 'cell' ;
```

---

### 4. Grammar: `CoexParser.g4` (if using split grammar)

**Remove from declaration rule:**
```antlr
| matrixDecl
```

**Remove matrix rules (lines ~128-149):**
```antlr
matrixDecl : ...
matrixDimensions : ...
matrixBody : ...
matrixTypeDecl : ...
matrixInitDecl : ...
matrixMethodDecl : ...
```

**Remove from primaryExpr:**
```antlr
| CELL
| CELL LBRACKET expression COMMA expression RBRACKET
```

---

### 5. AST Nodes: `ast_nodes.py`

**Remove these classes:**

```python
# DELETE: Lines ~243-245
@dataclass
class CellExpr(Expr):
    """Reference to current cell value in matrix formula"""
    pass

# DELETE: Lines ~249-252
@dataclass
class CellIndexExpr(Expr):
    """Neighbor cell access: cell[dx, dy]"""
    dx: Expr
    dy: Expr

# DELETE: Lines ~810-817
@dataclass
class MatrixDecl:
    """Matrix declaration with dimensions and methods"""
    name: str
    width: Expr
    height: Expr
    element_type: Optional[Type]
    init_value: Optional[Expr]
    methods: List['FunctionDecl']
```

**Remove from Program class (line ~854):**
```python
# DELETE this field:
matrices: List[MatrixDecl] = field(default_factory=list)
```

---

### 6. AST Builder: `ast_builder.py`

**Remove these methods:**

```python
# DELETE: Lines ~365-388
def visit_matrix_decl(self, ctx) -> MatrixDecl:
    ...

# DELETE: Lines ~390-406
def visit_matrix_method_decl(self, ctx) -> FunctionDecl:
    ...
```

**Remove from `visit_primary_expr` (lines ~1164-1171):**
```python
# DELETE: cell keyword handling
if ctx.CELL():
    if ctx.expression():
        # cell[dx, dy] - neighbor access
        dx = self.visit(ctx.expression(0))
        dy = self.visit(ctx.expression(1))
        return CellIndexExpr(dx, dy)
    else:
        # bare 'cell' - current cell value
        return CellExpr()
```

**Remove matrix_decl from visit_declaration if present.**

---

### 7. Codegen Core: `codegen/core.py`

**Remove import (line ~52):**
```python
# DELETE:
from codegen.matrix import MatrixGenerator
```

**Remove instance variables (lines ~451-460):**
```python
# DELETE these lines:
self._matrix = MatrixGenerator(self)
self.matrix_decls: Dict[str, 'MatrixDecl'] = {}
self.matrix_structs: Dict[str, ir.Type] = {}
self.current_matrix: Optional[str] = None
self.current_cell_x: Optional[ir.Value] = None
self.current_cell_y: Optional[ir.Value] = None
```

**Remove matrix processing in `generate()` method (lines ~829-865):**
```python
# DELETE: Matrix registration loop
for matrix in program.matrices:
    self._matrix.register_matrix(matrix)

# DELETE: Matrix method declaration loop
for matrix in program.matrices:
    self._matrix.declare_matrix_methods(matrix)

# DELETE: Matrix method generation loop
for matrix in program.matrices:
    self._matrix.generate_matrix_methods(matrix)
```

**Remove cell access delegation methods (lines ~2564-2570):**
```python
# DELETE:
def _generate_cell_access(self):
    return self._expressions.generate_cell_access()

def _generate_cell_index_access(self, dx, dy):
    return self._expressions.generate_cell_index_access(dx, dy)
```

**Remove matrix type handling in `_generate_constructor()` (lines ~2762-2765):**
```python
# DELETE: Matrix-specific constructor logic
if type_name in self.matrix_structs:
    ...
```

**Remove matrix indexing special case (lines ~3386-3390):**
```python
# DELETE: Special handling for matrix[i, j] indexing
```

**Remove `_generate_matrix_return()` and related code (lines ~3863-3886):**
```python
# DELETE: Entire method and any comments
def _generate_matrix_return(self, value):
    ...
```

---

### 8. Codegen Expressions: `codegen/expressions.py`

**Remove imports (line ~25):**
```python
# DELETE:
from ast_nodes import CellExpr, CellIndexExpr
```

**Remove dispatch cases (lines ~128-134):**
```python
# DELETE:
elif isinstance(expr, CellExpr):
    return self.generate_cell_access()
elif isinstance(expr, CellIndexExpr):
    return self.generate_cell_index_access(expr.dx, expr.dy)
```

**Remove cell[i,j] special case (lines ~731-734):**
```python
# DELETE: Special handling for cell indexing
```

**Remove these methods entirely:**

```python
# DELETE: Lines ~936-955
def generate_cell_access(self):
    """Generate code to read current cell value from read buffer"""
    ...

# DELETE: Lines ~957-1020+
def generate_cell_index_access(self, dx_expr, dy_expr):
    """Generate code for cell[dx, dy] neighbor access"""
    ...
```

---

### 9. Codegen Statements: `codegen/statements.py`

**Remove matrix return handling (lines ~1128-1136):**
```python
# DELETE:
if cg.current_matrix is not None:
    # Matrix formula return - write to output buffer
    result_ptr = builder.load(cg.module.get_global('__matrix_result'))
    builder.store(value, result_ptr)
    builder.branch(cg.matrix_loop_inc_block)
    return
```

---

### 10. Codegen Flow Control: `codegen/flow_control.py`

**Remove matrix return handling (lines ~70-75):**
```python
# DELETE:
if cg.current_matrix is not None:
    cg._generate_matrix_return(value)
    return
```

---

### 11. Tests: `tests/test_advanced.py`

**Remove entire `TestMatrix` class (lines ~156-243):**
```python
# DELETE: Entire class (~88 lines)
class TestMatrix:
    def test_matrix_creation(self, expect_output):
        ...

    def test_matrix_get_set(self, expect_output):
        ...

    def test_matrix_initial_value(self, expect_output):
        ...

    def test_matrix_formula_simple(self, expect_output):
        ...

    def test_matrix_cell_access(self, expect_output):
        ...
```

---

## Regenerate Parser

After modifying the grammar files, regenerate the parser:

```bash
cd /Users/matthewstrebe/Desktop/Coex/coex-compiler
antlr -Dlanguage=Python3 -visitor Coex.g4
```

This will regenerate:
- `CoexLexer.py`
- `CoexParser.py`
- `CoexListener.py`
- `CoexVisitor.py`

---

## Verification Steps

After removal, run the test suite to verify nothing else breaks:

```bash
python3 -m pytest tests/ -v --tb=short
```

**Expected results:**
- All tests pass except those in the deleted `TestMatrix` class
- No import errors or missing attribute errors
- No grammar/parsing errors

**Verify clean removal:**
```bash
# Should return no results:
grep -r "matrix" --include="*.py" codegen/
grep -r "cell\[" --include="*.py" codegen/
grep -r "CellExpr\|CellIndexExpr" --include="*.py" .
grep -r "MatrixDecl\|MatrixGenerator" --include="*.py" .
```

---

## Summary Checklist

- [ ] Delete `codegen/matrix.py`
- [ ] Update `Coex.g4` (remove matrix rules, MATRIX/CELL tokens)
- [ ] Update `CoexLexer.g4` if using split grammar
- [ ] Update `CoexParser.g4` if using split grammar
- [ ] Update `ast_nodes.py` (remove CellExpr, CellIndexExpr, MatrixDecl, Program.matrices)
- [ ] Update `ast_builder.py` (remove visit_matrix_decl, visit_matrix_method_decl, cell handling)
- [ ] Update `codegen/core.py` (remove MatrixGenerator, matrix variables, matrix processing)
- [ ] Update `codegen/expressions.py` (remove cell imports, dispatch, methods)
- [ ] Update `codegen/statements.py` (remove matrix return handling)
- [ ] Update `codegen/flow_control.py` (remove matrix return handling)
- [ ] Delete `TestMatrix` class from `tests/test_advanced.py`
- [ ] Regenerate parser with `antlr -Dlanguage=Python3 -visitor Coex.g4`
- [ ] Run test suite to verify clean removal
- [ ] Commit changes with message: "Remove legacy matrix/CA/cell support (prep for Array<T>)"
