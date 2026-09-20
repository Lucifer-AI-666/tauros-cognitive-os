from pathlib import Path

from tauros.auth import AuthService
from tauros.database import Database
from tauros.memory import MemoryManager
from tauros.models import MemoryCreate


def test_register_login_and_memory_isolation(tmp_path: Path):
    db = Database(tmp_path / "auth.db")
    auth = AuthService(db, guest_max_messages=5)
    mm = MemoryManager(db)

    a = auth.register("alice", "password123")
    b = auth.register("bob", "password456")
    assert a["token"] and b["token"]
    assert a["user"]["username"] == "alice"

    mm.remember(MemoryCreate(content="Alice ama il caffè", kind="preference"), user_id=a["user"]["id"])
    mm.remember(MemoryCreate(content="Bob ama il tè", kind="preference"), user_id=b["user"]["id"])

    alice_mem = mm.recall("caffè", user_id=a["user"]["id"])
    bob_mem = mm.recall("caffè", user_id=b["user"]["id"])
    assert alice_mem and "caffè" in alice_mem[0]["content"].casefold()
    assert bob_mem == []

    login = auth.login("alice", "password123")
    user = auth.resolve_bearer("Bearer " + login["token"], api_token="x" * 32)
    assert user and user.username == "alice" and not user.is_guest


def test_local_owner_session_is_operator(tmp_path: Path):
    db = Database(tmp_path / "local.db")
    auth = AuthService(db)
    data = auth.local_owner_session("Anouar")
    assert data["token"]
    assert data["user"]["username"] == "owner"
    assert data["user"]["is_operator"] is True
    user = auth.resolve_bearer("Bearer " + data["token"], api_token="z" * 32)
    assert user and user.username == "owner" and user.is_operator


def test_is_loopback_host():
    from tauros.auth import is_loopback_host

    assert is_loopback_host("127.0.0.1")
    assert is_loopback_host("::1")
    assert is_loopback_host("localhost")
    assert not is_loopback_host("192.168.1.10")
    assert not is_loopback_host("")


def test_smalltalk_skips_problem_agent():
    from tauros.problem_bridge import is_smalltalk, reframe_hint

    assert is_smalltalk("ciao")
    assert is_smalltalk("Ciao!")
    assert is_smalltalk("ok grazie")
    assert not is_smalltalk("Come sistemo il login di Tauros?")
    assert reframe_hint("ciao") is None


def test_guest_quota(tmp_path: Path):
    db = Database(tmp_path / "guest.db")
    auth = AuthService(db, guest_max_messages=2)
    g = auth.guest()
    user = auth.resolve_bearer("Bearer " + g["token"], api_token="y" * 32)
    assert user and user.is_guest
    auth.check_can_chat(user)
    auth.bump_message(user.id)
    auth.bump_message(user.id)
    user2 = auth.resolve_bearer("Bearer " + g["token"], api_token="y" * 32)
    assert user2
    # message_count reloaded
    user2.message_count = db.get_user(user2.id)["message_count"]
    try:
        auth.check_can_chat(user2)
        raised = False
    except PermissionError:
        raised = True
    assert raised
