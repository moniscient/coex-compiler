"""
Tests for ThreadChannel - channels that cross the thread-task boundary.
Phase 2, Step 6 of Task System implementation.
"""

import pytest


class TestThreadChannelBasic:
    """Basic ThreadChannel operations - func/task boundary"""

    def test_func_sends_task_receives(self, expect_output):
        """Func sends value, task receives it"""
        expect_output('''
task receiver(ch: Channel<int>) -> int
    return ch.receive()
~

func main() -> int
    ch: Channel<int> = Channel.new()
    ch.send(42)
    result := receiver(ch)
    print(result)
    return 0
~
''', "42\n")

    def test_task_sends_func_receives(self, expect_output):
        """Task sends value, func receives it"""
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
        """Thread sends value, task receives it"""
        expect_output('''
task receiver(ch: Channel<int>) -> int
    return ch.receive()
~

thread sender(ch: Channel<int>) -> void
    ch.send(77)
~

func main() -> int
    ch: Channel<int> = Channel.new()
    sender(ch)
    result := receiver(ch)
    print(result)
    return 0
~
''', "77\n")

    def test_task_sends_thread_receives(self, expect_output):
        """Task sends value, thread receives it"""
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
    result := receiver(ch)
    print(result)
    return 0
~
''', "88\n")


class TestThreadChannelMultipleSenders:
    """Multiple threads and tasks sending to same channel"""

    def test_multiple_senders(self, expect_output):
        """Tasks and threads send to same channel"""
        expect_output('''
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
''', "60\n")


class TestThreadChannelOrder:
    """FIFO order across boundary"""

    def test_fifo_thread_to_task(self, expect_output):
        """Thread sends multiple values, task receives in order"""
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
        """Task sends multiple values, thread receives in order"""
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

    def test_fifo_func_receives_from_task(self, expect_output):
        """Task sends multiple values, func receives in order"""
        expect_output('''
task sender(ch: Channel<int>) -> void
    ch.send(1)
    ch.send(2)
    ch.send(3)
~

func main() -> int
    ch: Channel<int> = Channel.new()
    sender(ch)
    for i in 0..3
        print(ch.receive())
    ~
    return 0
~
''', "1\n2\n3\n")


class TestThreadChannelStress:
    """Stress tests for ThreadChannel"""

    def test_high_volume_task_to_func(self, expect_output):
        """High volume from task to func"""
        expect_output('''
task sender(ch: Channel<int>, n: int) -> void
    for i in 0..n
        ch.send(i)
    ~
~

func main() -> int
    ch: Channel<int> = Channel.new()
    sender(ch, 1000)

    total = 0
    for i in 0..1000
        total = total + ch.receive()
    ~
    print(total)
    return 0
~
''', "499500\n")

    def test_high_volume_thread_to_func(self, expect_output):
        """High volume from thread to func"""
        expect_output('''
thread sender(ch: Channel<int>, n: int) -> void
    for i in 0..n
        ch.send(i)
    ~
~

func main() -> int
    ch: Channel<int> = Channel.new()
    sender(ch, 1000)

    total = 0
    for i in 0..1000
        total = total + ch.receive()
    ~
    print(total)
    return 0
~
''', "499500\n")

    def test_mixed_senders(self, expect_output):
        """Tasks and threads both sending to same channel"""
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
