"""Standalone migration rehearsal. Only a freshly created, isolated *_test DB.

Run in the network-isolated Phase-2 test container, never the production container.
The script refuses a DB that already has tables. It tests the real Alembic chain.
"""
import json
import os
import subprocess
import sys

from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import DBAPIError

url = make_url(os.environ["DATABASE_URL"])
if url.database != "accountability_migration_test":
    raise RuntimeError("Requires the dedicated empty accountability_migration_test DB")
engine = create_engine(url.set(drivername="postgresql+psycopg2"))
with engine.connect() as conn:
    assert not conn.execute(text("SELECT tablename FROM pg_tables WHERE schemaname='public'")).all()


def migrate(target, action="upgrade", expected_success=True):
    run = subprocess.run([sys.executable, "-m", "alembic", action, target], capture_output=True, text=True)
    if (run.returncode == 0) != expected_success:
        raise AssertionError(run.stdout + run.stderr)
    return run


def rows():
    with engine.connect() as c:
        return {t: c.execute(text(f"SELECT to_jsonb(r) - ARRAY['writer_version','revision_of','content_sha256','evidence_id'] FROM {t} r ORDER BY id")).scalars().all()
                for t in ("stock_theses", "forecasts")}


def rejects(sql):
    try:
        with engine.begin() as c:
            c.exec_driver_sql(sql)
    except DBAPIError:
        return
    raise AssertionError("Immutable history unexpectedly changed: " + sql)


migrate("c8e4a72f019d")
with engine.begin() as c:
    c.execute(text("""INSERT INTO stock_theses(ticker,as_of,leaning,conviction,kill_criteria,status,outcome)
        VALUES ('TEST','2025-10-01','bull',0.8,'[{"by_date":"Q1 FY2026"}]','graded','{"sentinel":"old thesis"}')"""))
    c.execute(text("""INSERT INTO forecasts(ticker,as_of,assumptions,projections,status,outcome)
        VALUES ('TEST','2025-10-01','{"original": true}','{}','graded','{"sentinel":"old forecast"}')"""))
before = rows()
migrate("head")
assert rows() == before
rejects("UPDATE stock_theses SET leaning='bear'")
rejects("UPDATE forecasts SET assumptions='{}'")
rejects("DELETE FROM stock_theses")
rejects("DELETE FROM forecasts")
# Empty-new-history rollback is safe and restores original shape/uniqueness.
migrate("c8e4a72f019d", "downgrade")
assert rows() == before
migrate("head")
with engine.begin() as c:
    c.execute(text("INSERT INTO research_evidence(id,payload) VALUES ('test-hash','{}')"))
    c.execute(text("""INSERT INTO stock_theses(ticker,as_of,leaning,kill_criteria,status,writer_version,revision_of,evidence_id)
        VALUES ('TEST','2025-10-01','bear','[]','open','accountability-v2',1,'test-hash')"""))
    c.execute(text("""INSERT INTO research_grade_calls(id,request,error)
        VALUES ('call-one','{}','in_progress_or_interrupted')"""))
rejects("UPDATE research_evidence SET payload='{\"changed\":true}'")
rejects("DELETE FROM research_evidence")
with engine.begin() as c:
    c.execute(text("UPDATE research_grade_calls SET error='Invalid mocked response', response='{}' WHERE id='call-one'"))
rejects("UPDATE research_grade_calls SET error=NULL WHERE id='call-one'")
migrate("c8e4a72f019d", "downgrade", expected_success=False)
with engine.connect() as c:
    assert c.execute(text("SELECT version_num FROM alembic_version")).scalar_one() == "f6a2c9e01844"
    assert c.execute(text("SELECT count(*) FROM stock_theses")).scalar_one() == 2
assert rows()["stock_theses"][0] == before["stock_theses"][0]
assert rows()["forecasts"] == before["forecasts"]
print(json.dumps({"status": "passed", "checks": [
    "full prior Alembic chain", "legacy rows and outcomes preserved", "same-day append permitted",
    "prediction/evidence update-delete blocked", "one-time call finalization", "empty-history downgrade",
    "nonempty-history downgrade fails transactionally without data loss"
]}))
