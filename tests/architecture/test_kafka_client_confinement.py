"""Which module may hold which Kafka client (order_saga_orchestrator design 13.1; #8's two rules).

The `fact-producer-confinement` import-linter contract keeps `aiokafka` out of every `application`
and `presentation` package. It cannot say WHICH infrastructure module may hold WHICH client, and
the saga adds the second client. This test reads the AST of every `services/*/src/**/*.py` and
asserts:

1. the modules that import `aiokafka` are exactly the literal set below (Orders' relay publisher,
   the copies of it in Fulfillment and Billing, the saga's subscriber, Notifications' fact
   subscriber, the Projector's, and the three dead-letter publishers of Orders, the Projector and
   Notifications, feature 27 `R16`), `dlq_depth.py` (S5) and the three Kafka admin probes of the
   readiness checks (S6, `R60`);
2. the publisher names no consumer-side name and the subscriber no producer-side name.

An AST is read so that a mention in a comment, a docstring or a string is not an import, and
everything that IS an import is counted wherever it sits: inside `if TYPE_CHECKING:`, aliased
(`from aiokafka import AIOKafkaConsumer as C`), or reached as an attribute
(`aiokafka.AIOKafkaConsumer`).

Sentinels build a temporary tree and prove each of those forms is seen, and that text which only
names the library is not (defeat-list rows 4, 5, 6, 11): a census that "finds nothing" means nothing
until it has been shown to find something.
"""

import ast
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
PUBLISHER = "otc_orders.infrastructure.outbox.kafka_publisher"
SUBSCRIBER = "otc_orders.infrastructure.messaging.kafka_fact_subscriber"
# Feature 23: Notifications' fact consumer is the second consumer (it consumes, it emits no fact).
NOTIFICATIONS_SUBSCRIBER = "otc_notifications.infrastructure.messaging.kafka_fact_subscriber"
# Feature 24: the Projector's fact consumer is the third consumer (it consumes, it emits no fact).
PROJECTOR_SUBSCRIBER = "otc_projector.infrastructure.messaging.kafka_fact_subscriber"
# Feature 17: Fulfillment's relay copy is the second producer (parity-guarded against Orders').
FULFILLMENT_PUBLISHER = "otc_fulfillment.infrastructure.outbox.kafka_publisher"
# Feature 19: Billing's relay copy is the third producer (parity-guarded against Orders').
BILLING_PUBLISHER = "otc_billing.infrastructure.outbox.kafka_publisher"
# Feature 27 (`R16`, `OR2`): the dead-letter publisher, canonical in Orders and copied to the two
# other fact consumers (parity-guarded by `test_observability_copy_parity.py`). A producer: it
# writes the original bytes of a failed record to `<topic>.dlq`, it emits no fact.
ORDERS_DEAD_LETTERS = "otc_orders.infrastructure.messaging.dead_letter_publisher"
PROJECTOR_DEAD_LETTERS = "otc_projector.infrastructure.messaging.dead_letter_publisher"
NOTIFICATIONS_DEAD_LETTERS = "otc_notifications.infrastructure.messaging.dead_letter_publisher"
DEAD_LETTER_PUBLISHERS = (ORDERS_DEAD_LETTERS, PROJECTOR_DEAD_LETTERS, NOTIFICATIONS_DEAD_LETTERS)
# Feature 27 (`R59`, S5.6): the dead-letter depth reader. A CONSUMER-side client that never joins a
# group (it reads offsets from the broker), so it may name no producer-side class.
DLQ_DEPTH = "otc_orders.infrastructure.messaging.dlq_depth"
# Feature 27 (`R60`, S6.2): the readiness probe of the fact stream, canonical in Orders and copied
# to the two other fact consumers (parity-guarded). An ADMIN client: it names neither a producer
# nor a consumer class.
HEALTH_PROBES = (
    "otc_orders.infrastructure.health.kafka_probe",
    "otc_notifications.infrastructure.health.kafka_probe",
    "otc_projector.infrastructure.health.kafka_probe",
)
EXPECTED_IMPORTERS = {
    *DEAD_LETTER_PUBLISHERS,
    *HEALTH_PROBES,
    DLQ_DEPTH,
    PUBLISHER,
    SUBSCRIBER,
    NOTIFICATIONS_SUBSCRIBER,
    PROJECTOR_SUBSCRIBER,
    FULFILLMENT_PUBLISHER,
    BILLING_PUBLISHER,
}
CONSUMER_SIDE = {"AIOKafkaConsumer", "TopicPartition", "ConsumerRecord"}
PRODUCER_SIDE = {"AIOKafkaProducer"}


