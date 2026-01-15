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
from task_analysis import analyze_task, TaskAnalysis, SuspensionPoint

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

    def register_task_function(self, name: str):
        """Register a function name as a task function."""
        self._task_function_names.add(name)

    def get_task_function_names(self) -> Set[str]:
        """Get set of all registered task function names."""
        return self._task_function_names

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
        - Takes a frame pointer and returns TaskResult
        - Switches on frame->state to execute current state
        - Returns TASK_RESULT_DONE(value) or TASK_RESULT_SPAWN(child_frame, child_step)
        """
        cg = self.cg

        # TaskResult struct: { i32 kind, i64 value, i8* child_frame, i8* child_step }
        task_result_type = ir.LiteralStructType([
            ir.IntType(32),  # kind
            ir.IntType(64),  # value (for DONE)
            ir.IntType(8).as_pointer(),  # child_frame (for SPAWN)
            ir.IntType(8).as_pointer(),  # child_step (for SPAWN)
        ])

        # Step function type: TaskResult step(Frame*)
        step_fn_type = ir.FunctionType(
            task_result_type,
            [frame_info.llvm_frame_type.as_pointer()]
        )

        step_fn_name = f"__{func.name}_step"
        step_fn = ir.Function(cg.module, step_fn_type, name=step_fn_name)
        step_fn.args[0].name = "frame"

        # Create entry block
        entry = step_fn.append_basic_block("entry")
        builder = ir.IRBuilder(entry)

        frame_ptr = step_fn.args[0]

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

        # Generate code for each state
        self._generate_state_blocks(
            builder, step_fn, frame_ptr, frame_info, func,
            analysis, state_blocks, task_result_type
        )

        # Default block: return DONE(0) - should never reach here
        builder.position_at_end(default_block)
        result = ir.Constant(task_result_type, [
            ir.Constant(ir.IntType(32), TASK_RESULT_DONE),
            ir.Constant(ir.IntType(64), 0),
            ir.Constant(ir.IntType(8).as_pointer(), None),
            ir.Constant(ir.IntType(8).as_pointer(), None),
        ])
        builder.ret(result)

        return step_fn

    def _generate_state_blocks(self, builder: ir.IRBuilder,
                                step_fn: ir.Function,
                                frame_ptr: ir.Value,
                                frame_info: TaskFrameInfo,
                                func: FunctionDecl,
                                analysis: TaskAnalysis,
                                state_blocks: List,
                                task_result_type):
        """Generate code for each state in the state machine."""
        cg = self.cg
        suspension_points = analysis.suspension_points

        # State 0: Initial state - execute until first suspension
        builder.position_at_end(state_blocks[0])

        if not suspension_points:
            # No suspension points - run to completion and return DONE
            # This shouldn't happen if we're generating state machine
            result = ir.Constant(task_result_type, [
                ir.Constant(ir.IntType(32), TASK_RESULT_DONE),
                ir.Constant(ir.IntType(64), 0),
                ir.Constant(ir.IntType(8).as_pointer(), None),
                ir.Constant(ir.IntType(8).as_pointer(), None),
            ])
            builder.ret(result)
            return

        # For state 0: execute code before first suspension, then SPAWN child
        first_sp = suspension_points[0]

        # Update state to 1 (after first suspension)
        state_ptr = builder.gep(frame_ptr, [
            ir.Constant(ir.IntType(32), 0),
            ir.Constant(ir.IntType(32), frame_info.field_indices['__state'])
        ], inbounds=True)
        builder.store(ir.Constant(ir.IntType(64), 1), state_ptr)

        # Create child frame and return SPAWN
        # For now, return a placeholder - the actual child frame creation
        # requires generating code for the callee's frame
        child_frame_ptr = ir.Constant(ir.IntType(8).as_pointer(), None)
        child_step_ptr = ir.Constant(ir.IntType(8).as_pointer(), None)

        result = ir.Constant(task_result_type, [
            ir.Constant(ir.IntType(32), TASK_RESULT_SPAWN),
            ir.Constant(ir.IntType(64), 0),
            child_frame_ptr,
            child_step_ptr,
        ])
        builder.ret(result)

        # Generate remaining states
        for i, sp in enumerate(suspension_points):
            state_idx = i + 1
            builder.position_at_end(state_blocks[state_idx])

            # Load resolved value from previous suspension
            resolved_ptr = builder.gep(frame_ptr, [
                ir.Constant(ir.IntType(32), 0),
                ir.Constant(ir.IntType(32), frame_info.field_indices['__resolved'])
            ], inbounds=True)
            resolved_val = builder.load(resolved_ptr, name="resolved")

            # Store to variable if this suspension had a target
            if sp.var_name and sp.var_name in frame_info.field_indices:
                var_ptr = builder.gep(frame_ptr, [
                    ir.Constant(ir.IntType(32), 0),
                    ir.Constant(ir.IntType(32), frame_info.field_indices[sp.var_name])
                ], inbounds=True)
                builder.store(resolved_val, var_ptr)

            # Check if there's another suspension after this
            if state_idx < len(suspension_points):
                # More suspensions - advance state and SPAWN next child
                next_state = state_idx + 1
                state_ptr = builder.gep(frame_ptr, [
                    ir.Constant(ir.IntType(32), 0),
                    ir.Constant(ir.IntType(32), frame_info.field_indices['__state'])
                ], inbounds=True)
                builder.store(ir.Constant(ir.IntType(64), next_state), state_ptr)

                result = ir.Constant(task_result_type, [
                    ir.Constant(ir.IntType(32), TASK_RESULT_SPAWN),
                    ir.Constant(ir.IntType(64), 0),
                    ir.Constant(ir.IntType(8).as_pointer(), None),
                    ir.Constant(ir.IntType(8).as_pointer(), None),
                ])
                builder.ret(result)
            else:
                # Last state - return DONE with final value
                # Load return value (use resolved_val or compute from frame)
                result = ir.Constant(task_result_type, [
                    ir.Constant(ir.IntType(32), TASK_RESULT_DONE),
                    resolved_val,
                    ir.Constant(ir.IntType(8).as_pointer(), None),
                    ir.Constant(ir.IntType(8).as_pointer(), None),
                ])
                builder.ret(result)

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

        # Create entry function
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
        frame_size = ir.Constant(ir.IntType(64), 64)  # Approximate size
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
        fn_type = ir.FunctionType(ir.IntType(8).as_pointer(), [ir.IntType(64)])
        fn = ir.Function(cg.module, fn_type, name="malloc")
        cg.functions["malloc"] = fn
        return fn

    def _get_or_declare_free(self) -> ir.Function:
        """Get or declare free function."""
        cg = self.cg
        if "free" in cg.functions:
            return cg.functions["free"]
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


def create_task_transformer(cg: 'CodeGenerator') -> TaskTransformer:
    """Factory function to create a TaskTransformer."""
    return TaskTransformer(cg)
