# Coex Regex Module Implementation Prompt

## Overview

You are tasked with implementing a POSIX-compliant regular expression module for the Coex programming language. This module will wrap Henry Spencer's BSD regex library using Coex's foreign function interface (FFI). The module should provide basic and extended regular expression support with standard POSIX-compliant syntax. PCRE support is explicitly excluded and will be implemented as a separate module.

## Source Library

Use Henry Spencer's BSD regex library, specifically the modernized **rxspencer** version:

- **Primary Repository**: https://github.com/garyhouston/rxspencer
- **Original Repository**: https://github.com/garyhouston/regex
- **Documentation**: https://garyhouston.github.io/regex/
- **Man Pages**: 
  - API: https://garyhouston.github.io/regex/regex3.html
  - Syntax: https://garyhouston.github.io/regex/regex7.html

The rxspencer version includes:
- CMake build system for easy compilation
- Modern compiler compatibility fixes
- BSD-style license (permissive)
- Full POSIX.2 compliance for BRE and ERE

## Coex FFI Architecture

### The Extern Function Kind

Coex provides the `extern` function kind for FFI to C libraries. Key constraints:

1. **Calling Hierarchy**: Only `func` functions can call `extern` functions. Neither `formula` nor `task` can call extern functions because they provide guarantees that extern functions cannot uphold.

2. **Parameter Types**: Extern functions accept Coex primitive types and `Array<byte>`:
   - `int` (Coex 64-bit) → C `int` (32-bit, truncated)
   - `float` (Coex) → C `double`
   - `bool` (Coex) → C `int`
   - `string` (Coex) → C `char*` (data pointer extracted)
   - `Array<byte>` → raw byte buffer

3. **Return Types**: Extern functions can only return:
   - `int` (64-bit integer) - for results, error codes, or opaque handles
   - `Array<byte>` - for bulk data that becomes immutable upon crossing the boundary

4. **Syntax**: Extern functions have no body, just a declaration:
   ```coex
   extern function_name(param1: type1, param2: type2) -> return_type
   ~
   ```

### Type Mapping (from codegen.py)

The compiler performs these C ABI conversions:

```python
# Coex → C parameter conversion
int     → i32 (truncated from i64)
float   → double
bool    → i32
string  → char* (pointer to string data)

# C → Coex return conversion  
i32     → i64 (sign-extended)
```

### Opaque Handle Pattern

For C libraries that use open/use/close patterns, Coex supports opaque handles via `int` returns:

```coex
extern resource_open(config: Array<byte>) -> int
~

extern resource_use(handle: int, data: Array<byte>) -> int
~

extern resource_close(handle: int) -> int
~

func use_resource()
    handle = resource_open(config.to_bytes())
    result = resource_use(handle, input_data)
    resource_close(handle)
    return result
~
```

## Spencer's Library API

The C library provides these core functions:

```c
// Compile a pattern into a regex_t structure
int regcomp(regex_t *preg, const char *pattern, int cflags);

// Execute a compiled pattern against a string
int regexec(const regex_t *preg, const char *string,
            size_t nmatch, regmatch_t pmatch[], int eflags);

// Get error message for an error code
size_t regerror(int errcode, const regex_t *preg,
                char *errbuf, size_t errbuf_size);

// Free a compiled regex
void regfree(regex_t *preg);
```

### Compilation Flags (cflags)
- `REG_EXTENDED` (1): Use Extended Regular Expressions (ERE) instead of Basic (BRE)
- `REG_ICASE` (2): Case-insensitive matching
- `REG_NOSUB` (4): Don't report subexpression matches
- `REG_NEWLINE` (8): Newline-sensitive matching

### Execution Flags (eflags)
- `REG_NOTBOL` (1): Start of string is not beginning of line
- `REG_NOTEOL` (2): End of string is not end of line

### Match Results
```c
typedef struct {
    regoff_t rm_so;  // Start offset of match
    regoff_t rm_eo;  // End offset of match (one past last char)
} regmatch_t;
```

## Implementation Strategy