def module_name(root: Path, path: Path) -> str:
    relative = path.relative_to(root / "services")
    parts = relative.parts  # <service>/src/otc_<service>/...
    return ".".join((*parts[2:-1], path.stem))


def aiokafka_names(source: str) -> set[str] | None:
    """The `aiokafka` names a module imports or reaches (`None`: it does not touch the library)."""
    tree = ast.parse(source)
    found: set[str] = set()
    touches = False
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name.split(".")[0] == "aiokafka":
                    touches = True
                    found.add(alias.name)
        elif (
            isinstance(node, ast.ImportFrom)
            and node.level == 0
            and node.module
            and node.module.split(".")[0] == "aiokafka"
        ):
            touches = True
            found.update(alias.name for alias in node.names)
        elif (
            isinstance(node, ast.Attribute)
            and isinstance(node.value, ast.Name)
            and node.value.id == "aiokafka"
        ):
            found.add(node.attr)
    return found if touches else None


def survey(root: Path) -> dict[str, set[str]]:
    """module -> the aiokafka names it uses, for every service module that imports the library."""
    result: dict[str, set[str]] = {}
    for path in sorted(root.glob("services/*/src/**/*.py")):
        if "__pycache__" in path.parts:
            continue
        names = aiokafka_names(path.read_text(encoding="utf-8"))
        if names is not None:
            result[module_name(root, path)] = names
    return result


def violations(found: dict[str, set[str]]) -> list[str]:
    problems: list[str] = []
    if set(found) != EXPECTED_IMPORTERS:
        problems.append(
            f"the modules importing aiokafka are {sorted(found)}, "
            f"expected {sorted(EXPECTED_IMPORTERS)}"
        )
    for publisher in (PUBLISHER, FULFILLMENT_PUBLISHER, BILLING_PUBLISHER, *DEAD_LETTER_PUBLISHERS):
        if consumer_names := found.get(publisher, set()) & CONSUMER_SIDE:
            problems.append(f"the publisher names consumer-side {sorted(consumer_names)}")
    for subscriber in (SUBSCRIBER, NOTIFICATIONS_SUBSCRIBER, PROJECTOR_SUBSCRIBER, DLQ_DEPTH):
        if producer_names := found.get(subscriber, set()) & PRODUCER_SIDE:
            problems.append(f"the subscriber names producer-side {sorted(producer_names)}")
    for probe in HEALTH_PROBES:
        if side_names := found.get(probe, set()) & (CONSUMER_SIDE | PRODUCER_SIDE):
            problems.append(
                f"the health probe {probe} names {sorted(side_names)}: it is an admin client"
            )
    return problems


def test_the_modules_importing_aiokafka_are_exactly_the_publishers_and_the_subscribers() -> None:
    found = survey(REPO_ROOT)

    assert violations(found) == []
    assert "AIOKafkaProducer" in found[PUBLISHER], "the census sees the publisher's real import"
    assert "AIOKafkaProducer" in found[FULFILLMENT_PUBLISHER], "and Fulfillment's"
    assert "AIOKafkaProducer" in found[BILLING_PUBLISHER], "and Billing's"
    assert "AIOKafkaConsumer" in found[SUBSCRIBER], "and the subscriber's"
    assert "AIOKafkaConsumer" in found[NOTIFICATIONS_SUBSCRIBER], "and Notifications'"
    assert "AIOKafkaConsumer" in found[PROJECTOR_SUBSCRIBER], "and the Projector's"
    for dead_letters in DEAD_LETTER_PUBLISHERS:
        assert "AIOKafkaProducer" in found[dead_letters], f"and {dead_letters}'s producer"
    assert "AIOKafkaConsumer" in found[DLQ_DEPTH], "and the dead-letter depth reader's consumer"


# ---- sentinels: each form of import must be seen, and a mere mention must not be


