"""The operator identity (`openapi.yaml` `/auth/login`, `domain-model.md` section 9: a single
operator identity, deliberately not multi-tenant)."""

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class OperatorIdentity:
    """Who `GET /auth/me` describes. The password is NOT part of it: the secret lives in the
    adapter that checks it (`infrastructure.operator_directory`), never in a value the application
    passes around."""

    username: str
    display_name: str
    roles: tuple[str, ...]
