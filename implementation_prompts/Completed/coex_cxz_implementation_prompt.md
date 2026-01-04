# Coex .cxz Library Support Implementation

## Overview

This document specifies the implementation of `.cxz` library support in the Coex compiler. The `.cxz` format is a ZIP-based archive containing Coex modules, FFI declarations, C source code, and metadata. This implementation enables Coex to import self-contained libraries with foreign function interfaces.

FFI libraries include C source code rather than precompiled binaries. Since Coex already requires clang for final compilation, the C source is compiled for the user's target architecture at build time and cached for subsequent use. This eliminates cross-compilation burden for library authors and ensures libraries work on any architecture clang supports.

## Prerequisites

Before starting, familiarize yourself with:

1. **Coex Compiler Architecture** (`CLAUDE.md`): Understand the compilation pipeline from source → AST → LLVM IR → executable.

2. **Existing Module System**: Review how `import` currently works in `ast_builder.py` and `codegen.py`.

3. **Extern Functions**: Review `FunctionKind.EXTERN` handling in `codegen.py`, particularly `_declare_extern_function()` and `_get_c_type()`.

4. **LLVM IR Generation**: Understand how `codegen.py` uses `llvmlite` to generate IR and link modules.

5. **CXZ Specification** (`coex_cxz_specification.md`): The complete specification for the `.cxz` format.

## Key Design Decisions

### C Source Instead of Bitcode

FFI libraries ship C source code, not precompiled LLVM bitcode. This decision was made because:

- Coex already requires clang for compilation, so there's no additional dependency
- Library authors don't need cross-compilation infrastructure for multiple architectures
- Libraries work on any architecture clang supports, including uncommon targets
- Source is always auditable—what you see is what gets compiled

Compiled objects are cached in `~/.coex/cache/` to avoid recompilation on subsequent builds.

### FFI Instance Isolation

Each func or task that uses FFI gets its own isolated instance:

- **Extern from func**: Instance scoped to func invocation, shared with nested funcs
- **Extern from task**: Instance scoped to task, completely isolated from parent and siblings

This enables safe parallel execution of thread-unsafe foreign libraries—each task has its own instance of the foreign library's state.

### Task FFI Isolation Rule

Tasks cannot access FFI instances created by their parent func. If a task needs FFI, it must make its own extern calls, which create task-local instances. This is enforced at compile time.

A future version may allow explicit shared access patterns using channels.

### The Air Gap Principle

A strict boundary exists between the Coex heap and the FFI heap:

- No shared pointers—all data is copied at the boundary
- C code never sees Coex heap pointers; Coex code never sees FFI heap pointers
- Deep copies use release semantics when returning to Coex, preserving memory ordering proofs
- Each FFI instance is isolated; corruption in one cannot affect others

This trades copy overhead for strong isolation guarantees.

### GC Safe Points

When a thread enters FFI code, it's marked as "In-Foreign-Code." The GC treats this as a safe point:

- Long-running FFI calls don't block garbage collection
- The GC can relocate Coex objects while FFI code runs (FFI only has copies)
- Handle indirection ensures Coex references remain valid after relocation

### Resource Backpressure

FFI instance creation can fail under memory pressure, returning `ResourceExhausted`. Programs handle this explicitly via select/match rather than experiencing mysterious crashes. This keeps resource management visible and explicit, consistent with Coex's philosophy.

### Cancellation via Within

FFI calls can be wrapped in `within` blocks for timeout enforcement. When a timeout expires mid-FFI, the instance is "abandoned"—the Coex program continues immediately while the OS thread finishes the C function asynchronously. Because instances are isolated, abandonment is safe.

## Implementation Checklist

### Phase 1: Archive Handling
- [ ] Create `cxz_loader.py` with `CXZLoader` class
- [ ] Implement manifest parsing (including `[ffi.system]` section)
- [ ] Implement archive validation
- [ ] Implement source extraction
- [ ] Implement source hash computation for caching
- [ ] Create `FFICache` class for compiled object caching
- [ ] Create `FFICompiler` class for clang invocation
- [ ] Implement system dependency checking (headers, pkg-config)
- [ ] Add `find_library()` search function
- [ ] Write unit tests for loader

### Phase 2: Import System
- [ ] Update grammar for string literal imports
- [ ] Regenerate ANTLR parser
- [ ] Update `ast_nodes.py` with library import fields
- [ ] Update `ast_builder.py` to handle library imports
- [ ] Implement library search logic

### Phase 3: FFI Support
- [ ] Create `ffi_codegen.py` with `FFICodeGen` class
- [ ] Create `FFIInstanceManager` class for scope tracking
- [ ] Implement FFI function declarations (including instance lifecycle)
- [ ] Implement `coex_ffi_enter` / `coex_ffi_exit` for GC safe points
- [ ] Create `runtime/ffi_support.c` with instance-local heap and slots
- [ ] Implement resource backpressure (ResourceExhausted error)
- [ ] Build FFI support as static library (libcoex_ffi.a)
- [ ] Write tests for instance creation/destruction
- [ ] Write tests for heap isolation between instances

