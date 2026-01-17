"""
Task Transformation Module

Transforms task functions into stackless coroutines executed on the work-stealing scheduler.

Implementation approach:
1. For tasks with NO suspension points (no task-to-task calls): generate direct execution
2. For tasks WITH suspension points: generate state machine with step function

The frame struct holds:
- state: int (current state in the state machine)
- resolved: int64 (result from subtask call)
- parameters: all function parameters
- hoisted_locals: locals that span suspension points
"""

from dataclasses import dataclass
from typing import List, Dict, Optional, Set, TYPE_CHECKING
from llvmlite import ir

from ast_nodes import FunctionDecl, FunctionKind, Type, Parameter
from task_analysis import analyze_task, TaskAnalysis, SuspensionPoint, ControlFlowContext

if TYPE_CHECKING:
    from codegen.core import CodeGenerator


# TaskResult kind constants (must match runtime/coex_scheduler.h)
TASK_RESULT_DONE = 0
TASK_RESULT_SPAWN = 1


@dataclass
class TaskFrameInfo:
    """Information about a task's frame struct."""
    task_name: str
    frame_type_name: str
    llvm_frame_type: ir.Type
    field_indices: Dict[str, int]  # field_name -> index
    parameters: List[Parameter]
    return_type: Optional[Type]


