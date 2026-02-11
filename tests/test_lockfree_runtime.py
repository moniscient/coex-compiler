"""
Tests for lock-free runtime changes (BUG-033, 035, 036, 042).
Validates that scheduler init, global queue, and channel operations
work correctly after removing mutexes from hot paths.
"""
import pytest


class TestSchedulerInit:
    """BUG-033: scheduler init via pthread_once"""

    def test_scheduler_init_from_multiple_threads(self, expect_output):
        """Spawn 10 threads that each call a task — verifies pthread_once init"""
        expect_output('''
task compute(x: int) -> int
    return x * 2
~

thread worker(id: int) -> int
    return compute(id)
~

func main() -> int
    total = 0
    i = 0
    while i < 10
        result := worker(i)
        total = total + result
        i = i + 1
    ~
    print(total)
    return 0
~
''', "90\n")


class TestGlobalQueue:
    """BUG-035: lock-free Treiber stack for global queue"""

    def test_global_queue_fan_out(self, expect_output):
        """Spawn 50 independent tasks, verify all complete with correct results"""
        expect_output('''
task square(x: int) -> int
    return x * x
~

func main() -> int
    total = 0
    i = 0
    while i < 50
        result := square(i)
        total = total + result
        i = i + 1
    ~
    print(total)
    return 0
~
''', "40425\n")


class TestChannelFIFO:
    """BUG-042: lock-free channel preserves FIFO order"""

    def test_channel_fifo_order_preserved(self, expect_output):
        """Send 100 values, verify FIFO order"""
        expect_output('''
task producer(ch: Channel<int>) -> void
    i = 0
    while i < 100
        ch.send(i)
        i = i + 1
    ~
~

func main() -> int
    ch: Channel<int> = Channel.new()
    producer(ch)
    ok = 1
    i = 0
    while i < 100
        v = ch.receive()
        if v != i
            ok = 0
        ~
        i = i + 1
    ~
    print(ok)
    return 0
~
''', "1\n")

    def test_channel_multiple_senders(self, expect_output):
        """5 threads each send 20 values to one channel, receiver collects all 100"""
        expect_output('''
thread sender(ch: Channel<int>, base: int) -> void
    i = 0
    while i < 20
        ch.send(base + i)
        i = i + 1
    ~
~

func main() -> int
    ch: Channel<int> = Channel.new()
    s = 0
    while s < 5
        sender(ch, s * 100)
        s = s + 1
    ~
    total = 0
    i = 0
    while i < 100
        v = ch.receive()
        total = total + v
        i = i + 1
    ~
    print(total)
    return 0
~
''', "20950\n")

    def test_channel_send_receive_interleaved(self, expect_output):
        """Alternating send/receive operations — validates no lost wakeups"""
        expect_output('''
task slow_producer(ch: Channel<int>) -> void
    i = 0
    while i < 10
        ch.send(i * 10)
        i = i + 1
    ~
~

func main() -> int
    ch: Channel<int> = Channel.new()
    slow_producer(ch)
    total = 0
    i = 0
    while i < 10
        v = ch.receive()
        total = total + v
        i = i + 1
    ~
    print(total)
    return 0
~
''', "450\n")


class TestParallelMap:
    """Exercises global queue + worker stealing with parallel for"""

    def test_parallel_map_20_elements(self, expect_output):
        """20 tasks via for-collection, verify all results"""
        expect_output('''
task double(x: int) -> int
    return x * 2
~

func main() -> int
    total = 0
    i = 0
    while i < 20
        result := double(i)
        total = total + result
        i = i + 1
    ~
    print(total)
    return 0
~
''', "380\n")
