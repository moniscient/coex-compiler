"""
Commentary Analyzers for Coex Compiler

Analyzers inspect the AST and generate compiler commentary for various concerns:
- Performance anti-patterns
- Function kind suggestions
- Move semantics opportunities
- GC pressure hints
"""

from abc import ABC, abstractmethod
from typing import List, Optional, Generator
from ast_nodes import (
    Program, FunctionDecl, FunctionKind, Stmt, Expr,
    ForStmt, WhileStmt, IfStmt, MatchStmt, CycleStmt,
    VarDecl, Assignment, ExprStmt, ReturnStmt,
    MethodCallExpr, CallExpr, Identifier, ListExpr,
    PrintStmt, AssignOp, MemberExpr
)
from commentary import CompilerComment, CommentaryCategory
from ast_nodes import (
    PrimitiveType, AtomicType, BinaryExpr, UnaryExpr, TernaryExpr
)


class CommentaryAnalyzer(ABC):
    """Base class for analyzers that generate compiler commentary."""

    @abstractmethod
    def analyze(self, program: Program) -> List[CompilerComment]:
        """Analyze program and return list of commentary."""
        pass

    def _walk_statements(self, stmts: List[Stmt]) -> Generator[Stmt, None, None]:
        """Recursively walk all statements in a block."""
        for stmt in stmts:
            yield stmt
            if isinstance(stmt, ForStmt):
                yield from self._walk_statements(stmt.body)
            elif isinstance(stmt, WhileStmt):
                yield from self._walk_statements(stmt.body)
            elif isinstance(stmt, CycleStmt):
                yield from self._walk_statements(stmt.body)
            elif isinstance(stmt, IfStmt):
                yield from self._walk_statements(stmt.then_body)
                for _, body in stmt.else_if_clauses:
                    yield from self._walk_statements(body)
                if stmt.else_body:
                    yield from self._walk_statements(stmt.else_body)
            elif isinstance(stmt, MatchStmt):
                for arm in stmt.arms:
                    yield from self._walk_statements(arm.body)


class PerformanceAnalyzer(CommentaryAnalyzer):
    """Detects performance anti-patterns."""

    def analyze(self, program: Program) -> List[CompilerComment]:
        comments = []
        for func in program.functions:
            if func.kind == FunctionKind.EXTERN:
                continue
            comments.extend(self._analyze_function(func))
        return comments

    def _analyze_function(self, func: FunctionDecl) -> List[CompilerComment]:
        comments = []

        stmt_list = list(self._walk_statements(func.body))
        for i, stmt in enumerate(stmt_list):
            # Detect loop with repeated list append: result = result.append(x)
            if isinstance(stmt, (ForStmt, WhileStmt)):
                loop_body = stmt.body
                append_info = self._find_repeated_append(loop_body)
                if append_info:
                    var_name, line = append_info
                    comments.append(CompilerComment(
                        category=CommentaryCategory.PERF,
                        message=(
                            f"Loop modifies '{var_name}' with append on each iteration, "
                            f"creating intermediate lists. Consider using Array for in-place mutation."
                        ),
                        line=line
                    ))

            # Detect nested loops with list operations
            if isinstance(stmt, ForStmt):
                if self._has_nested_loop_with_list_ops(stmt):
                    comments.append(CompilerComment(
                        category=CommentaryCategory.PERF,
                        message=(
                            "Nested loop with list operations may have O(n^2) or worse complexity. "
                            "Consider restructuring or using more efficient data structures."
                        ),
                        line=getattr(stmt, 'line', 1)
                    ))

        return comments

    def _find_repeated_append(self, body: List[Stmt]) -> Optional[tuple]:
        """Check if loop body has x = x.append(...) pattern. Returns (var_name, line) or None."""
        for stmt in body:
            var_name = None
            value_expr = None

            if isinstance(stmt, Assignment):
                if isinstance(stmt.target, Identifier):
                    var_name = stmt.target.name
                    value_expr = stmt.value
            elif isinstance(stmt, VarDecl):
                # Rebinding: result = result.append(x)
                var_name = stmt.name
                value_expr = stmt.initializer

            if var_name and value_expr:
                # Check for MethodCallExpr pattern
                if isinstance(value_expr, MethodCallExpr):
                    if value_expr.method == 'append':
                        if isinstance(value_expr.object, Identifier):
                            if value_expr.object.name == var_name:
                                return (var_name, getattr(stmt, 'line', 1))
                # Check for CallExpr(callee=MemberExpr(...)) pattern
                elif isinstance(value_expr, CallExpr):
                    if isinstance(value_expr.callee, MemberExpr):
                        if value_expr.callee.member == 'append':
                            if isinstance(value_expr.callee.object, Identifier):
                                if value_expr.callee.object.name == var_name:
                                    return (var_name, getattr(stmt, 'line', 1))
        return None

    def _has_nested_loop_with_list_ops(self, for_stmt: ForStmt) -> bool:
        """Check for nested loops with list operations."""
        for stmt in for_stmt.body:
            if isinstance(stmt, ForStmt):
                # Found nested loop, check for list operations
                for inner_stmt in self._walk_statements(stmt.body):
                    if isinstance(inner_stmt, Assignment):
                        if isinstance(inner_stmt.value, MethodCallExpr):
                            if inner_stmt.value.method in ('append', 'get', 'set'):
                                return True
        return False


