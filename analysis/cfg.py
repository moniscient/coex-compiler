"""
Control Flow Graph Construction for Coex

Builds a CFG from an AST function body for use in dataflow analysis.
"""

from dataclasses import dataclass, field
from typing import List, Set, Dict, Optional, Any
from ast_nodes import (
    Stmt, VarDecl, Assignment, ExprStmt, ReturnStmt, BreakStmt, ContinueStmt,
    IfStmt, ForStmt, WhileStmt, CycleStmt, MatchStmt, PrintStmt, DebugStmt,
    TupleDestructureStmt, SliceAssignment, ChannelSendStmt, SelectStmt,
    WithinStmt, ForAssignStmt, FirstAssignStmt, MostAssignStmt, LlvmIrStmt,
    Expr, Identifier, MethodCallExpr, BinaryExpr, UnaryExpr, CallExpr,
    MemberExpr, IndexExpr, SliceExpr, TernaryExpr, ListExpr, MapExpr, SetExpr,
    TupleExpr, ListComprehension, SetComprehension, MapComprehension,
    MatchArm, Pattern, IdentifierPattern, ConstructorPattern, TuplePattern
)


@dataclass
class BasicBlock:
    """A basic block in the CFG - a sequence of statements with no internal branches."""
    id: int
    statements: List[Stmt] = field(default_factory=list)
    successors: List['BasicBlock'] = field(default_factory=list)
    predecessors: List['BasicBlock'] = field(default_factory=list)

    # For loop handling
    is_loop_header: bool = False
    loop_back_edge_from: Optional['BasicBlock'] = None

    def __hash__(self):
        return self.id

    def __eq__(self, other):
        if not isinstance(other, BasicBlock):
            return False
        return self.id == other.id

    def __repr__(self):
        return f"BB{self.id}({len(self.statements)} stmts)"


@dataclass
class CFG:
    """Control Flow Graph for a function."""
    entry: BasicBlock
    exit: BasicBlock
    blocks: List[BasicBlock] = field(default_factory=list)

    def __repr__(self):
        return f"CFG({len(self.blocks)} blocks)"


