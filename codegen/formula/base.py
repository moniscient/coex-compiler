"""
Abstract Base Class for GPU Formula Backends.

Defines the interface that Metal, CUDA, and future backends must implement.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import List, Tuple, Optional, Any, TYPE_CHECKING

if TYPE_CHECKING:
    from ast_nodes import Expr, FunctionDecl


@dataclass
class KernelSpec:
    """Specification for a generated GPU kernel."""
    name: str                           # Unique kernel name
    source: str                         # Kernel source code (MSL, CUDA, etc.)
    input_params: List[Tuple[str, str]] # [(param_name, coex_type), ...]
    output_type: str                    # Coex type of output elements
    element_count_expr: Any             # Expression for element count (LLVM value)


@dataclass
class OffloadResult:
    """Result from attempting to offload a construct to GPU."""
    offloaded: bool                     # True if GPU offload was used
    kernel_spec: Optional[KernelSpec]   # Kernel details if offloaded
    llvm_value: Any                     # Resulting LLVM IR value


class FormulaBackend(ABC):
    """Abstract base class for GPU compute backends.

    Each backend (Metal, CUDA, etc.) implements this interface to provide:
    1. Kernel source generation from Coex AST
    2. Type mapping from Coex types to backend-specific types
    3. Runtime dispatch to execute kernels
    """

    @abstractmethod
    def get_name(self) -> str:
        """Return human-readable backend name."""
        pass

    @abstractmethod
    def map_type(self, coex_type: str) -> str:
        """Map a Coex type to the backend's type system.

        Args:
            coex_type: Coex type name (e.g., 'int', 'float', 'bool')

        Returns:
            Corresponding type name in the backend's language.
        """
        pass

    @abstractmethod
    def emit_map_kernel(
        self,
        kernel_name: str,
        formula_body: str,
        input_params: List[Tuple[str, str]],
        output_type: str
    ) -> str:
        """Emit a map-style kernel for parallel element-wise operations.

        Args:
            kernel_name: Unique name for this kernel
            formula_body: The formula body transpiled to C-like syntax
            input_params: List of (parameter_name, coex_type) tuples
            output_type: Coex type of output elements

        Returns:
            Complete kernel source code for the backend.
        """
        pass

    @abstractmethod
    def emit_predicate_kernel(
        self,
        kernel_name: str,
        predicate_body: str,
        input_params: List[Tuple[str, str]]
    ) -> str:
        """Emit a predicate kernel for filter operations (first/most).

        Args:
            kernel_name: Unique name for this kernel
            predicate_body: The predicate formula transpiled to C-like syntax
            input_params: List of (parameter_name, coex_type) tuples

        Returns:
            Complete kernel source code for the backend.
        """
        pass

    @abstractmethod
    def emit_dispatch_code(
        self,
        kernel_spec: KernelSpec,
        codegen: Any
    ) -> Any:
        """Emit LLVM IR to dispatch the kernel at runtime.

        This generates the code that:
        1. Prepares input buffers
        2. Allocates output buffer
        3. Invokes the GPU kernel
        4. Returns result as Coex collection

        Args:
            kernel_spec: Specification of the kernel to dispatch
            codegen: The CodeGenerator instance for LLVM IR emission

        Returns:
            LLVM IR value representing the result.
        """
        pass


class TranspileError(Exception):
    """Raised when formula AST cannot be transpiled to GPU code."""
    pass
