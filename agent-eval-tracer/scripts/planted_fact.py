#!/usr/bin/env python3
"""
planted_fact.py — the planted-fact memory recall test: plant a specific arbitrary
detail early, bury it under filler turns until it falls out of the active context
window, then probe for it late. If recall fails, the bug is retrieval/persistence,
not model capability. See references/memory-tests.md.

CRITICAL: run this against the SUMMARIZED / compressed memory state, not a raw
transcript you kept on the side. Summarization is the lossy step where facts
silently vanish, and the raw transcript is not what the agent actually sees.

You supply a DRIVER: any object with a `.send(message: str) -> str` method that
drives the *real* conversation-through-memory path (or a faithful copy of it — a
scratch memory store, per references/isolation.md). Each `.send` is one user turn;
the driver maintains conversation history and does its normal summarization
internally. The scaffold plants, buries, probes, and checks recall for you.

To compare summarized vs raw, pass a `driver_factory(mode)` that builds a fresh
driver configured for mode "summarized" or "raw"; run the test in each mode. If
summarized FAILS but raw PASSES, the summarizer is dropping the fact — fix the
summarizer/retrieval, not the model.

USAGE
-----
    from planted_fact import run_planted_fact_test, contains_check

    result = run_planted_fact_test(
        driver=build_driver(mode="summarized"),
        plant_msg="For the record, my account number is X9-4417.",
        filler_msgs=[f"Tell me fact #{i} about the ocean." for i in range(40)],
        probe_msg="What account number did I give you at the start?",
        expected="X9-4417",
        check=contains_check,
    )
    print(result.recalled, result.response)

DEMO
----
    python planted_fact.py --demo
Runs a fake driver that keeps raw history perfectly but "summarizes" by keeping
only the most recent turns — so the planted fact survives in raw mode and is lost
in summarized mode, exactly the failure this test is built to catch.
"""
from __future__ import annotations

import argparse
import re
from dataclasses import dataclass, field
from typing import Any, Callable, List, Optional, Protocol


class Driver(Protocol):
    def send(self, message: str) -> str: ...


# recall checkers: (response_text, expected) -> bool
def exact_check(response: str, expected: str) -> bool:
    return response.strip() == str(expected).strip()


def contains_check(response: str, expected: str) -> bool:
    """Normalized substring match — the usual default. Ignores case and
    collapses whitespace so formatting differences don't cause false failures."""
    norm = lambda s: re.sub(r"\s+", " ", str(s).lower()).strip()
    return norm(expected) in norm(response)


@dataclass
class MemoryTestResult:
    mode: str
    plant_msg: str
    probe_msg: str
    expected: str
    response: str
    recalled: bool
    n_filler_turns: int
    transcript: List[str] = field(default_factory=list)

    def summary(self) -> str:
        status = "PASS (recalled)" if self.recalled else "FAIL (forgot)"
        return (f"[{self.mode}] {status} — buried under {self.n_filler_turns} "
                f"filler turns\n  expected: {self.expected!r}\n  response: "
                f"{self.response!r}")


def run_planted_fact_test(driver: Driver,
                          plant_msg: str,
                          filler_msgs: List[str],
                          probe_msg: str,
                          expected: str,
                          check: Callable[[str, str], bool] = contains_check,
                          mode: str = "summarized",
                          plant_after: Optional[str] = None) -> MemoryTestResult:
    """Plant -> bury -> probe -> check, driving the real memory path.

    plant_after: optional warm-up message sent BEFORE the plant, so the plant
                 isn't literally turn 1 (turn 2 is a good default in the blog).
    """
    transcript: List[str] = []

    if plant_after:
        transcript.append(f"USER: {plant_after}")
        transcript.append(f"AGENT: {driver.send(plant_after)}")

    # 1. plant
    transcript.append(f"USER(plant): {plant_msg}")
    transcript.append(f"AGENT: {driver.send(plant_msg)}")

    # 2. bury
    for msg in filler_msgs:
        transcript.append(f"USER(filler): {msg}")
        transcript.append(f"AGENT: {driver.send(msg)}")

    # 3. probe
    transcript.append(f"USER(probe): {probe_msg}")
    response = driver.send(probe_msg)
    transcript.append(f"AGENT: {response}")

    # 4. check
    recalled = check(response, expected)

    return MemoryTestResult(mode=mode, plant_msg=plant_msg, probe_msg=probe_msg,
                            expected=expected, response=response, recalled=recalled,
                            n_filler_turns=len(filler_msgs), transcript=transcript)


def find_burial_threshold(driver_factory: Callable[[], Driver],
                          plant_msg: str,
                          make_filler: Callable[[int], str],
                          probe_msg: str,
                          expected: str,
                          check: Callable[[str, str], bool] = contains_check,
                          start: int = 5, stop: int = 80, step: int = 5) -> Optional[int]:
    """Increase the number of filler turns until recall first fails. Returns the
    smallest filler count at which the fact is forgotten (a concrete capacity
    limit you can report and regression-test), or None if it never failed.

    driver_factory must return a FRESH driver each call — otherwise state leaks
    between trials and the threshold is meaningless.
    """
    for depth in range(start, stop + 1, step):
        driver = driver_factory()
        filler = [make_filler(i) for i in range(depth)]
        result = run_planted_fact_test(driver, plant_msg, filler, probe_msg,
                                       expected, check)
        if not result.recalled:
            return depth
    return None


# --------------------------------------------------------------------------- #
# Demo: a fake driver. Raw mode remembers everything; summarized mode keeps only
# the most recent WINDOW turns, so an early planted fact is dropped once buried.
# --------------------------------------------------------------------------- #
class _FakeDriver:
    def __init__(self, mode: str, window: int = 6):
        self.mode = mode
        self.window = window
        self.history: List[str] = []

    def send(self, message: str) -> str:
        self.history.append(message)
        # the "memory" the agent can see when answering:
        visible = self.history if self.mode == "raw" else self.history[-self.window:]
        # naive recall: echo any account-number-looking token still visible
        if "account number" in message.lower():
            for turn in visible:
                m = re.search(r"[A-Z0-9]{2}-\d{4}", turn)
                if m:
                    return f"Your account number is {m.group(0)}."
            return "I'm sorry, I don't have that on record."
        return "ok, noted."


def _demo():
    plant = "For the record, my account number is X9-4417."
    filler = [f"Tell me fact #{i} about the ocean." for i in range(30)]
    probe = "What account number did I give you at the start?"
    expected = "X9-4417"

    for mode in ("raw", "summarized"):
        driver = _FakeDriver(mode=mode, window=6)
        result = run_planted_fact_test(driver, plant, filler, probe, expected,
                                       check=contains_check, mode=mode,
                                       plant_after="Hi, I have a couple of questions.")
        print(result.summary())
        print()

    print("Interpretation: raw PASSES, summarized FAILS -> the summarizer is "
          "dropping the planted fact. Fix the summarizer/retrieval, not the model.")

    thr = find_burial_threshold(
        driver_factory=lambda: _FakeDriver(mode="summarized", window=6),
        plant_msg=plant, make_filler=lambda i: f"Ocean fact #{i}?",
        probe_msg=probe, expected=expected, start=1, stop=12, step=1)
    print(f"\nRecall first fails at {thr} filler turns (summarized, window=6).")


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--demo", action="store_true", help="run the built-in demo")
    args = ap.parse_args()
    if args.demo:
        _demo()
    else:
        ap.print_help()
