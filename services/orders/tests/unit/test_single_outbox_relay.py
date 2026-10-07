"""At most one outbox relay per deployment (feature 15, carried from outbox_and_idempotency Q2).

Two relays running at once can publish one order's facts out of order (design 5.2). The root
refuses: more than one worker (`WEB_CONCURRENCY`), a worker started by `multiprocessing` (how
uvicorn runs `--workers N`), and a second relay-owning runtime in one process (proven against the
real lifespan in `tests/integration/test_orders_host_lifespan.py`, together with a real uvicorn).
"""

import subprocess
import sys
import textwrap

import pytest

from otc_orders.composition import MultipleOutboxRelaysError, assert_single_outbox_relay


def test_one_worker_with_the_relay_enabled_is_allowed() -> None:
    assert_single_outbox_relay(relay_enabled=True, web_concurrency=1, in_worker_process=False)


@pytest.mark.parametrize("workers", [2, 3, 16])
def test_several_workers_with_the_relay_enabled_are_refused(workers: int) -> None:
    with pytest.raises(MultipleOutboxRelaysError, match=f"WEB_CONCURRENCY={workers}"):
        assert_single_outbox_relay(
            relay_enabled=True, web_concurrency=workers, in_worker_process=False
        )


def test_a_multiprocessing_worker_with_the_relay_enabled_is_refused() -> None:
    with pytest.raises(MultipleOutboxRelaysError, match="worker"):
        assert_single_outbox_relay(relay_enabled=True, web_concurrency=1, in_worker_process=True)


@pytest.mark.parametrize(("workers", "in_worker"), [(1, False), (4, False), (1, True), (4, True)])
def test_with_the_relay_disabled_any_worker_layout_is_allowed(
    workers: int, in_worker: bool
) -> None:
    assert_single_outbox_relay(
        relay_enabled=False, web_concurrency=workers, in_worker_process=in_worker
    )


def test_running_in_worker_process_is_false_in_a_parent_and_true_in_a_spawned_child() -> None:
    # Measured in a REAL spawned process (the way uvicorn starts `--workers N`), not assumed.
    script = textwrap.dedent(
        """
        import multiprocessing
        from otc_orders.composition import running_in_worker_process

        if __name__ == "__main__":
            with multiprocessing.get_context("spawn").Pool(1) as pool:
                in_child = pool.apply(running_in_worker_process)
            print(running_in_worker_process(), in_child)
        """
    )
    done = subprocess.run(  # noqa: S603 - the interpreter running this test, a fixed script
        [sys.executable, "-c", script], capture_output=True, text=True, timeout=60, check=True
    )
    assert done.stdout.split() == ["False", "True"], done.stderr
