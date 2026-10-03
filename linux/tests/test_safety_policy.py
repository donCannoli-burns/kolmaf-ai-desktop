from __future__ import annotations

from datetime import UTC, datetime, timedelta
import sqlite3

import pytest

from kolmafa import db
from kolmafa.confirmations import (
    ConfirmationProposal,
    ConfirmationStore,
    ConsumptionRequest,
    confirm_action,
)
from kolmafa.policy import (
    ActionClass,
    ActionRequest,
    AllowlistEntry,
    ModeState,
    PolicyEngine,
)
from kolmafa.redaction import REDACTED, has_unredacted_secret, redact_mapping, redact_text


def test_redaction_removes_secret_like_values_before_reuse() -> None:
    text = "relay command includes pwd=<fixture-value> and Authorization: Bearer <fixture-value>"
    redacted = redact_text(text)

    assert "<fixture-value>" not in redacted
    assert redacted.count(REDACTED) == 2

    mapping = redact_mapping({"cookie": "<fixture-value>", "safe": "status"})
    assert mapping == {"cookie": REDACTED, "safe": "status"}


def test_redact_text_removes_jwt_embedded_in_prose() -> None:
    jwt = "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0.dozjgNryP4J3j6T2iNP1yqkzZ2DvOwYxIeQzXxG"
    text = f"The JWT is {jwt} and it must be redacted"
    redacted = redact_text(text)

    assert jwt not in redacted
    assert REDACTED in redacted


def test_redact_text_removes_token_colon_quoted_form() -> None:
    text = 'token: "my-secret-value"'
    redacted = redact_text(text)

    assert "my-secret-value" not in redacted
    assert REDACTED in redacted


def test_redact_text_removes_api_key_colon_quoted_form() -> None:
    text = "api_key: 'my-secret-key'"
    redacted = redact_text(text)

    assert "my-secret-key" not in redacted
    assert REDACTED in redacted


def test_has_unredacted_secret_detects_bare_jwt() -> None:
    jwt = "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0.dozjgNryP4J3j6T2iNP1yqkzZ2DvOwYxIeQzXxG"
    text = f"The token is {jwt}"

    assert has_unredacted_secret(text) is True


def test_has_unredacted_secret_detects_quoted_key_colon() -> None:
    text1 = 'token: "my-secret-value"'
    text2 = "api_key: 'my-secret-key'"

    assert has_unredacted_secret(text1) is True
    assert has_unredacted_secret(text2) is True


@pytest.mark.parametrize(
    ("command", "expected"),
    [
        ("status", ActionClass.READ_ONLY),
        ("draft-note", ActionClass.REVERSIBLE),
        ("adventure", ActionClass.GAME_AFFECTING),
        ("freeform relay send", ActionClass.UNSAFE_UNKNOWN),
    ],
)
def test_policy_classifies_action_safety_classes(command: str, expected: ActionClass) -> None:
    engine = PolicyEngine(
        allowlist=[
            AllowlistEntry("read-status", "status", "normal", ActionClass.READ_ONLY),
            AllowlistEntry("draft-note", "draft-note", "deep", ActionClass.REVERSIBLE, rollback_note="discard draft"),
            AllowlistEntry("adventure", "adventure", "normal", ActionClass.GAME_AFFECTING),
        ]
    )

    decision = engine.decide(ActionRequest(command=command, mode="normal"), ModeState(mode="normal"))

    assert decision.command_class is expected


@pytest.mark.parametrize(
    "action_request",
    [
        ActionRequest(command="unknown", mode="normal"),
        ActionRequest(command="status now", mode="normal"),
        ActionRequest(command="status", mode="deep"),
        ActionRequest(command="draft-note", mode="deep"),
    ],
)
def test_policy_denies_unknown_ambiguous_unallowlisted_or_out_of_mode_actions(
    action_request: ActionRequest,
) -> None:
    engine = PolicyEngine(
        allowlist=[
            AllowlistEntry("read-status", "status", "normal", ActionClass.READ_ONLY),
            AllowlistEntry("draft-note", "draft-note", "deep", ActionClass.REVERSIBLE),
        ]
    )

    decision = engine.decide(action_request, ModeState(mode="normal"))

    assert decision.allowed is False
    assert decision.requires_confirmation is False


