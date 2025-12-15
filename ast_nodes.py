"""
Coex AST Node Definitions

Complete AST for the Coex language, covering all constructs.
Concurrency primitives are included but will execute sequentially for now.
"""

from dataclasses import dataclass, field
from typing import List, Optional, Union, Dict, Any
from enum import Enum, auto


# ============================================================================
# Enums
# ============================================================================

class FunctionKind(Enum):
    FORMULA = auto()
    TASK = auto()
    FUNC = auto()


class BinaryOp(Enum):
    # Arithmetic
    ADD = "+"
    SUB = "-"
    MUL = "*"
    DIV = "/"
    MOD = "%"
    # Comparison
    EQ = "=="
    NE = "!="
    LT = "<"
    GT = ">"
    LE = "<="
    GE = ">="
    # Logical
    AND = "and"
    OR = "or"
    # Other
    RANGE = ".."
    NULL_COALESCE = "??"


class UnaryOp(Enum):
    NEG = "-"
    NOT = "not"
    AWAIT = "await"


class AssignOp(Enum):
    ASSIGN = "="
    MOVE_ASSIGN = ":="
    PLUS_ASSIGN = "+="
    MINUS_ASSIGN = "-="
    STAR_ASSIGN = "*="
    SLASH_ASSIGN = "/="
    PERCENT_ASSIGN = "%="


class SelectStrategy(Enum):
    DEFAULT = auto()
    FAIR = auto()
    RANDOM = auto()
    PRIORITY = auto()


# ============================================================================
# Type Nodes
# ============================================================================

@dataclass
class Type:
    """Base class for types"""
    pass


@dataclass
class PrimitiveType(Type):
    name: str  # "int", "float", "bool", "string", "byte", "char"
    
    def __repr__(self):
        return self.name


@dataclass
class AtomicType(Type):
    inner: str  # "int", "float", "bool"
    
    def __repr__(self):
        return f"atomic_{self.inner}"


@dataclass
class OptionalType(Type):
    inner: Type
    
    def __repr__(self):
        return f"{self.inner}?"


@dataclass
class ListType(Type):
    element_type: Type
    
    def __repr__(self):
        return f"List<{self.element_type}>"


@dataclass
class MapType(Type):
    key_type: Type
    value_type: Type
    
    def __repr__(self):
        return f"Map<{self.key_type}, {self.value_type}>"


@dataclass
class SetType(Type):
    element_type: Type

    def __repr__(self):
        return f"Set<{self.element_type}>"


@dataclass
class ArrayType(Type):
    element_type: Type

    def __repr__(self):
        return f"Array<{self.element_type}>"


@dataclass
class ChannelType(Type):
    element_type: Type
    
    def __repr__(self):
        return f"Channel<{self.element_type}>"


@dataclass
class TupleType(Type):
    elements: List[tuple]  # List of (name, type) or (None, type)
    
    def __repr__(self):
        parts = [f"{n}: {t}" if n else str(t) for n, t in self.elements]
        return f"({', '.join(parts)})"


@dataclass
class FunctionType(Type):
    kind: FunctionKind
    param_types: List[Type]
    return_type: Optional[Type]
    
    def __repr__(self):
        params = ", ".join(str(t) for t in self.param_types)
        ret = f" -> {self.return_type}" if self.return_type else ""
        return f"{self.kind.name.lower()}({params}){ret}"


@dataclass
class NamedType(Type):
    """User-defined type reference"""
    name: str
    type_args: List[Type] = field(default_factory=list)
    
    def __repr__(self):
        if self.type_args:
            args = ", ".join(str(t) for t in self.type_args)
            return f"{self.name}<{args}>"
        return self.name


# ============================================================================
# Expression Nodes
# ============================================================================

@dataclass
class Expr:
    """Base class for expressions"""
    pass


@dataclass
class IntLiteral(Expr):
    value: int


@dataclass
class FloatLiteral(Expr):
    value: float


