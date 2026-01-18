# Implementation Prompt: Phase 2, Step 7
# Channel Type Inference

## Objective

Implement compiler analysis that determines whether a channel needs TaskChannel (lightweight, task-only) or ThreadChannel (mutex-protected, crosses thread-task boundary).

## Prerequisites

- Phase 2, Steps 5-6 complete (both channel types working)
- Read `coex-task-system-spec.md` section 7.2 (Two Implementations)
- Understand escape analysis concepts

## Test-First Methodology

**Write all tests before implementing.** Type inference must be conservative — incorrectly using TaskChannel for a thread-crossing channel causes races.

## Invariants to Test

### Invariant 1: Pure Task Context → TaskChannel

```coex
task inner(ch: Channel<int>) -> void
    ch.send(42)
~

task outer() -> int
    ch: Channel<int> = Channel.new()  # Created in task
    inner(ch)                          # Passed only to tasks
    return ch.receive()
~

func main() -> int
    print(outer())
    return 0
~
```
Expected: Uses TaskChannel (lightweight path)
Expected output: `42`

### Invariant 2: Created in Func → ThreadChannel

```coex
task worker(ch: Channel<int>) -> void
    ch.send(100)
~

func main() -> int
    ch: Channel<int> = Channel.new()  # Created in func (main)
    worker(ch)
    result = ch.receive()              # Received in func
    print(result)
    return 0
~
```
Expected: Uses ThreadChannel (main could access concurrently)
Expected output: `100`

### Invariant 3: Passed to Thread → ThreadChannel

```coex
task producer(ch: Channel<int>) -> void
    ch.send(50)
~

thread consumer(ch: Channel<int>) -> int
    return ch.receive()
~

task coordinator() -> int
    ch: Channel<int> = Channel.new()  # Created in task
    producer(ch)
    return consumer(ch)               # Passed to thread!
~

func main() -> int
    print(coordinator())
    return 0
~
```
Expected: Uses ThreadChannel (escapes to thread)
Expected output: `50`

### Invariant 4: Stored in Data Structure → ThreadChannel (Conservative)

```coex
type ChannelHolder:
    ch: Channel<int>
~

task user(holder: ChannelHolder) -> void
    holder.ch.send(75)
~

func main() -> int
    ch: Channel<int> = Channel.new()
    holder = ChannelHolder(ch)
    user(holder)
    result = ch.receive()
    print(result)
    return 0
~
```
Expected: Uses ThreadChannel (stored in struct, could escape)
Expected output: `75`

### Invariant 5: Returned from Task → Depends on Caller

```coex
task make_channel() -> Channel<int>
    return Channel.new()
~

task pure_user() -> int
    ch = make_channel()
    ch.send(1)
    return ch.receive()
~

func main() -> int
    print(pure_user())
    return 0
~
```
Expected: Could be TaskChannel if stays in task context
Expected output: `1`

### Invariant 6: Multiple Uses, Any Thread → ThreadChannel

```coex
task task_user(ch: Channel<int>) -> void
    ch.send(10)
~

thread thread_user(ch: Channel<int>) -> void
    ch.send(20)
~

func main() -> int
    ch: Channel<int> = Channel.new()
    task_user(ch)
    thread_user(ch)  # Thread touches it!
    a = ch.receive()
    b = ch.receive()
    print(a + b)
    return 0
~
```
Expected: Uses ThreadChannel
Expected output: `30`

### Invariant 7: Channel in Closure/Lambda → Conservative

```coex
task with_closure() -> int
    ch: Channel<int> = Channel.new()
    
    # Channel captured by lambda
    sender = task() => ch.send(99)
    sender()
    
    return ch.receive()
~

func main() -> int
    print(with_closure())
    return 0
~
```
Expected: Needs analysis of closure context
Expected output: `99`

### Invariant 8: Conditional Escape → ThreadChannel

```coex
task maybe_escape(ch: Channel<int>, escape: bool) -> void
    if escape
        thread_helper(ch)  # Might escape to thread
    ~
    ch.send(1)
~

thread thread_helper(ch: Channel<int>) -> void
    ch.send(2)
~

func main() -> int
    ch: Channel<int> = Channel.new()
    maybe_escape(ch, false)
    print(ch.receive())
    return 0
~
```
Expected: Uses ThreadChannel (might escape on some paths)
Expected output: `1`

## Analysis Algorithm

### Step 1: Build Channel Flow Graph

Track where each channel can flow:

```python
@dataclass
class ChannelInfo:
    creation_site: ASTNode
    creation_context: FunctionKind  # task, thread, func
    flows_to: Set[FlowTarget]
    
@dataclass
class FlowTarget:
    kind: str  # 'call_arg', 'return', 'store_field', 'closure_capture'
    target_context: FunctionKind  # Context of target
    node: ASTNode
```

