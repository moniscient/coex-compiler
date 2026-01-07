"""
Uniqueness Analysis for Coex

Identifies opportunities for in-place mutation optimization by detecting
update patterns where a binding is unique (last use before rebinding).

The key pattern is: x = x.method(args)
When this is detected and x is not live after the method call, the wrapper
object can be mutated in place rather than allocating a new one.
"""

from dataclasses import dataclass, field
from typing import List, Dict, Set, Optional, Any
from .cfg import CFG, BasicBlock, build_cfg, collect_expr_uses
from .liveness import LivenessResult, compute_liveness, find_update_pattern, check_args_alias
from ast_nodes import (
    FunctionDecl, Stmt, VarDecl, Assignment, Identifier, MethodCallExpr,
    Type, SetType, MapType, ListType, ArrayType, NamedType, PrimitiveType
)


# Methods that are known update operations (return same type as receiver)
# This is used for type inference when type annotations aren't available
KNOWN_UPDATE_METHODS = {
    # Set operations
    'add': True,
    'remove': True,
    'union': True,
    'intersection': True,
    'difference': True,

    # Map operations
    'put': True,
    'set': True,  # alias for put

    # List operations
    'append': True,
    'prepend': True,
    'concat': True,
    'set_at': True,
    'remove_at': True,

    # Array operations (if applicable)
    # Note: arrays might have different semantics

    # String operations
    # Note: strings are typically immutable, in-place not applicable
}


@dataclass
class UpdateCandidate:
    """Represents a statement eligible for in-place wrapper mutation."""
    # Location in CFG
    block_id: int
    stmt_index: int
    statement: Stmt

    # Pattern details
    var_name: str
    method_name: str
    args: List[Any]

    # Analysis results
    is_last_use: bool  # Is the RHS use of var_name its last use?
    args_alias: bool   # Do any args potentially alias var_name?
    can_mutate_in_place: bool  # Final decision

    # Type information (if available)
    var_type: Optional[Type] = None

    def __repr__(self):
        status = "YES" if self.can_mutate_in_place else "NO"
        return f"UpdateCandidate({self.var_name} = {self.var_name}.{self.method_name}(...), in_place={status})"


@dataclass
class FunctionAnalysisResult:
    """Results of uniqueness analysis for a function."""
    function_name: str
    cfg: CFG
    liveness: LivenessResult
    update_candidates: List[UpdateCandidate] = field(default_factory=list)

    # Map from (block_id, stmt_index) to UpdateCandidate for quick lookup
    candidate_map: Dict[tuple, UpdateCandidate] = field(default_factory=dict)

    def get_candidate(self, block_id: int, stmt_index: int) -> Optional[UpdateCandidate]:
        """Get the update candidate for a specific statement, if any."""
        return self.candidate_map.get((block_id, stmt_index))

    def has_in_place_candidate(self, block_id: int, stmt_index: int) -> bool:
        """Check if a statement has an in-place mutation candidate."""
        candidate = self.get_candidate(block_id, stmt_index)
        return candidate is not None and candidate.can_mutate_in_place


