# Remove Global Variable Support

**Priority:** Language Simplification
**Complexity:** Low
**Breaking Change:** Yes - removes global variable declarations

---

## Motivation

Global variables are antithetical to Coex's design principles:

1. **Immutability**: Coex guarantees heap immutability. Global mutable state creates hidden dependencies and makes reasoning about code difficult.

2. **Concurrency safety**: Global state is a primary source of data races. Removing it eliminates an entire class of bugs.

3. **Function purity**: Global variables allow functions to have hidden inputs/outputs, breaking the purity model.

4. **Testability**: Code with global state is harder to test in isolation.

The only shared mutable state in Coex should be through explicit atomic types passed as parameters, making sharing visible in function signatures.

---

## What's Being Removed

### Current (Allowed)

```coex
var counter = 0  # Module-level global

func increment()
    counter = counter + 1
~

func main() -> int
    increment()
    increment()
    print(counter)  # 2
    return 0
~
```

### After (Not Allowed)

```coex
counter = 0  # ERROR: Global variable declarations are not allowed

func main() -> int
    return 0
~
```

---

## Alternative Patterns

### Pass State Explicitly

```coex
func increment(counter: int) -> int
    return counter + 1
~

func main() -> int
    counter = 0
    counter = increment(counter)
    counter = increment(counter)
    print(counter)  # 2
    return 0
~
```

### Use Atomic Types for Shared State

```coex
func worker(counter: atomic_int)
    counter.increment()
~

func main() -> int
    counter: atomic_int = 0
    # Pass to concurrent tasks
    return counter.load()
~
```

### Module-Level Constants (Future Feature)

If needed, module-level constants could be added later:

```coex
const PI = 3.14159
const MAX_SIZE = 1024

func area(radius: float) -> float
    return PI * radius * radius
~
```

This is NOT part of this implementation—just noting the distinction between mutable globals (removed) and immutable constants (potential future feature).

---

## Implementation Steps

### Step 1: Grammar Changes (CoexParser.g4)

Remove `globalVarDecl` from the `declaration` rule:

```antlr
// Current:
declaration
    : functionDecl
    | typeDecl
    | traitDecl
    | matrixDecl
    | globalVarDecl    // REMOVE THIS
    ;

// After:
declaration
    : functionDecl
    | typeDecl
    | traitDecl
    | matrixDecl
    ;
```

Remove the `globalVarDecl` rule entirely:

```antlr
// REMOVE THIS ENTIRE RULE:
// globalVarDecl
//     : VAR IDENTIFIER (COLON type)? ASSIGN expression NEWLINE
//     ;
```

### Step 2: Regenerate Parser

```bash
antlr -Dlanguage=Python3 -visitor Coex.g4
```

### Step 3: AST Changes (ast_nodes.py)

Remove `GlobalVarDecl` class:

```python
# REMOVE THIS CLASS:
# @dataclass
# class GlobalVarDecl:
#     """Global variable declaration"""
#     name: str
#     type_annotation: Optional[Type]
#     initializer: Expr
```

Update `Program` class to remove globals field:

```python
@dataclass
class Program:
    """Root AST node"""
    imports: List[ImportDecl]
    replacements: List[ReplaceDecl]
    functions: List[FunctionDecl]
    types: List[TypeDecl]
    traits: List[TraitDecl]
    matrices: List[MatrixDecl]
    # REMOVE: globals: List[GlobalVarDecl]
```

### Step 4: AST Builder Changes (ast_builder.py)

Remove `visitGlobalVarDecl` method:

```python
# REMOVE THIS METHOD:
# def visitGlobalVarDecl(self, ctx):
#     ...
```

Update `visitProgram` to not collect globals:

```python
def visitProgram(self, ctx):
    imports = []
    replacements = []
    functions = []
    types = []
    traits = []
    matrices = []
    # REMOVE: globals = []

    for decl in ctx.declaration():
        result = self.visit(decl)
        if isinstance(result, FunctionDecl):
            functions.append(result)
        elif isinstance(result, TypeDecl):
            types.append(result)
        # ... etc
        # REMOVE: elif isinstance(result, GlobalVarDecl):
        #     globals.append(result)

    return Program(
        imports=imports,
        replacements=replacements,
        functions=functions,
        types=types,
        traits=traits,
        matrices=matrices,
        # REMOVE: globals=globals
    )
```

### Step 5: Codegen Changes (codegen.py)

#### Remove globals dictionary

In `__init__`:

```python
# REMOVE:
# self.globals: Dict[str, ir.GlobalVariable] = {}
```

#### Remove `_generate_global_var` method

```python
# REMOVE THIS ENTIRE METHOD:
# def _generate_global_var(self, decl: GlobalVarDecl):
#     ...
```

#### Remove global generation from `generate` method

