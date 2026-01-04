

## Task: Refactor Coex Compiler to Use Explicit `posix` Platform Module

### Overview

Convert the existing built-in File type and scattered POSIX primitives in the Coex compiler into a cohesive `posix` platform module. This module represents platform-specific system primitives that may not be available on all Coex targets (embedded, WebAssembly, etc.). The `posix` type wraps a file descriptor and provides low-level I/O operations.

### Goals

1. Replace the built-in `File` type with a `posix` type that explicitly signals platform dependence
2. Consolidate all POSIX-related primitives under this single type
3. Update the main() function signature to use `posix` for stdin/stdout/stderr
4. Maintain backward compatibility for existing print() as a convenience wrapper

### The `posix` Type Definition

```coex
# posix is a built-in type wrapping a POSIX file descriptor
# Available only on Unix-like systems (Linux, macOS, BSD)

type posix:
    fd: int
~
```

### Methods to Implement

**Instance Methods (operate on a file descriptor):**

| Method | Signature | Description |
|--------|-----------|-------------|
| `read` | `func (p: posix) read(count: int) -> Result<[byte], string>` | Read up to `count` bytes |
| `read_all` | `func (p: posix) read_all() -> Result<string, string>` | Read entire contents as string |
| `write` | `func (p: posix) write(data: [byte]) -> Result<int, string>` | Write bytes, return count written |
| `writeln` | `func (p: posix) writeln(text: string) -> Result<int, string>` | Write string + newline |
| `seek` | `func (p: posix) seek(offset: int, whence: int) -> Result<int, string>` | Seek to position (whence: 0=SET, 1=CUR, 2=END) |
| `close` | `func (p: posix) close() -> Result<int, string>` | Close file descriptor |

**Static Methods (constructors and utilities):**

| Method | Signature | Description |
|--------|-----------|-------------|
| `open` | `func posix.open(path: string, mode: string) -> Result<posix, string>` | Open file ("r", "w", "rw", "a") |
| `print` | `func posix.print(value: int) -> ()` | Debug print to stdout (also overloads for float, string, bool) |

**Virtual Device Methods (not true POSIX but essential system primitives):**

| Method | Signature | Description |
|--------|-----------|-------------|
| `random_seed` | `func posix.random_seed() -> int` | Read 8 bytes from /dev/urandom as int |
| `urandom` | `func posix.urandom(count: int) -> [byte]` | Read `count` bytes from /dev/urandom |
| `time` | `func posix.time() -> int` | Unix timestamp in seconds |
| `time_ns` | `func posix.time_ns() -> int` | Monotonic nanosecond timestamp |
| `getenv` | `func posix.getenv(name: string) -> string?` | Get environment variable (nil if unset) |

### Updated main() Signature

```coex
# Minimal
func main() -> int

# With command-line arguments
func main(args: [string]) -> int

# With standard I/O handles
func main(stdin: posix, stdout: posix, stderr: posix) -> int

# Full signature
func main(args: [string], stdin: posix, stdout: posix, stderr: posix) -> int
```

The compiler generates wrapper code that creates `posix` handles with fd=0, fd=1, fd=2 for stdin, stdout, stderr respectively.

### Implementation Changes Required in codegen.py

**1. Rename and consolidate File infrastructure:**

- Rename `self.file_struct` → `self.posix_struct`
- Rename `self.file_open` → `self.posix_open`
- Rename `self.file_read_all` → `self.posix_read_all`
- Rename `self.file_writeln` → `self.posix_writeln`
- Rename `self.file_close` → `self.posix_close`
- Rename all `coex_file_*` functions → `coex_posix_*`
- Update `type_registry["File"]` → `type_registry["posix"]`
- Update `type_methods["File"]` → `type_methods["posix"]`

**2. Add new methods:**

