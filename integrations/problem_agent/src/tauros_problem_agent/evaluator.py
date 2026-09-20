from .config import AgentConfig
from .models import Decision, QualityScore, ReframingCandidate

class QualityEvaluator:
    def __init__(self,config:AgentConfig)->None:
        self.config=config
    def choose(self,original_request:str,original_score:QualityScore,candidates:tuple[ReframingCandidate,...],missing_constraints:tuple[str,...])->tuple[Decision,str,str]:
        if not candidates:
            return Decision.PROCEED,original_request,"Nessuna riformulazione chiaramente migliore."
        best=max(candidates,key=lambda x:x.score.total)
        improvement=best.score.total-original_score.total
        if original_score.total>=.78 and improvement<self.config.replacement_threshold:
            return Decision.PROCEED,original_request,"La richiesta iniziale è già sufficientemente chiara."
        if best.score.total>=self.config.minimum_candidate_score and improvement>=self.config.replacement_threshold:
            return Decision.REFRAME,best.question,f"La riformulazione migliora il punteggio da {original_score.total:.3f} a {best.score.total:.3f}."
        if missing_constraints:
            return Decision.INTEGRATE,original_request,"La richiesta è valida, ma servono informazioni aggiuntive."
        return Decision.PROCEED,original_request,"La riformulazione non offre un vantaggio sufficiente."
