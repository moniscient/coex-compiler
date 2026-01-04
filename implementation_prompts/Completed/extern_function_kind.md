# Implement `extern` Function Kind (Replaces `@clink`)

**Priority:** FFI Redesign
**Complexity:** Medium
**Breaking Change:** Yes - removes `@clink` annotation

---

## Overview

This implementation replaces the current `@clink("symbol")` annotation with a proper `extern` function kind. The `extern` kind provides a cleaner, more explicit FFI boundary with strict type constraints that maintain Coex's immutability guarantees.

### What's Being Replaced

**Current approach (`@clink`):**
```coex
@clink("fopen")
func file_open(path: string, mode: string) -> int
~
```

**New approach (`extern`):**
```coex
extern file_open(path: Array<byte>, mode: Array<byte>) -> int
~
```

---

## Specification

### The Extern Boundary

Extern functions use the C ABI for 64-bit systems. They accept Coex primitive types and `Array<byte>` as parameters, marshaled according to C calling conventions. The foreign code receives these values and operates entirely outside Coex's safety model.

**Parameter types allowed:**
- `int` (64-bit signed integer)
- `float` (64-bit double)
- `bool` (passed as 64-bit integer: 0 or 1)
- `byte` (8-bit unsigned)
- `Array<byte>` (passed as pointer to data + length)

**Return types allowed:**
- `int` (64-bit integer) - for results, error codes, or opaque handles
- `Array<byte>` - bulk data copied into Coex-managed memory

If foreign functions need different types (e.g., 32-bit int), write a C wrapper to handle the conversion.

### Data Crossing the Boundary

When an extern function returns `Array<byte>`, the data is **copied** into Coex-managed memory and becomes immutable. There is no borrowing, no shared references, no way for foreign code to mutate what Coex sees.

```coex
extern read_sensor(device_id: int) -> Array<byte>
~

func process_sensor()
    data = read_sensor(0)  # data is now immutable Coex array
    # process data using normal Coex operations
~
```

### Opaque Handles

Many foreign APIs use open/use/close patterns. Coex supports this through `int` returns representing opaque handles:

```coex
extern file_open(path: Array<byte>) -> int
~

extern file_read(handle: int, size: int) -> Array<byte>
~

extern file_close(handle: int) -> int
~

func read_config(path: string)
    handle = file_open(path.to_bytes())
    contents = file_read(handle, 4096)
    file_close(handle)
    return parse_config(contents)
~
```

The programmer is responsible for proper lifecycle management. This is inherently unsafe—extern functions operate outside Coex's guarantees.

### Calling Hierarchy

The complete function kind hierarchy with extern:

```
formula < task < func < extern
```

- **Formulas** can only call formulas
- **Tasks** can call formulas and tasks
- **Funcs** can call formulas, tasks, other funcs, and **extern functions**
- **Extern functions** are callable **only from func**

Extern cannot be called from formula or task because those kinds provide guarantees that extern functions cannot uphold.

---

## Implementation Steps

### Step 1: Grammar Changes (CoexLexer.g4)

Add `EXTERN` token:

```antlr
EXTERN: 'extern';
```

### Step 2: Grammar Changes (CoexParser.g4)

Update `functionKind` to include extern:

```antlr
functionKind
    : FORMULA
    | FUNC
    | TASK
    | EXTERN
    ;
```

Update `functionDecl` to handle extern's restricted signature:

```antlr
functionDecl
    : annotation* functionKind IDENTIFIER genericParams?
      LPAREN parameterList? RPAREN returnType? NEWLINE
      (block blockTerminator | blockTerminator)  // extern has no body, just terminator
    ;
```

Or create a separate rule for extern declarations:

```antlr
externDecl
    : EXTERN IDENTIFIER LPAREN parameterList? RPAREN returnType? blockTerminator
    ;
```

### Step 3: AST Changes (ast_nodes.py)

Update `FunctionKind` enum:

```python
class FunctionKind(Enum):
    FORMULA = auto()
    TASK = auto()
    FUNC = auto()
    EXTERN = auto()  # NEW
```

Extern functions have no body:

```python
@dataclass
class FunctionDecl:
    kind: FunctionKind
    name: str
    type_params: List[TypeParam]
    params: List[Parameter]
    return_type: Optional[Type]
    body: List[Stmt]  # Empty list for extern
    annotations: List[Annotation] = field(default_factory=list)
    is_extern: bool = False  # Or derive from kind == EXTERN
```

### Step 4: AST Builder Changes (ast_builder.py)

Handle extern function declarations:

```python
def visitFunctionDecl(self, ctx):
    kind = self._get_function_kind(ctx.functionKind())
    name = ctx.IDENTIFIER().getText()

    # ... params, return type ...

    # Extern functions have no body
    if kind == FunctionKind.EXTERN:
        body = []
    else:
        body = self.visit(ctx.block()) if ctx.block() else []

    return FunctionDecl(
        kind=kind,
        name=name,
        params=params,
        return_type=return_type,
        body=body,
        # ...
    )

def _get_function_kind(self, ctx):
    text = ctx.getText()
    if text == 'extern':
        return FunctionKind.EXTERN
    # ... existing cases ...
```

### Step 5: Semantic Validation (codegen.py or new validator)

Add validation for extern functions:

```python
def _validate_extern_function(self, func: FunctionDecl):
    """Validate extern function constraints."""

    # 1. Check parameter types
    allowed_param_types = {'int', 'float', 'bool', 'byte'}

    for param in func.params:
        if isinstance(param.type_annotation, PrimitiveType):
            if param.type_annotation.name not in allowed_param_types:
                raise RuntimeError(
                    f"Extern function '{func.name}' parameter '{param.name}' "
                    f"has invalid type '{param.type_annotation}'. "
                    f"Extern parameters must be int, float, bool, byte, or Array<byte>."
                )
        elif isinstance(param.type_annotation, ArrayType):
            elem = param.type_annotation.element_type
            if not (isinstance(elem, PrimitiveType) and elem.name == 'byte'):
                raise RuntimeError(
                    f"Extern function '{func.name}' parameter '{param.name}' "
                    f"has invalid array type. Only Array<byte> is allowed."
                )
        else:
            raise RuntimeError(
                f"Extern function '{func.name}' parameter '{param.name}' "
                f"has invalid type '{param.type_annotation}'. "
                f"Extern parameters must be int, float, bool, byte, or Array<byte>."
            )

    # 2. Check return type
    if func.return_type is None:
        pass  # void is allowed
    elif isinstance(func.return_type, PrimitiveType):
        if func.return_type.name != 'int':
            raise RuntimeError(
                f"Extern function '{func.name}' has invalid return type "
                f"'{func.return_type}'. Extern functions can only return int or Array<byte>."
            )
    elif isinstance(func.return_type, ArrayType):
        elem = func.return_type.element_type
        if not (isinstance(elem, PrimitiveType) and elem.name == 'byte'):
            raise RuntimeError(
                f"Extern function '{func.name}' has invalid return type. "
                f"Only Array<byte> is allowed for array returns."
            )
    else:
        raise RuntimeError(
            f"Extern function '{func.name}' has invalid return type "
            f"'{func.return_type}'. Extern functions can only return int or Array<byte>."
        )

    # 3. Ensure no body
    if func.body:
        raise RuntimeError(
            f"Extern function '{func.name}' cannot have a body. "
            f"Extern functions declare foreign interfaces only."
        )
```

### Step 6: Calling Hierarchy Validation

Add check when generating function calls:

```python
def _generate_call(self, expr: CallExpr) -> ir.Value:
    # ... resolve callee ...

    # Check calling hierarchy
    if callee_func.kind == FunctionKind.EXTERN:
        if self.current_function.kind != FunctionKind.FUNC:
            raise RuntimeError(
                f"Cannot call extern function '{callee_name}' from "
                f"{self.current_function.kind.name.lower()} '{self.current_function.name}'. "
                f"Extern functions can only be called from func."
            )

    # ... rest of call generation ...
```