class FunctionKindAnalyzer(CommentaryAnalyzer):
    """Suggests appropriate function kinds."""

    def analyze(self, program: Program) -> List[CompilerComment]:
        comments = []
        for func in program.functions:
            if func.kind == FunctionKind.EXTERN:
                continue
            suggestion = self._suggest_kind(func)
            if suggestion:
                comments.append(suggestion)
        return comments

    def _suggest_kind(self, func: FunctionDecl) -> Optional[CompilerComment]:
        # Only suggest for func that could be formula
        if func.kind == FunctionKind.FUNC:
            if self._is_pure(func):
                return CompilerComment(
                    category=CommentaryCategory.KIND,
                    message=(
                        f"Function '{func.name}' appears to be pure. "
                        f"Consider using 'formula' for compiler optimizations."
                    ),
                    line=getattr(func, 'line', 1)
                )
        return None

    def _is_pure(self, func: FunctionDecl) -> bool:
        """Check if function has no side effects."""
        for stmt in self._walk_statements(func.body):
            # Check for print statements
            if isinstance(stmt, PrintStmt):
                return False

            # Check for extern calls or func calls
            if isinstance(stmt, ExprStmt):
                if self._has_impure_call(stmt.expr):
                    return False

            if isinstance(stmt, (VarDecl, Assignment)):
                value = stmt.initializer if isinstance(stmt, VarDecl) else stmt.value
                if self._has_impure_call(value):
                    return False

            if isinstance(stmt, ReturnStmt) and stmt.value:
                if self._has_impure_call(stmt.value):
                    return False

        # Check for rebindable variables (formulas require const)
        for stmt in self._walk_statements(func.body):
            if isinstance(stmt, VarDecl) and not stmt.is_const:
                return False

        return True

    def _has_impure_call(self, expr: Expr) -> bool:
        """Check if expression contains impure function calls."""
        if isinstance(expr, CallExpr):
            # Would need to check if callee is a func (not formula)
            # For now, be conservative
            return True
        if isinstance(expr, MethodCallExpr):
            # Method calls on built-in types are generally pure
            # External methods would be impure
            pass
        return False


