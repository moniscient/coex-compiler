"""
Task Analysis Module

Analyzes task function bodies to identify suspension points and determine
which local variables need to be hoisted to the coroutine frame.

A suspension point is a call to another task function. The compiler transforms
task bodies into state machines where each suspension point becomes a state
transition.
"""

from dataclasses import dataclass, field
from typing import List, Set, Dict, Optional, Tuple, Any
from ast_nodes import (
    FunctionDecl, FunctionKind, Parameter, Type, Stmt, Expr,
    VarDecl, Assignment, ExprStmt, ReturnStmt, IfStmt, ForStmt, WhileStmt,
    CallExpr, MethodCallExpr, Identifier, BinaryExpr, UnaryExpr, TernaryExpr,
    ListExpr, MapExpr, TupleExpr, IndexExpr, MemberExpr, MatchStmt, MatchArm,
    BreakStmt, ContinueStmt
)


@dataclass
class ControlFlowContext:
    """Tracks the control flow context for a suspension point."""
    kind: str                  # "if_then", "if_else", "if_elif", "for", "while", "match", or "top"
    parent_stmt: Optional[Any] # The containing control flow statement
    parent_stmt_index: int     # Index of parent statement in its body
    branch_index: int          # For elif: which branch (0=then, 1=else, 2+=elif)
    nested_stmt_index: int     # Index of statement within the branch body
    parent_context: Optional['ControlFlowContext']  # For nested control flow


@dataclass
class SuspensionPoint:
    """A point where a task may suspend (yield to scheduler)."""
    node: Any                  # The AST node containing the task call
    call_expr: Any             # The CallExpr or MethodCallExpr
    state_id: int              # Unique state number (0, 1, 2, ...)
    var_name: Optional[str]    # Variable receiving result (if VarDecl/Assignment)
    callee_name: str           # Name of the called task function
    stmt_index: int            # Index in the statement list
    context: Optional[ControlFlowContext] = None  # Control flow context if nested


@dataclass
class TaskAnalysis:
    """Result of analyzing a task body."""
    function_name: str
    parameters: List[Parameter]
    return_type: Optional[Type]
    suspension_points: List[SuspensionPoint]
    hoisted_locals: Dict[str, Type]  # Locals that span suspension points
    all_locals: Dict[str, Type]      # All local variables defined in the task


def analyze_task(func: FunctionDecl, task_functions: Set[str]) -> TaskAnalysis:
    """
    Analyze a task function to find suspension points and determine frame layout.

    Args:
        func: The task function declaration
        task_functions: Set of function names that are task functions

    Returns:
        TaskAnalysis with suspension points and hoisted locals
    """
    assert func.kind == FunctionKind.TASK, f"Expected task, got {func.kind}"

    # Find all suspension points
    suspension_points = find_suspension_points(func.body, task_functions)

    # Find all local variables
    all_locals = find_all_locals(func.body)

    # Compute which locals need to be hoisted (span suspension points)
    hoisted_locals = compute_hoisted_locals(func.body, suspension_points, all_locals)

    return TaskAnalysis(
        function_name=func.name,
        parameters=func.params,
        return_type=func.return_type,
        suspension_points=suspension_points,
        hoisted_locals=hoisted_locals,
        all_locals=all_locals
    )


