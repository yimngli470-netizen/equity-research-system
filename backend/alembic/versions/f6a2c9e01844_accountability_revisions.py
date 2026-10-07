"""Append-only accountability records, preserving every legacy row/outcome.

Revision ID: f6a2c9e01844
Revises: c8e4a72f019d
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "f6a2c9e01844"
down_revision = "c8e4a72f019d"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table("research_evidence",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("payload", postgresql.JSONB(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()))
    for table, prefix in (("stock_theses", "thesis"), ("forecasts", "forecast")):
        op.drop_constraint(f"uq_{prefix}_ticker_asof", table, type_="unique")
        op.add_column(table, sa.Column("writer_version", sa.String(30), nullable=False, server_default="legacy-v1"))
        op.add_column(table, sa.Column("revision_of", sa.BigInteger(), sa.ForeignKey(f"{table}.id")))
        op.add_column(table, sa.Column("content_sha256", sa.String(64)))
        op.add_column(table, sa.Column("evidence_id", sa.String(64), sa.ForeignKey("research_evidence.id")))
    op.create_table("research_events",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("ticker", sa.String(10), nullable=False),
        sa.Column("event_key", sa.String(200), nullable=False),
        sa.Column("contract", postgresql.JSONB(), nullable=False),
        sa.Column("contract_sha256", sa.String(64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("ticker", "event_key", name="uq_research_event_key"))
    op.create_index("ix_research_events_ticker", "research_events", ["ticker"])
    op.create_table("research_submissions",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("event_id", sa.String(36), sa.ForeignKey("research_events.id"), nullable=False),
        sa.Column("ordinal", sa.Integer(), nullable=False),
        sa.Column("evidence_id", sa.String(64), sa.ForeignKey("research_evidence.id"), nullable=False),
        sa.Column("revision_of", sa.String(36), sa.ForeignKey("research_submissions.id")),
        sa.Column("thesis_id", sa.BigInteger(), sa.ForeignKey("stock_theses.id")),
        sa.Column("forecast_id", sa.BigInteger(), sa.ForeignKey("forecasts.id")),
        sa.Column("payload", postgresql.JSONB(), nullable=False),
        sa.Column("fingerprint", sa.String(64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("event_id", "fingerprint", name="uq_research_submission"))
    op.create_index("ix_research_submissions_event_id", "research_submissions", ["event_id"])
    op.create_table("research_resolutions",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("event_id", sa.String(36), sa.ForeignKey("research_events.id"), nullable=False),
        sa.Column("ordinal", sa.Integer(), nullable=False),
        sa.Column("evidence_id", sa.String(64), sa.ForeignKey("research_evidence.id"), nullable=False),
        sa.Column("supersedes_id", sa.String(36), sa.ForeignKey("research_resolutions.id")),
        sa.Column("status", sa.String(24), nullable=False),
        sa.Column("payload", postgresql.JSONB(), nullable=False),
        sa.Column("packet_sha256", sa.String(64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("event_id", "packet_sha256", name="uq_research_resolution_packet"))
    op.create_index("ix_research_resolutions_event_id", "research_resolutions", ["event_id"])
    op.create_table("research_grade_calls",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("request", postgresql.JSONB(), nullable=False),
        sa.Column("response", postgresql.JSONB()),
        sa.Column("error", sa.Text()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()))
    op.execute("""
    CREATE FUNCTION accountability_immutable() RETURNS trigger LANGUAGE plpgsql AS $$
    BEGIN
      RAISE EXCEPTION 'Append-only research record: %', TG_TABLE_NAME;
    END $$;
    CREATE FUNCTION accountability_prediction_guard() RETURNS trigger LANGUAGE plpgsql AS $$
    BEGIN
      IF TG_OP = 'DELETE' THEN RAISE EXCEPTION 'Cannot delete prediction history'; END IF;
      IF (to_jsonb(NEW) - ARRAY['status','outcome','graded_at']) IS DISTINCT FROM
         (to_jsonb(OLD) - ARRAY['status','outcome','graded_at']) THEN
        RAISE EXCEPTION 'Prediction inputs are immutable; append a revision';
      END IF;
      RETURN NEW;
    END $$;
    CREATE FUNCTION accountability_call_guard() RETURNS trigger LANGUAGE plpgsql AS $$
    BEGIN
      IF TG_OP = 'DELETE' THEN RAISE EXCEPTION 'Cannot delete model call'; END IF;
      IF OLD.error IS DISTINCT FROM 'in_progress_or_interrupted'
         OR (to_jsonb(NEW) - ARRAY['response','error']) IS DISTINCT FROM
            (to_jsonb(OLD) - ARRAY['response','error'])
         OR NEW.error = 'in_progress_or_interrupted' THEN
        RAISE EXCEPTION 'Model receipt may be finalized only once';
      END IF;
      RETURN NEW;
    END $$;
    """)
    for table in ("research_evidence", "research_events", "research_submissions", "research_resolutions"):
        op.execute(f"CREATE TRIGGER immutable_record BEFORE UPDATE OR DELETE ON {table} "
                   "FOR EACH ROW EXECUTE FUNCTION accountability_immutable()")
    for table in ("stock_theses", "forecasts"):
        op.execute(f"CREATE TRIGGER immutable_prediction BEFORE UPDATE OR DELETE ON {table} "
                   "FOR EACH ROW EXECUTE FUNCTION accountability_prediction_guard()")
    op.execute("CREATE TRIGGER finalize_once BEFORE UPDATE OR DELETE ON research_grade_calls "
               "FOR EACH ROW EXECUTE FUNCTION accountability_call_guard()")


def downgrade():
    # Reversing after new data exists would delete research history. Refuse, do not force.
    op.execute("""DO $$ BEGIN
      IF EXISTS (SELECT 1 FROM research_evidence) OR EXISTS (SELECT 1 FROM research_events)
         OR EXISTS (SELECT 1 FROM research_grade_calls)
         OR EXISTS (SELECT 1 FROM stock_theses WHERE writer_version <> 'legacy-v1' OR evidence_id IS NOT NULL)
         OR EXISTS (SELECT 1 FROM forecasts WHERE writer_version <> 'legacy-v1' OR evidence_id IS NOT NULL)
      THEN RAISE EXCEPTION 'Nonempty accountability history: restore a reviewed backup instead of lossy downgrade';
      END IF;
    END $$""")
    for table in ("stock_theses", "forecasts"):
        op.execute(f"DROP TRIGGER immutable_prediction ON {table}")
    for table in ("research_grade_calls", "research_resolutions", "research_submissions", "research_events"):
        op.drop_table(table)
    for table, prefix in (("stock_theses", "thesis"), ("forecasts", "forecast")):
        for column in ("evidence_id", "content_sha256", "revision_of", "writer_version"):
            op.drop_column(table, column)
        op.create_unique_constraint(f"uq_{prefix}_ticker_asof", table, ["ticker", "as_of"])
    op.drop_table("research_evidence")
    for name in ("accountability_immutable", "accountability_prediction_guard", "accountability_call_guard"):
        op.execute(f"DROP FUNCTION {name}()")