### Phase 1: C Wrapper Library

Create a thin C wrapper that simplifies the Spencer API for Coex consumption. The wrapper should:

1. **Handle Memory Management**: Allocate and free `regex_t` structures, returning opaque handles to Coex.

2. **Flatten Complex Types**: Convert `regmatch_t` arrays into formats Coex can consume (e.g., packed integers or byte arrays).

3. **Provide Simple Entry Points**:

```c
// coex_regex_wrapper.c

#include <rxspencer/regex.h>
#include <stdlib.h>
#include <string.h>

// Opaque handle storage (simple approach - production would use a proper handle table)
#define MAX_REGEX_HANDLES 1024
static regex_t* regex_handles[MAX_REGEX_HANDLES];
static int next_handle = 1;

// Compile a pattern, return handle (or negative error code)
int64_t coex_regex_compile(const char* pattern, int32_t flags) {
    if (next_handle >= MAX_REGEX_HANDLES) return -1;
    
    regex_t* preg = malloc(sizeof(regex_t));
    if (!preg) return -2;
    
    int result = regcomp(preg, pattern, flags);
    if (result != 0) {
        free(preg);
        return -result - 100;  // Offset to distinguish from handle errors
    }
    
    int handle = next_handle++;
    regex_handles[handle] = preg;
    return handle;
}

// Execute match, return 0 for match, 1 for no match, negative for error
int64_t coex_regex_match(int64_t handle, const char* text, int32_t eflags) {
    if (handle <= 0 || handle >= MAX_REGEX_HANDLES) return -1;
    regex_t* preg = regex_handles[handle];
    if (!preg) return -2;
    
    int result = regexec(preg, text, 0, NULL, eflags);
    return (result == 0) ? 0 : 1;
}

// Execute match with captures, return packed results as bytes
// Format: [match_count: i32][match0_start: i32][match0_end: i32]...
int64_t coex_regex_match_groups(int64_t handle, const char* text, 
                                 int32_t max_groups, int32_t eflags,
                                 uint8_t* output_buffer, int64_t buffer_size) {
    if (handle <= 0 || handle >= MAX_REGEX_HANDLES) return -1;
    regex_t* preg = regex_handles[handle];
    if (!preg) return -2;
    
    regmatch_t* pmatch = malloc(max_groups * sizeof(regmatch_t));
    if (!pmatch) return -3;
    
    int result = regexec(preg, text, max_groups, pmatch, eflags);
    
    if (result != 0) {
        free(pmatch);
        return 0;  // No match, return 0 groups
    }
    
    // Pack results into output buffer
    int32_t* out = (int32_t*)output_buffer;
    int count = 0;
    for (int i = 0; i < max_groups && pmatch[i].rm_so != -1; i++) {
        if ((count + 1) * 2 * sizeof(int32_t) + sizeof(int32_t) > buffer_size) break;
        out[1 + count * 2] = pmatch[i].rm_so;
        out[1 + count * 2 + 1] = pmatch[i].rm_eo;
        count++;
    }
    out[0] = count;
    
    free(pmatch);
    return count;
}

// Free a compiled regex
int64_t coex_regex_free(int64_t handle) {
    if (handle <= 0 || handle >= MAX_REGEX_HANDLES) return -1;
    regex_t* preg = regex_handles[handle];
    if (!preg) return -2;
    
    regfree(preg);
    free(preg);
    regex_handles[handle] = NULL;
    return 0;
}

// Get error message for a compile error
int64_t coex_regex_error(int64_t error_code, uint8_t* buffer, int64_t buffer_size) {
    // Convert our offset error codes back
    int regerr = (int)(-(error_code + 100));
    
    // Create a dummy regex_t for regerror (it only uses it for locale info)
    regex_t dummy;
    memset(&dummy, 0, sizeof(dummy));
    
    size_t len = regerror(regerr, &dummy, (char*)buffer, buffer_size);
    return (int64_t)len;
}
```

### Phase 2: Coex Extern Declarations

Create the Coex module with extern declarations:

