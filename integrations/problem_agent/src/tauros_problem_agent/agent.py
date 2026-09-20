from .config import AgentConfig
from .engine import AnalysisEngine, HeuristicAnalysisEngine
from .evaluator import QualityEvaluator
from .models import ProblemAnalysis

class ProblemAgent:
    def __init__(self,engine:AnalysisEngine|None=None,config:AgentConfig|None=None)->None:
        self.config=config or AgentConfig()
        self.engine=engine or HeuristicAnalysisEngine()
        self.evaluator=QualityEvaluator(self.config)
    def analyze(self,request:str,context:str|None=None)->ProblemAnalysis:
        cleaned=" ".join(request.split())
        if len(cleaned)<self.config.minimum_input_length:
            raise ValueError("La richiesta è troppo breve per essere analizzata.")
        draft=self.engine.analyze(cleaned,context)
        score=self.engine.score_original(cleaned)
        candidates=draft.reformulations[:self.config.max_reformulations]
        decision,selected,rationale=self.evaluator.choose(cleaned,score,candidates,draft.missing_constraints)
        return ProblemAnalysis(cleaned,draft.apparent_goal,draft.probable_real_goal,draft.assumptions,draft.missing_constraints,candidates,selected,decision,rationale,score,draft.confidence)