### Step 7: Codegen - Extern Function Declaration

```python
def _declare_extern_function(self, func: FunctionDecl):
    """Declare an extern function (external symbol, no body)."""

    # Build C ABI parameter types
    param_types = []
    for param in func.params:
        param_types.append(self._get_extern_param_type(param.type_annotation))

    # Build C ABI return type
    if func.return_type is None:
        return_type = ir.VoidType()
    else:
        return_type = self._get_extern_return_type(func.return_type)

    # Create external function declaration
    func_type = ir.FunctionType(return_type, param_types)
    llvm_func = ir.Function(self.module, func_type, name=func.name)
    llvm_func.linkage = 'external'

    self.functions[func.name] = llvm_func
    self.extern_functions[func.name] = func  # Track for call-site marshaling


def _get_extern_param_type(self, coex_type: Type) -> ir.Type:
    """Get LLVM type for extern parameter (C ABI)."""
    if isinstance(coex_type, PrimitiveType):
        if coex_type.name == 'int':
            return ir.IntType(64)
        elif coex_type.name == 'float':
            return ir.DoubleType()
        elif coex_type.name == 'bool':
            return ir.IntType(64)  # Pass as i64 for C compatibility
        elif coex_type.name == 'byte':
            return ir.IntType(8)
    elif isinstance(coex_type, ArrayType):
        # Array<byte> passed as {i8*, i64} or two separate args
        # Option 1: Struct
        return ir.LiteralStructType([ir.IntType(8).as_pointer(), ir.IntType(64)])
        # Option 2: Flatten to two parameters (pointer, length)

    raise RuntimeError(f"Invalid extern parameter type: {coex_type}")


def _get_extern_return_type(self, coex_type: Type) -> ir.Type:
    """Get LLVM type for extern return (C ABI)."""
    if isinstance(coex_type, PrimitiveType) and coex_type.name == 'int':
        return ir.IntType(64)
    elif isinstance(coex_type, ArrayType):
        # Return as {i8*, i64} struct
        return ir.LiteralStructType([ir.IntType(8).as_pointer(), ir.IntType(64)])

    raise RuntimeError(f"Invalid extern return type: {coex_type}")
```

### Step 8: Codegen - Extern Call Marshaling

```python
def _generate_extern_call(self, func_name: str, args: List[ir.Value],
                          func_decl: FunctionDecl) -> ir.Value:
    """Generate call to extern function with proper marshaling."""

    llvm_func = self.functions[func_name]
    marshaled_args = []

    for i, (arg, param) in enumerate(zip(args, func_decl.params)):
        marshaled = self._marshal_to_extern(arg, param.type_annotation)
        marshaled_args.append(marshaled)

    result = self.builder.call(llvm_func, marshaled_args)

    # Unmarshal return value
    if func_decl.return_type:
        return self._unmarshal_from_extern(result, func_decl.return_type)

    return result


def _marshal_to_extern(self, value: ir.Value, coex_type: Type) -> ir.Value:
    """Marshal Coex value to C ABI type."""
    if isinstance(coex_type, PrimitiveType):
        if coex_type.name == 'bool':
            # Extend bool to i64
            return self.builder.zext(value, ir.IntType(64))
        return value
    elif isinstance(coex_type, ArrayType):
        # Extract pointer and length from Array struct
        data_ptr = self._get_array_data(value)
        length = self.builder.call(self.array_len, [value])
        # Pack into struct or pass as separate args based on ABI choice
        return self._pack_array_for_extern(data_ptr, length)

    return value


def _unmarshal_from_extern(self, value: ir.Value, coex_type: Type) -> ir.Value:
    """Unmarshal C ABI return to Coex value."""
    if isinstance(coex_type, PrimitiveType) and coex_type.name == 'int':
        return value
    elif isinstance(coex_type, ArrayType):
        # Create new Coex Array from returned {ptr, len}
        # COPY the data into GC-managed memory
        ptr = self.builder.extract_value(value, 0)
        length = self.builder.extract_value(value, 1)
        return self._copy_extern_bytes_to_array(ptr, length)

    return value


def _copy_extern_bytes_to_array(self, ptr: ir.Value, length: ir.Value) -> ir.Value:
    """Copy foreign memory into a new Coex Array<byte>."""
    i64 = ir.IntType(64)
    i32 = ir.IntType(32)

    # Allocate new array with given length
    elem_size = ir.Constant(i64, 1)  # byte = 1 byte
    new_array = self.builder.call(self.array_new, [length, elem_size])

    # Get destination pointer
    dest_ptr = self._get_array_data(new_array)

    # Copy data
    self.builder.call(self.memcpy, [dest_ptr, ptr, length])

    return new_array
```