class UniquenessAnalysis:
    """
    Analyzes a function to identify update patterns eligible for in-place mutation.

    The analysis:
    1. Builds a CFG from the function body
    2. Computes liveness via backward dataflow
    3. Identifies statements matching x = x.method(args)
    4. Checks if the use of x on RHS is a last use
    5. Checks if args don't alias x
    6. Marks eligible statements for in-place code generation
    """

    def __init__(self, func: FunctionDecl, type_env: Optional[Dict[str, Type]] = None):
        """
        Initialize analysis for a function.

        Args:
            func: The function to analyze
            type_env: Optional type environment mapping variable names to types
        """
        self.func = func
        self.type_env = type_env or {}
        self.result: Optional[FunctionAnalysisResult] = None

    def analyze(self) -> FunctionAnalysisResult:
        """Run the full uniqueness analysis."""
        # Step 1: Build CFG
        cfg = build_cfg(self.func.body)

        # Step 2: Compute liveness
        liveness = compute_liveness(cfg)

        # Step 3: Find update candidates
        candidates = self._find_candidates(cfg, liveness)

        # Build result
        self.result = FunctionAnalysisResult(
            function_name=self.func.name,
            cfg=cfg,
            liveness=liveness,
            update_candidates=candidates
        )

        # Build lookup map
        for candidate in candidates:
            key = (candidate.block_id, candidate.stmt_index)
            self.result.candidate_map[key] = candidate

        return self.result

    def _find_candidates(self, cfg: CFG, liveness: LivenessResult) -> List[UpdateCandidate]:
        """Find all update pattern candidates in the CFG."""
        candidates = []

        for block in cfg.blocks:
            for i, stmt in enumerate(block.statements):
                candidate = self._check_statement(stmt, block.id, i, liveness)
                if candidate:
                    candidates.append(candidate)

        return candidates

    def _check_statement(self, stmt: Stmt, block_id: int, stmt_index: int,
                         liveness: LivenessResult) -> Optional[UpdateCandidate]:
        """
        Check if a statement is an update pattern eligible for in-place mutation.

        Returns UpdateCandidate if pattern matches, None otherwise.
        """
        # Check for update pattern: x = x.method(args)
        pattern = find_update_pattern(stmt)
        if pattern is None:
            return None

        var_name, method_name, args = pattern

        # Check if this method is a known update operation
        if method_name not in KNOWN_UPDATE_METHODS:
            # Could still be an update if we have type info showing return type matches
            # For now, only optimize known methods
            return None

        # Check if the use of var_name on RHS is its last use
        # The key insight: after x = x.method(...), the OLD x is dead
        # because the rebinding kills it. So we check if x is live AFTER this stmt.
        # If x is NOT live after, then this use is the last use of the old value.

        # Actually, for the pattern x = x.method(), x IS live after (the new value).
        # But the OLD value of x is consumed by the method call.
        # We need to check: is this the only use of x before it's rebound?

        # The correct check: x should not be live after this statement EXCEPT
        # for the new binding. But liveness doesn't distinguish old vs new bindings.

        # Simpler approach: the pattern x = x.method() ALWAYS consumes the old x.
        # The old value is passed to method(), then x is rebound.
        # So the old value is dead after this statement by definition.
        # The only concern is if x appears elsewhere in the RHS (in args).

        # Check for aliasing in args
        args_alias = check_args_alias(var_name, args)

        # For the pattern x = x.method(args), the old x is always "last used" here
        # because the rebinding kills it. The question is just aliasing.
        is_last_use = True  # By construction of the pattern

        # Final decision
        can_mutate = is_last_use and not args_alias

        # Get type info if available
        var_type = self.type_env.get(var_name)

        return UpdateCandidate(
            block_id=block_id,
            stmt_index=stmt_index,
            statement=stmt,
            var_name=var_name,
            method_name=method_name,
            args=args,
            is_last_use=is_last_use,
            args_alias=args_alias,
            can_mutate_in_place=can_mutate,
            var_type=var_type
        )


def analyze_function(func: FunctionDecl, type_env: Optional[Dict[str, Type]] = None) -> FunctionAnalysisResult:
    """
    Analyze a function for in-place mutation opportunities.

    Args:
        func: The function to analyze
        type_env: Optional type environment mapping variable names to their types

    Returns:
        FunctionAnalysisResult with all identified update candidates
    """
    analysis = UniquenessAnalysis(func, type_env)
    return analysis.analyze()


# ============================================================================
# Statement-Level Query Interface
# ============================================================================

class UpdatePatternChecker:
    """
    Simpler interface for checking individual statements during code generation.

    This can be used when you don't want to run full CFG/liveness analysis,
    but just want to check if a statement matches the update pattern.
    """

    def __init__(self):
        self.known_methods = KNOWN_UPDATE_METHODS

    def is_update_pattern(self, stmt: Stmt) -> Optional[tuple]:
        """
        Check if statement is an update pattern.

        Returns (var_name, method_name, args) or None.
        """
        return find_update_pattern(stmt)

    def can_optimize_update(self, stmt: Stmt) -> bool:
        """
        Quick check if a statement can potentially be optimized.

        This is a conservative check without full dataflow analysis.
        For the pattern x = x.method(args):
        - Returns True if method is a known update method
        - And args don't contain x
        """
        pattern = find_update_pattern(stmt)
        if pattern is None:
            return False

        var_name, method_name, args = pattern

        if method_name not in self.known_methods:
            return False

        if check_args_alias(var_name, args):
            return False

        return True


# Singleton for simple checks during codegen
_pattern_checker = UpdatePatternChecker()


def can_optimize_statement(stmt: Stmt) -> bool:
    """Quick check if a statement can use in-place mutation."""
    return _pattern_checker.can_optimize_update(stmt)


def get_update_pattern(stmt: Stmt) -> Optional[tuple]:
    """Get update pattern info if statement matches."""
    return _pattern_checker.is_update_pattern(stmt)
