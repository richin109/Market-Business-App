"""Reconcile the settings seed with Capability 9.1.

Revision ID: 0012_settings_catalog
Revises: 0011_category_rule_casefold
"""

import sqlalchemy as sa
from alembic import op

revision = "0012_settings_catalog"
down_revision = "0011_category_rule_casefold"
branch_labels = None
depends_on = None


SETTINGS = (
    ("business_timezone", "America/New_York", "IANA timezone used for business dates."),
    ("currency", "USD", "Single operating currency."),
    ("cost_review_threshold_days", "90", "Cost review age threshold in days."),
    ("expiry_scan_interval_minutes", "240", "Expiry scan cadence in minutes."),
    (
        "image_allowed_media_types",
        "image/jpeg,image/png,application/pdf",
        "Allowed image media types.",
    ),
    ("image_max_bytes", "10000000", "Maximum image upload size in bytes."),
    ("image_max_dimension_px", "10000", "Maximum image dimension in pixels."),
    ("item_mapping_suggestion_limit", "10", "Maximum ranked item mapping suggestions."),
    ("low_stock_alert_min_shelf_life_days", "30", "Minimum shelf life for low-stock alerts."),
    ("low_stock_threshold_pct", "20", "Low-stock threshold percentage."),
    ("market_ranking_min_visits", "5", "Minimum visits for market rankings."),
    ("mileage_rate", "0.67", "Mileage rate per mile."),
    ("ocr_engine", "tesseract-opencv", "Configured local OCR engine."),
    ("phash_duplicate_threshold", "6", "Maximum perceptual-hash distance for a near match."),
    ("receipt_image_extraction_enabled", "No", "Whether receipt image extraction is enabled."),
    ("receipt_image_min_dimension_px", "100", "Minimum dimension for receipt image candidates."),
    ("receipt_raw_retention_days", None, "Raw receipt retention; NULL until owner approval."),
    ("receipt_source_retention_days", None, "Receipt source retention; NULL until owner approval."),
    ("safety_stock_pct", "20", "Workbook compatibility value; inactive."),
    (
        "session_idle_timeout_minutes",
        "120",
        "Idle session timeout; absolute lifetime remains fixed.",
    ),
    ("square_fee_fixed_amount", "0.10", "Fixed Square transaction fee."),
    ("square_fee_rate", "0.026", "Square transaction fee rate."),
    (
        "store_alias_normalization_version",
        "casefold-trim-whitespace-punctuation-store-number-v1",
        "Store alias key normalization version.",
    ),
    ("tax_year", "2026", "Screen default tax year; record dates determine tax year."),
    ("testing_mode", "No", "Whether test-record mode is enabled."),
    ("week_starts_on", "Monday", "Locked Monday business-week start."),
    ("weekly_profit_goal", "300.00", "Weekly profit goal."),
    ("backup_destination_reference", None, "ADMIN-only backup destination reference."),
    ("backup_retention_period_days", None, "ADMIN-only backup retention period."),
    (
        "backup_encryption_key_owner",
        None,
        "ADMIN-only encryption-key owner; never store key material.",
    ),
    ("backup_restore_test_owner", None, "ADMIN-only restore-test owner."),
)
LEGACY_SETTINGS = {
    "business_timezone",
    "currency",
    "tax_year",
    "receipt_source_retention_days",
    "receipt_raw_retention_days",
    "week_starts_on",
}


def upgrade() -> None:
    connection = op.get_bind()
    connection.execute(
        sa.text("UPDATE tbl_settings SET key = 'week_starts_on' WHERE key = 'week_start'")
    )
    connection.execute(
        sa.text("UPDATE tbl_settings SET value = 'Monday' WHERE key = 'week_starts_on'")
    )
    with op.batch_alter_table("tbl_settings") as batch_op:
        batch_op.alter_column("value", existing_type=sa.Text(), nullable=True)
    connection.execute(
        sa.text(
            "UPDATE tbl_settings SET value = NULL WHERE key IN "
            "('receipt_source_retention_days', 'receipt_raw_retention_days') AND value = ''"
        )
    )

    settings_table = sa.table(
        "tbl_settings",
        sa.column("key", sa.String(length=100)),
        sa.column("value", sa.Text()),
        sa.column("description", sa.Text()),
    )
    existing = set(connection.execute(sa.select(settings_table.c.key)).scalars())
    missing = [
        {"key": key, "value": value, "description": description}
        for key, value, description in SETTINGS
        if key not in existing
    ]
    if missing:
        op.bulk_insert(settings_table, missing)


def downgrade() -> None:
    connection = op.get_bind()
    settings_table = sa.table("tbl_settings", sa.column("key", sa.String(length=100)))
    introduced_keys = [key for key, _, _ in SETTINGS if key not in LEGACY_SETTINGS]
    connection.execute(settings_table.delete().where(settings_table.c.key.in_(introduced_keys)))
    connection.execute(
        sa.text("UPDATE tbl_settings SET key = 'week_start' WHERE key = 'week_starts_on'")
    )
    connection.execute(
        sa.text(
            "UPDATE tbl_settings SET value = '' WHERE key IN "
            "('receipt_source_retention_days', 'receipt_raw_retention_days') AND value IS NULL"
        )
    )
    with op.batch_alter_table("tbl_settings") as batch_op:
        batch_op.alter_column("value", existing_type=sa.Text(), nullable=False)
