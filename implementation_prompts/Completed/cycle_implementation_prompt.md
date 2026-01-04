# Implementing the `cycle` Block in Coex

## Overview

Implement a new control flow construct that provides double-buffered semantics for synchronous dataflow computation. The syntax is `while condition cycle`, where the condition is evaluated in the outer scope and the cycle body contains double-buffered variables.

All variables declared within the cycle block are double-buffered: reads see the previous generation's values, writes accumulate into the next generation's buffer, and at each iteration boundary the buffers swap.

This construct enables cellular automata, Jacobi iteration, synchronous state machines, and other patterns where all updates should appear to happen simultaneously.

In order to do this, we will be implementing the standard "while" syntax for all purposes, and the while condition cycle syntax at the same time.

## Syntax

```
while condition
  # standard while syntax as implemented in most languages
  # while true is equivalent to loop. We will remove loop 
~
```

```
while condition cycle
  # All variables declared here are double-buffered
  # Reads see previous generation, writes go to next generation
~
```

The condition is evaluated in the outer scope—any variables it references must be declared outside the cycle block. This eliminates a class of bugs where users accidentally double-buffer their loop control variables.

## Semantics

1. **Condition scope**: The `while condition` part is evaluated in the enclosing scope, not the double-buffered scope. Variables referenced in the condition must exist outside the cycle block.

2. **Double-buffering scope**: Variables declared inside the cycle block (via `var` or first assignment) exist in two copies: a "read buffer" (previous generation) and a "write buffer" (current generation).

3. **Read semantics**: All variable reads within the cycle block for cycle-declared variables read from the previous generation's buffer.

4. **Write semantics**: All variable writes within the cycle block for cycle-declared variables write to the current generation's buffer.

5. **Iteration boundary**: At the end of each iteration (reaching the `~`), the buffers swap—the write buffer becomes the read buffer for the next iteration.

6. **Termination condition**: The condition is evaluated after each generation completes and buffers swap. If false, the cycle exits. The condition reads from the outer scope, which may have been modified by the cycle body if outer variables were assigned.

7. **External variables**: Variables declared outside the cycle block are NOT double-buffered. They behave normally—reads and writes see/modify the same storage. Use these for accumulators.

8. **Break/Continue**: `break` exits the cycle immediately (uncommitted writes in the write buffer are lost). `continue` skips to the buffer swap and condition check.

## Example Use Cases

### Cellular Automaton (Conway's Game of Life pattern)
```
generation = 0
alive = true
while generation < 1000 and alive cycle
  var next_grid = [[false] * width] * height  # Double-buffered
  
  for y in range(0, height)
    for x in range(0, width)
      count = count_neighbors(grid, x, y)  # grid from outer scope
      next_grid[y][x] = grid[y][x] and count == 2 or count == 3
    ~
  ~
  
  grid = next_grid  # Commit to outer scope at generation end
  generation += 1   # Accumulator in outer scope
  alive = any_alive(grid)
~
```

### Jacobi Iteration
```
x = initial_guess.copy()
max_change = infinity

while max_change > tolerance cycle
  var local_max: float = 0  # Double-buffered, resets each gen
  
  for i in range(1, n-1)
    new_val = (b[i] - A[i,i-1]*x[i-1] - A[i,i+1]*x[i+1]) / A[i,i]
    local_max = max(local_max, abs(new_val - x[i]))
    x[i] = new_val
  ~
  
  max_change = local_max  # Copy to outer scope for condition
~
```

### Synchronous State Machine
```
state = Initial
input_idx = 0

while state != Halted and input_idx < len(inputs) cycle
  var next_state = transition[state][inputs[input_idx]]  # Double-buffered
  var output = output_table[state]                        # Double-buffered
  
  emit(output)
  state = next_state      # Commit to outer scope
  input_idx += 1          # Advance in outer scope
~
```

## Implementation Steps

### Step 1: Grammar (Coex.g4)

Add the CYCLE keyword to the lexer section (near line 588, with other control flow keywords):

```antlr
CYCLE       : 'cycle' ;
```

Add the cycleStmt rule to the parser. Place it in controlFlowStmt (around line 204):

