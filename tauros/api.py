from __future__ import annotations

import asyncio
import json
import logging
import secrets
from pathlib import Path

from fastapi import Depends, FastAPI, Header, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles

from . import __version__
from .auth import AuthService, AuthUser, is_loopback_host
from .database import Database
from .memory import MemoryManager
from .models import (
    AuthLogin,
    AuthRegister,
    ChatRequest,
    ChatResponse,
    DecisionCreate,
    DecisionPatch,
    ElevateRequest,
    MemoryConfirmBatch,
    MemoryCreate,
    MemoryPatch,
    WriteApproveRequest,
    WriteProposeRequest,
    WriteRestoreRequest,
)
from .orchestrator import Orchestrator
from .planner import Planner
from .policy import PolicyEngine
from .providers import build_provider
from .privileges import PrivilegeLevel, PrivilegeService
from .security import (
    assert_strong_token,
    install_log_redaction,
    redact_obj,
)
from .brain import BrainRuntime, load_brain_override
from .rules import AGENT_CATALOG, RuleStore
from .settings import settings

load_brain_override(settings)
from .tools import ToolRegistry
from .writes import WriteService

WEB_DIR = Path(__file__).resolve().parent.parent / "web"

install_log_redaction()
logger = logging.getLogger("tauros.api")

if not settings.skip_token_check:
    try:
        assert_strong_token(settings.api_token)
    except Exception as exc:  # noqa: BLE001
        logger.error("Configurazione token non valida: %s", exc)
        _token_error = str(exc)
    else:
        _token_error = None
else:
    _token_error = None

db = Database(settings.database_path)
memory = MemoryManager(db)
privileges = PrivilegeService.from_settings(settings)
policy = PolicyEngine(settings, privileges=privileges)
path_guard = policy.path_guard
writes = WriteService(
    settings,
    path_guard,
    privileges,
    audit=lambda event, actor, details: db.audit(event, actor, details),
)
tools = ToolRegistry(policy, settings, path_guard, memory=memory, writes=writes)
provider = build_provider(settings)
planner = Planner(
    provider=provider,
    max_steps=settings.max_plan_steps,
    allowed_tools={
        "system_info",
        "disk_usage",
        "list_directory",
        "read_text_file",
        "memory_search",
        "workspace_search",
        "git_status",
        "git_log",
        "git_diff",
        "project_summary",
        "propose_write",
        "propose_patch",
        "file_snapshot",
    },
)
orchestrator = Orchestrator(settings, db, provider, memory, planner, tools, policy=policy)
brain = BrainRuntime(settings, orchestrator, planner)
auth_service = AuthService(db, guest_max_messages=settings.guest_max_messages)
# Ensure owner exists for operator token mapping
try:
    auth_service.ensure_owner(settings.owner)
except Exception as exc:  # noqa: BLE001
    logger.warning("Owner bootstrap: %s", exc)

app = FastAPI(title="TAUROS Cognitive OS", version=__version__)

_cors = settings.cors_origin_list()
app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors,
    allow_credentials=False,
    allow_methods=["GET", "POST", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type"],
)

if WEB_DIR.is_dir():
    app.mount("/static", StaticFiles(directory=str(WEB_DIR)), name="static")


def _file(name: str, media_type: str | None = None) -> FileResponse:
    path = WEB_DIR / name
    if not path.exists():
        raise HTTPException(status_code=404, detail=f"{name} non trovato")
    headers = {
        "Cache-Control": "no-cache" if name in {"sw.js", "index.html", "app.html"} else "public, max-age=3600",
    }
    if name == "sw.js":
        headers["Service-Worker-Allowed"] = "/"
    return FileResponse(path, media_type=media_type, headers=headers)


@app.get("/")
def product_home() -> FileResponse:
    # Product UI (login + chat). Console operativa resta su /console
    app_page = WEB_DIR / "app.html"
    if app_page.exists():
        return _file("app.html", "text/html; charset=utf-8")
    return _file("index.html", "text/html; charset=utf-8")


