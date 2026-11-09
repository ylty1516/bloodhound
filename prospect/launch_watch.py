"""Announced mining launches and durable, wallet-independent follow-up tasks.

Discovery is read-only. A task is not an endorsement, audit or execution grant.
"""
from __future__ import annotations
import datetime as dt
from contextlib import nullcontext
import hashlib
import json
import re
import urllib.parse
from html.parser import HTMLParser

from .domain import _url, now
from .store import _json

POLICY = {'id':'announced-before-mining-v1','label':'已公布挖掘消息，主网尚未开挖',
          'compute_order':['cpu','gpu','unknown','asic'],'auto_todo':True,
          'requires_binance_wallet':False,'requires_live_market':False,
          'requires_safety_pass_for_discovery':False,'execution_authorized':False}
SCHEMA = {'type':['object','null'],'properties':{
    'announced':{'type':'boolean'},'status':{'type':'string','enum':['not_started','open','cancelled','unknown']},
    'starts_at':{'type':'string'},'compute':{'type':'string','enum':['cpu','gpu','either','unknown','asic']},
    'network':{'type':'string','enum':['mainnet','testnet','unknown']},
    'wallet':{'type':'string','enum':['binance','native','unknown']},
    'evidence_url':{'type':'string'},'evidence_note':{'type':'string'},
    'evidence_kind':{'type':'string','enum':['primary','community']}},'additionalProperties':False}
SCHEMA['required']=list(SCHEMA['properties'])


def timestamp(value):
    if not value:return None
    if not isinstance(value,str) or len(value)>80:raise ValueError('开挖时间须为带时区的 ISO 时间')
    try:result=dt.datetime.fromisoformat(value.replace('Z','+00:00'))
    except ValueError:raise ValueError('开挖时间须为带时区的 ISO 时间') from None
    if result.tzinfo is None:raise ValueError('开挖时间必须包含时区，不能猜测时区')
    return result.astimezone(dt.timezone.utc)


def validate_signal(value):
    if value is None:return None
    if not isinstance(value,dict) or set(value)!=set(SCHEMA['properties']):raise ValueError('开挖预告字段不完整')
    if type(value['announced']) is not bool:raise ValueError('announced must be boolean')
    for key in ('status','compute','network','wallet','evidence_kind'):
        if value[key] not in SCHEMA['properties'][key]['enum']:raise ValueError('Invalid launch '+key)
    for key,maximum in (('evidence_note',1200),('evidence_url',2000),('starts_at',80)):
        if not isinstance(value[key],str) or len(value[key])>maximum:raise ValueError('Invalid launch '+key)
    if not value['evidence_note'].strip():raise ValueError('开挖消息必须保留直接证据说明')
    result=dict(value);result['evidence_url']=_url(value['evidence_url'])
    parsed=timestamp(value['starts_at']);result['starts_at']=parsed.isoformat() if parsed else ''
    return result


class Text(HTMLParser):
    def __init__(self):super().__init__(convert_charrefs=True);self.parts=[];self.hidden=0
    def handle_starttag(self,tag,attrs):
        if tag in ('script','style'):self.hidden+=1
        if tag in ('p','div','br','li','h1','h2','h3'):self.parts.append('\n')
    def handle_endtag(self,tag):
        if tag in ('script','style'):self.hidden=max(0,self.hidden-1)
    def handle_data(self,data):
        if not self.hidden:self.parts.append(data)


def plain(value):
    parser=Text();parser.feed(value[:1_500_000]);return re.sub(r'[ \t]+',' ',' '.join(parser.parts))[:90000]


def defaults():
    def gh(query):return 'https://api.github.com/search/repositories?'+urllib.parse.urlencode({'q':query,'sort':'updated','order':'desc','per_page':20})
    return [
        {'id':'launch-announcements','label':'BitcoinTalk · 新币挖掘公告','url':'https://bitcointalk.org/index.php?board=159.0',
         'kind':'launch_forum','category':'pow','enabled':True,'interval_seconds':900,
         'note':'站方已停用RSS/XML，改读公开公告列表；论坛消息仍需核对正文与官方身份。'},
        {'id':'launch-token-announcements','label':'BitcoinTalk · 代币挖掘线索','url':'https://bitcointalk.org/index.php?board=240.0',
         'kind':'launch_forum','category':'pow','enabled':True,'interval_seconds':1800,
         'note':'覆盖钱包/代币路线中的挖掘公告；不把普通预售当作挖矿。'},
        {'id':'launch-github-cpu','label':'GitHub · CPU 开挖预告线索','url':gh('mining CPU launch in:description'),
         'kind':'github','category':'pow','enabled':True,'interval_seconds':1800,'launch_discovery':True},
        {'id':'launch-github-ann','label':'GitHub · 即将开挖线索','url':gh('mining "coming soon" in:description'),
         'kind':'github','category':'pow','enabled':True,'interval_seconds':1800,'launch_discovery':True},
        {'id':'launch-shear','label':'SHEAR · 官网开挖预告','url':'https://shear.digital/',
         'kind':'launch_page','category':'pow','enabled':True,'interval_seconds':900,
         'project_name':'SHEAR (SHE)','project_identity':'launch:shear.digital','evidence_kind':'primary'},
    ]


