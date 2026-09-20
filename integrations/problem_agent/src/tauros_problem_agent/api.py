from typing import Any
try:
    from fastapi import FastAPI,HTTPException
    from pydantic import BaseModel,Field
except ImportError as exc:
    raise RuntimeError('Installa le dipendenze con: pip install -e ".[api]"') from exc
from .agent import ProblemAgent
app=FastAPI(title="TAUROS Problem Agent",version="0.1.0")
agent=ProblemAgent()
class AnalyzeRequest(BaseModel):
    request:str=Field(min_length=3)
    context:str|None=None
@app.get("/health")
def health()->dict[str,str]: return {"status":"ok"}
@app.post("/analyze")
def analyze(payload:AnalyzeRequest)->dict[str,Any]:
    try: return agent.analyze(payload.request,payload.context).to_dict()
    except ValueError as exc: raise HTTPException(status_code=400,detail=str(exc)) from exc
