"""The population the committed sweep (`scripts/notification-template-sweep.py`) mutates, pinned.

The sweep ENUMERATES the attribute reads of the event, payload and list elements in the seven
templates by AST; this test pins what it finds, as literals, so a read added to or removed from a
template names itself and the sweep is re-run (`--all`: 109 sites, 198 mutations, 198 caught at
the time of writing; the sentinels are `--sentinels`). The enumeration must include the reads inside
list elements and conditions (#8's 95th site was a nested list element: `step.Step`), and must not
count a name that only appears in a comment, a docstring or a string.
"""

import importlib.util
from pathlib import Path
from types import ModuleType

SCRIPT = Path(__file__).resolve().parents[5] / "scripts" / "notification-template-sweep.py"


def load() -> ModuleType:
    spec = importlib.util.spec_from_file_location("notification_template_sweep", SCRIPT)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_the_population_is_the_recorded_count_per_template_and_per_kind() -> None:
    sites = load().enumerate_sites()

    per_file: dict[str, int] = {}
    per_kind: dict[str, int] = {}
    for site in sites:
        per_file[site.path.name] = per_file.get(site.path.name, 0) + 1
        per_kind[site.kind] = per_kind.get(site.kind, 0) + 1

    assert per_file == {
        "invoice_issued.py": 16,
        "order_cancelled.py": 17,
        "order_completed.py": 14,
        "order_confirmed.py": 14,
        "order_despatched.py": 18,
        "order_placed.py": 14,
        "payment_received.py": 16,
    }
    assert per_kind == {"collection": 3, "enum": 5, "id": 21, "instant": 7, "int": 6, "string": 67}
    assert len(sites) == 109


def test_the_nested_list_element_reads_are_in_the_population() -> None:
    reads = {(s.path.name, s.text) for s in load().enumerate_sites()}

    assert ("order_cancelled.py", "step.step") in reads, "the site #8's survivor lived in"
    assert ("order_despatched.py", "line.product_code") in reads
    assert ("order_despatched.py", "line.units") in reads
    assert ("order_cancelled.py", "payload.compensation_steps") in reads


def test_every_instant_and_integer_site_is_classified_as_such() -> None:
    sites = load().enumerate_sites()
    instants = {s.field for s in sites if s.kind == "instant"}
    integers = {s.field for s in sites if s.kind == "int"}
    assert instants == {
        "order_date", "confirmed_at", "despatch_date", "invoice_date",
        "value_date", "completed_at", "cancelled_at",
    }  # fmt: skip
    assert integers == {"total_amount", "amount", "units"}  # units: the despatch line quantity