@app.get("/console")
@app.get("/console/")
def operator_console() -> FileResponse:
    return _file("index.html", "text/html; charset=utf-8")


@app.get("/index.html")
def dashboard_index() -> FileResponse:
    return _file("index.html", "text/html; charset=utf-8")


@app.get("/app.html")
def product_app() -> FileResponse:
    return _file("app.html", "text/html; charset=utf-8")


@app.get("/manifest.webmanifest")
def web_manifest() -> FileResponse:
    return _file("manifest.webmanifest", "application/manifest+json")


@app.get("/sw.js")
def service_worker() -> FileResponse:
    return _file("sw.js", "application/javascript; charset=utf-8")


@app.get("/offline.html")
def offline_page() -> FileResponse:
    return _file("offline.html", "text/html; charset=utf-8")


@app.get("/favicon.ico")
def favicon() -> FileResponse:
    icon = WEB_DIR / "icons" / "icon-32.png"
    if not icon.exists():
        raise HTTPException(status_code=404, detail="favicon non trovato")
    return FileResponse(icon, media_type="image/png")


@app.get("/icons/{name}")
def pwa_icon(name: str) -> FileResponse:
    safe = Path(name).name
    icon = WEB_DIR / "icons" / safe
    if not icon.exists() or not icon.is_file():
        raise HTTPException(status_code=404, detail="icon non trovato")
    return FileResponse(icon, media_type="image/png", headers={"Cache-Control": "public, max-age=86400"})


def require_user(authorization: str | None = Header(default=None)) -> AuthUser:
    if _token_error:
        raise HTTPException(status_code=503, detail=_token_error)
    user = auth_service.resolve_bearer(authorization, settings.api_token)
    if not user:
        raise HTTPException(status_code=401, detail="Autenticazione richiesta")
    return user


def require_operator(user: AuthUser = Depends(require_user)) -> AuthUser:
    if not user.is_operator:
        raise HTTPException(status_code=403, detail="Solo operatore")
    return user


@app.get("/health")
def health() -> dict:
    return {
        "ok": _token_error is None,
        "name": settings.name,
        "version": __version__,
        "provider": settings.provider,
        "model": settings.model,
        "security_mode": settings.security_mode,
        "host": settings.host,
        "token_configured": not bool(_token_error),
        "pwa": True,
        "auth": True,
        "guest_max_messages": settings.guest_max_messages,
        "registration_open": settings.allow_open_registration,
        "public_base_url": settings.public_base_url or None,
    }


# ---------- Auth ----------
@app.post("/auth/register")
def auth_register(body: AuthRegister) -> dict:
    if not settings.allow_open_registration:
        raise HTTPException(status_code=403, detail="Registrazione disabilitata")
    try:
        return auth_service.register(body.username, body.password)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/auth/login")
def auth_login(body: AuthLogin) -> dict:
    try:
        return auth_service.login(body.username, body.password)
    except ValueError as exc:
        raise HTTPException(status_code=401, detail=str(exc)) from exc


@app.post("/auth/guest")
def auth_guest() -> dict:
    return auth_service.guest()


@app.post("/auth/local")
def auth_local(request: Request) -> dict:
    """One-click owner login, only from this machine (loopback)."""
    if not settings.local_click_login:
        raise HTTPException(status_code=403, detail="Login locale disabilitato")
    host = request.client.host if request.client else ""
    if not is_loopback_host(host):
        raise HTTPException(status_code=403, detail="Login locale solo da questo PC")
    return auth_service.local_owner_session(settings.owner)


@app.get("/auth/gmail/config")
def auth_gmail_config() -> dict:
    """Config pubblica per la pagina di login (niente secret)."""
    return {
        "google_client_id": settings.google_client_id or "",
        "google_enabled": bool(settings.google_client_id),
        "otp_enabled": True,
        "otp_debug": bool(settings.otp_debug),
        "local_click_login": bool(settings.local_click_login),
        "smtp_configured": bool(settings.gmail_user and settings.gmail_app_password),
        "allowed_domains": settings.gmail_allowed_domains,
    }


