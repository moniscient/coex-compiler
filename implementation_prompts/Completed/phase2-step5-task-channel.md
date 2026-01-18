# Implementation Prompt: Phase 2, Step 5
# TaskChannel Implementation

## Objective

Implement lightweight channels for task-to-task communication. TaskChannels use scheduler-managed wait queues with no mutex overhead.

## Prerequisites

- Phase 2, Step 4 complete (task-to-task execution working)
- Read `coex-task-system-spec.md` section 7 (Channels)
- Understand the scheduler's task parking mechanism

## Test-First Methodology

**Write all tests before implementing.** Channels have subtle concurrency semantics.

## Invariants to Test

### Invariant 1: Basic Send and Receive

```coex
task sender(ch: Channel<int>) -> void
    ch.send(42)
~

task receiver(ch: Channel<int>) -> int
    return ch.receive()
~

task test() -> int
    ch: Channel<int> = Channel.new()
    sender(ch)
    return receiver(ch)
~

func main() -> int
    print(test())
    return 0
~
```
Expected output: `42`

### Invariant 2: Multiple Values Buffered

```coex
task producer(ch: Channel<int>) -> void
    ch.send(1)
    ch.send(2)
    ch.send(3)
~

task consumer(ch: Channel<int>) -> int
    a = ch.receive()
    b = ch.receive()
    c = ch.receive()
    return a + b + c
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
```
Expected output: `6`

### Invariant 3: FIFO Order Preserved

```coex
task sender(ch: Channel<int>) -> void
    ch.send(1)
    ch.send(2)
    ch.send(3)
    ch.send(4)
    ch.send(5)
~

task receiver(ch: Channel<int>) -> void
    for i in 0..5
        x = ch.receive()
        print(x)
    ~
~

task test() -> int
    ch: Channel<int> = Channel.new()
    sender(ch)
    receiver(ch)
    return 0
~

func main() -> int
    test()
    return 0
~
```
Expected output:
```
1
2
3
4
5
```

### Invariant 4: Receive Blocks Until Data Available

```coex
task slow_sender(ch: Channel<int>) -> void
    total = 0
    for i in 0..1000
        total = total + i
    ~
    ch.send(total)
~

task eager_receiver(ch: Channel<int>) -> int
    return ch.receive()
~

task test() -> int
    ch: Channel<int> = Channel.new()
    result = eager_receiver(ch)
    slow_sender(ch)
    return result
~

func main() -> int
    print(test())
    return 0
~
```
Expected output: `499500`

### Invariant 5: Send Wakes Exactly One Receiver

```coex
task receiver(ch: Channel<int>, id: int) -> int
    x = ch.receive()
    return x + id
~

task test() -> int
    ch: Channel<int> = Channel.new()
    r1 = receiver(ch, 100)
    r2 = receiver(ch, 200)
    r3 = receiver(ch, 300)
    ch.send(1)
    ch.send(2)
    ch.send(3)
    return r1 + r2 + r3
~

func main() -> int
    print(test())
    return 0
~
```
Expected output: `606` (order may vary but sum is constant)

### Invariant 6: Complex Types Through Channel

```coex
task send_list(ch: Channel<List<int>>) -> void
    ch.send([1, 2, 3, 4, 5])
~

task receive_list(ch: Channel<List<int>>) -> int
    data = ch.receive()
    return data.len()
~

task test() -> int
    ch: Channel<List<int>> = Channel.new()
    send_list(ch)
    return receive_list(ch)
~

func main() -> int
    print(test())
    return 0
~
```
Expected output: `5`

### Invariant 7: Unbounded Buffer Grows

```coex
task mass_sender(ch: Channel<int>, count: int) -> void
    for i in 0..count
        ch.send(i)
    ~
~

task mass_receiver(ch: Channel<int>, count: int) -> int
    total = 0
    for i in 0..count
        x = ch.receive()
        total = total + x
    ~
    return total
~

task test() -> int
    ch: Channel<int> = Channel.new()
    mass_sender(ch, 10000)
    return mass_receiver(ch, 10000)
~

func main() -> int
    print(test())
    return 0
~
```
Expected output: `49995000`

### Invariant 8: Multiple Senders, One Receiver