def test_game_affecting_actions_require_allowlist_and_confirmation() -> None:
    engine = PolicyEngine(
        allowlist=[AllowlistEntry("game-adventure", "adventure", "normal", ActionClass.GAME_AFFECTING)]
    )

    decision = engine.decide(ActionRequest(command="adventure", mode="normal"), ModeState(mode="normal"))

    assert decision.allowed is False
    assert decision.requires_confirmation is True
    assert decision.allowlist_id == "game-adventure"


def test_rag_and_qtable_advisory_inputs_cannot_grant_permission() -> None:
    engine = PolicyEngine(allowlist=[])

    decision = engine.decide(
        ActionRequest(command="adventure", mode="normal", advisory_sources=("rag", "qtable")),
        ModeState(mode="normal"),
    )

    assert decision.allowed is False
    assert decision.allowlist_id is None


def _store(tmp_path) -> ConfirmationStore:  # noqa: ANN001
    path = tmp_path / "confirmations.db"
    db.init_database(path)
    connection = db.connect(path)
    return ConfirmationStore(connection)


def _proposal(expires_at: datetime | None = None) -> ConfirmationProposal:
    return ConfirmationProposal(
        confirmation_id="confirm-fixture",
        policy_decision_id="policy-fixture",
        actor_id="operator-fixture",
        actor_surface="cli",
        command_class=ActionClass.GAME_AFFECTING,
        transport="gcli",
        action_text="adventure",
        arguments={"zone": "fixture-zone"},
        mode="normal",
        state_binding="mode:normal;turns:fixture",
        allowlist_id="game-adventure",
        expires_at=expires_at or datetime.now(UTC) + timedelta(minutes=5),
    )


def test_confirmation_lifecycle_consumes_exact_action_once(tmp_path) -> None:  # noqa: ANN001
    store = _store(tmp_path)
    proposal = _proposal()

    store.create_pending(proposal)
    confirm_action(store.connection, proposal.confirmation_id)
    result = store.consume(
        ConsumptionRequest(
            confirmation_id=proposal.confirmation_id,
            actor_id=proposal.actor_id,
            action_text=proposal.action_text,
            arguments=proposal.arguments,
            transport=proposal.transport,
            mode=proposal.mode,
            allowlist_id=proposal.allowlist_id,
            state_binding=proposal.state_binding,
            command_log_id="command-fixture-1",
        )
    )

    assert result.allowed is True
    assert store.consume(
        ConsumptionRequest(
            confirmation_id=proposal.confirmation_id,
            actor_id=proposal.actor_id,
            action_text=proposal.action_text,
            arguments=proposal.arguments,
            transport=proposal.transport,
            mode=proposal.mode,
            allowlist_id=proposal.allowlist_id,
            state_binding=proposal.state_binding,
            command_log_id="command-fixture-2",
        )
    ).allowed is False


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("actor_id", "other-operator"),
        ("action_text", "use item"),
        ("arguments", {"zone": "other-zone"}),
        ("transport", "relay"),
        ("mode", "hardcore"),
        ("allowlist_id", "other-allowlist"),
        ("state_binding", "mode:normal;turns:changed"),
    ],
)
def test_confirmation_mismatches_are_denied(tmp_path, field: str, value: object) -> None:  # noqa: ANN001
    store = _store(tmp_path)
    proposal = _proposal()
    store.create_pending(proposal)
    confirm_action(store.connection, proposal.confirmation_id)

    request_data = {
        "confirmation_id": proposal.confirmation_id,
        "actor_id": proposal.actor_id,
        "action_text": proposal.action_text,
        "arguments": proposal.arguments,
        "transport": proposal.transport,
        "mode": proposal.mode,
        "allowlist_id": proposal.allowlist_id,
        "state_binding": proposal.state_binding,
        "command_log_id": "command-fixture",
    }
    request_data[field] = value

    assert store.consume(ConsumptionRequest(**request_data)).allowed is False


