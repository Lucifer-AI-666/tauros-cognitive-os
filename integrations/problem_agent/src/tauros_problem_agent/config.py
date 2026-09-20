from dataclasses import dataclass

@dataclass(frozen=True, slots=True)
class AgentConfig:
    replacement_threshold: float=.12
    minimum_candidate_score: float=.58
    max_reformulations: int=3
    minimum_input_length: int=3