class TaskTransformer:
    """Transforms task functions for scheduler execution."""

    def __init__(self, cg: 'CodeGenerator'):
        self.cg = cg
        self.task_frames: Dict[str, TaskFrameInfo] = {}
        self.step_functions: Dict[str, ir.Function] = {}

        # Track which functions are tasks
        self._task_function_names: Set[str] = set()

        # Scheduler runtime functions (declared lazily)
        self._scheduler_init_fn = None
        self._scheduler_spawn_and_wait_fn = None

        # Batch spawn APIs for first/most
        self._first_context_create_fn = None
        self._first_context_destroy_fn = None
        self._first_spawn_task_fn = None
        self._first_wait_fn = None
        self._most_context_create_fn = None
        self._most_context_destroy_fn = None
        self._most_spawn_task_fn = None
        self._most_wait_fn = None

    def register_task_function(self, name: str):
        """Register a function name as a task function."""
        self._task_function_names.add(name)

    def get_task_function_names(self) -> Set[str]:
        """Get set of all registered task function names."""
        return self._task_function_names

    # ========================================================================
    # Mutual Recursion Support
    # ========================================================================

    def prepare_all_tasks_for_mutual_recursion(self, task_functions: List[FunctionDecl]):
        """
        Prepare all task functions for mutual recursion support.

        This method must be called BEFORE generating any task function bodies.
        It creates frame types and declares step functions for ALL tasks,
        allowing mutual recursion between tasks (e.g., is_even calling is_odd
        and is_odd calling is_even).

        Without this preparation, a task being generated cannot reference
        another task that hasn't been generated yet.
        """
        # First pass: analyze all tasks and create their frame types
        task_analyses = {}
        for func in task_functions:
            if func.kind != FunctionKind.TASK:
                continue
            analysis = analyze_task(func, self._task_function_names)
            if analysis.suspension_points:  # Only tasks with suspension points need this
                task_analyses[func.name] = (func, analysis)
                # Create frame type for this task
                self.get_or_create_frame_type(func, analysis)

        # Second pass: declare step functions for all analyzed tasks
        # This ensures all step functions exist before any body is generated
        for func_name, (func, analysis) in task_analyses.items():
            if func_name not in self.step_functions:
                frame_info = self.task_frames[func_name]
                self._declare_step_function(func, frame_info)

    def _declare_step_function(self, func: FunctionDecl, frame_info: TaskFrameInfo) -> ir.Function:
        """
        Declare a step function without generating its body.

        This creates the function signature and registers it, allowing other
        tasks to reference it during their code generation.
        """
        cg = self.cg

        # TaskResult struct matches C layout
        task_result_type = ir.LiteralStructType([
            ir.IntType(32),  # kind (offset 0)
            ir.IntType(32),  # padding (offset 4)
            ir.IntType(64),  # value or frame as i64 (offset 8)
            ir.IntType(8).as_pointer(),  # step_fn (offset 16)
        ])

        # Step function type: void step(Frame*, i64 resolved, TaskResult* out)
        step_fn_type = ir.FunctionType(
            ir.VoidType(),
            [frame_info.llvm_frame_type.as_pointer(), ir.IntType(64),
             task_result_type.as_pointer()]
        )

        step_fn_name = f"__{func.name}_step"
        step_fn = ir.Function(cg.module, step_fn_type, name=step_fn_name)
        step_fn.args[0].name = "frame"
        step_fn.args[1].name = "resolved"
        step_fn.args[2].name = "out_result"

        # Register step function
        self.step_functions[func.name] = step_fn

        return step_fn

    # ========================================================================
    # Scheduler Runtime Integration
    # ========================================================================

    def declare_scheduler_functions(self):
        """Declare scheduler runtime functions."""
        cg = self.cg
        module = cg.module

        # void coex_scheduler_ensure_init(void)
        if self._scheduler_init_fn is None:
            fn_type = ir.FunctionType(ir.VoidType(), [])
            self._scheduler_init_fn = ir.Function(module, fn_type,
                                                   name="coex_scheduler_ensure_init")

        # int64_t coex_scheduler_spawn_and_wait(void* frame, void* step_fn)
        if self._scheduler_spawn_and_wait_fn is None:
            fn_type = ir.FunctionType(
                ir.IntType(64),
                [ir.IntType(8).as_pointer(), ir.IntType(8).as_pointer()]
            )
            self._scheduler_spawn_and_wait_fn = ir.Function(
                module, fn_type, name="coex_scheduler_spawn_and_wait"
            )

    def ensure_scheduler_init(self, builder: ir.IRBuilder):
        """Generate call to ensure scheduler is initialized."""
        self.declare_scheduler_functions()
        builder.call(self._scheduler_init_fn, [])

    def declare_first_most_functions(self):
        """Declare scheduler batch spawn functions for first/most."""
        cg = self.cg
        module = cg.module
        i64 = ir.IntType(64)
        i8_ptr = ir.IntType(8).as_pointer()

        # FirstContext* coex_scheduler_first_context_create(int64_t count)
        if self._first_context_create_fn is None:
            fn_type = ir.FunctionType(i8_ptr, [i64])
            self._first_context_create_fn = ir.Function(
                module, fn_type, name="coex_scheduler_first_context_create"
            )

        # void coex_scheduler_first_context_destroy(FirstContext* ctx)
        if self._first_context_destroy_fn is None:
            fn_type = ir.FunctionType(ir.VoidType(), [i8_ptr])
            self._first_context_destroy_fn = ir.Function(
                module, fn_type, name="coex_scheduler_first_context_destroy"
            )

        # void coex_scheduler_first_spawn_task(FirstContext* ctx, int64_t index, void* frame, StepFunction step_fn)
        if self._first_spawn_task_fn is None:
            fn_type = ir.FunctionType(ir.VoidType(), [i8_ptr, i64, i8_ptr, i8_ptr])
            self._first_spawn_task_fn = ir.Function(
                module, fn_type, name="coex_scheduler_first_spawn_task"
            )

        # int64_t coex_scheduler_first_wait(FirstContext* ctx)
        if self._first_wait_fn is None:
            fn_type = ir.FunctionType(i64, [i8_ptr])
            self._first_wait_fn = ir.Function(
                module, fn_type, name="coex_scheduler_first_wait"
            )

        # MostContext* coex_scheduler_most_context_create(int64_t count)
        if self._most_context_create_fn is None:
            fn_type = ir.FunctionType(i8_ptr, [i64])
            self._most_context_create_fn = ir.Function(
                module, fn_type, name="coex_scheduler_most_context_create"
            )

        # void coex_scheduler_most_context_destroy(MostContext* ctx)
        if self._most_context_destroy_fn is None:
            fn_type = ir.FunctionType(ir.VoidType(), [i8_ptr])
            self._most_context_destroy_fn = ir.Function(
                module, fn_type, name="coex_scheduler_most_context_destroy"
            )

        # void coex_scheduler_most_spawn_task(MostContext* ctx, void* frame, StepFunction step_fn)
        if self._most_spawn_task_fn is None:
            fn_type = ir.FunctionType(ir.VoidType(), [i8_ptr, i8_ptr, i8_ptr])
            self._most_spawn_task_fn = ir.Function(
                module, fn_type, name="coex_scheduler_most_spawn_task"
            )

        # void coex_scheduler_most_wait(MostContext* ctx, int64_t** out_results, int64_t* out_count)
        if self._most_wait_fn is None:
            fn_type = ir.FunctionType(ir.VoidType(), [i8_ptr, i8_ptr.as_pointer(), i64.as_pointer()])
            self._most_wait_fn = ir.Function(
                module, fn_type, name="coex_scheduler_most_wait"
            )

    def get_first_context_create(self) -> ir.Function:
        """Get first context create function."""
        self.declare_first_most_functions()
        return self._first_context_create_fn

    def get_first_context_destroy(self) -> ir.Function:
        """Get first context destroy function."""
        self.declare_first_most_functions()
        return self._first_context_destroy_fn

    def get_first_spawn_task(self) -> ir.Function:
        """Get first spawn task function."""
        self.declare_first_most_functions()
        return self._first_spawn_task_fn

    def get_first_wait(self) -> ir.Function:
        """Get first wait function."""
        self.declare_first_most_functions()
        return self._first_wait_fn

    def get_most_context_create(self) -> ir.Function:
        """Get most context create function."""
        self.declare_first_most_functions()
        return self._most_context_create_fn

    def get_most_context_destroy(self) -> ir.Function:
        """Get most context destroy function."""
        self.declare_first_most_functions()
        return self._most_context_destroy_fn

    def get_most_spawn_task(self) -> ir.Function:
        """Get most spawn task function."""
        self.declare_first_most_functions()
        return self._most_spawn_task_fn

    def get_most_wait(self) -> ir.Function:
        """Get most wait function."""
        self.declare_first_most_functions()
        return self._most_wait_fn

    # ========================================================================
    # Frame Type Generation
    # ========================================================================

    def get_or_create_frame_type(self, func: FunctionDecl,
                                  analysis: TaskAnalysis) -> TaskFrameInfo:
        """Get or create frame struct type for a task."""
        if func.name in self.task_frames:
            return self.task_frames[func.name]

        cg = self.cg
        frame_name = f"__TaskFrame_{func.name}"

        # Build field list
        fields = []
        field_indices = {}
        idx = 0

        # Field 0: state (int64)
        fields.append(ir.IntType(64))
        field_indices['__state'] = idx
        idx += 1

        # Field 1: resolved value from subtask (int64)
        fields.append(ir.IntType(64))
        field_indices['__resolved'] = idx
        idx += 1

        # Field 2: waiter pointer (void*)
        fields.append(ir.IntType(8).as_pointer())
        field_indices['__waiter'] = idx
        idx += 1

        # Field 3: branch_taken (for if/else control flow)
        fields.append(ir.IntType(64))
        field_indices['__branch_taken'] = idx
        idx += 1

        # Field 4: loop_idx (current loop iteration index)
        fields.append(ir.IntType(64))
        field_indices['__loop_idx'] = idx
        idx += 1

        # Field 5: loop_end (loop end value)
        fields.append(ir.IntType(64))
        field_indices['__loop_end'] = idx
        idx += 1

        # Parameters
        for param in func.params:
            llvm_type = cg._get_llvm_type(param.type_annotation)
            fields.append(llvm_type)
            field_indices[param.name] = idx
            idx += 1

        # Hoisted locals (those that span suspension points)
        for local_name, local_type in analysis.hoisted_locals.items():
            if local_name not in field_indices:  # Avoid duplicates with params
                llvm_type = cg._get_llvm_type(local_type) if local_type else ir.IntType(64)
                fields.append(llvm_type)
                field_indices[local_name] = idx
                idx += 1

        # Suspension point target variables (receive child task results)
        for sp in analysis.suspension_points:
            if sp.var_name and sp.var_name not in field_indices:
                # Target variable isn't in frame yet - add it
                # Type will be int64 (task results are always i64)
                fields.append(ir.IntType(64))
                field_indices[sp.var_name] = idx
                idx += 1

        # All other locals from the function body (loop variables, etc.)
        # This ensures variables defined in loops/conditionals are accessible
        for local_name, local_type in analysis.all_locals.items():
            if local_name not in field_indices:
                llvm_type = cg._get_llvm_type(local_type) if local_type else ir.IntType(64)
                fields.append(llvm_type)
                field_indices[local_name] = idx
                idx += 1

        # Create LLVM struct type
        frame_type = ir.global_context.get_identified_type(f"struct.{frame_name}")
        frame_type.set_body(*fields)

        info = TaskFrameInfo(
            task_name=func.name,
            frame_type_name=frame_name,
            llvm_frame_type=frame_type,
            field_indices=field_indices,
            parameters=func.params,
            return_type=func.return_type
        )
        self.task_frames[func.name] = info
        return info

    # ========================================================================
    # Simple Task Execution (No Suspension Points)
    # ========================================================================

    def generate_simple_task(self, func: FunctionDecl) -> ir.Function:
        """
        Generate a simple task function for tasks with no suspension points.

        These tasks can run to completion without yielding.
        """
        cg = self.cg

        # Get return type
        if func.return_type:
            ret_type = cg._get_llvm_type(func.return_type)
        else:
            ret_type = ir.VoidType()

        # Get parameter types
        param_types = []
        for param in func.params:
            param_types.append(cg._get_llvm_type(param.type_annotation))

        # Create function type
        fn_type = ir.FunctionType(ret_type, param_types)

        # Create function
        llvm_func = ir.Function(cg.module, fn_type, name=func.name)
        cg.functions[func.name] = llvm_func

        return llvm_func

    def generate_simple_task_with_step(self, func: FunctionDecl):
        """
        Generate a simple task (no suspension points) with step function wrapper.

        For scheduler batch spawning (first/most), we need a step function even
        for tasks that don't suspend. This generates:
        1. The actual task function body (impl function)
        2. A minimal frame type (just parameters)
        3. A step function that calls the impl and returns DONE
        4. An entry function that either uses scheduler (for batch) or calls directly
        """
        cg = self.cg

        # Create a minimal analysis with no suspension points
        from task_analysis import TaskAnalysis
        analysis = TaskAnalysis(
            function_name=func.name,
            parameters=func.params,
            return_type=func.return_type,
            suspension_points=[],
            hoisted_locals={},
            all_locals={}
        )

        # Create frame type (for parameters)
        frame_info = self.get_or_create_frame_type(func, analysis)

        # Generate the impl function first
        impl_fn = self._generate_task_impl(func)

        # Generate step function that calls impl and returns DONE
        step_fn = self._generate_simple_step_function_with_impl(func, frame_info, impl_fn)
        self.step_functions[func.name] = step_fn

        # Generate entry function that just calls impl directly (no scheduler for simple calls)
        self._generate_simple_entry_function(func, impl_fn)

    def _generate_simple_step_function_with_impl(self, func: FunctionDecl,
                                                   frame_info: TaskFrameInfo,
                                                   impl_fn: ir.Function) -> ir.Function:
        """
        Generate a step function for a simple task (no suspension).

        This step function:
        1. Loads parameters from frame
        2. Calls the internal task function
        3. Returns TASK_RESULT_DONE with the result
        """
        cg = self.cg

        # TaskResult struct matches C layout with union:
        # { i32 kind; i32 padding; union { i64 value; struct { i8* frame; i8* step_fn; } }; }
        # For DONE: kind=0, padding=0, value=result, step_fn=null
        task_result_type = ir.LiteralStructType([
            ir.IntType(32),  # kind (offset 0)
            ir.IntType(32),  # padding (offset 4)
            ir.IntType(64),  # value or frame as i64 (offset 8)
            ir.IntType(8).as_pointer(),  # step_fn (offset 16)
        ])

        # Step function type: void step(Frame*, i64 resolved, TaskResult* out)
        # Using output parameter to avoid ABI issues with struct returns
        step_fn_type = ir.FunctionType(
            ir.VoidType(),
            [frame_info.llvm_frame_type.as_pointer(), ir.IntType(64),
             task_result_type.as_pointer()]
        )

        step_fn_name = f"__{func.name}_step"
        step_fn = ir.Function(cg.module, step_fn_type, name=step_fn_name)
        step_fn.args[0].name = "frame"
        step_fn.args[1].name = "resolved"
        step_fn.args[2].name = "out_result"

        # Create entry block
        entry = step_fn.append_basic_block("entry")
        builder = ir.IRBuilder(entry)

        frame_ptr = step_fn.args[0]
        out_ptr = step_fn.args[2]

        # Load parameters from frame and call impl function
        args = []
        for param in func.params:
            param_idx = frame_info.field_indices[param.name]
            param_ptr = builder.gep(frame_ptr, [
                ir.Constant(ir.IntType(32), 0),
                ir.Constant(ir.IntType(32), param_idx)
            ], inbounds=True)
            args.append(builder.load(param_ptr))

        # Call the implementation function
        result_val = builder.call(impl_fn, args, name="result")

        # Cast result to i64 if needed
        if result_val.type != ir.IntType(64):
            if isinstance(result_val.type, ir.IntType):
                result_val = builder.sext(result_val, ir.IntType(64))
            else:
                result_val = builder.ptrtoint(result_val, ir.IntType(64))

        # Store TASK_RESULT_DONE to output parameter
        # Store kind = 0 (TASK_RESULT_DONE)
        kind_ptr = builder.gep(out_ptr, [
            ir.Constant(ir.IntType(32), 0),
            ir.Constant(ir.IntType(32), 0)
        ], inbounds=True)
        builder.store(ir.Constant(ir.IntType(32), TASK_RESULT_DONE), kind_ptr)

        # Store padding = 0
        padding_ptr = builder.gep(out_ptr, [
            ir.Constant(ir.IntType(32), 0),
            ir.Constant(ir.IntType(32), 1)
        ], inbounds=True)
        builder.store(ir.Constant(ir.IntType(32), 0), padding_ptr)

        # Store value
        value_ptr = builder.gep(out_ptr, [
            ir.Constant(ir.IntType(32), 0),
            ir.Constant(ir.IntType(32), 2)
        ], inbounds=True)
        builder.store(result_val, value_ptr)

        # Store step_fn = null
        stepfn_ptr = builder.gep(out_ptr, [
            ir.Constant(ir.IntType(32), 0),
            ir.Constant(ir.IntType(32), 3)
        ], inbounds=True)
        builder.store(ir.Constant(ir.IntType(8).as_pointer(), None), stepfn_ptr)

        builder.ret_void()

        return step_fn

    def _generate_simple_entry_function(self, func: FunctionDecl,
                                         impl_fn: ir.Function):
        """
        Generate a simple entry function that just calls the impl directly.

        For simple tasks called normally (not via first/most), there's no need
        to go through the scheduler. Just call the implementation directly.
        """
        cg = self.cg

        # Reuse existing function declaration
        if func.name not in cg.functions:
            raise RuntimeError(f"Function {func.name} not declared")

        entry_fn = cg.functions[func.name]

        # Create entry block
        entry = entry_fn.append_basic_block("entry")
        builder = ir.IRBuilder(entry)

        # Just call impl with the arguments and return
        result = builder.call(impl_fn, list(entry_fn.args), name="result")
        builder.ret(result)

    def _generate_task_impl(self, func: FunctionDecl) -> ir.Function:
        """Generate the internal implementation function for a simple task."""
        cg = self.cg

        # Get return type
        if func.return_type:
            ret_type = cg._get_llvm_type(func.return_type)
        else:
            ret_type = ir.IntType(64)

        # Get parameter types
        param_types = []
        for param in func.params:
            param_types.append(cg._get_llvm_type(param.type_annotation))

        # Create implementation function with mangled name
        impl_name = f"__{func.name}_impl"
        fn_type = ir.FunctionType(ret_type, param_types)
        impl_fn = ir.Function(cg.module, fn_type, name=impl_name)

        # Name parameters
        for i, param in enumerate(func.params):
            impl_fn.args[i].name = param.name

        # Create entry block
        entry = impl_fn.append_basic_block("entry")

        # Save codegen state
        saved_builder = cg.builder
        saved_locals = cg.locals.copy() if hasattr(cg, 'locals') and cg.locals else {}
        saved_function = getattr(cg, 'current_function', None)
        saved_gc_frame = getattr(cg, 'gc_frame', None)
        saved_gc_root_indices = cg.gc_root_indices.copy() if hasattr(cg, 'gc_root_indices') and cg.gc_root_indices else {}

        # Set up for body generation
        cg.builder = ir.IRBuilder(entry)
        cg.locals = {}
        cg.current_function = func
        cg.gc_frame = None
        cg.gc_root_indices = {}

        # Set up parameter locals
        for i, param in enumerate(func.params):
            llvm_param = impl_fn.args[i]
            alloca = cg.builder.alloca(llvm_param.type, name=param.name)
            cg.builder.store(llvm_param, alloca)
            cg.locals[param.name] = alloca
            if param.type_annotation:
                cg.var_coex_types[param.name] = param.type_annotation

        # Generate body
        for stmt in func.body:
            cg._generate_statement(stmt)
            if cg.builder.block.is_terminated:
                break

        # Add implicit return if needed
        if not cg.builder.block.is_terminated:
            if isinstance(ret_type, ir.VoidType):
                cg.builder.ret_void()
            else:
                cg.builder.ret(ir.Constant(ret_type, 0))

        # Restore state
        cg.builder = saved_builder
        cg.locals = saved_locals
        cg.current_function = saved_function
        cg.gc_frame = saved_gc_frame
        cg.gc_root_indices = saved_gc_root_indices

        return impl_fn

    # ========================================================================
    # State Machine Task (With Suspension Points)
    # ========================================================================

    def generate_task_with_state_machine(self, func: FunctionDecl,
                                          analysis: TaskAnalysis) -> ir.Function:
        """
        Generate a task with state machine transformation.

        Creates:
        1. Frame struct type
        2. Step function that executes one state at a time
        3. Entry function that spawns on scheduler
        """
        cg = self.cg

        # Create frame type
        frame_info = self.get_or_create_frame_type(func, analysis)

        # Generate step function
        step_fn = self._generate_step_function(func, frame_info, analysis)
        self.step_functions[func.name] = step_fn

        # Generate entry function (what callers see)
        entry_fn = self._generate_entry_function(func, frame_info, step_fn)

        return entry_fn

    def _generate_step_function(self, func: FunctionDecl,
                                  frame_info: TaskFrameInfo,
                                  analysis: TaskAnalysis) -> ir.Function:
        """
        Generate the step function that implements the state machine.

        The step function:
        - Takes a frame pointer and output TaskResult*
        - Switches on frame->state to execute current state
        - Writes TASK_RESULT_DONE(value) or TASK_RESULT_SPAWN(child_frame, child_step) to output
        """
        cg = self.cg

        # TaskResult struct matches C layout with union:
        # { i32 kind; i32 padding; union { i64 value; struct { i8* frame; i8* step_fn; } }; }
        # For DONE: kind=0, padding=0, value=result, step_fn=null
        task_result_type = ir.LiteralStructType([
            ir.IntType(32),  # kind (offset 0)
            ir.IntType(32),  # padding (offset 4)
            ir.IntType(64),  # value or frame as i64 (offset 8)
            ir.IntType(8).as_pointer(),  # step_fn (offset 16)
        ])

        # Check if step function was already declared (for mutual recursion support)
        # If so, reuse it; otherwise create a new one
        step_fn = self.step_functions.get(func.name)
        if step_fn is None:
            # Step function type: void step(Frame*, i64 resolved, TaskResult* out)
            # Note: this signature uses output parameter to avoid ABI issues
            step_fn_type = ir.FunctionType(
                ir.VoidType(),
                [frame_info.llvm_frame_type.as_pointer(), ir.IntType(64),
                 task_result_type.as_pointer()]
            )

            step_fn_name = f"__{func.name}_step"
            step_fn = ir.Function(cg.module, step_fn_type, name=step_fn_name)
            step_fn.args[0].name = "frame"
            step_fn.args[1].name = "resolved"
            step_fn.args[2].name = "out_result"

            # Register step function early for recursive calls
            self.step_functions[func.name] = step_fn

        # Create entry block
        entry = step_fn.append_basic_block("entry")
        builder = ir.IRBuilder(entry)

        frame_ptr = step_fn.args[0]
        resolved_val = step_fn.args[1]
        out_ptr = step_fn.args[2]

        # Load current state
        state_ptr = builder.gep(frame_ptr, [
            ir.Constant(ir.IntType(32), 0),
            ir.Constant(ir.IntType(32), frame_info.field_indices['__state'])
        ], inbounds=True, name="state_ptr")
        current_state = builder.load(state_ptr, name="state")

        # Create blocks for each state + default
        num_states = len(analysis.suspension_points) + 1  # Initial state + after each suspension
        state_blocks = []
        for i in range(num_states):
            state_blocks.append(step_fn.append_basic_block(f"state_{i}"))
        default_block = step_fn.append_basic_block("state_default")

        # Switch on state
        switch = builder.switch(current_state, default_block)
        for i, block in enumerate(state_blocks):
            switch.add_case(ir.Constant(ir.IntType(64), i), block)

        # Save and initialize GC state for step function context
        old_gc_frame = getattr(cg, 'gc_frame', None)
        old_gc_root_indices = getattr(cg, 'gc_root_indices', {})
        cg.gc_frame = None
        cg.gc_root_indices = {}

        # Generate code for each state
        self._generate_state_blocks(
            builder, step_fn, frame_ptr, frame_info, func,
            analysis, state_blocks, task_result_type, out_ptr, resolved_val
        )

        # Restore GC state
        cg.gc_frame = old_gc_frame
        cg.gc_root_indices = old_gc_root_indices

        # Default block: write DONE(0) - should never reach here
        builder.position_at_end(default_block)
        self._store_task_result_done(builder, out_ptr, ir.Constant(ir.IntType(64), 0))
        builder.ret_void()

        return step_fn

    def _store_task_result_done(self, builder: ir.IRBuilder, out_ptr: ir.Value, value: ir.Value):
        """Store TASK_RESULT_DONE to output parameter."""
        # Store kind = 0
        kind_ptr = builder.gep(out_ptr, [
            ir.Constant(ir.IntType(32), 0),
            ir.Constant(ir.IntType(32), 0)
        ], inbounds=True)
        builder.store(ir.Constant(ir.IntType(32), TASK_RESULT_DONE), kind_ptr)

        # Store padding = 0
        padding_ptr = builder.gep(out_ptr, [
            ir.Constant(ir.IntType(32), 0),
            ir.Constant(ir.IntType(32), 1)
        ], inbounds=True)
        builder.store(ir.Constant(ir.IntType(32), 0), padding_ptr)

        # Store value
        value_ptr = builder.gep(out_ptr, [
            ir.Constant(ir.IntType(32), 0),
            ir.Constant(ir.IntType(32), 2)
        ], inbounds=True)
        builder.store(value, value_ptr)

        # Store step_fn = null
        stepfn_ptr = builder.gep(out_ptr, [
            ir.Constant(ir.IntType(32), 0),
            ir.Constant(ir.IntType(32), 3)
        ], inbounds=True)
        builder.store(ir.Constant(ir.IntType(8).as_pointer(), None), stepfn_ptr)

    def _store_task_result_spawn(self, builder: ir.IRBuilder, out_ptr: ir.Value,
                                   frame_ptr: ir.Value, step_fn_ptr: ir.Value):
        """Store TASK_RESULT_SPAWN to output parameter."""
        # Store kind = 1
        kind_ptr = builder.gep(out_ptr, [
            ir.Constant(ir.IntType(32), 0),
            ir.Constant(ir.IntType(32), 0)
        ], inbounds=True)
        builder.store(ir.Constant(ir.IntType(32), TASK_RESULT_SPAWN), kind_ptr)

        # Store padding = 0
        padding_ptr = builder.gep(out_ptr, [
            ir.Constant(ir.IntType(32), 0),
            ir.Constant(ir.IntType(32), 1)
        ], inbounds=True)
        builder.store(ir.Constant(ir.IntType(32), 0), padding_ptr)

        # Store frame as i64
        value_ptr = builder.gep(out_ptr, [
            ir.Constant(ir.IntType(32), 0),
            ir.Constant(ir.IntType(32), 2)
        ], inbounds=True)
        frame_as_i64 = builder.ptrtoint(frame_ptr, ir.IntType(64))
        builder.store(frame_as_i64, value_ptr)

        # Store step_fn
        stepfn_ptr = builder.gep(out_ptr, [
            ir.Constant(ir.IntType(32), 0),
            ir.Constant(ir.IntType(32), 3)
        ], inbounds=True)
        builder.store(step_fn_ptr, stepfn_ptr)

    def _get_top_level_stmt_index(self, sp: SuspensionPoint) -> int:
        """
        Get the top-level statement index for a suspension point.

        For top-level suspensions, this is sp.stmt_index.
        For nested suspensions, this is the parent_stmt_index from context.
        """
        if sp.context is None:
            return sp.stmt_index
        return sp.context.parent_stmt_index

    def _are_suspensions_mutually_exclusive(self, sp1: SuspensionPoint, sp2: SuspensionPoint) -> bool:
        """
        Check if two suspension points are in mutually exclusive branches of the same if/else.

        Returns True if sp1 and sp2 are in different branches (then vs else) of the same
        if statement, meaning only one can execute at runtime.
        """
        ctx1 = sp1.context
        ctx2 = sp2.context

        if ctx1 is None or ctx2 is None:
            return False

        # Both must be in if branches
        if ctx1.kind not in ("if_then", "if_else", "if_elif"):
            return False
        if ctx2.kind not in ("if_then", "if_else", "if_elif"):
            return False

        # Must be in the SAME if statement (compare actual parent_stmt objects)
        # parent_stmt_index alone is ambiguous for nested ifs
        if ctx1.parent_stmt is not ctx2.parent_stmt:
            return False

        # Must be in different branches
        if ctx1.branch_index == ctx2.branch_index:
            return False

        # They are in different branches of the same if statement - mutually exclusive
        return True

    def _generate_state_blocks(self, builder: ir.IRBuilder,
                                step_fn: ir.Function,
                                frame_ptr: ir.Value,
                                frame_info: TaskFrameInfo,
                                func: FunctionDecl,
                                analysis: TaskAnalysis,
                                state_blocks: List,
                                task_result_type,
                                out_ptr: ir.Value,
                                resolved_arg: ir.Value):
        """
        Generate code for each state in the state machine.

        Each state executes a segment of the function body:
        - State 0: statements from start until first suspension
        - State N: statements from after suspension N-1 until suspension N (or end)

        For nested suspensions (inside if/else/for/while), the code:
        1. Executes top-level statements up to the control flow statement
        2. Enters the control flow and executes until the suspension
        3. On resume, continues within the control flow and then after it
        """
        cg = self.cg
        suspension_points = analysis.suspension_points

        if not suspension_points:
            # No suspension points - shouldn't happen for state machine
            builder.position_at_end(state_blocks[0])
            self._store_task_result_done(builder, out_ptr, ir.Constant(ir.IntType(64), 0))
            builder.ret_void()
            return

        # State 0: Execute statements before first suspension, then spawn child
        builder.position_at_end(state_blocks[0])

        # Set up context for executing statements with frame-based variables
        self._setup_frame_locals_context(builder, frame_ptr, frame_info, func)

        first_sp = suspension_points[0]

        # Check if suspension is inside control flow
        if first_sp.context is not None and first_sp.context.kind in ("if_then", "if_else"):
            # Generate branching code for if/else
            self._generate_conditional_state_0(
                builder, step_fn, frame_ptr, frame_info, func,
                first_sp, task_result_type, out_ptr
            )
        elif first_sp.context is not None and first_sp.context.kind == "for":
            # Generate for loop handling
            self._generate_for_loop_state_0(
                builder, step_fn, frame_ptr, frame_info, func,
                first_sp, task_result_type, out_ptr, analysis
            )
        else:
            # Regular execution to suspension
            self._execute_to_suspension(
                builder, func.body, first_sp, frame_ptr, frame_info,
                out_ptr, step_fn
            )

            # Update state to 1
            state_ptr = builder.gep(frame_ptr, [
                ir.Constant(ir.IntType(32), 0),
                ir.Constant(ir.IntType(32), frame_info.field_indices['__state'])
            ], inbounds=True)
            builder.store(ir.Constant(ir.IntType(64), 1), state_ptr)

            # Create child frame and spawn
            child_frame, child_step_fn = self._create_child_task_spawn(
                builder, frame_ptr, frame_info, first_sp
            )
            self._store_task_result_spawn(builder, out_ptr, child_frame, child_step_fn)
            builder.ret_void()

        # Generate remaining states
        for i, sp in enumerate(suspension_points):
            state_idx = i + 1
            builder.position_at_end(state_blocks[state_idx])

            # Re-setup context for this state
            self._setup_frame_locals_context(builder, frame_ptr, frame_info, func)

            # Check if this suspension is inside a for loop - needs special handling
            if sp.context is not None and sp.context.kind == "for":
                # For loop suspension - use special resume handler
                self._generate_for_loop_resume_state(
                    builder, step_fn, frame_ptr, frame_info, func,
                    sp, task_result_type, out_ptr, resolved_arg
                )
                continue

            # Store resolved value to __resolved field for use in expression evaluation
            resolved_val = resolved_arg
            resolved_ptr = builder.gep(frame_ptr, [
                ir.Constant(ir.IntType(32), 0),
                ir.Constant(ir.IntType(32), frame_info.field_indices['__resolved'])
            ], inbounds=True)
            builder.store(resolved_val, resolved_ptr)

            # Also store resolved value to target variable if applicable
            if sp.var_name and sp.var_name in frame_info.field_indices:
                var_ptr = builder.gep(frame_ptr, [
                    ir.Constant(ir.IntType(32), 0),
                    ir.Constant(ir.IntType(32), frame_info.field_indices[sp.var_name])
                ], inbounds=True)
                builder.store(resolved_val, var_ptr)

            if state_idx < len(suspension_points):
                # More suspensions - but check if they're mutually exclusive
                next_sp = suspension_points[state_idx]

                # Check if current suspension is a return statement
                # If so, the result should be returned immediately, not continue to next
                if sp.var_name == "__return_value":
                    # This is a return statement suspension - just return the resolved value
                    self._store_task_result_done(builder, out_ptr, resolved_val)
                    builder.ret_void()
                elif self._are_suspensions_mutually_exclusive(sp, next_sp):
                    # Current and next suspensions are in different branches of the same if/else
                    # We completed one branch, so skip the other and return the result
                    return_val = self._execute_from_suspension_to_end(
                        builder, func.body, sp, frame_ptr, frame_info
                    )
                    self._store_task_result_done(builder, out_ptr, return_val)
                    builder.ret_void()
                else:
                    # Execute from after current suspension to next suspension
                    self._execute_from_suspension_to_next(
                        builder, func.body, sp, next_sp, frame_ptr, frame_info
                    )

                    # Update state and spawn next child
                    next_state = state_idx + 1
                    state_ptr = builder.gep(frame_ptr, [
                        ir.Constant(ir.IntType(32), 0),
                        ir.Constant(ir.IntType(32), frame_info.field_indices['__state'])
                    ], inbounds=True)
                    builder.store(ir.Constant(ir.IntType(64), next_state), state_ptr)

                    child_frame, child_step_fn = self._create_child_task_spawn(
                        builder, frame_ptr, frame_info, next_sp
                    )
                    self._store_task_result_spawn(builder, out_ptr, child_frame, child_step_fn)
                    builder.ret_void()
            else:
                # Last state - execute remaining statements and return
                # Check if this is a bare expression at the end that should be the implicit return
                from ast_nodes import ExprStmt, ReturnStmt
                is_bare_expr = sp.var_name is None and isinstance(sp.node, ExprStmt)

                # Check if there are any statements after this suspension that could affect return
                remaining_stmts = func.body[sp.stmt_index + 1:]
                has_return_after = any(isinstance(s, ReturnStmt) for s in remaining_stmts)

                if is_bare_expr and not has_return_after and len(remaining_stmts) == 0:
                    # Bare task call expression at end of function - use resolved value as return
                    self._store_task_result_done(builder, out_ptr, resolved_val)
                    builder.ret_void()
                else:
                    return_val = self._execute_from_suspension_to_end(
                        builder, func.body, sp, frame_ptr, frame_info
                    )

                    self._store_task_result_done(builder, out_ptr, return_val)
                    builder.ret_void()

    def _generate_conditional_state_0(self, builder: ir.IRBuilder,
                                        step_fn: ir.Function,
                                        frame_ptr: ir.Value,
                                        frame_info: TaskFrameInfo,
                                        func: FunctionDecl,
                                        first_sp: SuspensionPoint,
                                        task_result_type,
                                        out_ptr: ir.Value):
        """
        Generate conditional state 0 for suspensions inside if/else.

        This evaluates the condition and branches:
        - If condition matches suspension branch: execute up to suspension, SPAWN
        - If condition doesn't match: execute other branch, continue after if, DONE
        """
        from ast_nodes import IfStmt, ReturnStmt

        cg = self.cg
        ctx = first_sp.context
        parent_idx = ctx.parent_stmt_index

        # Execute statements before the if
        self._execute_statements_until(
            builder, func.body, 0, parent_idx, frame_ptr, frame_info
        )

        # Get the if statement
        if_stmt = func.body[parent_idx]
        if not isinstance(if_stmt, IfStmt):
            # Fallback to regular path
            self._execute_statements_until(
                builder, func.body, parent_idx, parent_idx + 1, frame_ptr, frame_info
            )
            return

        # Evaluate the condition
        cond_val = cg._generate_expression(if_stmt.condition)

        # Convert to i1 if needed
        if cond_val.type != ir.IntType(1):
            if isinstance(cond_val.type, ir.IntType):
                cond_val = builder.icmp_signed('!=', cond_val,
                                                ir.Constant(cond_val.type, 0), name="cond")
            else:
                cond_val = ir.Constant(ir.IntType(1), 1)

        # Create basic blocks for then and else paths
        suspend_block = step_fn.append_basic_block("suspend_path")
        skip_block = step_fn.append_basic_block("skip_path")

        # Branch based on condition and which branch has the suspension
        if ctx.kind == "if_then":
            # Suspension in then branch - if true: suspend, if false: skip
            builder.cbranch(cond_val, suspend_block, skip_block)
        else:  # if_else
            # Suspension in else branch - if true: skip, if false: suspend
            builder.cbranch(cond_val, skip_block, suspend_block)

        # Generate suspend path (condition leads to suspension)
        builder.position_at_end(suspend_block)

        # Store branch_taken
        branch_ptr = builder.gep(frame_ptr, [
            ir.Constant(ir.IntType(32), 0),
            ir.Constant(ir.IntType(32), frame_info.field_indices['__branch_taken'])
        ], inbounds=True)
        branch_val = 1 if ctx.kind == "if_then" else 0
        builder.store(ir.Constant(ir.IntType(64), branch_val), branch_ptr)

        # Execute the suspension branch up to the suspension
        if ctx.kind == "if_then":
            self._execute_statements_until(
                builder, if_stmt.then_body, 0, ctx.nested_stmt_index,
                frame_ptr, frame_info
            )
        else:
            self._execute_statements_until(
                builder, if_stmt.else_body, 0, ctx.nested_stmt_index,
                frame_ptr, frame_info
            )

        # Update state to 1
        state_ptr = builder.gep(frame_ptr, [
            ir.Constant(ir.IntType(32), 0),
            ir.Constant(ir.IntType(32), frame_info.field_indices['__state'])
        ], inbounds=True)
        builder.store(ir.Constant(ir.IntType(64), 1), state_ptr)

        # Create child frame and spawn
        child_frame, child_step_fn = self._create_child_task_spawn(
            builder, frame_ptr, frame_info, first_sp
        )
        self._store_task_result_spawn(builder, out_ptr, child_frame, child_step_fn)
        builder.ret_void()

        # Generate skip path (condition skips suspension, execute other branch)
        builder.position_at_end(skip_block)

        # Execute the other branch using the step function protocol
        if ctx.kind == "if_then":
            # Execute else branch
            if if_stmt.else_body:
                terminated = self._generate_statements_in_step_context(
                    builder, step_fn, if_stmt.else_body, frame_ptr, frame_info, out_ptr
                )
                if terminated:
                    return
        else:
            # Execute then branch (no suspension in then)
            terminated = self._generate_statements_in_step_context(
                builder, step_fn, if_stmt.then_body, frame_ptr, frame_info, out_ptr
            )
            if terminated:
                return

        # Continue after if statement
        start_idx = parent_idx + 1
        return_val = self._execute_statements_and_return(
            builder, func.body, start_idx, len(func.body), frame_ptr, frame_info
        )
        self._store_task_result_done(builder, out_ptr, return_val)
        builder.ret_void()

    def _generate_for_loop_state_0(self, builder: ir.IRBuilder,
                                    step_fn: ir.Function,
                                    frame_ptr: ir.Value,
                                    frame_info: TaskFrameInfo,
                                    func: FunctionDecl,
                                    first_sp: SuspensionPoint,
                                    task_result_type,
                                    out_ptr: ir.Value,
                                    analysis):
        """
        Generate state 0 for a suspension inside a for loop.

        This initializes the loop, checks the condition, and either:
        - Spawns the first iteration's child task
        - Skips the loop if it's empty
        """
        from ast_nodes import ForStmt, RangeExpr

        cg = self.cg
        ctx = first_sp.context
        parent_idx = ctx.parent_stmt_index

        # Execute statements before the for loop
        self._execute_statements_until(
            builder, func.body, 0, parent_idx, frame_ptr, frame_info
        )

        # Get the for statement
        for_stmt = func.body[parent_idx]
        if not isinstance(for_stmt, ForStmt):
            # Fallback
            return

        # Initialize loop state
        # Evaluate the iterable (for now, assuming it's a range)
        if isinstance(for_stmt.iterable, RangeExpr):
            start_val = cg._generate_expression(for_stmt.iterable.start)
            end_val = cg._generate_expression(for_stmt.iterable.end)
        else:
            # Default for other iterables - would need more complex handling
            start_val = ir.Constant(ir.IntType(64), 0)
            end_val = ir.Constant(ir.IntType(64), 0)

        # Store loop state to frame
        loop_idx_ptr = builder.gep(frame_ptr, [
            ir.Constant(ir.IntType(32), 0),
            ir.Constant(ir.IntType(32), frame_info.field_indices['__loop_idx'])
        ], inbounds=True)
        builder.store(start_val, loop_idx_ptr)

        loop_end_ptr = builder.gep(frame_ptr, [
            ir.Constant(ir.IntType(32), 0),
            ir.Constant(ir.IntType(32), frame_info.field_indices['__loop_end'])
        ], inbounds=True)
        builder.store(end_val, loop_end_ptr)

        # Also store the loop variable to frame (so it's accessible)
        loop_var_name = for_stmt.var_name
        if loop_var_name in frame_info.field_indices:
            loop_var_ptr = builder.gep(frame_ptr, [
                ir.Constant(ir.IntType(32), 0),
                ir.Constant(ir.IntType(32), frame_info.field_indices[loop_var_name])
            ], inbounds=True)
            builder.store(start_val, loop_var_ptr)

        # Check if loop should execute (idx < end)
        cond = builder.icmp_signed('<', start_val, end_val, name="loop_cond")

        # Create blocks for loop entry and skip
        loop_entry = step_fn.append_basic_block("loop_entry")
        loop_skip = step_fn.append_basic_block("loop_skip")

        builder.cbranch(cond, loop_entry, loop_skip)

        # Loop entry: execute body up to suspension, spawn child
        builder.position_at_end(loop_entry)

        # Execute loop body statements before the suspension
        self._execute_statements_until(
            builder, for_stmt.body, 0, ctx.nested_stmt_index,
            frame_ptr, frame_info
        )

        # Update state to 1
        state_ptr = builder.gep(frame_ptr, [
            ir.Constant(ir.IntType(32), 0),
            ir.Constant(ir.IntType(32), frame_info.field_indices['__state'])
        ], inbounds=True)
        builder.store(ir.Constant(ir.IntType(64), 1), state_ptr)

        # Create child frame and spawn
        child_frame, child_step_fn = self._create_child_task_spawn(
            builder, frame_ptr, frame_info, first_sp
        )
        self._store_task_result_spawn(builder, out_ptr, child_frame, child_step_fn)
        builder.ret_void()

        # Loop skip: continue after the loop
        builder.position_at_end(loop_skip)

        # Execute statements after the for loop and return
        start_idx = parent_idx + 1
        return_val = self._execute_statements_and_return(
            builder, func.body, start_idx, len(func.body), frame_ptr, frame_info
        )
        self._store_task_result_done(builder, out_ptr, return_val)
        builder.ret_void()

    def _generate_for_loop_resume_state(self, builder: ir.IRBuilder,
                                          step_fn: ir.Function,
                                          frame_ptr: ir.Value,
                                          frame_info: TaskFrameInfo,
                                          func: FunctionDecl,
                                          sp: SuspensionPoint,
                                          task_result_type,
                                          out_ptr: ir.Value,
                                          resolved_arg: ir.Value):
        """
        Generate the resume state for a suspension inside a for loop.

        After each iteration:
        1. Store resolved value to target variable
        2. Execute remaining loop body
        3. Increment loop index
        4. Check if more iterations
        5. If yes: execute loop body up to suspension, spawn, return SPAWN
        6. If no: continue after loop, return DONE
        """
        from ast_nodes import ForStmt

        cg = self.cg
        ctx = sp.context
        parent_idx = ctx.parent_stmt_index
        for_stmt = func.body[parent_idx]

        # Store resolved value to target variable
        if sp.var_name and sp.var_name in frame_info.field_indices:
            var_ptr = builder.gep(frame_ptr, [
                ir.Constant(ir.IntType(32), 0),
                ir.Constant(ir.IntType(32), frame_info.field_indices[sp.var_name])
            ], inbounds=True)
            builder.store(resolved_arg, var_ptr)

        # Execute remaining loop body statements (after the suspension)
        remaining_start = ctx.nested_stmt_index + 1
        self._execute_statements_until(
            builder, for_stmt.body, remaining_start, len(for_stmt.body),
            frame_ptr, frame_info
        )

        # Increment loop index
        loop_idx_ptr = builder.gep(frame_ptr, [
            ir.Constant(ir.IntType(32), 0),
            ir.Constant(ir.IntType(32), frame_info.field_indices['__loop_idx'])
        ], inbounds=True)
        current_idx = builder.load(loop_idx_ptr, name="loop_idx")
        next_idx = builder.add(current_idx, ir.Constant(ir.IntType(64), 1), name="next_idx")
        builder.store(next_idx, loop_idx_ptr)

        # Also update the loop variable in frame
        loop_var_name = for_stmt.var_name
        if loop_var_name in frame_info.field_indices:
            loop_var_ptr = builder.gep(frame_ptr, [
                ir.Constant(ir.IntType(32), 0),
                ir.Constant(ir.IntType(32), frame_info.field_indices[loop_var_name])
            ], inbounds=True)
            builder.store(next_idx, loop_var_ptr)

        # Check if more iterations (idx < end)
        loop_end_ptr = builder.gep(frame_ptr, [
            ir.Constant(ir.IntType(32), 0),
            ir.Constant(ir.IntType(32), frame_info.field_indices['__loop_end'])
        ], inbounds=True)
        loop_end = builder.load(loop_end_ptr, name="loop_end")
        more_iterations = builder.icmp_signed('<', next_idx, loop_end, name="more_iter")

        # Create blocks for continue and exit
        loop_continue = step_fn.append_basic_block("loop_continue")
        loop_exit = step_fn.append_basic_block("loop_exit")

        builder.cbranch(more_iterations, loop_continue, loop_exit)

        # Loop continue: execute body up to suspension, spawn next
        builder.position_at_end(loop_continue)

        # Execute loop body statements before the suspension
        self._execute_statements_until(
            builder, for_stmt.body, 0, ctx.nested_stmt_index,
            frame_ptr, frame_info
        )

        # Create child frame and spawn (state stays at current)
        child_frame, child_step_fn = self._create_child_task_spawn(
            builder, frame_ptr, frame_info, sp
        )
        self._store_task_result_spawn(builder, out_ptr, child_frame, child_step_fn)
        builder.ret_void()

        # Loop exit: continue after the loop
        builder.position_at_end(loop_exit)

        # Execute statements after the for loop and return
        start_idx = parent_idx + 1
        return_val = self._execute_statements_and_return(
            builder, func.body, start_idx, len(func.body), frame_ptr, frame_info
        )
        self._store_task_result_done(builder, out_ptr, return_val)
        builder.ret_void()

    def _execute_to_suspension(self, builder: ir.IRBuilder, body: list,
                                sp: SuspensionPoint, frame_ptr: ir.Value,
                                frame_info: TaskFrameInfo,
                                out_ptr: ir.Value = None, step_fn: ir.Function = None):
        """
        Execute statements from the beginning of body until the suspension point.

        For nested suspensions, this enters the control flow structure.
        """
        if sp.context is None:
            # Top-level suspension - just execute statements until it
            self._execute_statements_until(
                builder, body, 0, sp.stmt_index, frame_ptr, frame_info,
                out_ptr, step_fn
            )
        else:
            # Nested suspension - execute up to parent, then enter parent
            parent_idx = sp.context.parent_stmt_index
            self._execute_statements_until(
                builder, body, 0, parent_idx, frame_ptr, frame_info,
                out_ptr, step_fn
            )
            # Now execute within the parent control flow up to the suspension
            self._execute_within_control_flow_to_suspension(
                builder, body[parent_idx], sp, frame_ptr, frame_info
            )

    def _execute_within_control_flow_to_suspension(self, builder: ir.IRBuilder,
                                                     parent_stmt, sp: SuspensionPoint,
                                                     frame_ptr: ir.Value,
                                                     frame_info: TaskFrameInfo):
        """
        Execute within a control flow statement up to the suspension point.

        For if/else, this evaluates the condition and executes the appropriate branch.
        """
        from ast_nodes import IfStmt, ForStmt, WhileStmt, MatchStmt

        cg = self.cg
        ctx = sp.context

        if isinstance(parent_stmt, IfStmt):
            # Evaluate condition
            cond_val = cg._generate_expression(parent_stmt.condition)

            # Convert to i1 if needed
            if cond_val.type != ir.IntType(1):
                if isinstance(cond_val.type, ir.IntType):
                    cond_val = builder.icmp_signed('!=', cond_val,
                                                    ir.Constant(cond_val.type, 0), name="cond")
                else:
                    cond_val = ir.Constant(ir.IntType(1), 1)  # Default true

            # Store which branch we're taking in the frame
            branch_ptr = builder.gep(frame_ptr, [
                ir.Constant(ir.IntType(32), 0),
                ir.Constant(ir.IntType(32), frame_info.field_indices['__branch_taken'])
            ], inbounds=True)

            if ctx.kind == "if_then":
                # Suspension is in then branch
                # Store 1 (then) to branch_taken
                builder.store(ir.Constant(ir.IntType(64), 1), branch_ptr)
                # Execute then_body up to the nested suspension index
                self._execute_statements_until(
                    builder, parent_stmt.then_body, 0, ctx.nested_stmt_index,
                    frame_ptr, frame_info
                )
            elif ctx.kind == "if_else":
                # Suspension is in else branch
                # Store 0 (else) to branch_taken
                builder.store(ir.Constant(ir.IntType(64), 0), branch_ptr)
                # Execute else_body up to the nested suspension index
                self._execute_statements_until(
                    builder, parent_stmt.else_body, 0, ctx.nested_stmt_index,
                    frame_ptr, frame_info
                )
            elif ctx.kind == "if_elif":
                # Suspension is in an elif branch
                elif_idx = ctx.branch_index - 2
                if elif_idx >= 0 and elif_idx < len(parent_stmt.else_if_clauses):
                    _, elif_body = parent_stmt.else_if_clauses[elif_idx]
                    # Store branch index
                    builder.store(ir.Constant(ir.IntType(64), ctx.branch_index), branch_ptr)
                    self._execute_statements_until(
                        builder, elif_body, 0, ctx.nested_stmt_index,
                        frame_ptr, frame_info
                    )

        elif isinstance(parent_stmt, ForStmt):
            # For loops with suspensions - execute loop setup
            # Set up the loop variable from the iteration
            self._execute_statements_until(
                builder, parent_stmt.body, 0, ctx.nested_stmt_index,
                frame_ptr, frame_info
            )

        elif isinstance(parent_stmt, WhileStmt):
            # For while loops, evaluate condition first
            cond_val = cg._generate_expression(parent_stmt.condition)
            # Execute body up to suspension
            self._execute_statements_until(
                builder, parent_stmt.body, 0, ctx.nested_stmt_index,
                frame_ptr, frame_info
            )

    def _execute_from_suspension_to_next(self, builder: ir.IRBuilder, body: list,
                                          current_sp: SuspensionPoint,
                                          next_sp: SuspensionPoint,
                                          frame_ptr: ir.Value,
                                          frame_info: TaskFrameInfo):
        """
        Execute from after current suspension to the next suspension point.
        """
        # First, complete any remaining code from the current suspension's context
        if current_sp.context is not None:
            # Finish the current control flow branch
            self._complete_control_flow_branch(
                builder, body, current_sp, frame_ptr, frame_info
            )
            # Continue from after the control flow statement
            current_top_idx = current_sp.context.parent_stmt_index
            start_idx = current_top_idx + 1
        else:
            start_idx = current_sp.stmt_index + 1

        # Now execute to the next suspension
        if next_sp.context is None:
            # Next suspension is at top level
            end_idx = next_sp.stmt_index
            self._execute_statements_until(
                builder, body, start_idx, end_idx, frame_ptr, frame_info
            )
        else:
            # Next suspension is nested
            next_parent_idx = next_sp.context.parent_stmt_index
            # Execute top-level statements up to the parent
            self._execute_statements_until(
                builder, body, start_idx, next_parent_idx, frame_ptr, frame_info
            )
            # Enter the parent and execute to the suspension
            if next_parent_idx < len(body):
                self._execute_within_control_flow_to_suspension(
                    builder, body[next_parent_idx], next_sp, frame_ptr, frame_info
                )

    def _execute_from_suspension_to_end(self, builder: ir.IRBuilder, body: list,
                                          sp: SuspensionPoint,
                                          frame_ptr: ir.Value,
                                          frame_info: TaskFrameInfo) -> ir.Value:
        """
        Execute from after the suspension to the end of the function, returning the result.
        """
        from ast_nodes import ReturnStmt

        # Special handling for return statement suspensions
        # The suspension IS the return statement, so we need to evaluate the return
        # expression with the resolved task call value substituted
        if sp.var_name == "__return_value" and isinstance(sp.node, ReturnStmt):
            # The return expression contains a task call that's now resolved
            # Evaluate the expression using state context (which substitutes task calls)
            if sp.node.value:
                return_val = self._evaluate_expr_in_state_context(
                    builder, sp.node.value, frame_ptr, frame_info
                )
                # Cast to i64
                cg = self.cg
                if return_val.type != ir.IntType(64):
                    if isinstance(return_val.type, ir.IntType):
                        return_val = builder.sext(return_val, ir.IntType(64))
                    elif isinstance(return_val.type, ir.DoubleType):
                        return_val = builder.bitcast(return_val, ir.IntType(64))
                    elif isinstance(return_val.type, ir.PointerType):
                        return_val = builder.ptrtoint(return_val, ir.IntType(64))
                return return_val
            return ir.Constant(ir.IntType(64), 0)

        # First, complete any remaining code from the current suspension's context
        if sp.context is not None:
            # Finish the current control flow branch and get return value if any
            return_val, has_return = self._complete_control_flow_branch_with_return(
                builder, body, sp, frame_ptr, frame_info
            )
            if has_return:
                return return_val
            # Continue from after the control flow statement
            start_idx = sp.context.parent_stmt_index + 1
        else:
            start_idx = sp.stmt_index + 1

        # Execute remaining statements and find return
        return self._execute_statements_and_return(
            builder, body, start_idx, len(body), frame_ptr, frame_info
        )

    def _complete_control_flow_branch(self, builder: ir.IRBuilder, body: list,
                                        sp: SuspensionPoint,
                                        frame_ptr: ir.Value,
                                        frame_info: TaskFrameInfo):
        """
        Complete execution of the remaining statements in the current control flow branch.
        """
        from ast_nodes import IfStmt, ForStmt, WhileStmt

        ctx = sp.context
        if ctx is None:
            return

        parent_idx = ctx.parent_stmt_index
        if parent_idx >= len(body):
            return

        parent_stmt = body[parent_idx]

        if isinstance(parent_stmt, IfStmt):
            if ctx.kind == "if_then":
                # Complete remaining then_body statements after suspension
                remaining_start = ctx.nested_stmt_index + 1
                self._execute_statements_until(
                    builder, parent_stmt.then_body, remaining_start,
                    len(parent_stmt.then_body), frame_ptr, frame_info
                )
            elif ctx.kind == "if_else":
                # Complete remaining else_body statements
                remaining_start = ctx.nested_stmt_index + 1
                self._execute_statements_until(
                    builder, parent_stmt.else_body, remaining_start,
                    len(parent_stmt.else_body), frame_ptr, frame_info
                )
            elif ctx.kind == "if_elif":
                # Complete remaining elif body
                elif_idx = ctx.branch_index - 2
                if elif_idx >= 0 and elif_idx < len(parent_stmt.else_if_clauses):
                    _, elif_body = parent_stmt.else_if_clauses[elif_idx]
                    remaining_start = ctx.nested_stmt_index + 1
                    self._execute_statements_until(
                        builder, elif_body, remaining_start,
                        len(elif_body), frame_ptr, frame_info
                    )

        elif isinstance(parent_stmt, ForStmt):
            # Complete remaining loop body statements
            remaining_start = ctx.nested_stmt_index + 1
            self._execute_statements_until(
                builder, parent_stmt.body, remaining_start,
                len(parent_stmt.body), frame_ptr, frame_info
            )

        elif isinstance(parent_stmt, WhileStmt):
            # Complete remaining loop body statements
            remaining_start = ctx.nested_stmt_index + 1
            self._execute_statements_until(
                builder, parent_stmt.body, remaining_start,
                len(parent_stmt.body), frame_ptr, frame_info
            )

    def _complete_control_flow_branch_with_return(self, builder: ir.IRBuilder, body: list,
                                                    sp: SuspensionPoint,
                                                    frame_ptr: ir.Value,
                                                    frame_info: TaskFrameInfo) -> tuple:
        """
        Complete execution of the remaining statements in the control flow branch,
        capturing any return value.

        Returns (return_value, has_return) tuple.
        """
        from ast_nodes import IfStmt, ForStmt, WhileStmt, ReturnStmt

        cg = self.cg
        ctx = sp.context
        if ctx is None:
            return (ir.Constant(ir.IntType(64), 0), False)

        parent_idx = ctx.parent_stmt_index
        if parent_idx >= len(body):
            return (ir.Constant(ir.IntType(64), 0), False)

        parent_stmt = body[parent_idx]
        remaining_stmts = []

        if isinstance(parent_stmt, IfStmt):
            if ctx.kind == "if_then":
                remaining_start = ctx.nested_stmt_index + 1
                remaining_stmts = parent_stmt.then_body[remaining_start:]
            elif ctx.kind == "if_else":
                remaining_start = ctx.nested_stmt_index + 1
                remaining_stmts = parent_stmt.else_body[remaining_start:]
            elif ctx.kind == "if_elif":
                elif_idx = ctx.branch_index - 2
                if elif_idx >= 0 and elif_idx < len(parent_stmt.else_if_clauses):
                    _, elif_body = parent_stmt.else_if_clauses[elif_idx]
                    remaining_start = ctx.nested_stmt_index + 1
                    remaining_stmts = elif_body[remaining_start:]

        elif isinstance(parent_stmt, ForStmt):
            remaining_start = ctx.nested_stmt_index + 1
            remaining_stmts = parent_stmt.body[remaining_start:]

        elif isinstance(parent_stmt, WhileStmt):
            remaining_start = ctx.nested_stmt_index + 1
            remaining_stmts = parent_stmt.body[remaining_start:]

        # Execute remaining statements and check for return
        for stmt in remaining_stmts:
            if isinstance(stmt, ReturnStmt):
                if stmt.value:
                    return_val = cg._generate_expression(stmt.value)
                    # Cast to i64
                    if return_val.type != ir.IntType(64):
                        if isinstance(return_val.type, ir.IntType):
                            return_val = cg.builder.sext(return_val, ir.IntType(64))
                        elif isinstance(return_val.type, ir.DoubleType):
                            return_val = cg.builder.bitcast(return_val, ir.IntType(64))
                        elif isinstance(return_val.type, ir.PointerType):
                            return_val = cg.builder.ptrtoint(return_val, ir.IntType(64))
                    return (return_val, True)
                else:
                    return (ir.Constant(ir.IntType(64), 0), True)
            else:
                cg._generate_statement(stmt)
                if cg.builder.block.is_terminated:
                    break

        return (ir.Constant(ir.IntType(64), 0), False)

    def _setup_frame_locals_context(self, builder: ir.IRBuilder,
                                      frame_ptr: ir.Value,
                                      frame_info: TaskFrameInfo,
                                      func: FunctionDecl):
        """Set up locals to read/write from frame instead of stack."""
        cg = self.cg
        # Save and clear locals - we'll load from frame as needed
        self._saved_locals = cg.locals.copy() if cg.locals else {}
        self._saved_builder = cg.builder

        cg.builder = builder
        cg.locals = {}

        # Create alloca proxies for frame fields that act as local variables
        # These aren't real allocas - they're GEPs into the frame
        for field_name, field_idx in frame_info.field_indices.items():
            if field_name.startswith('__'):
                continue  # Skip internal fields
            # Create a GEP that points to this field
            field_ptr = builder.gep(frame_ptr, [
                ir.Constant(ir.IntType(32), 0),
                ir.Constant(ir.IntType(32), field_idx)
            ], inbounds=True, name=f"frame_{field_name}")
            cg.locals[field_name] = field_ptr

    def _execute_statements_until(self, builder: ir.IRBuilder,
                                    body: list, start_idx: int, end_idx: int,
                                    frame_ptr: ir.Value, frame_info: TaskFrameInfo,
                                    out_ptr: ir.Value = None, step_fn: ir.Function = None):
        """Execute statements from start_idx to end_idx (exclusive)."""
        cg = self.cg
        from ast_nodes import ReturnStmt, IfStmt

        for i in range(start_idx, min(end_idx, len(body))):
            stmt = body[i]
            if isinstance(stmt, ReturnStmt):
                # Don't execute return here - handled separately
                continue
            if isinstance(stmt, IfStmt) and out_ptr is not None and step_fn is not None:
                # Check if this if statement has an early return in the then branch
                if self._if_has_early_return(stmt):
                    # Generate special handling for early-return if
                    self._generate_early_return_if(
                        builder, step_fn, stmt, frame_ptr, frame_info, out_ptr
                    )
                    continue
            cg._generate_statement(stmt)
            if cg.builder.block.is_terminated:
                break

    def _if_has_early_return(self, if_stmt) -> bool:
        """Check if an if statement has an early return (return without suspension)."""
        from ast_nodes import ReturnStmt
        for stmt in if_stmt.then_body:
            if isinstance(stmt, ReturnStmt):
                return True
        return False

    def _generate_statements_in_step_context(self, builder: ir.IRBuilder,
                                               step_fn: ir.Function,
                                               stmts: list,
                                               frame_ptr: ir.Value,
                                               frame_info: TaskFrameInfo,
                                               out_ptr: ir.Value) -> bool:
        """
        Generate statements in step function context, handling returns properly.

        Returns True if the block was terminated (return executed), False otherwise.
        """
        from ast_nodes import ReturnStmt, IfStmt

        cg = self.cg

        for stmt in stmts:
            if isinstance(stmt, ReturnStmt):
                # Handle return - use step function protocol
                if stmt.value:
                    return_val = cg._generate_expression(stmt.value)
                    if return_val.type != ir.IntType(64):
                        if isinstance(return_val.type, ir.IntType):
                            return_val = builder.sext(return_val, ir.IntType(64))
                        elif isinstance(return_val.type, ir.PointerType):
                            return_val = builder.ptrtoint(return_val, ir.IntType(64))
                else:
                    return_val = ir.Constant(ir.IntType(64), 0)
                self._store_task_result_done(builder, out_ptr, return_val)
                builder.ret_void()
                return True
            elif isinstance(stmt, IfStmt):
                # Handle nested if/else with step function return protocol
                terminated = self._generate_if_in_step_context(
                    builder, step_fn, stmt, frame_ptr, frame_info, out_ptr
                )
                if terminated:
                    return True
            else:
                # Regular statement
                cg._generate_statement(stmt)
                if cg.builder.block.is_terminated:
                    return True

        return False

    def _generate_if_in_step_context(self, builder: ir.IRBuilder,
                                       step_fn: ir.Function,
                                       if_stmt,
                                       frame_ptr: ir.Value,
                                       frame_info: TaskFrameInfo,
                                       out_ptr: ir.Value) -> bool:
        """
        Generate an if/else statement in step function context.

        Handles returns using the step function protocol (ret void with out_result).
        Returns True if all branches return (block terminated).
        """
        from ast_nodes import IfStmt

        cg = self.cg

        # Evaluate condition
        cond_val = cg._generate_expression(if_stmt.condition)

        # Convert to i1 if needed
        if cond_val.type != ir.IntType(1):
            if isinstance(cond_val.type, ir.IntType):
                cond_val = builder.icmp_signed('!=', cond_val,
                                                ir.Constant(cond_val.type, 0), name="cond")
            else:
                cond_val = ir.Constant(ir.IntType(1), 1)

        # Create blocks
        then_block = step_fn.append_basic_block("if_then")
        else_block = step_fn.append_basic_block("if_else") if if_stmt.else_body else None
        merge_block = step_fn.append_basic_block("if_merge")

        # Branch
        if else_block:
            builder.cbranch(cond_val, then_block, else_block)
        else:
            builder.cbranch(cond_val, then_block, merge_block)

        # Generate then branch
        builder.position_at_end(then_block)
        cg.builder = builder
        then_terminated = self._generate_statements_in_step_context(
            builder, step_fn, if_stmt.then_body, frame_ptr, frame_info, out_ptr
        )
        if not then_terminated and not builder.block.is_terminated:
            builder.branch(merge_block)

        # Generate else branch
        else_terminated = False
        if else_block:
            builder.position_at_end(else_block)
            cg.builder = builder
            else_terminated = self._generate_statements_in_step_context(
                builder, step_fn, if_stmt.else_body, frame_ptr, frame_info, out_ptr
            )
            if not else_terminated and not builder.block.is_terminated:
                builder.branch(merge_block)

        # Check if all branches are terminated
        all_terminated = then_terminated and (else_terminated if else_block else True)

        # Only position at merge block if not all branches return
        if not all_terminated:
            builder.position_at_end(merge_block)
            cg.builder = builder
        else:
            # All branches return - add unreachable to merge block for IR validity
            builder.position_at_end(merge_block)
            builder.unreachable()
            # Position back at a valid block (though code won't reach here)

        # Return True if all branches are terminated
        return all_terminated

    def _generate_early_return_if(self, builder: ir.IRBuilder,
                                    step_fn: ir.Function,
                                    if_stmt,
                                    frame_ptr: ir.Value,
                                    frame_info: TaskFrameInfo,
                                    out_ptr: ir.Value):
        """
        Generate code for an if statement with an early return.

        This generates:
        - Evaluate condition
        - If true: execute then body, if return found store DONE and ret void
        - If false: continue (fall through to next statement)
        """
        from ast_nodes import ReturnStmt

        cg = self.cg

        # Evaluate condition
        cond_val = cg._generate_expression(if_stmt.condition)

        # Convert to i1 if needed
        if cond_val.type != ir.IntType(1):
            if isinstance(cond_val.type, ir.IntType):
                cond_val = builder.icmp_signed('!=', cond_val,
                                                ir.Constant(cond_val.type, 0), name="cond")
            else:
                cond_val = ir.Constant(ir.IntType(1), 1)

        # Create blocks
        then_block = step_fn.append_basic_block("early_ret_then")
        continue_block = step_fn.append_basic_block("early_ret_cont")

        builder.cbranch(cond_val, then_block, continue_block)

        # Then block: execute body and return if we find a return statement
        builder.position_at_end(then_block)

        for stmt in if_stmt.then_body:
            if isinstance(stmt, ReturnStmt):
                # Generate DONE result and return
                if stmt.value:
                    return_val = self._evaluate_expr_in_state_context(
                        builder, stmt.value, frame_ptr, frame_info
                    )
                    if return_val.type != ir.IntType(64):
                        if isinstance(return_val.type, ir.IntType):
                            return_val = builder.sext(return_val, ir.IntType(64))
                        elif isinstance(return_val.type, ir.PointerType):
                            return_val = builder.ptrtoint(return_val, ir.IntType(64))
                else:
                    return_val = ir.Constant(ir.IntType(64), 0)

                self._store_task_result_done(builder, out_ptr, return_val)
                builder.ret_void()
                break
            else:
                cg._generate_statement(stmt)
                if cg.builder.block.is_terminated:
                    break

        # Make sure then block is terminated
        if not builder.block.is_terminated:
            builder.branch(continue_block)

        # Continue block: fall through to next statement
        builder.position_at_end(continue_block)
        cg.builder = builder

    def _execute_statements_and_return(self, builder: ir.IRBuilder,
                                         body: list, start_idx: int, end_idx: int,
                                         frame_ptr: ir.Value, frame_info: TaskFrameInfo) -> ir.Value:
        """Execute remaining statements and return the return value."""
        cg = self.cg
        from ast_nodes import ReturnStmt

        return_val = ir.Constant(ir.IntType(64), 0)

        for i in range(start_idx, min(end_idx, len(body))):
            stmt = body[i]
            if isinstance(stmt, ReturnStmt):
                # Evaluate return expression using state machine context
                # This ensures task calls use the resolved value from the frame
                if stmt.value:
                    return_val = self._evaluate_expr_in_state_context(
                        builder, stmt.value, frame_ptr, frame_info
                    )
                    # Cast to i64
                    if return_val.type != ir.IntType(64):
                        if isinstance(return_val.type, ir.IntType):
                            return_val = cg.builder.sext(return_val, ir.IntType(64))
                        elif isinstance(return_val.type, ir.DoubleType):
                            return_val = cg.builder.bitcast(return_val, ir.IntType(64))
                        elif isinstance(return_val.type, ir.PointerType):
                            return_val = cg.builder.ptrtoint(return_val, ir.IntType(64))
                break  # Stop at return
            else:
                cg._generate_statement(stmt)
                if cg.builder.block.is_terminated:
                    break

        return return_val

    def _create_child_task_spawn(self, builder: ir.IRBuilder,
                                   parent_frame_ptr: ir.Value,
                                   parent_frame_info: TaskFrameInfo,
                                   sp: SuspensionPoint) -> tuple:
        """
        Create a child task frame for a suspension point.

        Returns (child_frame_ptr as i8*, child_step_fn as i8*).
        """
        cg = self.cg
        callee_name = sp.callee_name

        # Get child task's frame info
        child_frame_info = self.task_frames.get(callee_name)
        if child_frame_info is None:
            # Child task might not have a frame yet - this shouldn't happen
            # if tasks are processed in dependency order, but fall back gracefully
            return (ir.Constant(ir.IntType(8).as_pointer(), None),
                    ir.Constant(ir.IntType(8).as_pointer(), None))

        # Get child's step function
        child_step_fn = self.step_functions.get(callee_name)
        if child_step_fn is None:
            return (ir.Constant(ir.IntType(8).as_pointer(), None),
                    ir.Constant(ir.IntType(8).as_pointer(), None))

        # Allocate child frame on heap - calculate actual size from frame type
        num_fields = len(child_frame_info.llvm_frame_type.elements)
        frame_size = ir.Constant(ir.IntType(64), num_fields * 8)
        malloc_fn = self._get_or_declare_malloc()
        child_frame_mem = builder.call(malloc_fn, [frame_size], name="child_frame_mem")
        child_frame_ptr = builder.bitcast(
            child_frame_mem,
            child_frame_info.llvm_frame_type.as_pointer(),
            name="child_frame"
        )

        # Initialize child frame state to 0
        state_ptr = builder.gep(child_frame_ptr, [
            ir.Constant(ir.IntType(32), 0),
            ir.Constant(ir.IntType(32), child_frame_info.field_indices['__state'])
        ], inbounds=True)
        builder.store(ir.Constant(ir.IntType(64), 0), state_ptr)

        # Initialize child frame resolved to 0
        resolved_ptr = builder.gep(child_frame_ptr, [
            ir.Constant(ir.IntType(32), 0),
            ir.Constant(ir.IntType(32), child_frame_info.field_indices['__resolved'])
        ], inbounds=True)
        builder.store(ir.Constant(ir.IntType(64), 0), resolved_ptr)

        # Set waiter to parent frame (so child can wake parent when done)
        waiter_ptr = builder.gep(child_frame_ptr, [
            ir.Constant(ir.IntType(32), 0),
            ir.Constant(ir.IntType(32), child_frame_info.field_indices['__waiter'])
        ], inbounds=True)
        parent_as_i8 = builder.bitcast(parent_frame_ptr, ir.IntType(8).as_pointer())
        builder.store(parent_as_i8, waiter_ptr)

        # Initialize child's branch_taken to 0
        branch_ptr = builder.gep(child_frame_ptr, [
            ir.Constant(ir.IntType(32), 0),
            ir.Constant(ir.IntType(32), child_frame_info.field_indices['__branch_taken'])
        ], inbounds=True)
        builder.store(ir.Constant(ir.IntType(64), 0), branch_ptr)

        # Evaluate arguments and store in child frame
        call_expr = sp.call_expr
        if hasattr(call_expr, 'args') and call_expr.args:
            self._evaluate_and_store_args(
                builder, parent_frame_ptr, parent_frame_info,
                child_frame_ptr, child_frame_info,
                call_expr.args
            )

        # Return child frame and step function as i8*
        child_frame_i8 = builder.bitcast(child_frame_ptr, ir.IntType(8).as_pointer())
        child_step_i8 = builder.bitcast(child_step_fn, ir.IntType(8).as_pointer())

        return (child_frame_i8, child_step_i8)

    def _evaluate_and_store_args(self, builder: ir.IRBuilder,
                                   parent_frame_ptr: ir.Value,
                                   parent_frame_info: TaskFrameInfo,
                                   child_frame_ptr: ir.Value,
                                   child_frame_info: TaskFrameInfo,
                                   args: list):
        """
        Evaluate call arguments in state machine context and store in child frame.
        """
        cg = self.cg

        for i, (arg_expr, param) in enumerate(zip(args, child_frame_info.parameters)):
            # Evaluate the argument expression
            arg_val = self._evaluate_expr_in_state_context(
                builder, arg_expr, parent_frame_ptr, parent_frame_info
            )

            # Get the parameter's field index in child frame
            param_idx = child_frame_info.field_indices.get(param.name)
            if param_idx is None:
                continue

            # Get expected type and cast if needed
            expected_type = child_frame_info.llvm_frame_type.elements[param_idx]
            arg_val = cg._cast_value(arg_val, expected_type)

            # Store in child frame
            param_ptr = builder.gep(child_frame_ptr, [
                ir.Constant(ir.IntType(32), 0),
                ir.Constant(ir.IntType(32), param_idx)
            ], inbounds=True)
            builder.store(arg_val, param_ptr)

    def _evaluate_expr_in_state_context(self, builder: ir.IRBuilder,
                                          expr,
                                          frame_ptr: ir.Value,
                                          frame_info: TaskFrameInfo) -> ir.Value:
        """
        Evaluate an expression in the state machine context.

        Variables are loaded from the frame instead of normal locals.
        """
        from ast_nodes import (
            IntLiteral, FloatLiteral, StringLiteral, BoolLiteral,
            Identifier, BinaryExpr, UnaryExpr, CallExpr, MethodCallExpr,
            TernaryExpr, ListExpr, TupleExpr, IndexExpr, MemberExpr,
            BinaryOp
        )

        cg = self.cg

        if isinstance(expr, IntLiteral):
            return ir.Constant(ir.IntType(64), expr.value)

        elif isinstance(expr, FloatLiteral):
            return ir.Constant(ir.DoubleType(), expr.value)

        elif isinstance(expr, BoolLiteral):
            return ir.Constant(ir.IntType(1), 1 if expr.value else 0)

        elif isinstance(expr, StringLiteral):
            # Use the code generator's string handling
            return cg._generate_string_literal(expr.value)

        elif isinstance(expr, Identifier):
            # Load variable from frame if it's there
            var_name = expr.name
            if var_name in frame_info.field_indices:
                var_idx = frame_info.field_indices[var_name]
                var_ptr = builder.gep(frame_ptr, [
                    ir.Constant(ir.IntType(32), 0),
                    ir.Constant(ir.IntType(32), var_idx)
                ], inbounds=True)
                return builder.load(var_ptr, name=var_name)
            else:
                # Try normal codegen (for globals, functions, etc.)
                saved_builder = cg.builder
                cg.builder = builder
                try:
                    result = cg._generate_expression(expr)
                finally:
                    cg.builder = saved_builder
                return result

        elif isinstance(expr, BinaryExpr):
            left = self._evaluate_expr_in_state_context(builder, expr.left, frame_ptr, frame_info)
            right = self._evaluate_expr_in_state_context(builder, expr.right, frame_ptr, frame_info)

            # Handle binary operators (op is a BinaryOp enum)
            op = expr.op
            if op == BinaryOp.ADD:
                if isinstance(left.type, ir.IntType):
                    return builder.add(left, right, name="add")
                else:
                    return builder.fadd(left, right, name="fadd")
            elif op == BinaryOp.SUB:
                if isinstance(left.type, ir.IntType):
                    return builder.sub(left, right, name="sub")
                else:
                    return builder.fsub(left, right, name="fsub")
            elif op == BinaryOp.MUL:
                if isinstance(left.type, ir.IntType):
                    return builder.mul(left, right, name="mul")
                else:
                    return builder.fmul(left, right, name="fmul")
            elif op == BinaryOp.DIV:
                if isinstance(left.type, ir.IntType):
                    return builder.sdiv(left, right, name="div")
                else:
                    return builder.fdiv(left, right, name="fdiv")
            elif op == BinaryOp.MOD:
                return builder.srem(left, right, name="mod")
            elif op in (BinaryOp.LT, BinaryOp.GT, BinaryOp.LE, BinaryOp.GE, BinaryOp.EQ, BinaryOp.NE):
                if isinstance(left.type, ir.IntType):
                    cmp_map = {
                        BinaryOp.LT: 'slt', BinaryOp.GT: 'sgt',
                        BinaryOp.LE: 'sle', BinaryOp.GE: 'sge',
                        BinaryOp.EQ: 'eq', BinaryOp.NE: 'ne'
                    }
                    cmp = builder.icmp_signed(cmp_map[op], left, right, name="cmp")
                else:
                    cmp_map = {
                        BinaryOp.LT: 'olt', BinaryOp.GT: 'ogt',
                        BinaryOp.LE: 'ole', BinaryOp.GE: 'oge',
                        BinaryOp.EQ: 'oeq', BinaryOp.NE: 'one'
                    }
                    cmp = builder.fcmp_ordered(cmp_map[op], left, right, name="cmp")
                return builder.zext(cmp, ir.IntType(64))
            elif op == BinaryOp.AND:
                left_bool = builder.icmp_signed('!=', left, ir.Constant(left.type, 0))
                right_bool = builder.icmp_signed('!=', right, ir.Constant(right.type, 0))
                result = builder.and_(left_bool, right_bool)
                return builder.zext(result, ir.IntType(64))
            elif op == BinaryOp.OR:
                left_bool = builder.icmp_signed('!=', left, ir.Constant(left.type, 0))
                right_bool = builder.icmp_signed('!=', right, ir.Constant(right.type, 0))
                result = builder.or_(left_bool, right_bool)
                return builder.zext(result, ir.IntType(64))
            else:
                return ir.Constant(ir.IntType(64), 0)

        elif isinstance(expr, UnaryExpr):
            operand = self._evaluate_expr_in_state_context(builder, expr.operand, frame_ptr, frame_info)
            op = expr.op
            if op == '-':
                if isinstance(operand.type, ir.IntType):
                    return builder.neg(operand, name="neg")
                else:
                    return builder.fneg(operand, name="fneg")
            elif op == 'not':
                cmp = builder.icmp_signed('==', operand, ir.Constant(operand.type, 0))
                return builder.zext(cmp, ir.IntType(64))
            else:
                return operand

        elif isinstance(expr, CallExpr):
            # Check if this is a task call that we've already resolved
            callee_name = None
            if isinstance(expr.callee, Identifier):
                callee_name = expr.callee.name

            if callee_name and callee_name in self._task_function_names:
                # This is a task call - use the resolved value from frame
                # The __resolved field contains the result from the child task
                if '__resolved' in frame_info.field_indices:
                    resolved_ptr = builder.gep(frame_ptr, [
                        ir.Constant(ir.IntType(32), 0),
                        ir.Constant(ir.IntType(32), frame_info.field_indices['__resolved'])
                    ], inbounds=True)
                    return builder.load(resolved_ptr, name="resolved_task_result")

            # Non-task call within state machine - use normal codegen
            saved_builder = cg.builder
            cg.builder = builder
            try:
                result = cg._generate_expression(expr)
            finally:
                cg.builder = saved_builder
            return result

        else:
            # For complex expressions, fall back to normal codegen
            saved_builder = cg.builder
            cg.builder = builder
            try:
                result = cg._generate_expression(expr)
            finally:
                cg.builder = saved_builder
            return result

    def _evaluate_final_return(self, builder: ir.IRBuilder,
                                 frame_ptr: ir.Value,
                                 frame_info: TaskFrameInfo,
                                 func: FunctionDecl,
                                 resolved_val: ir.Value) -> ir.Value:
        """
        Evaluate the final return expression in the state machine.

        Finds the return statement in the function body and evaluates its
        expression with variables loaded from the frame.
        """
        from ast_nodes import ReturnStmt

        # Find the return statement in the function body
        return_stmt = None
        for stmt in func.body:
            if isinstance(stmt, ReturnStmt):
                return_stmt = stmt
                break

        if return_stmt is None or return_stmt.value is None:
            # No return statement found or void return - use resolved value
            return resolved_val

        # Evaluate the return expression in state context
        return_val = self._evaluate_expr_in_state_context(
            builder, return_stmt.value, frame_ptr, frame_info
        )

        # Cast to i64 if needed
        if return_val.type != ir.IntType(64):
            if isinstance(return_val.type, ir.IntType):
                return_val = builder.sext(return_val, ir.IntType(64))
            elif isinstance(return_val.type, ir.DoubleType):
                return_val = builder.bitcast(return_val, ir.IntType(64))
            elif isinstance(return_val.type, ir.PointerType):
                return_val = builder.ptrtoint(return_val, ir.IntType(64))

        return return_val

    def _generate_entry_function(self, func: FunctionDecl,
                                   frame_info: TaskFrameInfo,
                                   step_fn: ir.Function) -> ir.Function:
        """
        Generate the entry function that callers use to spawn a task.

        This function:
        1. Allocates a frame on the heap
        2. Initializes frame with parameters
        3. Calls scheduler to spawn and wait for result
        4. Returns the result
        """
        cg = self.cg

        # Get return type
        if func.return_type:
            ret_type = cg._get_llvm_type(func.return_type)
        else:
            ret_type = ir.IntType(64)

        # Get parameter types
        param_types = []
        for param in func.params:
            param_types.append(cg._get_llvm_type(param.type_annotation))

        # Create function type
        fn_type = ir.FunctionType(ret_type, param_types)

        # Reuse existing function declaration if it exists (from declare_function)
        if func.name in cg.functions:
            entry_fn = cg.functions[func.name]
        else:
            entry_fn = ir.Function(cg.module, fn_type, name=func.name)
            cg.functions[func.name] = entry_fn

        # Name parameters
        for i, param in enumerate(func.params):
            entry_fn.args[i].name = param.name

        # Create entry block
        entry = entry_fn.append_basic_block("entry")
        builder = ir.IRBuilder(entry)

        # Ensure scheduler is initialized
        self.ensure_scheduler_init(builder)

        # Allocate frame on heap (using malloc for now)
        # In the future, this should use GC allocation
        num_fields = len(frame_info.llvm_frame_type.elements)
        frame_size = ir.Constant(ir.IntType(64), num_fields * 8)
        malloc_fn = self._get_or_declare_malloc()
        frame_mem = builder.call(malloc_fn, [frame_size], name="frame_mem")
        frame_ptr = builder.bitcast(frame_mem, frame_info.llvm_frame_type.as_pointer(), name="frame")

        # Initialize state to 0
        state_ptr = builder.gep(frame_ptr, [
            ir.Constant(ir.IntType(32), 0),
            ir.Constant(ir.IntType(32), frame_info.field_indices['__state'])
        ], inbounds=True)
        builder.store(ir.Constant(ir.IntType(64), 0), state_ptr)

        # Initialize resolved to 0
        resolved_ptr = builder.gep(frame_ptr, [
            ir.Constant(ir.IntType(32), 0),
            ir.Constant(ir.IntType(32), frame_info.field_indices['__resolved'])
        ], inbounds=True)
        builder.store(ir.Constant(ir.IntType(64), 0), resolved_ptr)

        # Initialize waiter to null
        waiter_ptr = builder.gep(frame_ptr, [
            ir.Constant(ir.IntType(32), 0),
            ir.Constant(ir.IntType(32), frame_info.field_indices['__waiter'])
        ], inbounds=True)
        builder.store(ir.Constant(ir.IntType(8).as_pointer(), None), waiter_ptr)

        # Initialize branch_taken to 0
        branch_ptr = builder.gep(frame_ptr, [
            ir.Constant(ir.IntType(32), 0),
            ir.Constant(ir.IntType(32), frame_info.field_indices['__branch_taken'])
        ], inbounds=True)
        builder.store(ir.Constant(ir.IntType(64), 0), branch_ptr)

        # Copy parameters to frame
        for i, param in enumerate(func.params):
            param_idx = frame_info.field_indices[param.name]
            param_ptr = builder.gep(frame_ptr, [
                ir.Constant(ir.IntType(32), 0),
                ir.Constant(ir.IntType(32), param_idx)
            ], inbounds=True)
            builder.store(entry_fn.args[i], param_ptr)

        # Call scheduler to spawn and wait
        frame_i8 = builder.bitcast(frame_ptr, ir.IntType(8).as_pointer())
        step_i8 = builder.bitcast(step_fn, ir.IntType(8).as_pointer())
        result = builder.call(self._scheduler_spawn_and_wait_fn, [frame_i8, step_i8], name="result")

        # Cast result to return type if needed
        if isinstance(ret_type, ir.IntType) and ret_type.width != 64:
            result = builder.trunc(result, ret_type)
        elif isinstance(ret_type, ir.PointerType):
            result = builder.inttoptr(result, ret_type)
        elif isinstance(ret_type, ir.DoubleType):
            result = builder.bitcast(result, ret_type)

        # Free frame (in the future, GC will handle this)
        free_fn = self._get_or_declare_free()
        builder.call(free_fn, [frame_mem])

        builder.ret(result)

        return entry_fn

    def _get_or_declare_malloc(self) -> ir.Function:
        """Get or declare malloc function."""
        cg = self.cg
        if "malloc" in cg.functions:
            return cg.functions["malloc"]
        # Check if malloc is already in module
        for fn in cg.module.functions:
            if fn.name == "malloc":
                cg.functions["malloc"] = fn
                return fn
        fn_type = ir.FunctionType(ir.IntType(8).as_pointer(), [ir.IntType(64)])
        fn = ir.Function(cg.module, fn_type, name="malloc")
        cg.functions["malloc"] = fn
        return fn

    def _get_or_declare_free(self) -> ir.Function:
        """Get or declare free function."""
        cg = self.cg
        if "free" in cg.functions:
            return cg.functions["free"]
        # Check if free is already in module
        for fn in cg.module.functions:
            if fn.name == "free":
                cg.functions["free"] = fn
                return fn
        fn_type = ir.FunctionType(ir.VoidType(), [ir.IntType(8).as_pointer()])
        fn = ir.Function(cg.module, fn_type, name="free")
        cg.functions["free"] = fn
        return fn

    # ========================================================================
    # Task Call Generation (Called from expressions.py)
    # ========================================================================

    def generate_task_call(self, task_name: str, args: List[ir.Value],
                           builder: ir.IRBuilder) -> ir.Value:
        """
        Generate a call to a task function.

        This just calls the entry function, which handles scheduler interaction.
        """
        cg = self.cg

        # Ensure scheduler is initialized
        self.ensure_scheduler_init(builder)

        # Get the task function
        if task_name in cg.functions:
            task_fn = cg.functions[task_name]

            # Cast arguments if needed
            cast_args = []
            for i, arg in enumerate(args):
                if i < len(task_fn.args):
                    expected_type = task_fn.args[i].type
                    cast_args.append(cg._cast_value(arg, expected_type))
                else:
                    cast_args.append(arg)

            # Call the task
            return builder.call(task_fn, cast_args)
        else:
            # Task not found, return default
            return ir.Constant(ir.IntType(64), 0)

    # ========================================================================
    # Check if function is a task
    # ========================================================================

    def is_task_function(self, name: str) -> bool:
        """Check if a function name refers to a task."""
        return name in self._task_function_names

    # ========================================================================
    # Batch Task Spawning for first/most
    # ========================================================================

    def get_task_step_function(self, task_name: str) -> Optional[ir.Function]:
        """Get the step function for a task, if it has one."""
        return self.step_functions.get(task_name)

    def get_task_frame_info(self, task_name: str) -> Optional[TaskFrameInfo]:
        """Get frame info for a task, if it has one."""
        return self.task_frames.get(task_name)

    def allocate_task_frame(self, task_name: str, arg_values: List[ir.Value],
                            builder: ir.IRBuilder) -> Optional[ir.Value]:
        """
        Allocate and initialize a task frame for batch spawning.

        Returns the frame pointer (as i8*), or None if the task doesn't have a frame.
        This is used by first/most to spawn tasks without immediately waiting.
        """
        cg = self.cg

        # Get frame info
        frame_info = self.task_frames.get(task_name)
        if frame_info is None:
            return None

        # Allocate frame on heap - calculate actual size from frame type
        # Each field is 8 bytes (i64 or pointer)
        num_fields = len(frame_info.llvm_frame_type.elements)
        frame_size = ir.Constant(ir.IntType(64), num_fields * 8)
        malloc_fn = self._get_or_declare_malloc()
        frame_mem = builder.call(malloc_fn, [frame_size], name="frame_mem")
        frame_ptr = builder.bitcast(frame_mem, frame_info.llvm_frame_type.as_pointer(), name="frame")

        # Initialize state to 0
        state_ptr = builder.gep(frame_ptr, [
            ir.Constant(ir.IntType(32), 0),
            ir.Constant(ir.IntType(32), frame_info.field_indices['__state'])
        ], inbounds=True)
        builder.store(ir.Constant(ir.IntType(64), 0), state_ptr)

        # Initialize resolved to 0
        resolved_ptr = builder.gep(frame_ptr, [
            ir.Constant(ir.IntType(32), 0),
            ir.Constant(ir.IntType(32), frame_info.field_indices['__resolved'])
        ], inbounds=True)
        builder.store(ir.Constant(ir.IntType(64), 0), resolved_ptr)

        # Initialize waiter to null
        waiter_ptr = builder.gep(frame_ptr, [
            ir.Constant(ir.IntType(32), 0),
            ir.Constant(ir.IntType(32), frame_info.field_indices['__waiter'])
        ], inbounds=True)
        builder.store(ir.Constant(ir.IntType(8).as_pointer(), None), waiter_ptr)

        # Initialize branch_taken to 0
        branch_ptr = builder.gep(frame_ptr, [
            ir.Constant(ir.IntType(32), 0),
            ir.Constant(ir.IntType(32), frame_info.field_indices['__branch_taken'])
        ], inbounds=True)
        builder.store(ir.Constant(ir.IntType(64), 0), branch_ptr)

        # Copy parameters to frame
        for i, param in enumerate(frame_info.parameters):
            if i < len(arg_values):
                param_idx = frame_info.field_indices[param.name]
                param_ptr = builder.gep(frame_ptr, [
                    ir.Constant(ir.IntType(32), 0),
                    ir.Constant(ir.IntType(32), param_idx)
                ], inbounds=True)

                # Cast argument if needed
                arg_val = arg_values[i]
                expected_type = frame_info.llvm_frame_type.elements[param_idx]
                arg_val = cg._cast_value(arg_val, expected_type)
                builder.store(arg_val, param_ptr)

        # Return frame as i8*
        return builder.bitcast(frame_ptr, ir.IntType(8).as_pointer())

    def has_state_machine(self, task_name: str) -> bool:
        """Check if a task has a state machine (step function)."""
        return task_name in self.step_functions


def create_task_transformer(cg: 'CodeGenerator') -> TaskTransformer:
    """Factory function to create a TaskTransformer."""
    return TaskTransformer(cg)
