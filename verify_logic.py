#!/usr/bin/env python3
"""
Offline logic check for the Nik Gold 2-Candle Reversal SELL rules.

WHAT THIS IS: an INDEPENDENT Python re-implementation of the *rules*, used as an oracle to
confirm (a) the pattern fires on valid setups, (b) the "X" screenshots (red high >= green
high) are filtered out by rule 4, and (c) the short-side stop/target math points the right way.

WHAT THIS IS NOT: it does not compile or run the Pine scripts (Pine only runs inside
TradingView), and it is NOT a performance backtest. It validates the logic, not live results.
"""
from dataclasses import dataclass


@dataclass
class Candle:
    o: float
    h: float
    l: float
    c: float


def sell_signal(green: Candle, red: Candle) -> bool:
    r1 = green.c > green.o      # rule 1: green (bullish) candle first
    r2 = red.c < red.o          # rule 2: red (bearish) candle immediately after
    r3 = red.c < green.o        # rule 3: red closes below the green candle's OPEN
    r4 = green.h > red.h        # rule 4: green high strictly above the red high
    return r1 and r2 and r3 and r4


# (green, red, expected_signal, description)
CASES = [
    (Candle(100, 110, 99, 108), Candle(107, 108, 96, 98), True,
     "Valid sell (like 2/4/5.png): red closes below green open, red high < green high"),
    (Candle(100, 110, 99, 108), Candle(107, 111, 96, 98), False,
     "X case (like 1/3.png): red HIGH 111 exceeds green high 110 -> rule 4 blocks it"),
    (Candle(100, 110, 99, 108), Candle(107, 110, 96, 98), False,
     "Boundary: red high EQUALS green high -> still blocked (strict >)"),
    (Candle(100, 110, 99, 108), Candle(107, 108, 100, 101), False,
     "Red closes at 101, NOT below green open 100 -> rule 3 fails"),
    (Candle(100, 110, 99, 108), Candle(101, 109, 100, 107), False,
     "Second candle is green (close>open) -> rule 2 fails"),
    (Candle(100, 110, 99, 108), Candle(103, 108, 96, 103), False,
     "Second candle is a doji (open==close) -> rule 2 fails"),
    (Candle(108, 110, 100, 101), Candle(107, 108, 96, 98), False,
     "First candle is red -> rule 1 fails (no green to start the pattern)"),
]


def run_signal_tests() -> bool:
    print("PATTERN-RULE TESTS")
    ok = True
    for i, (g, r, exp, desc) in enumerate(CASES, 1):
        got = sell_signal(g, r)
        if got != exp:
            ok = False
        print(f"  [{'PASS' if got == exp else 'FAIL'}] case {i}: expected={exp}, got={got}  -- {desc}")
    return ok


def simulate_short(green: Candle, red: Candle, rr: float, sl_buffer: float, future):
    """Indicator-style levels (entry = red close). Walk forward: SL if a bar's high >= stop,
       TP if a bar's low <= target. If both happen in one bar, assume STOP first (TradingView's
       default pessimistic assumption)."""
    entry = red.c
    stop = green.h + sl_buffer
    risk = stop - entry
    tp = entry - rr * risk
    for k in future:
        if k.h >= stop:
            return ("SL", entry, stop, tp)
        if k.l <= tp:
            return ("TP", entry, stop, tp)
    return ("OPEN", entry, stop, tp)


def run_trade_tests() -> bool:
    print("EXIT-MATH TESTS (short: stop sits ABOVE entry, target = RR x risk BELOW entry)")
    ok = True
    g = Candle(100, 110, 99, 108)
    r = Candle(107, 108, 96, 98)   # entry=98, stop=110, risk=12

    res, entry, stop, tp = simulate_short(g, r, 2.0, 0.0, [Candle(98, 100, 73, 75)])  # low 73 <= 74
    c1 = res == "TP" and abs(tp - 74) < 1e-9
    ok &= c1
    print(f"  [{'PASS' if c1 else 'FAIL'}] RR=2 target: entry={entry} stop={stop} tp={tp} (expect 74) -> {res}")

    res2, *_ = simulate_short(g, r, 2.0, 0.0, [Candle(99, 111, 97, 109)])  # high 111 >= stop 110
    c2 = res2 == "SL"
    ok &= c2
    print(f"  [{'PASS' if c2 else 'FAIL'}] stop triggers when price rallies to the green high -> {res2}")

    res3, _, stop3, tp3 = simulate_short(g, r, 2.0, 1.0, [Candle(98, 100, 71, 72)])  # buffer=1
    c3 = abs(stop3 - 111) < 1e-9 and abs(tp3 - 72) < 1e-9 and res3 == "TP"
    ok &= c3
    print(f"  [{'PASS' if c3 else 'FAIL'}] buffer raises stop: stop={stop3} (expect 111), tp={tp3} (expect 72) -> {res3}")
    return ok


if __name__ == "__main__":
    a = run_signal_tests()
    print()
    b = run_trade_tests()
    print()
    if a and b:
        print("ALL LOGIC CHECKS PASSED")
    else:
        print("SOME CHECKS FAILED")
        raise SystemExit(1)