def canonical_announcement(url):
    url=_url(url);p=urllib.parse.urlsplit(url)
    if p.hostname=='bitcointalk.org':
        topic=urllib.parse.parse_qs(p.query).get('topic',[''])[0].split('.')[0]
        if topic.isdigit():return 'https://bitcointalk.org/index.php?topic='+topic+'.0'
    return url


def infer(text,url,kind='community'):
    """Conservative lead matching, not independent verification of author claims."""
    body=plain(text);lower=body.lower()
    if not re.search(r'\bmin(?:ing|ed|eable|er)\b|\bpow\b|proof.of.work|挖矿|开挖|挖掘',lower):return None
    if not re.search(r'\bcryptocurrency\b|\bblockchain\b|\bmainnet\b|\btestnet\b|proof.of.work|\bpow\b|加密货币|区块链|主网|矿币',lower):return None
    compute='unknown'
    if re.search(r'\bcpu\b|randomx|shearhash',lower):compute='cpu'
    if re.search(r'\bgpu\b|cuda|opencl',lower):compute='either' if compute=='cpu' else 'gpu'
    # Read only dates explicitly coupled to mainnet/mining launch, never arbitrary milestones.
    launch_re=r'(?:mainnet(?:\s+(?:genesis|launch))?|mining\s+(?:starts?|opens?|launch)|launch\s+(?:date|time)|主网(?:创世|开挖|上线)?|开挖(?:时间)?)[^\n.]{0,125}'
    dates=[];date_only=False
    for match in re.finditer(launch_re,lower):
        context=match.group(0)
        iso=re.search(r'20\d{2}-\d{2}-\d{2}[t ]\d{2}:\d{2}(?::\d{2})?(?:z|\s*utc|[+-]\d{2}:\d{2})',context)
        if iso:
            raw=re.sub(r'\s*utc$','+00:00',iso.group(0));raw=raw[:-1]+'+00:00' if raw.endswith('z') else raw
            try:dates.append(timestamp(raw))
            except ValueError:pass
            continue
        # UK winter dates are UTC; summer UK time remains unconfirmed rather than guessed.
        human=re.search(r'(\d{1,2})(?:st|nd|rd|th)?\s+(january|february|march|april|may|june|july|august|september|october|november|december)\s+(20\d{2})',context)
        if human:
            months='january february march april may june july august september october november december'.split()
            month=months.index(human[2])+1;tail=context[human.end():]
            clock=re.search(r'(\d{1,2})(?::(\d{2}))?\s*(am|pm)\s*(?:uk\s*time|utc)',tail)
            military=re.search(r'(\d{2})(\d{2})hrs\s*(?:uk\s*time|utc)',tail)
            if clock and ('utc' in clock[0] or month in (11,12,1,2)):
                hour=int(clock[1])%12+(12 if clock[3]=='pm' else 0);minute=int(clock[2] or 0)
            elif military and ('utc' in military[0] or month in (11,12,1,2)):hour=int(military[1]);minute=int(military[2])
            else:date_only=True;continue
            try:dates.append(dt.datetime(int(human[3]),month,int(human[1]),hour,minute,tzinfo=dt.timezone.utc))
            except ValueError:continue
    dates=sorted(set(dates));current=dt.datetime.now(dt.timezone.utc)
    starts=dates[0].isoformat() if len(dates)==1 else ''
    explicitly_not_open=bool(re.search(r'mainnet (?:is )?not (?:live|launched)|mining (?:has )?not (?:started|opened)|主网尚未|尚未开挖|未开放挖',lower))
    future=bool(re.search(r'pre[ -]ann|coming soon|will (?:launch|start|open)|launching|genesis(?:\s+block)?\s+incoming|即将.*(?:挖|上线)|将于|预计.*开挖',lower))
    is_open=bool(re.search(r'mainnet\s+(?:(?:is|now)\s+)?live\b|mining\s+(?:is\s+)?(?:now\s+)?open\b|主网已上线|已开放挖矿',lower))
    if dates and max(dates)<=current and not explicitly_not_open and not is_open:return None
    if not (any(d>current for d in dates) or explicitly_not_open or future or date_only or is_open):return None
    network='mainnet' if 'mainnet' in lower or '主网' in lower else 'testnet' if 'testnet' in lower or '测试网' in lower else 'unknown'
    # Sources with incomplete schedules become explicitly unverified tasks, never confirmed openings.
    note='公告提及挖掘和未来开放；需核对官方身份、主网窗口及日期变更。'
    if len(dates)>1:note='发现不同的开挖时间，存在冲突；先核对最新官方公告。'
    status='not_started' if network=='mainnet' and (len(dates)==1 and dates[0]>current or explicitly_not_open) else 'unknown'
    if is_open and not explicitly_not_open:status='open'
    if len(dates)>1:status='unknown'
    return validate_signal({'announced':True,'status':status,'starts_at':starts,'compute':compute,'network':network,
        'wallet':'unknown','evidence_url':url,'evidence_kind':kind,'evidence_note':note})


