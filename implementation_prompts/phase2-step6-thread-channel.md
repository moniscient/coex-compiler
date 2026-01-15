# Implementation Prompt: Phase 2, Step 6
# ThreadChannel Implementation

## Objective

Implement channels that can cross the thread-task boundary. ThreadChannels use mutex/condvar for synchronization when threads are involved.

## Prerequisites

- Phase 2, Step 5 complete (TaskChannel working)
- Read `coex-task-system-spec.md` section 7 (Channels)
- Understand pthread mutex and condition variable usage

## Test-First Methodology

**Write all tests before implementing.** Thread-task interaction has subtle synchronization requirements.

## Invariants to Test

### Invariant 1: Func Sends to Task

```coex
task receiver(ch: Channel<int>) -> int
    return ch.receive()
~

func main() -> int
    ch: Channel<int> = Channel.new()
    recv_result = receiver(ch)
    ch.send(42)  # Func sending
    print(recv_result)
    return 0
~
```
Expected output: `42`

### Invariant 2: Task Sends to Func

```coex
task sender(ch: Channel<int>) -> void
    ch.send(100)
~

func main() -> int
    ch: Channel<int> = Channel.new()
    sender(ch)
    result = ch.receive()  # Func receiving
    print(result)
    return 0
~
```
Expected output: `100`

### Invariant 3: Thread Sends to Task

```coex
task receiver(ch: Channel<int>) -> int
    return ch.receive()
~

thread sender_thread(ch: Channel<int>) -> void
    ch.send(77)
~

func main() -> int
    ch: Channel<int> = Channel.new()
    recv_result = receiver(ch)
    sender_thread(ch)
    print(recv_result)
    return 0
~
```
Expected output: `77`

### Invariant 4: Task Sends to Thread

```coex
task sender(ch: Channel<int>) -> void
    ch.send(88)
~

thread receiver_thread(ch: Channel<int>) -> int
    return ch.receive()
~

func main() -> int
    ch: Channel<int> = Channel.new()
    sender(ch)
    result = receiver_thread(ch)
    print(result)
    return 0
~
```
Expected output: `88`

### Invariant 5: Multiple Threads and Tasks

```coex
task task_sender(ch: Channel<int>, val: int) -> void
    ch.send(val)
~

thread thread_sender(ch: Channel<int>, val: int) -> void
    ch.send(val)
~

func main() -> int
    ch: Channel<int> = Channel.new()
    task_sender(ch, 10)
    thread_sender(ch, 20)
    task_sender(ch, 30)
    
    a = ch.receive()
    b = ch.receive()
    c = ch.receive()
    print(a + b + c)
    return 0
~
```
Expected output: `60`

### Invariant 6: Thread Blocks on Empty Channel

```coex
task delayed_sender(ch: Channel<int>) -> void
    total = 0
    for i in 0..10000
        total = total + i
    ~
    ch.send(total)
~

thread blocking_receiver(ch: Channel<int>) -> int
    return ch.receive()  # Should block until task sends
~

func main() -> int
    ch: Channel<int> = Channel.new()
    result = blocking_receiver(ch)
    delayed_sender(ch)
    print(result)
    return 0
~
```
Expected output: `49995000`

### Invariant 7: Task Wakes Blocked Thread

```coex
thread waiter(ch: Channel<int>) -> int
    return ch.receive()
~

task notifier(ch: Channel<int>) -> void
    ch.send(999)
~

func main() -> int
    ch: Channel<int> = Channel.new()
    result = waiter(ch)
    notifier(ch)
    print(result)
    return 0
~
```
Expected output: `999`

### Invariant 8: Thread Wakes Blocked Task

```coex
task waiter(ch: Channel<int>) -> int
    return ch.receive()
~

thread notifier(ch: Channel<int>) -> void
    ch.send(888)
~

func main() -> int
    ch: Channel<int> = Channel.new()
    result = waiter(ch)
    notifier(ch)
    print(result)
    return 0
~
```
Expected output: `888`

### Invariant 9: FIFO Order Across Boundary