```antlr
controlFlowStmt
    : ifStmt
    | forStmt
    | forAssignStmt
    | loopStmt
    | cycleStmt      // ADD THIS
    | matchStmt
    | selectStmt
    | withinStmt
    | returnStmt
    | breakStmt
    | continueStmt
    ;
```

Add the grammar rule for cycleStmt (place after loopStmt around line 278):

```antlr
// Cycle statement (double-buffered synchronous iteration)
// Condition is in outer scope; body variables are double-buffered
cycleStmt
    : WHILE expression CYCLE NEWLINE* block
    ;
```

### Step 2: Regenerate Parser

After modifying the grammar, regenerate the ANTLR parser files:

```bash
antlr4 -Dlanguage=Python3 -visitor Coex.g4
```

This will update CoexLexer.py, CoexParser.py, CoexListener.py, and CoexVisitor.py.

### Step 3: AST Node (ast_nodes.py)

Add a new AST node for CycleStmt. Place it near the other statement nodes (around line 502, after LoopStmt):

```python
@dataclass
class CycleStmt(Stmt):
    """Cycle statement (double-buffered synchronous iteration)
    
    while condition cycle
      # body with double-buffered locals
    ~
    
    The condition is evaluated in outer scope after each generation.
    Variables declared in the body are double-buffered.
    """
    condition: Expr
    body: List[Stmt]
```

Also add the import for CycleStmt if needed in any __all__ exports.

### Step 4: AST Builder (ast_builder.py)

Add handling for cycleStmt in the `visit_control_flow_stmt` method (around line 497):

```python
def visit_control_flow_stmt(self, ctx: CoexParser.ControlFlowStmtContext) -> Stmt:
    """Visit a control flow statement"""
    child = ctx.getChild(0)
    
    if isinstance(child, CoexParser.IfStmtContext):
        return self.visit_if_stmt(child)
    elif isinstance(child, CoexParser.ForStmtContext):
        return self.visit_for_stmt(child)
    elif isinstance(child, CoexParser.ForAssignStmtContext):
        return self.visit_for_assign_stmt(child)
    elif isinstance(child, CoexParser.LoopStmtContext):
        return self.visit_loop_stmt(child)
    elif isinstance(child, CoexParser.CycleStmtContext):  # ADD THIS
        return self.visit_cycle_stmt(child)
    elif isinstance(child, CoexParser.MatchStmtContext):
        return self.visit_match_stmt(child)
    # ... rest of method
```

Add the visitor method for cycle statements (place after visit_loop_stmt):

```python
def visit_cycle_stmt(self, ctx: CoexParser.CycleStmtContext) -> CycleStmt:
    """Visit a cycle statement: while condition cycle block"""
    condition = self.visit_expression(ctx.expression())
    body = self.visit_block(ctx.block())
    return CycleStmt(condition, body)
```

### Step 5: Code Generation (codegen.py)

This is the most complex part. The code generator needs to:

1. Identify which variables are declared inside the cycle block
2. Allocate two copies of each such variable (read buffer, write buffer)
3. Redirect reads to the read buffer and writes to the write buffer
4. Swap buffer contents at each iteration boundary
5. Evaluate the condition (in outer scope) after swapping

#### 5a. Initialize cycle context in __init__

In the `__init__` method of CodeGenerator (around line 76), add:

```python
# Cycle (double-buffer) context stack
self._cycle_context_stack = []
```

#### 5b. Add dispatch in _generate_statement

In the `_generate_statement` method (around line 3243), add handling for CycleStmt:

```python
elif isinstance(stmt, CycleStmt):
    self._generate_cycle(stmt)
```

#### 5c. Implement _generate_cycle

Add this method (place near _generate_loop around line 3658):