def find_suspension_points(body: List[Stmt], task_functions: Set[str]) -> List[SuspensionPoint]:
    """
    Walk AST to find all suspension points (task calls).

    Returns list of SuspensionPoints in execution order.
    """
    points = []
    state_id = [0]  # Mutable counter

    def process_statements(stmts: List[Stmt], context: Optional[ControlFlowContext] = None):
        for i, stmt in enumerate(stmts):
            process_statement(stmt, i, context)

    def process_statement(stmt: Stmt, stmt_index: int, context: Optional[ControlFlowContext]):
        if isinstance(stmt, VarDecl):
            # Check if initializer contains a task call
            if stmt.initializer:
                call = find_task_call_in_expr(stmt.initializer, task_functions)
                if call:
                    callee_name = get_callee_name(call)
                    points.append(SuspensionPoint(
                        node=stmt,
                        call_expr=call,
                        state_id=state_id[0],
                        var_name=stmt.name,
                        callee_name=callee_name,
                        stmt_index=stmt_index,
                        context=context
                    ))
                    state_id[0] += 1

        elif isinstance(stmt, Assignment):
            # Check if value contains a task call
            call = find_task_call_in_expr(stmt.value, task_functions)
            if call:
                callee_name = get_callee_name(call)
                var_name = stmt.target.name if isinstance(stmt.target, Identifier) else None
                points.append(SuspensionPoint(
                    node=stmt,
                    call_expr=call,
                    state_id=state_id[0],
                    var_name=var_name,
                    callee_name=callee_name,
                    stmt_index=stmt_index,
                    context=context
                ))
                state_id[0] += 1

        elif isinstance(stmt, ExprStmt):
            # Check if expression is a task call
            call = find_task_call_in_expr(stmt.expr, task_functions)
            if call:
                callee_name = get_callee_name(call)
                points.append(SuspensionPoint(
                    node=stmt,
                    call_expr=call,
                    state_id=state_id[0],
                    var_name=None,
                    callee_name=callee_name,
                    stmt_index=stmt_index,
                    context=context
                ))
                state_id[0] += 1

        elif isinstance(stmt, ReturnStmt):
            # Check if return value contains a task call
            if stmt.value:
                call = find_task_call_in_expr(stmt.value, task_functions)
                if call:
                    callee_name = get_callee_name(call)
                    points.append(SuspensionPoint(
                        node=stmt,
                        call_expr=call,
                        state_id=state_id[0],
                        var_name="__return_value",
                        callee_name=callee_name,
                        stmt_index=stmt_index,
                        context=context
                    ))
                    state_id[0] += 1

        elif isinstance(stmt, IfStmt):
            # Check condition (though task calls in conditions are unusual)
            call = find_task_call_in_expr(stmt.condition, task_functions)
            if call:
                callee_name = get_callee_name(call)
                points.append(SuspensionPoint(
                    node=stmt,
                    call_expr=call,
                    state_id=state_id[0],
                    var_name="__if_cond",
                    callee_name=callee_name,
                    stmt_index=stmt_index,
                    context=context
                ))
                state_id[0] += 1

            # Process then branch with context
            then_context = ControlFlowContext(
                kind="if_then",
                parent_stmt=stmt,
                parent_stmt_index=stmt_index,
                branch_index=0,
                nested_stmt_index=0,  # Will be set per-statement
                parent_context=context
            )
            for i, then_stmt in enumerate(stmt.then_body):
                then_ctx = ControlFlowContext(
                    kind="if_then",
                    parent_stmt=stmt,
                    parent_stmt_index=stmt_index,
                    branch_index=0,
                    nested_stmt_index=i,
                    parent_context=context
                )
                process_statement(then_stmt, i, then_ctx)

            # Process else branch with context
            if stmt.else_body:
                for i, else_stmt in enumerate(stmt.else_body):
                    else_ctx = ControlFlowContext(
                        kind="if_else",
                        parent_stmt=stmt,
                        parent_stmt_index=stmt_index,
                        branch_index=1,
                        nested_stmt_index=i,
                        parent_context=context
                    )
                    process_statement(else_stmt, i, else_ctx)

            # Process elif branches
            for elif_idx, (elif_cond, elif_body) in enumerate(stmt.else_if_clauses):
                call = find_task_call_in_expr(elif_cond, task_functions)
                if call:
                    callee_name = get_callee_name(call)
                    elif_cond_ctx = ControlFlowContext(
                        kind="if_elif_cond",
                        parent_stmt=stmt,
                        parent_stmt_index=stmt_index,
                        branch_index=2 + elif_idx,
                        nested_stmt_index=-1,  # Condition, not body
                        parent_context=context
                    )
                    points.append(SuspensionPoint(
                        node=stmt,
                        call_expr=call,
                        state_id=state_id[0],
                        var_name="__elif_cond",
                        callee_name=callee_name,
                        stmt_index=stmt_index,
                        context=elif_cond_ctx
                    ))
                    state_id[0] += 1
                for i, elif_stmt in enumerate(elif_body):
                    elif_ctx = ControlFlowContext(
                        kind="if_elif",
                        parent_stmt=stmt,
                        parent_stmt_index=stmt_index,
                        branch_index=2 + elif_idx,
                        nested_stmt_index=i,
                        parent_context=context
                    )
                    process_statement(elif_stmt, i, elif_ctx)

        elif isinstance(stmt, ForStmt):
            # Process loop body with context
            for i, for_stmt in enumerate(stmt.body):
                for_ctx = ControlFlowContext(
                    kind="for",
                    parent_stmt=stmt,
                    parent_stmt_index=stmt_index,
                    branch_index=0,
                    nested_stmt_index=i,
                    parent_context=context
                )
                process_statement(for_stmt, i, for_ctx)

        elif isinstance(stmt, WhileStmt):
            # Check condition
            call = find_task_call_in_expr(stmt.condition, task_functions)
            if call:
                callee_name = get_callee_name(call)
                points.append(SuspensionPoint(
                    node=stmt,
                    call_expr=call,
                    state_id=state_id[0],
                    var_name="__while_cond",
                    callee_name=callee_name,
                    stmt_index=stmt_index,
                    context=context
                ))
                state_id[0] += 1
            # Process body with context
            for i, while_stmt in enumerate(stmt.body):
                while_ctx = ControlFlowContext(
                    kind="while",
                    parent_stmt=stmt,
                    parent_stmt_index=stmt_index,
                    branch_index=0,
                    nested_stmt_index=i,
                    parent_context=context
                )
                process_statement(while_stmt, i, while_ctx)

        elif isinstance(stmt, MatchStmt):
            # Process match arms with context
            for arm_idx, arm in enumerate(stmt.arms):
                for i, arm_stmt in enumerate(arm.body):
                    match_ctx = ControlFlowContext(
                        kind="match",
                        parent_stmt=stmt,
                        parent_stmt_index=stmt_index,
                        branch_index=arm_idx,
                        nested_stmt_index=i,
                        parent_context=context
                    )
                    process_statement(arm_stmt, i, match_ctx)

    process_statements(body)
    return points