```coex
# lib/regex.coex
# POSIX Regular Expression Module for Coex
# Wraps Henry Spencer's BSD regex library (rxspencer)

# Compilation flags (combine with bitwise OR in wrapper)
const REG_EXTENDED: int = 1   # Use Extended Regular Expressions
const REG_ICASE: int = 2      # Case-insensitive matching
const REG_NOSUB: int = 4      # Don't track subexpressions
const REG_NEWLINE: int = 8    # Newline-sensitive matching

# Execution flags
const REG_NOTBOL: int = 1     # Start is not beginning of line
const REG_NOTEOL: int = 2     # End is not end of line

# Extern declarations for the C wrapper
extern coex_regex_compile(pattern: string, flags: int) -> int
~

extern coex_regex_match(handle: int, text: string, eflags: int) -> int
~

extern coex_regex_free(handle: int) -> int
~

# Note: For match_groups, we need Array<byte> support
# This requires the wrapper to handle buffer passing

# High-level Coex API wrapping the extern functions

type Regex:
    handle: int
    pattern: string
    
    func compile(pattern: string) -> Regex
        return Regex.compile_with_flags(pattern, 0)
    ~
    
    func compile_extended(pattern: string) -> Regex
        return Regex.compile_with_flags(pattern, REG_EXTENDED)
    ~
    
    func compile_with_flags(pattern: string, flags: int) -> Regex
        handle = coex_regex_compile(pattern, flags)
        if handle < 0
            # Handle error - for now, store negative handle
            return Regex(handle, pattern)
        ~
        return Regex(handle, pattern)
    ~
    
    func is_valid() -> bool
        return self.handle > 0
    ~
    
    func matches(text: string) -> bool
        if self.handle <= 0
            return false
        ~
        result = coex_regex_match(self.handle, text, 0)
        return result == 0
    ~
    
    func matches_with_flags(text: string, eflags: int) -> bool
        if self.handle <= 0
            return false
        ~
        result = coex_regex_match(self.handle, text, eflags)
        return result == 0
    ~
    
    func free() -> int
        if self.handle <= 0
            return -1
        ~
        return coex_regex_free(self.handle)
    ~
~

# Convenience functions

func regex_match(pattern: string, text: string) -> bool
    r = Regex.compile_extended(pattern)
    if not r.is_valid()
        return false
    ~
    result = r.matches(text)
    r.free()
    return result
~

func regex_match_basic(pattern: string, text: string) -> bool
    r = Regex.compile(pattern)
    if not r.is_valid()
        return false
    ~
    result = r.matches(text)
    r.free()
    return result
~
```

### Phase 3: Build System Integration

Create a Makefile target or build script that:

1. Clones/downloads rxspencer if not present
2. Builds rxspencer as a static library
3. Compiles the C wrapper
4. Links everything together when compiling Coex programs that use regex

```makefile
# Example Makefile additions

RXSPENCER_DIR = lib/rxspencer
RXSPENCER_LIB = $(RXSPENCER_DIR)/librxspencer.a

$(RXSPENCER_LIB):
	cd $(RXSPENCER_DIR) && cmake . && make

lib/coex_regex_wrapper.o: lib/coex_regex_wrapper.c $(RXSPENCER_LIB)
	$(CC) -c -I$(RXSPENCER_DIR) -o $@ $<

# When linking Coex programs that use regex:
# Add: lib/coex_regex_wrapper.o $(RXSPENCER_LIB)
```

## Testing Strategy

### Unit Tests

Create tests in `tests/test_regex.py` following Coex's test patterns:

