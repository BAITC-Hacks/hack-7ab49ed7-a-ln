import threading
import time
from types import SimpleNamespace

import pytest

from mg_api.analytics.store import RunCache

MB = 1024 * 1024
SETTLE_S = 0.3


def test_concurrent_misses_share_one_load(tmp_path):
    started, release = threading.Event(), threading.Event()
    loads = []

    def slow_loader(run_id, current):
        loads.append(run_id)
        started.set()
        release.wait(timeout=5)
        return SimpleNamespace(size_bytes=1)

    cache = RunCache(budget_mb=1, loader=slow_loader)
    results = []
    readers = [threading.Thread(target=lambda: results.append(cache.get("r1", tmp_path))) for _ in range(4)]
    for reader in readers:
        reader.start()
    assert started.wait(timeout=5)
    release.set()
    for reader in readers:
        reader.join(timeout=5)
    assert loads == ["r1"] and len(results) == 4 and all(r is results[0] for r in results)


def _concurrent_gets(cache: RunCache, tmp_path, readers: int, started: threading.Event, release: threading.Event):
    results = []
    barrier = threading.Barrier(readers)

    def read():
        barrier.wait()
        try:
            results.append(cache.get("r1", tmp_path))
        except (OSError, AttributeError) as e:
            results.append(e)

    threads = [threading.Thread(target=read) for _ in range(readers)]
    for thread in threads:
        thread.start()
    assert started.wait(timeout=5)
    time.sleep(SETTLE_S)
    release.set()
    for thread in threads:
        thread.join(timeout=5)
    return results


def test_waiters_share_an_uncached_result(tmp_path):
    started, release = threading.Event(), threading.Event()
    loads = []

    def oversized_loader(run_id, current):
        loads.append(run_id)
        started.set()
        release.wait(timeout=5)
        return SimpleNamespace(size_bytes=2 * MB)

    results = _concurrent_gets(RunCache(budget_mb=1, loader=oversized_loader), tmp_path, 4, started, release)
    assert loads == ["r1"] and len(results) == 4 and all(r is results[0] for r in results)


def test_waiters_receive_the_loaders_error(tmp_path):
    started, release = threading.Event(), threading.Event()

    def failing_loader(run_id, current):
        started.set()
        release.wait(timeout=5)
        raise OSError("artifact missing")

    results = _concurrent_gets(RunCache(budget_mb=1, loader=failing_loader), tmp_path, 3, started, release)
    assert len(results) == 3 and all(isinstance(r, OSError) for r in results)


def test_waiters_are_released_when_caching_the_result_fails(tmp_path):
    started, release = threading.Event(), threading.Event()

    def loader_of_unsizable_data(run_id, current):
        started.set()
        release.wait(timeout=5)
        return object()

    cache = RunCache(budget_mb=1, loader=loader_of_unsizable_data)
    results = _concurrent_gets(cache, tmp_path, 3, started, release)
    assert len(results) == 3 and all(isinstance(r, AttributeError) for r in results)


def test_waiter_does_not_repopulate_an_invalidated_run(tmp_path):
    started, release = threading.Event(), threading.Event()
    loads = []

    def slow_loader(run_id, current):
        loads.append(run_id)
        started.set()
        release.wait(timeout=5)
        return SimpleNamespace(size_bytes=1)

    cache = RunCache(budget_mb=1, loader=slow_loader)
    leader = threading.Thread(target=cache.get, args=("r1", tmp_path))
    leader.start()
    assert started.wait(timeout=5)
    waiter_result = []
    waiter = threading.Thread(target=lambda: waiter_result.append(cache.get("r1", tmp_path)))
    waiter.start()
    time.sleep(SETTLE_S)
    cache.invalidate("r1")
    release.set()
    leader.join(timeout=5)
    waiter.join(timeout=5)
    assert loads == ["r1"] and len(waiter_result) == 1
    cache.get("r1", tmp_path)
    assert loads == ["r1", "r1"]


def test_load_that_raced_an_invalidation_is_not_cached(tmp_path):
    loads = []

    def loader(run_id, current):
        loads.append(run_id)
        if len(loads) == 1:
            cache.invalidate(run_id)
        return SimpleNamespace(size_bytes=1)

    cache = RunCache(budget_mb=1, loader=loader)
    cache.get("r1", tmp_path)
    cache.get("r1", tmp_path)
    cache.get("r1", tmp_path)
    assert loads == ["r1", "r1"]


def test_runs_larger_than_the_budget_are_served_uncached(tmp_path):
    loads = []

    def loader(run_id, current):
        loads.append(run_id)
        return SimpleNamespace(size_bytes=2 * MB)

    cache = RunCache(budget_mb=1, loader=loader)
    cache.get("big", tmp_path)
    cache.get("big", tmp_path)
    assert loads == ["big", "big"]


def test_failed_load_does_not_block_the_next_reader(tmp_path):
    attempts = []

    def flaky_loader(run_id, current):
        attempts.append(run_id)
        if len(attempts) == 1:
            raise OSError("disk hiccup")
        return SimpleNamespace(size_bytes=1)

    cache = RunCache(budget_mb=1, loader=flaky_loader)
    with pytest.raises(OSError):
        cache.get("r1", tmp_path)
    assert cache.get("r1", tmp_path).size_bytes == 1 and len(attempts) == 2