def find_task_call_in_expr(expr: Expr, task_functions: Set[str]) -> Optional[Any]:
    """
    Find a task call in an expression. Returns the CallExpr/MethodCallExpr if found.

    For simplicity, we only handle the top-level call. Nested task calls
    (e.g., foo(bar()) where bar is a task) would need more complex handling.
    """
    if isinstance(expr, CallExpr):
        callee_name = get_callee_name(expr)
        if callee_name and callee_name in task_functions:
            return expr
        # Check arguments for task calls (nested)
        for arg in expr.args:
            call = find_task_call_in_expr(arg, task_functions)
            if call:
                return call

    elif isinstance(expr, MethodCallExpr):
        # Method calls on objects - check if it's a task method
        # For now, we don't handle task methods
        # Check arguments
        for arg in expr.args:
            call = find_task_call_in_expr(arg, task_functions)
            if call:
                return call

    elif isinstance(expr, BinaryExpr):
        call = find_task_call_in_expr(expr.left, task_functions)
        if call:
            return call
        return find_task_call_in_expr(expr.right, task_functions)

    elif isinstance(expr, UnaryExpr):
        return find_task_call_in_expr(expr.operand, task_functions)

    elif isinstance(expr, TernaryExpr):
        call = find_task_call_in_expr(expr.condition, task_functions)
        if call:
            return call
        call = find_task_call_in_expr(expr.then_expr, task_functions)
        if call:
            return call
        return find_task_call_in_expr(expr.else_expr, task_functions)

    elif isinstance(expr, ListExpr):
        for elem in expr.elements:
            call = find_task_call_in_expr(elem, task_functions)
            if call:
                return call

    elif isinstance(expr, TupleExpr):
        for _, elem in expr.elements:
            call = find_task_call_in_expr(elem, task_functions)
            if call:
                return call

    elif isinstance(expr, IndexExpr):
        call = find_task_call_in_expr(expr.object, task_functions)
        if call:
            return call
        return find_task_call_in_expr(expr.index, task_functions)

    elif isinstance(expr, MemberExpr):
        return find_task_call_in_expr(expr.object, task_functions)

    return None