def tree_with(tmp_path: Path, files: dict[str, str]) -> dict[str, set[str]]:
    for relative, content in files.items():
        target = tmp_path / "services" / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
    return survey(tmp_path)


PUBLISHER_FILE = "orders/src/otc_orders/infrastructure/outbox/kafka_publisher.py"
SUBSCRIBER_FILE = "orders/src/otc_orders/infrastructure/messaging/kafka_fact_subscriber.py"
FULFILLMENT_PUBLISHER_FILE = (
    "fulfillment/src/otc_fulfillment/infrastructure/outbox/kafka_publisher.py"
)
BILLING_PUBLISHER_FILE = "billing/src/otc_billing/infrastructure/outbox/kafka_publisher.py"
NOTIFICATIONS_SUBSCRIBER_FILE = (
    "notifications/src/otc_notifications/infrastructure/messaging/kafka_fact_subscriber.py"
)
PROJECTOR_SUBSCRIBER_FILE = (
    "projector/src/otc_projector/infrastructure/messaging/kafka_fact_subscriber.py"
)
ORDERS_DEAD_LETTERS_FILE = "orders/src/otc_orders/infrastructure/messaging/dead_letter_publisher.py"
PROJECTOR_DEAD_LETTERS_FILE = (
    "projector/src/otc_projector/infrastructure/messaging/dead_letter_publisher.py"
)
NOTIFICATIONS_DEAD_LETTERS_FILE = (
    "notifications/src/otc_notifications/infrastructure/messaging/dead_letter_publisher.py"
)
DLQ_DEPTH_FILE = "orders/src/otc_orders/infrastructure/messaging/dlq_depth.py"
HEALTH_PROBE_FILES = (
    "orders/src/otc_orders/infrastructure/health/kafka_probe.py",
    "notifications/src/otc_notifications/infrastructure/health/kafka_probe.py",
    "projector/src/otc_projector/infrastructure/health/kafka_probe.py",
)
CLEAN = {
    **dict.fromkeys(HEALTH_PROBE_FILES, "from aiokafka.admin import AIOKafkaAdminClient\n"),
    DLQ_DEPTH_FILE: "from aiokafka import AIOKafkaConsumer, TopicPartition\n",
    ORDERS_DEAD_LETTERS_FILE: "from aiokafka import AIOKafkaProducer\n",
    PROJECTOR_DEAD_LETTERS_FILE: "from aiokafka import AIOKafkaProducer\n",
    NOTIFICATIONS_DEAD_LETTERS_FILE: "from aiokafka import AIOKafkaProducer\n",
    PUBLISHER_FILE: "from aiokafka import AIOKafkaProducer\n",
    SUBSCRIBER_FILE: "from aiokafka import AIOKafkaConsumer\n",
    NOTIFICATIONS_SUBSCRIBER_FILE: "from aiokafka import AIOKafkaConsumer\n",
    PROJECTOR_SUBSCRIBER_FILE: "from aiokafka import AIOKafkaConsumer\n",
    FULFILLMENT_PUBLISHER_FILE: "from aiokafka import AIOKafkaProducer\n",
    BILLING_PUBLISHER_FILE: "from aiokafka import AIOKafkaProducer\n",
}


def test_sentinel_a_consumer_import_added_to_fulfillments_publisher_is_reported(
    tmp_path: Path,
) -> None:
    files = CLEAN | {
        FULFILLMENT_PUBLISHER_FILE: "from aiokafka import AIOKafkaProducer, AIOKafkaConsumer\n"
    }
    [problem] = violations(tree_with(tmp_path, files))
    assert "publisher names consumer-side ['AIOKafkaConsumer']" in problem


def test_sentinel_a_consumer_import_added_to_billings_publisher_is_reported(
    tmp_path: Path,
) -> None:
    files = CLEAN | {
        BILLING_PUBLISHER_FILE: "from aiokafka import AIOKafkaProducer, AIOKafkaConsumer\n"
    }
    [problem] = violations(tree_with(tmp_path, files))
    assert "publisher names consumer-side ['AIOKafkaConsumer']" in problem


