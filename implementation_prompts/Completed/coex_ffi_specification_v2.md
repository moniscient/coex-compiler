# Coex FFI Module Specification

## Overview

Coex modules that interface with foreign code use LLVM bitcode (`.bc` files) as the distribution format for compiled foreign functions. This approach preserves Coex's core principle of machine-specific compilation at build time while eliminating runtime dependencies on C compilers for end users.

Foreign function interfaces in Coex follow a strict boundary model: foreign code operates outside Coex's safety guarantees, and data crossing the boundary becomes independent Coex values through explicit copying. The `extern` function kind declares the interface; LLVM bitcode provides the implementation; a JSON configuration object describes the binding; and the `@ffi` annotation connects them.

## FFI Declaration Pattern

FFI modules use three components:

1. **JSON configuration**: A const declaring bitcode locations, version info, and symbol signatures
2. **@ffi annotation**: Binds extern declarations to a configuration
3. **extern declarations**: The foreign function signatures callable from Coex

```coex
# FFI Configuration
const rxspencer: json = {
    "name": "rxspencer",
    "version": "3.9.0",
    "license": "BSD-2-Clause",
    "source": "https://github.com/garyhouston/rxspencer",
    "bitcode": {
        "x86_64-unknown-linux-gnu": "ffi/rxspencer.x86_64-linux.bc",
        "x86_64-apple-darwin": "ffi/rxspencer.x86_64-darwin.bc",
        "x86_64-pc-windows-msvc": "ffi/rxspencer.x86_64-windows.bc",
        "aarch64-unknown-linux-gnu": "ffi/rxspencer.aarch64-linux.bc",
        "aarch64-apple-darwin": "ffi/rxspencer.aarch64-darwin.bc",
        "wasm32-unknown-unknown": "ffi/rxspencer.wasm32.bc"
    },
    "symbols": {
        "coex_regex_compile": "i64 (i8*, i32)",
        "coex_regex_match": "i64 (i64, i8*, i32)",
        "coex_regex_free": "i64 (i64)"
    },
    "requires": ["libc"]
}

# Extern declarations bound to the configuration
@ffi(rxspencer)
extern coex_regex_compile(pattern: string, flags: int) -> int
~

@ffi(rxspencer)
extern coex_regex_match(handle: int, text: string, eflags: int) -> int
~

@ffi(rxspencer)
extern coex_regex_free(handle: int) -> int
~
```

## JSON Configuration Schema

The FFI configuration JSON object supports these fields:

### Required Fields

**name** (string): Library identifier, used in error messages and tooling.

**bitcode** (object): Maps LLVM target triples to bitcode file paths. Paths are relative to the module file location.

### Optional Fields

**version** (string): Semantic version of the foreign library.

**license** (string): SPDX license identifier.

**source** (string): URL to the original source repository.

**symbols** (object): Maps symbol names to LLVM type signatures. The compiler uses this to verify that extern declarations match the bitcode. If omitted, the compiler extracts signatures directly from the bitcode.

**requires** (array of strings): External dependencies needed at link time. Currently recognized values:
- `"libc"` - Standard C library (malloc, free, memcpy, etc.)

### Example Configurations

Minimal configuration:

```coex
const mylib: json = {
    "name": "mylib",
    "bitcode": {
        "x86_64-unknown-linux-gnu": "ffi/mylib.x86_64-linux.bc",
        "x86_64-apple-darwin": "ffi/mylib.x86_64-darwin.bc"
    }
}
```

Full configuration:

