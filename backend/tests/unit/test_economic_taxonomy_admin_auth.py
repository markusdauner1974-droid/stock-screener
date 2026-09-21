from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from app.api.v1.config import require_admin
from app.domain.economic_taxonomy.contracts import AdminPrincipal


def _settings(*, key="secret", principal="operator:alice"):
    return SimpleNamespace(admin_api_key=key, admin_principal_id=principal)


def test_valid_admin_key_returns_trusted_principal():
    principal = require_admin(x_admin_key="secret", settings=_settings())

    assert principal == AdminPrincipal(
        subject="operator:alice",
        auth_method="admin_api_key",
        roles=frozenset({"taxonomy:review"}),
    )


@pytest.mark.parametrize(
    "configured_key, configured_principal",
    [(None, "operator:alice"), ("secret", None), ("", "operator:alice"), ("secret", "")],
)
def test_missing_admin_configuration_fails_closed(
    configured_key, configured_principal
):
    with pytest.raises(HTTPException) as error:
        require_admin(
            x_admin_key="secret",
            settings=_settings(key=configured_key, principal=configured_principal),
        )

    assert error.value.status_code == 503


def test_invalid_key_does_not_return_a_principal():
    with pytest.raises(HTTPException) as error:
        require_admin(x_admin_key="wrong", settings=_settings())

    assert error.value.status_code == 401


def test_bearer_key_authenticates_the_configured_principal():
    principal = require_admin(
        authorization="Bearer secret", settings=_settings()
    )

    assert principal.subject == "operator:alice"

