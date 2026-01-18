"""
Metal Runtime Dispatch for Coex GPU Offload.

This module provides a Python callback that can be called from compiled Coex
binaries to execute Metal compute kernels. The callback is registered via
ctypes and invoked by the C stub at runtime.

The callback receives:
- kernel_source: MSL kernel source code
- kernel_name: Name of the kernel function
- input_buf: Pointer to input data buffer
- count: Number of elements to process
- output_buf: Pointer to output buffer
- elem_size: Size of each element in bytes
"""

import ctypes
import sys
from ctypes import c_char_p, c_void_p, c_int64, CFUNCTYPE


# Callback function type for Metal dispatch
# void (*)(const char* src, const char* name, void* in, int64_t count, void* out, int64_t elem_size)
DISPATCH_FUNC_TYPE = CFUNCTYPE(
    None,           # return type: void
    c_char_p,       # kernel_source: const char*
    c_char_p,       # kernel_name: const char*
    c_void_p,       # input_buf: void*
    c_int64,        # count: int64_t
    c_void_p,       # output_buf: void*
    c_int64,        # elem_size: int64_t
)


# The callback instance - must be kept alive to prevent garbage collection
_dispatch_callback = None
_dispatch_callback_ptr = None

# Metal device and kernel cache
_metal_device = None
_kernel_cache = {}


def _get_metal_device():
    """Get or create the Metal device instance."""
    global _metal_device
    if _metal_device is None:
        try:
            import metalcompute as mc
            _metal_device = mc.Device()
        except ImportError:
            print("Warning: metalcompute not installed, GPU dispatch disabled", file=sys.stderr)
            return None
        except Exception as e:
            print(f"Warning: Metal device creation failed: {e}", file=sys.stderr)
            return None
    return _metal_device


def _metal_dispatch_impl(
    kernel_source: bytes,
    kernel_name: bytes,
    input_buf: int,
    count: int,
    output_buf: int,
    elem_size: int
):
    """Python implementation of Metal kernel dispatch.

    This is called from the compiled Coex binary via the C stub.

    Args:
        kernel_source: MSL kernel source code (null-terminated bytes)
        kernel_name: Name of the kernel function (null-terminated bytes)
        input_buf: Pointer to input data buffer (as integer)
        count: Number of elements to process
        output_buf: Pointer to output buffer (as integer)
        elem_size: Size of each element in bytes
    """
    try:
        # Decode strings
        src = kernel_source.decode('utf-8') if kernel_source else ""
        name = kernel_name.decode('utf-8') if kernel_name else "kernel_func"

        # Get Metal device
        device = _get_metal_device()
        if device is None:
            # No GPU - leave output as-is (zeros)
            return

        # Check cache
        cache_key = (src, name)
        if cache_key not in _kernel_cache:
            # Compile kernel
            compiled = device.kernel(src)
            _kernel_cache[cache_key] = compiled.function(name)

        kernel_func = _kernel_cache[cache_key]

        # Create input buffer from pointer
        # metalcompute expects buffers created from the device
        import metalcompute as mc

        input_size = count * elem_size
        output_size = count * elem_size

        # Create device buffers
        input_device_buf = device.buffer(input_size)
        output_device_buf = device.buffer(output_size)

        # Copy input data to device buffer
        # We need to copy from the C memory to the Metal buffer
        input_array = (ctypes.c_uint8 * input_size).from_address(input_buf)
        input_mv = memoryview(input_device_buf).cast('B')
        for i in range(input_size):
            input_mv[i] = input_array[i]

        # Execute kernel
        kernel_func(count, input_device_buf, output_device_buf)

        # Copy output data back
        output_array = (ctypes.c_uint8 * output_size).from_address(output_buf)
        output_mv = memoryview(output_device_buf).cast('B')
        for i in range(output_size):
            output_array[i] = output_mv[i]

    except Exception as e:
        # Log error but don't crash - leave output as zeros
        print(f"GPU dispatch error: {e}", file=sys.stderr)


def get_dispatch_callback():
    """Get the dispatch callback function.

    Returns:
        CFUNCTYPE callback object that can be passed to C code.
    """
    global _dispatch_callback
    if _dispatch_callback is None:
        _dispatch_callback = DISPATCH_FUNC_TYPE(_metal_dispatch_impl)
    return _dispatch_callback


def get_dispatch_address() -> int:
    """Get the address of the dispatch callback for use in compiled code.

    Returns:
        Integer address of the callback function.
    """
    global _dispatch_callback_ptr
    if _dispatch_callback_ptr is None:
        callback = get_dispatch_callback()
        _dispatch_callback_ptr = ctypes.cast(callback, c_void_p).value
    return _dispatch_callback_ptr


def register_with_stub(stub_lib):
    """Register the dispatch callback with the C stub library.

    Args:
        stub_lib: ctypes.CDLL object for the stub library
    """
    callback = get_dispatch_callback()

    # Declare registration function type
    register_func = stub_lib.coex_register_metal_dispatch
    register_func.argtypes = [DISPATCH_FUNC_TYPE]
    register_func.restype = None

    # Register callback
    register_func(callback)


def is_metal_available() -> bool:
    """Check if Metal GPU is available.

    Returns:
        True if Metal compute is available.
    """
    try:
        import metalcompute as mc
        device = mc.Device()
        return True
    except (ImportError, Exception):
        return False


def clear_kernel_cache():
    """Clear the kernel compilation cache.

    Useful for testing or when switching contexts.
    """
    global _kernel_cache
    _kernel_cache = {}


# Keep callback alive for the lifetime of the module
_keep_alive = None


def ensure_callback_alive():
    """Ensure the callback object is kept alive.

    Call this before executing any compiled code that might use GPU dispatch.
    """
    global _keep_alive
    if _keep_alive is None:
        _keep_alive = get_dispatch_callback()
