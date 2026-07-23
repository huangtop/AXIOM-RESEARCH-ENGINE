from pathlib import Path
import ast, json
from axiom_engine.ontology import load_ontology, validate_ontology, OntologyRegistry

def bundle(): return load_ontology(Path(__file__).parents[1]/"data"/"ontology")
def test_valid(): assert validate_ontology(bundle())["entities"] >= 8
def test_no_company_membership(): assert all(e.entity_type_id != "company" and not e.entity_id.startswith("company:") for e in bundle().entities)
def test_no_ticker_membership():
    text=json.dumps([e.__dict__ for e in bundle().entities]).lower(); assert '"ticker"' not in text and '"symbol"' not in text
def test_no_financial_fields():
    text=json.dumps([e.__dict__ for e in bundle().entities] + [r.__dict__ for r in bundle().relations]).lower(); assert "current_price" not in text and "revenue_ttm" not in text and "analyst_target" not in text
def test_deterministic_traversal():
    r=OntologyRegistry(bundle()); assert r.path("technology:co_packaged_optics","theme:ai_infrastructure") == ("technology:co_packaged_optics","technology:silicon_photonics","theme:ai_infrastructure")
def test_no_forbidden_imports():
    root=Path(__file__).parents[1]/"src"/"axiom_engine"/"ontology"
    names=[]
    for p in root.glob("*.py"):
        for n in ast.walk(ast.parse(p.read_text())):
            if isinstance(n,ast.Import): names += [a.name for a in n.names]
            elif isinstance(n,ast.ImportFrom) and n.module: names.append(n.module)
    assert not any(any(x in n.lower() for x in ("yfinance","research_report","legacy")) for n in names)