@dataclass
class BoolLiteral(Expr):
    value: bool


@dataclass
class StringLiteral(Expr):
    value: str


@dataclass
class CharLiteral(Expr):
    value: str  # Single character


@dataclass
class NilLiteral(Expr):
    pass


@dataclass
class Identifier(Expr):
    name: str
    type_args: List[Type] = field(default_factory=list)


@dataclass
class SelfExpr(Expr):
    """Reference to self in type methods"""
    pass


@dataclass
class CellExpr(Expr):
    """Reference to current cell in matrix formulas"""
    pass


@dataclass
class CellIndexExpr(Expr):
    """Relative cell access: cell[dx, dy]"""
    dx: Expr
    dy: Expr


@dataclass
class BinaryExpr(Expr):
    op: BinaryOp
    left: Expr
    right: Expr


@dataclass
class UnaryExpr(Expr):
    op: UnaryOp
    operand: Expr


@dataclass
class TernaryExpr(Expr):
    condition: Expr
    then_expr: Expr
    else_expr: Expr


@dataclass
class CallExpr(Expr):
    callee: Expr
    args: List[Expr]
    named_args: Dict[str, Expr] = field(default_factory=dict)


@dataclass
class MethodCallExpr(Expr):
    """obj.method(args)"""
    object: Expr
    method: str
    args: List[Expr]
    type_args: List[Type] = field(default_factory=list)


@dataclass
class MemberExpr(Expr):
    """obj.field"""
    object: Expr
    member: str


@dataclass
class IndexExpr(Expr):
    """obj[index] or obj[index1, index2]"""
    object: Expr
    indices: List[Expr]


@dataclass
class ListExpr(Expr):
    elements: List[Expr]


@dataclass
class MapExpr(Expr):
    """Map literal: {key: value, ...}"""
    entries: List[tuple]  # List of (key_expr, value_expr)


@dataclass
class SetExpr(Expr):
    """Set literal: {a, b, c}"""
    elements: List[Expr]


@dataclass
class TupleExpr(Expr):
    """Tuple literal: (a, b, c) or (name: a, other: b)"""
    elements: List[tuple]  # List of (name, expr) or (None, expr)


@dataclass
class RangeExpr(Expr):
    """start..end"""
    start: Expr
    end: Expr


@dataclass
class LambdaExpr(Expr):
    """formula(_ x: int) => x * 2"""
    kind: FunctionKind
    params: List['Parameter']
    body: Expr


@dataclass
class ComprehensionClause:
    """A single for/if clause in a comprehension: for pattern in iterable if condition"""
    pattern: 'Pattern'
    iterable: Expr
    condition: Optional[Expr] = None


@dataclass
class ListComprehension(Expr):
    """[expr for pattern in iterable if condition]"""
    body: Expr
    clauses: List[ComprehensionClause]


@dataclass
class SetComprehension(Expr):
    """{expr for pattern in iterable if condition}"""
    body: Expr
    clauses: List[ComprehensionClause]


@dataclass
class MapComprehension(Expr):
    """{key: value for pattern in iterable if condition}"""
    key: Expr
    value: Expr
    clauses: List[ComprehensionClause]


@dataclass
class ChannelReceiveExpr(Expr):
    """<- channel"""
    channel: Expr


@dataclass
class LlvmBinding:
    """Maps a Coex variable to an LLVM register"""
    coex_name: str              # e.g., "x"
    llvm_register: str          # e.g., "%a"
    type_hint: Optional[str] = None  # e.g., "i64"


@dataclass
class LlvmIrExpr(Expr):
    """Inline LLVM IR expression (returns a value)

    Example:
        var result: int = llvm_ir(x -> %a, y -> %b) -> %r: i64 \"\"\"
            %r = add i64 %a, %b
            ret i64 %r
        \"\"\"
    """
    bindings: List[LlvmBinding]
    ir_body: str
    return_register: str        # e.g., "%result"
    return_type: str            # e.g., "i64"