def get_callee_name(call: Any) -> Optional[str]:
    """Get the name of the function being called."""
    if isinstance(call, CallExpr):
        if isinstance(call.callee, Identifier):
            return call.callee.name
    elif isinstance(call, MethodCallExpr):
        return call.method
    return None


def find_all_locals(body: List[Stmt]) -> Dict[str, Type]:
    """Find all local variable declarations in the function body."""
    from ast_nodes import ListExpr, MapExpr, SetExpr, StringLiteral, ListType, MapType, SetType, PrimitiveType
    locals_dict = {}

    def infer_type_from_expr(expr) -> Optional[Type]:
        """Infer type from an expression for frame field generation."""
        if isinstance(expr, ListExpr):
            # List literal - infer element type from first element if possible
            if expr.elements:
                elem_type = infer_type_from_expr(expr.elements[0])
                return ListType(element_type=elem_type)
            return ListType(element_type=None)
        elif isinstance(expr, MapExpr):
            return MapType(key_type=None, value_type=None)
        elif isinstance(expr, SetExpr):
            return SetType(element_type=None)
        elif isinstance(expr, StringLiteral):
            return PrimitiveType(name="string")
        return None

    def process_statements(stmts: List[Stmt]):
        for stmt in stmts:
            process_statement(stmt)

    def process_statement(stmt: Stmt):
        if isinstance(stmt, VarDecl):
            if stmt.type_annotation:
                locals_dict[stmt.name] = stmt.type_annotation
            elif stmt.initializer:
                # Try to infer type from initializer
                inferred = infer_type_from_expr(stmt.initializer)
                locals_dict[stmt.name] = inferred
            else:
                # Type will be inferred during codegen
                locals_dict[stmt.name] = None

        elif isinstance(stmt, IfStmt):
            process_statements(stmt.then_body)
            if stmt.else_body:
                process_statements(stmt.else_body)
            for _, elif_body in stmt.else_if_clauses:
                process_statements(elif_body)

        elif isinstance(stmt, ForStmt):
            # Loop variable - use var_name property for backward compat
            if stmt.var_name:
                locals_dict[stmt.var_name] = None
            process_statements(stmt.body)

        elif isinstance(stmt, WhileStmt):
            process_statements(stmt.body)

        elif isinstance(stmt, MatchStmt):
            for arm in stmt.arms:
                process_statements(arm.body)

    process_statements(body)
    return locals_dict


