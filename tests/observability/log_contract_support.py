"""Support for the six real-process log-contract tests (feature 27, S1.6; `design.md` 2.5).

Not a test module (no `test_` prefix). Each service's `test_<svc>_log_contract.py` loads it BY
PATH, because the suite runs in importlib mode and a sibling directory is not importable by name;
it holds what the six tests share so they cannot drift apart in HOW they read a log.

The claim is about the bytes a real process writes, so everything here works on the stderr FILE of
a real `python -m uvicorn ...` (or `python -m otc_gateway`) child:

* `spawn` starts the child with the test's environment (a working directory with no `.env`);
* `wait_for_event` polls the file, PACED at 0.2 s, under `asyncio.timeout` whose message names the
  claim it waits for, and stops early when the child has exited or wrote a line that is not JSON;
* `stop` sends SIGTERM and waits for the exit, killing the child's process group on a timeout;
* `check_contract` is the contract over EVERY line the process wrote.
"""

import asyncio
import json
import os
import re
import signal
import subprocess
import sys
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

type Line = dict[str, Any]
type Match = Callable[[Line], bool]

INSTANT = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3}Z$")
REQUIRED_KEYS = ("level", "logger", "event", "timestamp")
# Lines of the server's own lifecycle: they happen outside any unit of work, so none may carry the
# unit's id (a binding that outlived its unit would put it there).
LIFECYCLE_PREFIXES = (
    "Started server process",
    "Waiting for application startup",
    "Application startup complete",
    "Shutting down",
    "Waiting for application shutdown",
    "Application shutdown complete",
    "Finished server process",
)
POLL_SECONDS = 0.2


@dataclass
class Process:
    popen: subprocess.Popen[bytes]
    stderr_path: Path
    stdout_path: Path
    command: Sequence[str]

    def stderr_text(self) -> str:
        return self.stderr_path.read_text(encoding="utf-8")


def spawn(command: Sequence[str], *, cwd: Path, tmp_path: Path, name: str) -> Process:
    """Start `command` with the CURRENT process environment (the test set it with `monkeypatch`).

    The child leads its own session, so a stuck one is killed with its whole process group."""
    stderr_path = tmp_path / f"{name}.stderr.log"
    stdout_path = tmp_path / f"{name}.stdout.log"
    with stderr_path.open("wb") as err, stdout_path.open("wb") as out:
        popen = subprocess.Popen(  # noqa: S603 - the interpreter running this test, fixed arguments
            list(command),
            cwd=cwd,
            env=os.environ.copy(),
            stdout=out,
            stderr=err,
            start_new_session=True,
        )
    return Process(popen, stderr_path, stdout_path, command)


def python_module(*arguments: str) -> list[str]:
    return [sys.executable, "-m", *arguments]


def complete_lines(text: str) -> list[str]:
    """The lines of `text` that are finished (a trailing partial line is still being written)."""
    parts = text.split("\n")
    return [part for part in parts[:-1] if part.strip()]


def parse(lines: Sequence[str]) -> list[Line]:
    """Every line as one JSON object; the first line that is not names itself."""
    parsed: list[Line] = []
    for number, text in enumerate(lines, start=1):
        try:
            value = json.loads(text)
        except json.JSONDecodeError:
            raise AssertionError(f"stderr line {number} is not JSON: {text!r}") from None
        assert isinstance(value, dict), f"stderr line {number} is JSON but not an object: {text!r}"
        parsed.append(value)
    return parsed


async def wait_for_event(process: Process, claim: str, match: Match, seconds: float = 90) -> Line:
    """The first complete line satisfying `match`; fails naming `claim` on timeout or child exit."""
    try:
        async with asyncio.timeout(seconds):
            while True:
                for text in complete_lines(process.stderr_text()):
                    try:
                        line = json.loads(text)
                    except json.JSONDecodeError:
                        # the contract is already broken: fail now, not after the whole timeout
                        raise AssertionError(
                            f"while waiting for: {claim}\na stderr line is not JSON: {text!r}"
                        ) from None
                    if isinstance(line, dict) and match(line):
                        return line
                code = process.popen.poll()
                if code is not None:
                    raise AssertionError(
                        f"the process exited with {code} before: {claim}\n{process.stderr_text()}"
                    )
                await asyncio.sleep(POLL_SECONDS)
    except TimeoutError:
        raise AssertionError(
            f"gave up after {seconds} s waiting for: {claim}\n{process.stderr_text()}"
        ) from None


def booted(line: Line) -> bool:
    return line.get("logger") == "uvicorn.error" and line.get("event") == (
        "Application startup complete."
    )


async def stop(process: Process, seconds: float = 40) -> int:
    """SIGTERM, then wait for the exit; the whole process group is killed on a timeout."""
    if process.popen.poll() is None:
        process.popen.send_signal(signal.SIGTERM)
    try:
        return await asyncio.wait_for(asyncio.to_thread(process.popen.wait), timeout=seconds)
    except TimeoutError:
        kill(process)
        raise AssertionError(
            f"the process ignored SIGTERM for {seconds} s:\n{process.stderr_text()}"
        ) from None


def kill(process: Process) -> None:
    """Idempotent cleanup for a `finally`: kill the child's process group if it still runs."""
    if process.popen.poll() is None:
        try:
            os.killpg(process.popen.pid, signal.SIGKILL)
        except ProcessLookupError:
            return
        process.popen.wait()


