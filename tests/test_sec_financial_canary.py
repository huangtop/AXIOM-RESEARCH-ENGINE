import gzip
import json

from scripts.fetch_sec_financial_canary import CANARY_CIKS, _decode_json


def test_canary_scope_is_exactly_eight_named_companies():
    assert set(CANARY_CIKS) == {"NVDA", "MU", "AMD", "GOOGL", "INTC", "TSLA", "TSM", "ARM"}


def test_decode_json_accepts_sec_gzip_response_by_header():
    payload = {"cik": 1045810, "entityName": "NVIDIA CORP"}
    assert _decode_json(gzip.compress(json.dumps(payload).encode()), "gzip") == payload


def test_decode_json_detects_gzip_magic_bytes_without_header():
    payload = {"filings": {"recent": {}}}
    assert _decode_json(gzip.compress(json.dumps(payload).encode())) == payload
