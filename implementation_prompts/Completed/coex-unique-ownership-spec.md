# Coex Unique Ownership: Specification and Implementation

## 1. Overview

Coex is a value-semantics language where heap data is immutable by default. The uniqueness analysis optimization (implemented separately) enables in-place mutation when the compiler can prove a binding has sole ownership. The `unique` keyword extends this by allowing programmers to *declare* sole ownership, guaranteeing the optimization applies and enabling the compiler to enforce the constraint.

This document specifies the `unique` ownership system for Coex, including syntax, semantics, compiler enforcement, and code generation.

### 1.1 Goals

1. **Guaranteed optimization:** Update operations on unique bindings are always performed in-place
2. **Compile-time enforcement:** Aliasing violations are caught at compile time, not runtime
3. **Explicit control:** Programmers choose when to use unique ownership via the `unique` keyword
4. **Clear semantics:** Move vs. copy is syntactically distinct (`=` vs. `:=`)
5. **Incremental adoption:** Code without `unique` behaves exactly as before

### 1.2 Initial Scope

The first implementation supports `unique` on:
- `Array<T>` types
- `String` type

HAMT-based types (`Set<T>`, `Map<K,V>`, `List<T>`) will be added in a future phase once their internal structure supports the required in-place mutations.

## 2. Syntax

### 2.1 Unique Binding Declaration

The `unique` keyword precedes the binding name in variable declarations:

```
unique <name> : <Type> = <expr>
unique <name> = <expr>
```

Examples:
```coex
unique buffer: Array<int> = []
unique name: String = "hello"
unique data = load_array(filename)  # Type inferred
```

### 2.2 Unique Function Parameters

Function parameters can be declared unique to receive ownership:

```
func <name>(<params>) -> <ReturnType>
    where <param> can be:
        <name> : <Type>           # Standard parameter
        unique <name> : <Type>    # Unique parameter (receives ownership)
```

Examples:
```coex
func process(unique data: Array<int>) -> int
    # data is unique here; caller's binding is invalidated
    for i in 0..data.len()
        data = data.set_at(i, data.get(i) * 2)  # In-place guaranteed
    ~
    return data.len()
~

func consume(unique buffer: String) -> void
    print(buffer)
~
```

### 2.3 Unique Return Types

Functions can return unique values:

```
func <name>(<params>) -> unique <Type>
```

Examples:
```coex
func make_buffer(size: int) -> unique Array<int>
    unique result: Array<int> = []
    for i in 0..size
        result = result.append(0)  # In-place guaranteed
    ~
    return result
~
```

### 2.4 Borrowed Parameters

Functions can borrow unique values without taking ownership using the `borrow` keyword:

```
func <name>(borrow <name> : <Type>) -> <ReturnType>
```

Examples:
```coex
func sum(borrow arr: Array<int>) -> int
    # arr is borrowed; caller retains ownership
    # Cannot mutate or move arr, only read
    total = 0
    for i in 0..arr.len()
        total = total + arr.get(i)
    ~
    return total
~

unique data: Array<int> = [1, 2, 3]
result = sum(data)   # Borrow: data still valid and unique
data = data.append(4)  # Still works
```

### 2.5 Copy Operator

The `:=` operator performs an explicit copy:

```
<target> := <source>
unique <target> := <source>
```

Examples:
```coex
unique arr: Array<int> = [1, 2, 3]
copy := arr              # copy is a non-unique copy of arr
unique other := arr      # other is an independent unique copy
# arr is still valid and unique
```

## 3. Semantics

### 3.1 Ownership Model

A unique binding has *sole ownership* of its value. This means:

1. No other binding references the same underlying storage
2. The value can be safely mutated in place
3. When the binding goes out of scope, the value can be deallocated (subject to GC)

### 3.2 Move Semantics

Assignment with `=` performs a move. The source binding is invalidated:

```coex
unique arr: Array<int> = [1, 2, 3]
other = arr       # Move: ownership transfers to 'other'
print(arr)        # Compile error: 'arr' was moved
```

