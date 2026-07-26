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

def test_reads_symbol_keyed_market_cache_and_counts_distinct_companies(tmp_path):
    root=_repo(tmp_path); (root/'data/cache').mkdir(parents=True)
    payload={"symbols":{
        "AAA":{"session_date":"2026-07-25","close":"10.5","currency":"USD"},
        "BBB":{"symbol":"BBB","session_date":"2026-07-25","close":"20","currency":"USD"},
    }}
    (root/'data/cache/previous_closes.json').write_text(json.dumps(payload))
    result=expand_production_sources(root, config={"sources":{"market":[{
        "path":"data/cache/previous_closes.json","provider":"demo","market_state":"historical"
    }]}})
    assert result['coverage']['market']['record_count']==2
    assert result['coverage']['market']['company_count']==2
    assert result['outputs']['market'][0]['semantic_type']=='market_fact'
    assert all(row['market_state']=='historical' for row in result['outputs']['market'])
    assert {row['price'] for row in result['outputs']['market']}=={10.5,20.0}


def test_market_observation_requires_market_date(tmp_path):
    root=_repo(tmp_path); (root/'provider').mkdir()
    (root/'provider/quotes.json').write_text(json.dumps([{"ticker":"AAA","price":10}]))
    result=expand_production_sources(root, config={"sources":{"market":[{"path":"provider/quotes.json","provider":"demo"}]}})
    assert result['coverage']['market']['record_count']==0
    assert result['rejected_records'][0]['reason']=='missing_market_date'


def test_market_source_spec_supplies_default_currency_and_state(tmp_path):
    root=_repo(tmp_path); (root/'provider').mkdir()
    (root/'provider/quotes.json').write_text(json.dumps([{"ticker":"AAA","close":"12.25","trade_date":"2026-07-25"}]))
    result=expand_production_sources(root, config={"sources":{"market":[{
        "path":"provider/quotes.json","provider":"demo","currency":"USD","market_state":"historical"
    }]}})
    row=result['outputs']['market'][0]
    assert row['currency']=='USD'
    assert row['market_state']=='historical'
    assert row['price']==12.25


def test_normalizes_metric_value_consensus_estimate(tmp_path):
    root=_repo(tmp_path); (root/'provider').mkdir()
    payload={"estimates":[{"ticker":"AAA","metric":"revenue","value":"450000000000","unit":"currency","currency":"USD","period_end":"2027-09-30","fiscal_year":2027,"fiscal_period":"FY","estimate_kind":"consensus_mean","analyst_count":35,"source_record_id":"AAA-REV-FY2027"}]}
    (root/'provider/estimates.json').write_text(json.dumps(payload))
    result=expand_production_sources(root, config={"sources":{"estimate":[{"path":"provider/estimates.json","provider":"licensed","as_of_date":"2026-07-24"}]}})
    row=result['outputs']['estimate'][0]
    assert row['forward_revenue']==450000000000.0
    assert row['analyst_count']==35
    assert row['record_state']=='complete'
    assert row['observed_at']=='2026-07-24'


def test_estimate_metric_value_requires_supported_metric(tmp_path):
    root=_repo(tmp_path); (root/'provider').mkdir()
    (root/'provider/estimates.json').write_text(json.dumps({"estimates":[{"ticker":"AAA","metric":"unknown_metric","value":1}]}))
    result=expand_production_sources(root, config={"sources":{"estimate":[{"path":"provider/estimates.json","provider":"licensed","as_of_date":"2026-07-24"}]}})
    assert result['coverage']['estimate']['record_count']==0
    assert result['rejected_records'][0]['reason']=='no_usable_values'


def test_normalizes_metric_value_sec_financial_fact_and_preserves_provenance(tmp_path):
    root=_repo(tmp_path); (root/'provider').mkdir()
    fact={"financial_fact_id":"fact:1","company_id":"company:1","metric":"revenue","value":"123000","unit":"currency","currency":"USD","period_type":"duration","period_start":"2025-01-01","period_end":"2025-12-31","fiscal_year":2025,"fiscal_period":"FY","statement":"income_statement","form_type":"10-K","accession_number":"0001","audited":True,"provenance_ids":["prov:1"]}
    (root/'provider/sec.json').write_text(json.dumps([fact]))
    result=expand_production_sources(root, config={"sources":{"financial":[{"path":"provider/sec.json","provider":"sec_companyfacts"}]}})
    row=result['outputs']['financial'][0]
    assert row['revenue']==123000.0
    assert row['metric']=='revenue'
    assert row['record_state']=='official'
    assert row['accession_number']=='0001'
    assert row['provenance_ids']==['prov:1']


def test_rejects_unsupported_metric_value_financial_row(tmp_path):
    root=_repo(tmp_path); (root/'provider').mkdir()
    (root/'provider/sec.json').write_text(json.dumps([{"company_id":"company:1","metric":"market_price","value":99,"period_end":"2025-12-31"}]))
    result=expand_production_sources(root, config={"sources":{"financial":[{"path":"provider/sec.json","provider":"sec_companyfacts"}]}})
    assert result['coverage']['financial']['record_count']==0
    assert result['rejected_records'][0]['reason']=='no_usable_values'
