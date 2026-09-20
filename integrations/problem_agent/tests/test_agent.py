from tauros_problem_agent import Decision,ProblemAgent

def test_railway_solar_is_reframed():
    r=ProblemAgent().analyze("Voglio mettere pannelli solari tra i binari")
    assert r.decision==Decision.REFRAME
    assert "fotovoltaico" in r.selected_question.lower()
    assert len(r.reformulations)==3

def test_short_input_is_rejected():
    try: ProblemAgent().analyze("a")
    except ValueError: pass
    else: raise AssertionError("ValueError atteso")

def test_serializable():
    r=ProblemAgent().analyze("Come posso organizzare meglio il mio progetto?")
    d=r.to_dict()
    assert d["decision"] in {"PROCEED","INTEGRATE","REFRAME"}
    assert isinstance(d["reformulations"],list)