```python
def _generate_cycle(self, stmt: CycleStmt):
    """Generate a cycle statement with double-buffered semantics.
    
    Syntax: while condition cycle block
    
    Variables declared inside the cycle block exist in two buffers.
    Reads see the 'read' buffer (previous generation).
    Writes go to the 'write' buffer (current generation).
    At iteration end, buffers swap and condition is checked in outer scope.
    """
    func = self.builder.function
    
    # Phase 1: Analyze the body to find variables declared inside
    cycle_vars = self._find_cycle_declared_vars(stmt.body)
    
    # Phase 2: Create double-buffered storage for cycle variables
    read_buffers = {}   # var_name -> alloca for read buffer
    write_buffers = {}  # var_name -> alloca for write buffer
    
    for var_name, var_type in cycle_vars.items():
        llvm_type = self._get_llvm_type(var_type) if var_type else ir.IntType(64)
        read_buffers[var_name] = self.builder.alloca(llvm_type, name=f"{var_name}_read")
        write_buffers[var_name] = self.builder.alloca(llvm_type, name=f"{var_name}_write")
        
        # Initialize both buffers to zero/null
        if isinstance(llvm_type, ir.IntType):
            zero = ir.Constant(llvm_type, 0)
        elif isinstance(llvm_type, ir.DoubleType):
            zero = ir.Constant(llvm_type, 0.0)
        elif isinstance(llvm_type, ir.PointerType):
            zero = ir.Constant(llvm_type, None)
        else:
            zero = ir.Constant(llvm_type, 0)
        self.builder.store(zero, read_buffers[var_name])
        self.builder.store(zero, write_buffers[var_name])
    
    # Phase 3: Create basic blocks
    body_block = func.append_basic_block("cycle_body")
    swap_block = func.append_basic_block("cycle_swap")
    cond_block = func.append_basic_block("cycle_cond")
    exit_block = func.append_basic_block("cycle_exit")
    
    # Save loop blocks for break/continue
    old_exit = self.loop_exit_block
    old_continue = self.loop_continue_block
    self.loop_exit_block = exit_block
    self.loop_continue_block = swap_block  # continue commits and checks condition
    
    # Phase 4: Initial condition check (enter cycle only if condition true)
    init_cond = self._generate_expression(stmt.condition)
    init_cond_bool = self._ensure_boolean(init_cond)
    self.builder.cbranch(init_cond_bool, body_block, exit_block)
    
    # Phase 5: Push cycle context and generate body
    self.builder.position_at_end(body_block)
    
    cycle_context = {
        'read_buffers': read_buffers,
        'write_buffers': write_buffers,
        'cycle_vars': set(cycle_vars.keys())
    }
    self._cycle_context_stack.append(cycle_context)
    
    # Generate body statements
    for s in stmt.body:
        self._generate_statement(s)
        if self.builder.block.is_terminated:
            break
    
    if not self.builder.block.is_terminated:
        self.builder.branch(swap_block)
    
    # Pop cycle context before swap (condition is in outer scope)
    self._cycle_context_stack.pop()
    
    # Phase 6: Buffer swap - copy write buffer to read buffer
    self.builder.position_at_end(swap_block)
    for var_name in cycle_vars:
        write_val = self.builder.load(write_buffers[var_name])
        self.builder.store(write_val, read_buffers[var_name])
    self.builder.branch(cond_block)
    
    # Phase 7: Condition check (in outer scope, after swap)
    self.builder.position_at_end(cond_block)
    cond_val = self._generate_expression(stmt.condition)
    cond_bool = self._ensure_boolean(cond_val)
    self.builder.cbranch(cond_bool, body_block, exit_block)
    
    # Phase 8: Exit and cleanup
    self.builder.position_at_end(exit_block)
    
    # Restore loop blocks
    self.loop_exit_block = old_exit
    self.loop_continue_block = old_continue


def _find_cycle_declared_vars(self, stmts: PyList[Stmt]) -> Dict[str, Optional[Type]]:
    """Find all variables declared within a list of statements.
    
    Returns dict of var_name -> type_annotation (or None if inferred).
    Recursively scans into control flow but not into nested cycles.
    """
    declared = {}
    
    for stmt in stmts:
        if isinstance(stmt, VarDecl):
            declared[stmt.name] = stmt.type_annotation
        elif isinstance(stmt, Assignment):
            # Simple assignment to new identifier declares a var
            if isinstance(stmt.target, Identifier) and stmt.op == AssignOp.ASSIGN:
                name = stmt.target.name
                # Only count as declaration if not already known
                if name not in declared and name not in self.locals and name not in self.globals:
                    declared[name] = None
        elif isinstance(stmt, IfStmt):
            # Recurse into branches
            declared.update(self._find_cycle_declared_vars(stmt.then_body))
            for _, body in stmt.else_if_clauses:
                declared.update(self._find_cycle_declared_vars(body))
            if stmt.else_body:
                declared.update(self._find_cycle_declared_vars(stmt.else_body))
        elif isinstance(stmt, ForStmt):
            # Loop variable is declared
            if stmt.var_name:
                declared[stmt.var_name] = None
            declared.update(self._find_cycle_declared_vars(stmt.body))
        elif isinstance(stmt, LoopStmt):
            declared.update(self._find_cycle_declared_vars(stmt.body))
        # Note: Don't recurse into nested CycleStmt - those have their own scope
    
    return declared
```

