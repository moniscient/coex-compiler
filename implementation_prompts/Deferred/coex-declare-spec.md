# Coex Declare Function Kind: Implementation Specification

## CRITICAL IMPLEMENTATION CONSTRAINTS

**READ THIS SECTION FIRST. THESE CONSTRAINTS ARE NON-NEGOTIABLE.**

### What This Spec Requires

This specification describes a new function kind `declare` for declarative linear algebra with Einstein notation. The implementation MUST:

1. Add `declare` as a new function kind in the parser and AST
2. Implement Einstein notation parsing within `declare` bodies
3. Build a lazy computation graph from `declare` body statements
4. Lower the computation graph to BLAS calls and/or GPU kernels at evaluation time
5. Enforce the calling hierarchy: `declare` can call `formula`, but not vice versa

### What This Spec PROHIBITS

The following approaches are **explicitly forbidden** without prior discussion and approval:

1. **NO runtime interpretation** — The declare body must compile to a static computation graph, not be interpreted statement-by-statement at runtime.

2. **NO Python-based graph execution** — The computation graph must lower to native code (LLVM IR, BLAS calls, GPU kernels), not execute via Python/NumPy at runtime.

3. **NO ignoring Einstein notation** — Index expressions like `C[i,j] = A[i,k] * B[k,j]` must be parsed and understood, not treated as array indexing syntax.

4. **NO skipping the graph optimization phase** — The compiler must analyze the full graph before generating code, enabling operation fusion and BLAS pattern recognition.

5. **NO partial implementations that "work around" the hard parts** — If Einstein notation parsing is difficult, stop and discuss. Do not substitute a simpler syntax.

### If You Encounter Obstacles

If implementing this spec as written is not feasible:

1. **STOP implementation**
2. **EXPLAIN** the specific technical obstacle
3. **PROPOSE** alternatives with tradeoffs
4. **WAIT** for approval before proceeding

---

## Overview

`declare` is a new function kind for declarative linear algebra. It provides:

1. **Einstein notation** — Implicit summation over repeated indices
2. **Lazy evaluation** — Builds a computation graph, executes at return
3. **Automatic optimization** — Graph analysis enables fusion and BLAS routing
4. **Purity** — No side effects, deterministic results

### Example

```coex
declare matmul(A: [[float32]], B: [[float32]]) -> [[float32]]:
    C[i,j] = A[i,k] * B[k,j]
    return C
~
```

This declares a matrix multiplication using Einstein notation. The repeated index `k` implies summation: `C[i,j] = Σₖ A[i,k] * B[k,j]`.

---

## Syntax

### Function Declaration

```
DECLARE    : 'declare' ;

functionKind
    : FORMULA
    | TASK
    | THREAD
    | FUNC
    | EXTERN
    | DECLARE    // NEW
    ;
```

A declare function follows standard Coex function syntax:

```coex
declare name(params) -> returnType:
    body
~
```

### Einstein Index Expressions

Within a `declare` body, a new syntactic form is valid: indexed assignment.

```
indexedAssignment
    : IDENTIFIER indexList ASSIGN expression
    ;

indexList
    : LBRACKET indexExpr (COMMA indexExpr)* RBRACKET
    ;

indexExpr
    : IDENTIFIER           // Index variable: i, j, k
    | INTEGER_LITERAL      // Constant index: 0, 1
    | rangeExpr            // Slice: 0..n, i..j
    ;

rangeExpr
    : expression DOTDOT expression
    ;
```

Examples:

```coex
C[i,j] = A[i,k] * B[k,j]     # Matrix multiply
T[i,j] = A[j,i]               # Transpose
v[i] = A[i,j] * x[j]          # Matrix-vector multiply
s = A[i,i]                    # Trace (scalar result)
O[i,j] = u[i] * v[j]          # Outer product
```

### Index Variable Scoping

Index variables (`i`, `j`, `k`, etc.) are implicitly declared by their first use in an indexed expression. They are scoped to the single statement they appear in.

