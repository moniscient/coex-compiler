# Coex Implementation Specification: SELECT and WITHIN Statements

## Overview

This document specifies the implementation requirements for two related concurrency constructs in the Coex programming language: the `select` statement for channel multiplexing and the `within` statement for temporal progress constraints. These constructs work together to provide safe, deterministic concurrent coordination with guaranteed progress.

## Design Philosophy

Coex prioritizes correctness over performance. The guiding principle is that programmers should not be able to accidentally make concurrency mistakes. Both `select` and `within` enforce this principle by providing structured, compiler-verifiable concurrency patterns that eliminate common bugs like deadlock, livelock, and starvation at either compile time or through deterministic runtime behavior.

---

## The SELECT Statement

### Purpose

The `select` statement provides safe multiplexed waiting on multiple channel operations. When a flow function must receive from multiple channels, naive implementations can cause livelock or starvation where one process consistently wins access to a channel while another remains perpetually blocked. The `select` statement solves this through explicit fairness strategies.

### Syntax

```
select [strategy]
    case <identifier> from <channel_expr>
        <statements>
    ~
    case <identifier> from <channel_expr>
        <statements>
    ~
end
```

The `~` and `end` tokens are completely synonymous as block terminators throughout Coex.

### Strategies

The `select` statement supports five scheduling strategies. Implementers must provide all five.

**Default Strategy** (`select` without modifier): The runtime chooses an optimal fair strategy based on runtime conditions. This includes engaging the "chess ending" strategy when livelock is detected. Chess ending works by detecting oscillation patterns between threads and arbitrarily suspending one thread momentarily to allow the other to proceed. This resolves all livelock conditions that cannot be detected at compile time, though it incurs detection overhead.

```coex
flow worker(tasks: Channel<Task>, control: Channel<Command>)
    loop
        select
            case task from tasks
                process(task)
            ~
            case cmd from control
                handle(cmd)
            ~
        end
    end
end
```

**Fair Strategy** (`select fair`): Round-robin selection with guaranteed fairness. The runtime tracks which channel was last selected and rotates through channels in order, ensuring each channel receives equal opportunity. This strategy prevents starvation by construction.

```coex
flow balanced(high: Channel<Task>, low: Channel<Task>)
    loop
        select fair
            case task from high
                process(task)
            ~
            case task from low
                process(task)
            ~
        end
    end
end
```

**Random Strategy** (`select random`): Random selection among ready channels, providing statistical fairness over time. This is simpler to implement than round-robin and is appropriate when strict ordering guarantees are unnecessary.

```coex
flow worker(tasks: Channel<Task>, control: Channel<Command>)
    loop
        select random
            case task from tasks
                process(task)
            ~
            case cmd from control
                handle(cmd)
            ~
        end
    end
end
```

**Priority Strategy** (`select priority`): Checks channels in source order; the first ready channel wins. The compiler must emit a warning that this strategy can cause starvation of lower-priority channels. Use only when explicit prioritization is required, such as ensuring shutdown signals preempt normal work.

```coex
flow handler(requests: Channel<Request>, control: Channel<Command>)
    loop
        select priority
            case cmd from control
                if cmd == Shutdown
                    break
                ~
                handle(cmd)
            ~
            case req from requests
                process(req)
            ~
        end
    end
end
```

**Timeout Strategy** (`select timeout <duration>`): Time-bounded selection. If no channel becomes ready within the specified duration, the select completes without executing any case body. This provides bounded waiting guarantees for monitoring and watchdog patterns.

```coex
flow monitor(data: Channel<Data>, heartbeat: Channel<Ping>)
    loop
        select timeout 5s
            case d from data
                record(d)
            ~
            case p from heartbeat
                update_status()
            ~
        end
    end
end
```

### Guarantees

With `select fair` or `select random`, Coex guarantees no livelock at the channel selection level, no starvation of any channel, and deterministic or statistical fairness respectively. These guarantees apply to channel selection itself; application logic can still create higher-level coordination bugs that these strategies cannot prevent.

### Implementation Requirements

The runtime must implement a FairSelector that tracks the last selected channel index and starts checking from the next channel in sequence. For random selection, the runtime must find all ready channels and randomly select among them. For priority selection, channels are checked in declaration order.

All strategies must handle the case where no channels are immediately ready by blocking until at least one channel has data available (or timeout expires for the timeout strategy).

The chess ending detection for the default strategy requires monitoring thread state transitions and detecting oscillation patterns. When two threads repeatedly yield to each other without making progress, one is temporarily suspended. This detection mechanism should be configurable at the runtime level.

---

## The WITHIN Statement