@app.post("/auth/gmail/request-code")
def auth_gmail_request_code(body: dict) -> dict:
    from .gmail_auth import GmailAuthConfig, GmailAuthService

    svc = GmailAuthService(
        db,
        auth_service,
        GmailAuthConfig(
            google_client_id=settings.google_client_id,
            gmail_user=settings.gmail_user,
            gmail_app_password=settings.gmail_app_password,
            otp_debug=settings.otp_debug,
            allowed_domains=settings.gmail_allowed_domains,
        ),
    )
    try:
        return svc.request_otp(body.get("email") or "")
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/auth/gmail/verify-code")
def auth_gmail_verify_code(body: dict) -> dict:
    from .gmail_auth import GmailAuthConfig, GmailAuthService

    svc = GmailAuthService(
        db,
        auth_service,
        GmailAuthConfig(
            google_client_id=settings.google_client_id,
            gmail_user=settings.gmail_user,
            gmail_app_password=settings.gmail_app_password,
            otp_debug=settings.otp_debug,
            allowed_domains=settings.gmail_allowed_domains,
        ),
    )
    try:
        return svc.verify_otp(body.get("email") or "", body.get("code") or "")
    except ValueError as exc:
        raise HTTPException(status_code=401, detail=str(exc)) from exc


@app.post("/auth/google")
def auth_google(body: dict) -> dict:
    """Body: { \"credential\": \"<Google ID token>\" } da GIS button."""
    from .gmail_auth import GmailAuthConfig, GmailAuthService

    svc = GmailAuthService(
        db,
        auth_service,
        GmailAuthConfig(
            google_client_id=settings.google_client_id,
            gmail_user=settings.gmail_user,
            gmail_app_password=settings.gmail_app_password,
            otp_debug=settings.otp_debug,
            allowed_domains=settings.gmail_allowed_domains,
        ),
    )
    token = body.get("credential") or body.get("id_token") or ""
    try:
        return svc.login_google_id_token(token)
    except ValueError as exc:
        raise HTTPException(status_code=401, detail=str(exc)) from exc


@app.get("/auth/me")
def auth_me(user: AuthUser = Depends(require_user)) -> dict:
    row = db.get_user(user.id)
    if not row:
        raise HTTPException(status_code=404, detail="Utente non trovato")
    priv = privileges.status(user.role, user.id)
    return AuthService._public_user(row) | {
        "is_operator": user.is_operator,
        "messages_remaining": user.messages_remaining,
        "privileges": priv,
    }


@app.get("/privileges")
def privilege_status(user: AuthUser = Depends(require_user)) -> dict:
    return privileges.status(user.role, user.id)


@app.post("/privileges/elevate")
def privilege_elevate(body: ElevateRequest, user: AuthUser = Depends(require_user)) -> dict:
    try:
        level = PrivilegeLevel[body.level.strip().upper()]
    except KeyError as exc:
        raise HTTPException(
            status_code=400,
            detail="level deve essere OPERATOR, ADMINISTRATOR o CONTROLLED_ROOT",
        ) from exc
    try:
        session = privileges.elevate(
            user_id=user.id,
            role=user.role,
            target=level,
            minutes=body.minutes,
            strong_confirmation=body.strong_confirmation,
            reason=body.reason,
            scope_path=body.scope_path,
            single_operation=body.single_operation,
        )
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    db.audit(
        "privilege_elevated",
        user.username,
        {
            "user_id": user.id,
            "level": session.level.name,
            "expires_at": session.expires_at.isoformat(),
            "reason": session.reason,
            "scope_path": session.scope_path,
            "single_operation": session.single_operation,
        },
    )
    return {
        "ok": True,
        "elevation": session.to_public(),
        "status": privileges.status(user.role, user.id),
        "message": (
            "Modalità elevata attiva. Alla scadenza torna il livello base. "
            "Più potere → più responsabilità."
        ),
    }