class MoveAnalyzer(CommentaryAnalyzer):
    """Suggests move semantics opportunities."""

    def analyze(self, program: Program) -> List[CompilerComment]:
        comments = []
        for func in program.functions:
            if func.kind == FunctionKind.EXTERN:
                continue
            comments.extend(self._analyze_function(func))
        return comments

    def _analyze_function(self, func: FunctionDecl) -> List[CompilerComment]:
        comments = []

        # Track variable usage
        stmt_list = list(self._walk_statements(func.body))

        for i, stmt in enumerate(stmt_list):
            if isinstance(stmt, VarDecl) and not stmt.is_copy:
                # Check if the source is a variable that's not used afterward
                if isinstance(stmt.initializer, Identifier):
                    source_var = stmt.initializer.name
                    if not self._is_used_after(source_var, stmt_list[i+1:]):
                        comments.append(CompilerComment(
                            category=CommentaryCategory.MOVE,
                            message=(
                                f"Variable '{source_var}' is not used after this assignment. "
                                f"Consider: {stmt.name} := {source_var} (move instead of copy)"
                            ),
                            line=getattr(stmt, 'line', 1)
                        ))

            elif isinstance(stmt, Assignment) and stmt.op == AssignOp.ASSIGN:
                if isinstance(stmt.value, Identifier) and isinstance(stmt.target, Identifier):
                    source_var = stmt.value.name
                    remaining = stmt_list[i+1:]
                    if not self._is_used_after(source_var, remaining):
                        comments.append(CompilerComment(
                            category=CommentaryCategory.MOVE,
                            message=(
                                f"Variable '{source_var}' is not used after this line. "
                                f"Consider using := (move) instead of = (copy)."
                            ),
                            line=getattr(stmt, 'line', 1)
                        ))

        return comments

    def _is_used_after(self, var_name: str, remaining_stmts: List[Stmt]) -> bool:
        """Check if variable is used in remaining statements."""
        for stmt in remaining_stmts:
            if self._stmt_uses_var(stmt, var_name):
                return True
        return False

    def _stmt_uses_var(self, stmt: Stmt, var_name: str) -> bool:
        """Check if statement uses the variable."""
        if isinstance(stmt, VarDecl):
            return self._expr_uses_var(stmt.initializer, var_name)
        elif isinstance(stmt, Assignment):
            # Don't count assignment to the variable as "using" it
            if isinstance(stmt.target, Identifier) and stmt.target.name == var_name:
                return False
            return self._expr_uses_var(stmt.value, var_name) or self._expr_uses_var(stmt.target, var_name)
        elif isinstance(stmt, ExprStmt):
            return self._expr_uses_var(stmt.expr, var_name)
        elif isinstance(stmt, ReturnStmt):
            return stmt.value and self._expr_uses_var(stmt.value, var_name)
        elif isinstance(stmt, PrintStmt):
            return self._expr_uses_var(stmt.value, var_name)
        elif isinstance(stmt, ForStmt):
            return (self._expr_uses_var(stmt.iterable, var_name) or
                    any(self._stmt_uses_var(s, var_name) for s in stmt.body))
        elif isinstance(stmt, WhileStmt):
            return (self._expr_uses_var(stmt.condition, var_name) or
                    any(self._stmt_uses_var(s, var_name) for s in stmt.body))
        elif isinstance(stmt, IfStmt):
            if self._expr_uses_var(stmt.condition, var_name):
                return True
            if any(self._stmt_uses_var(s, var_name) for s in stmt.then_body):
                return True
            for cond, body in stmt.else_if_clauses:
                if self._expr_uses_var(cond, var_name):
                    return True
                if any(self._stmt_uses_var(s, var_name) for s in body):
                    return True
            if stmt.else_body and any(self._stmt_uses_var(s, var_name) for s in stmt.else_body):
                return True
        return False

    def _expr_uses_var(self, expr: Expr, var_name: str) -> bool:
        """Check if expression uses the variable."""
        if expr is None:
            return False
        if isinstance(expr, Identifier):
            return expr.name == var_name
        elif isinstance(expr, CallExpr):
            if self._expr_uses_var(expr.callee, var_name):
                return True
            return any(self._expr_uses_var(arg, var_name) for arg in expr.args)
        elif isinstance(expr, MethodCallExpr):
            if self._expr_uses_var(expr.object, var_name):
                return True
            return any(self._expr_uses_var(arg, var_name) for arg in expr.args)
        elif isinstance(expr, ListExpr):
            return any(self._expr_uses_var(e, var_name) for e in expr.elements)
        # Add more expression types as needed
        return False