```coex
declare example(A: [[float32]], B: [[float32]]) -> [[float32]]:
    C[i,j] = A[i,k] * B[k,j]    # i, j, k scoped to this statement
    D[i,j] = C[i,j] + A[i,j]    # Fresh i, j scoped to this statement
    return D
~
```

### Repeated Index Convention (Einstein Summation)

When an index variable appears exactly twice on the right-hand side of an assignment, summation over that index is implied:

```coex
# k appears twice on RHS → sum over k
C[i,j] = A[i,k] * B[k,j]    # Means: C[i,j] = Σₖ A[i,k] * B[k,j]

# i appears twice on RHS → sum over i (trace)
t = A[i,i]                   # Means: t = Σᵢ A[i,i]

# No repeated indices → element-wise / outer product
O[i,j] = u[i] * v[j]         # Means: O[i,j] = u[i] * v[j] (no sum)
```

### Dimension Inference

Index ranges are inferred from array dimensions:

```coex
declare matmul(A: [[float32]], B: [[float32]]) -> [[float32]]:
    # A is M×K, B is K×N
    # i ranges over 0..M, j over 0..N, k over 0..K
    C[i,j] = A[i,k] * B[k,j]
    return C
~
```

The compiler infers:
- `i` range from first dimension of `A`
- `j` range from second dimension of `B`
- `k` range from second dimension of `A` (must equal first dimension of `B`)

Dimension mismatch is a compile-time error if dimensions are statically known, otherwise a runtime error.

---

## Semantic Model

### Computation Graph

A `declare` body builds a computation graph, not an imperative sequence. Each statement adds nodes to the graph:

```coex
declare example(A: [[float32]], B: [[float32]], C: [[float32]]) -> [[float32]]:
    D[i,j] = A[i,k] * B[k,j]      # Node 1: GEMM(A, B) → D
    E[i,j] = D[i,j] + C[i,j]      # Node 2: ADD(D, C) → E
    return E                      # Node 3: Output E
~
```

Graph structure:

```
    A ──┐
        ├──→ [GEMM] ──→ D ──┐
    B ──┘                    ├──→ [ADD] ──→ E ──→ [RETURN]
                         C ──┘
```

### Lazy Evaluation

The graph does not execute until `return`. This enables:

1. **Dead code elimination** — Unreferenced nodes are removed
2. **Operation fusion** — Adjacent compatible ops merge
3. **BLAS pattern recognition** — Subgraphs matching BLAS ops route to library calls

### Purity

`declare` functions are pure:

1. No side effects (no I/O, no printing)
2. No mutable state access
3. Deterministic: same inputs → same outputs
4. No calling `func`, `task`, or `thread`

### Calling Hierarchy

```
func / task / thread
         │
         ▼ can call
      declare ←──────┐
         │           │ (can call other declares)
         ▼ can call  │
      formula        │
                     │
      declare ───────┘
```

- `declare` CAN call `formula` — formula evaluates eagerly, result becomes a constant node
- `declare` CAN call other `declare` — inlines the callee's graph
- `declare` CANNOT call `func`, `task`, `thread`
- `formula` CANNOT call `declare`

---

## Implementation Architecture

### Phase 1: Parsing

#### 1.1 Add DECLARE Token

```antlr
DECLARE : 'declare' ;

functionKind
    : FORMULA
    | TASK  
    | THREAD
    | FUNC
    | EXTERN
    | DECLARE
    ;
```

#### 1.2 Add Indexed Assignment Rule

```antlr
// Only valid inside declare bodies
indexedAssignment
    : IDENTIFIER indexList ASSIGN expression
    ;

indexList  
    : LBRACKET indexSpec (COMMA indexSpec)* RBRACKET
    ;

indexSpec
    : IDENTIFIER                              // Index variable
    | INTEGER_LITERAL                         // Constant
    | expression DOTDOT expression            // Range
    ;
```

#### 1.3 Modify Statement Rule for Declare Bodies