class CFGBuilder:
    """Builds a CFG from a list of statements."""

    def __init__(self):
        self.block_id = 0
        self.blocks: List[BasicBlock] = []
        self.exit_block: Optional[BasicBlock] = None

        # Loop context for break/continue
        self.loop_stack: List[tuple] = []  # (header_block, exit_block)

    def new_block(self) -> BasicBlock:
        """Create a new basic block."""
        block = BasicBlock(id=self.block_id)
        self.block_id += 1
        self.blocks.append(block)
        return block

    def add_edge(self, from_block: BasicBlock, to_block: BasicBlock):
        """Add a CFG edge from from_block to to_block."""
        if to_block not in from_block.successors:
            from_block.successors.append(to_block)
        if from_block not in to_block.predecessors:
            to_block.predecessors.append(from_block)

    def build(self, statements: List[Stmt]) -> CFG:
        """Build a CFG from a list of statements."""
        entry = self.new_block()
        self.exit_block = self.new_block()

        # Build the CFG
        final_block = self._build_statements(statements, entry)

        # Connect final block to exit if it doesn't already terminate
        if final_block and self.exit_block not in final_block.successors:
            self.add_edge(final_block, self.exit_block)

        return CFG(entry=entry, exit=self.exit_block, blocks=self.blocks)

    def _build_statements(self, statements: List[Stmt], current: BasicBlock) -> Optional[BasicBlock]:
        """
        Build CFG for a list of statements, starting at current block.
        Returns the final block (or None if all paths terminated).
        """
        for stmt in statements:
            if current is None:
                # Dead code after return/break/continue
                break
            current = self._build_statement(stmt, current)
        return current

    def _build_statement(self, stmt: Stmt, current: BasicBlock) -> Optional[BasicBlock]:
        """
        Build CFG for a single statement.
        Returns the block to continue from (or None if statement terminates flow).
        """
        if isinstance(stmt, (VarDecl, Assignment, ExprStmt, PrintStmt, DebugStmt,
                            TupleDestructureStmt, SliceAssignment, ChannelSendStmt,
                            LlvmIrStmt)):
            # Simple statements - add to current block
            current.statements.append(stmt)
            return current

        elif isinstance(stmt, ReturnStmt):
            current.statements.append(stmt)
            self.add_edge(current, self.exit_block)
            return None  # Flow terminates

        elif isinstance(stmt, BreakStmt):
            current.statements.append(stmt)
            if self.loop_stack:
                _, loop_exit = self.loop_stack[-1]
                self.add_edge(current, loop_exit)
            return None  # Flow terminates (within loop)

        elif isinstance(stmt, ContinueStmt):
            current.statements.append(stmt)
            if self.loop_stack:
                loop_header, _ = self.loop_stack[-1]
                self.add_edge(current, loop_header)
            return None  # Flow terminates (within loop)

        elif isinstance(stmt, IfStmt):
            return self._build_if(stmt, current)

        elif isinstance(stmt, WhileStmt):
            return self._build_while(stmt, current)

        elif isinstance(stmt, CycleStmt):
            return self._build_cycle(stmt, current)

        elif isinstance(stmt, ForStmt):
            return self._build_for(stmt, current)

        elif isinstance(stmt, MatchStmt):
            return self._build_match(stmt, current)

        elif isinstance(stmt, SelectStmt):
            return self._build_select(stmt, current)

        elif isinstance(stmt, WithinStmt):
            return self._build_within(stmt, current)

        elif isinstance(stmt, (ForAssignStmt, FirstAssignStmt, MostAssignStmt)):
            # These are like for loops but with assignment
            return self._build_for_assign(stmt, current)

        else:
            # Unknown statement type - add to current block
            current.statements.append(stmt)
            return current

    def _build_if(self, stmt: IfStmt, current: BasicBlock) -> Optional[BasicBlock]:
        """Build CFG for if statement."""
        # Add condition evaluation to current block (conceptually)
        # Create blocks for then, else, and merge
        then_block = self.new_block()
        merge_block = self.new_block()

        # Edge from current to then block
        self.add_edge(current, then_block)

        # Build then body
        then_exit = self._build_statements(stmt.then_body, then_block)

        # Handle elif clauses
        prev_else_entry = current
        for elif_cond, elif_body in stmt.else_if_clauses:
            elif_block = self.new_block()
            self.add_edge(prev_else_entry, elif_block)
            elif_exit = self._build_statements(elif_body, elif_block)
            if elif_exit:
                self.add_edge(elif_exit, merge_block)
            prev_else_entry = self.new_block()
            self.add_edge(current, prev_else_entry)

        # Handle else clause
        if stmt.else_body:
            else_block = self.new_block()
            self.add_edge(prev_else_entry, else_block)
            else_exit = self._build_statements(stmt.else_body, else_block)
            if else_exit:
                self.add_edge(else_exit, merge_block)
        else:
            # No else - edge directly to merge
            self.add_edge(prev_else_entry, merge_block)

        # Connect then exit to merge
        if then_exit:
            self.add_edge(then_exit, merge_block)

        # If all branches terminated, merge is unreachable
        if then_exit is None and (stmt.else_body is None or else_exit is None):
            # At least one path reaches merge
            pass

        return merge_block

    def _build_while(self, stmt: WhileStmt, current: BasicBlock) -> Optional[BasicBlock]:
        """Build CFG for while loop."""
        # Create header, body, and exit blocks
        header = self.new_block()
        header.is_loop_header = True
        body_block = self.new_block()
        exit_block = self.new_block()

        # Edge from current to header
        self.add_edge(current, header)

        # Header has edges to body and exit (condition true/false)
        self.add_edge(header, body_block)
        self.add_edge(header, exit_block)

        # Push loop context for break/continue
        self.loop_stack.append((header, exit_block))

        # Build body
        body_exit = self._build_statements(stmt.body, body_block)

        # Pop loop context
        self.loop_stack.pop()

        # Back edge from body exit to header
        if body_exit:
            self.add_edge(body_exit, header)
            header.loop_back_edge_from = body_exit

        return exit_block

    def _build_cycle(self, stmt: CycleStmt, current: BasicBlock) -> Optional[BasicBlock]:
        """Build CFG for cycle statement (similar to while)."""
        return self._build_while(WhileStmt(condition=stmt.condition, body=stmt.body), current)

    def _build_for(self, stmt: ForStmt, current: BasicBlock) -> Optional[BasicBlock]:
        """Build CFG for for loop."""
        # Similar to while - has a header that checks if iteration continues
        header = self.new_block()
        header.is_loop_header = True
        body_block = self.new_block()
        exit_block = self.new_block()

        # Edge from current to header (evaluates iterable once conceptually)
        self.add_edge(current, header)

        # Header checks if more elements
        self.add_edge(header, body_block)
        self.add_edge(header, exit_block)

        # Push loop context
        self.loop_stack.append((header, exit_block))

        # Build body
        body_exit = self._build_statements(stmt.body, body_block)

        # Pop loop context
        self.loop_stack.pop()

        # Back edge
        if body_exit:
            self.add_edge(body_exit, header)
            header.loop_back_edge_from = body_exit

        return exit_block

    def _build_for_assign(self, stmt, current: BasicBlock) -> Optional[BasicBlock]:
        """Build CFG for for-assign variants (ForAssignStmt, FirstAssignStmt, MostAssignStmt)."""
        # Treat as a loop structure
        header = self.new_block()
        header.is_loop_header = True
        body_block = self.new_block()
        exit_block = self.new_block()

        self.add_edge(current, header)
        self.add_edge(header, body_block)
        self.add_edge(header, exit_block)

        # The body is just the expression, add as a synthetic statement
        body_block.statements.append(stmt)

        self.add_edge(body_block, header)
        header.loop_back_edge_from = body_block

        return exit_block

    def _build_match(self, stmt: MatchStmt, current: BasicBlock) -> Optional[BasicBlock]:
        """Build CFG for match statement."""
        merge_block = self.new_block()

        for arm in stmt.arms:
            arm_block = self.new_block()
            self.add_edge(current, arm_block)
            arm_exit = self._build_statements(arm.body, arm_block)
            if arm_exit:
                self.add_edge(arm_exit, merge_block)

        return merge_block

    def _build_select(self, stmt: SelectStmt, current: BasicBlock) -> Optional[BasicBlock]:
        """Build CFG for select statement."""
        merge_block = self.new_block()

        for case in stmt.cases:
            case_block = self.new_block()
            self.add_edge(current, case_block)
            case_exit = self._build_statements(case.body, case_block)
            if case_exit:
                self.add_edge(case_exit, merge_block)

        return merge_block

    def _build_within(self, stmt: WithinStmt, current: BasicBlock) -> Optional[BasicBlock]:
        """Build CFG for within statement."""
        body_block = self.new_block()
        merge_block = self.new_block()

        self.add_edge(current, body_block)
        body_exit = self._build_statements(stmt.body, body_block)
        if body_exit:
            self.add_edge(body_exit, merge_block)

        if stmt.else_body:
            else_block = self.new_block()
            self.add_edge(current, else_block)
            else_exit = self._build_statements(stmt.else_body, else_block)
            if else_exit:
                self.add_edge(else_exit, merge_block)
        else:
            self.add_edge(current, merge_block)

        return merge_block


