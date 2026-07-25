import json
from pathlib import Path
from axiom_engine.production_population.core import build_population, validate_population, write_population


def fixture(tmp_path: Path):
    (tmp_path/"data/universe").mkdir(parents=True)
    companies=[{"company_id":"company:US-CIK0001","display_name":"One","primary_security_id":"security:NASDAQ-ONE"},{"company_id":"company:US-CIK0002","display_name":"Two","primary_security_id":"security:NYSE-TWO"}]
    securities=[{"security_id":"security:NASDAQ-ONE","company_id":"company:US-CIK0001","ticker":"ONE","primary_listing":True},{"security_id":"security:NYSE-TWO","company_id":"company:US-CIK0002","ticker":"TWO","primary_listing":True}]
    (tmp_path/"data/universe/companies.json").write_text(json.dumps(companies))
    (tmp_path/"data/universe/securities.json").write_text(json.dumps(securities))
    (tmp_path/"data/src").mkdir()
    (tmp_path/"data/src/financial.json").write_text(json.dumps([{"company_id":"company:US-CIK0001","revenue":10}]))
    (tmp_path/"data/src/market.json").write_text(json.dumps([{"ticker":"TWO","market_price":20}]))
    (tmp_path/"data/src/estimate.csv").write_text("ticker,forward_eps\nONE,3\n")
    manifest={"selections":{"financial":{"path":"data/src/financial.json"},"market":{"path":"data/src/market.json"},"estimate":{"path":"data/src/estimate.csv"}}}
    (tmp_path/"manifest.json").write_text(json.dumps(manifest))
    return companies


def test_builder_emits_one_record_per_company(tmp_path):
    fixture(tmp_path); r=build_population(tmp_path,Path("data/universe"),Path("manifest.json")); assert all(len(r["populations"][x])==2 for x in ("financial","market","estimate"))


def test_builder_preserves_missing_as_explicit_false(tmp_path):
    fixture(tmp_path); r=build_population(tmp_path,Path("data/universe"),Path("manifest.json")); rows={x["company_id"]:x for x in r["populations"]["financial"]}; assert rows["company:US-CIK0002"]["data_present"] is False


def test_ticker_linkage(tmp_path):
    fixture(tmp_path); r=build_population(tmp_path,Path("data/universe"),Path("manifest.json")); assert r["summary"]["data_present_company_counts"]["market"]==1


def test_validator(tmp_path):
    fixture(tmp_path); r=build_population(tmp_path,Path("data/universe"),Path("manifest.json")); out=tmp_path/"out"; write_population(r,out); assert validate_population(tmp_path,Path("data/universe"),out)["valid"]