def compute_hoisted_locals(
    body: List[Stmt],
    suspension_points: List[SuspensionPoint],
    all_locals: Dict[str, Type]
) -> Dict[str, Type]:
    """
    Compute which local variables need to be hoisted to the frame.

    A local needs to be hoisted if:
    1. It's defined before a suspension point
    2. It's used after that suspension point
    """
    if not suspension_points:
        return {}

    # Track which variables are defined and used
    defined_before = {}  # var -> suspension point index where first defined before
    used_after = set()   # vars used after any suspension point

    # Simple approach: if any local is defined before the first suspension
    # and might be used after, hoist it.
    # This is conservative but correct.

    first_suspension_index = suspension_points[0].stmt_index if suspension_points else len(body)

    def find_defined_vars(stmts: List[Stmt], up_to_index: int) -> Set[str]:
        """Find variables defined in statements up to given index."""
        defined = set()
        for i, stmt in enumerate(stmts):
            if i >= up_to_index:
                break
            if isinstance(stmt, VarDecl):
                defined.add(stmt.name)
            elif isinstance(stmt, ForStmt):
                if stmt.var_name:
                    defined.add(stmt.var_name)
        return defined

    def find_used_vars(stmts: List[Stmt], from_index: int) -> Set[str]:
        """Find variables used in statements from given index."""
        used = set()

        def find_in_expr(expr):
            if isinstance(expr, Identifier):
                used.add(expr.name)
            elif isinstance(expr, CallExpr):
                for arg in expr.args:
                    find_in_expr(arg)
            elif isinstance(expr, MethodCallExpr):
                find_in_expr(expr.object)
                for arg in expr.args:
                    find_in_expr(arg)
            elif isinstance(expr, BinaryExpr):
                find_in_expr(expr.left)
                find_in_expr(expr.right)
            elif isinstance(expr, UnaryExpr):
                find_in_expr(expr.operand)
            elif isinstance(expr, TernaryExpr):
                find_in_expr(expr.condition)
                find_in_expr(expr.then_expr)
                find_in_expr(expr.else_expr)
            elif isinstance(expr, ListExpr):
                for elem in expr.elements:
                    find_in_expr(elem)
            elif isinstance(expr, TupleExpr):
                for _, elem in expr.elements:
                    find_in_expr(elem)
            elif isinstance(expr, IndexExpr):
                find_in_expr(expr.object)
                find_in_expr(expr.index)
            elif isinstance(expr, MemberExpr):
                find_in_expr(expr.object)

        def find_in_stmt(stmt):
            if isinstance(stmt, VarDecl):
                if stmt.initializer:
                    find_in_expr(stmt.initializer)
            elif isinstance(stmt, Assignment):
                if isinstance(stmt.target, Identifier):
                    used.add(stmt.target.name)
                find_in_expr(stmt.value)
            elif isinstance(stmt, ExprStmt):
                find_in_expr(stmt.expr)
            elif isinstance(stmt, ReturnStmt):
                if stmt.value:
                    find_in_expr(stmt.value)
            elif isinstance(stmt, IfStmt):
                find_in_expr(stmt.condition)
                for s in stmt.then_body:
                    find_in_stmt(s)
                if stmt.else_body:
                    for s in stmt.else_body:
                        find_in_stmt(s)
                for cond, body in stmt.else_if_clauses:
                    find_in_expr(cond)
                    for s in body:
                        find_in_stmt(s)
            elif isinstance(stmt, ForStmt):
                find_in_expr(stmt.iterable)
                for s in stmt.body:
                    find_in_stmt(s)
            elif isinstance(stmt, WhileStmt):
                find_in_expr(stmt.condition)
                for s in stmt.body:
                    find_in_stmt(s)
            elif isinstance(stmt, MatchStmt):
                find_in_expr(stmt.value)
                for arm in stmt.arms:
                    for s in arm.body:
                        find_in_stmt(s)

        for i, stmt in enumerate(stmts):
            if i >= from_index:
                find_in_stmt(stmt)
        return used

    # Find vars defined before first suspension
    defined = find_defined_vars(body, first_suspension_index)

    # Find vars used after first suspension (including at the suspension point)
    used = find_used_vars(body, first_suspension_index)

    # Hoisted = defined before AND used after
    hoisted_names = defined & used

    # Return with types
    return {name: all_locals.get(name) for name in hoisted_names}


def has_suspension_points(func: FunctionDecl, task_functions: Set[str]) -> bool:
    """Quick check if a task has any suspension points."""
    return len(find_suspension_points(func.body, task_functions)) > 0
