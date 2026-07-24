import json
from pathlib import Path
import pytest
from axiom_engine.market_data import MarketDataError,build_market_data,validate_market_data

def dump(p,v): p.write_text(json.dumps(v),encoding='utf-8')
def registry(p):
 p.mkdir(); dump(p/'companies.json',[{'company_id':'company:US-AAPL','ticker':'AAPL'}]); dump(p/'securities.json',[{'security_id':'security:US-AAPL','company_id':'company:US-AAPL','ticker':'AAPL'}])
def test_build_canonical_bundle(tmp_path):
 r=tmp_path/'r'; registry(r); s=tmp_path/'s.json'; dump(s,[{'ticker':'AAPL','price':'200','sharesOutstanding':'1000','marketCap':'200000','currency':'USD','trading_date':'2026-07-24'}]); o=tmp_path/'o'
 report=build_market_data(source=s,registry_dir=r,output_dir=o,adapter='generic',write=True)
 assert report['observations_built']==3 and report['acceptance_passed']
 assert sorted(x.name for x in o.iterdir())==['diagnostics.json','manifest.json','observations.json','provenance.json']
 assert validate_market_data(o)['valid']
def test_canonical_adapter(tmp_path):
 r=tmp_path/'r'; registry(r); s=tmp_path/'s.json'; dump(s,{'observations':[{'company_id':'company:US-AAPL','security_id':'security:US-AAPL','ticker':'AAPL','metric':'current_price','value':'201'}]})
 assert build_market_data(source=s,registry_dir=r,adapter='canonical')['observations_built']==1
def test_rejects_valuation_fields(tmp_path):
 r=tmp_path/'r'; registry(r); s=tmp_path/'s.json'; dump(s,{'ticker':'AAPL','price':'200','fair_value':'300'})
 with pytest.raises(MarketDataError,match='forbidden'): build_market_data(source=s,registry_dir=r)
def test_unresolved_company_is_diagnostic(tmp_path):
 r=tmp_path/'r'; registry(r); s=tmp_path/'s.json'; dump(s,[{'ticker':'MSFT','price':'200'}])
 report=build_market_data(source=s,registry_dir=r); assert not report['acceptance_passed'] and report['diagnostic_summary']['errors']==1
def test_valuation_engine_contract_filename(tmp_path):
 r=tmp_path/'r'; registry(r); s=tmp_path/'s.json'; dump(s,[{'ticker':'AAPL','price':'200'}]); o=tmp_path/'market_data'; build_market_data(source=s,registry_dir=r,output_dir=o,write=True)
 assert (o/'observations.json').exists()
