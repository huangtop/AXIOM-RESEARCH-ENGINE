#!/usr/bin/env python3
from __future__ import annotations
import argparse,json,subprocess,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]

def main():
    p=argparse.ArgumentParser(description='Import all provider response files present in the intake inbox')
    p.add_argument('--repository-root',default='.')
    p.add_argument('--inbox',default='data/provider_intake/inbox')
    p.add_argument('--contracts-dir',default='data/generated/production_refresh/provider_contracts')
    p.add_argument('--strict',action='store_true'); a=p.parse_args()
    root=Path(a.repository_root).resolve(); inbox=root/a.inbox; contracts=root/a.contracts_dir
    imports=[]; failures=[]
    if inbox.exists():
        for response in sorted(inbox.glob('*_batch_response.json')):
            layer=response.name.split('_batch_response.json')[0]
            request=contracts/f'{layer}_batch_request.json'
            if not request.exists(): failures.append({'response':str(response),'reason':'missing_batch_request'}); continue
            cmd=[sys.executable,str(ROOT/'scripts/import_provider_batch_response.py'),'--repository-root',str(root),'--request',str(request.relative_to(root)),'--response',str(response.relative_to(root))]
            if a.strict: cmd.append('--strict')
            cp=subprocess.run(cmd,cwd=root,text=True,capture_output=True)
            imports.append({'layer':layer,'response':str(response.relative_to(root)),'returncode':cp.returncode,'stdout_tail':cp.stdout[-2000:],'stderr_tail':cp.stderr[-2000:]})
            if cp.returncode: failures.append({'response':str(response),'reason':'import_failed'})
    summary={'schema_version':'provider-inbox-import-summary.v030.7.0','version':'V030.7.0','import_count':len(imports),'failure_count':len(failures),'imports':imports,'failures':failures}
    out=root/'data/generated/production_refresh/provider_imports/inbox_import_summary.json'; out.parent.mkdir(parents=True,exist_ok=True); out.write_text(json.dumps(summary,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(summary,ensure_ascii=False,indent=2)); return 2 if a.strict and failures else 0
if __name__=='__main__': raise SystemExit(main())
