from __future__ import annotations

import re

from .database import Database
from .models import MemoryCreate, MemoryPatch
from .security import content_hash


class MemoryManager:
    def __init__(self, db: Database):
        self.db = db

    def remember(self, item: MemoryCreate, user_id: int | None = None) -> dict:
        existing = self.db.find_by_hash(
            content_hash(item.content), include_candidates=True, user_id=user_id
        )
        if existing and existing["content"].casefold() == item.content.casefold():
            return existing

        memory_id = self.db.add_memory(
            item.content,
            item.kind,
            item.importance,
            item.tags,
            item.source,
            item.confidence,
            item.status,
            supersedes_id=item.supersedes_id,
            source_turn_id=item.source_turn_id,
            source_file=item.source_file,
            user_id=user_id,
        )
        self.db.audit(
            "memory_created",
            item.source,
            {
                "memory_id": memory_id,
                "kind": item.kind,
                "status": item.status,
                "source": item.source,
                "user_id": user_id,
            },
        )
        return {"id": memory_id, **item.model_dump()}

    def recall(self, query: str, limit: int = 8, user_id: int | None = None) -> list[dict]:
        return self.db.search_memories(query, limit, include_candidates=False, user_id=user_id)

    def forget(self, memory_id: int, user_id: int | None = None) -> bool:
        ok = self.db.deactivate_memory(memory_id, user_id=user_id)
        self.db.audit(
            "memory_deactivated", "user", {"memory_id": memory_id, "success": ok, "user_id": user_id}
        )
        return ok

    def correct(self, memory_id: int, patch: MemoryPatch, user_id: int | None = None) -> dict | None:
        updated = self.db.update_memory(
            memory_id, patch.model_dump(exclude_none=True), user_id=user_id
        )
        self.db.audit(
            "memory_corrected",
            "user",
            {
                "memory_id": memory_id,
                "fields": list(patch.model_dump(exclude_none=True)),
                "user_id": user_id,
            },
        )
        return updated

    def extract_candidates(self, text: str) -> list[MemoryCreate]:
        clean = " ".join(text.strip().split())
        candidates: list[MemoryCreate] = []
        rules = [
            (r"\b(?:ricorda che|memorizza che|tieni a mente che)\s+(.+)", "fact", 8),
            (r"\b(?:preferisco|mi piace|non mi piace|voglio che)\s+(.+)", "preference", 7),
            (r"\b(?:il progetto|sto lavorando a|stiamo costruendo)\s+(.+)", "project", 7),
            (r"\b(?:devo|dobbiamo|resta da|da fare)\s+(.+)", "open_loop", 6),
            (r"\b(?:ho imparato che|lezione:)\s*(.+)", "lesson", 7),
        ]
        for pattern, kind, importance in rules:
            match = re.search(pattern, clean, re.IGNORECASE)
            if not match:
                continue
            content = match.group(1).strip(" .")
            if 5 <= len(content) <= 500:
                candidates.append(
                    MemoryCreate(
                        content=content,
                        kind=kind,  # type: ignore[arg-type]
                        importance=importance,
                        tags=["auto-extracted"],
                        source="conversation",
                        confidence=0.72,
                        status="candidate",
                    )
                )
        return candidates[:3]

    def soft_save_candidates(self, text: str, user_id: int | None = None) -> list[dict]:
        saved = []
        for candidate in self.extract_candidates(text):
            existing = self.db.find_by_hash(
                content_hash(candidate.content), include_candidates=True, user_id=user_id
            )
            if existing:
                continue
            saved.append(self.remember(candidate, user_id=user_id))
        return saved

    def consolidate(self, user_id: int | None = None, *, min_confidence: float = 0.85) -> dict:
        """
        Light consolidation:
        - promote high-confidence candidates to active (if no active duplicate)
        - supersede older active when a newer active supersedes_id points at it
        Does not invent facts; never auto-promotes low-confidence items.
        """
        candidates = self.db.list_memories(
            200, status="candidate", user_id=user_id
        )
        promoted: list[int] = []
        skipped: list[dict] = []
        for c in candidates:
            conf = float(c.get("confidence") or 0)
            if conf < min_confidence:
                skipped.append({"id": c["id"], "reason": "confidence_bassa"})
                continue
            # Prefer explicit user confirmation for auto-extract; only promote high conf
            if (c.get("source") or "") == "conversation" and conf < 0.95:
                skipped.append({"id": c["id"], "reason": "richiede_conferma_utente"})
                continue
            updated = self.correct(
                int(c["id"]), MemoryPatch(status="active"), user_id=user_id
            )
            if updated:
                promoted.append(int(c["id"]))
        self.db.audit(
            "memory_consolidate",
            "system",
            {"promoted": promoted, "skipped": len(skipped), "user_id": user_id},
        )
        return {
            "promoted_ids": promoted,
            "promoted": len(promoted),
            "skipped": skipped[:30],
            "min_confidence": min_confidence,
        }
