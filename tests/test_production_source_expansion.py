from __future__ import annotations
import json
from pathlib import Path
from axiom_engine.production_source_expansion import expand_production_sources, write_expansion_outputs

def _repo(tmp_path: Path) -> Path:
    (tmp_path/'data/universe').mkdir(parents=True)
    (tmp_path/'data/universe/companies.json').write_text(json.dumps([{"company_id":"company:1"},{"company_id":"company:2"}]))
    (tmp_path/'data/universe/securities.json').write_text(json.dumps([
        {"security_id":"security:1","company_id":"company:1","ticker":"AAA"},
        {"security_id":"security:2","company_id":"company:2","ticker":"BBB"},
    ]))
    return tmp_path

def test_normalizes_market_and_rejects_blank_rows(tmp_path):
    root=_repo(tmp_path); (root/'provider').mkdir()
    (root/'provider/quotes.json').write_text(json.dumps([
        {"ticker":"AAA","last_price":10,"quote_time":"2026-07-25","currency":"USD"},
        {"ticker":"BBB","last_price":None,"quote_time":"2026-07-25"},
    ]))
    payload=expand_production_sources(root, config={"sources":{"market":[{"path":"provider/quotes.json","provider":"demo"}]}})
    assert payload['coverage']['market']['company_count']==1
    assert payload['outputs']['market'][0]['semantic_type']=='market_fact'
    assert payload['outputs']['market'][0]['price']==10
    assert payload['rejected_records'][0]['reason']=='no_usable_values'

def test_resolves_security_and_deduplicates_identical_records(tmp_path):
    root=_repo(tmp_path); (root/'provider').mkdir()
    row={"security_id":"security:1","price":10,"market_date":"2026-07-25"}
    (root/'provider/quotes.json').write_text(json.dumps([row,row]))
    payload=expand_production_sources(root, config={"sources":{"market":[{"path":"provider/quotes.json","provider":"demo"}]}})
    assert len(payload['outputs']['market'])==1
    assert payload['outputs']['market'][0]['company_id']=='company:1'

def test_placeholder_estimate_is_not_emitted(tmp_path):
    root=_repo(tmp_path); (root/'provider').mkdir()
    (root/'provider/estimates.csv').write_text('ticker,target_price,estimate_date\nAAA,,2026-07-25\n')
    payload=expand_production_sources(root, config={"sources":{"estimate":[{"path":"provider/estimates.csv","provider":"demo"}]}})
    assert payload['coverage']['estimate']['record_count']==0
    assert payload['rejected_records'][0]['reason']=='no_usable_values'

def test_writes_canonical_outputs(tmp_path):
    root=_repo(tmp_path); (root/'provider').mkdir()
    (root/'provider/facts.json').write_text(json.dumps([{"company_id":"company:1","revenue":100,"period_end":"2025-12-31"}]))
    payload=expand_production_sources(root, config={"sources":{"financial":[{"path":"provider/facts.json","provider":"demo"}]}})
    out=root/'out'; write_expansion_outputs(payload,out)
    assert (out/'financial_facts.json').exists()
    assert (out/'market_facts.json').exists()
    assert (out/'estimate_facts.json').exists()
    assert json.loads((out/'expansion_summary.json').read_text())['coverage']['financial']['company_count']==1
