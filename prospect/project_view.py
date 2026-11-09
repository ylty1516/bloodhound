"""Plain project/device summaries. Hints never become verified execution rights."""
import re

PRIORITIES=('cpu','gpu','either','none','unknown')
LABELS={'cpu':'CPU 优先','gpu':'GPU 优先','either':'CPU / GPU 均可','none':'网页 / 轻量任务','unknown':'设备待确认'}


def validate_compute(value,urls):
    if value is None:return
    if not isinstance(value,dict) or set(value)!={'priority','reason','sources'}:raise ValueError('Invalid compute profile')
    if value['priority'] not in PRIORITIES or not isinstance(value['reason'],str) or not 1<=len(value['reason'])<=600:raise ValueError('Invalid compute conclusion')
    if not isinstance(value['sources'],list) or len(value['sources'])>4 or any(not isinstance(u,str) or u not in urls for u in value['sources']):raise ValueError('Compute conclusion requires declared evidence')
    if value['priority']!='unknown' and not value['sources']:raise ValueError('CPU/GPU priority needs cited evidence')


def compute_profile(candidate,report=None,plan=None):
    # This describes the route we actually implement, not an earnings ranking.
    drivers=(plan or {}).get('execution_drivers',[])
    if any(d in ('opacra-testnet-cpu','opacra-testnet-node') for d in drivers):
        source=(plan.get('recipe') or {}).get('artifact',{}).get('url')
        return {'priority':'cpu','label':'CPU 优先','basis':'execution_route','reason':'当前接入的是 CPU 测试网路线，不使用 GPU。','sources':[source] if source else []}
    value=(report or {}).get('compute_profile') or (plan or {}).get('compute_profile')
    if value:
        declared={s.get('url') for s in ((report or {}).get('sources') or (plan or {}).get('sources') or []) if isinstance(s,dict)}
        try:validate_compute(value,declared)
        except (ValueError,TypeError):value=None
        if value:return value|{'label':LABELS[value['priority']],'basis':'agent_report'}
    summary=candidate.get('summary','')
    cpu=bool(re.search(r'\bcpu\b',summary,re.I));gpu=bool(re.search(r'\bgpu\b|\bcuda\b',summary,re.I))
    hint='either' if cpu and gpu else 'cpu' if cpu else 'gpu' if gpu else 'unknown'
    label={'cpu':'CPU 方向 · 待核实','gpu':'GPU 方向 · 待核实','either':'CPU / GPU · 待核实','unknown':'设备待确认'}[hint]
    return {'priority':hint,'label':label,'basis':'discovery_hint' if hint!='unknown' else 'unknown',
            'reason':'仅项目简介提到相关设备，尚未由 Agent 核验。' if hint!='unknown' else '现有资料不足以判断 CPU 或 GPU 优先，不根据你的显卡配置猜测。','sources':[]}


def launch_summary(candidate,plan,readiness):
    """Explain who can fix a blocker, instead of asking the novice to decode it."""
    recommendation=(plan or {}).get('recommendation') or {}
    if recommendation.get('status') in ('security_concern','unavailable'):
        return {'status':'unsafe' if recommendation['status']=='security_concern' else 'closed','label':'发现安全问题' if recommendation['status']=='security_concern' else '参与已关闭',
                'can_configure':False,'owner':'agent','reason':recommendation.get('reason') or '现有检查不支持开始运行。','next_step':'先查看原因，暂不启动这条路线。','plan_id':plan['id'],'blockers':[]}
    if not plan or not plan.get('execution_drivers'):
        return {'status':'not_integrated','label':'尚未接入运行','can_configure':False,'owner':'software',
                'reason':'这个项目目前只收集到了资料，软件还没有接好它的安装、启动和结果验证。',
                'next_step':'先看已接入的路线；重复检查资料不会自动补上运行功能。','plan_id':(plan or {}).get('id'),'blockers':[]}
    readiness=readiness or {};blocks=readiness.get('blockers',[])
    product_block=next((b for b in blocks if b['owner']=='software'),None)
    if product_block:
        return {'status':'needs_software','label':'运行方式待更新','can_configure':False,'owner':'software','reason':'这条路线的运行程序或系统支持还需要我们更新。',
                'next_step':'这部分由软件适配处理，不需要你研究链上参数。','plan_id':plan['id'],'blockers':blocks}
    unsafe=(plan.get('recommendation') or {}).get('status')=='security_concern'
    ready=readiness.get('can_configure',False)
    return {'status':'ready' if ready else 'unsafe' if unsafe else 'preparing','label':'可设置运行' if ready else '发现安全问题' if unsafe else '还在准备',
            'can_configure':ready,'owner':None if ready else 'agent',
            'reason':'运行程序和当前版本核验已准备好，确认一次资源范围即可。' if ready else '已接好启动程序，但当前版本的安全检查还没有通过。' if not unsafe else '检查发现尚未解决的安全问题，暂不启动。',
            'next_step':'打开运行设置，核对本次范围后启动。' if ready else '需要 Agent 核对下载程序及对应版本；不需要你填写源码版本或校验码。',
            'plan_id':plan['id'],'blockers':blocks,'testnet':(plan.get('recipe') or {}).get('network')=='testnet'}