```python
class TestRegex:
    def test_basic_match(self, expect_output):
        expect_output('''
import regex

func main() -> int
    r = Regex.compile_extended("[0-9]+")
    if r.matches("abc123def")
        print(1)
    else
        print(0)
    ~
    r.free()
    return 0
~
''', "1\n")

    def test_no_match(self, expect_output):
        expect_output('''
import regex

func main() -> int
    r = Regex.compile_extended("[0-9]+")
    if r.matches("abcdef")
        print(1)
    else
        print(0)
    ~
    r.free()
    return 0
~
''', "0\n")

    def test_basic_vs_extended(self, expect_output):
        # In BRE, + is literal; in ERE, + means one-or-more
        expect_output('''
import regex

func main() -> int
    # ERE: [0-9]+ matches one or more digits
    r1 = Regex.compile_extended("[0-9]+")
    # BRE: [0-9]+ matches digit followed by literal +
    r2 = Regex.compile("[0-9]+")
    
    if r1.matches("123")
        print(1)
    ~
    if r2.matches("123")
        print(2)
    ~
    if r2.matches("1+")
        print(3)
    ~
    
    r1.free()
    r2.free()
    return 0
~
''', "1\n3\n")

    def test_case_insensitive(self, expect_output):
        # This requires adding REG_ICASE support
        pass

    def test_convenience_function(self, expect_output):
        expect_output('''
import regex

func main() -> int
    if regex_match("[a-z]+@[a-z]+\\.[a-z]+", "test@example.com")
        print(1)
    else
        print(0)
    ~
    return 0
~
''', "1\n")
```

### POSIX Compliance Tests

Port relevant tests from rxspencer's test suite to verify:
- Basic Regular Expression (BRE) syntax
- Extended Regular Expression (ERE) syntax  
- Anchors (^, $)
- Character classes ([abc], [^abc], [a-z])
- Quantifiers (*, +, ?, {n}, {n,m})
- Alternation (|) in ERE
- Grouping and backreferences
- Special characters and escaping

## Future Enhancements

### Capture Group Support

Once `Array<byte>` FFI is fully working, implement:

```coex
type Match:
    start: int
    end: int
    text: string
~

type MatchResult:
    case Success(matches: List<Match>)
    case NoMatch
    case Error(code: int, message: string)
~

# Add to Regex type:
func find_groups(text: string, max_groups: int) -> MatchResult
    # Call coex_regex_match_groups extern
    # Parse the packed byte buffer
    # Return structured result
~
```

### Search and Replace

```coex
func replace(text: string, replacement: string) -> string
    # Implement using match positions
~

func replace_all(text: string, replacement: string) -> string
    # Iterate finding all matches
~
```

### Iterator Interface

```coex
func find_all(text: string) -> List<Match>
    # Return all non-overlapping matches
~
```

## Implementation Checklist

- [ ] Clone rxspencer repository into `lib/rxspencer/`
- [ ] Create C wrapper (`lib/coex_regex_wrapper.c`)
- [ ] Build rxspencer and wrapper as static library
- [ ] Create Coex module (`lib/regex.coex`)
- [ ] Add extern declarations for wrapper functions
- [ ] Implement `Regex` type with compile/match/free
- [ ] Add convenience functions
- [ ] Update Makefile/build system for linking
- [ ] Create comprehensive test suite
- [ ] Document the module API
- [ ] Test BRE and ERE compliance
- [ ] Add error handling and error messages

## Key Files to Create

1. `lib/rxspencer/` - Cloned repository
2. `lib/coex_regex_wrapper.c` - C wrapper source
3. `lib/coex_regex_wrapper.h` - C wrapper header
4. `lib/regex.coex` - Coex module
5. `tests/test_regex.py` - Test suite
6. `docs/regex.md` - User documentation

## Notes on Coex Value Semantics

Remember that Coex uses value semantics throughout. The `Regex` type as designed above stores an opaque handle (integer), which is safe because:

1. The handle is just a number—copying it doesn't duplicate the underlying C resource
2. The programmer must explicitly call `free()` to release the C resource
3. This matches the "opaque handle" pattern described in the Coex specification

For a more robust implementation, consider adding reference counting in the C wrapper or designing the API to encourage single-use patterns.

## References

- Coex Language Specification: `The_Coex_Programming_Language.docx`
- Coex Compiler Internals: `CLAUDE.md`
- rxspencer Documentation: https://garyhouston.github.io/regex/
- POSIX.2 Regular Expressions: IEEE Std 1003.2
