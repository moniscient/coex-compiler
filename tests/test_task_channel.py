"""
Tests for TaskChannel - lightweight channels for task-to-task communication.
Phase 2, Step 5 of the Coex Task System implementation.
"""
import pytest


class TestTaskChannelBasic:
    """Basic TaskChannel operations"""

    def test_send_then_receive(self, expect_output):
        """Basic send and receive"""
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
        """Multiple values buffered"""
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
        """FIFO order preserved"""
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

    @pytest.mark.skip(reason="BUG-012: Task calls are synchronous - test hangs indefinitely")
    def test_receive_waits_for_send(self, expect_output):
        """Receive blocks until data available"""
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

    @pytest.mark.skip(reason="BUG-012: Task calls are synchronous - test hangs indefinitely")
    def test_multiple_waiters(self, expect_output):
        """Multiple receivers wait for values"""
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

    @pytest.mark.xfail(reason="BUG-006: Channel<List<int>> receive() returns unknown type")
    def test_list_through_channel(self, expect_output):
        """List values through channel"""
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
        """String values through channel"""
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
    s := test()
    print(s)
    return 0
~
''', "hello\n")


class TestTaskChannelStress:
    """Stress tests"""

    def test_many_values(self, expect_output):
        """Many values through channel"""
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

    @pytest.mark.skip(reason="BUG-012: Task calls are synchronous - test hangs indefinitely")
    def test_ping_pong(self, expect_output):
        """Ping-pong communication pattern"""
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


class TestTaskChannelPassedAsParameter:
    """Tests for passing channels to tasks"""

    def test_channel_parameter(self, expect_output):
        """Channel passed as parameter"""
        expect_output('''
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
''', "60\n")

    def test_channel_in_loop(self, expect_output):
        """Channel operations in loop"""
        expect_output('''
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
''', "30\n")

    def test_multiple_senders(self, expect_output):
        """Multiple senders, one receiver"""
        expect_output('''
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
''', "60\n")
