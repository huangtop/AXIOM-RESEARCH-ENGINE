import json
from pathlib import Path
from axiom_engine.fair_value_snapshot import build_fair_value_snapshot

def test_builds_and_renormalizes_ready_models(tmp_path: Path):
 (tmp_path/'v.json').write_text(json.dumps({"schema_version":"valuation-input-snapshot.v030.12.0","as_of_date":"2026-07-27","companies":[{"company_id":"c1","primary_symbol":"AAA","display_name":"AAA","market":{"previous_close":{"value":100,"currency":"USD"}},"financial_metrics":{"diluted_shares_outstanding":{"value":10},"revenue":{"value":500},"free_cash_flow":{"value":20},"cash_and_cash_equivalents":{"value":5},"total_debt":{"value":0},"trailing_eps":{"value":4},"forward_eps":{"value":5},"enterprise_value":{"value":995},"ebitda":{"value":25}}}]}))
 (tmp_path/'h.json').write_text(json.dumps({"benchmarks":[]}))
 report,_=build_fair_value_snapshot(tmp_path,valuation_input_path='v.json',historical_benchmark_path='h.json',target_company_count=1)
 row=report['companies'][0]
 assert row['models']['historical']['status']=='blocked'
 assert row['models']['peer']['status']=='ready'
 assert row['models']['dcf']['status']=='ready'
 assert row['composite']['status']=='ready'
 assert abs(sum(row['composite']['normalized_weights'].values())-1)<1e-9
 assert report['summary']['valuation_card_ready_count']==1
