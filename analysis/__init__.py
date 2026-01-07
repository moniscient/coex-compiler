"""
Coex Static Analysis Modules

This package provides dataflow analysis for compiler optimizations:
- cfg: Control flow graph construction
- liveness: Backward liveness analysis
- uniqueness: Uniqueness analysis for in-place mutation optimization
"""

from .cfg import CFG, BasicBlock, build_cfg
from .liveness import LivenessAnalysis, compute_liveness
from .uniqueness import UniquenessAnalysis, UpdateCandidate, analyze_function

__all__ = [
    'CFG', 'BasicBlock', 'build_cfg',
    'LivenessAnalysis', 'compute_liveness',
    'UniquenessAnalysis', 'UpdateCandidate', 'analyze_function'
]