```coex
thread sender(ch: Channel<int>) -> void
    ch.send(1)
    ch.send(2)
    ch.send(3)
~

task receiver(ch: Channel<int>) -> void
    for i in 0..3
        print(ch.receive())
    ~
~

func main() -> int
    ch: Channel<int> = Channel.new()
    sender(ch)
    receiver(ch)
    return 0
~
```
Expected output:
```
1
2
3
```

### Invariant 10: High Contention Across Boundary

```coex
task task_worker(ch: Channel<int>, count: int) -> void
    for i in 0..count
        ch.send(i)
    ~
~

thread thread_worker(ch: Channel<int>, count: int) -> void
    for i in 0..count
        ch.send(i + 1000)
    ~
~

func main() -> int
    ch: Channel<int> = Channel.new()
    task_worker(ch, 100)
    thread_worker(ch, 100)
    
    total = 0
    for i in 0..200
        total = total + ch.receive()
    ~
    print(total)
    return 0
~
```
Expected output: `104950` (sum 0..99 + sum 1000..1099)

## Implementation Steps

### Step 1: Define ThreadChannel Data Structure

```python
THREAD_CHANNEL_TYPE = """
%ThreadChannel = type {
    %RingBuffer*,            ; buffer
    %WaitQueue*,             ; recv_waiters (mixed task/thread)
    %pthread_mutex_t*,       ; mutex for synchronization
    %pthread_cond_t*         ; condvar for thread wakeup
}

%MixedWaitNode = type {
    i64,                     ; waiter_id
    i1,                      ; is_thread (true = thread, false = task)
    %MixedWaitNode*          ; next
}
"""
```

### Step 2: Implement Channel Creation

```python
def generate_thread_channel_new(self, elem_type):
    """
    Create ThreadChannel with mutex/condvar:
    1. Allocate channel struct
    2. Allocate and init buffer
    3. Allocate and init wait queue
    4. Allocate and init mutex
    5. Allocate and init condvar
    """
    channel = gc_alloc(sizeof(ThreadChannel))
    
    # Buffer (same as TaskChannel)
    buffer = gc_alloc(sizeof(RingBuffer) + 16 * sizeof(i64))
    buffer.capacity = 16
    buffer.head = 0
    buffer.tail = 0
    buffer.count = 0
    
    # Wait queue
    wait_queue = gc_alloc(sizeof(WaitQueue))
    wait_queue.count = 0
    wait_queue.head = null
    wait_queue.tail = null
    
    # Mutex
    mutex = gc_alloc(sizeof(pthread_mutex_t))
    pthread_mutex_init(mutex, null)
    
    # Condvar
    cond = gc_alloc(sizeof(pthread_cond_t))
    pthread_cond_init(cond, null)
    
    channel.buffer = buffer
    channel.recv_waiters = wait_queue
    channel.mutex = mutex
    channel.cond = cond
    
    return channel
```

### Step 3: Implement Thread-Side Send

```python
def generate_thread_channel_send(self):
    """
    Send from thread/func context:
    1. Lock mutex
    2. Add value to buffer
    3. Check for waiters
    4. If task waiter: scheduler wake
    5. If thread waiter: condvar signal
    6. Unlock mutex
    """
    pthread_mutex_lock(channel.mutex)
    
    buffer_push(channel.buffer, value)
    
    if channel.recv_waiters.count > 0:
        waiter = wait_queue_pop(channel.recv_waiters)
        if waiter.is_thread:
            # Signal condvar - thread will wake and grab value
            pthread_cond_signal(channel.cond)
        else:
            # Wake task via scheduler
            value = buffer_pop(channel.buffer)
            task = suspended_tasks[waiter.waiter_id]
            task.pending_value = value
            scheduler_push_ready(task)
        
    pthread_mutex_unlock(channel.mutex)
```

### Step 4: Implement Thread-Side Receive

```python
def generate_thread_channel_receive(self):
    """
    Receive from thread/func context:
    1. Lock mutex
    2. While buffer empty:
       - Add self to wait queue
       - Wait on condvar (releases mutex while waiting)
    3. Pop value from buffer
    4. Unlock mutex
    5. Return value
    """
    pthread_mutex_lock(channel.mutex)
    
    while channel.buffer.count == 0:
        # Add self to waiters
        wait_queue_push(channel.recv_waiters, pthread_self(), is_thread=true)
        # Wait (atomically releases mutex)
        pthread_cond_wait(channel.cond, channel.mutex)
        # Mutex re-acquired here
    
    value = buffer_pop(channel.buffer)
    
    pthread_mutex_unlock(channel.mutex)
    
    return value
```

