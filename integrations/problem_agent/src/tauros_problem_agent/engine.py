from __future__ import annotations
import re
from dataclasses import dataclass
from typing import Protocol
from .models import QualityScore, ReframingCandidate

@dataclass(frozen=True, slots=True)
class EngineDraft:
    apparent_goal: str
    probable_real_goal: str
    assumptions: tuple[str,...]
    missing_constraints: tuple[str,...]
    reformulations: tuple[ReframingCandidate,...]
    confidence: float

class AnalysisEngine(Protocol):
    def analyze(self, request:str, context:str|None=None)->EngineDraft: ...
    def score_original(self, request:str)->QualityScore: ...

class HeuristicAnalysisEngine:
    def analyze(self, request:str, context:str|None=None)->EngineDraft:
        text=re.sub(r"\s+"," ",request.strip())
        lower=text.lower()
        apparent=text.rstrip(" .!?")
        if "pannell" in lower and ("binari" in lower or "rotaie" in lower):
            real=("Sfruttare una superficie ferroviaria poco utilizzata per produrre energia senza compromettere sicurezza, traffico, drenaggio e manutenzione.")
            assumptions=("Lo spazio tra le rotaie è tecnicamente e legalmente utilizzabile.","I moduli resistono a vibrazioni, detriti e condizioni ambientali.","L'installazione non ostacola drenaggio e manutenzione.","Il sistema può essere rimosso rapidamente.")
            constraints=("tratta ferroviaria e geometria del binario","normativa e autorizzazioni","carichi, vibrazioni e detriti","drenaggio","rimozione e manutenzione","costo e resa energetica")
            raw=[
                ("Come progettare un sistema fotovoltaico ferroviario modulare, rimovibile singolarmente, resistente alle vibrazioni e compatibile con drenaggio, sicurezza e manutenzione?","Rende espliciti i requisiti tecnici e operativi.",QualityScore(.94,.83,.91,.90)),
                ("Quali condizioni tecniche, normative ed economiche devono essere soddisfatte per installare pannelli fotovoltaici tra le rotaie senza interferire con l'esercizio ferroviario?","Verifica la fattibilità prima della progettazione.",QualityScore(.92,.90,.88,.94)),
                ("Come realizzare e testare un prototipo di cento metri di fotovoltaico tra le rotaie con moduli removibili e metriche su resa, vibrazioni, drenaggio e manutenzione?","Trasforma l'idea in un esperimento misurabile.",QualityScore(.91,.87,.94,.96))]
        else:
            real=self._real_goal(text)
            assumptions=("Il mezzo indicato dall'utente è adatto a raggiungere il risultato.",)
            constraints=("criterio preciso di successo","limiti quantitativi rilevanti","contesto operativo") if not context else ("criterio preciso di successo","limiti quantitativi rilevanti")
            base=self.score_original(text)
            raw=[
                (f"Come raggiungere questo risultato: {real.rstrip('.')} tenendo conto dei vincoli reali?","Esplicita risultato e vincoli.",self._boost(base,.18,.16,.10,.15)),
                (f"Quali informazioni e criteri servono per trasformare «{apparent}» in un obiettivo verificabile e realizzabile?","Definisce i criteri prima della soluzione.",self._boost(base,.14,.12,.08,.18)),
                ("Qual è il modo più semplice e verificabile per raggiungere l'obiettivo evitando assunzioni non confermate?","Riduce complessità e ambiguità.",self._boost(base,.10,.14,.07,.12))]
        reformulations=tuple(ReframingCandidate(q,r,s) for q,r,s in raw)
        confidence=.55 if len(text.split())<6 else .78
        return EngineDraft(apparent,real,assumptions,constraints,reformulations,confidence)

    def _real_goal(self,text:str)->str:
        lower=text.lower()
        if lower.startswith(("come ","quale ","quanto ","perché ","dove ","quando ")):
            return f"Ottenere una risposta affidabile e operativa alla domanda: {text.rstrip('?')}."
        cleaned=re.sub(r"^(io\s+)?(voglio|vorrei|devo|mi serve)\s+","",text,flags=re.I)
        return f"Raggiungere il risultato desiderato, cioè {cleaned.rstrip(' .!?')}, con una soluzione realistica e verificabile."

    def score_original(self,request:str)->QualityScore:
        words=request.split(); n=len(words); has_q=request.rstrip().endswith("?"); has_num=any(c.isdigit() for c in request)
        return QualityScore(round(min(1,.45+min(n,20)*.015+(.08 if has_q else 0)),3),round(.48+(.08 if n>=8 else 0),3),.58,round(.42+(.15 if has_num else 0)+(.08 if has_q else 0),3))

    @staticmethod
    def _boost(b:QualityScore,c:float,f:float,v:float,r:float)->QualityScore:
        return QualityScore(min(1,b.clarity+c),min(1,b.feasibility+f),min(1,b.value+v),min(1,b.verifiability+r))