@app.post("/privileges/revoke")
def privilege_revoke(user: AuthUser = Depends(require_user)) -> dict:
    ok = privileges.revoke(user.id)
    db.audit("privilege_revoked", user.username, {"user_id": user.id, "had_session": ok})
    return {"ok": True, "revoked": ok, "status": privileges.status(user.role, user.id)}


# ---------- Supervised writes ----------
@app.get("/writes/proposals")
def list_write_proposals(
    status: str | None = None,
    user: AuthUser = Depends(require_user),
) -> list[dict]:
    uid = None if user.is_operator else user.id
    return writes.list_proposals(user_id=uid, status=status)


@app.get("/writes/proposals/{proposal_id}")
def get_write_proposal(proposal_id: str, user: AuthUser = Depends(require_user)) -> dict:
    prop = writes.get(proposal_id)
    if not prop:
        raise HTTPException(status_code=404, detail="Proposta non trovata")
    if not user.is_operator and prop.user_id != user.id:
        raise HTTPException(status_code=403, detail="Proposta di un altro utente")
    return prop.to_public(include_full=True)


@app.post("/writes/propose")
def propose_write_api(body: WriteProposeRequest, user: AuthUser = Depends(require_user)) -> dict:
    try:
        return writes.propose(
            user_id=user.id,
            actor=user.username,
            path=body.path,
            content=body.content,
            kind=body.kind,
            old_text=body.old_text,
            new_text=body.new_text,
            purpose=body.purpose,
            role=user.role,
        )
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/writes/proposals/{proposal_id}/approve")
def approve_write(
    proposal_id: str, body: WriteApproveRequest, user: AuthUser = Depends(require_user)
) -> dict:
    try:
        return writes.approve(
            proposal_id,
            actor=user.username,
            user_id=user.id,
            role=user.role if not user.is_operator else "operator",
            confirm=body.confirm,
            strong_confirmation=body.strong_confirmation,
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@app.post("/writes/proposals/{proposal_id}/reject")
def reject_write(proposal_id: str, user: AuthUser = Depends(require_user)) -> dict:
    try:
        return writes.reject(proposal_id, actor=user.username, user_id=user.id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/writes/restore")
def restore_write(body: WriteRestoreRequest, user: AuthUser = Depends(require_user)) -> dict:
    try:
        return writes.restore_backup(
            path=body.path,
            backup_path=body.backup_path,
            user_id=user.id,
            actor=user.username,
            role=user.role if not user.is_operator else "operator",
            strong_confirmation=body.strong_confirmation,
        )
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.post("/auth/logout")
def auth_logout(authorization: str | None = Header(default=None)) -> dict:
    try:
        u = auth_service.resolve_bearer(authorization, settings.api_token)
        if u:
            privileges.revoke(u.id)
    except Exception:  # noqa: BLE001
        pass
    if authorization and authorization.lower().startswith("bearer "):
        token = authorization.split(" ", 1)[1].strip()
        if token != settings.api_token:
            auth_service.logout(token)
    return {"ok": True}


# ---------- Chat ----------
@app.get("/tools")
def list_tools(user: AuthUser = Depends(require_user)) -> list[dict[str, str]]:
    return tools.available()


@app.post("/problem/analyze")
def problem_analyze(
    body: dict,
    user: AuthUser = Depends(require_user),
) -> dict:
    """Pre-filtro Problem Agent: PROCEED | INTEGRATE | REFRAME."""
    from .problem_bridge import analyze_problem, problem_agent_available

    if not problem_agent_available():
        raise HTTPException(status_code=503, detail="Problem Agent non installato in integrations/")
    text = (body.get("message") or body.get("request") or "").strip()
    if not text:
        raise HTTPException(status_code=400, detail="message richiesto")
    try:
        return analyze_problem(text, body.get("context"))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@app.get("/problem/status")
def problem_status(user: AuthUser = Depends(require_user)) -> dict:
    from .problem_bridge import problem_agent_available

    return {"available": problem_agent_available(), "path": "integrations/problem_agent"}


@app.post("/chat", response_model=ChatResponse)
async def chat(request: ChatRequest, user: AuthUser = Depends(require_user)) -> ChatResponse:
    try:
        auth_service.check_can_chat(user)
    except PermissionError as exc:
        raise HTTPException(status_code=429, detail=str(exc)) from exc
    req = request.model_copy(update={"is_guest": user.is_guest})
    result = await orchestrator.chat(req, user_id=user.id, role=user.role)
    auth_service.bump_message(user.id)
    return result


@app.post("/chat/stream")
async def chat_stream(request: ChatRequest, user: AuthUser = Depends(require_user)) -> StreamingResponse:
    try:
        auth_service.check_can_chat(user)
    except PermissionError as exc:
        raise HTTPException(status_code=429, detail=str(exc)) from exc

    async def events():
        yield "event: state\ndata: " + json.dumps({"stage": "planning"}) + "\n\n"
        await asyncio.sleep(0)
        req = request.model_copy(update={"is_guest": user.is_guest})
        result = await orchestrator.chat(req, user_id=user.id, role=user.role)
        auth_service.bump_message(user.id)
        yield "event: trace\ndata: " + result.trace.model_dump_json() + "\n\n"
        yield "event: answer\ndata: " + json.dumps({"answer": result.answer}, ensure_ascii=False) + "\n\n"
        yield "event: done\ndata: {}\n\n"

    return StreamingResponse(events(), media_type="text/event-stream")


# ---------- Memory (scoped) ----------
@app.post("/memories")
def add_memory(item: MemoryCreate, user: AuthUser = Depends(require_user)) -> dict:
    return memory.remember(item, user_id=user.id)


@app.get("/memories")
def list_memories(
    limit: int = 100,
    kind: str | None = None,
    status: str | None = None,
    user: AuthUser = Depends(require_user),
) -> list[dict]:
    return db.list_memories(min(max(limit, 1), 500), kind, status, user_id=user.id)


@app.get("/memories/search")
def search_memories(q: str, limit: int = 20, user: AuthUser = Depends(require_user)) -> list[dict]:
    return db.search_memories(q, min(max(limit, 1), 100), include_candidates=True, user_id=user.id)


@app.patch("/memories/{memory_id}")
def correct_memory(
    memory_id: int, patch: MemoryPatch, user: AuthUser = Depends(require_user)
) -> dict:
    result = memory.correct(memory_id, patch, user_id=user.id)
    if not result:
        raise HTTPException(status_code=404, detail="Memoria non trovata")
    return result


@app.post("/memories/confirm")
def confirm_memories(body: MemoryConfirmBatch, user: AuthUser = Depends(require_user)) -> list[dict]:
    confirmed: list[dict] = []
    for memory_id in body.ids:
        result = memory.correct(memory_id, MemoryPatch(status="active"), user_id=user.id)
        if result:
            confirmed.append(result)
    return confirmed


@app.delete("/memories/{memory_id}")
def forget_memory(memory_id: int, user: AuthUser = Depends(require_user)) -> dict:
    return {"success": memory.forget(memory_id, user_id=user.id)}


@app.get("/open-loops")
def open_loops(limit: int = 100, user: AuthUser = Depends(require_user)) -> list[dict]:
    return db.list_memories(
        min(max(limit, 1), 500),
        kind="open_loop",
        statuses=["active", "candidate"],
        user_id=user.id,
    )


@app.post("/open-loops/{memory_id}/resolve")
def resolve_open_loop(memory_id: int, user: AuthUser = Depends(require_user)) -> dict:
    result = memory.correct(
        memory_id, MemoryPatch(status="resolved"), user_id=user.id
    )
    if not result:
        raise HTTPException(status_code=404, detail="Open loop non trovato")
    db.audit("open_loop_resolved", user.username, {"memory_id": memory_id})
    return result


@app.post("/decisions")
def add_decision(item: DecisionCreate, user: AuthUser = Depends(require_user)) -> dict:
    decision_id = db.add_decision(
        item.title,
        item.rationale,
        item.outcome,
        item.status,
        item.revisit_at.isoformat() if item.revisit_at else None,
        user_id=user.id,
    )
    db.audit("decision_created", user.username, {"decision_id": decision_id, "title": item.title})
    return {"id": decision_id, **item.model_dump(mode="json")}


@app.get("/decisions")
def list_decisions(
    limit: int = 100, status: str | None = None, user: AuthUser = Depends(require_user)
) -> list[dict]:
    return db.list_decisions(min(max(limit, 1), 500), status, user_id=user.id)


@app.patch("/decisions/{decision_id}")
def patch_decision(
    decision_id: int, patch: DecisionPatch, user: AuthUser = Depends(require_user)
) -> dict:
    fields = patch.model_dump(exclude_none=True)
    if "revisit_at" in fields and fields["revisit_at"] is not None:
        fields["revisit_at"] = fields["revisit_at"].isoformat()
    updated = db.update_decision(decision_id, fields, user_id=user.id)
    if not updated:
        raise HTTPException(status_code=404, detail="Decisione non trovata")
    db.audit(
        "decision_updated",
        user.username,
        {"decision_id": decision_id, "fields": list(fields.keys())},
    )
    return updated


@app.get("/brief")
def daily_brief(user: AuthUser = Depends(require_user)) -> dict:
    return orchestrator.build_brief(user.id, is_operator=user.is_operator)


@app.post("/memories/consolidate")
def consolidate_memories(user: AuthUser = Depends(require_user)) -> dict:
    if user.is_guest:
        raise HTTPException(status_code=403, detail="Ospite non può consolidare memoria permanente")
    return memory.consolidate(user_id=user.id)


@app.get("/audit")
def list_audit(limit: int = 100, user: AuthUser = Depends(require_operator)) -> list[dict]:
    return db.list_audit(min(max(limit, 1), 500))


@app.get("/audit/verify")
def verify_audit(user: AuthUser = Depends(require_operator)) -> dict:
    return db.verify_audit()


@app.get("/export")
def export_data(user: AuthUser = Depends(require_user)) -> dict:
    # Users export only their slice; operator gets full redacted dump
    if user.is_operator:
        return redact_obj(db.export_all())
    return redact_obj(
        {
            "memories": db.list_memories(500, user_id=user.id),
            "decisions": db.list_decisions(500, user_id=user.id),
            "user": AuthService._public_user(db.get_user(user.id) or {}),
        }
    )


def _rule_store() -> RuleStore:
    return policy.rules


@app.get("/rules")
def list_rules(user: AuthUser = Depends(require_operator)) -> dict:
    rules = _rule_store().list_rules()
    return {"rules": [r.to_dict() for r in rules], "path": str(settings.rules_path)}


@app.put("/rules")
def replace_rules(body: dict, user: AuthUser = Depends(require_operator)) -> dict:
    items = body.get("rules")
    if not isinstance(items, list):
        raise HTTPException(status_code=400, detail="Body: { rules: [...] }")
    try:
        rules = _rule_store().replace_all(items)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    db.audit("rules_replace", user.username, {"count": len(rules)})
    return {"rules": [r.to_dict() for r in rules]}


@app.post("/rules")
def add_rule(body: dict, user: AuthUser = Depends(require_operator)) -> dict:
    try:
        rule = _rule_store().add(body)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    db.audit("rules_add", user.username, rule.to_dict())
    return {"rule": rule.to_dict()}


@app.patch("/rules/{rule_id}")
def patch_rule(rule_id: str, body: dict, user: AuthUser = Depends(require_operator)) -> dict:
    if "enabled" not in body:
        raise HTTPException(status_code=400, detail="Body: { enabled: true|false }")
    rule = _rule_store().set_enabled(rule_id, bool(body.get("enabled")))
    if not rule:
        raise HTTPException(status_code=404, detail="Regola non trovata")
    db.audit("rules_toggle", user.username, rule.to_dict())
    return {"rule": rule.to_dict()}


@app.delete("/rules/{rule_id}")
def delete_rule(rule_id: str, user: AuthUser = Depends(require_operator)) -> dict:
    if not _rule_store().delete(rule_id):
        raise HTTPException(status_code=404, detail="Regola non trovata")
    db.audit("rules_delete", user.username, {"id": rule_id})
    return {"ok": True}


@app.post("/rules/evaluate")
def evaluate_rule(body: dict, user: AuthUser = Depends(require_operator)) -> dict:
    tool = str(body.get("tool") or "")
    path = body.get("path")
    hit = _rule_store().evaluate(tool, str(path) if path else None)
    if not hit:
        return {"match": False, "effect": "fallthrough", "reason": "nessuna regola utente"}
    return {
        "match": True,
        "effect": hit.rule.effect,
        "reason": hit.reason,
        "rule": hit.rule.to_dict(),
    }


@app.get("/agents")
def list_agents(user: AuthUser = Depends(require_user)) -> dict:
    return {"agents": AGENT_CATALOG}


@app.get("/brain")
def get_brain(user: AuthUser = Depends(require_user)) -> dict:
    return brain.snapshot()


@app.put("/brain")
def put_brain(body: dict, user: AuthUser = Depends(require_operator)) -> dict:
    from .providers import ProviderError

    try:
        snap = brain.apply(str(body.get("provider") or ""), str(body.get("model") or ""))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except ProviderError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    db.audit(
        "brain_switch",
        user.username,
        {"provider": snap["provider"], "model": snap["model"]},
    )
    return snap


@app.get("/security")
def security_status(user: AuthUser = Depends(require_user)) -> dict:
    return {
        "mode": settings.security_mode,
        "host": settings.host,
        "allow_lan_bind": settings.allow_lan_bind,
        "allowlist": [str(p) for p in settings.allowlist_paths()] if user.is_operator else ["(protetto)"],
        "blocklist": [str(p) for p in settings.blocklist_paths()] if user.is_operator else [],
        "max_file_bytes": settings.max_file_bytes,
        "max_tool_steps": settings.max_tool_steps,
    }


@app.get("/dashboard/stats")
def dashboard_stats(user: AuthUser = Depends(require_user)) -> dict:
    uid = None if user.is_operator else user.id
    active = db.list_memories(500, status="active", user_id=uid if uid else user.id)
    # operator sees only own unless we pass None - for operator show own + system; use user.id always for simplicity
    if user.is_operator:
        active = db.list_memories(500, status="active")
        candidates = db.list_memories(500, status="candidate")
        loops = db.list_memories(500, kind="open_loop", statuses=["active", "candidate"])
        decisions = db.list_decisions(200)
    else:
        active = db.list_memories(500, status="active", user_id=user.id)
        candidates = db.list_memories(500, status="candidate", user_id=user.id)
        loops = db.list_memories(500, kind="open_loop", statuses=["active", "candidate"], user_id=user.id)
        decisions = db.list_decisions(200, user_id=user.id)
    audit = db.list_audit(20) if user.is_operator else []
    by_kind: dict[str, int] = {}
    for m in active:
        by_kind[m.get("kind") or "unknown"] = by_kind.get(m.get("kind") or "unknown", 0) + 1
    return {
        "version": __version__,
        "provider": settings.provider,
        "model": settings.model,
        "security_mode": settings.security_mode,
        "user": {
            "id": user.id,
            "username": user.username,
            "is_guest": user.is_guest,
            "is_operator": user.is_operator,
            "messages_remaining": user.messages_remaining,
        },
        "counts": {
            "memories_active": len(active),
            "memories_candidate": len(candidates),
            "open_loops": len(loops),
            "decisions": len(decisions),
            "audit_recent": len(audit),
        },
        "memories_by_kind": by_kind,
        "recent_audit": audit[:8],
        "open_loops_preview": loops[:8],
        "candidates_preview": candidates[:8],
        "integrity_ok": db.integrity_ok(),
    }
