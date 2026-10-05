"""`python -m otc_seed`: seed the four stores of the development stack, once, idempotently.

Exit codes: 0 = every store holds the dataset (added or already present); 1 = a store refused
(unreachable, not migrated to head, rejected a row); 2 = no credential configured.
The report is one JSON object on stdout: rows/documents ADDED by this run, per store and table
(a second run prints zeros).
"""

import asyncio
import json
import sys

from pydantic import ValidationError

from otc_seed.application import run_seed
from otc_seed.composition import build_runtime
from otc_seed.infrastructure.settings import SeedSettings


async def run() -> int:
    try:
        settings = SeedSettings()
    except ValidationError as error:
        print(f"seed: configuration refused: {error}", file=sys.stderr)
        return 2
    runtime = build_runtime(settings)
    try:
        report = await run_seed(runtime.targets)
    except Exception as error:
        print(f"seed: FAILED: {type(error).__name__}: {error}", file=sys.stderr)
        return 1
    finally:
        await runtime.aclose()
    print(json.dumps({"added": report.added, "totalAdded": report.total_added}, indent=2))
    return 0


def main() -> int:
    return asyncio.run(run())