### Step 2: Determine Escape Points

A channel "escapes" task context if it:
- Is created in func/thread context
- Is passed as argument to thread/func
- Is stored in a data structure (conservative)
- Is returned to func/thread caller
- Is captured by a closure that escapes

```python
def escapes_task_context(channel_info: ChannelInfo) -> bool:
    # Created outside task context
    if channel_info.creation_context in (FUNC, THREAD):
        return True
    
    # Flows to non-task context
    for flow in channel_info.flows_to:
        if flow.target_context in (FUNC, THREAD):
            return True
        if flow.kind == 'store_field':
            return True  # Conservative
    
    return False
```

### Step 3: Propagate Through Calls

If a task passes a channel to another task, analyze transitively:

```python
def analyze_transitive_flows(channel: ChannelInfo, visited: Set):
    if channel in visited:
        return
    visited.add(channel)
    
    for flow in channel.flows_to:
        if flow.kind == 'call_arg':
            callee = resolve_callee(flow.node)
            param_channel = get_parameter_channel(callee, flow.arg_index)
            if param_channel:
                # Merge flows
                channel.flows_to.update(param_channel.flows_to)
                analyze_transitive_flows(param_channel, visited)
```

### Step 4: Mark Channel Types

After analysis, mark each channel creation site:

```python
def determine_channel_type(channel_info: ChannelInfo) -> ChannelType:
    if escapes_task_context(channel_info):
        return ThreadChannel
    else:
        return TaskChannel
```

## Implementation Steps

### Step 1: Create Channel Analysis Pass

Create `channel_analysis.py`:

```python
"""
Analyze channel usage to determine TaskChannel vs ThreadChannel.
"""

from dataclasses import dataclass, field
from typing import Set, Dict, List
from ast_nodes import *

@dataclass
class ChannelFlowInfo:
    """Information about a channel's creation and usage."""
    creation_node: ASTNode
    creation_function: str
    creation_kind: FunctionKind
    escapes: bool = False
    escape_reason: str = ""
    flows_to_threads: bool = False
    flows_to_funcs: bool = False
    stored_in_struct: bool = False

class ChannelAnalyzer(ASTVisitor):
    def __init__(self):
        self.channels: Dict[int, ChannelFlowInfo] = {}  # node_id -> info
        self.current_function_kind: FunctionKind = FUNC
        
    def analyze(self, program: Program) -> Dict[int, ChannelFlowInfo]:
        self.visit(program)
        self.propagate_flows()
        self.determine_escapes()
        return self.channels
```

### Step 2: Track Channel Creation

```python
def visit_channel_new(self, node: ChannelNew):
    """Record channel creation site and context."""
    info = ChannelFlowInfo(
        creation_node=node,
        creation_function=self.current_function,
        creation_kind=self.current_function_kind
    )
    
    # Created outside task → escapes immediately
    if self.current_function_kind in (FUNC, THREAD):
        info.escapes = True
        info.escape_reason = f"Created in {self.current_function_kind} context"
    
    self.channels[id(node)] = info
```

### Step 3: Track Channel Flows

```python
def visit_call(self, node: CallExpr):
    """Track channels passed as arguments."""
    callee_kind = self.get_callee_kind(node.callee)
    
    for i, arg in enumerate(node.args):
        if self.is_channel_expr(arg):
            channel_info = self.get_channel_info(arg)
            if channel_info:
                if callee_kind == THREAD:
                    channel_info.flows_to_threads = True
                elif callee_kind == FUNC:
                    channel_info.flows_to_funcs = True

def visit_field_assign(self, node: FieldAssign):
    """Track channels stored in data structures."""
    if self.is_channel_expr(node.value):
        channel_info = self.get_channel_info(node.value)
        if channel_info:
            channel_info.stored_in_struct = True
```

### Step 4: Determine Final Types

```python
def determine_escapes(self):
    """Mark channels that escape task context."""
    for channel_id, info in self.channels.items():
        if info.flows_to_threads:
            info.escapes = True
            info.escape_reason = "Passed to thread"
        elif info.flows_to_funcs:
            info.escapes = True
            info.escape_reason = "Passed to func"
        elif info.stored_in_struct:
            info.escapes = True
            info.escape_reason = "Stored in data structure (conservative)"

def get_channel_type(self, node: ASTNode) -> str:
    """Get the channel implementation type for a creation site."""
    info = self.channels.get(id(node))
    if info and not info.escapes:
        return "TaskChannel"
    else:
        return "ThreadChannel"  # Default to safe option
```

### Step 5: Integrate with Code Generator

