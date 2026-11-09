"""Capture a private, consistent baseline and verify restore into a separate file.

Never replaces the live database, reads credentials or starts research/mining.
Only counts, hashes and backup references are written to the project evidence.
"""
import datetime as dt
import hashlib
import json
from pathlib import Path
import sqlite3
import sys
import zipfile

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from prospect.cli import request
from prospect.service import data_directory


def digest_file(path):return hashlib.sha256(path.read_bytes()).hexdigest()


def logical_digest(connection):
    digest=hashlib.sha256()
    for line in connection.iterdump():digest.update(line.encode('utf-8'));digest.update(b'\n')
    return digest.hexdigest()


def main():
    private=data_directory().resolve()
    library=Path('F:/Codex_Save_Library').resolve()
    if private==library or private.is_relative_to(library):
        raise ValueError('Private backup must remain outside the save library')
    source=private/'prospect.sqlite3'
    if not source.is_file():raise ValueError('Canonical database is unavailable; no baseline created')
    stamp=dt.datetime.now(dt.timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
    folder=private/'backups'/('delivery-baseline-'+stamp);folder.mkdir(parents=True)
    database=folder/'prospect.sqlite3'
    with sqlite3.connect(source.as_uri()+'?mode=ro',uri=True) as live,sqlite3.connect(database) as saved:
        live.backup(saved)
    with sqlite3.connect(database) as saved:
        assert saved.execute('PRAGMA integrity_check').fetchone()[0]=='ok'
        counts={name:saved.execute('SELECT count(*) FROM "'+name.replace('"','""')+'"').fetchone()[0]
                for name, in saved.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")}
        ids=[row[0] for row in saved.execute('SELECT id FROM candidates ORDER BY id')]
        settings={key:json.loads(value) for key,value in saved.execute('SELECT key,payload FROM settings')
                  if key in ('profile','agent_models','sources','observation','discovery_policy','monitoring','agent_budget','user_preferences')}
        configuration_digest=hashlib.sha256(json.dumps(settings,sort_keys=True,ensure_ascii=False).encode()).hexdigest()
        original_digest=logical_digest(saved)
        restored=folder/'restore-verification.sqlite3'
        with sqlite3.connect(restored) as copy:saved.backup(copy)
    with sqlite3.connect(restored) as copy:
        assert copy.execute('PRAGMA integrity_check').fetchone()[0]=='ok'
        assert logical_digest(copy)==original_digest
    files=sorted({path for top in ('prospect','web','tests','scripts') for path in (ROOT/top).rglob('*')
                  if path.suffix in ('.py','.js','.mjs','.html','.css') and '__pycache__' not in path.parts}
                 | {ROOT/name for name in ('README.md','AGENTS.md','STATUS.md','EXECUTION_PLAN.md','PROJECT_PLAN.md','ACCEPTANCE.md',
                                           'adapters/bridge.py','adapters/manage.py','docs/DELIVERY_EXECUTION_PLAN.md','docs/delivery-tasks.json')})
    manifest={str(path.relative_to(ROOT)).replace('\\','/'):digest_file(path) for path in files if path.is_file()}
    with zipfile.ZipFile(folder/'source-before-changes.zip','w',zipfile.ZIP_DEFLATED) as archive:
        for relative in manifest:archive.write(ROOT/relative,relative)
    (folder/'manifest.json').write_text(json.dumps({'files':manifest,'configuration_digest':configuration_digest,
        'database_sha256':digest_file(database),'logical_digest':original_digest},ensure_ascii=False,indent=2),'utf-8')
    state=request(private,18766,'/api/ready')
    result={'captured_at':dt.datetime.now(dt.timezone.utc).isoformat(),'task_id':'PLAN-00','status':'verified',
        'private_backup_reference':'backups/'+folder.name,'backup_outside_save_library':True,'sqlite_integrity':'ok',
        'restore_verification':'logical equality in separate private file; live database never replaced',
        'restored_logical_digest_matches':True,'table_counts':counts,'candidate_count':len(ids),
        'candidate_ids_sha256':hashlib.sha256('\n'.join(ids).encode()).hexdigest(),
        'configuration_sha256':configuration_digest,'source_file_count':len(manifest),'source_manifest_sha256':digest_file(folder/'manifest.json'),
        'acceptance_plan_sha256':digest_file(ROOT/'docs/DELIVERY_EXECUTION_PLAN.md'),'acceptance_file_sha256':digest_file(ROOT/'ACCEPTANCE.md'),
        'service_pid':state['pid'],'runtime_configuration_changed':False,'model_calls':0,'mining_started':False,
        'known_external_gaps':['Claude successful native generation','pi interactive CLI/resume','Full DeepSeek Harness runtime','Current discovery-scope 168h observation']}
    (ROOT/'evidence/delivery-baseline.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n','utf-8')
    print(json.dumps({key:result[key] for key in ('task_id','status','candidate_count','source_file_count','restored_logical_digest_matches','service_pid','runtime_configuration_changed')},ensure_ascii=False))


if __name__=='__main__':main()