class LaunchWatch:
    def __init__(self,store):self.store=store

    def migrate(self):
        if self.store.get_setting('observation',{}).get('status')=='running':return
        if self.store.get_setting('launch_watch_migrated'):
            self._upgrade_sources();return
        configured=self.store.get_setting('sources',[]);new=defaults();known={s['id'] for s in new}
        settings={'sources':[s|{'enabled':False} for s in configured if s['id'] not in known]+new,
            'discovery_policy':POLICY,'monitoring':{'enabled':True,'mode':'rules_only','updated_at':now()},'launch_watch_migrated':True,
            'launch_source_revision':'public-forum-v1'}
        with self.store._connection(write=True) as db:
            for key,value in settings.items():
                db.execute('INSERT INTO settings VALUES (?,?) ON CONFLICT(key) DO UPDATE SET payload=excluded.payload',(key,_json(value)))
            self.store._event(db,'launch_watch_policy_changed',POLICY)

    def _upgrade_sources(self):
        if self.store.get_setting('launch_source_revision')=='public-forum-v1':return
        if self.store.get_setting('observation',{}).get('status')=='running':return
        old_url='https://bitcointalk.org/index.php?board=159.0&type=rss&action=.xml&limit=30'
        with self.store._connection(write=True) as db:
            def setting(key,default):
                row=db.execute('SELECT payload FROM settings WHERE key=?',(key,)).fetchone();return json.loads(row[0]) if row else default
            if setting('launch_source_revision',None)=='public-forum-v1':return
            if setting('observation',{}).get('status')=='running':return
            sources=setting('sources',[]);health=setting('source_health',{});presets={source['id']:source for source in defaults()};changed=[]
            for index,source in enumerate(sources):
                if source['id']=='launch-announcements' and source['url']==old_url and source['kind']=='launch_rss':
                    prior=health.get(source['id'],{})
                    sources[index]=source|{key:presets[source['id']][key] for key in ('url','kind','note')}
                    health[source['id']]={'status':'not_checked','next_check_epoch':0,'previous_endpoint':{'url':old_url,'kind':'launch_rss',
                        'status':prior.get('status'),'error':prior.get('error'),'failures':prior.get('failures'),'last_checked':prior.get('last_checked')},
                        'migration_note':'原RSS/XML已被站方停用，改读同站公开公告列表；旧故障记录保留。'}
                    changed.append(source['id'])
            if 'launch-token-announcements' not in {source['id'] for source in sources}:
                sources.append(presets['launch-token-announcements']);changed.append('launch-token-announcements')
            for key,value in {'sources':sources,'source_health':health,'launch_source_revision':'public-forum-v1'}.items():
                db.execute('INSERT INTO settings VALUES (?,?) ON CONFLICT(key) DO UPDATE SET payload=excluded.payload',(key,_json(value)))
            self.store._event(db,'discovery_sources_updated',{'changed':changed,'old_observation_preserved':True,'reason':'Public forum replaces disabled XML; existing Windows proxy is respected.'})

    def observe(self,candidate_id,signal,source_id='agent',db=None):
        signal=validate_signal(signal)
        if not signal:return None
        candidate=self.store.get_candidate(candidate_id)
        if not candidate:raise ValueError('Unknown launch candidate')
        ident='launch-'+hashlib.sha256(candidate['identity_key'].encode()).hexdigest()[:24]
        with (nullcontext(db) if db is not None else self.store._connection(write=True)) as db:
            row=db.execute('SELECT payload FROM launch_watch WHERE id=?',(ident,)).fetchone()
            old=json.loads(row[0]) if row else None
            start=timestamp(signal['starts_at'])
            if not old and (not signal['announced'] or signal['status'] in ('open','cancelled') or start and start<=dt.datetime.now(dt.timezone.utc)):
                return None
            if not old and signal['network']=='testnet':return None
            if old and old.get('evidence_kind')=='primary' and signal['evidence_kind']=='community':return old
            agent_update=source_id=='agent'
            same_announcement=old is not None and all(old.get(k)==signal.get(k) for k in ('status','starts_at','compute','network','evidence_url'))
            if old and old.get('agent_reviewed') and not agent_update and same_announcement:
                if signal['wallet']=='unknown':signal['wallet']=old['wallet']
                signal['evidence_note']=old['evidence_note']
            value=(old or {'id':ident,'candidate_id':candidate_id,'created_at':now(),'todo_status':'pending'})|signal
            value.update(name=candidate['name'],project_url=candidate['url'],
                source_id=old.get('source_id',source_id) if old and agent_update else source_id,
                agent_reviewed=agent_update or bool(old and old.get('agent_reviewed') and same_announcement),checked_at=now())
            changed=old is None or any(old.get(k)!=value.get(k) for k in signal)
            value['updated_at']=now() if changed else old['updated_at']
            db.execute('INSERT INTO launch_watch VALUES (?,?) ON CONFLICT(id) DO UPDATE SET payload=excluded.payload',(ident,_json(value)))
            if changed:self.store._event(db,'prelaunch_detected' if old is None else 'prelaunch_updated',
                {'id':ident,'candidate_id':candidate_id,'compute':value['compute'],'starts_at':value['starts_at'],'todo_status':value['todo_status'],'execution_authorized':False})
        return value

    def touch(self,source_id):
        with self.store._connection(write=True) as db:
            rows=db.execute('SELECT id,payload FROM launch_watch').fetchall()
            for row in rows:
                value=json.loads(row['payload'])
                if value.get('source_id')==source_id:
                    value['checked_at']=now();db.execute('UPDATE launch_watch SET payload=? WHERE id=?',(_json(value),row['id']))

    def decide(self,ident,status):
        if status not in ('pending','watching','done','dismissed'):raise ValueError('Invalid todo status')
        with self.store._connection(write=True) as db:
            row=db.execute('SELECT payload FROM launch_watch WHERE id=?',(ident,)).fetchone()
            if not row:raise ValueError('Unknown launch task')
            value=json.loads(row[0]);value.update(todo_status=status,decision_at=now())
            db.execute('UPDATE launch_watch SET payload=? WHERE id=?',(_json(value),ident))
            self.store._event(db,'prelaunch_todo_changed',{'id':ident,'todo_status':status})
        return value

    def view(self):
        current=dt.datetime.now(dt.timezone.utc)
        with self.store._connection() as db:items=[json.loads(r[0]) for r in db.execute('SELECT payload FROM launch_watch')]
        rank={'cpu':0,'either':0,'gpu':1,'unknown':2,'asic':3}
        for item in items:
            starts=timestamp(item['starts_at']);age=(current-timestamp(item['checked_at'])).total_seconds()
            phase=item['status']
            if not item['announced']:phase='retracted'
            if phase=='not_started' and starts and starts<=current:phase='due'
            if phase not in ('open','cancelled','retracted') and age>3*86400:phase='needs_recheck'
            item.update(phase=phase,critical=item['todo_status'] in ('pending','watching') and phase not in ('open','cancelled','retracted'),
                rank=rank[item['compute']],starts_in_seconds=round((starts-current).total_seconds()) if starts else None,
                evidence_stale=age>3*86400,execution_authorized=False)
        items.sort(key=lambda x:(x['todo_status'] not in ('pending','watching'),x['rank'],x['compute']=='either',x['starts_at'] or '9999',x['created_at']))
        return {'policy':POLICY,'items':items,'pending_count':sum(x['todo_status']=='pending' for x in items),
            'important_count':sum(x['critical'] for x in items),'server_at':now()}
