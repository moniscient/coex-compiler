"""
Tests for Channel Type Inference.
Phase 2, Step 7 of Task System implementation.

These tests verify that channels work correctly regardless of which
implementation (TaskChannel or ThreadChannel) would be inferred.
Currently uses a unified implementation that handles all cases.
"""

import pytest


class TestChannelInference:
    """Tests for channel type inference - verify correctness"""

    def test_pure_task_context(self, expect_output):
        """Channel staying in task context works correctly"""
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
        """Channel created in func works correctly"""
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
        """Channel passed to thread works correctly"""
        expect_output('''
task producer(ch: Channel<int>) -> void
    ch.send(50)
~

thread consumer(ch: Channel<int>) -> int
    return ch.receive()
~

func test() -> int
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
        """Channel stored in struct works correctly"""
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
        """Channel that might escape to thread works correctly"""
        expect_output('''
thread helper(ch: Channel<int>) -> void
    ch.send(2)
~

func maybe_escape(ch: Channel<int>, escape: bool) -> void
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

    def test_conditional_thread_escape_true(self, expect_output):
        """Channel that actually escapes to thread works correctly"""
        expect_output('''
thread helper(ch: Channel<int>) -> void
    ch.send(2)
~

func maybe_escape(ch: Channel<int>, escape: bool) -> void
    if escape
        helper(ch)
    else
        ch.send(1)
    ~
~

func main() -> int
    ch: Channel<int> = Channel.new()
    maybe_escape(ch, true)
    print(ch.receive())
    return 0
~
''', "2\n")


class TestChannelInferenceCorrectness:
    """Verify inference doesn't break correctness"""

    def test_task_channel_concurrent_access(self, expect_output):
        """Channel handles concurrent task access"""
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
        """Channel handles mixed task/thread access"""
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

    def test_channel_returned_from_task(self, expect_output):
        """Channel returned from task works correctly"""
        expect_output('''
task make_channel() -> Channel<int>
    ch: Channel<int> = Channel.new()
    ch.send(99)
    return ch
~

func main() -> int
    ch := make_channel()
    print(ch.receive())
    return 0
~
''', "99\n")


class TestChannelComplexScenarios:
    """Complex channel usage scenarios"""

    def test_multiple_channels(self, expect_output):
        """Multiple channels in same function work correctly"""
        expect_output('''
task forwarder(in_ch: Channel<int>, out_ch: Channel<int>) -> void
    val = in_ch.receive()
    out_ch.send(val * 2)
~

func main() -> int
    ch1: Channel<int> = Channel.new()
    ch2: Channel<int> = Channel.new()
    ch1.send(21)
    forwarder(ch1, ch2)
    print(ch2.receive())
    return 0
~
''', "42\n")

    def test_channel_pipeline(self, expect_output):
        """Pipeline of channels works correctly"""
        expect_output('''
task stage1(ch_out: Channel<int>) -> void
    ch_out.send(1)
~

task stage2(ch_in: Channel<int>, ch_out: Channel<int>) -> void
    val = ch_in.receive()
    ch_out.send(val + 10)
~

task stage3(ch_in: Channel<int>, ch_out: Channel<int>) -> void
    val = ch_in.receive()
    ch_out.send(val + 100)
~

func main() -> int
    ch1: Channel<int> = Channel.new()
    ch2: Channel<int> = Channel.new()
    ch3: Channel<int> = Channel.new()

    stage1(ch1)
    stage2(ch1, ch2)
    stage3(ch2, ch3)

    print(ch3.receive())
    return 0
~
''', "111\n")

    def test_bidirectional_channels(self, expect_output):
        """Two tasks communicating via channels works correctly"""
        expect_output('''
task echo_server(request: Channel<int>, response: Channel<int>) -> void
    val = request.receive()
    response.send(val * 2)
~

task client(request: Channel<int>, response: Channel<int>) -> int
    request.send(25)
    return response.receive()
~

func main() -> int
    req: Channel<int> = Channel.new()
    resp: Channel<int> = Channel.new()
    echo_server(req, resp)
    result := client(req, resp)
    print(result)
    return 0
~
''', "50\n")