```python
def _generate_channel_new(self, node: ChannelNew):
    """Generate appropriate channel type based on analysis."""
    channel_type = self.channel_analysis.get_channel_type(node)
    
    if channel_type == "TaskChannel":
        return self._generate_task_channel_new(node)
    else:
        return self._generate_thread_channel_new(node)

def _generate_channel_send(self, node: ChannelSend):
    """Generate appropriate send based on channel type."""
    channel_type = self.get_channel_type(node.channel)
    
    if channel_type == "TaskChannel":
        return self._generate_task_channel_send(node)
    else:
        return self._generate_thread_channel_send(node)
```

## Test Files to Create

Create `tests/test_channel_inference.py`:

```python
import pytest

class TestChannelInference:
    """Tests for channel type inference"""
    
    def test_pure_task_context(self, expect_output):
        """Channel staying in task context uses TaskChannel"""
        expect_output('''
task inner(ch: Channel<int>) -> void
    ch.send(42)
~

task outer() -> int
    ch: Channel<int> = Channel.new()
    inner(ch)
    return ch.receive()
~

func main() -> int
    print(outer())
    return 0
~
''', "42\n")

    def test_created_in_func(self, expect_output):
        """Channel created in func uses ThreadChannel"""
        expect_output('''
task worker(ch: Channel<int>) -> void
    ch.send(100)
~

func main() -> int
    ch: Channel<int> = Channel.new()
    worker(ch)
    print(ch.receive())
    return 0
~
''', "100\n")

    def test_passed_to_thread(self, expect_output):
        """Channel passed to thread uses ThreadChannel"""
        expect_output('''
task producer(ch: Channel<int>) -> void
    ch.send(50)
~

thread consumer(ch: Channel<int>) -> int
    return ch.receive()
~

task test() -> int
    ch: Channel<int> = Channel.new()
    producer(ch)
    return consumer(ch)
~

func main() -> int
    print(test())
    return 0
~
''', "50\n")

    def test_stored_in_struct(self, expect_output):
        """Channel stored in struct uses ThreadChannel (conservative)"""
        expect_output('''
type Holder:
    ch: Channel<int>
~

task user(h: Holder) -> void
    h.ch.send(75)
~

func main() -> int
    ch: Channel<int> = Channel.new()
    h = Holder(ch)
    user(h)
    print(ch.receive())
    return 0
~
''', "75\n")

    def test_conditional_thread_escape(self, expect_output):
        """Channel that might escape uses ThreadChannel"""
        expect_output('''
thread helper(ch: Channel<int>) -> void
    ch.send(2)
~

task maybe_escape(ch: Channel<int>, escape: bool) -> void
    if escape
        helper(ch)
    else
        ch.send(1)
    ~
~

func main() -> int
    ch: Channel<int> = Channel.new()
    maybe_escape(ch, false)
    print(ch.receive())
    return 0
~
''', "1\n")


class TestChannelInferenceCorrectness:
    """Verify inference doesn't break correctness"""
    
    def test_task_channel_concurrent_access(self, expect_output):
        """TaskChannel handles concurrent task access"""
        expect_output('''
task sender(ch: Channel<int>, n: int) -> void
    for i in 0..n
        ch.send(i)
    ~
~

task receiver(ch: Channel<int>, n: int) -> int
    total = 0
    for i in 0..n
        total = total + ch.receive()
    ~
    return total
~

task test() -> int
    ch: Channel<int> = Channel.new()
    sender(ch, 100)
    return receiver(ch, 100)
~

func main() -> int
    print(test())
    return 0
~
''', "4950\n")

    def test_thread_channel_mixed_access(self, expect_output):
        """ThreadChannel handles mixed task/thread access"""
        expect_output('''
task task_sender(ch: Channel<int>) -> void
    ch.send(10)
~

thread thread_sender(ch: Channel<int>) -> void
    ch.send(20)
~

func main() -> int
    ch: Channel<int> = Channel.new()
    task_sender(ch)
    thread_sender(ch)
    a = ch.receive()
    b = ch.receive()
    print(a + b)
    return 0
~
''', "30\n")
```

## Verification

```bash
python3 -m pytest tests/test_channel_inference.py -v
```

## Success Criteria

1. All tests pass
2. Task-only channels get TaskChannel (verified via debug output or inspection)
3. Escaping channels get ThreadChannel
4. Conservative: when in doubt, use ThreadChannel
5. No races from incorrect inference

## Notes

- Conservative is correct: using ThreadChannel when TaskChannel would suffice is slower but safe
- Using TaskChannel when ThreadChannel is needed causes data races
- Start conservative, optimize later with more precise analysis
- Consider adding debug mode that reports which channel type was chosen