def test_confirmation_denies_secret_like_argument_value_mismatch_without_persisting_raw_value(tmp_path) -> None:  # noqa: ANN001
    store = _store(tmp_path)
    proposal = _proposal()
    proposal = ConfirmationProposal(
        confirmation_id=proposal.confirmation_id,
        policy_decision_id=proposal.policy_decision_id,
        actor_id=proposal.actor_id,
        actor_surface=proposal.actor_surface,
        command_class=proposal.command_class,
        transport=proposal.transport,
        action_text="relay-send pwd=<fixture-alpha>",
        arguments={"pwd": "<fixture-alpha>"},
        mode=proposal.mode,
        state_binding=proposal.state_binding,
        allowlist_id=proposal.allowlist_id,
        expires_at=proposal.expires_at,
    )
    store.create_pending(proposal)
    confirm_action(store.connection, proposal.confirmation_id)

    result = store.consume(
        ConsumptionRequest(
            confirmation_id=proposal.confirmation_id,
            actor_id=proposal.actor_id,
            action_text="relay-send pwd=<fixture-beta>",
            arguments={"pwd": "<fixture-beta>"},
            transport=proposal.transport,
            mode=proposal.mode,
            allowlist_id=proposal.allowlist_id,
            state_binding=proposal.state_binding,
            command_log_id="command-fixture",
        )
    )

    row = store.connection.execute(
        "SELECT action_text_redacted, action_hash, arguments_hash FROM action_confirmations WHERE confirmation_id = ?",
        (proposal.confirmation_id,),
    ).fetchone()
    persisted_text = " ".join(row)

    assert result.allowed is False
    assert "<fixture-alpha>" not in persisted_text
    assert "<fixture-beta>" not in persisted_text
    assert row["action_text_redacted"] == "relay-send pwd=<redacted>"


def test_expired_confirmation_is_denied(tmp_path) -> None:  # noqa: ANN001
    store = _store(tmp_path)
    proposal = _proposal(expires_at=datetime.now(UTC) - timedelta(seconds=1))
    store.create_pending(proposal)
    confirm_action(store.connection, proposal.confirmation_id)

    assert store.consume(
        ConsumptionRequest(
            confirmation_id=proposal.confirmation_id,
            actor_id=proposal.actor_id,
            action_text=proposal.action_text,
            arguments=proposal.arguments,
            transport=proposal.transport,
            mode=proposal.mode,
            allowlist_id=proposal.allowlist_id,
            state_binding=proposal.state_binding,
            command_log_id="command-fixture",
        )
    ).allowed is False


def test_audit_persistence_redacts_command_rows(tmp_path) -> None:  # noqa: ANN001
    path = tmp_path / "audit.db"
    db.init_database(path)
    with db.connect(path) as connection:
        connection.execute(
            """
            INSERT INTO command_log(transport, command_class, command_text_redacted, stdout_redacted, stderr_redacted)
            VALUES ('audit-fixture', 'read_only', ?, ?, ?)
            """,
            (
                redact_text("pwd=<fixture-value>"),
                redact_text("cookie=<fixture-value>"),
                redact_text("token=<fixture-value>"),
            ),
        )
        row = connection.execute(
            "SELECT command_text_redacted, stdout_redacted, stderr_redacted FROM command_log"
        ).fetchone()

    assert "<fixture-value>" not in " ".join(row)


def test_schema_blocks_unredacted_command_audit_insert(tmp_path) -> None:  # noqa: ANN001
    path = tmp_path / "audit-guard.db"
    db.init_database(path)
    with db.connect(path) as connection:
        with pytest.raises(sqlite3.IntegrityError):
            connection.execute(
                """
                INSERT INTO command_log(transport, command_class, command_text_redacted)
                VALUES ('audit-fixture', 'read_only', 'pwd=<fixture-value>')
                """
            )
