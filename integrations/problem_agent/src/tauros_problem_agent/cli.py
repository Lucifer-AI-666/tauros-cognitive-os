import argparse,sys
from .agent import ProblemAgent
from .formatters import as_json,as_markdown

def main()->None:
    p=argparse.ArgumentParser(prog="tauros-problem")
    p.add_argument("request")
    p.add_argument("--context",default=None)
    p.add_argument("--json",action="store_true")
    a=p.parse_args()
    try:
        result=ProblemAgent().analyze(a.request,a.context)
    except ValueError as exc:
        print(f"Errore: {exc}",file=sys.stderr); raise SystemExit(2) from exc
    print(as_json(result) if a.json else as_markdown(result))

if __name__=="__main__": main()