### Purpose

The `within` statement provides structured timeout handling for operations that must complete within specified time bounds. It serves as a unified progress monitoring mechanism that detects slow computations, deadlock (blocked on channel operations), livelock (spinning without progress), and any other failure to complete within expected time. The runtime does not need to distinguish between these cases; they are all simply lack of progress.

### Syntax

**With timeout handler:**
```
within <duration_expr>
    <statements>
else
    <timeout_handler_statements>
end
```

**Without handler (strict mode):**
```
within <duration_expr>
    <statements>
end
```

The `<duration_expr>` is an integer expression (literal or variable) representing timeout duration in milliseconds. Duration literals with suffixes (e.g., `5s`, `100ms`, `2m`) are syntactic sugar that the lexer converts to millisecond integer values.

### Semantics

When a `within` block executes, the runtime establishes a timeout deadline. If the enclosed statements complete before the deadline expires, execution continues normally after the `end` marker and the `else` clause (if present) is skipped entirely.

If the timeout occurs before completion, behavior depends on whether an `else` clause is present. With an `else` clause, execution of the main block terminates and control transfers to the handler. Without an `else` clause, the runtime panics with diagnostic information showing where the timeout occurred and what operations were in progress.

The `else` clause can perform any valid operation within the enclosing function's capabilities, including returning values, throwing errors, retrying operations, recording diagnostics, or performing cleanup.

### Integration with Function Types

The `within` construct respects the function type hierarchy. In `formula` functions (pure computation), `within` cannot be used because formulas must provably terminate through structural means rather than runtime timeout. In `flow`, `async`, `coex`, and `func` functions, `within` is permitted and provides the primary mechanism for ensuring progress in concurrent and asynchronous operations.

### Examples

**Strict enforcement (panic on timeout):**
```coex
within 5000
    result = expensive_computation(data)
end
```

**Graceful degradation:**
```coex
async fetch_with_fallback(url: string) -> Response
    within 30000
        return await http.get(url)
    else
        print("Request timeout, using cached data")
        return get_cached_response(url)
    end
end
```

**Dynamic timeout configuration:**
```coex
func process_with_config(task: Task, timeout_ms: int) -> Result
    within timeout_ms
        return compute(task)
    else
        return Result(error: "Timeout after " + str(timeout_ms) + "ms")
    end
end
```

**Retry with exponential backoff:**
```coex
async fetch_with_retry(url: string, max_attempts: int) -> Result<Response>
    var attempt: int = 0
    var delay: int = 1000
    
    loop
        attempt += 1
        
        within delay * attempt
            response = await http.get(url)
            return Result.ok(response)
        else
            if attempt >= max_attempts
                return Result.error("Max retries exceeded")
            end
            await sleep(delay * attempt)
        end
    end
end
```

**Circuit breaker pattern:**
```coex
coex monitored_service(requests: Channel<Request>, service_url: string) -> Response
    var consecutive_timeouts: int = 0
    
    loop
        req = requests.receive()
        if req == nil
            break
        end
        
        within 3000
            response = await http.post(service_url, req.data)
            consecutive_timeouts = 0
            return response
        else
            consecutive_timeouts += 1
            if consecutive_timeouts >= 5
                return Response.circuit_open()
            end
            return Response.timeout()
        end
    end
end
```

**Nested timeouts:**
```coex
within 60000
    within 10000
        part1()
    else
        print("Part 1 timeout")
    ~
    
    within 10000
        part2()
    else
        print("Part 2 timeout")
    ~
else
    panic("Overall timeout")
end
```

Inner timeouts that complete (including via their else clause) do not trigger outer timeouts. The outer timeout applies to the total elapsed time of the entire block.

### Implementation Requirements

The runtime must start a timer when entering a `within` block, execute the enclosed statements, and cancel the timer if the block completes before the deadline. If the deadline expires, the runtime must interrupt the executing statements and transfer control to the else handler or panic.

Timer cancellation must be efficient; there should be no overhead after successful completion. The interrupt mechanism must safely handle interruption at any point in the enclosed statements, including during channel operations, async awaits, and arbitrary computation.

Panic diagnostics must include the location of the within block, the specified timeout duration, and information about what operation was in progress when the timeout occurred (e.g., "blocked on channel receive from tasks", "awaiting http.get").

---

## Interaction Between SELECT and WITHIN

The `select` and `within` constructs are designed to work together. A `within` block can enclose a `select` statement to provide an absolute time bound on channel multiplexing:

```coex
flow receive_with_guarantee(
    high_priority: Channel<Message>,
    low_priority: Channel<Message>
) -> Message
    within 10000
        select fair
            case msg from high_priority
                return msg
            ~
            case msg from low_priority
                return msg
            ~
        end
    else
        return Message.timeout_placeholder()
    end
end
```

This pattern ensures forward progress even when the fair selection strategy and chess ending detection are insufficient. The `within` provides a definitive upper bound on wait time, preventing indefinite blocking regardless of channel state.

The `select timeout` strategy provides similar timeout functionality scoped specifically to the select operation, while `within` provides timeout functionality for arbitrary code blocks. Use `select timeout` when the timeout applies only to channel selection; use `within` when the timeout should encompass additional processing after channel selection.

---

## Compiler Requirements

### SELECT Compilation

The compiler must recognize the `select` keyword followed by an optional strategy keyword (`fair`, `random`, `priority`, or `timeout` with duration) and parse zero or more case clauses. Each case clause binds an identifier to a value received from a channel expression.

For `select priority`, the compiler must emit a warning about potential starvation of lower-priority channels.

The compiler should verify that `select` statements appear only within function types that permit channel operations (`flow`, `coex`, `func`).

### WITHIN Compilation

The compiler must recognize the `within` keyword followed by a duration expression and parse statements until either `else` or `end`/`~`. If `else` is present, parse additional statements until `end`/`~`.

The compiler must reject `within` in `formula` functions, as formulas must be provably terminating.

The compiler should emit helpful diagnostics when a `within` block contains no operations that could reasonably block (pure computation with no channel or async operations), suggesting that the timeout may be unnecessary or incorrectly placed.

### Duration Literals

The lexer should recognize duration suffixes and convert them to millisecond integer values:

| Suffix | Multiplier |
|--------|------------|
| `ms`   | 1          |
| `s`    | 1000       |
| `m`    | 60000      |

For example, `5s` becomes the integer `5000`, and `100ms` remains `100`.

---

## Runtime Requirements

### Channel Infrastructure

The runtime must provide thread-safe channel implementations with the following operations: `send(value)`, `receive() -> value`, `try_receive() -> value?`, `close()`, `is_closed() -> bool`, `len() -> int`.

Channels must support blocking on receive when empty and blocking on send when full (for bounded channels). The runtime must provide a mechanism to wait for any of multiple channels to become ready.

### Timer Infrastructure

The runtime must provide high-resolution timers capable of millisecond-level precision. Timers must be efficiently cancelable. The runtime should use a timer wheel or similar data structure to handle large numbers of concurrent timers efficiently.

### Thread Interruption

The runtime must provide a safe mechanism to interrupt blocked operations when a `within` timeout expires. This includes interrupting channel receive operations, async awaits, and (for cooperative multitasking) yielding during computation.

### Chess Ending Detection

For the default `select` strategy, the runtime must implement livelock detection. The recommended approach monitors thread state transitions, detecting when two or more threads repeatedly attempt operations that interfere with each other. When oscillation exceeds a threshold, one thread is temporarily suspended to break the cycle.

This detection should be tunable (threshold, suspension duration) at the runtime configuration level. Applications that use explicit strategies (`fair`, `random`, `priority`) should not incur chess ending detection overhead.

---

## Testing Requirements

Implementations must pass the following test categories:

**SELECT correctness:** Verify that `select fair` provides round-robin ordering. Verify that `select random` selects among ready channels without systematic bias. Verify that `select priority` always selects the first ready channel in source order. Verify that `select timeout` returns after the specified duration when no channels are ready.

**WITHIN correctness:** Verify that blocks completing before timeout skip the else clause. Verify that else handlers execute when timeout occurs. Verify that panic occurs when timeout happens without an else handler. Verify that nested timeouts behave correctly.

**Interaction tests:** Verify that `within` correctly interrupts blocked `select` operations. Verify that `select timeout` inside `within` respects both timeouts (the earlier one fires).

**Stress tests:** Verify fairness guarantees under high contention. Verify that chess ending detection resolves constructed livelock scenarios. Verify that timer infrastructure handles thousands of concurrent `within` blocks.

---

## References

This specification derives from the Coex language design documents developed in conversations available at:

- https://claude.ai/chat/b41d5a04-b763-4638-a2e7-6307dfffd3e0 (timeout handling and within doctrine)
- https://claude.ai/chat/ec5fd6ca-9a53-4e85-b675-bbbcbec10bfe (ANTLR4 grammar specification)
- https://claude.ai/chat/61bd1b5b-17b7-439f-a29b-53a58909db9b (select strategies and livelock analysis)
- https://claude.ai/chat/d6f7ec1f-c57f-400a-a353-30e55b264815 (function type keywords)
