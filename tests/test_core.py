from pathlib import Path

from tauros.database import Database
from tauros.memory import MemoryManager
from tauros.models import MemoryCreate, MemoryPatch
from tauros.planner import Planner
from tauros.policy import PolicyEngine
from tauros.settings import Settings
from tauros.tools import ToolRegistry


def _settings(tmp_path: Path, **kwargs) -> Settings:
    base = {
        "api_token": "test-token-with-24-plus-chars!!",
        "skip_token_check": True,
        "database_path": tmp_path / "t.db",
        "workspace_allowlist": str(tmp_path),
        "security_mode": "read_only",
        "host": "127.0.0.1",
        "allow_lan_bind": False,
    }
    base.update(kwargs)
    return Settings(**base)


def test_memory_fts_roundtrip(tmp_path: Path):
    db = Database(tmp_path / "test.db")
    manager = MemoryManager(db)
    saved = manager.remember(MemoryCreate(content="Tauros usa Ollama localmente", kind="project", importance=8))
    found = manager.recall("Ollama locale")
    assert saved["id"] > 0
    assert found[0]["content"] == "Tauros usa Ollama localmente"


def test_memory_candidate_and_correction(tmp_path: Path):
    db = Database(tmp_path / "test.db")
    manager = MemoryManager(db)
    candidates = manager.soft_save_candidates("Ricorda che preferisco risposte lineari")
    assert candidates and candidates[0]["status"] == "candidate"
    corrected = manager.correct(candidates[0]["id"], MemoryPatch(status="active", importance=9))
    assert corrected["status"] == "active"
    assert corrected["importance"] == 9


def test_open_loop_extraction(tmp_path: Path):
    db = Database(tmp_path / "test.db")
    manager = MemoryManager(db)
    saved = manager.soft_save_candidates("Dobbiamo collegare Telegram al progetto")
    assert saved[0]["kind"] == "open_loop"


def test_planner_system_info():
    plan = Planner().create("Dammi informazioni sul sistema")
    assert plan.tool_calls[0].name == "system_info"


def test_policy_blocks_dangerous_tool(tmp_path: Path):
    settings = _settings(tmp_path)
    decision = PolicyEngine(settings).authorize_tool("delete_file", {"path": str(tmp_path / "x")})
    assert not decision.allowed


def test_disk_usage_is_cross_platform(tmp_path: Path):
    settings = _settings(tmp_path)
    policy = PolicyEngine(settings)
    result = ToolRegistry(policy, settings, policy.path_guard).disk_usage(str(tmp_path))
    assert result["total"] > 0
    assert result["free"] >= 0


def test_candidates_excluded_from_hard_recall(tmp_path: Path):
    db = Database(tmp_path / "test.db")
    manager = MemoryManager(db)
    saved = manager.soft_save_candidates("Ricorda che preferisco risposte lineari")
    assert saved and saved[0]["status"] == "candidate"
    hard = manager.recall("preferisco risposte lineari")
    assert hard == []
    manager.correct(saved[0]["id"], MemoryPatch(status="active"))
    hard_after = manager.recall("preferisco risposte lineari")
    assert hard_after and hard_after[0]["status"] == "active"


def test_patch_does_not_revive_forgotten(tmp_path: Path):
    db = Database(tmp_path / "test.db")
    manager = MemoryManager(db)
    item = manager.remember(MemoryCreate(content="Segreto temporaneo", kind="temporary", importance=3))
    manager.forget(item["id"])
    patched = manager.correct(item["id"], MemoryPatch(importance=4))
    assert patched is not None
    assert patched["status"] == "forgotten"
    assert patched["active"] == 0
    assert manager.recall("Segreto temporaneo") == []