def build_cfg(statements: List[Stmt]) -> CFG:
    """Build a CFG from a list of statements."""
    builder = CFGBuilder()
    return builder.build(statements)


# ============================================================================
# Expression Variable Collection
# ============================================================================

def collect_expr_uses(expr: Expr) -> Set[str]:
    """
    Collect all variable names used in an expression.
    Returns a set of variable names that are read.
    """
    uses = set()
    _collect_expr_uses_impl(expr, uses)
    return uses


def _collect_expr_uses_impl(expr: Expr, uses: Set[str]):
    """Recursively collect variable uses from an expression."""
    if expr is None:
        return

    if isinstance(expr, Identifier):
        uses.add(expr.name)

    elif isinstance(expr, BinaryExpr):
        _collect_expr_uses_impl(expr.left, uses)
        _collect_expr_uses_impl(expr.right, uses)

    elif isinstance(expr, UnaryExpr):
        _collect_expr_uses_impl(expr.operand, uses)

    elif isinstance(expr, CallExpr):
        _collect_expr_uses_impl(expr.callee, uses)
        for arg in expr.args:
            _collect_expr_uses_impl(arg, uses)
        for arg in expr.named_args.values():
            _collect_expr_uses_impl(arg, uses)

    elif isinstance(expr, MethodCallExpr):
        _collect_expr_uses_impl(expr.object, uses)
        for arg in expr.args:
            _collect_expr_uses_impl(arg, uses)

    elif isinstance(expr, MemberExpr):
        _collect_expr_uses_impl(expr.object, uses)

    elif isinstance(expr, IndexExpr):
        _collect_expr_uses_impl(expr.object, uses)
        for idx in expr.indices:
            _collect_expr_uses_impl(idx, uses)

    elif isinstance(expr, SliceExpr):
        _collect_expr_uses_impl(expr.object, uses)
        if expr.start:
            _collect_expr_uses_impl(expr.start, uses)
        if expr.end:
            _collect_expr_uses_impl(expr.end, uses)

    elif isinstance(expr, TernaryExpr):
        _collect_expr_uses_impl(expr.condition, uses)
        _collect_expr_uses_impl(expr.then_expr, uses)
        _collect_expr_uses_impl(expr.else_expr, uses)

    elif isinstance(expr, ListExpr):
        for elem in expr.elements:
            _collect_expr_uses_impl(elem, uses)

    elif isinstance(expr, MapExpr):
        for key, value in expr.entries:
            _collect_expr_uses_impl(key, uses)
            _collect_expr_uses_impl(value, uses)

    elif isinstance(expr, SetExpr):
        for elem in expr.elements:
            _collect_expr_uses_impl(elem, uses)

    elif isinstance(expr, TupleExpr):
        for _, elem in expr.elements:
            _collect_expr_uses_impl(elem, uses)

    elif isinstance(expr, (ListComprehension, SetComprehension)):
        _collect_expr_uses_impl(expr.value, uses)
        for clause in expr.clauses:
            _collect_expr_uses_impl(clause.iterable, uses)
            if clause.condition:
                _collect_expr_uses_impl(clause.condition, uses)

    elif isinstance(expr, MapComprehension):
        _collect_expr_uses_impl(expr.key, uses)
        _collect_expr_uses_impl(expr.value, uses)
        for clause in expr.clauses:
            _collect_expr_uses_impl(clause.iterable, uses)
            if clause.condition:
                _collect_expr_uses_impl(clause.condition, uses)


