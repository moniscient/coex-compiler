"""
Coex POSIX Platform Type Code Generator

Generates LLVM IR for the posix platform type, providing POSIX file I/O
and system utilities.

Methods:
- posix.open(path, mode) -> Result<posix, string>
- p.read(count) -> Result<[byte], string>
- p.read_all() -> Result<string, string>
- p.write(data) -> Result<int, string>
- p.writeln(text) -> Result<(), string>
- p.seek(offset, whence) -> Result<int, string>
- p.close() -> Result<(), string>
- posix.time() -> int
- posix.time_ns() -> int
- posix.getenv(name) -> string?
- posix.random_seed() -> int
- posix.urandom(count) -> [byte]
"""

from llvmlite import ir
from ast_nodes import PrimitiveType


class PosixGenerator:
    """Generates LLVM IR for posix platform type operations."""

    def __init__(self, codegen: 'CodeGenerator'):
        """Initialize with reference to main code generator."""
        self.cg = codegen

    def create_posix_type(self):
        """Create built-in posix platform type for POSIX I/O.

        posix is a platform type wrapping POSIX file descriptors:
        - posix.open(path, mode) -> Result<posix, string>
        - p.read_all() -> Result<string, string>
        - p.writeln(text) -> Result<(), string>
        - p.close() -> Result<(), string>
        """
        cg = self.cg
        i32 = ir.IntType(32)
        i64 = ir.IntType(64)
        i8_ptr = ir.IntType(8).as_pointer()

        # Declare POSIX file functions
        # int open(const char *pathname, int flags, mode_t mode)
        open_ty = ir.FunctionType(i32, [i8_ptr, i32, i32])
        cg.posix_open_syscall = ir.Function(cg.module, open_ty, name="open")

        # ssize_t read(int fd, void *buf, size_t count)
        read_ty = ir.FunctionType(i64, [i32, i8_ptr, i64])
        cg.posix_read_syscall = ir.Function(cg.module, read_ty, name="read")

        # int close(int fd)
        close_ty = ir.FunctionType(i32, [i32])
        cg.posix_close_syscall = ir.Function(cg.module, close_ty, name="close")

        # off_t lseek(int fd, off_t offset, int whence)
        lseek_ty = ir.FunctionType(i64, [i32, i64, i32])
        cg.posix_lseek_syscall = ir.Function(cg.module, lseek_ty, name="lseek")

        # time_t time(time_t *t) - returns seconds since Unix epoch
        time_ty = ir.FunctionType(i64, [i8_ptr])
        cg.c_time = ir.Function(cg.module, time_ty, name="time")

        # int clock_gettime(clockid_t clk_id, struct timespec *tp)
        clock_gettime_ty = ir.FunctionType(i32, [i32, i8_ptr])
        cg.c_clock_gettime = ir.Function(cg.module, clock_gettime_ty, name="clock_gettime")

        # char* getenv(const char *name)
        getenv_ty = ir.FunctionType(i8_ptr, [i8_ptr])
        cg.c_getenv = ir.Function(cg.module, getenv_ty, name="getenv")

        # Create posix struct: { i32 fd }
        cg.posix_struct = ir.global_context.get_identified_type("struct.posix")
        cg.posix_struct.set_body(
            i32,  # fd - file descriptor (only field)
        )
        posix_ptr = cg.posix_struct.as_pointer()

        # Register posix in type registry
        cg.type_registry["posix"] = cg.posix_struct
        cg.type_fields["posix"] = [("fd", PrimitiveType("int"))]
        cg.type_methods["posix"] = {}

        # Track posix as extern type
        cg.extern_types = getattr(cg, 'extern_types', set())
        cg.extern_types.add("posix")

        # Register posix with GC (4 bytes, no reference fields)
        cg.gc.register_type("posix", 4, [])

        # Create posix.open(path, mode) -> Result<posix, string>
        self._create_posix_open(posix_ptr, i8_ptr, i32, i64)

        # Create p.read_all() -> Result<string, string>
        self._create_posix_read_all(posix_ptr, i64, i8_ptr)

        # Create p.writeln(text) -> Result<(), string>
        self._create_posix_writeln(posix_ptr, i64)

        # Create p.close() -> Result<(), string>
        self._create_posix_close(posix_ptr, i32)

        # Create p.read(count) -> Result<[byte], string>
        self._create_posix_read(posix_ptr, i32, i64, i8_ptr)

        # Create p.write(data) -> Result<int, string>
        self._create_posix_write(posix_ptr, i32, i64, i8_ptr)

        # Create p.seek(offset, whence) -> Result<int, string>
        self._create_posix_seek(posix_ptr, i32, i64)

        # Create posix.time() -> int (static method)
        self._create_posix_time(i64, i8_ptr)

        # Create posix.time_ns() -> int (static method)
        self._create_posix_time_ns(i32, i64, i8_ptr)

        # Create posix.getenv(name) -> string? (static method)
        self._create_posix_getenv(i8_ptr, i64)

        # Create posix.random_seed() -> int (static method)
        self._create_posix_random_seed(i32, i64, i8_ptr)

        # Create posix.urandom(count) -> [byte] (static method)
        self._create_posix_urandom(i32, i64, i8_ptr)

    def _get_raw_string_ptr_with_builder(self, builder: ir.IRBuilder, value: str) -> ir.Value:
        """Get raw pointer to a string constant using a specific builder."""
        cg = self.cg
        name = f"str_{cg.string_counter}"
        cg.string_counter += 1
        global_str = cg._create_global_string(value, name)
        return builder.bitcast(global_str, ir.IntType(8).as_pointer())

    def _create_posix_open(self, posix_ptr: ir.Type, i8_ptr: ir.Type, i32: ir.Type, i64: ir.Type):
        """Create posix.open(path, mode) static method."""
        cg = self.cg
        result_ptr = cg.result_struct.as_pointer()
        string_ptr = cg.string_struct.as_pointer()

        # posix.open(path: String*, mode: String*) -> Result*
        func_type = ir.FunctionType(result_ptr, [string_ptr, string_ptr])
        func = ir.Function(cg.module, func_type, name="coex_posix_open")
        cg.posix_open_method = func
        cg.functions["coex_posix_open"] = func
        cg.functions["posix_open"] = func  # For static method lookup
        cg.type_methods["posix"]["open"] = "coex_posix_open"

        func.args[0].name = "path"
        func.args[1].name = "mode"

        entry = func.append_basic_block("entry")
        open_ok = func.append_basic_block("open_ok")
        open_err = func.append_basic_block("open_err")

        builder = ir.IRBuilder(entry)

        path = func.args[0]
        mode = func.args[1]

        # Get path as C string
        path_cstr = builder.call(cg.string_data, [path])

        # Parse mode string to get flags
        # For now, just check first char: 'r' = O_RDONLY (0), 'w' = O_WRONLY|O_CREAT|O_TRUNC (577)
        mode_cstr = builder.call(cg.string_data, [mode])
        first_char = builder.load(mode_cstr)

        # Check if mode is 'r' (114) or 'w' (119)
        is_read = builder.icmp_unsigned("==", first_char, ir.Constant(ir.IntType(8), ord('r')))
        read_flags = ir.Constant(i32, 0)  # O_RDONLY
        write_flags = ir.Constant(i32, 577)  # O_WRONLY | O_CREAT | O_TRUNC
        flags = builder.select(is_read, read_flags, write_flags)

        # Call open(path, flags, 0644)
        mode_bits = ir.Constant(i32, 0o644)
        fd = builder.call(cg.posix_open_syscall, [path_cstr, flags, mode_bits])

        # Check if open succeeded (fd >= 0)
        zero = ir.Constant(i32, 0)
        success = builder.icmp_signed(">=", fd, zero)
        builder.cbranch(success, open_ok, open_err)

        # Open succeeded - create posix and return Ok(posix)
        builder.position_at_end(open_ok)

        # Allocate posix struct (4 bytes for fd only)
        posix_size = ir.Constant(i64, 4)
        posix_type_id = ir.Constant(i32, cg.gc.get_type_id("posix"))
        posix_raw = cg.gc.alloc_with_deref(builder, posix_size, posix_type_id)
        posix_ptr_val = builder.bitcast(posix_raw, posix_ptr)

        # Set fd field
        fd_field = builder.gep(posix_ptr_val, [ir.Constant(i32, 0), ir.Constant(i32, 0)], inbounds=True)
        builder.store(fd, fd_field)

        # Return Result.ok(posix) - store posix pointer as i64
        posix_as_i64 = builder.ptrtoint(posix_ptr_val, i64)
        ok_result = builder.call(cg.result_ok, [posix_as_i64])
        builder.ret(ok_result)

        # Open failed - return Err(message)
        builder.position_at_end(open_err)
        err_msg = self._get_raw_string_ptr_with_builder(builder, "Failed to open file")
        err_string = builder.call(cg.string_from_literal, [err_msg])
        err_as_i64 = builder.ptrtoint(err_string, i64)
        err_result = builder.call(cg.result_err, [err_as_i64])
        builder.ret(err_result)

    def _create_posix_read_all(self, posix_ptr: ir.Type, i64: ir.Type, i8_ptr: ir.Type):
        """Create posix.read_all() method."""
        cg = self.cg
        result_ptr = cg.result_struct.as_pointer()
        string_ptr = cg.string_struct.as_pointer()
        i32 = ir.IntType(32)

        # posix.read_all() -> Result*
        func_type = ir.FunctionType(result_ptr, [posix_ptr])
        func = ir.Function(cg.module, func_type, name="coex_posix_read_all")
        cg.posix_read_all = func
        cg.functions["coex_posix_read_all"] = func
        cg.type_methods["posix"]["read_all"] = "coex_posix_read_all"

        func.args[0].name = "p"

        entry = func.append_basic_block("entry")
        read_done = func.append_basic_block("read_done")
        read_err = func.append_basic_block("read_err")

        builder = ir.IRBuilder(entry)

        p = func.args[0]

        # Get fd from posix
        fd_field = builder.gep(p, [ir.Constant(i32, 0), ir.Constant(i32, 0)], inbounds=True)
        fd = builder.load(fd_field)

        # Get file size using lseek
        # lseek(fd, 0, SEEK_END) to get size
        SEEK_END = ir.Constant(i32, 2)
        SEEK_SET = ir.Constant(i32, 0)
        file_size = builder.call(cg.posix_lseek_syscall, [fd, ir.Constant(i64, 0), SEEK_END])

        # Seek back to start
        builder.call(cg.posix_lseek_syscall, [fd, ir.Constant(i64, 0), SEEK_SET])

        # Allocate buffer for file content
        buf_size = builder.add(file_size, ir.Constant(i64, 1))  # +1 for null terminator
        string_data_type_id = ir.Constant(i32, cg.gc.TYPE_STRING_DATA)
        buffer = cg.gc.alloc_with_deref(builder, buf_size, string_data_type_id)

        # Read entire file
        bytes_read = builder.call(cg.posix_read_syscall, [fd, buffer, file_size])

        # Check if read succeeded
        zero = ir.Constant(i64, 0)
        success = builder.icmp_signed(">=", bytes_read, zero)
        builder.cbranch(success, read_done, read_err)

        # Read succeeded - create string and return Ok
        builder.position_at_end(read_done)

        # Null-terminate the buffer
        null_pos = builder.gep(buffer, [bytes_read])
        builder.store(ir.Constant(ir.IntType(8), 0), null_pos)

        # Create string from buffer (bytes_read = byte_len, assume ASCII for char_count)
        result_string = builder.call(cg.string_new, [buffer, bytes_read, bytes_read])
        string_as_i64 = builder.ptrtoint(result_string, i64)
        ok_result = builder.call(cg.result_ok, [string_as_i64])
        builder.ret(ok_result)

        # Read failed
        builder.position_at_end(read_err)
        err_msg = self._get_raw_string_ptr_with_builder(builder, "Failed to read file")
        err_string = builder.call(cg.string_from_literal, [err_msg])
        err_as_i64 = builder.ptrtoint(err_string, i64)
        err_result = builder.call(cg.result_err, [err_as_i64])
        builder.ret(err_result)

    def _create_posix_writeln(self, posix_ptr: ir.Type, i64: ir.Type):
        """Create posix.writeln(text) method."""
        cg = self.cg
        result_ptr = cg.result_struct.as_pointer()
        string_ptr = cg.string_struct.as_pointer()
        i32 = ir.IntType(32)

        # posix.writeln(text: String*) -> Result*
        func_type = ir.FunctionType(result_ptr, [posix_ptr, string_ptr])
        func = ir.Function(cg.module, func_type, name="coex_posix_writeln")
        cg.posix_writeln = func
        cg.functions["coex_posix_writeln"] = func
        cg.type_methods["posix"]["writeln"] = "coex_posix_writeln"

        func.args[0].name = "p"
        func.args[1].name = "text"

        entry = func.append_basic_block("entry")
        write_ok = func.append_basic_block("write_ok")
        write_err = func.append_basic_block("write_err")

        builder = ir.IRBuilder(entry)

        p = func.args[0]
        text = func.args[1]

        # Get fd from posix
        fd_field = builder.gep(p, [ir.Constant(i32, 0), ir.Constant(i32, 0)], inbounds=True)
        fd = builder.load(fd_field)

        # Get text data and byte size (not total memory footprint)
        text_data = builder.call(cg.string_data, [text])
        text_size = builder.call(cg.string_byte_size, [text])

        # Write text
        bytes_written = builder.call(cg.write_syscall, [fd, text_data, text_size])

        # Write newline
        newline_str = self._get_raw_string_ptr_with_builder(builder, "\n")
        builder.call(cg.write_syscall, [fd, newline_str, ir.Constant(i64, 1)])

        # Check if write succeeded
        zero = ir.Constant(i64, 0)
        success = builder.icmp_signed(">=", bytes_written, zero)
        builder.cbranch(success, write_ok, write_err)

        # Write succeeded - return Ok(())
        builder.position_at_end(write_ok)
        ok_result = builder.call(cg.result_ok, [ir.Constant(i64, 0)])
        builder.ret(ok_result)

        # Write failed
        builder.position_at_end(write_err)
        err_msg = self._get_raw_string_ptr_with_builder(builder, "Failed to write to file")
        err_string = builder.call(cg.string_from_literal, [err_msg])
        err_as_i64 = builder.ptrtoint(err_string, i64)
        err_result = builder.call(cg.result_err, [err_as_i64])
        builder.ret(err_result)

    def _create_posix_close(self, posix_ptr: ir.Type, i32: ir.Type):
        """Create posix.close() method."""
        cg = self.cg
        result_ptr = cg.result_struct.as_pointer()
        i64 = ir.IntType(64)

        # posix.close() -> Result*
        func_type = ir.FunctionType(result_ptr, [posix_ptr])
        func = ir.Function(cg.module, func_type, name="coex_posix_close")
        cg.posix_close_func = func
        cg.functions["coex_posix_close"] = func
        cg.type_methods["posix"]["close"] = "coex_posix_close"

        func.args[0].name = "posix_handle"

        entry = func.append_basic_block("entry")
        close_ok = func.append_basic_block("close_ok")
        close_err = func.append_basic_block("close_err")

        builder = ir.IRBuilder(entry)

        posix_handle = func.args[0]

        # Get fd from posix struct
        fd_field = builder.gep(posix_handle, [ir.Constant(i32, 0), ir.Constant(i32, 0)], inbounds=True)
        fd = builder.load(fd_field)

        # Close the file descriptor
        result = builder.call(cg.posix_close_syscall, [fd])

        # Check if close succeeded (result == 0)
        zero = ir.Constant(i32, 0)
        success = builder.icmp_signed("==", result, zero)
        builder.cbranch(success, close_ok, close_err)

        # Close succeeded - return Ok(())
        builder.position_at_end(close_ok)
        ok_result = builder.call(cg.result_ok, [ir.Constant(i64, 0)])
        builder.ret(ok_result)

        # Close failed
        builder.position_at_end(close_err)
        err_msg = self._get_raw_string_ptr_with_builder(builder, "Failed to close file")
        err_string = builder.call(cg.string_from_literal, [err_msg])
        err_as_i64 = builder.ptrtoint(err_string, i64)
        err_result = builder.call(cg.result_err, [err_as_i64])
        builder.ret(err_result)

    def _create_posix_read(self, posix_ptr: ir.Type, i32: ir.Type, i64: ir.Type, i8_ptr: ir.Type):
        """Create posix.read(count) method - reads bytes from file descriptor.

        Returns Result<[byte], string> - Ok with byte list or Err with message.
        """
        cg = self.cg
        result_ptr = cg.result_struct.as_pointer()
        list_ptr = cg.list_struct.as_pointer()

        # posix.read(count: int) -> Result*
        func_type = ir.FunctionType(result_ptr, [posix_ptr, i64])
        func = ir.Function(cg.module, func_type, name="coex_posix_read")
        cg.posix_read_func = func
        cg.functions["coex_posix_read"] = func
        cg.type_methods["posix"]["read"] = "coex_posix_read"

        func.args[0].name = "posix_handle"
        func.args[1].name = "count"

        entry = func.append_basic_block("entry")
        read_ok = func.append_basic_block("read_ok")
        read_err = func.append_basic_block("read_err")

        builder = ir.IRBuilder(entry)

        posix_handle = func.args[0]
        count = func.args[1]

        # Get fd from posix struct
        fd_field = builder.gep(posix_handle, [ir.Constant(i32, 0), ir.Constant(i32, 0)], inbounds=True)
        fd = builder.load(fd_field)

        # Allocate buffer for reading
        buf = builder.call(cg.malloc, [count])

        # Call read(fd, buf, count)
        bytes_read = builder.call(cg.posix_read_syscall, [fd, buf, count])

        # Check if read failed (bytes_read < 0)
        zero = ir.Constant(i64, 0)
        success = builder.icmp_signed(">=", bytes_read, zero)
        builder.cbranch(success, read_ok, read_err)

        # Read succeeded - create [byte] list from buffer
        builder.position_at_end(read_ok)

        # Create new list with elem_size = 1 (byte)
        elem_size = ir.Constant(i64, 1)
        byte_list = builder.call(cg.list_new, [elem_size])

        # Get the tail pointer from the new list and copy data there (Phase 4: handle)
        tail_handle_ptr = builder.gep(byte_list, [ir.Constant(i32, 0), ir.Constant(i32, 3)], inbounds=True)
        tail_handle = builder.load(tail_handle_ptr)
        tail = builder.inttoptr(tail_handle, ir.IntType(8).as_pointer())

        # Copy bytes_read bytes from buf to tail
        builder.call(cg.memcpy, [tail, buf, bytes_read])

        # Update list length and tail_len
        len_ptr = builder.gep(byte_list, [ir.Constant(i32, 0), ir.Constant(i32, 1)], inbounds=True)
        builder.store(bytes_read, len_ptr)

        # Phase 4: tail_len is i64
        tail_len_ptr = builder.gep(byte_list, [ir.Constant(i32, 0), ir.Constant(i32, 4)], inbounds=True)
        builder.store(bytes_read, tail_len_ptr)

        # Free the temporary buffer
        builder.call(cg.free, [buf])

        # Return Ok(byte_list)
        list_as_i64 = builder.ptrtoint(byte_list, i64)
        ok_result = builder.call(cg.result_ok, [list_as_i64])
        builder.ret(ok_result)

        # Read failed
        builder.position_at_end(read_err)
        builder.call(cg.free, [buf])
        err_msg = self._get_raw_string_ptr_with_builder(builder, "Failed to read from file")
        err_string = builder.call(cg.string_from_literal, [err_msg])
        err_as_i64 = builder.ptrtoint(err_string, i64)
        err_result = builder.call(cg.result_err, [err_as_i64])
        builder.ret(err_result)

    def _create_posix_write(self, posix_ptr: ir.Type, i32: ir.Type, i64: ir.Type, i8_ptr: ir.Type):
        """Create posix.write(data) method - writes bytes to file descriptor.

        Takes [byte] list and returns Result<int, string> with bytes written.
        """
        cg = self.cg
        result_ptr = cg.result_struct.as_pointer()
        list_ptr = cg.list_struct.as_pointer()

        # posix.write(data: [byte]) -> Result*
        func_type = ir.FunctionType(result_ptr, [posix_ptr, list_ptr])
        func = ir.Function(cg.module, func_type, name="coex_posix_write")
        cg.posix_write_func = func
        cg.functions["coex_posix_write"] = func
        cg.type_methods["posix"]["write"] = "coex_posix_write"

        func.args[0].name = "posix_handle"
        func.args[1].name = "data"

        entry = func.append_basic_block("entry")
        write_ok = func.append_basic_block("write_ok")
        write_err = func.append_basic_block("write_err")

        builder = ir.IRBuilder(entry)

        posix_handle = func.args[0]
        data = func.args[1]

        # Get fd from posix struct
        fd_field = builder.gep(posix_handle, [ir.Constant(i32, 0), ir.Constant(i32, 0)], inbounds=True)
        fd = builder.load(fd_field)

        # Get length from list
        len_ptr = builder.gep(data, [ir.Constant(i32, 0), ir.Constant(i32, 1)], inbounds=True)
        data_len = builder.load(len_ptr)

        # Get tail pointer from list (where byte data is stored) - Phase 4: handle
        tail_handle_ptr = builder.gep(data, [ir.Constant(i32, 0), ir.Constant(i32, 3)], inbounds=True)
        tail_handle = builder.load(tail_handle_ptr)
        tail = builder.inttoptr(tail_handle, ir.IntType(8).as_pointer())

        # Call write(fd, tail, len)
        bytes_written = builder.call(cg.write_syscall, [fd, tail, data_len])

        # Check if write failed (bytes_written < 0)
        zero = ir.Constant(i64, 0)
        success = builder.icmp_signed(">=", bytes_written, zero)
        builder.cbranch(success, write_ok, write_err)

        # Write succeeded - return Ok(bytes_written)
        builder.position_at_end(write_ok)
        ok_result = builder.call(cg.result_ok, [bytes_written])
        builder.ret(ok_result)

        # Write failed
        builder.position_at_end(write_err)
        err_msg = self._get_raw_string_ptr_with_builder(builder, "Failed to write to file")
        err_string = builder.call(cg.string_from_literal, [err_msg])
        err_as_i64 = builder.ptrtoint(err_string, i64)
        err_result = builder.call(cg.result_err, [err_as_i64])
        builder.ret(err_result)

    def _create_posix_seek(self, posix_ptr: ir.Type, i32: ir.Type, i64: ir.Type):
        """Create posix.seek(offset, whence) method - repositions file offset.

        whence: 0=SEEK_SET, 1=SEEK_CUR, 2=SEEK_END
        Returns Result<int, string> with new position or error.
        """
        cg = self.cg
        result_ptr = cg.result_struct.as_pointer()

        # posix.seek(offset: int, whence: int) -> Result*
        func_type = ir.FunctionType(result_ptr, [posix_ptr, i64, i64])
        func = ir.Function(cg.module, func_type, name="coex_posix_seek")
        cg.posix_seek_func = func
        cg.functions["coex_posix_seek"] = func
        cg.type_methods["posix"]["seek"] = "coex_posix_seek"

        func.args[0].name = "posix_handle"
        func.args[1].name = "offset"
        func.args[2].name = "whence"

        entry = func.append_basic_block("entry")
        seek_ok = func.append_basic_block("seek_ok")
        seek_err = func.append_basic_block("seek_err")

        builder = ir.IRBuilder(entry)

        posix_handle = func.args[0]
        offset = func.args[1]
        whence = func.args[2]

        # Get fd from posix struct
        fd_field = builder.gep(posix_handle, [ir.Constant(i32, 0), ir.Constant(i32, 0)], inbounds=True)
        fd = builder.load(fd_field)

        # Convert whence from i64 to i32 for lseek
        whence_32 = builder.trunc(whence, i32)

        # Call lseek(fd, offset, whence)
        new_pos = builder.call(cg.posix_lseek_syscall, [fd, offset, whence_32])

        # Check if lseek failed (result == -1)
        neg_one = ir.Constant(i64, -1)
        failed = builder.icmp_signed("==", new_pos, neg_one)
        builder.cbranch(failed, seek_err, seek_ok)

        # Seek succeeded - return Ok(new_pos)
        builder.position_at_end(seek_ok)
        ok_result = builder.call(cg.result_ok, [new_pos])
        builder.ret(ok_result)

        # Seek failed
        builder.position_at_end(seek_err)
        err_msg = self._get_raw_string_ptr_with_builder(builder, "Failed to seek in file")
        err_string = builder.call(cg.string_from_literal, [err_msg])
        err_as_i64 = builder.ptrtoint(err_string, i64)
        err_result = builder.call(cg.result_err, [err_as_i64])
        builder.ret(err_result)

    def _create_posix_time(self, i64: ir.Type, i8_ptr: ir.Type):
        """Create posix.time() static method - returns Unix timestamp in seconds."""
        cg = self.cg
        # posix.time() -> int
        func_type = ir.FunctionType(i64, [])
        func = ir.Function(cg.module, func_type, name="coex_posix_time")
        cg.posix_time_func = func
        cg.functions["coex_posix_time"] = func
        cg.functions["posix_time"] = func  # For static method lookup
        cg.type_methods["posix"]["time"] = "coex_posix_time"

        entry = func.append_basic_block("entry")
        builder = ir.IRBuilder(entry)

        # Call time(NULL) to get seconds since Unix epoch
        null_ptr = ir.Constant(i8_ptr, None)
        timestamp = builder.call(cg.c_time, [null_ptr])
        builder.ret(timestamp)

    def _create_posix_time_ns(self, i32: ir.Type, i64: ir.Type, i8_ptr: ir.Type):
        """Create posix.time_ns() static method - returns nanosecond precision time.

        Uses clock_gettime with runtime platform detection:
        - macOS: CLOCK_MONOTONIC = 1
        - Linux: CLOCK_MONOTONIC = 4
        """
        cg = self.cg
        # posix.time_ns() -> int
        func_type = ir.FunctionType(i64, [])
        func = ir.Function(cg.module, func_type, name="coex_posix_time_ns")
        cg.posix_time_ns_func = func
        cg.functions["coex_posix_time_ns"] = func
        cg.functions["posix_time_ns"] = func
        cg.type_methods["posix"]["time_ns"] = "coex_posix_time_ns"

        entry = func.append_basic_block("entry")
        is_linux = func.append_basic_block("is_linux")
        is_macos = func.append_basic_block("is_macos")
        call_clock = func.append_basic_block("call_clock")

        builder = ir.IRBuilder(entry)

        # Create timespec struct on stack: { i64 tv_sec, i64 tv_nsec }
        timespec_ty = ir.LiteralStructType([i64, i64])
        timespec = builder.alloca(timespec_ty, name="timespec")
        timespec_ptr = builder.bitcast(timespec, i8_ptr)

        # Runtime platform detection: try to open /proc/version (Linux-only)
        proc_version = self._get_raw_string_ptr_with_builder(builder, "/proc/version")
        O_RDONLY = ir.Constant(i32, 0)
        fd = builder.call(cg.posix_open_syscall, [proc_version, O_RDONLY, ir.Constant(i32, 0)])

        # If fd >= 0, we're on Linux; otherwise macOS
        zero = ir.Constant(i32, 0)
        is_linux_cond = builder.icmp_signed(">=", fd, zero)
        builder.cbranch(is_linux_cond, is_linux, is_macos)

        # Linux path: close fd and use CLOCK_MONOTONIC = 4
        builder.position_at_end(is_linux)
        builder.call(cg.posix_close_syscall, [fd])
        clock_id_linux = ir.Constant(i32, 4)  # CLOCK_MONOTONIC on Linux
        builder.branch(call_clock)

        # macOS path: use CLOCK_MONOTONIC = 1
        builder.position_at_end(is_macos)
        clock_id_macos = ir.Constant(i32, 1)  # CLOCK_MONOTONIC on macOS
        builder.branch(call_clock)

        # Call clock_gettime
        builder.position_at_end(call_clock)
        clock_id = builder.phi(i32, name="clock_id")
        clock_id.add_incoming(clock_id_linux, is_linux)
        clock_id.add_incoming(clock_id_macos, is_macos)

        builder.call(cg.c_clock_gettime, [clock_id, timespec_ptr])

        # Extract tv_sec and tv_nsec
        sec_ptr = builder.gep(timespec, [ir.Constant(i32, 0), ir.Constant(i32, 0)], inbounds=True)
        nsec_ptr = builder.gep(timespec, [ir.Constant(i32, 0), ir.Constant(i32, 1)], inbounds=True)
        tv_sec = builder.load(sec_ptr)
        tv_nsec = builder.load(nsec_ptr)

        # Return tv_sec * 1_000_000_000 + tv_nsec
        billion = ir.Constant(i64, 1000000000)
        result = builder.add(builder.mul(tv_sec, billion), tv_nsec)
        builder.ret(result)

    def _create_posix_getenv(self, i8_ptr: ir.Type, i64: ir.Type):
        """Create posix.getenv(name) static method - returns environment variable.

        Returns string? (optional string) - nil if not found.
        """
        cg = self.cg
        string_ptr = cg.string_struct.as_pointer()
        i32 = ir.IntType(32)

        # posix.getenv(name: string) -> string?
        # Returns nullable string pointer
        func_type = ir.FunctionType(string_ptr, [string_ptr])
        func = ir.Function(cg.module, func_type, name="coex_posix_getenv")
        cg.posix_getenv_func = func
        cg.functions["coex_posix_getenv"] = func
        cg.functions["posix_getenv"] = func
        cg.type_methods["posix"]["getenv"] = "coex_posix_getenv"

        func.args[0].name = "name"

        entry = func.append_basic_block("entry")
        found = func.append_basic_block("found")
        not_found = func.append_basic_block("not_found")

        builder = ir.IRBuilder(entry)

        name = func.args[0]

        # Get string data pointer (Phase 4: owner is i64 handle)
        # Note: getenv expects null-terminated string, so we just use string_data
        # which returns owner + offset (must ensure null-terminated at call site)
        c_str = builder.call(cg.string_data, [name])

        # Call getenv(name)
        result = builder.call(cg.c_getenv, [c_str])

        # Check if result is NULL
        null_ptr = ir.Constant(i8_ptr, None)
        is_null = builder.icmp_unsigned("==", result, null_ptr)
        builder.cbranch(is_null, not_found, found)

        # Found - wrap in Coex string
        builder.position_at_end(found)
        coex_string = builder.call(cg.string_from_literal, [result])
        builder.ret(coex_string)

        # Not found - return nil (null pointer)
        builder.position_at_end(not_found)
        null_string = ir.Constant(string_ptr, None)
        builder.ret(null_string)

    def _create_posix_random_seed(self, i32: ir.Type, i64: ir.Type, i8_ptr: ir.Type):
        """Create posix.random_seed() static method - returns random seed from /dev/urandom."""
        cg = self.cg
        # posix.random_seed() -> int
        func_type = ir.FunctionType(i64, [])
        func = ir.Function(cg.module, func_type, name="coex_posix_random_seed")
        cg.posix_random_seed_func = func
        cg.functions["coex_posix_random_seed"] = func
        cg.functions["posix_random_seed"] = func
        cg.type_methods["posix"]["random_seed"] = "coex_posix_random_seed"

        entry = func.append_basic_block("entry")
        builder = ir.IRBuilder(entry)

        # Open /dev/urandom
        urandom_path = self._get_raw_string_ptr_with_builder(builder, "/dev/urandom")
        O_RDONLY = ir.Constant(i32, 0)
        fd = builder.call(cg.posix_open_syscall, [urandom_path, O_RDONLY, ir.Constant(i32, 0)])

        # Allocate 8 bytes for i64
        buf = builder.alloca(i64, name="seed_buf")
        buf_ptr = builder.bitcast(buf, i8_ptr)

        # Read 8 bytes
        eight = ir.Constant(i64, 8)
        builder.call(cg.posix_read_syscall, [fd, buf_ptr, eight])

        # Close fd
        builder.call(cg.posix_close_syscall, [fd])

        # Return the random i64
        seed = builder.load(buf)
        builder.ret(seed)

    def _create_posix_urandom(self, i32: ir.Type, i64: ir.Type, i8_ptr: ir.Type):
        """Create posix.urandom(count) static method - returns random bytes."""
        cg = self.cg
        list_ptr = cg.list_struct.as_pointer()

        # posix.urandom(count: int) -> [byte]
        func_type = ir.FunctionType(list_ptr, [i64])
        func = ir.Function(cg.module, func_type, name="coex_posix_urandom")
        cg.posix_urandom_func = func
        cg.functions["coex_posix_urandom"] = func
        cg.functions["posix_urandom"] = func
        cg.type_methods["posix"]["urandom"] = "coex_posix_urandom"

        func.args[0].name = "count"

        entry = func.append_basic_block("entry")
        builder = ir.IRBuilder(entry)

        count = func.args[0]

        # Open /dev/urandom
        urandom_path = self._get_raw_string_ptr_with_builder(builder, "/dev/urandom")
        O_RDONLY = ir.Constant(i32, 0)
        fd = builder.call(cg.posix_open_syscall, [urandom_path, O_RDONLY, ir.Constant(i32, 0)])

        # Create new list with elem_size = 1 (byte)
        elem_size = ir.Constant(i64, 1)
        byte_list = builder.call(cg.list_new, [elem_size])

        # Get the tail pointer and read directly into it - Phase 4: handle
        tail_handle_ptr = builder.gep(byte_list, [ir.Constant(i32, 0), ir.Constant(i32, 3)], inbounds=True)
        tail_handle = builder.load(tail_handle_ptr)
        tail = builder.inttoptr(tail_handle, ir.IntType(8).as_pointer())

        # Read count bytes into tail
        builder.call(cg.posix_read_syscall, [fd, tail, count])

        # Close fd
        builder.call(cg.posix_close_syscall, [fd])

        # Update list length and tail_len
        len_ptr = builder.gep(byte_list, [ir.Constant(i32, 0), ir.Constant(i32, 1)], inbounds=True)
        builder.store(count, len_ptr)

        # Phase 4: tail_len is now i64
        tail_len_ptr = builder.gep(byte_list, [ir.Constant(i32, 0), ir.Constant(i32, 4)], inbounds=True)
        builder.store(count, tail_len_ptr)

        builder.ret(byte_list)