def check_contract(
    process: Process,
    *,
    correlation_id: str,
    provoked: Mapping[str, Match],
    trace_id: str | None = None,
) -> list[Line]:
    """The contract over EVERY stderr line the process wrote (call it after `stop`).

    1. every non-blank line is one JSON object (so uvicorn's `Started server process` is too);
    2. each carries `level`, `logger`, `event`, `timestamp` as non-empty strings, the timestamp in
       the wire's instant format;
    3. no value anywhere is an empty string, and `traceId` / `spanId` are hex of 32 / 16 digits;
    4. the lifecycle lines of the server carry no `correlationId` (a binding ends with its unit);
    5. every line `provoked` names exists, carries `correlationId == correlation_id`, and is among
       the lines carrying it;
    6. when `trace_id` is given, the lines carrying it are exactly the lines carrying the unit's
       `correlationId` (the six per-service tests pass the trace id of the unit's inbound
       `traceparent`).
    """
    text = process.stderr_text()
    lines = parse([line for line in text.split("\n") if line.strip()])
    assert lines, "the process wrote nothing to stderr"
    for number, line in enumerate(lines, start=1):
        for key in REQUIRED_KEYS:
            assert isinstance(line.get(key), str), f"line {number} lacks `{key}`: {line}"
            assert line[key], f"line {number} has an empty `{key}`: {line}"
        assert INSTANT.match(line["timestamp"]), f"line {number} timestamp: {line['timestamp']!r}"
        empty = [key for key, value in line.items() if value == ""]
        assert not empty, f"line {number} has empty values for {empty}: {line}"
        if "traceId" in line:
            assert re.fullmatch(r"[0-9a-f]{32}", line["traceId"]), f"line {number}: {line}"
        if "spanId" in line:
            assert re.fullmatch(r"[0-9a-f]{16}", line["spanId"]), f"line {number}: {line}"
    assert any(
        line["logger"] == "uvicorn.error" and line["event"].startswith("Started server process")
        for line in lines
    ), "no JSON `Started server process` line (uvicorn's own format leaked, or the line is absent)"
    for line in lines:
        if line["event"].startswith(LIFECYCLE_PREFIXES):
            assert "correlationId" not in line, f"a lifecycle line carries a correlationId: {line}"
    carrying = [line for line in lines if line.get("correlationId") == correlation_id]
    for name, match in provoked.items():
        found = [line for line in lines if match(line)]
        assert found, f"the line the unit provokes ({name}) is absent from stderr:\n{text}"
        for line in found:
            assert line.get("correlationId") == correlation_id, (
                f"the line ({name}) lacks the unit's correlationId {correlation_id}: {line}"
            )
            assert line in carrying
    if trace_id is not None:
        with_trace = [line for line in lines if line.get("traceId") == trace_id]
        assert with_trace == carrying, (
            "the lines carrying the unit's traceId are not the lines carrying its correlationId:"
            f"\n traceId: {with_trace}\n correlationId: {carrying}"
        )
    return lines


# ----------------------------------------------------------------------------------------- Kafka
#
# The Projector and Notifications children consume the REAL fact topics (their names are constants
# of the service, not settings), and the session broker holds the facts every earlier test
# produced. Isolation (item 10, "commits its group to the end first"): the child's consumer group is
# unique to the test and is committed at the END of every partition before the child starts, so the
# child reads only the fact the test publishes after that.


async def commit_group_at_end(bootstrap_servers: str, group: str, topics: Sequence[str]) -> None:
    from aiokafka import AIOKafkaConsumer, TopicPartition
    from aiokafka.admin import AIOKafkaAdminClient

    admin = AIOKafkaAdminClient(bootstrap_servers=bootstrap_servers)
    await admin.start()
    try:
        described: list[dict[str, Any]] = await admin.describe_topics(list(topics))
    finally:
        await admin.close()
    partitions = [
        TopicPartition(topic["topic"], int(partition["partition"]))
        for topic in described
        for partition in topic["partitions"]
    ]
    assert partitions, f"the broker reports no partition for {list(topics)}"
    consumer = AIOKafkaConsumer(
        bootstrap_servers=bootstrap_servers,
        group_id=group,
        client_id="otc-log-contract-baseline",
        enable_auto_commit=False,
    )
    await consumer.start()
    try:
        consumer.assign(partitions)
        ends: dict[Any, int] = await consumer.end_offsets(partitions)
        await consumer.commit({partition: ends[partition] for partition in partitions})
    finally:
        await asyncio.sleep(
            0.05
        )  # aiokafka 0.14: stop() can raise CancelledError before its first step
        await consumer.stop()


async def publish(
    bootstrap_servers: str,
    topic: str,
    key: str,
    value: bytes,
    headers: Sequence[tuple[str, bytes]] = (),
) -> None:
    from aiokafka import AIOKafkaProducer

    producer = AIOKafkaProducer(bootstrap_servers=bootstrap_servers, client_id="otc-log-contract")
    await producer.start()
    try:
        await producer.send_and_wait(
            topic, value=value, key=key.encode("utf-8"), headers=list(headers)
        )
    finally:
        await producer.stop()