def collect_stmt_uses(stmt: Stmt) -> Set[str]:
    """Collect all variable uses in a statement (GEN set)."""
    uses = set()

    if isinstance(stmt, VarDecl):
        uses.update(collect_expr_uses(stmt.initializer))

    elif isinstance(stmt, Assignment):
        # For assignment, the target is a def, but if target is complex (e.g., x.field),
        # the base object is a use
        if isinstance(stmt.target, Identifier):
            # x = expr: x is def, expr is use
            pass
        else:
            # x.field = expr or x[i] = expr: x is use
            uses.update(collect_expr_uses(stmt.target))
        uses.update(collect_expr_uses(stmt.value))

    elif isinstance(stmt, ExprStmt):
        uses.update(collect_expr_uses(stmt.expr))

    elif isinstance(stmt, ReturnStmt):
        if stmt.value:
            uses.update(collect_expr_uses(stmt.value))

    elif isinstance(stmt, PrintStmt):
        uses.update(collect_expr_uses(stmt.value))

    elif isinstance(stmt, DebugStmt):
        uses.update(collect_expr_uses(stmt.value))

    elif isinstance(stmt, TupleDestructureStmt):
        uses.update(collect_expr_uses(stmt.value))

    elif isinstance(stmt, SliceAssignment):
        uses.update(collect_expr_uses(stmt.target))
        if stmt.start:
            uses.update(collect_expr_uses(stmt.start))
        if stmt.end:
            uses.update(collect_expr_uses(stmt.end))
        uses.update(collect_expr_uses(stmt.value))

    elif isinstance(stmt, ChannelSendStmt):
        uses.update(collect_expr_uses(stmt.channel))
        uses.update(collect_expr_uses(stmt.value))

    elif isinstance(stmt, IfStmt):
        uses.update(collect_expr_uses(stmt.condition))

    elif isinstance(stmt, WhileStmt):
        uses.update(collect_expr_uses(stmt.condition))

    elif isinstance(stmt, CycleStmt):
        uses.update(collect_expr_uses(stmt.condition))

    elif isinstance(stmt, ForStmt):
        uses.update(collect_expr_uses(stmt.iterable))

    elif isinstance(stmt, MatchStmt):
        uses.update(collect_expr_uses(stmt.subject))

    return uses


def collect_stmt_defs(stmt: Stmt) -> Set[str]:
    """Collect all variable definitions in a statement (KILL set)."""
    defs = set()

    if isinstance(stmt, VarDecl):
        defs.add(stmt.name)

    elif isinstance(stmt, Assignment):
        if isinstance(stmt.target, Identifier):
            defs.add(stmt.target.name)

    elif isinstance(stmt, TupleDestructureStmt):
        for name in stmt.names:
            defs.add(name)

    elif isinstance(stmt, ForStmt):
        if isinstance(stmt.pattern, str):
            defs.add(stmt.pattern)
        elif isinstance(stmt.pattern, IdentifierPattern):
            defs.add(stmt.pattern.name)

    return defs