The parser needs context to know it's inside a `declare` body. Options:

**Option A: Context-sensitive parsing**
Track when inside a declare function and allow indexed assignments only there.

**Option B: Unified parsing, semantic rejection**
Parse indexed assignments anywhere, reject during semantic analysis if not in declare.

Recommend Option B for simpler grammar.

### Phase 2: AST Representation

#### 2.1 New AST Nodes

```python
class DeclareFunction(FunctionDecl):
    """A declare function kind."""
    kind = FunctionKind.DECLARE
    body: DeclareBody

class DeclareBody:
    """Body of a declare function - builds computation graph."""
    statements: List[DeclareStatement]
    return_expr: Expression

class DeclareStatement:
    """Base class for statements in declare body."""
    pass

class IndexedAssignment(DeclareStatement):
    """Einstein notation assignment: C[i,j] = A[i,k] * B[k,j]"""
    target: str                      # Target array name (C)
    target_indices: List[IndexSpec]  # Target indices (i, j)
    expression: Expression           # RHS expression
    
class IndexSpec:
    """An index in Einstein notation."""
    pass

class IndexVariable(IndexSpec):
    """A named index variable: i, j, k"""
    name: str

class IndexConstant(IndexSpec):
    """A constant index: 0, 1, 2"""
    value: int

class IndexRange(IndexSpec):
    """A range index: 0..n"""
    start: Expression
    end: Expression

class IndexedAccess(Expression):
    """Array access with Einstein indices: A[i,k]"""
    array: str
    indices: List[IndexSpec]
```

#### 2.2 Index Analysis

After parsing, analyze indices to determine:

```python
class IndexAnalysis:
    """Analysis results for an indexed assignment."""
    
    # All index variables used
    all_indices: Set[str]
    
    # Indices appearing on LHS (output dimensions)
    output_indices: List[str]
    
    # Indices appearing exactly twice on RHS (summed)
    summed_indices: Set[str]
    
    # Indices appearing once on RHS (element-wise)
    elementwise_indices: Set[str]
    
    # Inferred dimension for each index
    index_dimensions: Dict[str, Expression]
```

Example analysis for `C[i,j] = A[i,k] * B[k,j]`:

```python
IndexAnalysis(
    all_indices={'i', 'j', 'k'},
    output_indices=['i', 'j'],
    summed_indices={'k'},           # k appears twice on RHS
    elementwise_indices={'i', 'j'}, # i, j appear once each on RHS
    index_dimensions={
        'i': dim(A, 0),
        'j': dim(B, 1),
        'k': dim(A, 1),  # must equal dim(B, 0)
    }
)
```

### Phase 3: Computation Graph Construction

#### 3.1 Graph Nodes

```python
class GraphNode:
    """Base class for computation graph nodes."""
    inputs: List[GraphNode]
    output_type: Type
    output_shape: Tuple[Expression, ...]

class InputNode(GraphNode):
    """Function parameter."""
    name: str
    param_index: int

class ConstantNode(GraphNode):
    """Constant value (e.g., from formula call)."""
    value: Any

class GEMMNode(GraphNode):
    """Matrix multiply: C = A @ B"""
    A: GraphNode
    B: GraphNode
    # Optional: alpha, beta for C = alpha*A@B + beta*C
    alpha: float = 1.0
    beta: float = 0.0

class ElementwiseNode(GraphNode):
    """Element-wise operation."""
    operation: ElementwiseOp  # ADD, SUB, MUL, DIV, etc.
    operands: List[GraphNode]

class TransposeNode(GraphNode):
    """Matrix transpose."""
    input: GraphNode
    axes: Tuple[int, ...]  # Permutation

class ReductionNode(GraphNode):
    """Reduction (sum, max, etc.) over axes."""
    input: GraphNode
    operation: ReductionOp
    axes: Tuple[int, ...]

class EinsumNode(GraphNode):
    """General Einstein summation (fallback for complex patterns)."""
    inputs: List[GraphNode]
    subscripts: str  # NumPy einsum format: 'ik,kj->ij'
```