### Step 5: Implement Task-Side Send (with mutex)

```python
def generate_task_channel_send_threaded(self):
    """
    Send from task context to ThreadChannel:
    1. Lock mutex
    2. Add value to buffer
    3. Check for waiters
    4. Wake appropriately (thread vs task)
    5. Unlock mutex
    6. Continue (send never suspends)
    """
    pthread_mutex_lock(channel.mutex)
    
    buffer_push(channel.buffer, value)
    
    if channel.recv_waiters.count > 0:
        waiter = wait_queue_pop(channel.recv_waiters)
        if waiter.is_thread:
            pthread_cond_signal(channel.cond)
        else:
            value = buffer_pop(channel.buffer)
            task = suspended_tasks[waiter.waiter_id]
            task.pending_value = value
            scheduler_push_ready(task)
    
    pthread_mutex_unlock(channel.mutex)
```

### Step 6: Implement Task-Side Receive (with mutex)

```python
def generate_task_channel_receive_threaded(self):
    """
    Receive from task context on ThreadChannel:
    1. Lock mutex
    2. If buffer has data: pop, unlock, continue
    3. If buffer empty: add to waiters, unlock, suspend
    
    Note: Task cannot hold mutex while suspended!
    Must release mutex before returning TaskResult.Receive
    """
    pthread_mutex_lock(channel.mutex)
    
    if channel.buffer.count > 0:
        value = buffer_pop(channel.buffer)
        pthread_mutex_unlock(channel.mutex)
        return value  # Continue, no suspend
    else:
        # Add to waiters
        wait_queue_push(channel.recv_waiters, current_task_id, is_thread=false)
        pthread_mutex_unlock(channel.mutex)  # MUST unlock before suspend
        return TaskResult.Receive(updated_frame, channel)
```

### Step 7: Handle Task Resume After Wake

When a thread sends and wakes a task:

```python
def thread_send_wake_task(channel, value, task_id):
    """
    Called while holding mutex.
    Thread is sending, task is waiting.
    """
    # Value is already in buffer from send
    # Pop it for direct handoff to task
    task = suspended_tasks.pop(task_id)
    task.pending_value = buffer_pop(channel.buffer)
    
    # Push to scheduler (don't signal condvar - task doesn't use it)
    scheduler_push_ready(task)
```

### Step 8: Handle Thread Wake After Task Send

When a task sends and wakes a thread:

```python
def task_send_wake_thread(channel, value):
    """
    Task is sending, thread is waiting on condvar.
    Task holds mutex.
    """
    # Value is in buffer
    # Signal condvar - thread will wake, reacquire mutex, pop value
    pthread_cond_signal(channel.cond)
    # Thread handles its own value retrieval after waking
```

## Test Files to Create

Create `tests/test_thread_channel.py`:

