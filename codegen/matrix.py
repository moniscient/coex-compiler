"""
Matrix (Cellular Automata) type implementation for Coex.

This module provides the Matrix type implementation for the Coex compiler.
Matrix is a 2D grid structure with double-buffered read/write semantics
for cellular automata computation.

Matrix struct:
    Field 0: width (i64)
    Field 1: height (i64)
    Field 2: read_buffer (elem_type*) - Current state (read from)
    Field 3: write_buffer (elem_type*) - Next state (write to)

The double-buffering allows cellular automata formulas to read from
the current state while writing the next state, with buffer swapping
after each step.

Matrix methods iterate over all cells, executing a formula for each
cell that can access neighboring cells through the `cell` keyword.
"""
from typing import TYPE_CHECKING
from llvmlite import ir

if TYPE_CHECKING:
    from codegen.core import CodeGenerator


class MatrixGenerator:
    """Generates Matrix (Cellular Automata) type and methods for the Coex compiler."""

    def __init__(self, codegen: 'CodeGenerator'):
        """Initialize with reference to parent CodeGenerator instance."""
        self.cg = codegen

    def register_matrix(self, matrix_decl: 'MatrixDecl'):
        """Register a matrix declaration and create its runtime structure."""
        cg = self.cg

        name = matrix_decl.name
        cg.matrix_decls[name] = matrix_decl

        # Determine element type
        elem_type = cg._get_llvm_type(matrix_decl.element_type)

        # Create matrix struct type
        # struct Matrix_Name {
        #   i64 width, i64 height,
        #   elem_type* read_buffer,   # Current state (read from)
        #   elem_type* write_buffer,  # Next state (write to)
        # }
        struct_name = f"struct.Matrix_{name}"
        matrix_struct = ir.global_context.get_identified_type(struct_name)
        matrix_struct.set_body(
            ir.IntType(64),           # width
            ir.IntType(64),           # height
            elem_type.as_pointer(),   # read_buffer
            elem_type.as_pointer(),   # write_buffer
        )
        cg.matrix_structs[name] = matrix_struct

        # Register in type registry for method dispatch
        # Register under both 'Counter' (for Type.new() pattern) and 'Matrix_Counter' (for instance method dispatch)
        cg.type_registry[name] = matrix_struct
        cg.type_methods[name] = {}

        # Also register under full struct name for method dispatch (since _get_type_name_from_ptr returns "Matrix_Counter")
        full_name = f"Matrix_{name}"
        cg.type_registry[full_name] = matrix_struct
        cg.type_methods[full_name] = {}

        # Create constructor: Matrix_Name.new() -> Matrix_Name*
        self._create_matrix_constructor(name, matrix_decl, matrix_struct, elem_type)

        # Create accessor methods
        self._create_matrix_accessors(name, matrix_struct, elem_type)

    def _create_matrix_constructor(self, name: str, matrix_decl: 'MatrixDecl',
                                    matrix_struct: ir.Type, elem_type: ir.Type):
        """Create the matrix constructor function."""
        cg = self.cg

        matrix_ptr_type = matrix_struct.as_pointer()

        # new() -> Matrix*
        func_name = f"Matrix_{name}_new"
        func_type = ir.FunctionType(matrix_ptr_type, [])
        func = ir.Function(cg.module, func_type, name=func_name)
        cg.functions[func_name] = func
        cg.type_methods[name]["new"] = func_name
        cg.type_methods[f"Matrix_{name}"]["new"] = func_name

        entry = func.append_basic_block("entry")
        builder = ir.IRBuilder(entry)

        # Evaluate width and height (they should be constant expressions)
        # For now, we generate them inline
        saved_builder = cg.builder
        cg.builder = builder

        width_val = cg._generate_expression(matrix_decl.width)
        height_val = cg._generate_expression(matrix_decl.height)
        init_val = cg._generate_expression(matrix_decl.init_value)

        cg.builder = saved_builder

        # Ensure i64
        if width_val.type != ir.IntType(64):
            width_val = builder.zext(width_val, ir.IntType(64))
        if height_val.type != ir.IntType(64):
            height_val = builder.zext(height_val, ir.IntType(64))

        # Allocate matrix struct via GC
        struct_size = ir.Constant(ir.IntType(64), 32)  # 4 * 8 bytes
        matrix_type_id = ir.Constant(ir.IntType(32), cg.gc.TYPE_UNKNOWN)
        raw_ptr = cg.gc.alloc_with_deref(builder, struct_size, matrix_type_id)
        matrix_ptr = builder.bitcast(raw_ptr, matrix_ptr_type)

        # Store width and height
        width_field = builder.gep(matrix_ptr, [
            ir.Constant(ir.IntType(32), 0),
            ir.Constant(ir.IntType(32), 0)
        ], inbounds=True)
        builder.store(width_val, width_field)

        height_field = builder.gep(matrix_ptr, [
            ir.Constant(ir.IntType(32), 0),
            ir.Constant(ir.IntType(32), 1)
        ], inbounds=True)
        builder.store(height_val, height_field)

        # Calculate buffer size
        total_cells = builder.mul(width_val, height_val)
        elem_size = cg._get_type_size(elem_type)
        buffer_size = builder.mul(total_cells, ir.Constant(ir.IntType(64), elem_size))

        # Allocate read buffer via GC
        buffer_type_id = ir.Constant(ir.IntType(32), cg.gc.TYPE_ARRAY_DATA)
        read_raw = cg.gc.alloc_with_deref(builder, buffer_size, buffer_type_id)
        read_buffer = builder.bitcast(read_raw, elem_type.as_pointer())
        read_field = builder.gep(matrix_ptr, [
            ir.Constant(ir.IntType(32), 0),
            ir.Constant(ir.IntType(32), 2)
        ], inbounds=True)
        builder.store(read_buffer, read_field)

        # Allocate write buffer via GC
        write_raw = cg.gc.alloc_with_deref(builder, buffer_size, buffer_type_id)
        write_buffer = builder.bitcast(write_raw, elem_type.as_pointer())
        write_field = builder.gep(matrix_ptr, [
            ir.Constant(ir.IntType(32), 0),
            ir.Constant(ir.IntType(32), 3)
        ], inbounds=True)
        builder.store(write_buffer, write_field)

        # Initialize all cells to init_value
        # for i in range(total_cells): buffer[i] = init_val
        idx_ptr = builder.alloca(ir.IntType(64), name="init_idx")
        builder.store(ir.Constant(ir.IntType(64), 0), idx_ptr)

        init_loop = func.append_basic_block("init_loop")
        init_body = func.append_basic_block("init_body")
        init_done = func.append_basic_block("init_done")

        builder.branch(init_loop)

        builder.position_at_end(init_loop)
        idx = builder.load(idx_ptr)
        cond = builder.icmp_signed("<", idx, total_cells)
        builder.cbranch(cond, init_body, init_done)

        builder.position_at_end(init_body)
        # Initialize both buffers
        read_elem_ptr = builder.gep(read_buffer, [idx])
        write_elem_ptr = builder.gep(write_buffer, [idx])

        # Cast init_val to element type if needed
        stored_val = cg._cast_value_with_builder(builder, init_val, elem_type)
        builder.store(stored_val, read_elem_ptr)
        builder.store(stored_val, write_elem_ptr)

        next_idx = builder.add(idx, ir.Constant(ir.IntType(64), 1))
        builder.store(next_idx, idx_ptr)
        builder.branch(init_loop)

        builder.position_at_end(init_done)
        builder.ret(matrix_ptr)

    def _create_matrix_accessors(self, name: str, matrix_struct: ir.Type, elem_type: ir.Type):
        """Create get/set accessor methods for a matrix."""
        cg = self.cg

        matrix_ptr_type = matrix_struct.as_pointer()
        i64 = ir.IntType(64)

        # get(x, y) -> elem_type
        get_name = f"Matrix_{name}_get"
        get_type = ir.FunctionType(elem_type, [matrix_ptr_type, i64, i64])
        get_func = ir.Function(cg.module, get_type, name=get_name)
        cg.functions[get_name] = get_func
        cg.type_methods[name]["get"] = get_name
        cg.type_methods[f"Matrix_{name}"]["get"] = get_name

        get_func.args[0].name = "self"
        get_func.args[1].name = "x"
        get_func.args[2].name = "y"

        entry = get_func.append_basic_block("entry")
        builder = ir.IRBuilder(entry)

        self_ptr = get_func.args[0]
        x = get_func.args[1]
        y = get_func.args[2]

        # Get width for index calculation
        width_field = builder.gep(self_ptr, [
            ir.Constant(ir.IntType(32), 0),
            ir.Constant(ir.IntType(32), 0)
        ], inbounds=True)
        width = builder.load(width_field)

        # Get read buffer
        read_field = builder.gep(self_ptr, [
            ir.Constant(ir.IntType(32), 0),
            ir.Constant(ir.IntType(32), 2)
        ], inbounds=True)
        read_buffer = builder.load(read_field)

        # Calculate index: y * width + x
        row_offset = builder.mul(y, width)
        idx = builder.add(row_offset, x)

        # Load and return value
        elem_ptr = builder.gep(read_buffer, [idx])
        value = builder.load(elem_ptr)
        builder.ret(value)

        # set(x, y, value)
        set_name = f"Matrix_{name}_set"
        set_type = ir.FunctionType(ir.VoidType(), [matrix_ptr_type, i64, i64, elem_type])
        set_func = ir.Function(cg.module, set_type, name=set_name)
        cg.functions[set_name] = set_func
        cg.type_methods[name]["set"] = set_name
        cg.type_methods[f"Matrix_{name}"]["set"] = set_name

        set_func.args[0].name = "self"
        set_func.args[1].name = "x"
        set_func.args[2].name = "y"
        set_func.args[3].name = "value"

        entry = set_func.append_basic_block("entry")
        builder = ir.IRBuilder(entry)

        self_ptr = set_func.args[0]
        x = set_func.args[1]
        y = set_func.args[2]
        value = set_func.args[3]

        # Get width
        width_field = builder.gep(self_ptr, [
            ir.Constant(ir.IntType(32), 0),
            ir.Constant(ir.IntType(32), 0)
        ], inbounds=True)
        width = builder.load(width_field)

        # Get read buffer (set writes to read buffer for direct access)
        read_field = builder.gep(self_ptr, [
            ir.Constant(ir.IntType(32), 0),
            ir.Constant(ir.IntType(32), 2)
        ], inbounds=True)
        read_buffer = builder.load(read_field)

        # Calculate index
        row_offset = builder.mul(y, width)
        idx = builder.add(row_offset, x)

        # Store value
        elem_ptr = builder.gep(read_buffer, [idx])
        builder.store(value, elem_ptr)
        builder.ret_void()

        # width() -> i64
        width_name = f"Matrix_{name}_width"
        width_type = ir.FunctionType(i64, [matrix_ptr_type])
        width_func = ir.Function(cg.module, width_type, name=width_name)
        cg.functions[width_name] = width_func
        cg.type_methods[name]["width"] = width_name
        cg.type_methods[f"Matrix_{name}"]["width"] = width_name

        entry = width_func.append_basic_block("entry")
        builder = ir.IRBuilder(entry)
        width_field = builder.gep(width_func.args[0], [
            ir.Constant(ir.IntType(32), 0),
            ir.Constant(ir.IntType(32), 0)
        ], inbounds=True)
        builder.ret(builder.load(width_field))

        # height() -> i64
        height_name = f"Matrix_{name}_height"
        height_type = ir.FunctionType(i64, [matrix_ptr_type])
        height_func = ir.Function(cg.module, height_type, name=height_name)
        cg.functions[height_name] = height_func
        cg.type_methods[name]["height"] = height_name
        cg.type_methods[f"Matrix_{name}"]["height"] = height_name

        entry = height_func.append_basic_block("entry")
        builder = ir.IRBuilder(entry)
        height_field = builder.gep(height_func.args[0], [
            ir.Constant(ir.IntType(32), 0),
            ir.Constant(ir.IntType(32), 1)
        ], inbounds=True)
        builder.ret(builder.load(height_field))

    def declare_matrix_methods(self, matrix_decl: 'MatrixDecl'):
        """Declare user-defined matrix methods (register names without generating bodies)."""
        cg = self.cg

        name = matrix_decl.name
        matrix_struct = cg.matrix_structs[name]
        matrix_ptr_type = matrix_struct.as_pointer()

        for method in matrix_decl.methods:
            func_name = f"Matrix_{name}_{method.name}"
            func_type = ir.FunctionType(ir.VoidType(), [matrix_ptr_type])
            func = ir.Function(cg.module, func_type, name=func_name)
            cg.functions[func_name] = func
            cg.type_methods[name][method.name] = func_name
            cg.type_methods[f"Matrix_{name}"][method.name] = func_name

    def generate_matrix_methods(self, matrix_decl: 'MatrixDecl'):
        """Generate user-defined matrix methods (formulas that apply to all cells)."""
        cg = self.cg

        name = matrix_decl.name
        matrix_struct = cg.matrix_structs[name]
        elem_type = cg._get_llvm_type(matrix_decl.element_type)

        for method in matrix_decl.methods:
            self._generate_matrix_formula(name, method, matrix_struct, elem_type)

    def _generate_matrix_formula(self, matrix_name: str, method: 'FunctionDecl',
                                  matrix_struct: ir.Type, elem_type: ir.Type):
        """Generate a matrix formula method that applies to all cells.

        This generates a function that:
        1. Iterates over all cells (y, x)
        2. Sets up cell context (current position, read buffer access)
        3. Calls the formula body for each cell
        4. Writes result to write buffer
        5. Swaps buffers after completion
        """
        cg = self.cg

        matrix_ptr_type = matrix_struct.as_pointer()
        i64 = ir.IntType(64)

        # Get the already-declared method
        func_name = f"Matrix_{matrix_name}_{method.name}"
        func = cg.functions[func_name]

        func.args[0].name = "self"

        entry = func.append_basic_block("entry")
        cg.builder = ir.IRBuilder(entry)

        # Save state
        saved_locals = cg.locals.copy()
        saved_matrix = cg.current_matrix
        saved_cell_x = cg.current_cell_x
        saved_cell_y = cg.current_cell_y

        cg.locals = {}
        cg._reset_function_scope()
        cg.current_matrix = matrix_name

        # Get self pointer
        self_ptr = func.args[0]
        self_alloca = cg.builder.alloca(matrix_ptr_type, name="self")
        cg.builder.store(self_ptr, self_alloca)
        cg.locals["self"] = self_alloca

        # Load matrix dimensions
        width_field = cg.builder.gep(self_ptr, [
            ir.Constant(ir.IntType(32), 0),
            ir.Constant(ir.IntType(32), 0)
        ], inbounds=True)
        width = cg.builder.load(width_field, name="width")

        height_field = cg.builder.gep(self_ptr, [
            ir.Constant(ir.IntType(32), 0),
            ir.Constant(ir.IntType(32), 1)
        ], inbounds=True)
        height = cg.builder.load(height_field, name="height")

        # Get buffer pointers
        read_field = cg.builder.gep(self_ptr, [
            ir.Constant(ir.IntType(32), 0),
            ir.Constant(ir.IntType(32), 2)
        ], inbounds=True)
        read_buffer = cg.builder.load(read_field, name="read_buffer")

        write_field = cg.builder.gep(self_ptr, [
            ir.Constant(ir.IntType(32), 0),
            ir.Constant(ir.IntType(32), 3)
        ], inbounds=True)
        write_buffer = cg.builder.load(write_field, name="write_buffer")

        # Store buffers for cell access
        read_alloca = cg.builder.alloca(elem_type.as_pointer(), name="read_buf")
        cg.builder.store(read_buffer, read_alloca)
        cg.locals["__read_buffer"] = read_alloca

        write_alloca = cg.builder.alloca(elem_type.as_pointer(), name="write_buf")
        cg.builder.store(write_buffer, write_alloca)
        cg.locals["__write_buffer"] = write_alloca

        width_alloca = cg.builder.alloca(i64, name="matrix_width")
        cg.builder.store(width, width_alloca)
        cg.locals["__width"] = width_alloca

        height_alloca = cg.builder.alloca(i64, name="matrix_height")
        cg.builder.store(height, height_alloca)
        cg.locals["__height"] = height_alloca

        # PRE-ALLOCATE all local variables used in the formula body
        # This prevents stack overflow from allocas inside the loop
        local_vars = cg._collect_local_variables(method.body)
        for var_name in local_vars:
            if var_name not in cg.locals:
                var_alloca = cg.builder.alloca(i64, name=var_name)
                cg.locals[var_name] = var_alloca

        # Create loop: for y in 0..height: for x in 0..width: body
        y_var = cg.builder.alloca(i64, name="cell_y")
        cg.builder.store(ir.Constant(i64, 0), y_var)
        cg.locals["__cell_y"] = y_var
        cg.current_cell_y = y_var

        x_var = cg.builder.alloca(i64, name="cell_x")
        cg.locals["__cell_x"] = x_var
        cg.current_cell_x = x_var

        # Outer loop (y)
        y_loop_cond = func.append_basic_block("y_loop_cond")
        y_loop_body = func.append_basic_block("y_loop_body")
        y_loop_inc = func.append_basic_block("y_loop_inc")
        y_loop_end = func.append_basic_block("y_loop_end")

        cg.builder.branch(y_loop_cond)

        cg.builder.position_at_end(y_loop_cond)
        y_val = cg.builder.load(y_var)
        y_cond = cg.builder.icmp_signed("<", y_val, height)
        cg.builder.cbranch(y_cond, y_loop_body, y_loop_end)

        cg.builder.position_at_end(y_loop_body)
        # Inner loop (x)
        cg.builder.store(ir.Constant(i64, 0), x_var)

        x_loop_cond = func.append_basic_block("x_loop_cond")
        x_loop_body = func.append_basic_block("x_loop_body")
        x_loop_inc = func.append_basic_block("x_loop_inc")
        x_loop_end = func.append_basic_block("x_loop_end")

        cg.builder.branch(x_loop_cond)

        cg.builder.position_at_end(x_loop_cond)
        x_val = cg.builder.load(x_var)
        x_cond = cg.builder.icmp_signed("<", x_val, width)
        cg.builder.cbranch(x_cond, x_loop_body, x_loop_end)

        cg.builder.position_at_end(x_loop_body)

        # Generate formula body
        result = None
        for stmt in method.body:
            result = cg._generate_statement(stmt)
            if cg.builder.block.is_terminated:
                break

        # Only generate write-to-buffer code if block isn't already terminated by return
        if not cg.builder.block.is_terminated:
            # If no explicit return, the formula should return a value
            # Write result to write buffer
            if result is None:
                result = ir.Constant(elem_type, 0)

            # Calculate write index
            x_val = cg.builder.load(x_var)
            y_val = cg.builder.load(y_var)
            width_val = cg.builder.load(width_alloca)
            write_buf = cg.builder.load(write_alloca)

            row_offset = cg.builder.mul(y_val, width_val)
            write_idx = cg.builder.add(row_offset, x_val)
            write_ptr = cg.builder.gep(write_buf, [write_idx])

            # Store result if we have one (non-void expression result)
            if result is not None and hasattr(result, 'type') and result.type != ir.VoidType():
                cg.builder.store(result, write_ptr)

            cg.builder.branch(x_loop_inc)

        # x increment
        cg.builder.position_at_end(x_loop_inc)
        x_val = cg.builder.load(x_var)
        next_x = cg.builder.add(x_val, ir.Constant(i64, 1))
        cg.builder.store(next_x, x_var)
        cg.builder.branch(x_loop_cond)

        # x loop end -> y increment
        cg.builder.position_at_end(x_loop_end)
        cg.builder.branch(y_loop_inc)

        # y increment
        cg.builder.position_at_end(y_loop_inc)
        y_val = cg.builder.load(y_var)
        next_y = cg.builder.add(y_val, ir.Constant(i64, 1))
        cg.builder.store(next_y, y_var)
        cg.builder.branch(y_loop_cond)

        # After loops: swap buffers
        cg.builder.position_at_end(y_loop_end)

        # Swap read and write buffers
        current_read = cg.builder.load(read_field)
        current_write = cg.builder.load(write_field)
        cg.builder.store(current_write, read_field)
        cg.builder.store(current_read, write_field)

        cg.builder.ret_void()

        # Restore state
        cg.locals = saved_locals
        cg.current_matrix = saved_matrix
        cg.current_cell_x = saved_cell_x
        cg.current_cell_y = saved_cell_y
