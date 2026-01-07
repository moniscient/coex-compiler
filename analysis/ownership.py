"""
Ownership Analysis for Coex

Tracks ownership state through the program and detects violations:
- Use-after-move errors for unique bindings
- Invalid operations on borrowed bindings
- Inconsistent ownership across control flow branches
- Invalid moves inside loops

This implements the declared uniqueness system where:
- `unique` bindings have sole ownership and can be moved
- `=` operator moves unique bindings (source invalidated)
- `:=` operator copies (source preserved)
- `borrow` parameters allow read-only access without ownership transfer
"""

from dataclasses import dataclass, field
from enum import Enum
from typing import List, Dict, Set, Optional, Tuple, Any
from .cfg import CFG, BasicBlock, build_cfg, collect_expr_uses, collect_stmt_uses, collect_stmt_defs
from ast_nodes import (
    FunctionDecl, Stmt, VarDecl, Assignment, Identifier, Expr, AssignOp,
    ReturnStmt, IfStmt, WhileStmt, ForStmt, MatchStmt, CallExpr, MethodCallExpr,
    Type, ArrayType, PrimitiveType, Parameter
)


class OwnershipState(Enum):
    """Possible ownership states for a binding."""
    VALID = "valid"       # Binding is valid and can be used
    MOVED = "moved"       # Binding has been moved, cannot be used
    BORROWED = "borrowed" # Binding is borrowed (parameter only)


@dataclass
class SourceLocation:
    """Source location for error reporting."""
    line: int = 0
    column: int = 0

    def __str__(self):
        if self.line > 0:
            return f"line {self.line}"
        return "unknown location"


@dataclass
class BindingInfo:
    """Information about a variable binding's ownership."""
    name: str
    type: Optional[Type]
    is_unique: bool
    ownership: OwnershipState
    declared_at: Optional[SourceLocation] = None
    moved_at: Optional[SourceLocation] = None
    move_target: Optional[str] = None  # Name of binding it was moved to

    def is_valid(self) -> bool:
        return self.ownership == OwnershipState.VALID

    def is_moved(self) -> bool:
        return self.ownership == OwnershipState.MOVED

    def is_borrowed(self) -> bool:
        return self.ownership == OwnershipState.BORROWED


# Error codes for ownership violations
ERROR_CODES = {
    "use_after_move": "E0501",
    "move_in_loop": "E0502",
    "inconsistent_branch": "E0503",
    "mutate_borrowed": "E0504",
    "return_borrowed": "E0505",
    "move_borrowed": "E0506",
    "store_borrowed": "E0507",
    "unsupported_unique_type": "E0508",
}

# Helpful suggestions for each error type
ERROR_SUGGESTIONS = {
    "use_after_move": "hint: use ':=' instead of '=' to copy the value",
    "move_in_loop": "hint: use ':=' to copy inside the loop, or move before the loop",
    "inconsistent_branch": "hint: ensure the variable is moved on all branches or none",
    "mutate_borrowed": "hint: borrowed bindings are read-only; consider passing as owned",
    "return_borrowed": "hint: create a copy with ':=' before returning",
    "move_borrowed": "hint: borrowed bindings cannot be moved; consider passing as owned",
    "store_borrowed": "hint: borrowed bindings cannot be stored; consider passing as owned",
    "unsupported_unique_type": "hint: only Array<T> and String support 'unique' in this version",
}


@dataclass
class OwnershipError:
    """Represents an ownership violation."""
    kind: str  # "use_after_move", "move_in_loop", "inconsistent_branch", etc.
    message: str
    location: SourceLocation
    binding_name: str
    declared_at: Optional[SourceLocation] = None
    moved_at: Optional[SourceLocation] = None

    def format(self) -> str:
        """Format error for display."""
        error_code = ERROR_CODES.get(self.kind, "E0500")
        result = f"{error_code}: {self.message}"
        if self.location.line > 0:
            result = f"{self.location}: {result}"
        if self.moved_at and self.moved_at.line > 0:
            result += f"\n  note: '{self.binding_name}' was moved at {self.moved_at}"
        if self.declared_at and self.declared_at.line > 0:
            result += f"\n  note: '{self.binding_name}' was declared at {self.declared_at}"
        # Add suggestion
        suggestion = ERROR_SUGGESTIONS.get(self.kind)
        if suggestion:
            result += f"\n  {suggestion}"
        return result


