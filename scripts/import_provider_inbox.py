#!/usr/bin/env python3
from __future__ import annotations
import argparse, json, shutil, subprocess, sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
if str(ROOT/'src') not in sys.path: sys.path.insert(0,str(ROOT/'src'))
from axiom_engine.production_refresh import build_provider_intake_receipt, provider_archive_filename, provider_response_content_hash

def _load_stdout_report(text: str):
    try: return json.loads(text)
    except Exception: return {}

def main():
    p=argparse.ArgumentParser(description='Import provider responses and archive every processed intake file')
    p.add_argument('--repository-root',default='.')
    p.add_argument('--inbox',default='data/provider_intake/inbox')
    p.add_argument('--contracts-dir',default='data/generated/production_refresh/provider_contracts')
    p.add_argument('--processed-dir',default='data/provider_intake/processed')
    p.add_argument('--failed-dir',default='data/provider_intake/failed')
    p.add_argument('--receipts-dir',default='data/provider_intake/receipts')
    p.add_argument('--retain-inbox',action='store_true')
    p.add_argument('--strict',action='store_true'); a=p.parse_args()
    root=Path(a.repository_root).resolve(); inbox=root/a.inbox; contracts=root/a.contracts_dir
    processed=root/a.processed_dir; failed=root/a.failed_dir; receipts=root/a.receipts_dir
    for path in (inbox,processed,failed,receipts): path.mkdir(parents=True,exist_ok=True)
    known={p.stem for p in receipts.glob('*.json')}
    imports=[]; failures=[]; skipped=[]
    for response in sorted(inbox.glob('*_batch_response.json')):
        digest=provider_response_content_hash(response.read_bytes())
        layer=response.name.split('_batch_response.json')[0]
        if digest in known:
            archive=processed/provider_archive_filename(response.name,digest,status='duplicate')
            if not a.retain_inbox: shutil.move(str(response),archive)
            skipped.append({'layer':layer,'response':str(response.relative_to(root)),'reason':'duplicate_content','content_sha256':digest,'archive_path':str(archive.relative_to(root))})
            continue
        request=contracts/f'{layer}_batch_request.json'
        if not request.exists():
            reason='missing_batch_request'; archive=failed/provider_archive_filename(response.name,digest,status='failed')
            if not a.retain_inbox: shutil.move(str(response),archive)
            receipt=build_provider_intake_receipt(response_path=str(response.relative_to(root)),content_hash=digest,status='failed',layer=layer,failure_reason=reason)
            (receipts/f'{digest}.json').write_text(json.dumps(receipt,ensure_ascii=False,indent=2),encoding='utf-8')
            failures.append({'response':str(response.relative_to(root)),'reason':reason,'archive_path':str(archive.relative_to(root))}); continue
        cmd=[sys.executable,str(ROOT/'scripts/import_provider_batch_response.py'),'--repository-root',str(root),'--request',str(request.relative_to(root)),'--response',str(response.relative_to(root))]
        if a.strict: cmd.append('--strict')
        cp=subprocess.run(cmd,cwd=root,text=True,capture_output=True); report=_load_stdout_report(cp.stdout)
        ok=cp.returncode==0 and bool(report.get('valid'))
        status='accepted' if ok else 'failed'; target_dir=processed if ok else failed
        archive=target_dir/provider_archive_filename(response.name,digest,status=status)
        if not a.retain_inbox: shutil.move(str(response),archive)
        receipt=build_provider_intake_receipt(response_path=str(response.relative_to(root)),content_hash=digest,status=status,layer=layer,import_report=report,failure_reason=None if ok else 'import_failed')
        (receipts/f'{digest}.json').write_text(json.dumps(receipt,ensure_ascii=False,indent=2),encoding='utf-8'); known.add(digest)
        item={'layer':layer,'response':str(response.relative_to(root)),'returncode':cp.returncode,'content_sha256':digest,'archive_path':str(archive.relative_to(root)),'receipt_path':str((receipts/f'{digest}.json').relative_to(root)),'stdout_tail':cp.stdout[-2000:],'stderr_tail':cp.stderr[-2000:]}
        if ok: imports.append(item)
        else: failures.append({**item,'reason':'import_failed'})
    summary={'schema_version':'provider-inbox-import-summary.v030.7.1','version':'V030.7.1','status':'failed' if failures else ('no_input' if not imports and not skipped else 'completed'),'inbox_path':str(inbox.relative_to(root)),'import_count':len(imports),'failure_count':len(failures),'skipped_count':len(skipped),'imports':imports,'failures':failures,'skipped':skipped}
    out=root/'data/generated/production_refresh/provider_imports/inbox_import_summary.json'; out.parent.mkdir(parents=True,exist_ok=True); out.write_text(json.dumps(summary,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(summary,ensure_ascii=False,indent=2)); return 2 if a.strict and failures else 0
if __name__=='__main__': raise SystemExit(main())
