from datetime import date, datetime, timezone
from decimal import Decimal
import pytest
from axiom_engine.previous_close import DailyClose
from axiom_engine.valuation_api import LegacyValuationAPIService, ValuationAPIError

class CloseProvider:
    def __init__(self): self.calls=[]
    def previous_close(self,symbol,*,as_of=None): self.calls.append((symbol,as_of)); return DailyClose(symbol,date(2026,7,21),Decimal('205.47'),'USD','America/New_York')

def payload(): return {'market_consensus_eps_forward':6,'market_consensus_eps_current':4,'growth_estimate':.30,'future_revenue_per_share':10,'ps':20,'book_value_per_share':5,'target_pb':12,'ebitda_estimate':1000,'net_debt':5000,'shares_outstanding':100,'default_params':{'success_prob':.2}}

def test_all_models_and_previous_close():
    provider=CloseProvider(); result=LegacyValuationAPIService(provider).calculate({'symbol':'nvda','research_payload':payload()})
    assert result['symbol']=='NVDA' and result['reference_price']=='205.47' and result['price_type']=='previous_regular_close'
    assert set(result['models'])=={'peg','pe','ps','pb','ev_ebitda','milestone'}
    assert result['models']['pe']['fair_value']=='308.21'; assert provider.calls==[('NVDA',None)]

def test_fixed_close_skips_provider():
    provider=CloseProvider(); result=LegacyValuationAPIService(provider).calculate({'symbol':'NVDA','research_payload':payload(),'previous_close':{'session_date':'2026-07-21','close':'205.47','currency':'USD'}})
    assert result['valuation_as_of']=='2026-07-21' and provider.calls==[]

def test_override_calculated_backend_only():
    result=LegacyValuationAPIService(CloseProvider()).calculate({'symbol':'NVDA','research_payload':payload(),'overrides':{'target_pe':'40'}})
    assert result['models']['pe']['fair_value']=='240.00'

def test_as_of_forwarded():
    provider=CloseProvider(); LegacyValuationAPIService(provider).calculate({'symbol':'NVDA','research_payload':payload(),'as_of':'2026-07-22T08:00:00Z'})
    assert provider.calls[0][1]==datetime(2026,7,22,8,tzinfo=timezone.utc)

def test_unknown_override_rejected():
    with pytest.raises(ValuationAPIError,match='unsupported override'):
        LegacyValuationAPIService(CloseProvider()).calculate({'symbol':'NVDA','research_payload':payload(),'overrides':{'fair_value':999}})