```python
import pytest

class TestThreadChannelBasic:
    """Basic ThreadChannel operations"""
    
    def test_func_sends_task_receives(self, expect_output):
        expect_output('''
task receiver(ch: Channel<int>) -> int
    return ch.receive()
~

func main() -> int
    ch: Channel<int> = Channel.new()
    result = receiver(ch)
    ch.send(42)
    print(result)
    return 0
~
''', "42\n")

    def test_task_sends_func_receives(self, expect_output):
        expect_output('''
task sender(ch: Channel<int>) -> void
    ch.send(100)
~

func main() -> int
    ch: Channel<int> = Channel.new()
    sender(ch)
    result = ch.receive()
    print(result)
    return 0
~
''', "100\n")


class TestThreadChannelWithThread:
    """ThreadChannel with explicit thread functions"""
    
    def test_thread_sends_task_receives(self, expect_output):
        expect_output('''
task receiver(ch: Channel<int>) -> int
    return ch.receive()
~

thread sender(ch: Channel<int>) -> void
    ch.send(77)
~

func main() -> int
    ch: Channel<int> = Channel.new()
    result = receiver(ch)
    sender(ch)
    print(result)
    return 0
~
''', "77\n")

    def test_task_sends_thread_receives(self, expect_output):
        expect_output('''
task sender(ch: Channel<int>) -> void
    ch.send(88)
~

thread receiver(ch: Channel<int>) -> int
    return ch.receive()
~

func main() -> int
    ch: Channel<int> = Channel.new()
    sender(ch)
    result = receiver(ch)
    print(result)
    return 0
~
''', "88\n")


class TestThreadChannelBlocking:
    """Blocking behavior across boundary"""
    
    def test_thread_blocks_task_wakes(self, expect_output):
        expect_output('''
thread waiter(ch: Channel<int>) -> int
    return ch.receive()
~

task sender(ch: Channel<int>) -> void
    ch.send(999)
~

func main() -> int
    ch: Channel<int> = Channel.new()
    result = waiter(ch)
    sender(ch)
    print(result)
    return 0
~
''', "999\n")

    def test_task_blocks_thread_wakes(self, expect_output):
        expect_output('''
task waiter(ch: Channel<int>) -> int
    return ch.receive()
~

thread sender(ch: Channel<int>) -> void
    ch.send(888)
~

func main() -> int
    ch: Channel<int> = Channel.new()
    result = waiter(ch)
    sender(ch)
    print(result)
    return 0
~
''', "888\n")


class TestThreadChannelOrder:
    """FIFO order across boundary"""
    
    def test_fifo_thread_to_task(self, expect_output):
        expect_output('''
thread sender(ch: Channel<int>) -> void
    ch.send(1)
    ch.send(2)
    ch.send(3)
~

task receiver(ch: Channel<int>) -> void
    for i in 0..3
        print(ch.receive())
    ~
~

func main() -> int
    ch: Channel<int> = Channel.new()
    sender(ch)
    receiver(ch)
    return 0
~
''', "1\n2\n3\n")

    def test_fifo_task_to_thread(self, expect_output):
        expect_output('''
task sender(ch: Channel<int>) -> void
    ch.send(1)
    ch.send(2)
    ch.send(3)
~

thread receiver(ch: Channel<int>) -> void
    for i in 0..3
        print(ch.receive())
    ~
~

func main() -> int
    ch: Channel<int> = Channel.new()
    sender(ch)
    receiver(ch)
    return 0
~
''', "1\n2\n3\n")


class TestThreadChannelStress:
    """Stress tests for ThreadChannel"""
    
    def test_high_volume(self, expect_output):
        expect_output('''
task sender(ch: Channel<int>, n: int) -> void
    for i in 0..n
        ch.send(i)
    ~
~

thread receiver(ch: Channel<int>, n: int) -> int
    total = 0
    for i in 0..n
        total = total + ch.receive()
    ~
    return total
~

func main() -> int
    ch: Channel<int> = Channel.new()
    sender(ch, 1000)
    result = receiver(ch, 1000)
    print(result)
    return 0
~
''', "499500\n")

    def test_mixed_senders(self, expect_output):
        expect_output('''
task task_sender(ch: Channel<int>) -> void
    for i in 0..50
        ch.send(i)
    ~
~

thread thread_sender(ch: Channel<int>) -> void
    for i in 50..100
        ch.send(i)
    ~
~

func main() -> int
    ch: Channel<int> = Channel.new()
    task_sender(ch)
    thread_sender(ch)
    
    total = 0
    for i in 0..100
        total = total + ch.receive()
    ~
    print(total)
    return 0
~
''', "4950\n")
```

## Verification

```bash
python3 -m pytest tests/test_thread_channel.py -v

# Run multiple times to catch race conditions
for i in {1..20}; do
    python3 -m pytest tests/test_thread_channel.py -v || exit 1
done
```

## Success Criteria

1. All tests pass
2. Thread-to-task communication works
3. Task-to-thread communication works
4. Blocking thread is woken by task send
5. Suspended task is woken by thread send
6. FIFO order preserved across boundary
7. No deadlocks under stress
8. No race conditions (run tests repeatedly)

## Notes

- ThreadChannel uses mutex always (no fast path)
- Task must release mutex before suspending
- Thread uses condvar wait, task uses scheduler wait
- Mixed wait queue tracks waiter type for correct wake mechanism
- Compiler infers ThreadChannel when channel escapes task context
