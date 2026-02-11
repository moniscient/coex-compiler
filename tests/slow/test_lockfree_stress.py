"""
Stress tests for lock-free runtime (BUG-033, 035, 036, 042).
These tests use large workloads to expose race conditions.
"""
import pytest


class TestGlobalQueueStress:
    """BUG-035: stress test Treiber stack global queue"""

    def test_global_queue_10000_tasks(self, expect_output):
        """10,000 tasks through lock-free global queue"""
        expect_output('''
task identity(x: int) -> int
    return x
~

func main() -> int
    total = 0
    i = 0
    while i < 10000
        result := identity(i)
        total = total + result
        i = i + 1
    ~
    print(total)
    return 0
~
''', "49995000\n")


class TestChannelStress:
    """BUG-042: stress test lock-free MPSC channel"""

    def test_channel_100000_messages(self, expect_output):
        """100K messages through lock-free MPSC queue"""
        expect_output('''
task producer(ch: Channel<int>, count: int) -> void
    i = 0
    while i < count
        ch.send(1)
        i = i + 1
    ~
~

func main() -> int
    ch: Channel<int> = Channel.new()
    producer(ch, 100000)
    total = 0
    i = 0
    while i < 100000
        v = ch.receive()
        total = total + v
        i = i + 1
    ~
    print(total)
    return 0
~
''', "100000\n")