```coex
const rxspencer: json = {
    "name": "rxspencer",
    "version": "3.9.0",
    "license": "BSD-2-Clause",
    "source": "https://github.com/garyhouston/rxspencer",
    "bitcode": {
        "x86_64-unknown-linux-gnu": "ffi/rxspencer.x86_64-linux.bc",
        "x86_64-apple-darwin": "ffi/rxspencer.x86_64-darwin.bc",
        "x86_64-pc-windows-msvc": "ffi/rxspencer.x86_64-windows.bc",
        "aarch64-unknown-linux-gnu": "ffi/rxspencer.aarch64-linux.bc",
        "aarch64-apple-darwin": "ffi/rxspencer.aarch64-darwin.bc",
        "wasm32-unknown-unknown": "ffi/rxspencer.wasm32.bc"
    },
    "symbols": {
        "coex_regex_compile": "i64 (i8*, i32)",
        "coex_regex_match": "i64 (i64, i8*, i32)",
        "coex_regex_match_groups": "i64 (i64, i8*, i32, i32, i8*, i64)",
        "coex_regex_free": "i64 (i64)",
        "coex_regex_error": "i64 (i64, i8*, i64)"
    },
    "requires": ["libc"]
}
```

## Module Structure

A Coex module with FFI dependencies follows this directory structure:

```
lib/<module_name>/
    <module_name>.coex          # Coex module with @ffi annotations
    ffi/
        <library>.x86_64-linux.bc
        <library>.x86_64-darwin.bc
        <library>.x86_64-windows.bc
        <library>.aarch64-linux.bc
        <library>.aarch64-darwin.bc
        <library>.wasm32.bc
        src/                    # Optional: original C source
            <source_files>.c
            <header_files>.h
            build.sh            # Script for regenerating bitcode
```

## Compiler Behavior

When the Coex compiler encounters an `@ffi` annotation, it performs these steps:

1. **Resolve Configuration**: Look up the identifier in the annotation. It must reference a `const` binding of type `json` in the current scope.

2. **Validate JSON Schema**: Verify the JSON object contains required fields (`name`, `bitcode`).

3. **Select Bitcode**: Based on the compilation target triple, select the appropriate `.bc` file from the `bitcode` object. If no matching bitcode exists, emit an error:
   ```
   error: No FFI bitcode for target 'riscv64-unknown-linux-gnu'
   
   Available targets for 'rxspencer':
     - x86_64-unknown-linux-gnu
     - x86_64-apple-darwin
     - aarch64-apple-darwin
   
   To add support, rebuild the bitcode from source:
     cd lib/regex/ffi/src && ./build.sh riscv64-unknown-linux-gnu
   ```

4. **Load Bitcode**: Parse the LLVM bitcode file and incorporate it into the compilation unit.

5. **Verify Declaration**: If `symbols` is present in the configuration, verify that the extern function name appears in `symbols` and that the Coex type signature is compatible with the declared LLVM signature.

6. **Check Calling Context**: Verify that calls to this extern only occur within `func` functions. Emit an error if called from `formula` or `task`:
   ```
   error: Cannot call extern function 'coex_regex_compile' from task function
   
   Extern functions operate outside Coex's safety guarantees and can only
   be called from 'func' functions. Consider wrapping the call:
   
       func compile_regex(pattern: string) -> int
           return coex_regex_compile(pattern, 0)
       ~
   ```

7. **Generate Call Code**: When compiling calls to the extern function:
   - Convert Coex values to C ABI types
   - Emit call to the foreign symbol
   - Convert return value back to Coex type

8. **Link Dependencies**: During final linking, resolve symbols listed in `requires` from system libraries.

## Type Mapping

The compiler converts between Coex types and C ABI types at the FFI boundary:

### Parameters (Coex → C)

| Coex Type | C Type | Conversion |
|-----------|--------|------------|
| `int` | `int64_t` | Direct (Coex int is 64-bit) |
| `int` | `int32_t` | Truncate if symbol signature specifies i32 |
| `float` | `double` | Direct |
| `bool` | `int32_t` | Zero-extend |
| `string` | `char*` | Extract data pointer |
| `Array<byte>` | `uint8_t*` | Extract data pointer |

### Returns (C → Coex)

| C Type | Coex Type | Conversion |
|--------|-----------|------------|
| `int64_t` | `int` | Direct |
| `int32_t` | `int` | Sign-extend |
| `double` | `float` | Direct |
| `void` | (none) | No return value |

