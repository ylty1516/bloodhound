"""One-time explicit provenance correction for four known browser QA simulations."""
import json
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from prospect.service import data_directory
from prospect.store import Store

known = {
    '6500e59a7d9f27dc535f658c':'2026-11-06T11:32:20.843385+00:00',
    '3623410d9a950ed3aee5950f':'2026-11-06T12:02:53.025209+00:00',
    'f0a739a11a1d03472483b3af':'2026-11-06T12:04:07.814405+00:00',
    'e2d630dd03525ec61dde749f':'2026-11-06T12:04:48.769780+00:00',
}
store = Store(data_directory()/'prospect.sqlite3')
annotated = []
for run in store.runs():
    if run['id'] not in known: continue
    if run.get('mode') != 'simulation' or run.get('at') != known[run['id']] or run.get('candidate_name') != 'vergecurrency/verge':
        raise RuntimeError('Record differs from known browser QA evidence; left untouched')
    store.annotate_validation_run(run['id'], '2026-11-06 开发阶段 browser-qa.mjs 界面验证；未执行挖矿，原始结果保留')
    annotated.append(run['id'])
print(json.dumps({'annotated_ids':annotated,'raw_records_deleted':0,'scope':'only four identified browser QA simulations'}))