```python
def generate(self, program: Program) -> str:
    # ... imports, types, etc ...

    # REMOVE:
    # for global_var in program.globals:
    #     self._generate_global_var(global_var)

    # ... functions ...
```

#### Update identifier lookup

In `_generate_identifier`:

```python
def _generate_identifier(self, expr: Identifier) -> ir.Value:
    name = expr.name

    # ... moved_vars check ...

    if name in self.locals:
        return self.builder.load(self.locals[name], name=name)
    # REMOVE:
    # elif name in self.globals:
    #     return self.builder.load(self.globals[name], name=name)
    elif name in self.functions:
        return self.functions[name]
    else:
        # ... field access in method context ...
```

#### Update assignment handling

In `_generate_assignment`:

```python
def _generate_assignment(self, stmt: Assignment):
    # ... existing code ...

    ptr = self._get_lvalue(stmt.target)
    if ptr is None and isinstance(stmt.target, Identifier):
        name = stmt.target.name
        # Create LOCAL variable only
        alloca = self.builder.alloca(value.type, name=name)
        self.locals[name] = alloca
        ptr = alloca
    # REMOVE any global handling
```

#### Update `_get_lvalue`

```python
def _get_lvalue(self, expr: Expr) -> Optional[ir.Value]:
    if isinstance(expr, Identifier):
        name = expr.name
        if name in self.locals:
            return self.locals[name]
        # REMOVE:
        # elif name in self.globals:
        #     return self.globals[name]
    # ...
```

### Step 6: Add Helpful Error Message

If someone tries to declare at module level, provide a helpful error:

In parser error handling or AST builder:

```python
def visitProgram(self, ctx):
    for child in ctx.children:
        # Check for statement-like constructs at module level
        if self._looks_like_variable_decl(child):
            raise SyntaxError(
                "Global variable declarations are not allowed in Coex.\n\n"
                "Coex does not support global mutable state. Instead:\n"
                "- Pass state explicitly as function parameters\n"
                "- Use atomic types for shared concurrent state\n"
                "- Define state in main() and pass to other functions\n\n"
                "Example:\n"
                "  func main() -> int\n"
                "      counter = 0\n"
                "      counter = process(counter)\n"
                "      return counter\n"
                "  ~"
            )
```

### Step 7: Update Tests

Remove any tests that use global variables:

```python
# REMOVE tests like:
# def test_global_variable(self, expect_output):
#     expect_output('''
# var x = 10
# func main() -> int
#     print(x)
#     return 0
# ~
# ''', "10\n")
```

Add test verifying globals are rejected:

```python
def test_global_variable_rejected(self, compile_coex):
    """Global variables should be rejected with helpful error."""
    with pytest.raises(Exception, match="Global variable declarations are not allowed"):
        compile_coex('''
x = 10

func main() -> int
    return x
~
''')
```

### Step 8: Update Documentation

Update `CLAUDE.md`:

```markdown
## Design Principles

### No Global Variables

Coex does not support global mutable state. All state must be:
- Declared within functions
- Passed explicitly as parameters
- Shared via atomic types (for concurrent access)

This ensures all data dependencies are visible in function signatures.
```

---

## Migration Guide

### Before

```coex
var config_value = 42

func get_config() -> int
    return config_value
~

func set_config(v: int)
    config_value = v
~
```

### After

```coex
func main() -> int
    config = 42
    config = process_with_config(config)
    print(config)
    return 0
~

func process_with_config(config: int) -> int
    # Use config, return updated value if needed
    return config + 1
~
```

---

## Implementation Checklist

- [ ] Grammar: Remove `globalVarDecl` from `declaration` rule
- [ ] Grammar: Remove `globalVarDecl` rule entirely
- [ ] Grammar: Regenerate parser
- [ ] AST: Remove `GlobalVarDecl` class
- [ ] AST: Remove `globals` field from `Program`
- [ ] Builder: Remove `visitGlobalVarDecl` method
- [ ] Builder: Update `visitProgram` to not collect globals
- [ ] Builder: Add helpful error for module-level declarations
- [ ] Codegen: Remove `self.globals` dictionary
- [ ] Codegen: Remove `_generate_global_var` method
- [ ] Codegen: Remove global generation loop
- [ ] Codegen: Update `_generate_identifier` to not check globals
- [ ] Codegen: Update `_generate_assignment` to not create globals
- [ ] Codegen: Update `_get_lvalue` to not check globals
- [ ] Tests: Remove tests using global variables
- [ ] Tests: Add test verifying globals are rejected
- [ ] Docs: Update CLAUDE.md

---

## Notes

- This is a simplification that removes code rather than adding it
- The error message should be educational, explaining the alternative patterns
- Module-level constants (immutable) could be a separate future feature
- Atomic types remain the mechanism for explicit shared state
