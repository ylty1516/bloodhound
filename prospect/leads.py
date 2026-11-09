"""Lossless discovery catalogue. Unknown evidence is never an exclusion reason."""
from collections import Counter
import hashlib
import json

from .domain import assess,now
from .launch_watch import LaunchWatch
from .project_view import compute_profile,launch_summary
from .store import _json

STAGES={'unverified':'待核实','upcoming':'待开挖','open':'已开放','excluded':'有依据排除'}
COMPUTE=('cpu','gpu','either','none','unknown','asic')
MARKER='lead_catalog_history_v1'


def project_matches(candidate,job):
    prior=job.get('context',{}).get('candidate',{})
    if not prior:return False
    value={key:candidate.get(key) for key in prior}
    return value==prior or hashlib.sha256(_json(value).encode()).hexdigest()==job.get('accepted_project_fingerprint')


class LeadCatalog:
    def __init__(self,store):self.store=store

    def initialize(self):
        """One-time provenance only: no candidate, source or model is rewritten."""
        with self.store._connection(write=True) as db:
            if db.execute('SELECT 1 FROM settings WHERE key=?',(MARKER,)).fetchone():return
            watched={json.loads(row[0])['candidate_id'] for row in db.execute('SELECT payload FROM launch_watch')}
            ids=[row[0] for row in db.execute('SELECT id FROM candidates ORDER BY id') if row[0] not in watched]
            value={'at':now(),'legacy_candidate_ids':ids,'meaning':'Historical catalogue membership; not a negative project assessment.'}
            db.execute('INSERT INTO settings VALUES (?,?)',(MARKER,_json(value)))
            self.store._event(db,'lead_catalog_initialized',{'legacy_count':len(ids),'candidates_deleted':0})

    def _reports(self):
        with self.store._connection() as db:
            if not db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='agent_checks'").fetchone():return {}
            reports={}
            for row in db.execute("SELECT payload FROM agent_checks WHERE status='completed' ORDER BY rowid DESC"):
                job=json.loads(row[0]);reports.setdefault(job['candidate_id'],job)
            return reports

    def records(self):
        legacy=set(self.store.get_setting(MARKER,{}).get('legacy_candidate_ids',[]))
        watched={item['candidate_id']:item for item in LaunchWatch(self.store).view()['items']}
        reports=self._reports();hardware=self.store.hardware();profile=self.store.profile();result=[]
        for candidate in self.store.candidates():
            task=watched.get(candidate['id']);job=reports.get(candidate['id']);report=(job or {}).get('report') or {}
            matches=bool(job and project_matches(candidate,job))
            direction=compute_profile(candidate,report if matches else None)
            if task:
                compute=task['compute'];direction={'priority':compute,
                    'label':{'cpu':'CPU 优先','gpu':'GPU 其次','either':'CPU / GPU 均可 · CPU 优先','none':'网页 / 轻量任务','unknown':'设备待确认','asic':'ASIC 方向'}[compute],
                    'basis':'launch_announcement','reason':'公告中的设备方向；优先级不代表收益。','sources':[task['evidence_url']]}
            stage='unverified';reason_code='announcement_unverified';sources=[]
            reason='已有公开线索，尚缺足够的官方主网开挖证据，需要继续核对。'
            if candidate['id'] in legacy:
                reason_code='legacy_unreviewed';reason='历史存档，尚未逐项复核；未进入重点待办不代表项目无价值或不能参与。'
            if job:
                reason_code='launch_still_unverified';reason='已有完成的 Agent 报告，当前仍缺明确的主网开挖证据。检查完成不代表安全通过或运行已接入。'
                if not matches:reason+=' 项目资料与当时报告已有变化，需要复核。'
            if task:
                sources=[task['evidence_url']]
                reason_code='launch_awaiting_confirmation';reason='收到了挖掘预告，官方身份、主网窗口或具体时间仍需核实。'
                primary=task['evidence_kind']=='primary'
                if task['phase']=='not_started' and primary and task['network']=='mainnet':
                    stage='upcoming';reason_code='mainnet_not_started';reason=task['evidence_note']
                elif task['phase']=='open' and primary:
                    stage='open';reason_code='announced_open';reason='已有来源说明已开放，不属于当前“尚未开挖”的重点范围；资料仍保留可查。 '+task['evidence_note']
                elif task['phase'] in ('cancelled','retracted') and primary:
                    stage='excluded';reason_code='announcement_'+task['phase'];reason='开挖公告已取消或撤回，已退出待开挖范围，原始记录保留。 '+task['evidence_note']
                elif task['phase']=='due':
                    reason_code='scheduled_time_reached';reason='公告时间已到，需要核对是否实际开放；不会仅凭倒计时把它写成已开挖。'
                elif task['evidence_stale']:
                    reason_code='evidence_stale';reason='公告超过三天没有成功复核，状态待重新确认。'
            info={'stage':stage,'stage_label':STAGES[stage],'reason_code':reason_code,'reason':reason,'reason_sources':sources,
                'historical':candidate['id'] in legacy,'important':bool(task and task['critical']),
                'todo_id':task['id'] if task else None,'todo_status':task['todo_status'] if task else None,
                'review_status':'completed' if job else 'not_reviewed','review_id':job['id'] if job else None,
                'reviewed_at':(job or {}).get('finished_at'),'project_matches_report':matches if job else None,
                'review_summary':str(report.get('summary',''))[:400] if job else None,
                'source_seen_at':candidate.get('checked_at'),'execution_authorized':False}
            result.append(candidate|{'lead_info':info,'compute_profile':direction,'assessment':assess(candidate,hardware,profile),
                'prelaunch':task,'launch':launch_summary(candidate,None,None)})
        rank={'cpu':0,'either':0,'gpu':1,'none':2,'unknown':3,'asic':4}
        result.sort(key=lambda c:(not c['lead_info']['important'],rank[c['compute_profile']['priority']],c['name'].casefold(),c['id']))
        return result

    def page(self,offset=0,limit=20,q='',stage='all',category='all',compute='all'):
        if type(offset) is not int or offset<0 or type(limit) is not int or not 1<=limit<=50:raise ValueError('分页范围无效：offset≥0，limit为1至50')
        if not isinstance(q,str) or len(q)>160:raise ValueError('搜索词最多160个字符')
        if stage not in ('all',*STAGES) or category not in ('all','pow','node','tasks') or compute not in ('all',*COMPUTE):raise ValueError('线索筛选条件无效')
        records=self.records();needle=q.strip().casefold()
        counts=dict(Counter(item['lead_info']['stage'] for item in records))
        filtered=[item for item in records if (not needle or needle in (item['name']+' '+item['summary']+' '+item['id']+' '+item['url']).casefold())
            and (stage=='all' or item['lead_info']['stage']==stage) and (category=='all' or item['category']==category)
            and (compute=='all' or item['compute_profile']['priority']==compute or item['compute_profile']['priority']=='either' and compute in ('cpu','gpu'))]
        return {'items':filtered[offset:offset+limit],'total':len(records),'matched':len(filtered),'offset':offset,'limit':limit,
            'next_offset':offset+limit if offset+limit<len(filtered) else None,'counts':{key:counts.get(key,0) for key in STAGES},
            'important_count':sum(item['lead_info']['important'] for item in records),
            'reviewed_count':sum(item['lead_info']['review_status']=='completed' for item in records),
            'filters':{'q':q,'stage':stage,'category':category,'compute':compute}}

    def detail(self,ident):
        if not isinstance(ident,str) or not 1<=len(ident)<=160:raise ValueError('线索ID无效')
        item=next((item for item in self.records() if item['id']==ident),None)
        if item is None:raise ValueError('找不到这条线索')
        return item
