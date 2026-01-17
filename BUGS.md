# Coex Bug Tracker

## Bug Reporting Protocol

**Mandatory**: When encountering any unexpected behavior, test failure, or anomaly during development—even if worked around or tangential to the current task—immediately append a bug report here before continuing. Never assume a bug will be "remembered" for later.

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

*No open bugs currently tracked.*

---

## Resolved Bugs

### BUG-001: Mutual recursion segfault in task coroutines
- **Discovered**: 2025-01-17, during task testing
- **Category**: Runtime
- **Severity**: Critical
- **Reproduction**: Create two tasks that call each other recursively
- **Observed**: Segmentation fault during coroutine context switch
- **Expected**: Tasks should execute mutual recursion correctly
- **Hypothesis**: Stack frame allocation was insufficient for deep recursion
- **Files**: `codegen.py` (task frame allocation)
- **Status**: Resolved (commit a55f8df)
- **Resolution**: Fixed task frame allocation size calculation

### BUG-002: Scheduler race condition in task completion
- **Discovered**: 2025-01-17, during concurrent task testing
- **Category**: Runtime
- **Severity**: Critical
- **Reproduction**: Run multiple tasks with rapid completion
- **Observed**: Race condition causing undefined behavior
- **Expected**: Clean task completion without races
- **Hypothesis**: Missing synchronization in scheduler
- **Files**: `codegen.py` (scheduler implementation)
- **Status**: Resolved (commit 2b69903)
- **Resolution**: Added proper synchronization to scheduler

---

## Notes

### Session Protocol
1. **Session Start**: Review BUGS.md, summarize current state
2. **Pre-Task**: Check if any open bugs interact with planned work
3. **During Development**: Bug-on-discovery rule applies (document immediately)
4. **Session End**: Review work done, ensure all encountered bugs are recorded

### llvmlite Known Issues
- `thread_local = 'localdynamic'` is silently ignored (documented in CLAUDE.md)
- Workaround: Use pthread TLS via ThreadEntry struct
