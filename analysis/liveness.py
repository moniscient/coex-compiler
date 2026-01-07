"""
Liveness Analysis for Coex

Implements backward dataflow analysis to compute which variables are live
at each program point. A variable is live at a point if there exists a
control flow path from that point to a use of the variable.
"""

from dataclasses import dataclass, field
from typing import Set, Dict, List, Optional
from .cfg import CFG, BasicBlock, collect_stmt_uses, collect_stmt_defs, collect_expr_uses
from ast_nodes import Stmt, VarDecl, Assignment, Identifier, MethodCallExpr


@dataclass
class LivenessResult:
    """Results of liveness analysis for a function."""
    # Live variables at entry to each block
    live_in: Dict[int, Set[str]] = field(default_factory=dict)

    # Live variables at exit of each block
    live_out: Dict[int, Set[str]] = field(default_factory=dict)

    # Live variables before each statement (keyed by (block_id, stmt_index))
    live_before: Dict[tuple, Set[str]] = field(default_factory=dict)

    # Live variables after each statement
    live_after: Dict[tuple, Set[str]] = field(default_factory=dict)


class LivenessAnalysis:
    """
    Backward dataflow analysis for variable liveness.

    Transfer function:
        IN[B] = GEN[B] ∪ (OUT[B] - KILL[B])
        OUT[B] = ∪ IN[S] for all successors S of B

    At join points (multiple successors), we take the union:
    a variable is live if it's live on ANY path forward.
    """

    def __init__(self, cfg: CFG):
        self.cfg = cfg
        self.result = LivenessResult()

        # Initialize sets for all blocks
        for block in cfg.blocks:
            self.result.live_in[block.id] = set()
            self.result.live_out[block.id] = set()

    def analyze(self) -> LivenessResult:
        """Run the liveness analysis to fixed point."""
        changed = True
        iterations = 0
        max_iterations = 1000  # Safety limit

        while changed and iterations < max_iterations:
            changed = False
            iterations += 1

            # Process blocks in reverse postorder (approximation: reverse order)
            for block in reversed(self.cfg.blocks):
                old_in = self.result.live_in[block.id].copy()

                # OUT[B] = union of IN[S] for all successors S
                new_out = set()
                for succ in block.successors:
                    new_out.update(self.result.live_in[succ.id])
                self.result.live_out[block.id] = new_out

                # Compute IN[B] by processing statements in reverse order
                live = new_out.copy()
                for i in range(len(block.statements) - 1, -1, -1):
                    stmt = block.statements[i]
                    self.result.live_after[(block.id, i)] = live.copy()

                    # Apply transfer function for this statement
                    live = self._transfer_stmt(stmt, live)

                    self.result.live_before[(block.id, i)] = live.copy()

                self.result.live_in[block.id] = live

                if live != old_in:
                    changed = True

        return self.result

    def _transfer_stmt(self, stmt: Stmt, live_out: Set[str]) -> Set[str]:
        """
        Compute live-in from live-out for a single statement.

        live_in = gen(stmt) ∪ (live_out - kill(stmt))
        """
        gen = collect_stmt_uses(stmt)
        kill = collect_stmt_defs(stmt)

        # For an update pattern like x = x.add(y), the use of x on RHS
        # is in gen, and x is in kill. But we need special handling:
        # The old value of x is used (gen) before the new value is defined (kill).
        # So liveness correctly shows x is live before this statement.

        live_in = gen.union(live_out - kill)
        return live_in


def compute_liveness(cfg: CFG) -> LivenessResult:
    """Compute liveness analysis for a CFG."""
    analysis = LivenessAnalysis(cfg)
    return analysis.analyze()


# ============================================================================
# Last-Use Detection
# ============================================================================

@dataclass
class UseInfo:
    """Information about a variable use in an expression."""
    var_name: str
    is_last_use: bool
    is_update_receiver: bool  # True if this is the receiver of x.method() in x = x.method()
    stmt_location: tuple  # (block_id, stmt_index)


def is_var_live_after(var: str, block_id: int, stmt_index: int, liveness: LivenessResult) -> bool:
    """Check if a variable is live after a specific statement."""
    key = (block_id, stmt_index)
    if key in liveness.live_after:
        return var in liveness.live_after[key]
    return False


def is_last_use_of_var(var: str, block_id: int, stmt_index: int, liveness: LivenessResult) -> bool:
    """
    Determine if a use of 'var' in statement (block_id, stmt_index) is its last use.

    A use is the last use if the variable is NOT live after this statement.
    """
    return not is_var_live_after(var, block_id, stmt_index, liveness)


def find_update_pattern(stmt: Stmt) -> Optional[tuple]:
    """
    Check if statement matches the update pattern: x = x.method(args)

    Returns (var_name, method_name, args) if pattern matches, None otherwise.

    The pattern is:
    - Assignment or VarDecl
    - Target is a simple identifier 'x'
    - RHS is a method call x.method(args)
    - Receiver of method call is the same identifier 'x'

    Note: The AST can represent method calls in two ways:
    1. MethodCallExpr(object, method, args)
    2. CallExpr(callee=MemberExpr(object, member), args)
    We handle both cases.
    """
    from ast_nodes import CallExpr, MemberExpr

    target_name = None
    rhs = None

    if isinstance(stmt, VarDecl):
        target_name = stmt.name
        rhs = stmt.initializer
    elif isinstance(stmt, Assignment):
        if isinstance(stmt.target, Identifier):
            target_name = stmt.target.name
            rhs = stmt.value
        else:
            return None
    else:
        return None

    # Check if RHS is a method call on the same variable
    # Case 1: MethodCallExpr
    if isinstance(rhs, MethodCallExpr):
        if not isinstance(rhs.object, Identifier):
            return None
        if rhs.object.name != target_name:
            return None
        return (target_name, rhs.method, rhs.args)

    # Case 2: CallExpr with MemberExpr callee (e.g., s.add(1))
    if isinstance(rhs, CallExpr) and isinstance(rhs.callee, MemberExpr):
        member_expr = rhs.callee
        if not isinstance(member_expr.object, Identifier):
            return None
        if member_expr.object.name != target_name:
            return None
        return (target_name, member_expr.member, rhs.args)

    return None


def check_args_alias(var_name: str, args: List) -> bool:
    """
    Check if any of the arguments could alias the variable.

    For now, we conservatively check if var_name appears in any argument.
    Returns True if there's potential aliasing (unsafe for in-place mutation).
    """
    for arg in args:
        uses = collect_expr_uses(arg)
        if var_name in uses:
            return True
    return False