After a move:
- The source binding is in an *invalid* state
- Any use of the source binding is a compile error
- The destination binding owns the value

### 3.3 Copy Semantics

Assignment with `:=` performs an explicit deep copy:

```coex
unique arr: Array<int> = [1, 2, 3]
other := arr      # Copy: 'other' is independent
print(arr)        # Valid: arr still owns original
print(other)      # Valid: other owns the copy
```

After a copy:
- The source binding remains valid and unique
- The destination binding owns a fresh, independent copy
- No aliasing exists between source and destination

### 3.4 Function Parameter Passing

#### 3.4.1 Passing to Unique Parameter

Ownership transfers to the callee:

```coex
func consume(unique data: Array<int>) -> void
    # ...
~

unique arr: Array<int> = [1, 2, 3]
consume(arr)      # Move: arr invalid after call
print(arr)        # Compile error: 'arr' was moved
```

#### 3.4.2 Passing to Non-Unique Parameter

Ownership transfers (move) and uniqueness is lost. The compiler emits a warning:

```coex
func process(data: Array<int>) -> void
    # data is not unique; standard semantics
~

unique arr: Array<int> = [1, 2, 3]
process(arr)      # Move + warning: uniqueness lost
#@ [UNIQUE] Unique binding 'arr' passed to non-unique parameter; uniqueness lost
print(arr)        # Compile error: 'arr' was moved
```

#### 3.4.3 Passing to Borrowed Parameter

No ownership transfer; the callee borrows temporarily:

```coex
func inspect(borrow data: Array<int>) -> int
    return data.len()
~

unique arr: Array<int> = [1, 2, 3]
len = inspect(arr)  # Borrow: arr still valid
arr = arr.append(4) # Valid: arr still unique
```

### 3.5 Return Values

Returning a unique value transfers ownership to the caller:

```coex
func make() -> unique Array<int>
    unique result: Array<int> = [1, 2, 3]
    return result   # Ownership transfers to caller
~

unique arr = make()  # arr is unique
other = make()       # other is unique (unique return to non-unique binding is fine)
```

A function returning `unique` guarantees the returned value has sole ownership—no other references exist.

### 3.6 Type Conversion

Type conversion creates a copy. The source remains valid:

```coex
unique arr: Array<int> = [1, 2, 3]
list: List<int> = arr    # Conversion copies data; arr still valid and unique
set: Set<int> = arr      # Conversion copies data; arr still valid and unique
```

This is because conversion constructs a new value of a different type from the source's contents. No aliasing is possible between different types.

### 3.7 Storing in Data Structures

Storing a unique in a collection of compatible type moves it and drops uniqueness:

```coex
unique arr: Array<int> = [1, 2, 3]
container: List<Array<int>> = [arr]  # Move: arr invalid, element is shared
print(arr)                           # Compile error: 'arr' was moved
```

The stored value becomes shared because:
1. The collection holds a reference
2. The element can be retrieved multiple times
3. Multiple retrievals would create aliases

### 3.8 Borrowing Rules

A borrow allows temporary read access without ownership transfer:

1. **Read-only access:** Borrowed values can be read but not mutated
2. **No moving:** Cannot move out of a borrowed value
3. **Scope-limited:** The borrow lasts for the duration of the function call
4. **Original preserved:** The lender's unique binding remains valid after the borrow ends

```coex
func valid_borrow(borrow arr: Array<int>) -> int
    return arr.len()                    # Read: OK
    # arr = arr.append(1)               # Mutate: Compile error
    # other = arr                       # Move: Compile error
~

func invalid_borrow(borrow arr: Array<int>) -> Array<int>
    return arr                          # Compile error: cannot move borrowed value
~
```

### 3.9 Control Flow

#### 3.9.1 Conditionals

A unique must be moved on all paths or no paths:

```coex
unique arr: Array<int> = [1, 2, 3]

# Valid: moved on all paths
if condition
    consume(arr)
else
    consume(arr)
~
# arr is invalid here (moved on all paths)

# Valid: not moved on any path
if condition
    x = arr.len()
else
    y = arr.get(0)
~
arr = arr.append(4)  # Valid: arr not moved

# Invalid: moved on only one path
if condition
    consume(arr)
~
print(arr)  # Compile error: 'arr' potentially moved
```

#### 3.9.2 Loops

Rebinding is allowed; moving to another binding inside a loop is not:

```coex
unique arr: Array<int> = [1, 2, 3]

# Valid: rebinding in loop
while condition
    arr = arr.append(x)  # Rebind: OK, arr remains unique
~

# Invalid: move inside loop
while condition
    other = arr          # Compile error: 'arr' moved, invalid on next iteration
~
```

#### 3.9.3 For Loops

The iteration variable in a for loop is not unique (collection retains reference):

```coex
unique arr: Array<int> = [1, 2, 3]
for elem in arr       # elem is NOT unique; arr still owns elements
    print(elem)
~
arr = arr.append(4)   # Valid: arr still unique (for loop only borrowed)
```

### 3.10 Partial Moves

Not supported. Moving any part of a structure moves the entire structure:

```coex
type State:
    unique buffer: Array<int>
    count: int
~

func process(s: State) -> void
    consume(s.buffer)   # Moves entire 's', not just buffer
    print(s.count)      # Compile error: 's' was moved
~
```

## 4. Compiler Implementation

### 4.1 AST Extensions

Add new AST node variants and fields:

```python
@dataclass
class UniqueModifier:
    """Marker for unique ownership"""
    pass

@dataclass
class BorrowModifier:
    """Marker for borrowed parameter"""
    pass

@dataclass
class Parameter:
    name: str
    type: Type
    unique: bool = False      # True if 'unique' modifier present
    borrow: bool = False      # True if 'borrow' modifier present

@dataclass
class VariableDecl:
    name: str
    type: Optional[Type]
    initializer: Expr
    unique: bool = False      # True if 'unique' modifier present

@dataclass 
class Assignment:
    target: str
    value: Expr
    is_copy: bool = False     # True if ':=' operator used

@dataclass
class FunctionDecl:
    name: str
    params: List[Parameter]
    return_type: Type
    return_unique: bool = False  # True if return type is unique
    body: List[Statement]
```

### 4.2 Parser Extensions

Extend the parser to recognize:

1. `unique` keyword before variable names in declarations
2. `unique` keyword before parameter names
3. `unique` keyword before return types
4. `borrow` keyword before parameter names
5. `:=` as a distinct assignment operator

Grammar additions (ANTLR-style):

```antlr
variableDecl
    : UNIQUE? IDENTIFIER (COLON type)? EQUALS expression
    ;

parameter
    : (UNIQUE | BORROW)? IDENTIFIER COLON type
    ;

returnType
    : UNIQUE? type
    ;

assignment
    : IDENTIFIER (EQUALS | COLON_EQUALS) expression
    ;

UNIQUE : 'unique' ;
BORROW : 'borrow' ;
COLON_EQUALS : ':=' ;
```

### 4.3 Ownership Tracking

The compiler maintains ownership state for each binding:

```python
class OwnershipState(Enum):
    VALID = "valid"           # Binding owns its value
    MOVED = "moved"           # Value was moved; binding is invalid
    BORROWED = "borrowed"     # Temporarily borrowed; will be valid after borrow ends

@dataclass
class BindingInfo:
    name: str
    type: Type
    is_unique: bool
    ownership: OwnershipState
    moved_at: Optional[SourceLocation]  # Where the move occurred (for error messages)
```

### 4.4 Ownership Analysis Pass

A new compiler pass tracks ownership through the program:

```python
class OwnershipAnalyzer(ASTVisitor):
    def __init__(self):
        self.bindings: Dict[str, BindingInfo] = {}
        self.errors: List[OwnershipError] = []
        self.warnings: List[OwnershipWarning] = []
    
    def visit_variable_decl(self, node: VariableDecl):
        # Register new binding
        self.bindings[node.name] = BindingInfo(
            name=node.name,
            type=node.type,
            is_unique=node.unique,
            ownership=OwnershipState.VALID,
            moved_at=None
        )
        # Analyze initializer
        self.visit(node.initializer)
    
    def visit_identifier(self, node: Identifier):
        # Check if binding is valid
        info = self.bindings.get(node.name)
        if info and info.ownership == OwnershipState.MOVED:
            self.errors.append(OwnershipError(
                f"Use of moved binding '{node.name}'",
                node.location,
                f"'{node.name}' was moved at {info.moved_at}"
            ))
    
    def visit_assignment(self, node: Assignment):
        source_info = self.bindings.get(node.value.name) if isinstance(node.value, Identifier) else None
        
        if node.is_copy:
            # ':=' operator: source remains valid
            # Target gets a copy
            pass
        else:
            # '=' operator: move semantics
            if source_info and source_info.is_unique:
                source_info.ownership = OwnershipState.MOVED
                source_info.moved_at = node.location
    
    def visit_call(self, node: CallExpr):
        func = self.resolve_function(node.name)
        for arg, param in zip(node.args, func.params):
            arg_info = self.bindings.get(arg.name) if isinstance(arg, Identifier) else None
            
            if arg_info and arg_info.is_unique:
                if param.borrow:
                    # Borrow: no ownership transfer
                    pass
                elif param.unique:
                    # Unique param: ownership transfers
                    arg_info.ownership = OwnershipState.MOVED
                    arg_info.moved_at = node.location
                else:
                    # Non-unique param: ownership transfers, uniqueness lost
                    arg_info.ownership = OwnershipState.MOVED
                    arg_info.moved_at = node.location
                    self.warnings.append(OwnershipWarning(
                        f"Unique binding '{arg.name}' passed to non-unique parameter; uniqueness lost",
                        node.location
                    ))
    
    def visit_if(self, node: IfStatement):
        # Snapshot state before branches
        state_before = self.snapshot_state()
        
        # Analyze 'then' branch
        self.visit(node.then_branch)
        state_after_then = self.snapshot_state()
        
        # Restore and analyze 'else' branch
        self.restore_state(state_before)
        if node.else_branch:
            self.visit(node.else_branch)
        state_after_else = self.snapshot_state()
        
        # Merge states: a binding is moved if moved on ANY path
        self.merge_states(state_after_then, state_after_else)
    
    def visit_while(self, node: WhileStatement):
        # Snapshot state before loop
        state_before = self.snapshot_state()
        
        # Analyze loop body
        self.visit(node.body)
        state_after_body = self.snapshot_state()
        
        # Check for moves inside loop
        for name, info in state_after_body.items():
            before_info = state_before.get(name)
            if before_info and before_info.ownership == OwnershipState.VALID:
                if info.ownership == OwnershipState.MOVED:
                    # Check if it's a rebinding (OK) or move to another binding (error)
                    if not self.is_rebinding(node.body, name):
                        self.errors.append(OwnershipError(
                            f"Unique binding '{name}' moved inside loop",
                            info.moved_at,
                            "Moving a unique binding inside a loop would invalidate it on subsequent iterations"
                        ))
```

### 4.5 Borrow Checking

For borrowed parameters, the compiler ensures:

1. The borrowed value is not mutated
2. The borrowed value is not moved
3. The borrowed value is not returned or stored

```python
class BorrowChecker(ASTVisitor):
    def __init__(self):
        self.borrowed_bindings: Set[str] = set()
    
    def visit_function(self, node: FunctionDecl):
        # Register borrowed parameters
        for param in node.params:
            if param.borrow:
                self.borrowed_bindings.add(param.name)
        
        # Analyze function body
        self.visit(node.body)
    
    def visit_assignment(self, node: Assignment):
        if node.target in self.borrowed_bindings:
            self.errors.append(BorrowError(
                f"Cannot mutate borrowed binding '{node.target}'",
                node.location
            ))
        
        if isinstance(node.value, Identifier) and node.value.name in self.borrowed_bindings:
            if not node.is_copy:
                self.errors.append(BorrowError(
                    f"Cannot move borrowed binding '{node.value.name}'",
                    node.location
                ))
    
    def visit_return(self, node: ReturnStatement):
        if isinstance(node.value, Identifier) and node.value.name in self.borrowed_bindings:
            self.errors.append(BorrowError(
                f"Cannot return borrowed binding '{node.value.name}'",
                node.location
            ))
```

