from __future__ import annotations

from types import SimpleNamespace

import pytest

from scripts.publish_economic_taxonomy import _parser, _publication_principal


def test_publication_principal_uses_configured_admin_identity():
    principal = _publication_principal(
        SimpleNamespace(
            admin_api_key="configured-secret",
            admin_principal_id="admin:release-manager",
        ),
        "configured-secret",
    )

    assert principal.subject == "admin:release-manager"
    assert principal.auth_method == "admin_api_key"
    assert principal.roles == frozenset({"taxonomy:review"})


@pytest.mark.parametrize(
    ("admin_api_key", "admin_principal_id"),
    [("", "admin:release-manager"), ("configured-secret", "")],
)
def test_publication_principal_fails_closed_without_admin_configuration(
    admin_api_key, admin_principal_id
):
    with pytest.raises(RuntimeError, match="admin_identity_not_configured"):
        _publication_principal(
            SimpleNamespace(
                admin_api_key=admin_api_key,
                admin_principal_id=admin_principal_id,
            ),
            "configured-secret",
        )


@pytest.mark.parametrize("credential", (None, "wrong-secret"))
def test_publication_principal_rejects_unauthenticated_caller(credential):
    with pytest.raises(PermissionError, match="admin_authentication_failed"):
        _publication_principal(
            SimpleNamespace(
                admin_api_key="configured-secret",
                admin_principal_id="admin:release-manager",
            ),
            credential,
        )


def test_parser_does_not_accept_caller_supplied_audit_identity():
    with pytest.raises(SystemExit):
        _parser().parse_args(
            [
                "--capability-id",
                "00000000-0000-0000-0000-000000000001",
                "--mode",
                "economic",
                "--actor",
                "forged:principal",
            ]
        )
