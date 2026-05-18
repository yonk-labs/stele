from stele.runtime.scheduling import SchedulingPolicy, SessionScheduler


class FakeClock:
    def __init__(self) -> None:
        self.t = 0.0

    def __call__(self) -> float:
        return self.t

    def advance(self, secs: float) -> None:
        self.t += secs


def test_warmup_turns_1_2_4_8() -> None:
    s = SessionScheduler(policy=SchedulingPolicy(idle_seconds=1e9))
    fired = [t for t in range(1, 10) if s.should_process("sess")]
    assert fired == [1, 2, 4, 8]


def test_queue_high_water_triggers() -> None:
    clock = FakeClock()
    s = SessionScheduler(
        policy=SchedulingPolicy(queue_high_water=3, idle_seconds=1e9),
        clock=clock,
    )
    s.should_process("a")  # turn 1 (warmup) — consume it
    for _ in range(3):
        s.enqueue("a", "evt")
    # turn 3 isn't a warmup turn, but the queue is at high-water
    s.should_process("a")  # turn 2 (warmup)
    assert s.should_process("a") is True  # turn 3 via queue depth


def test_idle_flush_with_fake_clock() -> None:
    clock = FakeClock()
    s = SessionScheduler(
        policy=SchedulingPolicy(idle_seconds=300), clock=clock
    )
    for _ in range(8):
        s.should_process("x")  # exhaust warmup turns
    assert s.should_process("x") is False        # turn 9, not idle yet
    clock.advance(301)
    assert s.should_process("x") is True         # idle timeout elapsed


def test_flush_session_is_scoped_and_idempotent() -> None:
    s = SessionScheduler(policy=SchedulingPolicy())
    s.enqueue("s1", "a")
    s.enqueue("s1", "b")
    s.enqueue("s2", "z")
    flushed = s.flush_session("s1")
    assert flushed == ["a", "b"]
    assert s.flush_session("s1") == []           # idempotent
    assert s.queue_depth("s2") == 1              # other session untouched
    assert s.flush_session("s2") == ["z"]


def test_flush_all_reports_leftovers_under_limit() -> None:
    s = SessionScheduler(policy=SchedulingPolicy())
    for i in range(5):
        s.enqueue("s1", i)
    s.enqueue("s2", "q")
    flushed, leftovers = s.flush_all(max_items=3)
    assert len(flushed) == 3
    assert leftovers  # explicit leftovers, not silently dropped
