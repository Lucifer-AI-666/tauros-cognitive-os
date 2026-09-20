import json
from .models import ProblemAnalysis

def as_json(a:ProblemAnalysis)->str:
    return json.dumps(a.to_dict(),ensure_ascii=False,indent=2)

def as_markdown(a:ProblemAnalysis)->str:
    assumptions="\n".join(f"- {x}" for x in a.implicit_assumptions) or "- Nessuna"
    constraints="\n".join(f"- {x}" for x in a.missing_constraints) or "- Nessuno"
    alternatives="\n\n".join(f"### Alternativa {i}\n{x.question}\n\nMotivo: {x.rationale}\n\nPunteggio: {x.score.total:.3f}" for i,x in enumerate(a.reformulations,1))
    return f"""# Analisi del problema

## Richiesta originale
{a.original_request}

## Obiettivo apparente
{a.apparent_goal}

## Obiettivo reale probabile
{a.probable_real_goal}

## Assunzioni implicite
{assumptions}

## Vincoli mancanti
{constraints}

## Riformulazioni
{alternatives}

## Domanda selezionata
{a.selected_question}

## Decisione
{a.decision.value}

## Motivazione
{a.rationale}

## Confidenza
{a.confidence:.2f}
"""
