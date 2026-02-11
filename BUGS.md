# Coex Bug Tracker

## Bug Reporting Protocol

**Mandatory**: When encountering any unexpected behavior, test failure, or anomaly during development—even if worked around or tangential to the current task—immediately append a bug report here before continuing. Never assume a bug will be "remembered" for later.

### Workflow
1. **New bugs**: Append to the bottom of this file, above the "Next valid BUG ID" line. Use the ID shown there, then increment it.
2. **Resolved bugs**: When a bug is fixed, update its Status to "Fixed (date)" and move the entire entry to `BUGS-RESOLVED.md`. Do not reuse its BUG ID number.
3. **Next BUG ID**: The last line of this file always shows the next valid BUG ID. Update it after each insertion.

### Bug Categories
- **Parser**: Grammar issues, ANTLR parse failures
- **Semantic**: Type checking, binding resolution, trait matching
- **Codegen**: LLVM IR generation, type registry issues
- **Runtime**: Task scheduler, channel operations, coroutine behavior
- **GC**: Garbage collector, handle table, shadow stack issues
- **Stdlib**: Standard library functions, posix module

### Severity Levels
- **Critical**: Crashes, data corruption, security issues
- **High**: Correctness bugs, wrong output
- **Medium**: Performance issues, edge cases
- **Low**: Minor issues, cosmetic problems

---

## Open Bugs

<!-- Template for new bugs:

### BUG-XXX: One-line summary
- **Discovered**: YYYY-MM-DD, during [context]
- **Category**: [Parser|Semantic|Codegen|Runtime|GC|Stdlib]
- **Severity**: [Critical|High|Medium|Low]
- **Reproduction**: Steps to reproduce
- **Observed**: What actually happens
- **Expected**: What should happen
- **Hypothesis**: Theory about the cause
- **Files**: Likely involved files
- **Status**: Open

-->

### BUG-023: llvmlite thread_local attribute silently ignored
- **Discovered**: 2025-01-17, during codebase scan
- **Category**: Codegen
- **Severity**: High
- **Reproduction**: Set `variable.thread_local = 'localdynamic'` and inspect generated IR
- **Observed**: IR shows plain `global`, not `thread_local global`
- **Expected**: Variable should be thread-local in generated code
- **Hypothesis**: llvmlite library bug - attribute setter has no effect
- **Files**: `coex_gc.py` (TLS variables), all code using thread-local state
- **Status**: Open (workaround in place: use pthread TLS via ThreadEntry struct)




---

---

### BUG-117: LLVM 20 (llvmlite >=0.45.0) causes heap corruption and silent crashes
- **Discovered**: 2026-02-10, during Linux CI investigation
- **Category**: Codegen
- **Severity**: Critical
- **Reproduction**: Run `test_gc_auto_trigger_multiple_cycles` or `test_list_set_38_elements_tail_and_tree` on Linux with llvmlite >=0.45.0 (which uses LLVM 20 with the new PipelineTuningOptions pass manager)
- **Observed**: On Linux CI (Python 3.11, llvmlite 0.46.0/LLVM 20): `test_gc_auto_trigger_multiple_cycles` silently crashes (empty output); `test_list_set_38_elements_tail_and_tree` gets `malloc(): unaligned tcache chunk detected` (glibc heap corruption). Both pass on macOS (llvmlite 0.43.0/LLVM 14).
- **Expected**: Tests should pass with any supported llvmlite version
- **Hypothesis**: LLVM 20's new optimization pipeline is more aggressive and may exploit undefined behavior in our IR, particularly: (1) ptrtoint→arithmetic→inttoptr roundtrips that lose pointer provenance, (2) plain (non-atomic) initial loads on atomically-modified alloc_list pointers (data race UB in C11 memory model), (3) possible other UB patterns that LLVM 14 doesn't exploit.
- **Root causes to investigate**:
  - All `ptrtoint → sub → inttoptr` patterns for header access (widespread in coex_gc.py). Should use `gep` with negative offset to preserve provenance.
  - Plain loads at gc_alloc_to_thread_list:6525, gc_sweep:6668, prepend_survivors:6953 racing with atomic CAS operations on same memory. Should be `load_atomic(..., ordering='monotonic')`.
  - Any other UB patterns exposed by LLVM 20's stricter optimization.
- **Workaround**: Pin llvmlite to <0.45.0 in requirements.txt
- **Files**: coex_gc.py (ptrtoint/inttoptr patterns, atomic ordering), codegen/core.py (compile_to_object LLVM 20 path), requirements.txt
- **Status**: Open (workaround in place: llvmlite pinned to <0.45.0)

---

**Next valid BUG ID: BUG-121**
