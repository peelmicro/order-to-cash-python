"""A7: `consumer_name.py` is a byte-identical copy of Orders' (the closed consumer vocabulary)."""

from pathlib import Path

from otc_projector.infrastructure.messaging.consumer_name import ConsumerName

SERVICES = Path(__file__).resolve().parents[3]
COPY = SERVICES / "projector/src/otc_projector/infrastructure/messaging/consumer_name.py"
ORIGINAL = SERVICES / "orders/src/otc_orders/infrastructure/messaging/consumer_name.py"


def test_the_projectors_consumer_name_is_a_byte_identical_copy_of_orders() -> None:
    assert COPY.read_bytes() == ORIGINAL.read_bytes()


def test_the_projector_consumer_name_value_is_projector() -> None:
    assert ConsumerName.PROJECTOR.value == "projector"