### 4.6 Error Messages

The compiler produces clear, helpful error messages:

```
error[E0501]: use of moved value 'arr'
  --> example.coex:10:5
   |
 7 | unique arr: Array<int> = [1, 2, 3]
   |        --- binding declared here
 8 | consume(arr)
   |         --- value moved here
 9 | 
10 | print(arr)
   |       ^^^ use of moved value
   |
   = help: consider using ':=' to copy instead of move

warning[W0502]: unique binding passed to non-unique parameter
  --> example.coex:15:9
   |
14 | unique data: Array<int> = load()
   |        ---- unique binding declared here
15 | process(data)
   |         ^^^^ uniqueness lost here
   |
   = note: 'process' parameter is not declared 'unique'
   = help: declare parameter as 'unique' or 'borrow' to preserve uniqueness

error[E0503]: cannot mutate borrowed binding 'arr'
  --> example.coex:22:5
   |
20 | func modify(borrow arr: Array<int>) -> void
   |             ---------- 'arr' is borrowed here
21 |     
22 |     arr = arr.append(1)
   |     ^^^ cannot mutate borrowed value
   |
   = help: remove 'borrow' modifier to take ownership, or return modified value
```

### 4.7 Warning Insertion

When uniqueness is lost, insert a warning comment into the source representation:

```python
def emit_uniqueness_warning(self, binding: str, location: SourceLocation):
    warning = f"#@ [UNIQUE] Unique binding '{binding}' passed to non-unique parameter; uniqueness lost"
    self.warnings.append(Warning(warning, location))
```

## 5. Code Generation

### 5.1 Unique Bindings

Unique bindings generate the same code as non-unique bindings, but update operations use in-place variants:

```coex
unique arr: Array<int> = [1, 2, 3]
arr = arr.append(4)
```

Generates (using in-place optimization):

```llvm
; Initial allocation
%handle = call i64 @array_new()
; ... initialize with [1, 2, 3] ...
store i64 %handle, ptr %arr_slot

; In-place append (from uniqueness analysis)
%wrapper = call ptr @gc_handle_deref(i64 %handle)
call void @array_append_inplace(ptr %wrapper, i64 4)
; Handle unchanged; no store needed
```

### 5.2 Move Operations

Moves don't generate special code—they're enforced at compile time. The value simply changes which binding "owns" it conceptually:

```coex
unique arr: Array<int> = [1, 2, 3]
other = arr  # Move
```

Generates:

```llvm
; arr initialization
%handle = call i64 @array_new()
store i64 %handle, ptr %arr_slot

; Move: just copy the handle, compiler prevents further use of arr
%h = load i64, ptr %arr_slot
store i64 %h, ptr %other_slot
```

### 5.3 Copy Operations

The `:=` operator generates a deep copy:

```coex
unique arr: Array<int> = [1, 2, 3]
other := arr
```

Generates:

```llvm
; arr initialization
%arr_handle = call i64 @array_new()
store i64 %arr_handle, ptr %arr_slot

; Copy: create new array with same contents
%copy_handle = call i64 @array_copy(i64 %arr_handle)
store i64 %copy_handle, ptr %other_slot
```

### 5.4 Borrowed Parameters

Borrowed parameters pass the handle without ownership transfer. The callee cannot modify or move:

```coex
func sum(borrow arr: Array<int>) -> int
    total = 0
    for i in 0..arr.len()
        total = total + arr.get(i)
    ~
    return total
~
```

Generates standard parameter passing—the borrowing is enforced at compile time, not runtime:

```llvm
define i64 @sum(i64 %arr_handle) {
    ; %arr_handle is read-only within this function
    ; Compiler has verified no mutations or moves
    ; ... standard array access code ...
}
```

### 5.5 Type Conversion

Type conversion generates a copy via the target type's constructor:

```coex
unique arr: Array<int> = [1, 2, 3]
list: List<int> = arr
```

Generates:

```llvm
; arr initialization
%arr_handle = call i64 @array_new()
store i64 %arr_handle, ptr %arr_slot

; Conversion: construct List from Array contents
%list_handle = call i64 @list_from_array(i64 %arr_handle)
store i64 %list_handle, ptr %list_slot
; arr_handle unchanged; arr still valid
```

## 6. Implementation Tasks

### Task 1: Lexer and Parser Extensions

Extend the lexer to recognize:
- `unique` keyword
- `borrow` keyword
- `:=` operator (COLON_EQUALS token)

Extend the parser to handle:
- `unique` modifier on variable declarations
- `unique` and `borrow` modifiers on function parameters
- `unique` modifier on return types
- `:=` as assignment operator

Deliverable: Updates to `CoexLexer.g4` and `CoexParser.g4`

### Task 2: AST Extensions

Add new fields to AST nodes:
- `VariableDecl.unique: bool`
- `Parameter.unique: bool`
- `Parameter.borrow: bool`
- `FunctionDecl.return_unique: bool`
- `Assignment.is_copy: bool`

Deliverable: Updates to `ast_nodes.py`

### Task 3: Ownership Analysis Pass

Implement the ownership analyzer:
- Track ownership state for each binding
- Detect moves and invalidate source bindings
- Handle control flow (if/else, while, for)
- Generate errors for use-after-move
- Generate warnings for uniqueness loss

Deliverable: New `ownership.py` module

### Task 4: Borrow Checker

Implement borrow checking:
- Track borrowed bindings within functions
- Prevent mutation of borrowed values
- Prevent moving borrowed values
- Prevent returning/storing borrowed values

Deliverable: New `borrow_check.py` module

### Task 5: Error Reporting

Implement clear error messages:
- Use-after-move errors with location of move
- Borrow violation errors
- Control flow errors (moved on some paths)
- Helpful suggestions (use `:=`, add `borrow`, etc.)

Deliverable: Updates to error reporting infrastructure

### Task 6: Warning Insertion

Implement `#@` warning insertion:
- Detect uniqueness loss scenarios
- Insert warnings into source/AST representation
- Format warnings consistently with existing `#@` warnings

Deliverable: Updates to warning system

### Task 7: Code Generation Integration

Integrate with existing uniqueness optimization:
- Unique bindings always use in-place variants
- Generate copy operations for `:=`
- No special runtime code for moves (compile-time only)

Deliverable: Updates to `codegen.py`

### Task 8: Copy Operations

Implement deep copy for supported types:
- `array_copy(handle) -> handle`
- `string_copy(handle) -> handle`

These create fresh, independent values with copied contents.

Deliverable: New copy functions in codegen

### Task 9: Testing

Comprehensive test suite:
- Valid unique usage patterns
- Move semantics (valid and invalid)
- Copy semantics
- Borrow semantics (valid and invalid)
- Control flow (if/else, while, for)
- Function parameters (unique, borrow, non-unique)
- Return values
- Type conversion
- Error message quality

Deliverable: Test suite in `tests/unique/`

## 7. Examples

### 7.1 Basic Usage

```coex
func process_data() -> int
    # Declare unique array
    unique buffer: Array<int> = []
    
    # In-place append (guaranteed)
    for i in 0..1000
        buffer = buffer.append(i)
    ~
    
    # Borrow for read-only access
    total = sum(buffer)
    
    # Still unique; can continue using
    buffer = buffer.append(total)
    
    return buffer.len()
~

func sum(borrow arr: Array<int>) -> int
    result = 0
    for i in 0..arr.len()
        result = result + arr.get(i)
    ~
    return result
~
```

