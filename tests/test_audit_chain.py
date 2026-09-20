from pathlib import Path

from tauros.audit_chain import GENESIS
from tauros.database import Database
from tauros.security import generate_api_token
from tauros.settings import Settings


def _db(tmp_path: Path) -> Database:
    settings = Settings(
        api_token=generate_api_token(),
        skip_token_check=True,
        host="127.0.0.1",
        database_path=tmp_path / "t.db",
        groq_api_key="",
        openai_api_key="",
    )
    return Database(settings.database_path)


def test_audit_chain_links_and_detects_tamper(tmp_path: Path):
    db = _db(tmp_path)
    db.audit("a", "op", {"n": 1})
    db.audit("b", "op", {"n": 2})
    rows = list(reversed(db.list_audit(10)))
    assert rows[0]["prev_hash"] == GENESIS
    assert rows[1]["prev_hash"] == rows[0]["row_hash"]
    assert db.verify_audit()["ok"] is True

    with db.connect() as con:
        con.execute("UPDATE audit SET details_json='{}' WHERE event_type='b'")
    broken = db.verify_audit()
    assert broken["ok"] is False
    assert broken["first_bad_id"] is not None