```coex
task sender(ch: Channel<int>, value: int) -> void
    ch.send(value)
~

task collector(ch: Channel<int>) -> int
    a = ch.receive()
    b = ch.receive()
    c = ch.receive()
    return a + b + c
~

task test() -> int
    ch: Channel<int> = Channel.new()
    sender(ch, 10)
    sender(ch, 20)
    sender(ch, 30)
    return collector(ch)
~

func main() -> int
    print(test())
    return 0
~
```
Expected output: `60`

### Invariant 9: Channel Passed as Parameter

```coex
task worker(ch: Channel<int>, input: int) -> void
    ch.send(input * 2)
~

task coordinator() -> int
    ch: Channel<int> = Channel.new()
    worker(ch, 10)
    worker(ch, 20)
    a = ch.receive()
    b = ch.receive()
    return a + b
~

func main() -> int
    print(coordinator())
    return 0
~
```
Expected output: `60`

### Invariant 10: Channel in Loop

```coex
task producer(ch: Channel<int>, count: int) -> void
    for i in 0..count
        ch.send(i * i)
    ~
~

task consumer(ch: Channel<int>, count: int) -> int
    total = 0
    for i in 0..count
        x = ch.receive()
        total = total + x
    ~
    return total
~

task test() -> int
    ch: Channel<int> = Channel.new()
    producer(ch, 5)
    return consumer(ch, 5)
~

func main() -> int
    print(test())
    return 0
~
```
Expected output: `30` (0 + 1 + 4 + 9 + 16)

## Implementation Steps

### Step 1: Define TaskChannel Data Structure

```python
TASK_CHANNEL_TYPE = """
%TaskChannel = type {
    %RingBuffer*,        ; buffer (unbounded, grows as needed)
    %WaitQueue*          ; recv_waiters (tasks blocked on receive)
}

%RingBuffer = type {
    i64,                 ; capacity
    i64,                 ; head (read position)
    i64,                 ; tail (write position)
    i64,                 ; count
    [0 x i64]            ; data (value handles)
}

%WaitQueue = type {
    i64,                 ; count
    %WaitNode*           ; head
    %WaitNode*           ; tail
}

%WaitNode = type {
    i64,                 ; task_id
    %WaitNode*           ; next
}
"""
```

### Step 2: Implement Channel Creation

```python
def generate_channel_new(self, elem_type):
    """
    Create a new TaskChannel:
    1. Allocate channel struct on heap
    2. Allocate initial buffer (capacity 16)
    3. Initialize empty wait queue
    4. Return channel handle
    """
    # Allocate channel
    channel = gc_alloc(sizeof(TaskChannel))
    
    # Allocate buffer with initial capacity
    buffer = gc_alloc(sizeof(RingBuffer) + 16 * sizeof(i64))
    buffer.capacity = 16
    buffer.head = 0
    buffer.tail = 0
    buffer.count = 0
    
    # Initialize wait queue
    wait_queue = gc_alloc(sizeof(WaitQueue))
    wait_queue.count = 0
    wait_queue.head = null
    wait_queue.tail = null
    
    channel.buffer = buffer
    channel.recv_waiters = wait_queue
    
    return channel
```

### Step 3: Implement Send Operation

```python
def generate_channel_send(self):
    """
    Send value to channel (never blocks with unbounded buffer):
    
    1. Check if any receivers are waiting
    2. If receiver waiting:
       - Pop receiver from wait queue
       - Set receiver's pending_value directly
       - Push receiver to ready queue
    3. If no receiver waiting:
       - Add value to buffer (grow if needed)
    """
    # Check for waiting receiver
    if channel.recv_waiters.count > 0:
        # Direct handoff - don't buffer
        waiter_id = wait_queue_pop(channel.recv_waiters)
        waiter = suspended_tasks[waiter_id]
        waiter.pending_value = value
        ready_queue_push(waiter)
    else:
        # Buffer the value
        buffer_push(channel.buffer, value)
```

### Step 4: Implement Receive Operation