- `_create_posix_read()` - Read specified byte count, return `Result<[byte], string>`
- `_create_posix_write()` - Write byte array, return `Result<int, string>`
- `_create_posix_seek()` - Wrapper around lseek
- `_create_posix_random_seed()` - Open /dev/urandom, read 8 bytes, convert to int, close
- `_create_posix_urandom()` - Open /dev/urandom, read n bytes, return as byte array, close
- `_create_posix_time()` - Call `time(NULL)` or `clock_gettime()`
- `_create_posix_time_ns()` - Call `clock_gettime(CLOCK_MONOTONIC)`
- `_create_posix_getenv()` - Call `getenv()`, return nullable string

**3. Add new C library declarations:**

```python
# In _create_builtins() or new _create_posix_primitives():

# time_t time(time_t *tloc)
time_ty = ir.FunctionType(i64, [i8_ptr])
self.libc_time = ir.Function(self.module, time_ty, name="time")

# int clock_gettime(clockid_t clk_id, struct timespec *tp)
clock_gettime_ty = ir.FunctionType(i32, [i32, i8_ptr])
self.libc_clock_gettime = ir.Function(self.module, clock_gettime_ty, name="clock_gettime")

# char *getenv(const char *name)
getenv_ty = ir.FunctionType(i8_ptr, [i8_ptr])
self.libc_getenv = ir.Function(self.module, getenv_ty, name="getenv")
```

**4. Update main() wrapper generation:**

In `_declare_main_with_params()` and related functions:
- Change parameter type checking from "File" to "posix"
- Update struct creation to use `self.posix_struct`

**5. Keep print() as convenience wrapper:**

The existing `print()` function should remain but internally use posix primitives. It writes to fd=1 (stdout). Mark it as deprecated in favor of `stdout.writeln()` but keep it functional for debugging convenience.

### Seek Whence Constants

Define these as the standard POSIX values:
- `SEEK_SET = 0` - Seek from beginning of file
- `SEEK_CUR = 1` - Seek from current position  
- `SEEK_END = 2` - Seek from end of file

Users pass these as integers to `posix.seek()`.

### Error Handling

All I/O operations return `Result` types. Error messages should be descriptive:
- "Failed to open file: <path>"
- "Failed to read from file descriptor"
- "Failed to write to file descriptor"
- "Failed to seek in file descriptor"
- "Failed to close file descriptor"
- "Failed to read from /dev/urandom"

For `posix.getenv()`, return `nil` (nullable string) if the variable is not set, rather than using Result—this matches the common case where missing env vars are expected.

### Testing

After implementation, verify:

1. Basic I/O:
```coex
func main(args: [string], stdin: posix, stdout: posix, stderr: posix) -> int
    stdout.writeln("Hello, world!")
    return 0
~
```

2. File operations:
```coex
func main() -> int
    match posix.open("test.txt", "w")
        case Ok(f):
            f.writeln("Test content")
            f.close()
        ~
        case Err(msg):
            posix.print(msg)
        ~
    ~
    return 0
~
```

3. Virtual devices:
```coex
func main() -> int
    seed: int = posix.random_seed()
    posix.print(seed)
    
    now: int = posix.time()
    posix.print(now)
    
    home: string? = posix.getenv("HOME")
    match home
        case Some(path):
            posix.print(path)
        ~
        case None:
            posix.print("HOME not set")
        ~
    ~
    
    return 0
~
```

### Documentation Updates

Update The_Coex_Programming_Language.docx:
- Replace all references to `File` type with `posix`
- Add section explaining platform modules and portability
- Document that `posix` is only available on Unix-like systems
- Note that future targets may provide different platform modules (e.g., `hal` for embedded, `wasm` for WebAssembly)

### Out of Scope

The following are explicitly excluded from this refactoring:
- Networking primitives (socket, bind, listen, accept, connect)
- Concurrency primitives (fork, exec, waitpid, pipe)
- Signal handling
- Memory-mapped I/O
- Directory operations (opendir, readdir, stat, mkdir) - save for future `posix` expansion

---

This prompt should provide enough detail to implement the refactoring while maintaining clarity about scope and intent.