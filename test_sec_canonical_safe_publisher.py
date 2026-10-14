import importlib.util
import json
from pathlib import Path
from unittest.mock import patch

import pytest

SCRIPT = Path(__file__).with_name('AXIOM_SEC_Canonical_Safe_Publisher.py')
spec = importlib.util.spec_from_file_location('sec_safe_publisher', SCRIPT)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


def fixture_tree(path, end='2026-06-30'):
    path.mkdir()
    (path / 'quarterly').mkdir()
    cid='company:US-CIK0000000001'
    (path / 'quarterly' / 'example.json').write_text(json.dumps([{'company_id':cid, 'metric':'revenue','value':'100','period_end':end,'fiscal_year':2026,'fiscal_period':'Q2'}]))
    (path / 'manifest.json').write_text(json.dumps({'summary':{}}))
    (path / 'financial_facts.json').write_text(json.dumps([{'company_id':cid,'metric':'revenue','period_end':end,'value':'100'}]))
    (path / 'quarterly_index.json').write_text(json.dumps({'company_count':1,'company_id_to_file':{cid:'quarterly/example.json'}}))
    (path / 'diagnostics.json').write_text('[]')


def test_validate_tree_and_older_data(tmp_path):
    old=tmp_path/'old';new=tmp_path/'new'
    fixture_tree(old,'2026-06-30');fixture_tree(new,'2025-06-30')
    a=module.validate_tree(old);b=module.validate_tree(new)
    r={'summary':{'quarterly_company_count':4397,'quarterly_financial_fact_count':135954,'quarantined_company_count':133,'source_mode_counts':{'sec_bulk':5671},'companies_requested':5813}}
    failures=module.validate_candidate(a,b,r)
    assert any('regressions' in x for x in failures)


def test_broken_index_rejected(tmp_path):
    path=tmp_path/'tree';fixture_tree(path)
    (path/'quarterly'/'example.json').unlink()
    with pytest.raises(ValueError, match='Broken/unsafe'):
        module.validate_tree(path)


def test_switch_and_explicit_rollback(tmp_path):
    canon=tmp_path/'canonical_financial_population';stage=tmp_path/'stage'
    backup=tmp_path/'canonical_financial_population.backup-123'
    fixture_tree(canon, '2025-06-30');fixture_tree(stage, '2026-06-30')
    module.swap_publish(canon,stage,backup)
    assert module.validate_tree(canon)['quarter_latest']['company:US-CIK0000000001']=='2026-06-30'
    assert module.validate_tree(backup)['quarter_latest']['company:US-CIK0000000001']=='2025-06-30'
    replaced=module.rollback(canon,backup,tmp_path)
    assert replaced is not None and replaced.is_dir()
    assert module.validate_tree(canon)['quarter_latest']['company:US-CIK0000000001']=='2025-06-30'


def test_failed_swap_restores_original(tmp_path):
    canon=tmp_path/'canonical_financial_population';stage=tmp_path/'stage'
    backup=tmp_path/'canonical_financial_population.backup-123'
    fixture_tree(canon);fixture_tree(stage)
    actual=module.os.replace
    def fail_stage(src,dst):
        if Path(src)==stage:
            raise OSError('simulated stage failure')
        return actual(src,dst)
    with patch.object(module.os,'replace',side_effect=fail_stage):
        with pytest.raises(OSError,match='simulated'):
            module.swap_publish(canon,stage,backup)
    assert canon.is_dir() and not backup.exists()
    module.validate_tree(canon)


def test_symlink_rejected(tmp_path):
    canon=tmp_path/'canonical';fixture_tree(canon)
    (canon/'link').symlink_to(tmp_path)
    with pytest.raises(ValueError,match='Symlink'):
        module.validate_tree(canon)


def test_legacy_duplicates_preserved_but_new_duplicates_rejected(tmp_path):
    old = tmp_path / 'old'; new = tmp_path / 'new'
    fixture_tree(old); fixture_tree(new)
    for tree in (old, new):
        path = tree / 'quarterly' / 'example.json'
        rows = json.loads(path.read_text())
        rows.append(dict(rows[0], value='101'))
        path.write_text(json.dumps(rows))
    old_state = module.validate_tree(old)
    new_state = module.validate_tree(new)
    assert len(old_state['quarter_duplicates']) == 1
    report = {'summary': {'quarterly_company_count':4397, 'quarterly_financial_fact_count':135954,
              'quarantined_company_count':133, 'source_mode_counts':{'sec_bulk':5671},
              'companies_requested':5813}}
    assert not any('New/worsened quarterly duplicate' in x
                   for x in module.validate_candidate(old_state, new_state, report))
    path = new / 'quarterly' / 'example.json'
    rows = json.loads(path.read_text()); rows.append(dict(rows[0], value='102'))
    path.write_text(json.dumps(rows))
    new_state = module.validate_tree(new)
    assert any('New/worsened quarterly duplicate' in x
               for x in module.validate_candidate(old_state, new_state, report))


def test_legacy_fiscal_collision_preserved_but_new_collision_rejected(tmp_path):
    old=tmp_path/'old'; new=tmp_path/'new'
    fixture_tree(old); fixture_tree(new)
    for tree in (old, new):
        p=tree/'quarterly'/'example.json'
        rows=json.loads(p.read_text())
        rows.append(dict(rows[0], metric='net_income', period_end='2026-03-31'))
        p.write_text(json.dumps(rows))
    report={'summary':{'quarterly_company_count':4397,'quarterly_financial_fact_count':135954,
            'quarantined_company_count':133,'source_mode_counts':{'sec_bulk':5671},'companies_requested':5813}}
    prev=module.validate_tree(old)
    current=module.validate_tree(new)
    assert len(prev['fiscal_identity_conflicts'])==1
    assert not any('FY/Q period collision' in f for f in module.validate_candidate(prev,current,report))
    path=new/'quarterly'/'example.json'
    rows=json.loads(path.read_text())
    rows[-1]['period_end']='2026-04-01'
    path.write_text(json.dumps(rows))
    current=module.validate_tree(new)
    assert any('New/worsened FY/Q period collision' in f for f in module.validate_candidate(prev,current,report))

def test_new_fiscal_collision_rejected_when_old_was_clean(tmp_path):
    old=tmp_path/'old'; new=tmp_path/'new'
    fixture_tree(old); fixture_tree(new)
    path=new/'quarterly'/'example.json'
    rows=json.loads(path.read_text())
    rows.append(dict(rows[0], metric='net_income', period_end='2026-03-31'))
    path.write_text(json.dumps(rows))
    report={'summary':{'quarterly_company_count':4397,'quarterly_financial_fact_count':135954,
            'quarantined_company_count':133,'source_mode_counts':{'sec_bulk':5671},'companies_requested':5813}}
    assert any('New/worsened FY/Q period collision' in f for f in module.validate_candidate(module.validate_tree(old),module.validate_tree(new),report))