### Step 9: Remove @clink Support

Remove the old `@clink` annotation handling:

1. Remove from `_get_clink_symbol()` method
2. Remove from `_generate_clink_wrapper()` method
3. Remove `clink_functions` tracking
4. Remove `_get_c_type()`, `_convert_to_c_type()`, `_convert_from_c_type()` if only used for @clink
5. Update or remove tests that use `@clink`

### Step 10: Update Built-in File Type

The current `File` extern type should be reimplemented using the new extern functions:

```coex
# Instead of extern type File with @clink methods:

extern fopen(path: Array<byte>, mode: Array<byte>) -> int
~

extern fread(handle: int, size: int) -> Array<byte>
~

extern fwrite(handle: int, data: Array<byte>) -> int
~

extern fclose(handle: int) -> int
~

# Coex wrapper for convenience
func file_read(path: string) -> Array<byte>
    handle = fopen(path.to_bytes(), "r".to_bytes())
    if handle < 0
        return []
    ~
    contents = fread(handle, 1048576)  # 1MB max
    fclose(handle)
    return contents
~
```

---

## C ABI Details

### Parameter Passing

| Coex Type | C Type | Notes |
|-----------|--------|-------|
| `int` | `int64_t` | Direct pass |
| `float` | `double` | Direct pass |
| `bool` | `int64_t` | 0 = false, 1 = true |
| `byte` | `uint8_t` | Direct pass |
| `Array<byte>` | `struct { uint8_t* data; int64_t len; }` | Or two separate args |

### Return Values

| Coex Type | C Type | Notes |
|-----------|--------|-------|
| `int` | `int64_t` | Direct return |
| `Array<byte>` | `struct { uint8_t* data; int64_t len; }` | Coex copies the data |
| (void) | `void` | No return value |

### Array<byte> ABI Options

**Option A: Struct passing**
```c
typedef struct {
    uint8_t* data;
    int64_t len;
} ByteArray;

ByteArray read_file(int64_t handle, int64_t size);
```

**Option B: Separate parameters (simpler C interface)**
```c
// Coex passes: read_file(handle, size, &out_ptr, &out_len)
void read_file(int64_t handle, int64_t size, uint8_t** out_ptr, int64_t* out_len);
```

Recommend Option A for returns, Option B for parameters if needed.

---

## Error Messages

All extern-related errors should include the warning from the spec:

```python
EXTERN_WARNING = (
    "Everything that happens with extern functions is your own damned fault. "
    "Extern functions operate entirely outside Coex's safety model."
)

def _extern_error(self, message: str) -> RuntimeError:
    return RuntimeError(f"{message}\n\nNote: {EXTERN_WARNING}")
```

---

## Test Cases

### Basic Extern Declaration

```python
def test_extern_declaration(self, compile_coex):
    """Extern functions should compile without body."""
    compile_coex('''
extern get_time() -> int
~

func main() -> int
    return 0
~
''')
```

### Extern Parameter Validation