@dataclass
class MatchExpr(Expr):
    """Match expression (returns value)"""
    subject: Expr
    arms: List['MatchArm']


# ============================================================================
# Pattern Nodes (for match)
# ============================================================================

@dataclass
class Pattern:
    """Base class for patterns"""
    pass


@dataclass
class WildcardPattern(Pattern):
    """Matches anything: _"""
    pass


@dataclass
class LiteralPattern(Pattern):
    """Matches a literal value"""
    value: Expr


@dataclass
class IdentifierPattern(Pattern):
    """Binds to a name"""
    name: str


@dataclass
class TuplePattern(Pattern):
    """Matches tuple: (a, b, c)"""
    elements: List[Pattern]


@dataclass
class ConstructorPattern(Pattern):
    """Matches enum variant: Some(x) or None"""
    name: str
    args: List[Pattern] = field(default_factory=list)


@dataclass
class MatchArm:
    """A single arm in a match expression"""
    pattern: Pattern
    guard: Optional[Expr]  # Optional guard: case x if x > 0
    body: List['Stmt']


# ============================================================================
# Statement Nodes
# ============================================================================

@dataclass
class Stmt:
    """Base class for statements"""
    pass


@dataclass
class VarDecl(Stmt):
    name: str
    type_annotation: Optional[Type]
    initializer: Expr
    is_mutable: bool = True  # var = mutable, no var = immutable
    is_move: bool = False  # True if := was used


@dataclass
class TupleDestructureStmt(Stmt):
    """Tuple destructuring: (a, b) = expr or (a, b) = func()"""
    names: List[str]  # Variable names to bind
    value: Expr


@dataclass
class Assignment(Stmt):
    target: Expr
    op: AssignOp
    value: Expr


@dataclass
class ExprStmt(Stmt):
    expr: Expr


@dataclass
class ReturnStmt(Stmt):
    value: Optional[Expr]


@dataclass
class BreakStmt(Stmt):
    pass


@dataclass
class ContinueStmt(Stmt):
    pass


@dataclass
class IfStmt(Stmt):
    condition: Expr
    then_body: List[Stmt]
    else_if_clauses: List[tuple]  # List of (condition, body) pairs
    else_body: Optional[List[Stmt]]


@dataclass
class ForStmt(Stmt):
    pattern: Union[str, Pattern]  # str for backward compat, Pattern for destructuring
    iterable: Expr
    body: List[Stmt]
    
    @property
    def var_name(self) -> Optional[str]:
        """Backward compatibility: return var name if pattern is simple identifier"""
        if isinstance(self.pattern, str):
            return self.pattern
        if isinstance(self.pattern, IdentifierPattern):
            return self.pattern.name
        return None


@dataclass
class ForAssignStmt(Stmt):
    """results = for item in items expr ~"""
    target: str
    pattern: Union[str, Pattern]  # str for backward compat, Pattern for destructuring
    iterable: Expr
    body_expr: Expr
    
    @property
    def var_name(self) -> Optional[str]:
        """Backward compatibility"""
        if isinstance(self.pattern, str):
            return self.pattern
        if isinstance(self.pattern, IdentifierPattern):
            return self.pattern.name
        return None


@dataclass
class LoopStmt(Stmt):
    body: List[Stmt]


@dataclass
class WhileStmt(Stmt):
    """Standard while loop: while condition block"""
    condition: Expr
    body: List[Stmt]


@dataclass
class CycleStmt(Stmt):
    """Cycle statement (double-buffered synchronous iteration)

    while condition cycle
      # body with double-buffered locals
    ~

    The condition is evaluated in outer scope after each generation.
    Variables declared in the body are double-buffered:
    - Reads see the previous generation's values
    - Writes go to the current generation's buffer
    - At iteration end, buffers swap
    """
    condition: Expr
    body: List[Stmt]