## Memory Model

Foreign functions operate outside Coex's managed heap. The Coex runtime provides memory management primitives for FFI use.

### Arena Allocation

Temporary allocations during a single extern call use a per-call arena:

```c
void* coex_ffi_arena_alloc(size_t size);  // Bump allocation
void  coex_ffi_arena_reset(void);          // Called after extern returns
```

The arena resets automatically after each extern call returns. Foreign code needing scratch space should use arena allocation for automatic cleanup.

### Slot Table

State that must persist across extern calls uses the slot table:

```c
int64_t coex_ffi_slot_alloc(size_t size);                    // Allocate slot, return handle
void    coex_ffi_slot_write(int64_t handle, void* data, size_t size);
void*   coex_ffi_slot_get(int64_t handle);                   // Get pointer to slot data
void    coex_ffi_slot_free(int64_t handle);                  // Release slot
```

Slot handles are integers that Coex code stores and passes back to extern functions. This pattern supports resources like compiled regex handles that must survive across multiple calls.

### Boundary Crossing Rules

**Foreign → Coex**: Data must be explicitly copied into Coex-managed values.
- Integer returns pass directly (with sign extension if needed)
- Byte data: foreign code writes to a Coex-provided buffer, or runtime copies from foreign buffer into new `Array<byte>`
- Strings: foreign code writes null-terminated bytes; Coex copies into a string value

**Coex → Foreign**: Coex provides read-only access to its data.
- Integer parameters pass directly (with truncation if needed)
- String parameters: Coex extracts data pointer; foreign code must not retain it past the call
- `Array<byte>` parameters: Coex provides pointer and length; foreign code must not retain the pointer

## Building FFI Bitcode

Module maintainers generate bitcode using clang:

```bash
#!/bin/bash
# ffi/src/build.sh - Rebuild FFI bitcode from source

set -e

CLANG_FLAGS="-O2 -fPIC -DNDEBUG"

build_target() {
    local target=$1
    local output="../$(basename $(pwd)).$target.bc"
    
    echo "Building for $target..."
    
    # Compile each source file to bitcode
    for src in *.c; do
        clang $CLANG_FLAGS --target=$target -emit-llvm -c "$src" -o "${src%.c}.bc"
    done
    
    # Link all bitcode files
    llvm-link *.bc -o "$output"
    
    # Clean up intermediate files
    rm -f *.bc
    
    echo "Created $output"
}

# Default targets
TARGETS=(
    "x86_64-unknown-linux-gnu"
    "x86_64-apple-darwin"
    "x86_64-pc-windows-msvc"
    "aarch64-unknown-linux-gnu"
    "aarch64-apple-darwin"
)

# Build specified target or all defaults
if [ $# -eq 0 ]; then
    for target in "${TARGETS[@]}"; do
        build_target "$target"
    done
else
    for target in "$@"; do
        build_target "$target"
    done
fi

echo "Done."
```

### WebAssembly Builds

WebAssembly requires special handling:

```bash
build_wasm() {
    echo "Building for wasm32..."
    
    for src in *.c; do
        clang -O2 -DNDEBUG --target=wasm32 -nostdlib \
            -emit-llvm -c "$src" -o "${src%.c}.bc"
    done
    
    llvm-link *.bc -o "../$(basename $(pwd)).wasm32.bc"
    rm -f *.bc
}
```

## Complete Example: Regex Module

