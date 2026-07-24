from __future__ import annotations
import csv, json
from pathlib import Path
import pytest
from axiom_engine.real_100_estimate_loader import Real100EstimateError, build_real_100_estimate_template, build_real_100_estimates, validate_real_100_estimates

def write(path, payload): path.write_text(json.dumps(payload), encoding="utf-8")
def registry(root, n=100):
    root.mkdir()
    companies=[{"company_id":f"company:US-{i:03d}"} for i in range(n)]
    securities=[{"company_id":f"company:US-{i:03d}","ticker":f"T{i:03d}","exchange":"NASDAQ","primary_listing":True} for i in range(n)]
    write(root/"companies.json", companies); write(root/"securities.json", securities)

def source(path, n=100):
    estimates=[]
    for i in range(n):
        for metric in ("revenue","net_income","diluted_eps"):
            estimates.append({"ticker":f"T{i:03d}","metric":metric,"value":"10","currency":"USD","period_end":"2027-12-31","fiscal_year":2027,"fiscal_period":"FY","estimate_kind":"consensus_mean","analyst_count":5})
    write(path,{"provider_id":"provider:test","provider_name":"Test","as_of_date":"2026-07-24","estimates":estimates})

def test_template_has_300_rows(tmp_path):
    r=tmp_path/"registry"; registry(r); out=tmp_path/"template.csv"
    report=build_real_100_estimate_template(registry_dir=r,output=out)
    assert report["rows"]==300
    assert len(list(csv.DictReader(out.open())))==300

def test_dry_run_does_not_write(tmp_path):
    r=tmp_path/"registry"; registry(r); s=tmp_path/"source.json"; source(s); out=tmp_path/"estimates"
    report=build_real_100_estimates(s,registry_dir=r,output_dir=out)
    assert report["acceptance_passed"] and not out.exists()

def test_write_and_validate(tmp_path):
    r=tmp_path/"registry"; registry(r); s=tmp_path/"source.json"; source(s); out=tmp_path/"estimates"
    report=build_real_100_estimates(s,registry_dir=r,output_dir=out,diagnostics_file=tmp_path/"diag.json",write=True)
    assert report["estimates_built"]==300
    validation=validate_real_100_estimates(estimate_dir=out,registry_dir=r)
    assert validation["acceptance_passed"]

def test_unknown_ticker_rejected(tmp_path):
    r=tmp_path/"registry"; registry(r,1); s=tmp_path/"source.json"
    write(s,{"estimates":[{"ticker":"BAD","metric":"revenue","value":1,"fiscal_year":2027}]})
    with pytest.raises(Real100EstimateError,match="unknown company"): build_real_100_estimates(s,registry_dir=r)

def test_duplicate_key_rejected(tmp_path):
    r=tmp_path/"registry"; registry(r,1); s=tmp_path/"source.json"
    row={"ticker":"T000","metric":"revenue","value":1,"fiscal_year":2027}
    write(s,{"estimates":[row,row]})
    with pytest.raises(Real100EstimateError,match="duplicate"): build_real_100_estimates(s,registry_dir=r)

def test_no_estimates_are_invented(tmp_path):
    r=tmp_path/"registry"; registry(r,1); s=tmp_path/"source.json"; write(s,{"estimates":[]})
    report=build_real_100_estimates(s,registry_dir=r)
    assert report["estimates_built"]==0 and not report["acceptance_passed"]

def test_empty_generated_template_is_skipped_without_error(tmp_path):
    r=tmp_path/"registry"; registry(r); template=tmp_path/"template.csv"; diag=tmp_path/"diag.json"
    build_real_100_estimate_template(registry_dir=r, output=template)
    report=build_real_100_estimates(template, registry_dir=r, diagnostics_file=diag, write=True)
    assert report["estimates_built"] == 0
    assert report["rows_received"] == 300
    assert report["rows_skipped_blank"] == 300
    assert report["input_status"] == "empty_template"
    assert not report["acceptance_passed"]
    assert diag.exists()


def test_partially_filled_row_remains_an_error(tmp_path):
    r=tmp_path/"registry"; registry(r,1); s=tmp_path/"partial.csv"
    s.write_text("company_id,ticker,metric,value,unit,currency,period_end,fiscal_year,fiscal_period,estimate_kind,analyst_count,source_record_id\ncompany:US-000,T000,revenue,,currency,USD,2027-12-31,2027,FY,consensus_mean,,\n", encoding="utf-8")
    with pytest.raises(Real100EstimateError, match="invalid value"):
        build_real_100_estimates(s, registry_dir=r)

def test_template_prefills_forward_period(tmp_path):
    r=tmp_path/"registry"; registry(r,1); template=tmp_path/"template.csv"
    build_real_100_estimate_template(registry_dir=r, output=template, fiscal_year=2028, period_end="2028-09-30")
    rows=list(csv.DictReader(template.open()))
    assert rows[0]["fiscal_year"] == "2028"
    assert rows[0]["period_end"] == "2028-09-30"


def test_generic_adapter_accepts_provider_aliases(tmp_path):
    r=tmp_path/"registry"; registry(r,1); s=tmp_path/"provider.json"
    write(s,{"provider_id":"provider:fmp","estimates":[{"symbol":"T000","field":"eps","consensusMean":"9.5","estimate":"9.5","year":2027,"date":"2027-12-31","numberOfAnalysts":7}]})
    report=build_real_100_estimates(s,registry_dir=r,adapter="fmp",compact=True)
    assert report["estimates_built"] == 1
    assert report["provider_adapter"] == "fmp"
    assert "missing_metrics_by_company" not in report


def test_empty_template_compact_report_has_reason(tmp_path):
    r=tmp_path/"registry"; registry(r,1); template=tmp_path/"template.csv"
    build_real_100_estimate_template(registry_dir=r, output=template)
    report=build_real_100_estimates(template,registry_dir=r,compact=True)
    assert report["reason"] == "Template contains no populated estimate rows."
    assert report["diagnostics"] == "template_not_filled"
    assert report["summary"]["blank_rows"] == 3
    assert "missing_metrics_by_company" not in report


def test_unsupported_adapter_rejected(tmp_path):
    r=tmp_path/"registry"; registry(r,1); s=tmp_path/"source.json"; write(s,{"estimates":[]})
    with pytest.raises(Real100EstimateError, match="unsupported provider adapter"):
        build_real_100_estimates(s,registry_dir=r,adapter="unknown")


def test_cli_template_exposes_forward_period_options():
    from typer.testing import CliRunner
    from axiom_engine.cli import app
    result = CliRunner().invoke(app, ["build-real-100-estimate-template", "--help"])
    assert result.exit_code == 0
    assert "--fiscal-year" in result.stdout
    assert "--period-end" in result.stdout


def test_cli_build_exposes_provider_and_compact_options():
    from typer.testing import CliRunner
    from axiom_engine.cli import app
    result = CliRunner().invoke(app, ["build-real-100-estimates", "--help"])
    assert result.exit_code == 0
    for option in ("--compact", "--adapter", "--provider-id", "--provider-name", "--as-of-date"):
        assert option in result.stdout