# Warning codes
WARNING_CODES = {
    "unique_to_non_unique": "W0501",
}


@dataclass
class OwnershipWarning:
    """Represents an ownership warning (non-fatal)."""
    kind: str  # "unique_to_non_unique", etc.
    message: str
    location: SourceLocation
    binding_name: str

    def format(self) -> str:
        warning_code = WARNING_CODES.get(self.kind, "W0500")
        result = f"{warning_code}: {self.message}"
        if self.location.line > 0:
            result = f"{self.location}: {result}"
        return result


@dataclass
class OwnershipContext:
    """Ownership state at a program point."""
    bindings: Dict[str, BindingInfo] = field(default_factory=dict)

    def copy(self) -> 'OwnershipContext':
        """Create a deep copy of this context."""
        new_ctx = OwnershipContext()
        for name, info in self.bindings.items():
            new_ctx.bindings[name] = BindingInfo(
                name=info.name,
                type=info.type,
                is_unique=info.is_unique,
                ownership=info.ownership,
                declared_at=info.declared_at,
                moved_at=info.moved_at,
                move_target=info.move_target
            )
        return new_ctx

    def get_binding(self, name: str) -> Optional[BindingInfo]:
        return self.bindings.get(name)

    def set_binding(self, name: str, info: BindingInfo):
        self.bindings[name] = info

    def mark_moved(self, name: str, location: SourceLocation, target: Optional[str] = None):
        """Mark a binding as moved."""
        if name in self.bindings:
            self.bindings[name].ownership = OwnershipState.MOVED
            self.bindings[name].moved_at = location
            self.bindings[name].move_target = target

    def mark_valid(self, name: str):
        """Mark a binding as valid (e.g., after reassignment)."""
        if name in self.bindings:
            self.bindings[name].ownership = OwnershipState.VALID
            self.bindings[name].moved_at = None
            self.bindings[name].move_target = None


@dataclass
class FunctionOwnershipResult:
    """Results of ownership analysis for a function."""
    function_name: str
    errors: List[OwnershipError] = field(default_factory=list)
    warnings: List[OwnershipWarning] = field(default_factory=list)
    unique_bindings: Set[str] = field(default_factory=set)
    borrowed_params: Set[str] = field(default_factory=set)

    def has_errors(self) -> bool:
        return len(self.errors) > 0

    def format_errors(self) -> str:
        return "\n".join(e.format() for e in self.errors)

    def format_warnings(self) -> str:
        return "\n".join(w.format() for w in self.warnings)


def _get_source_location(node: Any) -> SourceLocation:
    """Extract source location from an AST node."""
    if hasattr(node, 'line') and node.line:
        col = getattr(node, 'column', 0) or 0
        return SourceLocation(line=node.line, column=col)
    return SourceLocation()


def _is_supported_unique_type(type_ann: Optional[Type]) -> bool:
    """Check if a type supports unique ownership."""
    if type_ann is None:
        return False
    if isinstance(type_ann, ArrayType):
        return True
    if isinstance(type_ann, PrimitiveType) and type_ann.name == "string":
        return True
    return False