#### 5d. Helper to check if in cycle context

Add helper methods:

```python
def _in_cycle_context(self) -> bool:
    """Check if currently generating code inside a cycle block."""
    return len(self._cycle_context_stack) > 0

def _get_cycle_context(self):
    """Get the current cycle context, or None if not in a cycle."""
    if self._cycle_context_stack:
        return self._cycle_context_stack[-1]
    return None
```

#### 5e. Modify variable reads to respect cycle context

Find the method that handles Identifier expressions (likely `_generate_identifier` or within `_generate_expression`). Add cycle-aware logic:

```python
def _generate_identifier(self, expr: Identifier) -> ir.Value:
    name = expr.name
    
    # Check if we're in a cycle and this is a cycle variable
    ctx = self._get_cycle_context()
    if ctx and name in ctx['cycle_vars']:
        # Read from read buffer (previous generation)
        read_buf = ctx['read_buffers'][name]
        return self.builder.load(read_buf, name=name)
    
    # Normal variable access (existing code)
    if name in self.locals:
        return self.builder.load(self.locals[name], name=name)
    elif name in self.globals:
        return self.builder.load(self.globals[name], name=name)
    # ... rest of existing logic
```

#### 5f. Modify variable writes to respect cycle context

Find the method that handles Assignment statements. Add cycle-aware logic at the beginning:

```python
def _generate_assignment(self, stmt: Assignment):
    # Check if target is a cycle variable
    if isinstance(stmt.target, Identifier):
        name = stmt.target.name
        ctx = self._get_cycle_context()
        if ctx and name in ctx['cycle_vars']:
            # Write to write buffer (current generation)
            value = self._generate_expression(stmt.value)
            write_buf = ctx['write_buffers'][name]
            
            # Handle compound assignment
            if stmt.op != AssignOp.ASSIGN:
                # Read from READ buffer, compute, write to WRITE buffer
                old_val = self.builder.load(ctx['read_buffers'][name])
                if stmt.op == AssignOp.PLUS_ASSIGN:
                    value = self.builder.add(old_val, value)
                elif stmt.op == AssignOp.MINUS_ASSIGN:
                    value = self.builder.sub(old_val, value)
                # ... other compound ops
            
            self.builder.store(value, write_buf)
            return
    
    # Normal assignment (existing code)
    # ...
```

#### 5g. Modify VarDecl to respect cycle context

In the method that handles VarDecl statements:

```python
def _generate_var_decl(self, stmt: VarDecl):
    name = stmt.name
    
    # Check if this is a cycle variable
    ctx = self._get_cycle_context()
    if ctx and name in ctx['cycle_vars']:
        # Initialize by writing to write buffer
        value = self._generate_expression(stmt.initializer)
        write_buf = ctx['write_buffers'][name]
        self.builder.store(value, write_buf)
        return
    
    # Normal var declaration (existing code)
    # ...
```

### Step 6: Add CycleStmt to imports

In codegen.py, ensure CycleStmt is imported from ast_nodes:

```python
from ast_nodes import *
```

Or if explicit imports are used, add CycleStmt to the list.

### Step 7: Tests

Create test cases. Add these to your test file:

```python
def test_cycle_basic_counter():
    """Test basic cycle with external counter"""
    code = '''
    func main() -> int
      count = 0
      while count < 5 cycle
        var x: int = 1
        count += 1
      ~
      return count
    ~
    '''
    assert compile_and_run(code) == 5


def test_cycle_double_buffer_isolation():
    """Test that cycle vars don't see their own writes within a generation"""
    code = '''
    func main() -> int
      result = 0
      iteration = 0
      while iteration < 3 cycle
        var a: int = 0
        var b: int = a + 1
        a = 10
        var c: int = a
        result = b + c
        iteration += 1
      ~
      return result
    ~
    '''
    # First iteration: a=0(read), b=0+1=1, a=10(write), c=0(read)=0, result=1
    # After swap: a_read=10
    # Second iteration: a=10(read), b=10+1=11, a=10(write), c=10(read)=10, result=21
    # After swap: a_read=10 (same)
    # Third iteration: same as second, result=21
    assert compile_and_run(code) == 21


def test_cycle_accumulator_outside():
    """Test that variables outside cycle accumulate normally"""
    code = '''
    func main() -> int
      sum = 0
      i = 0
      while i < 5 cycle
        var contribution: int = i * 2
        sum += contribution
        i += 1
      ~
      return sum
    ~
    '''
    # i=0: contribution=0, sum=0
    # i=1: contribution=2, sum=2
    # i=2: contribution=4, sum=6
    # i=3: contribution=6, sum=12
    # i=4: contribution=8, sum=20
    assert compile_and_run(code) == 20


def test_cycle_break():
    """Test break inside cycle"""
    code = '''
    func main() -> int
      count = 0
      while true cycle
        var x: int = 1
        count += 1
        if count >= 3
          break
        ~
      ~
      return count
    ~
    '''
    assert compile_and_run(code) == 3


def test_cycle_continue():
    """Test continue inside cycle"""
    code = '''
    func main() -> int
      count = 0
      sum = 0
      while count < 5 cycle
        var x: int = count
        count += 1
        if x == 2
          continue
        ~
        sum += x
      ~
      return sum
    ~
    '''
    # x values: 0, 1, 2(skip), 3, 4 -> sum = 0+1+3+4 = 8
    assert compile_and_run(code) == 8


def test_cycle_nested_for():
    """Test for loop inside cycle"""
    code = '''
    func main() -> int
      iteration = 0
      total = 0
      while iteration < 3 cycle
        var sum: int = 0
        for i in range(0, 4)
          sum += i
        ~
        total += sum
        iteration += 1
      ~
      return total
    ~
    '''
    # Each iteration: sum = 0+1+2+3 = 6
    # 3 iterations: total = 18
    assert compile_and_run(code) == 18


def test_cycle_condition_uses_outer():
    """Test that condition correctly reads outer scope"""
    code = '''
    func main() -> int
      limit = 5
      count = 0
      while count < limit cycle
        var x: int = 1
        count += 1
        if count == 3
          limit = 3
        ~
      ~
      return count
    ~
    '''
    # count goes 1, 2, 3, then limit=3, condition false, exit
    assert compile_and_run(code) == 3
```

### Step 8: Update Specification

Add documentation for the cycle construct to the Coex language specification document.

## Implementation Notes

1. **Start simple**: For the initial implementation, focus on primitive types (int, float, bool). Complex types like lists and user-defined types can be added later.

2. **Type inference challenge**: The `_find_cycle_declared_vars` helper may not know types for variables declared via plain assignment. You may need to:
   - Require explicit `var x: type` declarations for cycle variables
   - Or infer types during a first pass before code generation
   - Or default to i64 and cast as needed

3. **Nested cycles**: The context stack design supports nested cycles correctly. Each cycle pushes its own context, and variables are looked up in the innermost context first.

4. **Compound assignment semantics**: For `x += 1` inside a cycle, the read comes from the read buffer (previous gen) and the write goes to the write buffer (current gen). This is the correct synchronous semantics.

5. **Condition evaluation timing**: The condition is checked:
   - Before the first iteration (don't enter if already false)
   - After each buffer swap (exit when false)

6. **Break vs Continue**: 
   - `break` exits immediately, uncommitted writes are lost
   - `continue` jumps to swap block, commits writes, checks condition

## Testing Strategy

Run tests incrementally:

1. Parse test: verify `while x cycle ... ~` parses correctly
2. AST test: verify CycleStmt node is constructed
3. Basic codegen: counter-based cycle works
4. Double-buffer semantics: verify read/write isolation
5. Break and continue
6. Nested control flow inside cycle
7. Edge cases: condition immediately false, single iteration

```bash
pytest tests/ -v -k cycle
```