#### 3.2 Pattern Recognition

Convert indexed assignments to graph nodes:

```python
class PatternRecognizer:
    """Recognize common patterns and emit optimized nodes."""
    
    def recognize(self, assignment: IndexedAssignment, 
                  analysis: IndexAnalysis) -> GraphNode:
        
        # Matrix multiply: C[i,j] = A[i,k] * B[k,j]
        if self._is_matmul(assignment, analysis):
            return self._emit_gemm(assignment)
        
        # Transpose: T[i,j] = A[j,i]
        if self._is_transpose(assignment, analysis):
            return self._emit_transpose(assignment)
        
        # Matrix-vector: y[i] = A[i,j] * x[j]
        if self._is_matvec(assignment, analysis):
            return self._emit_gemv(assignment)
        
        # Dot product: d = u[i] * v[i]
        if self._is_dot(assignment, analysis):
            return self._emit_dot(assignment)
        
        # Outer product: O[i,j] = u[i] * v[j]
        if self._is_outer(assignment, analysis):
            return self._emit_outer(assignment)
        
        # Trace: t = A[i,i]
        if self._is_trace(assignment, analysis):
            return self._emit_trace(assignment)
        
        # Element-wise: C[i,j] = A[i,j] + B[i,j]
        if self._is_elementwise(assignment, analysis):
            return self._emit_elementwise(assignment)
        
        # Fallback: general einsum
        return self._emit_einsum(assignment, analysis)
    
    def _is_matmul(self, assignment, analysis) -> bool:
        """Check for pattern: C[i,j] = A[i,k] * B[k,j]"""
        # Two inputs, one summed index, multiplication
        return (
            len(analysis.summed_indices) == 1 and
            len(analysis.output_indices) == 2 and
            self._is_multiplication(assignment.expression) and
            self._indices_match_matmul_pattern(assignment, analysis)
        )
```

### Phase 4: Graph Optimization

#### 4.1 Optimization Passes

```python
class GraphOptimizer:
    """Optimize computation graph before code generation."""
    
    def optimize(self, graph: ComputationGraph) -> ComputationGraph:
        graph = self.dead_code_elimination(graph)
        graph = self.constant_folding(graph)
        graph = self.operation_fusion(graph)
        graph = self.blas_pattern_matching(graph)
        return graph
    
    def dead_code_elimination(self, graph):
        """Remove nodes not reachable from output."""
        reachable = self._find_reachable(graph.output_node)
        return graph.filter(lambda n: n in reachable)
    
    def constant_folding(self, graph):
        """Evaluate operations on constants at compile time."""
        for node in graph.topological_order():
            if all(isinstance(inp, ConstantNode) for inp in node.inputs):
                result = self._evaluate(node)
                graph.replace(node, ConstantNode(result))
        return graph
    
    def operation_fusion(self, graph):
        """Fuse compatible adjacent operations."""
        # Example: GEMM followed by elementwise add → GEMM with beta
        # C = A @ B; D = C + E → D = 1.0*A@B + 1.0*E (single GEMM call)
        for node in graph.nodes:
            if isinstance(node, GEMMNode):
                for user in node.users:
                    if isinstance(user, ElementwiseNode) and user.operation == ADD:
                        fused = self._fuse_gemm_add(node, user)
                        graph.replace(user, fused)
        return graph
```

### Phase 5: Code Generation

#### 5.1 Backend Selection