class GCAnalyzer(CommentaryAnalyzer):
    """Detects GC pressure patterns."""

    def analyze(self, program: Program) -> List[CompilerComment]:
        comments = []
        for func in program.functions:
            if func.kind == FunctionKind.EXTERN:
                continue
            comments.extend(self._analyze_function(func))
        return comments

    def _analyze_function(self, func: FunctionDecl) -> List[CompilerComment]:
        comments = []

        for stmt in self._walk_statements(func.body):
            # Detect allocation in tight loops
            if isinstance(stmt, (ForStmt, WhileStmt)):
                alloc_count = self._count_allocations(stmt.body)
                if alloc_count >= 3:
                    comments.append(CompilerComment(
                        category=CommentaryCategory.GC,
                        message=(
                            f"Loop contains {alloc_count} allocations per iteration. "
                            f"Consider hoisting allocations outside the loop or using pre-allocated buffers."
                        ),
                        line=getattr(stmt, 'line', 1)
                    ))

        return comments

    def _count_allocations(self, body: List[Stmt]) -> int:
        """Count allocations in a block of statements."""
        count = 0
        for stmt in body:
            if isinstance(stmt, VarDecl):
                if isinstance(stmt.initializer, ListExpr):
                    count += 1
                elif isinstance(stmt.initializer, MethodCallExpr):
                    if stmt.initializer.method in ('append', 'set'):
                        count += 1
            elif isinstance(stmt, Assignment):
                if isinstance(stmt.value, ListExpr):
                    count += 1
                elif isinstance(stmt.value, MethodCallExpr):
                    if stmt.value.method in ('append', 'set'):
                        count += 1
        return count


