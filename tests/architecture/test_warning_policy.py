"""DeprecationWarning-as-error policy (pyproject.toml `filterwarnings`)."""

import importlib
import warnings

import pytest


def test_deprecation_warning_is_an_error_under_the_pytest_policy() -> None:
    # Claim: a DeprecationWarning raised in a test fails it (one targeted filter exempts).
    with pytest.raises(DeprecationWarning, match="policy probe"):
        warnings.warn("policy probe", DeprecationWarning, stacklevel=1)


def test_testcontainers_nats_import_is_exempted_by_the_one_targeted_filter() -> None:
    # Claim: the single targeted filter is effective, i.e. the import that emits the library's own
    # DeprecationWarning does not fail under the error policy.
    importlib.import_module("testcontainers.community.nats")
