from axiom_engine.real_100_onboarding import load_cohort,onboarding_status,build_sec_registry_source
import pytest

def test_exactly_100_unique_symbols():
 c=load_cohort(); assert c.company_count==100; assert len({x.ticker for x in c.symbols})==100

def test_no_synthetic_symbols():
 assert all(not x.ticker.startswith(('TEST','FAKE','SYNTH')) for x in load_cohort().symbols)

def test_absent_data_never_passes(tmp_path):
 r=onboarding_status(registry_dir=tmp_path/'r',financial_dir=tmp_path/'f',estimate_dir=tmp_path/'e'); assert r['valuation_ready']==0 and not r['acceptance_passed']

def test_sec_requires_contact_email():
 with pytest.raises(ValueError): build_sec_registry_source('AXIOM')

def test_no_legacy_or_yfinance_imports():
 import ast
 from pathlib import Path
 names=[]
 for p in Path('src/axiom_engine/real_100_onboarding').glob('*.py'):
  for n in ast.walk(ast.parse(p.read_text())):
   if isinstance(n,ast.Import): names += [x.name for x in n.names]
   if isinstance(n,ast.ImportFrom): names += [n.module or '']
 assert not any('yfinance' in x or 'legacy' in x or 'research_report' in x for x in names)