class AtomicSpinAnalyzer(CommentaryAnalyzer):
    """Detects potentially problematic spin-waits on atomics in task context.

    Tasks are cooperatively scheduled, so spinning on an atomic can starve
    the scheduler and prevent other tasks from making progress.
    """

    # Atomic method names that read shared state
    ATOMIC_READ_METHODS = {'load', 'compare_exchange'}

    def analyze(self, program: Program) -> List[CompilerComment]:
        comments = []
        for func in program.functions:
            # Only check TASK functions, not THREAD, FUNC, etc.
            if func.kind != FunctionKind.TASK:
                continue

            # Build set of known atomic parameter names
            atomic_params = self._get_atomic_params(func)
            comments.extend(self._analyze_function(func, atomic_params))
        return comments

    def _get_atomic_params(self, func: FunctionDecl) -> set:
        """Get set of parameter names that are atomic types."""
        atomic_names = set()
        for param in func.params:
            if param.type_annotation:
                type_name = str(param.type_annotation)
                if type_name.startswith('atomic_'):
                    atomic_names.add(param.name)
        return atomic_names

    def _analyze_function(self, func: FunctionDecl, atomic_params: set) -> List[CompilerComment]:
        comments = []

        # Track local variables that are assigned from atomics
        atomic_derived = set()

        for stmt in self._walk_statements(func.body):
            # Track atomic-derived variables
            if isinstance(stmt, VarDecl):
                if self._expr_involves_atomic(stmt.initializer, atomic_params, atomic_derived):
                    atomic_derived.add(stmt.name)
            elif isinstance(stmt, Assignment):
                if isinstance(stmt.target, Identifier):
                    if self._expr_involves_atomic(stmt.value, atomic_params, atomic_derived):
                        atomic_derived.add(stmt.target.name)

            # Check while loops for atomic conditions
            if isinstance(stmt, WhileStmt):
                # Check if condition involves atomic
                if self._expr_involves_atomic(stmt.condition, atomic_params, atomic_derived):
                    comments.append(CompilerComment(
                        category=CommentaryCategory.ATOMIC_SPIN,
                        message=(
                            "Loop condition depends on atomic load; may starve scheduler. "
                            "Consider using channels or select for task synchronization."
                        ),
                        line=getattr(stmt, 'line', 1)
                    ))

                # Also check for atomic reads inside while body that affect termination
                for body_stmt in stmt.body:
                    if isinstance(body_stmt, (VarDecl, Assignment)):
                        target_name = body_stmt.name if isinstance(body_stmt, VarDecl) else (
                            body_stmt.target.name if isinstance(body_stmt.target, Identifier) else None
                        )
                        if target_name and self._var_used_in_condition(target_name, stmt.condition):
                            value = body_stmt.initializer if isinstance(body_stmt, VarDecl) else body_stmt.value
                            if self._expr_involves_atomic(value, atomic_params, atomic_derived):
                                # Variable controlling loop is updated from atomic
                                comments.append(CompilerComment(
                                    category=CommentaryCategory.ATOMIC_SPIN,
                                    message=(
                                        f"Variable '{target_name}' updated from atomic in loop; may starve scheduler. "
                                        "Consider using channels or select for task synchronization."
                                    ),
                                    line=getattr(body_stmt, 'line', 1)
                                ))

        return comments

    def _expr_involves_atomic(self, expr: Expr, atomic_params: set, atomic_derived: set) -> bool:
        """Check if expression reads from an atomic variable."""
        if expr is None:
            return False

        if isinstance(expr, MethodCallExpr):
            # Check if method is an atomic read
            if expr.method in self.ATOMIC_READ_METHODS:
                if isinstance(expr.object, Identifier):
                    if expr.object.name in atomic_params:
                        return True
            # Also check arguments
            return any(self._expr_involves_atomic(arg, atomic_params, atomic_derived) for arg in expr.args)

        if isinstance(expr, CallExpr):
            # Check for CallExpr(callee=MemberExpr(...)) pattern which is how
            # method calls like flag.load() are parsed
            if isinstance(expr.callee, MemberExpr):
                method_name = expr.callee.member
                if method_name in self.ATOMIC_READ_METHODS:
                    if isinstance(expr.callee.object, Identifier):
                        if expr.callee.object.name in atomic_params:
                            return True
            # Check callee and arguments
            if self._expr_involves_atomic(expr.callee, atomic_params, atomic_derived):
                return True
            return any(self._expr_involves_atomic(arg, atomic_params, atomic_derived) for arg in expr.args)

        if isinstance(expr, Identifier):
            # Check if it's a variable derived from atomic
            return expr.name in atomic_derived

        if isinstance(expr, MemberExpr):
            # Check the object of member access
            return self._expr_involves_atomic(expr.object, atomic_params, atomic_derived)

        if isinstance(expr, BinaryExpr):
            return (self._expr_involves_atomic(expr.left, atomic_params, atomic_derived) or
                    self._expr_involves_atomic(expr.right, atomic_params, atomic_derived))

        if isinstance(expr, UnaryExpr):
            return self._expr_involves_atomic(expr.operand, atomic_params, atomic_derived)

        if isinstance(expr, TernaryExpr):
            return (self._expr_involves_atomic(expr.condition, atomic_params, atomic_derived) or
                    self._expr_involves_atomic(expr.then_expr, atomic_params, atomic_derived) or
                    self._expr_involves_atomic(expr.else_expr, atomic_params, atomic_derived))

        return False

    def _var_used_in_condition(self, var_name: str, condition: Expr) -> bool:
        """Check if variable is used in a condition expression."""
        if condition is None:
            return False

        if isinstance(condition, Identifier):
            return condition.name == var_name

        if isinstance(condition, BinaryExpr):
            return (self._var_used_in_condition(var_name, condition.left) or
                    self._var_used_in_condition(var_name, condition.right))

        if isinstance(condition, UnaryExpr):
            return self._var_used_in_condition(var_name, condition.operand)

        if isinstance(condition, MethodCallExpr):
            if isinstance(condition.object, Identifier) and condition.object.name == var_name:
                return True
            return any(self._var_used_in_condition(var_name, arg) for arg in condition.args)

        if isinstance(condition, CallExpr):
            return any(self._var_used_in_condition(var_name, arg) for arg in condition.args)

        return False


# All analyzers to run
ALL_ANALYZERS = [
    PerformanceAnalyzer(),
    FunctionKindAnalyzer(),
    MoveAnalyzer(),
    GCAnalyzer(),
    AtomicSpinAnalyzer(),
]


def run_all_analyzers(program: Program) -> List[CompilerComment]:
    """Run all analyzers and collect comments."""
    comments = []
    for analyzer in ALL_ANALYZERS:
        comments.extend(analyzer.analyze(program))
    return comments