### 7.2 Move and Copy

```coex
func demonstrate_move_copy() -> void
    unique original: Array<int> = [1, 2, 3]
    
    # Copy: original remains valid
    unique backup := original
    
    # Move: original becomes invalid
    transferred = original
    
    # This would be an error:
    # print(original)  # Error: 'original' was moved
    
    # But backup is still valid
    print(backup)
~
```

### 7.3 Function Ownership Transfer

```coex
func producer() -> unique Array<int>
    unique result: Array<int> = []
    for i in 0..100
        result = result.append(i * i)
    ~
    return result  # Ownership transfers to caller
~

func consumer(unique data: Array<int>) -> int
    # Received ownership; can mutate in-place
    data = data.set_at(0, 999)
    return data.get(0)
~

func main() -> void
    unique arr = producer()   # Receive unique array
    result = consumer(arr)    # Transfer ownership
    # arr is now invalid
~
```

### 7.4 Borrowing Pattern

```coex
func analyze(borrow data: Array<int>) -> Analysis
    # Can read data but not modify or move it
    min_val = data.get(0)
    max_val = data.get(0)
    
    for i in 1..data.len()
        val = data.get(i)
        if val < min_val
            min_val = val
        ~
        if val > max_val
            max_val = val
        ~
    ~
    
    return Analysis(min_val, max_val, data.len())
~

func main() -> void
    unique measurements: Array<int> = collect_data()
    
    # Borrow for analysis; retain ownership
    stats = analyze(measurements)
    
    # Still unique; can add more data
    measurements = measurements.append(new_reading)
    
    # Borrow again
    updated_stats = analyze(measurements)
~
```

### 7.5 Control Flow

```coex
func conditional_processing(unique data: Array<int>, mode: int) -> int
    if mode == 1
        # Process and consume
        return process_mode1(data)  # data moved
    else if mode == 2
        # Different processing
        return process_mode2(data)  # data moved
    else
        # Default: just return length
        result = data.len()
        cleanup(data)               # data moved
        return result
    ~
    # data is moved on all paths; no use after if is valid
~

func loop_processing(unique buffer: Array<int>) -> Array<int>
    while buffer.len() < 1000
        buffer = buffer.append(buffer.len())  # Rebinding OK
    ~
    return buffer  # Transfer ownership to caller
~
```

## 8. Future Extensions

### 8.1 HAMT-Based Types

Extend `unique` support to `Set<T>`, `Map<K,V>`, and `List<T>` once their internal structure supports in-place mutation of wrapper and path nodes.

### 8.2 Unique Fields in UDTs

Allow `unique` fields in user-defined types:

```coex
type Buffer:
    unique data: Array<byte>
    position: int
~
```

### 8.3 Mutable Borrows

Add `borrow mut` for exclusive mutable borrows:

```coex
func fill(borrow mut arr: Array<int>, value: int) -> void
    for i in 0..arr.len()
        arr = arr.set_at(i, value)  # Allowed with mutable borrow
    ~
~
```

### 8.4 Lifetime Annotations

For complex borrowing patterns, explicit lifetime annotations:

```coex
func longest<'a>(borrow x: Array<'a, int>, borrow y: Array<'a, int>) -> borrow Array<'a, int>
    if x.len() > y.len()
        return x
    else
        return y
    ~
~
```

## 9. Appendix: Comparison with Other Languages

### Rust

Coex's unique ownership is inspired by Rust but simpler:
- No lifetime annotations (initially)
- No mutable borrows (initially)
- Simpler partial move rules (none allowed)
- Explicit copy operator (`:=`) vs. `Clone` trait

### Swift

Similar to Swift's copy-on-write, but:
- Uniqueness is declared, not inferred
- No reference counting overhead
- Compile-time enforcement only

### Clean

Similar to Clean's uniqueness types:
- Both provide guaranteed in-place mutation
- Coex uses keyword modifier; Clean uses type annotation (`*`)
- Coex borrowing is simpler than Clean's uniqueness propagation
