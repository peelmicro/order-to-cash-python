from otc_seed.__main__ import main


def test_seed_cli_exits_zero() -> None:
    assert main() == 0