```python
def generate_channel_receive(self):
    """
    Receive value from channel:
    
    1. Check if buffer has data
    2. If data available:
       - Pop from buffer
       - Continue execution with value (no suspend)
    3. If buffer empty:
       - Add task to recv_waiters
       - Suspend (return TaskResult.Receive)
    """
    if channel.buffer.count > 0:
        value = buffer_pop(channel.buffer)
        # Continue with value - no suspension
        return value
    else:
        # Must suspend
        wait_queue_push(channel.recv_waiters, current_task_id)
        return TaskResult.Receive(updated_frame, channel)
```

### Step 5: Integrate with State Machine

Channel receive is a suspension point. The state machine must handle it:

```python
# In generated step function
case N:
    # ... code before receive ...
    
    # Check buffer first
    if channel.buffer.count > 0:
        value = buffer_pop(channel.buffer)
        frame.received_value = value
        # Fall through to next state
        goto case N+1
    else:
        # Must suspend
        return TaskResult.Receive(
            frame with { state: N+1 },
            channel
        )

case N+1:
    # Resumed with value in resolved parameter
    frame.received_value = resolved
    # ... code after receive ...
```

### Step 6: Implement Scheduler Integration

```python
def handle_task_result_receive(task, frame, channel):
    """
    Handle TaskResult.Receive from scheduler:
    
    1. Double-check buffer (might have data now due to race)
    2. If data: resume immediately
    3. If empty: park in wait queue
    """
    if channel.buffer.count > 0:
        # Data arrived between check and suspend
        value = buffer_pop(channel.buffer)
        task.pending_value = value
        task.frame = frame
        ready_queue_push(task)
    else:
        # Park task
        wait_queue_push(channel.recv_waiters, task.id)
        suspended_tasks[task.id] = SuspendedTask(
            frame=frame,
            step_fn=task.step_fn,
            waiter=task.waiter,
            pending_value=None
        )
```

### Step 7: Implement Buffer Operations

```python
def buffer_push(buffer, value):
    """Push value, growing buffer if needed."""
    if buffer.count == buffer.capacity:
        buffer = grow_buffer(buffer)
    
    buffer.data[buffer.tail] = value
    buffer.tail = (buffer.tail + 1) % buffer.capacity
    buffer.count += 1

def buffer_pop(buffer):
    """Pop value from buffer (assumes count > 0)."""
    value = buffer.data[buffer.head]
    buffer.head = (buffer.head + 1) % buffer.capacity
    buffer.count -= 1
    return value

def grow_buffer(buffer):
    """Double buffer capacity, copying existing data."""
    new_capacity = buffer.capacity * 2
    new_buffer = allocate(sizeof(RingBuffer) + new_capacity * sizeof(i64))
    new_buffer.capacity = new_capacity
    new_buffer.count = buffer.count
    new_buffer.head = 0
    new_buffer.tail = buffer.count
    
    # Copy data to contiguous region
    for i in 0..buffer.count:
        old_idx = (buffer.head + i) % buffer.capacity
        new_buffer.data[i] = buffer.data[old_idx]
    
    return new_buffer
```

### Step 8: Implement Wait Queue Operations

```python
def wait_queue_push(queue, task_id):
    """Add task to wait queue (FIFO)."""
    node = allocate(sizeof(WaitNode))
    node.task_id = task_id
    node.next = null
    
    if queue.tail == null:
        queue.head = node
        queue.tail = node
    else:
        queue.tail.next = node
        queue.tail = node
    
    queue.count += 1

def wait_queue_pop(queue):
    """Remove and return first task from queue."""
    node = queue.head
    queue.head = node.next
    if queue.head == null:
        queue.tail = null
    queue.count -= 1
    return node.task_id
```

## Test Files to Create

Create `tests/test_task_channel.py`:

```python
import pytest

class TestTaskChannelBasic:
    """Basic TaskChannel operations"""
    
    def test_send_then_receive(self, expect_output):
        expect_output('''
task sender(ch: Channel<int>) -> void
    ch.send(42)
~

task receiver(ch: Channel<int>) -> int
    return ch.receive()
~

task test() -> int
    ch: Channel<int> = Channel.new()
    sender(ch)
    return receiver(ch)
~

func main() -> int
    print(test())
    return 0
~
''', "42\n")

    def test_multiple_values(self, expect_output):
        expect_output('''
task producer(ch: Channel<int>) -> void
    ch.send(1)
    ch.send(2)
    ch.send(3)
~

task consumer(ch: Channel<int>) -> int
    a = ch.receive()
    b = ch.receive()
    c = ch.receive()
    return a + b + c
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
''', "6\n")

    def test_fifo_order(self, expect_output):
        expect_output('''
task sender(ch: Channel<int>) -> void
    ch.send(1)
    ch.send(2)
    ch.send(3)
~

task receiver(ch: Channel<int>) -> void
    for i in 0..3
        print(ch.receive())
    ~
~

task test() -> int
    ch: Channel<int> = Channel.new()
    sender(ch)
    receiver(ch)
    return 0
~

func main() -> int
    test()
    return 0
~
''', "1\n2\n3\n")


class TestTaskChannelBlocking:
    """Tests for blocking/suspension behavior"""
    
    def test_receive_waits_for_send(self, expect_output):
        expect_output('''
task slow_sender(ch: Channel<int>) -> void
    total = 0
    for i in 0..100
        total = total + i
    ~
    ch.send(total)
~

task receiver(ch: Channel<int>) -> int
    return ch.receive()
~

task test() -> int
    ch: Channel<int> = Channel.new()
    result = receiver(ch)
    slow_sender(ch)
    return result
~

func main() -> int
    print(test())
    return 0
~
''', "4950\n")

    def test_multiple_waiters(self, expect_output):
        expect_output('''
task receiver(ch: Channel<int>, id: int) -> int
    x = ch.receive()
    return x + id
~

task test() -> int
    ch: Channel<int> = Channel.new()
    r1 = receiver(ch, 100)
    r2 = receiver(ch, 200)
    ch.send(1)
    ch.send(2)
    return r1 + r2
~

func main() -> int
    print(test())
    return 0
~
''', "303\n")


class TestTaskChannelTypes:
    """Tests for different value types"""
    
    def test_list_through_channel(self, expect_output):
        expect_output('''
task send_list(ch: Channel<List<int>>) -> void
    ch.send([1, 2, 3])
~

task recv_list(ch: Channel<List<int>>) -> int
    data = ch.receive()
    return data.len()
~

task test() -> int
    ch: Channel<List<int>> = Channel.new()
    send_list(ch)
    return recv_list(ch)
~

func main() -> int
    print(test())
    return 0
~
''', "3\n")

    def test_string_through_channel(self, expect_output):
        expect_output('''
task send_str(ch: Channel<string>) -> void
    ch.send("hello")
~

task recv_str(ch: Channel<string>) -> string
    return ch.receive()
~

task test() -> string
    ch: Channel<string> = Channel.new()
    send_str(ch)
    return recv_str(ch)
~

func main() -> int
    s = test()
    print(s)
    return 0
~
''', "hello\n")


class TestTaskChannelStress:
    """Stress tests"""
    
    def test_many_values(self, expect_output):
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
    sender(ch, 1000)
    return receiver(ch, 1000)
~

func main() -> int
    print(test())
    return 0
~
''', "499500\n")

    def test_ping_pong(self, expect_output):
        expect_output('''
task ping(to_pong: Channel<int>, from_pong: Channel<int>, n: int) -> int
    for i in 0..n
        to_pong.send(i)
        x = from_pong.receive()
    ~
    return n
~

task pong(from_ping: Channel<int>, to_ping: Channel<int>, n: int) -> int
    for i in 0..n
        x = from_ping.receive()
        to_ping.send(x + 1)
    ~
    return n
~

task test() -> int
    ch1: Channel<int> = Channel.new()
    ch2: Channel<int> = Channel.new()
    p = ping(ch1, ch2, 10)
    q = pong(ch1, ch2, 10)
    return p + q
~

func main() -> int
    print(test())
    return 0
~
''', "20\n")
```

## Verification

```bash
python3 -m pytest tests/test_task_channel.py -v
```

## Success Criteria

1. All tests pass
2. Send never blocks (unbounded buffer)
3. Receive blocks only when buffer empty
4. FIFO order preserved
5. Wake exactly one waiter per send
6. Complex types work through channels
7. No memory leaks (channels are GC-traced)

## Notes

- TaskChannel is for task-to-task only; ThreadChannel comes in Step 6
- Buffer growth is amortized O(1) per operation
- Wait queue is FIFO for fairness
- Channel handle is a GC-managed heap value