def test_sentinel_a_producer_import_added_to_the_dead_letter_depth_reader_is_reported(
    tmp_path: Path,
) -> None:
    files = CLEAN | {DLQ_DEPTH_FILE: "from aiokafka import AIOKafkaConsumer, AIOKafkaProducer\n"}
    [problem] = violations(tree_with(tmp_path, files))
    assert "subscriber names producer-side ['AIOKafkaProducer']" in problem


@pytest.mark.parametrize("probe_file", HEALTH_PROBE_FILES)
@pytest.mark.parametrize("side", ["AIOKafkaProducer", "AIOKafkaConsumer"])
def test_sentinel_a_producer_or_consumer_import_added_to_a_health_probe_is_reported(
    tmp_path: Path, probe_file: str, side: str
) -> None:
    files = CLEAN | {probe_file: f"from aiokafka import AIOKafkaAdminClient, {side}\n"}
    [problem] = violations(tree_with(tmp_path, files))
    assert f"names ['{side}']: it is an admin client" in problem


def test_sentinel_the_clean_pair_is_accepted(tmp_path: Path) -> None:
    assert violations(tree_with(tmp_path, CLEAN)) == []


def test_sentinel_a_producer_import_added_to_the_subscriber_is_reported(tmp_path: Path) -> None:
    files = CLEAN | {SUBSCRIBER_FILE: "from aiokafka import AIOKafkaConsumer, AIOKafkaProducer\n"}
    [problem] = violations(tree_with(tmp_path, files))
    assert "subscriber names producer-side ['AIOKafkaProducer']" in problem


def test_sentinel_a_producer_import_added_to_notifications_subscriber_is_reported(
    tmp_path: Path,
) -> None:
    files = CLEAN | {
        NOTIFICATIONS_SUBSCRIBER_FILE: "from aiokafka import AIOKafkaConsumer, AIOKafkaProducer\n"
    }
    [problem] = violations(tree_with(tmp_path, files))
    assert "subscriber names producer-side ['AIOKafkaProducer']" in problem


def test_sentinel_a_producer_import_added_to_the_projectors_subscriber_is_reported(
    tmp_path: Path,
) -> None:
    files = CLEAN | {
        PROJECTOR_SUBSCRIBER_FILE: "from aiokafka import AIOKafkaConsumer, AIOKafkaProducer\n"
    }
    [problem] = violations(tree_with(tmp_path, files))
    assert "subscriber names producer-side ['AIOKafkaProducer']" in problem


def test_sentinel_a_second_projector_module_importing_aiokafka_is_reported(tmp_path: Path) -> None:
    other = "projector/src/otc_projector/presentation/projector_facts_consumer.py"
    [problem] = violations(
        tree_with(tmp_path, CLEAN | {other: "from aiokafka import AIOKafkaConsumer\n"})
    )
    assert "otc_projector.presentation.projector_facts_consumer" in problem


def test_sentinel_projector_subscriber_missing_is_reported(tmp_path: Path) -> None:
    files = {k: v for k, v in CLEAN.items() if k != PROJECTOR_SUBSCRIBER_FILE}
    [problem] = violations(tree_with(tmp_path, files))
    assert "the modules importing aiokafka are" in problem


def test_sentinel_notifications_subscriber_missing_is_reported(tmp_path: Path) -> None:
    files = {k: v for k, v in CLEAN.items() if k != NOTIFICATIONS_SUBSCRIBER_FILE}
    [problem] = violations(tree_with(tmp_path, files))
    assert "the modules importing aiokafka are" in problem


def test_sentinel_a_consumer_import_added_to_the_publisher_is_reported(tmp_path: Path) -> None:
    files = CLEAN | {PUBLISHER_FILE: "from aiokafka import AIOKafkaProducer, TopicPartition\n"}
    [problem] = violations(tree_with(tmp_path, files))
    assert "publisher names consumer-side ['TopicPartition']" in problem


def test_sentinel_a_third_module_importing_aiokafka_is_reported(tmp_path: Path) -> None:
    other = "orders/src/otc_orders/infrastructure/saga/command_dispatcher.py"
    [problem] = violations(tree_with(tmp_path, CLEAN | {other: "import aiokafka\n"}))
    assert "otc_orders.infrastructure.saga.command_dispatcher" in problem