```coex
# lib/regex/regex.coex
#
# POSIX Regular Expression Module for Coex
# Wraps Henry Spencer's BSD regex library (rxspencer)

# ============================================================================
# FFI Configuration
# ============================================================================

const rxspencer: json = {
    "name": "rxspencer",
    "version": "3.9.0",
    "license": "BSD-2-Clause",
    "source": "https://github.com/garyhouston/rxspencer",
    "bitcode": {
        "x86_64-unknown-linux-gnu": "ffi/rxspencer.x86_64-linux.bc",
        "x86_64-apple-darwin": "ffi/rxspencer.x86_64-darwin.bc",
        "x86_64-pc-windows-msvc": "ffi/rxspencer.x86_64-windows.bc",
        "aarch64-unknown-linux-gnu": "ffi/rxspencer.aarch64-linux.bc",
        "aarch64-apple-darwin": "ffi/rxspencer.aarch64-darwin.bc",
        "wasm32-unknown-unknown": "ffi/rxspencer.wasm32.bc"
    },
    "symbols": {
        "coex_regex_compile": "i64 (i8*, i32)",
        "coex_regex_match": "i64 (i64, i8*, i32)",
        "coex_regex_free": "i64 (i64)"
    },
    "requires": ["libc"]
}

# ============================================================================
# FFI Extern Declarations
# ============================================================================

@ffi(rxspencer)
extern coex_regex_compile(pattern: string, flags: int) -> int
~

@ffi(rxspencer)
extern coex_regex_match(handle: int, text: string, eflags: int) -> int
~

@ffi(rxspencer)
extern coex_regex_free(handle: int) -> int
~

# ============================================================================
# Constants
# ============================================================================

const REG_BASIC: int = 0
const REG_EXTENDED: int = 1
const REG_ICASE: int = 2
const REG_NOSUB: int = 4
const REG_NEWLINE: int = 8

const REG_NOTBOL: int = 1
const REG_NOTEOL: int = 2

# ============================================================================
# Types
# ============================================================================

type RegexError:
    code: int
    message: string
~

type RegexResult:
    case Ok(handle: int)
    case Err(error: RegexError)
~

type MatchResult:
    case Match
    case NoMatch
    case Err(error: RegexError)
~

# ============================================================================
# Regex Type
# ============================================================================

type Regex:
    handle: int
    
    func compile(pattern: string) -> RegexResult
        return Regex.compile_flags(pattern, REG_EXTENDED)
    ~
    
    func compile_basic(pattern: string) -> RegexResult
        return Regex.compile_flags(pattern, REG_BASIC)
    ~
    
    func compile_flags(pattern: string, flags: int) -> RegexResult
        result = coex_regex_compile(pattern, flags)
        if result > 0
            return RegexResult.Ok(result)
        ~
        return RegexResult.Err(RegexError(-result, "Compilation failed"))
    ~
    
    func matches(self, text: string) -> MatchResult
        if self.handle <= 0
            return MatchResult.Err(RegexError(-1, "Invalid handle"))
        ~
        result = coex_regex_match(self.handle, text, 0)
        if result == 0
            return MatchResult.Match
        else if result == 1
            return MatchResult.NoMatch
        ~
        return MatchResult.Err(RegexError(-result, "Match failed"))
    ~
    
    func free(self) -> int
        if self.handle <= 0
            return -1
        ~
        return coex_regex_free(self.handle)
    ~
~

# ============================================================================
# Convenience Functions
# ============================================================================

func regex_match(pattern: string, text: string) -> bool
    result = Regex.compile(pattern)
    match result
        case Ok(handle):
            r = Regex(handle)
            m = r.matches(text)
            r.free()
            match m
                case Match:
                    return true
                ~
                case NoMatch:
                    return false
                ~
                case Err(e):
                    return false
                ~
            ~
        ~
        case Err(e):
            return false
        ~
    ~
~

func regex_match_basic(pattern: string, text: string) -> bool
    result = Regex.compile_basic(pattern)
    match result
        case Ok(handle):
            r = Regex(handle)
            m = r.matches(text)
            r.free()
            match m
                case Match:
                    return true
                ~
                case NoMatch:
                    return false
                ~
                case Err(e):
                    return false
                ~
            ~
        ~
        case Err(e):
            return false
        ~
    ~
~

# ============================================================================
# Module Tests
# ============================================================================

func main() -> int
    passed = 0
    failed = 0
    
    # Test 1: ERE digit match
    if regex_match("[0-9]+", "abc123def")
        print("PASS: ERE digit match")
        passed = passed + 1
    else
        print("FAIL: ERE digit match")
        failed = failed + 1
    ~
    
    # Test 2: No match
    if not regex_match("[0-9]+", "abcdef")
        print("PASS: ERE no match")
        passed = passed + 1
    else
        print("FAIL: ERE no match")
        failed = failed + 1
    ~
    
    # Test 3: Email pattern
    if regex_match("[a-z]+@[a-z]+\\.[a-z]+", "user@example.com")
        print("PASS: Email pattern")
        passed = passed + 1
    else
        print("FAIL: Email pattern")
        failed = failed + 1
    ~
    
    print("")
    print("Passed: " + passed.to_string())
    print("Failed: " + failed.to_string())
    
    return failed
~
```

