"""
Coex Static Analysis Modules

This package provides dataflow analysis for compiler optimizations:
- cfg: Control flow graph construction
- liveness: Backward liveness analysis
- uniqueness: Uniqueness analysis for in-place mutation optimization
- ownership: Ownership analysis for unique bindings and move semantics
"""

from .cfg import CFG, BasicBlock, build_cfg
from .liveness import LivenessAnalysis, compute_liveness
from .uniqueness import UniquenessAnalysis, UpdateCandidate, analyze_function
from .ownership import (
    OwnershipAnalyzer, analyze_ownership, check_program_ownership,
    OwnershipState, BindingInfo, OwnershipError, OwnershipWarning,
    FunctionOwnershipResult
)

__all__ = [
    'CFG', 'BasicBlock', 'build_cfg',
    'LivenessAnalysis', 'compute_liveness',
    'UniquenessAnalysis', 'UpdateCandidate', 'analyze_function',
    'OwnershipAnalyzer', 'analyze_ownership', 'check_program_ownership',
    'OwnershipState', 'BindingInfo', 'OwnershipError', 'OwnershipWarning',
    'FunctionOwnershipResult'
]