```python
class DeclareCodeGenerator:
    """Generate code for declare functions."""
    
    def __init__(self, platform: Platform):
        self.platform = platform
        self.blas_backend = self._select_blas_backend()
    
    def _select_blas_backend(self):
        if self.platform.is_macos:
            return AccelerateBackend()
        elif self.platform.has_cuda:
            return CuBLASBackend()
        else:
            return OpenBLASBackend()
    
    def generate(self, func: DeclareFunction) -> LLVMFunction:
        # Build computation graph
        graph = self.build_graph(func.body)
        
        # Optimize
        graph = GraphOptimizer().optimize(graph)
        
        # Generate code for each node
        llvm_func = self.create_function_skeleton(func)
        
        for node in graph.topological_order():
            self.generate_node(node, llvm_func)
        
        return llvm_func
    
    def generate_node(self, node: GraphNode, llvm_func):
        if isinstance(node, GEMMNode):
            self.generate_gemm(node, llvm_func)
        elif isinstance(node, ElementwiseNode):
            self.generate_elementwise(node, llvm_func)
        elif isinstance(node, TransposeNode):
            self.generate_transpose(node, llvm_func)
        # ... etc
    
    def generate_gemm(self, node: GEMMNode, llvm_func):
        """Generate BLAS GEMM call."""
        # Emit call to cblas_sgemm or cblas_dgemm
        self.blas_backend.emit_gemm(
            llvm_func,
            A=node.A.output_buffer,
            B=node.B.output_buffer,
            C=node.output_buffer,
            M=node.A.shape[0],
            N=node.B.shape[1],
            K=node.A.shape[1],
            alpha=node.alpha,
            beta=node.beta
        )
```

#### 5.2 Calling Formula from Declare

When a `declare` body calls a `formula`:

```python
def handle_formula_call(self, call: FunctionCall, graph: ComputationGraph):
    """Formula calls evaluate eagerly; result becomes constant node."""
    
    # Generate code to call the formula
    result_value = self.emit_formula_call(call)
    
    # Result becomes a constant in the graph
    return ConstantNode(result_value)
```

---

## Testing

### Parser Tests

```python
def test_parse_declare_function():
    source = """
    declare matmul(A: [[float32]], B: [[float32]]) -> [[float32]]:
        C[i,j] = A[i,k] * B[k,j]
        return C
    ~
    """
    ast = parse(source)
    assert ast.functions[0].kind == FunctionKind.DECLARE
    assert isinstance(ast.functions[0].body.statements[0], IndexedAssignment)

def test_parse_einstein_indices():
    source = """
    declare trace(A: [[float32]]) -> float32:
        t = A[i,i]
        return t
    ~
    """
    ast = parse(source)
    stmt = ast.functions[0].body.statements[0]
    # t has no indices (scalar output)
    # A[i,i] has repeated index (implies sum)
```

### Index Analysis Tests

```python
def test_matmul_index_analysis():
    assignment = parse_assignment("C[i,j] = A[i,k] * B[k,j]")
    analysis = analyze_indices(assignment)
    
    assert analysis.output_indices == ['i', 'j']
    assert analysis.summed_indices == {'k'}
    assert 'i' in analysis.elementwise_indices
    assert 'j' in analysis.elementwise_indices

def test_trace_index_analysis():
    assignment = parse_assignment("t = A[i,i]")
    analysis = analyze_indices(assignment)
    
    assert analysis.output_indices == []  # Scalar
    assert analysis.summed_indices == {'i'}
```

### Pattern Recognition Tests

```python
def test_recognize_gemm():
    assignment = parse_assignment("C[i,j] = A[i,k] * B[k,j]")
    node = PatternRecognizer().recognize(assignment)
    assert isinstance(node, GEMMNode)

def test_recognize_transpose():
    assignment = parse_assignment("T[i,j] = A[j,i]")
    node = PatternRecognizer().recognize(assignment)
    assert isinstance(node, TransposeNode)

def test_recognize_elementwise_add():
    assignment = parse_assignment("C[i,j] = A[i,j] + B[i,j]")
    node = PatternRecognizer().recognize(assignment)
    assert isinstance(node, ElementwiseNode)
    assert node.operation == ElementwiseOp.ADD
```

### End-to-End Tests