@dataclass
class MatchStmt(Stmt):
    """Match statement (no return value)"""
    subject: Expr
    arms: List[MatchArm]


@dataclass
class SelectStmt(Stmt):
    """Select on multiple channels"""
    strategy: SelectStrategy
    timeout: Optional[Expr]
    cases: List['SelectCase']


@dataclass
class SelectCase:
    """case item <- channel: body"""
    var_name: str
    channel: Expr
    body: List[Stmt]


@dataclass
class WithinStmt(Stmt):
    """within timeout: body else: fallback"""
    timeout: Expr
    body: List[Stmt]
    else_body: Optional[List[Stmt]]


@dataclass
class ChannelSendStmt(Stmt):
    """channel.send(value)"""
    channel: Expr
    value: Expr


@dataclass
class PrintStmt(Stmt):
    """Built-in print for testing"""
    value: Expr


@dataclass
class LlvmIrStmt(Stmt):
    """Inline LLVM IR statement (void, no return value)

    Example:
        llvm_ir \"\"\"
            fence seq_cst
            ret void
        \"\"\"
    """
    bindings: List[LlvmBinding]
    ir_body: str


# ============================================================================
# Declaration Nodes
# ============================================================================

@dataclass
class Parameter:
    name: str
    type_annotation: Type
    positional: bool = False  # True if prefixed with _
    default_value: Optional[Expr] = None


@dataclass
class FunctionDecl:
    kind: FunctionKind
    name: str
    type_params: List['TypeParam'] = field(default_factory=list)
    params: List[Parameter] = field(default_factory=list)
    return_type: Optional[Type] = None
    body: List[Stmt] = field(default_factory=list)


@dataclass
class TypeParam:
    """Generic type parameter: T or T: Trait"""
    name: str
    bounds: List[str] = field(default_factory=list)  # Trait bounds


@dataclass
class GlobalVarDecl:
    name: str
    type_annotation: Type
    initializer: Expr


@dataclass
class FieldDecl:
    """Field in a type declaration"""
    name: str
    type_annotation: Type
    default_value: Optional[Expr] = None


@dataclass
class TypeDecl:
    """User-defined type"""
    name: str
    type_params: List[TypeParam] = field(default_factory=list)
    fields: List[FieldDecl] = field(default_factory=list)
    methods: List[FunctionDecl] = field(default_factory=list)
    variants: List['EnumVariant'] = field(default_factory=list)  # For enums


@dataclass
class EnumVariant:
    """Variant in an enum type"""
    name: str
    fields: List[FieldDecl] = field(default_factory=list)


@dataclass
class TraitDecl:
    """Trait declaration"""
    name: str
    type_params: List[TypeParam] = field(default_factory=list)
    methods: List[FunctionDecl] = field(default_factory=list)  # Abstract methods


@dataclass
class MatrixDecl:
    """Matrix (cellular automaton) declaration"""
    name: str
    width: Expr
    height: Expr
    element_type: Type
    init_value: Expr
    methods: List[FunctionDecl] = field(default_factory=list)


@dataclass
class ImportDecl:
    """Import declaration: import module_name"""
    module: str  # e.g., "math"


@dataclass
class ReplaceDecl:
    """Replace declaration: replace shortname with module.function"""
    shortname: str       # e.g., "abs"
    module: str          # e.g., "math"
    qualified_name: str  # e.g., "abs" (the function name in the module)


# ============================================================================
# Program Node
# ============================================================================

@dataclass
class Program:
    imports: List[ImportDecl] = field(default_factory=list)
    replaces: List['ReplaceDecl'] = field(default_factory=list)
    globals: List[GlobalVarDecl] = field(default_factory=list)
    types: List[TypeDecl] = field(default_factory=list)
    traits: List[TraitDecl] = field(default_factory=list)
    matrices: List[MatrixDecl] = field(default_factory=list)
    functions: List[FunctionDecl] = field(default_factory=list)
