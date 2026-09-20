from __future__ import annotations
from dataclasses import asdict, dataclass, field
from enum import StrEnum
from typing import Any

class Decision(StrEnum):
    PROCEED="PROCEED"
    INTEGRATE="INTEGRATE"
    REFRAME="REFRAME"

@dataclass(frozen=True, slots=True)
class QualityScore:
    clarity: float
    feasibility: float
    value: float
    verifiability: float
    @property
    def total(self)->float:
        return round((self.clarity+self.feasibility+self.value+self.verifiability)/4,3)
    def to_dict(self)->dict[str,float]:
        return {"clarity":self.clarity,"feasibility":self.feasibility,"value":self.value,"verifiability":self.verifiability,"total":self.total}

@dataclass(frozen=True, slots=True)
class ReframingCandidate:
    question: str
    rationale: str
    score: QualityScore
    def to_dict(self)->dict[str,Any]:
        return {"question":self.question,"rationale":self.rationale,"score":self.score.to_dict()}

@dataclass(frozen=True, slots=True)
class ProblemAnalysis:
    original_request: str
    apparent_goal: str
    probable_real_goal: str
    implicit_assumptions: tuple[str,...]=field(default_factory=tuple)
    missing_constraints: tuple[str,...]=field(default_factory=tuple)
    reformulations: tuple[ReframingCandidate,...]=field(default_factory=tuple)
    selected_question: str=""
    decision: Decision=Decision.PROCEED
    rationale: str=""
    original_score: QualityScore=field(default_factory=lambda:QualityScore(.5,.5,.5,.5))
    confidence: float=.5
    def to_dict(self)->dict[str,Any]:
        data=asdict(self)
        data["decision"]=self.decision.value
        data["original_score"]=self.original_score.to_dict()
        data["reformulations"]=[x.to_dict() for x in self.reformulations]
        return data
