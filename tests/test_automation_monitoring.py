from __future__ import annotations
import json
from pathlib import Path
from axiom_engine.automation.monitoring import (
    build_metrics, build_trends, collect_operational_snapshot,
    format_automation_status, load_history, record_automation_run,
)

def run(run_id='r1', status='completed', duration=100, stage_status='completed'):
    return {'run_id':run_id,'status':status,'started_at':'2026-01-01T00:00:00+00:00','finished_at':'2026-01-01T00:00:01+00:00','duration_ms':duration,'stage_count':1,'completed_stage_count':int(stage_status=='completed'),'stages':[{'name':'production_refresh','status':stage_status,'duration_ms':duration}]}

def test_build_metrics_counts_success_failure_and_skip():
    m=build_metrics([run(),run('r2','failed',200,'failed'),run('r3','completed',0,'skipped')])
    assert (m['total_runs'],m['successful_runs'],m['failed_runs'])==(3,2,1)
    assert m['skipped_production_refresh_runs']==1

def test_build_metrics_stage_averages():
    m=build_metrics([run(duration=100),run('r2',duration=300)])
    assert m['average_duration_ms']==200 and m['average_stage_duration_ms']['production_refresh']==200

def test_build_trends_window():
    t=build_trends([run(f'r{i}') for i in range(5)],window=3)
    assert t['point_count']==3 and t['points'][0]['run_id']=='r2'

def test_operational_snapshot_reads_coverage_and_ready(tmp_path):
    p=tmp_path/'data/generated/production_refresh/refresh_report.json'; p.parent.mkdir(parents=True)
    p.write_text(json.dumps({'coverage_pct':10.6,'ready_company_count':301}))
    s=collect_operational_snapshot(tmp_path)
    assert s['coverage_pct']==10.6 and s['ready_company_count']==301

def test_record_run_writes_history_metrics_and_trends(tmp_path):
    out=tmp_path/'data/generated/automation'
    result=record_automation_run(tmp_path,run(),out)
    assert Path(result['history_path']).exists()
    assert (out/'automation_metrics.json').exists() and (out/'automation_trends.json').exists()

def test_record_run_deduplicates_by_run_id(tmp_path):
    out=tmp_path/'out'; record_automation_run(tmp_path,run(),out); record_automation_run(tmp_path,run(duration=999),out)
    assert len(list((out/'history').glob('*.json')))==1
    assert load_history(out/'history')[0]['duration_ms']==999

def test_history_retention(tmp_path):
    out=tmp_path/'out'
    for i in range(5): record_automation_run(tmp_path,run(f'r{i}'),out,history_limit=3)
    assert len(load_history(out/'history'))==3

def test_status_formatter_contains_operational_fields(tmp_path):
    out=tmp_path/'out'; record_automation_run(tmp_path,run(),out)
    text=format_automation_status(out)
    assert 'AXIOM Automation V030.8.5' in text and 'Production Refresh: completed' in text and 'Success Rate: 100.0%' in text
