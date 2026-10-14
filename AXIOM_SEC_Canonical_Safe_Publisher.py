#!/usr/bin/env python3
"""AXIOM SEC canonical release gate. Default: stage and validate, NO canonical writes.

Required existing local V7 Safe Merge writer. Full bulk run only. During publish,
canonical is briefly unavailable between two same-filesystem renames; rollback
backup remains available. Do not run concurrently with a canonical consumer/writer.
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
import uuid
from collections import Counter
from datetime import datetime, timezone, date
from pathlib import Path

CANON_REL = Path('data/generated/canonical_financial_population')
MIN_COMPANIES = 4397
MIN_QUARTER_ROWS = 135954
MAX_QUARANTINE = 133
REQUIRED_QUARTERS = {
    'CRM': ('0001108524', 8),
    'ONTO': ('0000704532', 8),
    'CBRS': ('0002021728', 4),
    'SNDK': ('0002023554', 8),
}
REQUIRED_Q4 = {
    'CRM': {'2025-01-31': {'revenue': '9993000000', 'net_income': '1708000000'},
            '2026-01-31': {'revenue': '11201000000', 'net_income': '1943000000'}},
    'ONTO': {'2024-12-28': {'revenue': '263939000', 'net_income': '48817000'},
             '2026-01-03': {'revenue': '266866000', 'net_income': '10529000'}},
    'SNDK': {'2025-06-27': {'revenue': '1901000000', 'net_income': '-23000000'},
             '2026-07-03': {'revenue': '8965000000', 'net_income': '6903000000'}},
}


def load(path):
    return json.loads(path.read_text(encoding='utf-8'))


def safe_tree(path):
    if not path.is_dir() or path.is_symlink():
        raise ValueError(f'Not a safe directory: {path}')
    for p in path.rglob('*'):
        if p.is_symlink():
            raise ValueError(f'Symlink in canonical/staging is not allowed: {p}')


def safe_index_path(root, rel):
    if not isinstance(rel, str) or not rel or Path(rel).is_absolute():
        raise ValueError(f'Invalid indexed file: {rel}')
    p = root / rel
    if not p.resolve().is_relative_to(root.resolve()) or not p.is_file() or p.is_symlink():
        raise ValueError(f'Broken/unsafe indexed file: {rel}')
    return p


def validate_tree(root):
    safe_tree(root)
    required = ('manifest.json', 'financial_facts.json', 'quarterly_index.json', 'diagnostics.json')
    for filename in required:
        if not (root / filename).is_file():
            raise ValueError(f'Missing canonical file: {filename}')
    manifest = load(root / 'manifest.json')
    annual = load(root / 'financial_facts.json')
    index_data = load(root / 'quarterly_index.json')
    diagnostics = load(root / 'diagnostics.json')
    if not isinstance(annual, list) or not isinstance(diagnostics, list):
        raise ValueError('Invalid annual/diagnostics JSON structures')
    index = index_data.get('company_id_to_file')
    if not isinstance(index, dict) or index_data.get('company_count') != len(index):
        raise ValueError('Quarterly index count/structure invalid')
    quarter_latest = {}
    quarter_data = {}
    quarter_duplicates = {}
    fiscal_identity_ends = {}
    for cid, rel in index.items():
        rows = load(safe_index_path(root, rel))
        if not isinstance(rows, list):
            raise ValueError(f'Invalid quarterly rows {cid}')
        if any(row.get('company_id') != cid for row in rows):
            raise ValueError(f'Quarterly company mismatch {cid}')
        seen = Counter()
        for r in rows:
            period = (r.get('fiscal_year'), r.get('fiscal_period'))
            end = str(r.get('period_end') or '')
            date.fromisoformat(end)
            fiscal_identity_ends.setdefault((cid, *period), set()).add(end)
            key = (r.get('metric'), end)
            seen[key] += 1
        duplicates = {key: count for key, count in seen.items() if count > 1}
        if duplicates:
            quarter_duplicates[cid] = duplicates
        quarter_latest[cid] = max((str(r['period_end']) for r in rows), default='')
        quarter_data[cid] = rows
    annual_latest = {}
    for row in annual:
        cid = str(row.get('company_id') or '')
        end = str(row.get('period_end') or '')
        if cid and end:
            date.fromisoformat(end)
            annual_latest[cid] = max(end, annual_latest.get(cid, ''))
    fiscal_identity_conflicts = {k: frozenset(v) for k, v in fiscal_identity_ends.items() if len(v) > 1}
    return {'index': index, 'quarter_data': quarter_data, 'quarter_latest': quarter_latest,
            'quarter_duplicates': quarter_duplicates,
            'fiscal_identity_conflicts': fiscal_identity_conflicts,
            'annual_latest': annual_latest, 'manifest': manifest,
            'annual_count': len(annual), 'index_count': len(index)}


def validate_candidate(old, new, report):
    failures = []
    # Legacy canonical can already have multiple metrics for one period.  Do not
    # erase quarantined history just to pass the release gate, but prevent any
    # newly created or worsened duplicate metric/period in the staged release.
    for cid, duplicates in new['quarter_duplicates'].items():
        previous = old['quarter_duplicates'].get(cid, {})
        worsened = [(key, count, previous.get(key, 1))
                    for key, count in duplicates.items()
                    if count > previous.get(key, 1)]
        if worsened:
            failures.append(f'New/worsened quarterly duplicate metric/end: {cid} {worsened[:5]}')
    for label, old_map, new_map in (
        ('quarterly_index', old['index'], new['index']),
        ('annual_companies', old['annual_latest'], new['annual_latest']),
    ):
        lost = sorted(set(old_map) - set(new_map))
        if lost:
            failures.append(f'{label} disappeared: {len(lost)}, examples={lost[:8]}')
    for label in ('quarter_latest', 'annual_latest'):
        regressions = [(cid, end, new[label].get(cid)) for cid, end in old[label].items()
                       if cid in new[label] and new[label][cid] < end]
        if regressions:
            failures.append(f'{label} regressions: {len(regressions)}, examples={regressions[:8]}')
    stats = report['summary']
    if stats.get('quarterly_company_count', 0) < MIN_COMPANIES:
        failures.append('Quarterly company count under acceptance floor')
    if stats.get('quarterly_financial_fact_count', 0) < MIN_QUARTER_ROWS:
        failures.append('Quarterly row count under acceptance floor')
    if stats.get('quarantined_company_count', 10**9) > MAX_QUARANTINE:
        failures.append('Quarantine count exceeds accepted baseline')
    if stats.get('source_mode_counts') != {'sec_bulk': 5671}:
        failures.append('SEC source modes differ from accepted full ZIP baseline')
    if stats.get('companies_requested') != 5813:
        failures.append('Not a full-scope SEC report')
    # Existing canonical may contain FY/Q collisions in quarantined companies.
    # Safe Merge intentionally preserves their old full quarterly files to avoid
    # losing newer periods. Do not publish *new* or *worsened* collisions.
    # Compare exact period-end sets, not just the count of collision groups.
    for key, new_ends in new['fiscal_identity_conflicts'].items():
        old_ends = old['fiscal_identity_conflicts'].get(key, frozenset())
        if not old_ends or not new_ends.issubset(old_ends):
            failures.append(
                f'New/worsened FY/Q period collision: {key} '
                f'old={sorted(old_ends)} staged={sorted(new_ends)}'
            )
    for ticker, (cik, count) in REQUIRED_QUARTERS.items():
        cid = f'company:US-CIK{cik}'
        periods = {(r['fiscal_year'], r['fiscal_period'], r['period_end'])
                   for r in new['quarter_data'].get(cid, [])}
        if len(periods) != count:
            failures.append(f'{ticker}: expected {count} quarterly periods, got {len(periods)}')
    from decimal import Decimal
    for ticker, periods in REQUIRED_Q4.items():
        cik = REQUIRED_QUARTERS[ticker][0]
        cid = f'company:US-CIK{cik}'
        by_key = {(r['period_end'], r['fiscal_period'], r['metric']): r
                  for r in new['quarter_data'].get(cid, [])}
        for end, values in periods.items():
            for metric, expected in values.items():
                row = by_key.get((end, 'Q4', metric))
                if row is None or Decimal(str(row['value'])) != Decimal(expected):
                    failures.append(f'{ticker} {end} Q4 {metric}: expected {expected}')
    return failures


def ensure_locked(parent):
    lock = parent / '.axiom-sec-canonical-publisher.lock'
    lock.mkdir()  # atomic exclusive lock, remains on hard-crash; manual review required
    (lock / 'owner.json').write_text(json.dumps({'pid': os.getpid(), 'started': datetime.now(timezone.utc).isoformat()}))
    return lock


def build_stage(root, bulk_zip, stage):
    sys.path.insert(0, str(root / 'src'))
    from axiom_engine.sec_financial_population import build_sec_financial_population, write_sec_financial_population
    report = build_sec_financial_population(root, bulk_zip=bulk_zip, cache_ttl_days=-1, write_cache=False)
    print('Source summary:', report['summary'], flush=True)
    write_sec_financial_population(report, stage, merge_existing=True)
    return report


def swap_publish(canon, stage, backup):
    """Move current canonical to durable backup; move staged candidate into place.

    The two renames are NOT a fully atomic directory exchange. Stop concurrent
    canonical consumers during this short window; backup supports recovery.
    """
    if canon.exists() is False or backup.exists():
        raise ValueError('Canonical missing or backup collision')
    os.replace(canon, backup)
    try:
        os.replace(stage, canon)
    except BaseException:
        if not canon.exists() and backup.exists():
            os.replace(backup, canon)
        raise


def rollback(canon, backup, parent):
    if backup.parent.resolve() != parent.resolve() or not backup.name.startswith(canon.name + '.backup-'):
        raise ValueError('Rollback accepts only publisher backup within canonical parent')
    safe_tree(backup)
    validate_tree(backup)
    if canon.exists():
        # Keep current release as separately named failed/replaced release for inspection.
        replaced = parent / (canon.name + '.replaced-' + uuid.uuid4().hex[:12])
        os.replace(canon, replaced)
        try:
            os.replace(backup, canon)
        except BaseException:
            os.replace(replaced, canon)
            raise
        return replaced
    os.replace(backup, canon)
    return None


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, default=Path.cwd())
    parser.add_argument('--bulk-zip', type=Path, default=Path('/tmp/axiom-sec-companyfacts.zip'))
    group = parser.add_mutually_exclusive_group()
    group.add_argument('--publish', action='store_true', help='Explicitly approve publishing after all validations')
    group.add_argument('--rollback', type=Path, help='Restore a previously created publisher backup')
    args = parser.parse_args(argv)
    root = args.root.resolve()
    canon = root / CANON_REL
    parent = canon.parent
    if not parent.is_dir() or not canon.is_dir() and not args.rollback:
        parser.error('Existing canonical directory required')
    lock = ensure_locked(parent)
    stage = None
    try:
        if args.rollback:
            preserved = rollback(canon, args.rollback.resolve(), parent)
            print('ROLLBACK COMPLETE. Restored canonical:', canon)
            if preserved:
                print('Previous published release preserved at:', preserved)
            return 0
        if not args.bulk_zip.is_file():
            raise ValueError(f'SEC ZIP missing: {args.bulk_zip}')
        if canon.is_symlink():
            raise ValueError('Canonical must be a real directory, not symlink')
        print('Validating existing canonical...', flush=True)
        old = validate_tree(canon)
        print('Existing legacy duplicate metric/end groups:',
              sum(map(len, old['quarter_duplicates'].values())),
              'across', len(old['quarter_duplicates']), 'companies', flush=True)
        token = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ') + '-' + uuid.uuid4().hex[:8]
        stage = parent / (canon.name + '.staging-' + token)
        backup = parent / (canon.name + '.backup-' + token)
        print('Copying canonical to sibling staging directory...', flush=True)
        shutil.copytree(canon, stage, symlinks=False)
        print('Building from SEC bulk and safe-merging into staging...', flush=True)
        report = build_stage(root, args.bulk_zip, stage)
        print('Validating full staged tree...', flush=True)
        new = validate_tree(stage)
        print('Legacy FY/Q collision groups:', len(old['fiscal_identity_conflicts']),
              'staged FY/Q collision groups:', len(new['fiscal_identity_conflicts']), flush=True)
        print('Staged duplicate metric/end groups:',
              sum(map(len, new['quarter_duplicates'].values())),
              'across', len(new['quarter_duplicates']), 'companies', flush=True)
        failures = validate_candidate(old, new, report)
        print('BEFORE index/annual:', old['index_count'], old['annual_count'])
        print('STAGED index/annual:', new['index_count'], new['annual_count'])
        print('Quarterly holds:', new['manifest']['summary'].get('quarterly_safe_merge_held_company_count'))
        print('VALIDATION:', 'PASS' if not failures else 'FAIL')
        for f in failures[:50]:
            print(' BLOCK:', f)
        if failures:
            return 2
        if not args.publish:
            print('DRY RUN PASS. Canonical unchanged. Staging will be removed.')
            print('To publish, rerun with --publish (builds/validates again).')
            return 0
        print('PUBLISH requested. Swapping on same filesystem; concurrent readers must be stopped.', flush=True)
        swap_publish(canon, stage, backup)
        stage = None
        try:
            validate_tree(canon)
        except BaseException:
            print('Post-swap validation FAILED. Restoring backup...', file=sys.stderr, flush=True)
            rollback(canon, backup, parent)
            raise
        print('PUBLISHED:', canon)
        print('ROLLBACK BACKUP:', backup)
        print('To rollback: python3 AXIOM_SEC_Canonical_Safe_Publisher.py --rollback', backup)
        print('Review git diff and rerun tests before commit/push.')
        return 0
    finally:
        if stage and stage.exists():
            shutil.rmtree(stage)
        shutil.rmtree(lock)


if __name__ == '__main__':
    raise SystemExit(main())