### Phase 4: Code Generation
- [ ] Track func/task context for FFI scoping
- [ ] Generate FFI instance creation at func entry (when FFI used)
- [ ] Generate FFI instance creation at task entry (isolated)
- [ ] Generate FFI instance teardown at scope exit
- [ ] Generate `coex_ffi_enter` before extern calls
- [ ] Generate `coex_ffi_exit` after extern calls
- [ ] Implement release-ordered stores when copying from FFI to Coex heap
- [ ] Implement library module compilation
- [ ] Implement extern declaration processing
- [ ] Add compiled FFI objects to link arguments
- [ ] Implement `get_link_args()` to return object files

### Phase 5: Compiler Driver
- [ ] Update `coexc.py` for FFI object linking
- [ ] Add FFI support library linking (libcoex_ffi.a)
- [ ] Handle system library linking (`-lssl -lcrypto` etc.)
- [ ] Integrate pkg-config for system dependencies
- [ ] Handle cache miss gracefully (compile on demand)
- [ ] Handle missing clang errors gracefully
- [ ] Handle missing system dependencies with clear error messages

### Phase 6: Testing
- [ ] Create integration test suite
- [ ] Test pure Coex libraries
- [ ] Test FFI libraries with bundled C code
- [ ] Test FFI libraries with system dependencies
- [ ] Test caching (first compile vs cached)
- [ ] Test parallel task FFI isolation
- [ ] Test ResourceExhausted handling
- [ ] Test `within` timeout with FFI calls
- [ ] Test error conditions

### Phase 7: Documentation
- [ ] Update `CLAUDE.md`
- [ ] Add examples to repository
- [ ] Document library creation process
- [ ] Document system dependency requirements

## Error Messages

Implement clear, helpful error messages:

```
error: Library 'regex' not found

Searched in:
  - ./lib/regex.cxz
  - ~/.coex/lib/regex.cxz
  - /usr/local/lib/coex/regex.cxz

To install: coex pkg install regex
```

```
error: FFI compilation failed for 'regex'

Command: clang -c -fPIC -O2 -o /tmp/regex_ffi.o src/wrapper.c
Error: src/wrapper.c:42:10: fatal error: 'missing.h' file not found

Check that all header files are included in the library's src/ directory.
```

```
error: Missing system dependency for library 'tls'

Required header not found: openssl/ssl.h

Install the OpenSSL development package:
  Ubuntu/Debian: sudo apt install libssl-dev
  macOS:         brew install openssl
  Fedora:        sudo dnf install openssl-devel
```

```
error: Cannot call extern function 'coex_regex_compile' from formula function 'pure_match'

Extern functions operate outside Coex's safety guarantees and can only
be called from 'func' or 'task' functions.
```

```
error: Task cannot access parent func's FFI handle

The variable 'regex_handle' holds an FFI handle created in the parent func.
Tasks have isolated FFI instances and cannot use handles from parent scopes.

To use FFI in a task, call the extern function directly within the task:

    task for doc in docs
        r = regex_compile(pattern)  # Creates task-local instance
        result = regex_find_all(r, doc)
        regex_free(r)
        yield result
    ~

This creates an isolated FFI instance per task, enabling safe parallel
execution of thread-unsafe foreign code.
```

```
error: FFI resource exhausted

Cannot create FFI instance: system memory pressure.

Handle this with select:

    select
        case result = extern_function(args):
            # success
        ~
        case ResourceExhausted:
            # handle backpressure
        ~
    ~
```

## File Summary

New files to create:
- `cxz_loader.py` - Archive loading, validation, FFI compilation, caching
- `ffi_codegen.py` - FFI code generation helpers (compile-time only)
- `runtime/ffi_support.c` - C implementation of FFI support functions (statically linked)
- `tests/test_cxz_loader.py` - Unit tests for loader
- `tests/test_cxz_integration.py` - Integration tests

Files to modify:
- `Coex.g4` - Add string literal import syntax
- `ast_nodes.py` - Extend ImportDecl
- `ast_builder.py` - Handle library imports
- `codegen.py` - FFI integration, instance management, object linking
- `coexc.py` - Library linking in compiler driver
- `CLAUDE.md` - Documentation updates

## Detailed Implementation

See the specification document (`coex_cxz_specification.md`) for:
- Complete archive structure
- Manifest format with all fields
- FFI execution model details
- Example regex library implementation
- Type mapping at FFI boundary

The specification contains the authoritative definitions. This document focuses on implementation guidance.
