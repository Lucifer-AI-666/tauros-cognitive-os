"""Bridge opzionale verso TAUROS Problem Agent (integrations/problem_agent)."""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

_INTEGRATION_SRC = (
    Path(__file__).resolve().parent.parent
    / "integrations"
    / "problem_agent"
    / "src"
)


def problem_agent_available() -> bool:
    return (_INTEGRATION_SRC / "tauros_problem_agent" / "agent.py").is_file()


def analyze_problem(request: str, context: str | None = None) -> dict[str, Any]:
    if not problem_agent_available():
        raise RuntimeError(
            "Problem Agent non trovato in integrations/problem_agent/src/"
        )
    root = str(_INTEGRATION_SRC)
    if root not in sys.path:
        sys.path.insert(0, root)

    from tauros_problem_agent.agent import ProblemAgent  # type: ignore

    analysis = ProblemAgent().analyze(request, context)
    if hasattr(analysis, "to_dict"):
        data = analysis.to_dict()
    else:
        data = {"raw": str(analysis)}
    data["available"] = True
    return data


_SMALLTALK = frozenset(
    {
        "ciao",
        "ciao!",
        "ciaoo",
        "hey",
        "hei",
        "hi",
        "hello",
        "salve",
        "buongiorno",
        "buonasera",
        "buonanotte",
        "ok",
        "okay",
        "va bene",
        "grazie",
        "grazie!",
        "thanks",
        "si",
        "sì",
        "no",
        "perfetto",
        "ottimo",
        "ok grazie",
        "ehi",
        "yo",
    }
)


def is_smalltalk(request: str) -> bool:
    text = " ".join((request or "").split()).casefold().strip("!.? ")
    if not text:
        return True
    if text in _SMALLTALK:
        return True
    if len(text) < 16 and text.split()[0] in _SMALLTALK:
        return True
    return False


def reframe_hint(request: str) -> str | None:
    if is_smalltalk(request):
        return None
    try:
        a = analyze_problem(request)
    except Exception:
        return None
    decision = str(a.get("decision", "")).upper()
    if decision not in {"REFRAME", "INTEGRATE"}:
        return None
    real = a.get("probable_real_goal") or a.get("apparent_goal") or ""
    rationale = a.get("rationale") or ""
    reform = a.get("selected_question") or ""
    parts = [f"[Problem Agent: {decision}]", f"Obiettivo probabile: {real}"]
    if reform:
        parts.append(f"Riformulazione: {reform}")
    if rationale:
        parts.append(f"Motivo: {rationale}")
    return "\n".join(parts)
