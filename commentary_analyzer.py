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
            if isinstance(stmt, VarDecl) and not stmt.is_move:
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


# All analyzers to run
ALL_ANALYZERS = [
    PerformanceAnalyzer(),
    FunctionKindAnalyzer(),
    MoveAnalyzer(),
    GCAnalyzer(),
]


def run_all_analyzers(program: Program) -> List[CompilerComment]:
    """Run all analyzers and collect comments."""
    comments = []
    for analyzer in ALL_ANALYZERS:
        comments.extend(analyzer.analyze(program))
    return comments