class OwnershipAnalyzer:
    """
    Analyzes ownership and detects violations in a function.

    The analysis tracks:
    1. Which bindings are declared `unique`
    2. When unique bindings are moved (via `=` operator)
    3. When moved bindings are used (error)
    4. Control flow merging for branches
    5. Loop body moves (error - would invalidate on second iteration)
    """

    def __init__(self, func: FunctionDecl):
        self.func = func
        self.errors: List[OwnershipError] = []
        self.warnings: List[OwnershipWarning] = []
        self.unique_bindings: Set[str] = set()
        self.borrowed_params: Set[str] = set()

        # Track loop nesting for move-in-loop detection
        self.loop_depth = 0

        # Current ownership context
        self.context = OwnershipContext()

    def analyze(self) -> FunctionOwnershipResult:
        """Run ownership analysis on the function."""
        # Initialize context with parameters
        self._init_parameters()

        # Analyze function body
        self._analyze_statements(self.func.body)

        return FunctionOwnershipResult(
            function_name=self.func.name,
            errors=self.errors,
            warnings=self.warnings,
            unique_bindings=self.unique_bindings,
            borrowed_params=self.borrowed_params
        )

    def _init_parameters(self):
        """Initialize ownership context with function parameters."""
        for param in self.func.params:
            is_unique = getattr(param, 'is_unique', False)
            is_borrow = getattr(param, 'is_borrow', False)

            if is_unique:
                self.unique_bindings.add(param.name)

            if is_borrow:
                self.borrowed_params.add(param.name)
                ownership = OwnershipState.BORROWED
            else:
                ownership = OwnershipState.VALID

            self.context.set_binding(param.name, BindingInfo(
                name=param.name,
                type=param.type_annotation,
                is_unique=is_unique,
                ownership=ownership
            ))

    def _analyze_statements(self, stmts: List[Stmt]):
        """Analyze a list of statements."""
        for stmt in stmts:
            self._analyze_statement(stmt)

    def _analyze_statement(self, stmt: Stmt):
        """Analyze a single statement for ownership violations."""
        if isinstance(stmt, VarDecl):
            self._analyze_var_decl(stmt)
        elif isinstance(stmt, Assignment):
            self._analyze_assignment(stmt)
        elif isinstance(stmt, ReturnStmt):
            self._analyze_return(stmt)
        elif isinstance(stmt, IfStmt):
            self._analyze_if(stmt)
        elif isinstance(stmt, WhileStmt):
            self._analyze_while(stmt)
        elif isinstance(stmt, ForStmt):
            self._analyze_for(stmt)
        elif isinstance(stmt, MatchStmt):
            self._analyze_match(stmt)
        elif isinstance(stmt, CallExpr):
            self._analyze_call_expr(stmt, _get_source_location(stmt))
        elif isinstance(stmt, MethodCallExpr):
            self._analyze_method_call(stmt, _get_source_location(stmt))
        else:
            # For other statements, check for uses of moved variables
            self._check_expr_uses(getattr(stmt, 'value', None), _get_source_location(stmt))
            self._check_expr_uses(getattr(stmt, 'expr', None), _get_source_location(stmt))

    def _analyze_var_decl(self, stmt: VarDecl):
        """Analyze a variable declaration."""
        location = _get_source_location(stmt)
        is_unique = getattr(stmt, 'is_unique', False)
        is_copy = getattr(stmt, 'is_copy', False)

        # Check if unique is applied to unsupported type
        if is_unique and stmt.type_annotation:
            if not _is_supported_unique_type(stmt.type_annotation):
                self.errors.append(OwnershipError(
                    kind="unsupported_unique_type",
                    message=f"'unique' is only supported for Array<T> and String types, not '{stmt.type_annotation}'",
                    location=location,
                    binding_name=stmt.name
                ))

        # Check initializer for use of moved variables
        self._check_expr_uses(stmt.initializer, location)

        # Handle move from source variable
        if isinstance(stmt.initializer, Identifier) and not is_copy:
            source_name = stmt.initializer.name
            source_info = self.context.get_binding(source_name)

            if source_info:
                # Check for moving/storing borrowed binding
                if source_info.is_borrowed():
                    self.errors.append(OwnershipError(
                        kind="move_borrowed",
                        message=f"cannot move borrowed binding '{source_name}'",
                        location=location,
                        binding_name=source_name,
                        declared_at=source_info.declared_at
                    ))
                elif source_info.is_unique:
                    # Moving from a unique binding
                    if self.loop_depth > 0:
                        self.errors.append(OwnershipError(
                            kind="move_in_loop",
                            message=f"cannot move unique binding '{source_name}' inside a loop",
                            location=location,
                            binding_name=source_name,
                            declared_at=source_info.declared_at
                        ))
                    else:
                        # Mark source as moved
                        self.context.mark_moved(source_name, location, stmt.name)

        # Check for storing borrowed binding (even with copy operator)
        if isinstance(stmt.initializer, Identifier) and is_copy:
            source_name = stmt.initializer.name
            source_info = self.context.get_binding(source_name)
            if source_info and source_info.is_borrowed():
                self.errors.append(OwnershipError(
                    kind="store_borrowed",
                    message=f"cannot store borrowed binding '{source_name}'",
                    location=location,
                    binding_name=source_name,
                    declared_at=source_info.declared_at
                ))

        # Register the new binding
        if is_unique:
            self.unique_bindings.add(stmt.name)

        self.context.set_binding(stmt.name, BindingInfo(
            name=stmt.name,
            type=stmt.type_annotation,
            is_unique=is_unique,
            ownership=OwnershipState.VALID,
            declared_at=location
        ))

    def _analyze_assignment(self, stmt: Assignment):
        """Analyze an assignment statement."""
        location = _get_source_location(stmt)
        is_copy = stmt.op == AssignOp.COPY_ASSIGN

        # Check RHS for use of moved variables
        self._check_expr_uses(stmt.value, location)

        if isinstance(stmt.target, Identifier):
            target_name = stmt.target.name
            target_info = self.context.get_binding(target_name)

            # Check for mutating borrowed binding
            if target_info and target_info.is_borrowed():
                self.errors.append(OwnershipError(
                    kind="mutate_borrowed",
                    message=f"cannot mutate borrowed binding '{target_name}'",
                    location=location,
                    binding_name=target_name,
                    declared_at=target_info.declared_at
                ))
                return  # Don't process further

            # Reassignment makes a moved variable valid again
            if target_info and target_info.is_moved():
                self.context.mark_valid(target_name)

            # Handle move/store from source
            if isinstance(stmt.value, Identifier):
                source_name = stmt.value.name
                source_info = self.context.get_binding(source_name)

                if source_info:
                    # Check for moving/storing borrowed binding
                    if source_info.is_borrowed():
                        error_kind = "store_borrowed" if is_copy else "move_borrowed"
                        self.errors.append(OwnershipError(
                            kind=error_kind,
                            message=f"cannot {'store' if is_copy else 'move'} borrowed binding '{source_name}'",
                            location=location,
                            binding_name=source_name,
                            declared_at=source_info.declared_at
                        ))
                    elif source_info.is_unique and not is_copy:
                        # Moving from a unique binding
                        if self.loop_depth > 0:
                            self.errors.append(OwnershipError(
                                kind="move_in_loop",
                                message=f"cannot move unique binding '{source_name}' inside a loop",
                                location=location,
                                binding_name=source_name,
                                declared_at=source_info.declared_at
                            ))
                        else:
                            self.context.mark_moved(source_name, location, target_name)
        else:
            # Check target expression for uses (e.g., arr[i] = x)
            self._check_expr_uses(stmt.target, location)

            # Check for mutating through borrowed binding (e.g., borrowed_arr[i] = x)
            if hasattr(stmt.target, 'object') and isinstance(stmt.target.object, Identifier):
                base_name = stmt.target.object.name
                base_info = self.context.get_binding(base_name)
                if base_info and base_info.is_borrowed():
                    self.errors.append(OwnershipError(
                        kind="mutate_borrowed",
                        message=f"cannot mutate through borrowed binding '{base_name}'",
                        location=location,
                        binding_name=base_name,
                        declared_at=base_info.declared_at
                    ))

    def _analyze_return(self, stmt: ReturnStmt):
        """Analyze a return statement."""
        location = _get_source_location(stmt)

        if stmt.value:
            # Check for returning borrowed binding
            if isinstance(stmt.value, Identifier):
                binding = self.context.get_binding(stmt.value.name)
                if binding and binding.ownership == OwnershipState.BORROWED:
                    self.errors.append(OwnershipError(
                        kind="return_borrowed",
                        message=f"cannot return borrowed binding '{stmt.value.name}'",
                        location=location,
                        binding_name=stmt.value.name
                    ))

            self._check_expr_uses(stmt.value, location)

    def _analyze_if(self, stmt: IfStmt):
        """Analyze if statement with branch merging."""
        location = _get_source_location(stmt)

        # Check condition
        self._check_expr_uses(stmt.condition, location)

        # Save context before branches
        saved_context = self.context.copy()

        # Analyze then branch
        self._analyze_statements(stmt.then_body)
        then_context = self.context

        # Analyze elif branches
        elif_contexts = []
        for elif_cond, elif_body in stmt.else_if_clauses:
            self.context = saved_context.copy()
            self._check_expr_uses(elif_cond, location)
            self._analyze_statements(elif_body)
            elif_contexts.append(self.context)

        # Analyze else branch
        else_context = None
        if stmt.else_body:
            self.context = saved_context.copy()
            self._analyze_statements(stmt.else_body)
            else_context = self.context

        # Merge contexts
        all_contexts = [then_context] + elif_contexts
        if else_context:
            all_contexts.append(else_context)
        else:
            # No else branch - original context also flows through
            all_contexts.append(saved_context)

        self.context = self._merge_contexts(all_contexts, location)

    def _analyze_while(self, stmt: WhileStmt):
        """Analyze while loop."""
        location = _get_source_location(stmt)

        # Check condition
        self._check_expr_uses(stmt.condition, location)

        # Enter loop
        self.loop_depth += 1

        # Analyze body
        self._analyze_statements(stmt.body)

        # Exit loop
        self.loop_depth -= 1

    def _analyze_for(self, stmt: ForStmt):
        """Analyze for loop."""
        location = _get_source_location(stmt)

        # Check iterable
        self._check_expr_uses(stmt.iterable, location)

        # Register loop variable
        loop_var = stmt.pattern if isinstance(stmt.pattern, str) else getattr(stmt.pattern, 'name', None)
        if loop_var:
            self.context.set_binding(loop_var, BindingInfo(
                name=loop_var,
                type=None,  # Type inferred from iterable
                is_unique=False,
                ownership=OwnershipState.VALID,
                declared_at=location
            ))

        # Enter loop
        self.loop_depth += 1

        # Analyze body
        self._analyze_statements(stmt.body)

        # Exit loop
        self.loop_depth -= 1

    def _analyze_match(self, stmt: MatchStmt):
        """Analyze match statement."""
        location = _get_source_location(stmt)

        # Check subject
        self._check_expr_uses(stmt.subject, location)

        # Save context
        saved_context = self.context.copy()

        # Analyze each arm
        arm_contexts = []
        for arm in stmt.arms:
            self.context = saved_context.copy()
            # Register pattern bindings
            self._register_pattern_bindings(arm.pattern, location)
            self._analyze_statements(arm.body)
            arm_contexts.append(self.context)

        # Merge contexts
        if arm_contexts:
            self.context = self._merge_contexts(arm_contexts, location)

    def _register_pattern_bindings(self, pattern: Any, location: SourceLocation):
        """Register bindings introduced by a pattern."""
        if hasattr(pattern, 'name') and pattern.name:
            self.context.set_binding(pattern.name, BindingInfo(
                name=pattern.name,
                type=None,
                is_unique=False,
                ownership=OwnershipState.VALID,
                declared_at=location
            ))
        if hasattr(pattern, 'fields'):
            for field_pattern in pattern.fields:
                self._register_pattern_bindings(field_pattern, location)
        if hasattr(pattern, 'elements'):
            for elem in pattern.elements:
                self._register_pattern_bindings(elem, location)

    def _analyze_call_expr(self, expr: CallExpr, location: SourceLocation):
        """Analyze a call expression for ownership issues."""
        # Check callee
        self._check_expr_uses(expr.callee, location)

        # Check arguments
        for arg in expr.args:
            self._check_expr_uses(arg, location)

            # Warn if passing unique to non-unique parameter
            if isinstance(arg, Identifier):
                binding = self.context.get_binding(arg.name)
                if binding and binding.is_unique:
                    # TODO: Check if callee parameter is unique
                    # For now, just warn
                    self.warnings.append(OwnershipWarning(
                        kind="unique_to_non_unique",
                        message=f"unique binding '{arg.name}' passed to function; uniqueness may be lost",
                        location=location,
                        binding_name=arg.name
                    ))

    def _analyze_method_call(self, expr: MethodCallExpr, location: SourceLocation):
        """Analyze a method call for ownership issues."""
        # Check receiver
        self._check_expr_uses(expr.object, location)

        # Check arguments
        for arg in expr.args:
            self._check_expr_uses(arg, location)

    def _check_expr_uses(self, expr: Optional[Expr], location: SourceLocation):
        """Check an expression for uses of moved variables."""
        if expr is None:
            return

        if isinstance(expr, Identifier):
            binding = self.context.get_binding(expr.name)
            if binding and binding.is_moved():
                self.errors.append(OwnershipError(
                    kind="use_after_move",
                    message=f"use of moved value '{expr.name}'",
                    location=location,
                    binding_name=expr.name,
                    declared_at=binding.declared_at,
                    moved_at=binding.moved_at
                ))

        # Recursively check subexpressions
        if hasattr(expr, 'left'):
            self._check_expr_uses(expr.left, location)
        if hasattr(expr, 'right'):
            self._check_expr_uses(expr.right, location)
        if hasattr(expr, 'operand'):
            self._check_expr_uses(expr.operand, location)
        if hasattr(expr, 'object'):
            self._check_expr_uses(expr.object, location)
        if hasattr(expr, 'args') and isinstance(expr.args, list):
            for arg in expr.args:
                self._check_expr_uses(arg, location)
        if hasattr(expr, 'callee'):
            self._check_expr_uses(expr.callee, location)
        if hasattr(expr, 'condition'):
            self._check_expr_uses(expr.condition, location)
        if hasattr(expr, 'then_expr'):
            self._check_expr_uses(expr.then_expr, location)
        if hasattr(expr, 'else_expr'):
            self._check_expr_uses(expr.else_expr, location)
        if hasattr(expr, 'elements') and isinstance(expr.elements, list):
            for elem in expr.elements:
                if isinstance(elem, tuple):
                    self._check_expr_uses(elem[1], location)
                else:
                    self._check_expr_uses(elem, location)
        if hasattr(expr, 'entries') and isinstance(expr.entries, list):
            for key, val in expr.entries:
                self._check_expr_uses(key, location)
                self._check_expr_uses(val, location)
        if hasattr(expr, 'indices') and isinstance(expr.indices, list):
            for idx in expr.indices:
                self._check_expr_uses(idx, location)

    def _merge_contexts(self, contexts: List[OwnershipContext], location: SourceLocation) -> OwnershipContext:
        """
        Merge ownership contexts from multiple branches.

        Rules:
        - If moved on ALL branches -> MOVED
        - If moved on SOME branches -> ERROR (inconsistent state)
        - If valid on ALL branches -> VALID
        """
        if not contexts:
            return OwnershipContext()

        if len(contexts) == 1:
            return contexts[0]

        # Get all unique binding names
        all_names = set()
        for ctx in contexts:
            all_names.update(ctx.bindings.keys())

        merged = OwnershipContext()

        for name in all_names:
            # Collect states across branches
            states = []
            binding_info = None

            for ctx in contexts:
                info = ctx.get_binding(name)
                if info:
                    states.append(info.ownership)
                    if binding_info is None:
                        binding_info = info

            if not states or binding_info is None:
                continue

            # Check for unique binding with inconsistent state
            if binding_info.is_unique:
                moved_count = sum(1 for s in states if s == OwnershipState.MOVED)
                valid_count = sum(1 for s in states if s == OwnershipState.VALID)

                if moved_count > 0 and valid_count > 0:
                    # Inconsistent - moved on some but not all branches
                    self.errors.append(OwnershipError(
                        kind="inconsistent_branch",
                        message=f"unique binding '{name}' may or may not be moved depending on control flow",
                        location=location,
                        binding_name=name,
                        declared_at=binding_info.declared_at
                    ))
                    # Mark as moved in merged context (conservative)
                    merged.set_binding(name, BindingInfo(
                        name=name,
                        type=binding_info.type,
                        is_unique=binding_info.is_unique,
                        ownership=OwnershipState.MOVED,
                        declared_at=binding_info.declared_at,
                        moved_at=binding_info.moved_at
                    ))
                elif moved_count == len(states):
                    # Moved on all branches
                    merged.set_binding(name, BindingInfo(
                        name=name,
                        type=binding_info.type,
                        is_unique=binding_info.is_unique,
                        ownership=OwnershipState.MOVED,
                        declared_at=binding_info.declared_at,
                        moved_at=binding_info.moved_at
                    ))
                else:
                    # Valid on all branches
                    merged.set_binding(name, BindingInfo(
                        name=name,
                        type=binding_info.type,
                        is_unique=binding_info.is_unique,
                        ownership=OwnershipState.VALID,
                        declared_at=binding_info.declared_at
                    ))
            else:
                # Non-unique bindings - just copy the info
                merged.set_binding(name, BindingInfo(
                    name=name,
                    type=binding_info.type,
                    is_unique=binding_info.is_unique,
                    ownership=binding_info.ownership,
                    declared_at=binding_info.declared_at
                ))

        return merged


def analyze_ownership(func: FunctionDecl) -> FunctionOwnershipResult:
    """
    Analyze a function for ownership violations.

    Args:
        func: The function to analyze

    Returns:
        FunctionOwnershipResult with all errors and warnings
    """
    analyzer = OwnershipAnalyzer(func)
    return analyzer.analyze()


def check_program_ownership(functions: List[FunctionDecl]) -> Tuple[List[OwnershipError], List[OwnershipWarning]]:
    """
    Check ownership for all functions in a program.

    Returns:
        Tuple of (all_errors, all_warnings)
    """
    all_errors = []
    all_warnings = []

    for func in functions:
        result = analyze_ownership(func)
        all_errors.extend(result.errors)
        all_warnings.extend(result.warnings)

    return all_errors, all_warnings