def test_sentinel_an_aliased_import_is_counted_by_its_real_name(tmp_path: Path) -> None:
    files = CLEAN | {PUBLISHER_FILE: "from aiokafka import AIOKafkaConsumer as C\n"}
    [problem] = violations(tree_with(tmp_path, files))
    assert "publisher names consumer-side ['AIOKafkaConsumer']" in problem


def test_sentinel_an_import_inside_type_checking_is_counted(tmp_path: Path) -> None:
    source = "from typing import TYPE_CHECKING\nif TYPE_CHECKING:\n    import aiokafka\n"
    other = "orders/src/otc_orders/application/ports/hidden.py"
    [problem] = violations(tree_with(tmp_path, CLEAN | {other: source}))
    assert "otc_orders.application.ports.hidden" in problem


def test_sentinel_an_attribute_reach_is_counted(tmp_path: Path) -> None:
    files = CLEAN | {PUBLISHER_FILE: "import aiokafka\nclient = aiokafka.AIOKafkaConsumer\n"}
    [problem] = violations(tree_with(tmp_path, files))
    assert "publisher names consumer-side ['AIOKafkaConsumer']" in problem


def test_sentinel_text_that_only_names_the_library_is_not_an_import(tmp_path: Path) -> None:
    mention = (
        '# import aiokafka\nDOC = """from aiokafka import AIOKafkaProducer"""\nNAME = "aiokafka"\n'
    )
    other = "orders/src/otc_orders/application/ports/mention.py"
    assert violations(tree_with(tmp_path, CLEAN | {other: mention})) == []


def test_sentinel_another_services_import_is_reported_too(tmp_path: Path) -> None:
    other = "billing/src/otc_billing/infrastructure/consumer.py"
    [problem] = violations(
        tree_with(tmp_path, CLEAN | {other: "from aiokafka import AIOKafkaConsumer\n"})
    )
    assert "otc_billing.infrastructure.consumer" in problem


@pytest.mark.parametrize(
    "file",
    [ORDERS_DEAD_LETTERS_FILE, PROJECTOR_DEAD_LETTERS_FILE, NOTIFICATIONS_DEAD_LETTERS_FILE],
)
def test_sentinel_a_consumer_import_added_to_a_dead_letter_publisher_is_reported(
    tmp_path: Path, file: str
) -> None:
    files = CLEAN | {file: "from aiokafka import AIOKafkaProducer, AIOKafkaConsumer\n"}
    [problem] = violations(tree_with(tmp_path, files))
    assert "publisher names consumer-side ['AIOKafkaConsumer']" in problem


@pytest.mark.parametrize(
    "file",
    [ORDERS_DEAD_LETTERS_FILE, PROJECTOR_DEAD_LETTERS_FILE, NOTIFICATIONS_DEAD_LETTERS_FILE],
)
def test_sentinel_a_missing_dead_letter_publisher_is_reported(tmp_path: Path, file: str) -> None:
    [problem] = violations(tree_with(tmp_path, {k: v for k, v in CLEAN.items() if k != file}))
    assert "the modules importing aiokafka are" in problem


def test_sentinel_a_producer_under_orders_application_is_reported(tmp_path: Path) -> None:
    """S4.9: the literal grew, so the rule is re-armed on the layer that must stay out."""
    other = "orders/src/otc_orders/application/ports/producer.py"
    [problem] = violations(
        tree_with(tmp_path, CLEAN | {other: "from aiokafka import AIOKafkaProducer\n"})
    )
    assert "otc_orders.application.ports.producer" in problem


def test_sentinel_an_aliased_producer_in_presentation_is_reported(tmp_path: Path) -> None:
    other = "orders/src/otc_orders/presentation/saga_facts_consumer.py"
    [problem] = violations(
        tree_with(tmp_path, CLEAN | {other: "from aiokafka import AIOKafkaProducer as P\n"})
    )
    assert "otc_orders.presentation.saga_facts_consumer" in problem


def test_sentinel_a_dead_letter_module_in_another_service_is_reported(tmp_path: Path) -> None:
    other = "billing/src/otc_billing/infrastructure/messaging/dead_letter_publisher.py"
    [problem] = violations(
        tree_with(tmp_path, CLEAN | {other: "from aiokafka import AIOKafkaProducer\n"})
    )
    assert "otc_billing.infrastructure.messaging.dead_letter_publisher" in problem