```python
def test_matmul_execution():
    source = """
    declare matmul(A: [[float32]], B: [[float32]]) -> [[float32]]:
        C[i,j] = A[i,k] * B[k,j]
        return C
    ~
    
    func main():
        A = [[1.0, 2.0], [3.0, 4.0]]
        B = [[5.0, 6.0], [7.0, 8.0]]
        C = matmul(A, B)
        print(C)
    ~
    """
    # [[1*5+2*7, 1*6+2*8], [3*5+4*7, 3*6+4*8]]
    # [[19, 22], [43, 50]]
    assert run(source) == "[[19.0, 22.0], [43.0, 50.0]]"

def test_declare_calls_formula():
    source = """
    formula scale_factor(n: int) -> float32:
        if n <= 1: 1.0 else: float32(n) * scale_factor(n - 1)
    ~
    
    declare scaled_matrix(A: [[float32]], n: int) -> [[float32]]:
        factor = scale_factor(n)
        B[i,j] = A[i,j] * factor
        return B
    ~
    
    func main():
        A = [[1.0, 2.0], [3.0, 4.0]]
        B = scaled_matrix(A, 3)  # factor = 6.0
        print(B)
    ~
    """
    assert run(source) == "[[6.0, 12.0], [18.0, 24.0]]"

def test_formula_cannot_call_declare():
    source = """
    declare matmul(A: [[float32]], B: [[float32]]) -> [[float32]]:
        C[i,j] = A[i,k] * B[k,j]
        return C
    ~
    
    formula bad(A: [[float32]], B: [[float32]]) -> [[float32]]:
        matmul(A, B)
    ~
    """
    assert_compile_error(source, "Formula 'bad' cannot call declare 'matmul'")
```

### BLAS Routing Tests

```python
def test_gemm_routes_to_blas():
    source = """
    declare matmul(A: [[float32]], B: [[float32]]) -> [[float32]]:
        C[i,j] = A[i,k] * B[k,j]
        return C
    ~
    """
    ir = compile_to_ir(source)
    assert "cblas_sgemm" in ir or "cublasSgemm" in ir
```

---

## Diagnostics

### Compile-Time Errors

```
error: Index dimension mismatch in declare 'matmul'
  --> source.coex:3:5
   |
 3 |     C[i,j] = A[i,k] * B[k,j]
   |              ^^^^^^   ^^^^^^
   |
   = note: index 'k' has dimension 3 from A[i,k]
   = note: index 'k' has dimension 5 from B[k,j]
   = note: these must be equal for matrix multiplication
```

```
error: Formula 'compute' cannot call declare 'matmul'
  --> source.coex:10:9
   |
10 |         matmul(A, B)
   |         ^^^^^^^^^^^^
   |
   = note: formulas may only call other formulas
   = note: 'matmul' is a declare function
   = help: consider restructuring so the func/task calls the declare
```

```
error: Invalid index expression in declare body
  --> source.coex:5:5
   |
 5 |     C[i,j] = A[i,k] * B[k,j] + side_effect()
   |                                ^^^^^^^^^^^^^
   |
   = note: declare bodies must be pure
   = note: 'side_effect' is a func which may have side effects
```

### Compiler Diagnostics

```
#@ Compiling declare 'matmul' (line 5):
#@   Pattern recognized: GEMM (matrix multiply)
#@   Index analysis: sum over k, output indices i,j
#@   Backend: Accelerate cblas_sgemm
#@   Optimization: None needed (single operation)
```

---

## Summary

The `declare` function kind introduces:

1. **New keyword**: `declare` as a function kind
2. **Einstein notation**: `C[i,j] = A[i,k] * B[k,j]` syntax with implicit summation
3. **Computation graph**: Lazy evaluation model with optimization passes
4. **Pattern recognition**: Common patterns (GEMM, transpose, etc.) route to BLAS
5. **Calling hierarchy**: `declare` → `formula` allowed, reverse prohibited

Implementation requires:
- Parser changes for `declare` keyword and indexed assignment syntax
- New AST nodes for Einstein notation
- Index analysis pass for summation convention
- Computation graph builder
- Pattern recognizer for BLAS operations
- Graph optimizer
- Code generator targeting BLAS backends
