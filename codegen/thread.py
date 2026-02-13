"""
Thread concurrency implementation for Coex.

This module provides structured concurrency through the `thread` function kind.
Threads spawn OS threads via pthreads, with explicit parameter passing,
cooperative cancellation, and three collection strategies (for, first, most).

Key concepts:
- TaskClosure: Per-thread execution context with params, result, cancellation
- Nursery: Per-function tracking of spawned threads for join-at-exit
- Trampoline: Compiler-generated entry point for each thread function

The C runtime (runtime/coex_task.c) handles pthread operations.
"""
from typing import TYPE_CHECKING, Dict, List, Optional, Tuple
from llvmlite import ir

if TYPE_CHECKING:
    from codegen.core import CodeGenerator
    from ast_nodes import FunctionDecl, Type


class ThreadGenerator:
    """Generates thread concurrency infrastructure for the Coex compiler."""

    def __init__(self, codegen: 'CodeGenerator'):
        """Initialize with reference to parent CodeGenerator instance."""
        self.cg = codegen

        # Task-related LLVM types (initialized in create_task_types)
        self.closure_type: Optional[ir.Type] = None
        self.closure_ptr_type: Optional[ir.Type] = None
        self.thread_handle_type: Optional[ir.Type] = None

        # Runtime function declarations
        self.closure_alloc: Optional[ir.Function] = None
        self.closure_free: Optional[ir.Function] = None
        self.task_spawn: Optional[ir.Function] = None
        self.task_join: Optional[ir.Function] = None
        self.task_cancel: Optional[ir.Function] = None
        self.task_is_cancelled: Optional[ir.Function] = None
        self.task_signal_complete: Optional[ir.Function] = None
        self.task_wait_complete: Optional[ir.Function] = None
        self.task_wait_any: Optional[ir.Function] = None
        self.task_wait_all: Optional[ir.Function] = None

        # Task trampoline tracking
        # Maps task function name -> trampoline function
        self.trampolines: Dict[str, ir.Function] = {}

        # Parameter struct types for task calls
        # Maps (task_name, call_site_id) -> params struct type
        self.param_struct_types: Dict[Tuple[str, int], ir.Type] = {}
        self._param_struct_counter = 0

        # Nursery tracking per function
        # When generating a function, this tracks spawned tasks
        self._current_nursery_handles: List[ir.Value] = []
        self._current_nursery_closures: List[ir.Value] = []
        self._nursery_handles_alloca: Optional[ir.AllocaInst] = None
        self._nursery_closures_alloca: Optional[ir.AllocaInst] = None
        self._nursery_count_alloca: Optional[ir.AllocaInst] = None

    def reset_for_function(self):
        """Reset nursery state for a new function generation.

        Must be called at the start of each function generation to ensure
        nursery allocas from previous functions don't leak into the new one.
        """
        self._current_nursery_handles = []
        self._current_nursery_closures = []
        self._nursery_handles_alloca = None
        self._nursery_closures_alloca = None
        self._nursery_count_alloca = None

    def create_task_types(self):
        """Create task-related LLVM types and declare runtime functions.

        This should be called during CodeGenerator initialization,
        after basic types are set up but before function generation.
        """
        cg = self.cg

        # Common types
        i8 = ir.IntType(8)
        i8_ptr = i8.as_pointer()
        i32 = ir.IntType(32)
        i64 = ir.IntType(64)
        i1 = ir.IntType(1)
        void = ir.VoidType()

        # TaskClosure struct - must match runtime/coex_task.h
        # struct TaskClosure {
        #     void* params;           // i8*
        #     void* result;           // i8*
        #     void* exception;        // i8*
        #     atomic_bool cancelled;  // i8
        #     atomic_bool completed;  // i8
        #     pthread_mutex_t mutex;  // opaque, treat as i8*
        #     pthread_cond_t cond;    // opaque, treat as i8*
        # }
        #
        # Note: We use i8* for the pthread types since we only access
        # through the C runtime functions, not directly in LLVM IR.
        self.closure_type = ir.global_context.get_identified_type("struct.TaskClosure")
        self.closure_type.set_body(
            i8_ptr,     # 0: params
            i8_ptr,     # 1: result (stored as pointer, actually i64 handle)
            i8_ptr,     # 2: exception (stored as pointer, actually i64 handle)
            i8,         # 3: cancelled (atomic bool)
            i8,         # 4: completed (atomic bool)
            # Note: mutex and cond are in the C struct but we don't
            # access them directly - they're managed by C runtime
        )
        self.closure_ptr_type = self.closure_type.as_pointer()

        # Thread handle is pthread_t which is platform-specific
        # On most platforms it's a pointer or unsigned long
        # We treat it as i64 for simplicity
        self.thread_handle_type = i64

        # Declare C runtime functions
        self._declare_runtime_functions()

    def _declare_runtime_functions(self):
        """Declare external references to C runtime task functions."""
        cg = self.cg

        i8_ptr = ir.IntType(8).as_pointer()
        i32 = ir.IntType(32)
        i64 = ir.IntType(64)
        i1 = ir.IntType(1)
        void = ir.VoidType()

        closure_ptr = self.closure_ptr_type
        thread_handle = self.thread_handle_type

        # Task entry function type: void (*)(TaskClosure*)
        self.task_entry_fn_type = ir.FunctionType(void, [closure_ptr])
        task_entry_ptr = self.task_entry_fn_type.as_pointer()

        # coex_task_closure_alloc(params_size: size_t) -> TaskClosure*
        alloc_ty = ir.FunctionType(closure_ptr, [i64])
        self.closure_alloc = ir.Function(cg.module, alloc_ty, name="coex_task_closure_alloc")
        cg.functions["coex_task_closure_alloc"] = self.closure_alloc

        # coex_task_closure_free(closure: TaskClosure*) -> void
        free_ty = ir.FunctionType(void, [closure_ptr])
        self.closure_free = ir.Function(cg.module, free_ty, name="coex_task_closure_free")
        cg.functions["coex_task_closure_free"] = self.closure_free

        # coex_task_spawn(entry: TaskEntryFn, closure: TaskClosure*) -> pthread_t
        spawn_ty = ir.FunctionType(thread_handle, [task_entry_ptr, closure_ptr])
        self.task_spawn = ir.Function(cg.module, spawn_ty, name="coex_task_spawn")
        cg.functions["coex_task_spawn"] = self.task_spawn

        # coex_task_join(thread: pthread_t) -> void
        join_ty = ir.FunctionType(void, [thread_handle])
        self.task_join = ir.Function(cg.module, join_ty, name="coex_task_join")
        cg.functions["coex_task_join"] = self.task_join

        # coex_task_cancel(closure: TaskClosure*) -> void
        cancel_ty = ir.FunctionType(void, [closure_ptr])
        self.task_cancel = ir.Function(cg.module, cancel_ty, name="coex_task_cancel")
        cg.functions["coex_task_cancel"] = self.task_cancel

        # coex_task_is_cancelled(closure: TaskClosure*) -> bool
        is_cancelled_ty = ir.FunctionType(i1, [closure_ptr])
        self.task_is_cancelled = ir.Function(cg.module, is_cancelled_ty, name="coex_task_is_cancelled")
        cg.functions["coex_task_is_cancelled"] = self.task_is_cancelled

        # coex_task_signal_complete(closure: TaskClosure*) -> void
        signal_ty = ir.FunctionType(void, [closure_ptr])
        self.task_signal_complete = ir.Function(cg.module, signal_ty, name="coex_task_signal_complete")
        cg.functions["coex_task_signal_complete"] = self.task_signal_complete

        # coex_task_wait_complete(closure: TaskClosure*) -> void
        wait_ty = ir.FunctionType(void, [closure_ptr])
        self.task_wait_complete = ir.Function(cg.module, wait_ty, name="coex_task_wait_complete")
        cg.functions["coex_task_wait_complete"] = self.task_wait_complete

        # coex_task_wait_any(closures: TaskClosure**, count: int) -> int
        closure_ptr_ptr = closure_ptr.as_pointer()
        wait_any_ty = ir.FunctionType(i32, [closure_ptr_ptr, i32])
        self.task_wait_any = ir.Function(cg.module, wait_any_ty, name="coex_task_wait_any")
        cg.functions["coex_task_wait_any"] = self.task_wait_any

        # coex_task_wait_all(closures: TaskClosure**, count: int) -> void
        wait_all_ty = ir.FunctionType(void, [closure_ptr_ptr, i32])
        self.task_wait_all = ir.Function(cg.module, wait_all_ty, name="coex_task_wait_all")
        cg.functions["coex_task_wait_all"] = self.task_wait_all

        # coex_task_set_current(closure: TaskClosure*) -> void
        set_current_ty = ir.FunctionType(void, [closure_ptr])
        self.task_set_current = ir.Function(cg.module, set_current_ty, name="coex_task_set_current")
        cg.functions["coex_task_set_current"] = self.task_set_current

        # coex_task_get_current() -> TaskClosure*
        get_current_ty = ir.FunctionType(closure_ptr, [])
        self.task_get_current = ir.Function(cg.module, get_current_ty, name="coex_task_get_current")
        cg.functions["coex_task_get_current"] = self.task_get_current

        # coex_task_check_safepoint() -> int (1 if cancelled, 0 otherwise)
        check_safepoint_ty = ir.FunctionType(i32, [])
        self.task_check_safepoint = ir.Function(cg.module, check_safepoint_ty, name="coex_task_check_safepoint")
        cg.functions["coex_task_check_safepoint"] = self.task_check_safepoint

    # =========================================================================
    # Nursery Management
    # =========================================================================

    def init_nursery(self, builder: ir.IRBuilder, max_tasks: int = 64):
        """Initialize nursery for the current function.

        Called at function entry to set up tracking for bare task calls.
        The nursery stores thread handles and closure pointers for tasks
        that will be joined at function exit.

        Args:
            builder: IR builder for current function entry block
            max_tasks: Maximum number of bare task calls expected (can grow)
        """
        i64 = ir.IntType(64)

        # Allocate arrays for handles and closures
        # These are stack-allocated arrays of fixed size
        handles_array_type = ir.ArrayType(self.thread_handle_type, max_tasks)
        closures_array_type = ir.ArrayType(self.closure_ptr_type, max_tasks)

        self._nursery_handles_alloca = builder.alloca(handles_array_type, name="nursery_handles")
        self._nursery_closures_alloca = builder.alloca(closures_array_type, name="nursery_closures")

        # Counter for current number of tasks in nursery
        self._nursery_count_alloca = builder.alloca(i64, name="nursery_count")
        builder.store(ir.Constant(i64, 0), self._nursery_count_alloca)

        # Clear runtime lists
        self._current_nursery_handles = []
        self._current_nursery_closures = []

    def add_to_nursery(self, builder: ir.IRBuilder,
                       thread_handle: ir.Value,
                       closure_ptr: ir.Value):
        """Add a spawned task to the current function's nursery.

        Args:
            builder: IR builder
            thread_handle: pthread_t value from coex_task_spawn
            closure_ptr: TaskClosure* pointer
        """
        if self._nursery_count_alloca is None:
            raise RuntimeError("Nursery not initialized - call init_nursery first")

        i32 = ir.IntType(32)
        i64 = ir.IntType(64)

        # Load current count
        count = builder.load(self._nursery_count_alloca, name="nursery_idx")
        count_i32 = builder.trunc(count, i32)

        # Store handle at handles[count]
        handle_ptr = builder.gep(
            self._nursery_handles_alloca,
            [ir.Constant(i32, 0), count_i32],
            inbounds=True,
            name="handle_slot"
        )
        builder.store(thread_handle, handle_ptr)

        # Store closure at closures[count]
        closure_slot = builder.gep(
            self._nursery_closures_alloca,
            [ir.Constant(i32, 0), count_i32],
            inbounds=True,
            name="closure_slot"
        )
        builder.store(closure_ptr, closure_slot)

        # Increment count
        new_count = builder.add(count, ir.Constant(i64, 1))
        builder.store(new_count, self._nursery_count_alloca)

    def join_nursery(self, builder: ir.IRBuilder):
        """Join all tasks in the nursery at function exit.

        This is called before gc_pop_frame in function epilogue.
        All spawned tasks are joined, and their closures freed.
        """
        if self._nursery_count_alloca is None:
            # No nursery initialized, nothing to do
            return

        cg = self.cg
        i32 = ir.IntType(32)
        i64 = ir.IntType(64)

        # Get current count
        count = builder.load(self._nursery_count_alloca, name="final_count")

        # Check if count > 0
        zero = ir.Constant(i64, 0)
        has_tasks = builder.icmp_signed('>', count, zero, name="has_tasks")

        # Track current block for phi incoming
        entry_block = builder.block

        # Create blocks for the join loop
        func = builder.block.function
        join_loop = func.append_basic_block("nursery_join_loop")
        join_body = func.append_basic_block("nursery_join_body")
        join_done = func.append_basic_block("nursery_join_done")

        builder.cbranch(has_tasks, join_loop, join_done)

        # Join loop: for i = 0; i < count; i++
        builder.position_at_end(join_loop)
        i_phi = builder.phi(i64, name="join_idx")
        i_phi.add_incoming(zero, entry_block)

        # Check if i < count
        in_range = builder.icmp_signed('<', i_phi, count, name="in_range")
        builder.cbranch(in_range, join_body, join_done)

        # Join body
        builder.position_at_end(join_body)
        i_i32 = builder.trunc(i_phi, i32)

        # Load thread handle
        handle_ptr = builder.gep(
            self._nursery_handles_alloca,
            [ir.Constant(i32, 0), i_i32],
            inbounds=True
        )
        thread_handle = builder.load(handle_ptr, name="thread_handle")

        # Load closure pointer
        closure_ptr = builder.gep(
            self._nursery_closures_alloca,
            [ir.Constant(i32, 0), i_i32],
            inbounds=True
        )
        closure = builder.load(closure_ptr, name="closure")

        # Join the thread
        builder.call(self.task_join, [thread_handle])

        # Free the closure
        builder.call(self.closure_free, [closure])

        # Increment i
        next_i = builder.add(i_phi, ir.Constant(i64, 1))
        i_phi.add_incoming(next_i, join_body)
        builder.branch(join_loop)

        # Done
        builder.position_at_end(join_done)

        # Reset nursery state
        self._nursery_count_alloca = None
        self._nursery_handles_alloca = None
        self._nursery_closures_alloca = None

    # =========================================================================
    # Parameter Struct Generation
    # =========================================================================

    def get_or_create_param_struct(self, task_name: str,
                                    param_types: List[ir.Type]) -> ir.Type:
        """Get or create a parameter struct type for a task call site.

        Each unique combination of task + parameter types gets its own struct.

        Args:
            task_name: Name of the task function being called
            param_types: LLVM types of the parameters

        Returns:
            LLVM struct type for the parameters
        """
        # Create a key from task name and param type string representations
        type_key = (task_name, tuple(str(t) for t in param_types))

        if type_key in self.param_struct_types:
            return self.param_struct_types[type_key]

        # Create new struct type
        struct_name = f"struct.TaskParams_{task_name}_{self._param_struct_counter}"
        self._param_struct_counter += 1

        param_struct = ir.global_context.get_identified_type(struct_name)
        if param_types:
            param_struct.set_body(*param_types)
        else:
            # Empty struct for no-arg tasks
            param_struct.set_body(ir.IntType(8))  # Placeholder byte

        self.param_struct_types[type_key] = param_struct
        return param_struct

    # =========================================================================
    # Trampoline Generation
    # =========================================================================

    def generate_trampoline(self, task_func: 'FunctionDecl',
                            task_llvm_func: ir.Function) -> ir.Function:
        """Generate a trampoline function for a task.

        The trampoline is the actual entry point called by pthread_create.
        It handles:
        1. GC thread registration
        2. Shadow stack setup
        3. Parameter extraction from closure
        4. Calling the actual task body
        5. Storing result in closure
        6. Signaling completion
        7. GC thread unregistration

        Args:
            task_func: AST node for the task function
            task_llvm_func: LLVM function for the task body

        Returns:
            LLVM trampoline function
        """
        cg = self.cg

        # Check if trampoline already exists
        trampoline_name = f"_task_trampoline_{task_func.name}"
        if trampoline_name in self.trampolines:
            return self.trampolines[trampoline_name]

        # Create trampoline function: void trampoline(TaskClosure*)
        trampoline_type = ir.FunctionType(ir.VoidType(), [self.closure_ptr_type])
        trampoline = ir.Function(cg.module, trampoline_type, name=trampoline_name)
        trampoline.args[0].name = "closure"

        entry = trampoline.append_basic_block("entry")
        builder = ir.IRBuilder(entry)

        closure_ptr = trampoline.args[0]
        i32 = ir.IntType(32)
        i64 = ir.IntType(64)
        i8_ptr = ir.IntType(8).as_pointer()

        # 1. Register thread with GC
        if cg.gc is not None and cg.gc.gc_register_thread is not None:
            builder.call(cg.gc.gc_register_thread, [])

        # 1b. Set current task closure for safepoint checks (TLS)
        builder.call(self.task_set_current, [closure_ptr])

        # 2. Push GC frame for HEAP-TYPE parameters AND result handle
        # CRITICAL: Only allocate slots for heap types (list, map, string, etc.)
        # Primitive types (int, float, bool) must NOT be rooted - their values would
        # be misinterpreted as handle indices during GC root scanning!
        num_heap_params = 0
        heap_param_indices = []  # Map heap param slot -> original param index
        for i, param in enumerate(task_func.params):
            if param.type_annotation and cg._is_heap_type(param.type_annotation):
                heap_param_indices.append(i)
                num_heap_params += 1

        # BUG-099: Also need a slot for heap-type return values
        returns_heap_type = (task_func.return_type is not None and cg._is_heap_type(task_func.return_type))
        total_gc_slots = num_heap_params + (1 if returns_heap_type else 0)

        frame_ptr = None
        if cg.gc is not None and total_gc_slots > 0:
            frame_ptr = cg.gc.push_frame(builder, total_gc_slots)

        # 3. Extract parameters from closure->params
        params_ptr_field = builder.gep(
            closure_ptr,
            [ir.Constant(i32, 0), ir.Constant(i32, 0)],
            inbounds=True,
            name="params_field"
        )
        params_ptr = builder.load(params_ptr_field, name="params_ptr")

        # Build list of extracted parameter values
        call_args = []
        heap_slot = 0  # Track slot index for heap params
        if task_func.params:
            # Get param struct type
            param_llvm_types = [arg.type for arg in task_llvm_func.args]
            param_struct = self.get_or_create_param_struct(task_func.name, param_llvm_types)

            # Cast params pointer to param struct pointer
            params_struct_ptr = builder.bitcast(params_ptr, param_struct.as_pointer())

            # Extract each parameter
            for i, param in enumerate(task_func.params):
                param_ptr = builder.gep(
                    params_struct_ptr,
                    [ir.Constant(i32, 0), ir.Constant(i32, i)],
                    inbounds=True,
                    name=f"param_{param.name}_ptr"
                )
                param_val = builder.load(param_ptr, name=f"param_{param.name}")
                call_args.append(param_val)

                # Register heap-type parameters as GC roots
                if cg.gc is not None and frame_ptr is not None:
                    if param.type_annotation and cg._is_heap_type(param.type_annotation):
                        cg.gc.set_root(builder, frame_ptr, heap_slot, param_val)
                        heap_slot += 1

        # 4. Call the actual task body
        result = builder.call(task_llvm_func, call_args, name="task_result")

        # 5. Store result in closure->result
        result_field = builder.gep(
            closure_ptr,
            [ir.Constant(i32, 0), ir.Constant(i32, 1)],
            inbounds=True,
            name="result_field"
        )
        # Convert result to i8* for storage in closure
        # BUG-099: For heap-type pointer results, convert to GC handle first
        # so the stored i64 is a stable handle, not a raw pointer that goes stale
        # With handles-everywhere, all reference type results are already i64 handles
        result_handle = None
        if result.type == i64:
            result_handle = result  # May be a GC handle for ref types
            result_ptr = builder.inttoptr(result, i8_ptr)
        elif result.type == ir.VoidType():
            result_ptr = ir.Constant(i8_ptr, None)
        elif isinstance(result.type, (ir.DoubleType, ir.FloatType)):
            if isinstance(result.type, ir.FloatType):
                result = builder.fpext(result, ir.DoubleType())
            result_i64 = builder.bitcast(result, i64)
            result_ptr = builder.inttoptr(result_i64, i8_ptr)
        elif hasattr(result.type, 'is_pointer') and result.type.is_pointer:
            # Legacy path for actual pointer types (e.g., channels)
            result_i64 = builder.ptrtoint(result, i64)
            result_ptr = builder.inttoptr(result_i64, i8_ptr)
        else:
            result_i64 = builder.zext(result, i64)
            result_ptr = builder.inttoptr(result_i64, i8_ptr)
        builder.store(result_ptr, result_field)

        # BUG-099: Root the result handle so it survives GC between task
        # completion and main thread consumption
        if returns_heap_type and result_handle is not None and frame_ptr is not None:
            cg.gc.set_root(builder, frame_ptr, num_heap_params, result_handle)

        # 6. Pop GC frame
        if cg.gc is not None and total_gc_slots > 0:
            cg.gc.pop_frame(builder, frame_ptr)

        # 7. Clear current task closure TLS before signaling completion
        null_closure = ir.Constant(self.closure_ptr_type, None)
        builder.call(self.task_set_current, [null_closure])

        # 8. Signal completion
        builder.call(self.task_signal_complete, [closure_ptr])

        # 9. Unregister thread from GC
        if cg.gc is not None and cg.gc.gc_unregister_thread is not None:
            builder.call(cg.gc.gc_unregister_thread, [])

        builder.ret_void()

        self.trampolines[trampoline_name] = trampoline
        cg.functions[trampoline_name] = trampoline

        return trampoline

    # =========================================================================
    # Task Spawning
    # =========================================================================

    def spawn_task(self, builder: ir.IRBuilder,
                   task_func: 'FunctionDecl',
                   task_llvm_func: ir.Function,
                   args: List[ir.Value],
                   add_to_nursery: bool = True) -> Tuple[ir.Value, ir.Value]:
        """Spawn a task with given arguments.

        Args:
            builder: IR builder
            task_func: AST node for task function
            task_llvm_func: LLVM function for task body
            args: Argument values to pass to task
            add_to_nursery: Whether to add to function nursery for auto-join

        Returns:
            Tuple of (thread_handle, closure_ptr)
        """
        cg = self.cg
        i32 = ir.IntType(32)
        i64 = ir.IntType(64)
        i8_ptr = ir.IntType(8).as_pointer()

        # Get or create trampoline
        trampoline = self.generate_trampoline(task_func, task_llvm_func)

        # Calculate params struct size
        param_types = [arg.type for arg in args]
        if param_types:
            param_struct = self.get_or_create_param_struct(task_func.name, param_types)
            # Use 8 bytes per parameter (all types are i64 or pointer-sized)
            params_size = len(param_types) * 8
        else:
            param_struct = None
            params_size = 0

        # Allocate closure
        params_size_val = ir.Constant(i64, max(params_size, 1))  # At least 1 byte
        closure_ptr = builder.call(self.closure_alloc, [params_size_val], name="closure")

        # Fill in parameters
        if args and param_struct:
            params_field = builder.gep(
                closure_ptr,
                [ir.Constant(i32, 0), ir.Constant(i32, 0)],
                inbounds=True
            )
            params_ptr = builder.load(params_field)
            params_struct_ptr = builder.bitcast(params_ptr, param_struct.as_pointer())

            for i, arg in enumerate(args):
                arg_ptr = builder.gep(
                    params_struct_ptr,
                    [ir.Constant(i32, 0), ir.Constant(i32, i)],
                    inbounds=True
                )
                builder.store(arg, arg_ptr)

        # Spawn thread
        thread_handle = builder.call(
            self.task_spawn,
            [trampoline, closure_ptr],
            name="thread_handle"
        )

        # Add to nursery if requested
        if add_to_nursery:
            self.add_to_nursery(builder, thread_handle, closure_ptr)

        return thread_handle, closure_ptr

    # =========================================================================
    # Cancellation Support
    # =========================================================================

    def inject_cancellation_check(self, builder: ir.IRBuilder,
                                   closure_ptr: ir.Value):
        """Inject a cancellation check at a safepoint.

        If the task has been cancelled, this will trigger early exit.
        Called at loop back-edges and other safepoints in task functions.

        Args:
            builder: IR builder
            closure_ptr: Pointer to current task's closure (stored as function local)
        """
        # Check cancellation flag
        is_cancelled = builder.call(
            self.task_is_cancelled,
            [closure_ptr],
            name="is_cancelled"
        )

        # Create exit block for cancellation
        func = builder.block.function
        cancel_block = func.append_basic_block("cancelled")
        continue_block = func.append_basic_block("continue")

        builder.cbranch(is_cancelled, cancel_block, continue_block)

        # Cancelled path: signal completion and exit
        builder.position_at_end(cancel_block)
        builder.call(self.task_signal_complete, [closure_ptr])

        # Unregister from GC if needed
        cg = self.cg
        if cg.gc is not None and cg.gc.gc_unregister_thread is not None:
            builder.call(cg.gc.gc_unregister_thread, [])

        builder.ret_void()

        # Continue normal execution
        builder.position_at_end(continue_block)

    def inject_safepoint(self, builder: ir.IRBuilder, loop_exit_block):
        """Inject a TLS-based cancellation safepoint check.

        Uses thread-local storage to check if current task is cancelled.
        If cancelled, branches to the loop exit block for early termination.
        Safe to call from any context - returns immediately if not in a task.

        Also calls the GC safepoint to acknowledge watermarks for GC
        synchronization. This is critical for the watermark protocol to work -
        without safepoints at loop backedges, a thread in a long loop would
        never acknowledge the GC watermark and GC would hang waiting.

        This is the preferred method for loop back-edge safepoints as it
        doesn't require tracking the closure pointer through the call stack.

        Args:
            builder: IR builder positioned at the safepoint location
            loop_exit_block: Block to branch to if cancelled
        """
        i32 = ir.IntType(32)

        # First, call GC safepoint for watermark acknowledgment
        # This must happen at loop backedges to allow GC coordination
        builder.call(self.cg.gc.gc_safepoint, [])

        # Call TLS-based check: returns 1 if cancelled, 0 otherwise
        is_cancelled = builder.call(
            self.task_check_safepoint,
            [],
            name="safepoint_check"
        )

        # Compare result to 0
        zero = ir.Constant(i32, 0)
        cancelled = builder.icmp_signed('!=', is_cancelled, zero, name="is_cancelled")

        # Branch: if cancelled, exit loop; otherwise continue
        func = builder.block.function
        continue_block = func.append_basic_block("safepoint_continue")

        builder.cbranch(cancelled, loop_exit_block, continue_block)

        # Position builder in continue block for normal execution
        builder.position_at_end(continue_block)

    # =========================================================================
    # Utility Methods
    # =========================================================================

    def has_active_nursery(self) -> bool:
        """Check if there's an active nursery for the current function."""
        return self._nursery_count_alloca is not None

    def get_nursery_count(self, builder: ir.IRBuilder) -> ir.Value:
        """Get current number of tasks in nursery."""
        if self._nursery_count_alloca is None:
            return ir.Constant(ir.IntType(64), 0)
        return builder.load(self._nursery_count_alloca)
