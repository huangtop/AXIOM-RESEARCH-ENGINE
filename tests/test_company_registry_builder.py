import json
from pathlib import Path
import pytest
from typer.testing import CliRunner

from axiom_engine.cli import app
from axiom_engine.company_registry_builder import build_real_100_registry, validate_real_100_registry


def fixtures(tmp_path: Path, count: int = 100):
    cohort = {"schema_version":"1.0.0","cohort_id":"cohort:test-100","name":"Test","selection_policy":"fixed","company_count":count,"symbols":[{"rank":i,"ticker":f"T{i:03d}","exchange_hint":None} for i in range(1,count+1)]}
    sec = {"fields":["cik","name","ticker","exchange"],"data":[[i,f"Company {i}",f"T{i:03d}","Nasdaq"] for i in range(1,count+1)]}
    cp=tmp_path/'cohort.json'; sp=tmp_path/'sec.json'; cp.write_text(json.dumps(cohort)); sp.write_text(json.dumps(sec)); return cp,sp


def test_dry_run_resolves_100_without_writes(tmp_path):
    cp,sp=fixtures(tmp_path); out=tmp_path/'source.json'; reg=tmp_path/'registry'
    r=build_real_100_registry(user_agent='AXIOM test@example.com',cohort_path=str(cp),sec_file=str(sp),source_output=str(out),registry_dir=str(reg))
    assert r.companies_resolved == 100 and r.dry_run
    assert not out.exists() and not reg.exists()


def test_write_builds_canonical_registry(tmp_path):
    cp,sp=fixtures(tmp_path); out=tmp_path/'source.json'; reg=tmp_path/'registry'
    r=build_real_100_registry(user_agent='AXIOM test@example.com',cohort_path=str(cp),sec_file=str(sp),source_output=str(out),registry_dir=str(reg),write=True)
    assert r.securities_resolved == 100
    assert len(json.loads((reg/'companies.json').read_text())) == 100
    assert validate_real_100_registry(str(cp),str(reg))["acceptance_passed"]


def test_refuses_incomplete_write(tmp_path):
    cp,sp=fixtures(tmp_path); payload=json.loads(sp.read_text()); payload['data'].pop(); sp.write_text(json.dumps(payload))
    with pytest.raises(ValueError, match='incomplete'):
        build_real_100_registry(user_agent='AXIOM test@example.com',cohort_path=str(cp),sec_file=str(sp),source_output=str(tmp_path/'x.json'),registry_dir=str(tmp_path/'r'),write=True)


def test_dot_ticker_matches_sec_dash(tmp_path):
    cohort={"schema_version":"1.0.0","cohort_id":"cohort:x","name":"X","selection_policy":"fixed","company_count":1,"symbols":[{"rank":1,"ticker":"BRK.B","exchange_hint":None}]}
    sec={"fields":["cik","name","ticker","exchange"],"data":[[1067983,"Berkshire Hathaway Inc.","BRK-B","NYSE"]]}
    cp=tmp_path/'c.json'; sp=tmp_path/'s.json'; cp.write_text(json.dumps(cohort)); sp.write_text(json.dumps(sec))
    r=build_real_100_registry(user_agent='x@y.com',cohort_path=str(cp),sec_file=str(sp))
    assert r.companies_resolved == 1


def test_user_agent_required_for_network():
    with pytest.raises(ValueError, match='contact email'):
        build_real_100_registry(user_agent='AXIOM',cohort_path='missing.json')


def test_cli_commands_present():
    help_result=CliRunner().invoke(app,['--help'])
    assert 'build-real-100-company-registry' in help_result.stdout
    assert 'validate-real-100-company-registry' in help_result.stdout


def test_network_gzip_response_is_decoded(tmp_path, monkeypatch):
    import gzip
    from axiom_engine.company_registry_builder import core

    cp, _ = fixtures(tmp_path, count=1)
    payload = {
        "fields": ["cik", "name", "ticker", "exchange"],
        "data": [[1, "Company 1", "T001", "Nasdaq"]],
    }
    compressed = gzip.compress(json.dumps(payload).encode("utf-8"))

    class Headers:
        def get(self, key, default=None):
            return "gzip" if key == "Content-Encoding" else default

    class Response:
        headers = Headers()
        def __enter__(self): return self
        def __exit__(self, *args): return False
        def read(self): return compressed

    monkeypatch.setattr(core.urllib.request, "urlopen", lambda request, timeout: Response())
    result = build_real_100_registry(
        user_agent="AXIOM test@example.com",
        cohort_path=str(cp),
    )
    assert result.companies_resolved == 1


def test_network_gzip_magic_is_decoded_without_header(tmp_path, monkeypatch):
    import gzip
    from axiom_engine.company_registry_builder import core

    cp, _ = fixtures(tmp_path, count=1)
    payload = {
        "fields": ["cik", "name", "ticker", "exchange"],
        "data": [[1, "Company 1", "T001", "Nasdaq"]],
    }
    compressed = gzip.compress(json.dumps(payload).encode("utf-8"))

    class Headers:
        def get(self, key, default=None): return default

    class Response:
        headers = Headers()
        def __enter__(self): return self
        def __exit__(self, *args): return False
        def read(self): return compressed

    monkeypatch.setattr(core.urllib.request, "urlopen", lambda request, timeout: Response())
    result = build_real_100_registry(
        user_agent="AXIOM test@example.com",
        cohort_path=str(cp),
    )
    assert result.companies_resolved == 1


def test_non_ascii_user_agent_is_rejected_cleanly():
    with pytest.raises(ValueError, match="ASCII"):
        build_real_100_registry(
            user_agent="AXIOM 你的信箱@example.com",
            cohort_path="missing.json",
        )


def test_verified_ticker_change_alias_resolves_mmc_to_mrsh(tmp_path):
    cohort={"schema_version":"1.0.0","cohort_id":"cohort:x","name":"X","selection_policy":"fixed","company_count":1,"symbols":[{"rank":1,"ticker":"MMC","exchange_hint":"NYSE"}]}
    sec={"fields":["cik","name","ticker","exchange"],"data":[[62709,"Marsh & McLennan Companies, Inc.","MRSH","NYSE"]]}
    cp=tmp_path/'c.json'; sp=tmp_path/'s.json'; out=tmp_path/'source.json'; reg=tmp_path/'registry'
    cp.write_text(json.dumps(cohort)); sp.write_text(json.dumps(sec))
    result=build_real_100_registry(user_agent='x@y.com',cohort_path=str(cp),sec_file=str(sp),source_output=str(out),registry_dir=str(reg),write=True)
    assert result.companies_resolved == 1
    source=json.loads(out.read_text())
    assert source['securities'][0]['ticker'] == 'MMC'
    assert source['companies'][0]['metadata']['sec_current_ticker'] == 'MRSH'
    assert source['companies'][0]['metadata']['ticker_alias_applied'] is True
    assert validate_real_100_registry(str(cp),str(reg))["acceptance_passed"]