```python
def test_extern_rejects_string_param(self, compile_coex):
    """Extern functions cannot accept string parameters."""
    with pytest.raises(Exception, match="invalid type"):
        compile_coex('''
extern bad_func(name: string) -> int
~

func main() -> int
    return 0
~
''')


def test_extern_accepts_array_byte(self, compile_coex):
    """Extern functions can accept Array<byte>."""
    compile_coex('''
extern good_func(data: Array<byte>) -> int
~

func main() -> int
    return 0
~
''')
```

### Extern Return Validation

```python
def test_extern_rejects_list_return(self, compile_coex):
    """Extern functions cannot return List."""
    with pytest.raises(Exception, match="invalid return type"):
        compile_coex('''
extern bad_func() -> [int]
~

func main() -> int
    return 0
~
''')
```

### Calling Hierarchy

```python
def test_formula_cannot_call_extern(self, compile_coex):
    """Formulas cannot call extern functions."""
    with pytest.raises(Exception, match="cannot call extern"):
        compile_coex('''
extern get_value() -> int
~

formula bad() -> int
    return get_value()
~

func main() -> int
    return bad()
~
''')


def test_task_cannot_call_extern(self, compile_coex):
    """Tasks cannot call extern functions."""
    with pytest.raises(Exception, match="cannot call extern"):
        compile_coex('''
extern get_value() -> int
~

task bad() -> int
    return get_value()
~

func main() -> int
    return 0
~
''')


def test_func_can_call_extern(self, compile_coex):
    """Funcs can call extern functions."""
    compile_coex('''
extern get_value() -> int
~

func good() -> int
    return get_value()
~

func main() -> int
    return good()
~
''')
```

### Extern With No Body

```python
def test_extern_rejects_body(self, compile_coex):
    """Extern functions cannot have a body."""
    with pytest.raises(Exception, match="cannot have a body"):
        compile_coex('''
extern bad_func() -> int
    return 42
~

func main() -> int
    return 0
~
''')
```

---

## Implementation Checklist

- [ ] Lexer: Add `EXTERN` token to `CoexLexer.g4`
- [ ] Parser: Add `EXTERN` to `functionKind` in `CoexParser.g4`
- [ ] Parser: Handle extern functions with no body
- [ ] Parser: Regenerate with `antlr -Dlanguage=Python3 -visitor Coex.g4`
- [ ] AST: Add `EXTERN` to `FunctionKind` enum
- [ ] Builder: Handle extern function declarations
- [ ] Validation: Add `_validate_extern_function()` for type constraints
- [ ] Validation: Add calling hierarchy check (only func can call extern)
- [ ] Codegen: Add `_declare_extern_function()` for external linkage
- [ ] Codegen: Add `_get_extern_param_type()` and `_get_extern_return_type()`
- [ ] Codegen: Add `_generate_extern_call()` with marshaling
- [ ] Codegen: Add `_marshal_to_extern()` for parameter conversion
- [ ] Codegen: Add `_unmarshal_from_extern()` for return conversion
- [ ] Codegen: Add `_copy_extern_bytes_to_array()` for Array<byte> returns
- [ ] Remove: Delete `@clink` annotation support
- [ ] Remove: Delete `_get_clink_symbol()`, `_generate_clink_wrapper()`
- [ ] Remove: Delete `_get_c_type()`, `_convert_to_c_type()`, `_convert_from_c_type()`
- [ ] Update: Reimplement File I/O using new extern functions
- [ ] Tests: Add extern declaration tests
- [ ] Tests: Add parameter/return type validation tests
- [ ] Tests: Add calling hierarchy tests
- [ ] Tests: Remove/update @clink tests
- [ ] Docs: Update CLAUDE.md

---

## Notes

- Extern is the only function kind with external linkage (no body, symbol resolved at link time)
- The data copy on `Array<byte>` return is intentional—maintains immutability guarantee
- No support for callbacks (passing Coex functions to C code)
- No support for complex C types—use C wrappers for those
- Error messages should emphasize that extern is "your own damned fault"