## Module Directory Layout

```
lib/regex/
├── regex.coex                      # Module source (shown above)
└── ffi/
    ├── rxspencer.x86_64-linux.bc   # ~80KB
    ├── rxspencer.x86_64-darwin.bc  # ~80KB
    ├── rxspencer.x86_64-windows.bc # ~80KB
    ├── rxspencer.aarch64-linux.bc  # ~80KB
    ├── rxspencer.aarch64-darwin.bc # ~80KB
    ├── rxspencer.wasm32.bc         # ~60KB
    └── src/
        ├── build.sh                # Bitcode build script
        ├── COPYRIGHT               # rxspencer license
        ├── coex_wrapper.c          # Coex-specific wrapper
        ├── regcomp.c               # Spencer library
        ├── regexec.c
        ├── regerror.c
        ├── regfree.c
        ├── regex.h
        └── regex2.h
```

## Multiple FFI Libraries

A module can bind to multiple foreign libraries by defining multiple configurations:

```coex
const zlib_ffi: json = {
    "name": "zlib",
    "version": "1.2.13",
    "bitcode": {
        "x86_64-unknown-linux-gnu": "ffi/zlib.x86_64-linux.bc",
        "x86_64-apple-darwin": "ffi/zlib.x86_64-darwin.bc"
    }
}

const lz4_ffi: json = {
    "name": "lz4",
    "version": "1.9.4",
    "bitcode": {
        "x86_64-unknown-linux-gnu": "ffi/lz4.x86_64-linux.bc",
        "x86_64-apple-darwin": "ffi/lz4.x86_64-darwin.bc"
    }
}

@ffi(zlib_ffi)
extern deflate(data: Array<byte>, level: int) -> Array<byte>
~

@ffi(zlib_ffi)
extern inflate(data: Array<byte>) -> Array<byte>
~

@ffi(lz4_ffi)
extern lz4_compress(data: Array<byte>) -> Array<byte>
~

@ffi(lz4_ffi)
extern lz4_decompress(data: Array<byte>, original_size: int) -> Array<byte>
~
```

## Security Considerations

FFI bitcode executes with full native code privileges. The `@ffi` annotation and `extern` keyword serve as explicit markers that code is leaving Coex's safety envelope.

Module consumers should:

1. **Verify provenance**: Only use FFI modules from trusted sources
2. **Audit source**: Original C source in `ffi/src/` is available for inspection
3. **Reproducible builds**: The `build.sh` script regenerates bitcode from source
4. **Signature verification**: Package managers should support cryptographic signatures

The Coex compiler makes no safety guarantees about FFI code. Bugs in foreign code can corrupt memory, cause crashes, or introduce security vulnerabilities.

## Grammar Changes

The `@ffi` annotation requires no grammar changes—it uses the existing annotation syntax:

```antlr
annotation
    : AT IDENTIFIER (LPAREN IDENTIFIER RPAREN)? NEWLINE*
    ;
```

The compiler recognizes `@ffi` specifically and validates that:
- The argument is an identifier (not a string literal)
- The identifier references a `const` of type `json`
- The annotated declaration is an `extern` function
