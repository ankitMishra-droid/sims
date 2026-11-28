"""Grant 3000 free AI credits once to existing workspaces.

Revision ID: 0006_existing_users_free_credits
Revises: 0005_phase10_hardening_alerts_indexes
Create Date: 2026-11-28 02:01:19.000000
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0006_existing_users_free_credits"
down_revision: Union[str, Sequence[str], None] = "0005_phase10_hardening_alerts_indexes"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

FREE_CREDIT_UNITS = 3_000_000


def upgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)
    if not insp.has_table("businesses"):
        return
    if not insp.has_table("ai_credit_accounts") or not insp.has_table("ai_credit_transactions"):
        return

    business_rows = bind.execute(
        sa.text("SELECT id, owner_user_id FROM businesses ORDER BY id ASC")
    ).fetchall()

    for business_id, owner_user_id in business_rows:
        idem_key = f"initial-grant:{business_id}"
        existing_tx = bind.execute(
            sa.text(
                "SELECT id FROM ai_credit_transactions "
                "WHERE business_id = :bid "
                "AND transaction_type = 'INITIAL_GRANT' "
                "AND idempotency_key = :idem"
            ),
            {"bid": business_id, "idem": idem_key},
        ).first()
        if existing_tx is not None:
            continue

        account = bind.execute(
            sa.text(
                "SELECT id, available_units, reserved_units, lifetime_granted_units "
                "FROM ai_credit_accounts WHERE business_id = :bid"
            ),
            {"bid": business_id},
        ).first()

        if account is None:
            bind.execute(
                sa.text(
                    "INSERT INTO ai_credit_accounts "
                    "(business_id, available_units, reserved_units, lifetime_granted_units, "
                    "lifetime_consumed_units, lifetime_refunded_units, status, plan_tier) "
                    "VALUES (:bid, :units, 0, :units, 0, 0, 'ACTIVE', 'standard')"
                ),
                {"bid": business_id, "units": FREE_CREDIT_UNITS},
            )
            available_before = 0
            reserved_before = 0
        else:
            _, available_before, reserved_before, lifetime_granted_before = account
            available_before = int(available_before or 0)
            reserved_before = int(reserved_before or 0)
            lifetime_granted_before = int(lifetime_granted_before or 0)
            bind.execute(
                sa.text(
                    "UPDATE ai_credit_accounts "
                    "SET available_units = :available_after, "
                    "lifetime_granted_units = :lifetime_granted_after "
                    "WHERE business_id = :bid"
                ),
                {
                    "available_after": available_before + FREE_CREDIT_UNITS,
                    "lifetime_granted_after": lifetime_granted_before + FREE_CREDIT_UNITS,
                    "bid": business_id,
                },
            )

        bind.execute(
            sa.text(
                "INSERT INTO ai_credit_transactions "
                "(transaction_uid, business_id, user_id, request_id, idempotency_key, "
                "transaction_type, credit_delta_units, amount_units, "
                "available_before_units, available_after_units, "
                "reserved_before_units, reserved_after_units, status, operation_type, "
                "pricing_version, reason) "
                "VALUES (:uid, :bid, :uid_user, :request_id, :idem, "
                "'INITIAL_GRANT', :units, :units, "
                ":available_before, :available_after, "
                ":reserved_before, :reserved_after, 'POSTED', "
                "'account_initialization', '2026-11-phase9-v1', "
                "'Existing workspace free AI credit allocation')"
            ),
            {
                "uid": f"initial-grant-{business_id}",
                "bid": business_id,
                "uid_user": owner_user_id,
                "request_id": f"init-{business_id}",
                "idem": idem_key,
                "units": FREE_CREDIT_UNITS,
                "available_before": available_before,
                "available_after": available_before + FREE_CREDIT_UNITS,
                "reserved_before": reserved_before,
                "reserved_after": reserved_before,
            },
        )


def downgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)
    if not insp.has_table("ai_credit_transactions") or not insp.has_table("ai_credit_accounts"):
        return

    grants = bind.execute(
        sa.text(
            "SELECT id, business_id, amount_units, available_after_units FROM ai_credit_transactions "
            "WHERE transaction_type = 'INITIAL_GRANT' "
            "AND reason = 'Existing workspace free AI credit allocation'"
        )
    ).fetchall()
    for tx_id, business_id, amount_units, available_after_units in grants:
        account = bind.execute(
            sa.text(
                "SELECT available_units, lifetime_granted_units "
                "FROM ai_credit_accounts WHERE business_id = :bid"
            ),
            {"bid": business_id},
        ).first()
        if account is not None:
            amount = int(amount_units)
            later_transaction = bind.execute(
                sa.text(
                    "SELECT id FROM ai_credit_transactions "
                    "WHERE business_id = :bid AND id > :tx_id LIMIT 1"
                ),
                {"bid": business_id, "tx_id": tx_id},
            ).first()
            if later_transaction is not None or int(account.available_units) != int(available_after_units):
                raise RuntimeError(
                    "Cannot downgrade the existing-user credit grant after the workspace's credit balance changed."
                )
            bind.execute(
                sa.text(
                    "UPDATE ai_credit_accounts "
                    "SET available_units = available_units - :amount, "
                    "lifetime_granted_units = lifetime_granted_units - :amount "
                    "WHERE business_id = :bid"
                ),
                {"amount": amount, "bid": business_id},
            )
        bind.execute(
            sa.text("DELETE FROM ai_credit_transactions WHERE id = :tx_id"),
            {"tx_id": tx_id},
        )
