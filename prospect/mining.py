"""One reviewed economic mining route, with evidence-based admission and payout accounting.

Discovery and accounting use fixed public endpoints and read-only wallet commands.
An HTTP caller cannot provide a command, endpoint, token contract, or payout address.
"""
from decimal import Decimal, InvalidOperation
import hashlib
import datetime as dt
import json
import os
from pathlib import Path
import re
import secrets
import socket
import ssl
import threading
import time
import urllib.parse
import urllib.request
import zipfile

from .binance_wallet import receive_address, usdt_quote, USDT_BSC,WalletConnection
from .domain import now
from .vm_mining import DRIVER as VM_DRIVER,LINUX_URL,LINUX_SHA,LINUX_EXE_SHA,BASE_SHA,prepared as vm_prepared

DRIVER = 'unmineable-usdt-bsc-cpu'
CANDIDATE_ID = hashlib.sha256(DRIVER.encode()).hexdigest()[:24]
URL = 'https://unmineable.com/coins/USDT'
MINER_URL = 'https://github.com/xmrig/xmrig/releases/download/v6.26.0/xmrig-6.26.0-windows-x64.zip'
MINER_SHA = 'bba8097cb37d9b458a1cb1137876b27cde6740d17fe4ccbc086ba07d87d9e147'
EXE_SHA = '6fa80698d7268f6e88aa88c06fb27ee99e1bcee747c2e76911e6206a5b1aeeb3'
POOL = 'rx.unmineable.com:443'
META = 'https://api.unmineable.dev/v1/meta/coin/USDT'
PUBLIC_API = 'https://api.unmineable.com'
FRESH_SECONDS = 1800
REVIEW = Path(__file__).resolve().parents[1] / 'reviews/unmineable-usdt-bsc.json'


class _Redirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        allowed = {'api.unmineable.com', 'api.unmineable.dev', 'github.com', 'release-assets.githubusercontent.com'}
        url = urllib.parse.urlsplit(newurl)
        if url.scheme != 'https' or url.hostname not in allowed or url.username or url.password:
            raise ValueError('请求跳转离开已核验的官方服务')
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def opener():
    proxies = urllib.request.getproxies_registry() if os.name == 'nt' else urllib.request.getproxies()
    return urllib.request.build_opener(urllib.request.ProxyHandler(proxies), _Redirect())


def public_json(path, body=None):
    # Call sites use constants plus validated address/UUID; never accepts UI URLs.
    url = path if path == META else PUBLIC_API + path
    headers = {'User-Agent': 'Prospect/0.1 public mining integration', 'Accept': 'application/json'}
    if body is not None: headers['Content-Type'] = 'application/json'
    request = urllib.request.Request(url, data=json.dumps(body).encode() if body is not None else None, headers=headers)
    with opener().open(request, timeout=12) as response: raw = response.read(500001)
    if len(raw) > 500000: raise ValueError('矿池响应超过限额')
    data = json.loads(raw)
    if data.get('success') is not True: raise ValueError('矿池：' + str(data.get('msg', '请求未成功'))[:300])
    return data.get('data')


def amount(value):
    try:
        result = Decimal(str(value))
        if not result.is_finite() or result < 0: raise ValueError()
        return result
    except (InvalidOperation, ValueError): raise ValueError('矿池返回无效金额') from None


def live_market():
    """Official market-data-only API: no API key, account or trade permission."""
    base='https://data-api.binance.vision/api/v3/'
    def read(path):
        request=urllib.request.Request(base+path,headers={'User-Agent':'Prospect/0.1 market verification'})
        with opener().open(request,timeout=12) as response:raw=response.read(200001)
        if len(raw)>200000:raise ValueError('市场数据超过限额')
        return json.loads(raw)
    info=read('exchangeInfo?symbol=BNBUSDT')
    symbol=next((s for s in info.get('symbols',[]) if s.get('symbol')=='BNBUSDT'),{})
    if symbol.get('status')!='TRADING' or symbol.get('quoteAsset')!='USDT' or symbol.get('isSpotTradingAllowed') is not True:
        raise ValueError('USDT 的现货交易通道当前未开放')
    ticker=read('ticker/24hr?symbol=BNBUSDT')
    if ticker.get('symbol')!='BNBUSDT' or amount(ticker.get('lastPrice'))<=0 or amount(ticker.get('quoteVolume'))<=0 or int(ticker.get('count',0))<=0:
        raise ValueError('未取得 USDT 的有效成交与价格证据')
    if abs(time.time()-int(ticker.get('closeTime',0))/1000)>600:raise ValueError('现货市场数据已经过期')
    return {'symbol':'BNBUSDT','status':'TRADING','price_usdt_per_bnb':str(amount(ticker['lastPrice'])),
            'volume_usdt_24h':str(amount(ticker['quoteVolume'])),'trades_24h':int(ticker['count']),
            'source':base+'ticker/24hr?symbol=BNBUSDT','checked_at':now(),'trade_executed':False}


def pool_account(address):
    if not re.fullmatch(r'0x[0-9a-fA-F]{40}', address): raise ValueError('收款地址无效')
    data = public_json('/v5/address/' + address + '?coin=USDT')
    if data.get('network') != 'BSC' or str(data.get('address', '')).lower() != address.lower():
        raise ValueError('矿池结算网络或地址与币安 BSC 钱包不一致，已停止')
    if data.get('enabled') is not True or data.get('delisted_chain') or any((data.get('err_flags') or {}).values()):
        raise ValueError('矿池收款状态异常，未开始挖矿')
    ident = data.get('uuid', '')
    if not re.fullmatch(r'[a-fA-F0-9-]{36}', ident): raise ValueError('矿池账户标识无效')
    threshold = amount(data.get('payment_threshold'))
    if threshold <= 0: raise ValueError('矿池未返回有效付款门槛')
    # In particular do not persist mining_key, referral codes or a raw response.
    return {'uuid': ident, 'network': 'BSC', 'address': address, 'balance': str(amount(data.get('balance'))),
            'threshold': str(threshold), 'auto_pay': data.get('auto') is True,
            'mining_fee': str(data.get('mining_fee', 'unknown')), 'checked_at': now()}


def review():
    data = json.loads(REVIEW.read_text('utf-8'))
    if data.get('artifact_sha256') != MINER_SHA or data.get('executable_sha256') != EXE_SHA or data.get('status') != 'scoped_review_pass':
        raise ValueError('此版本尚未完成限定运行范围的程序审阅')
    return data


def pool_socket(transport=None):
    proxy=(transport or {}).get('proxy')
    if proxy and not re.fullmatch(r'127\.0\.0\.1:[0-9]{1,5}',proxy):raise ValueError('只支持已核验的本机系统代理')
    sock=socket.create_connection(('127.0.0.1',int(proxy.rsplit(':',1)[1])) if proxy else ('rx.unmineable.com',443),timeout=10)
    try:
        if proxy:
            sock.sendall(b'\x05\x01\x00')
            def take(count):
                data=b''
                while len(data)<count:
                    part=sock.recv(count-len(data))
                    if not part:raise ValueError('系统代理提前断开')
                    data+=part
                return data
            if take(2)!=b'\x05\x00':raise ValueError('本机代理不支持 SOCKS5')
            host=b'rx.unmineable.com';sock.sendall(b'\x05\x01\x00\x03'+bytes([len(host)])+host+b'\x01\xbb')
            header=take(4)
            if header[1]!=0:raise ValueError('系统代理无法连接矿池')
            size={1:4,4:16}.get(header[3])
            if header[3]==3:size=take(1)[0]
            if size is None:raise ValueError('系统代理返回异常')
            take(size+2)
        return sock
    except Exception:sock.close();raise


def pool_transport():
    """Probe only the fixed Stratum endpoint. No wallet credentials are sent.

    unMineable publishes an SSL endpoint using a self-signed certificate. Pin its
    first observed certificate for this reviewed run; do not weaken HTTPS or OS
    certificate settings. This is TOFU, not CA-authenticated pool identity.
    """
    proxy = None
    if os.name == 'nt':
        configured = urllib.request.getproxies_registry().get('https', '')
        parsed = urllib.parse.urlsplit(configured if '://' in configured else 'http://' + configured)
        if parsed.hostname in ('127.0.0.1', 'localhost') and parsed.port and not parsed.username:
            proxy = '127.0.0.1:' + str(parsed.port)
    sock = pool_socket({'proxy':proxy})
    try:
        context=ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
        context.check_hostname=False;context.verify_mode=ssl.CERT_NONE
        with context.wrap_socket(sock,server_hostname='rx.unmineable.com') as stream:
            return {'proxy':proxy,'certificate_sha256':hashlib.sha256(stream.getpeercert(binary_form=True)).hexdigest(),
                    'authentication':'first_use_pin','ca_authenticated':False}
    finally:sock.close()


class Mining:
    def __init__(self, store, directory):
        self.store, self.directory = store, Path(directory)
        self.lock = threading.RLock()
        self.thread = None
        self.closing = False
        self.wallet_connection=WalletConnection(self._wallet_connected)
        self.wallet_revision=0;self.pending_wallet_refresh=False

    def _wallet_connected(self):
        with self.lock:
            self.wallet_revision+=1
            self.store.set_setting('binance_receive_proof',None)
            self.store.set_setting('binance_usdt_quote_proof',None)
            self._save(status='needs_refresh',verified_epoch=0,needs_wallet_login=False,message='钱包已连接，重新核对本次收款地址')
            if self.thread and self.thread.is_alive():self.pending_wallet_refresh=True
            else:self.refresh()

    def view(self):
        data = self.store.get_setting('economic_mining', {})
        data={k:v for k,v in data.items() if k!='error'}|{'error_message':data.get('error')}
        if data.get('status') == 'checking' and not (self.thread and self.thread.is_alive()):
            data = data | {'status': 'needs_refresh', 'message': '上次准备被中断，点击重新准备即可'}
        stale = time.time() - data.get('verified_epoch', 0) > FRESH_SECONDS
        evidence_ready=data.get('status') in ('ready','checking') and not stale
        environment_ready=vm_prepared(self.directory)
        if evidence_ready and not environment_ready:data=data|{'message':'收款与市场已核对；正在准备独立虚拟机运行环境'}
        return {'route': {'id': VM_DRIVER, 'name': '隔离 CPU 挖矿 → USDT → 币安 Agent 钱包', 'url': URL,
                          'compute': 'CPU 优先 · 独立虚拟机 · 2 线程', 'network': 'BSC', 'chain_id': '56', 'token': 'USDT',
                          'contract': USDT_BSC, 'algorithm': 'RandomX', 'pool': POOL,
                          'conversion': '矿池将 PoW 算力收益换算成 USDT；USDT 本身不采用 PoW 挖矿',
                          'miner_version': '6.26.0', 'miner_sha256': LINUX_SHA,'execution_backend':'isolated_vm'},
                'policy': {'id': 'binance-wallet-tradable-v1', 'requires_wallet_network': True, 'requires_live_market': True,
                           'requires_verified_wallet_quote':True,'wallet_login_required_for_receiving':False,
                           'unknowns_excluded': True, 'profit_guaranteed': False},
                **data,'wallet_login':self.wallet_connection.view(), 'fresh': not stale,'evidence_ready':evidence_ready,'environment_ready':environment_ready,
                'ready':evidence_ready and environment_ready}

    def refresh(self):
        with self.lock:
            if self.wallet_connection.view()['status'] in ('starting','waiting'):return self.view()
            if self.thread and self.thread.is_alive(): return self.view()
            if self.closing: raise ValueError('服务正在停止')
            self._save(status='checking', stage='wallet', message='正在读取币安钱包连接和 BSC 收款地址',attempt_epoch=time.time(),needs_wallet_login=False)
            self.thread = threading.Thread(target=self._refresh, daemon=True)
            self.thread.start()
            return self.view()

    def _save(self, **fields):
        with self.lock:
            self.store.set_setting('economic_mining', self.store.get_setting('economic_mining', {}) | fields | {'updated_at': now()})

    def _refresh(self):
        revision=self.wallet_revision
        try:
            proof=self.store.get_setting('binance_receive_proof')
            wallet_quote=self.store.get_setting('binance_usdt_quote_proof')
            reusable=False
            if proof and wallet_quote:
                age=(dt.datetime.now(dt.timezone.utc)-dt.datetime.fromisoformat(wallet_quote.get('checked_at',''))).total_seconds()
                reusable=0<=age<86400 and proof.get('receive_verified') is True and re.fullmatch(r'0x[0-9a-fA-F]{40}',proof.get('address','')) is not None and proof.get('chain_id')=='56' and wallet_quote.get('from_contract','').lower()==USDT_BSC.lower()
            if reusable:
                # Receiving does not use the CLI's signing session. Do not keep
                # querying an expired login merely to receive mining rewards.
                wallet=proof
            else:
                wallet=receive_address()|{'receive_verified':True,'verified_at':now()}
                wallet_quote=usdt_quote()|{'checked_at':now()}
                self.store.set_setting('binance_receive_proof',wallet)
                self.store.set_setting('binance_usdt_quote_proof',wallet_quote)
            self._save(wallet=wallet, stage='market', message='核对 USDT/BSC 的真实兑换报价')
            market=live_market()
            self._save(stage='pool', message='核对矿池的结算网络、门槛和公开余额')
            meta = public_json(META)
            chain = next((c for c in meta.get('chains', []) if c.get('network') == 'BSC'), {})
            if meta.get('symbol') != 'USDT' or meta.get('delisted') or not meta.get('payment_enabled') or not chain.get('enabled') or chain.get('delisted'):
                raise ValueError('USDT/BSC 的矿池结算通道当前不可用')
            account = pool_account(wallet['address'])
            scoped = review()
            self._save(stage='connection',message='检查矿池连接并固定本次证书指纹')
            transport=pool_transport()
            with self.lock:
                if revision!=self.wallet_revision:return
                self._save(status='ready', stage='ready', message='钱包、交易报价和矿池结算通道已核对，可以确认一次运行',
                           wallet=wallet, market=market,wallet_quote=wallet_quote,pool=account,transport=transport,
                           review={'status': scoped['status'], 'limitations': scoped['limitations']},
                           verified_epoch=time.time(), error=None,needs_wallet_login=False)
                self.store.upsert_candidate(self.candidate())
        except Exception as exc:
            needs_login=any(t in str(exc) for t in ('尚未登录','NOT_LOGGED_IN','SESSION_EXPIRED'))
            self._save(status='needs_attention', stage='attention', message=str(exc)[:500], error=str(exc)[:500],needs_wallet_login=needs_login, verified_epoch=0)
        finally:
            with self.lock:
                if self.pending_wallet_refresh and not self.closing:
                    self.pending_wallet_refresh=False;self.thread=None;self.refresh()

    def material(self, auto_payout=True, isolated=False):
        state = self.view()
        blockers = []
        if not state['evidence_ready']: blockers.append(state.get('message') or '请先准备币安钱包与真实挖矿路线')
        if isolated and not state['environment_ready']:blockers.append('独立虚拟机尚未完成启动与连接验证')
        if not state['fresh'] and state.get('verified_epoch'): blockers.append('钱包与交易通道核验已过期，点击重新准备')
        try: scoped = review()
        except (ValueError, OSError) as exc: blockers.append(str(exc)); scoped = {}
        wallet, pool = state.get('wallet', {}), state.get('pool', {})
        if isolated:
            scoped=json.loads((REVIEW.parent/'unmineable-usdt-bsc-vm.json').read_text('utf-8'))
            if scoped.get('linux_archive_sha256')!=LINUX_SHA or scoped.get('linux_executable_sha256')!=LINUX_EXE_SHA or scoped.get('base_sha256')!=BASE_SHA or scoped.get('status')!='scoped_review_pass':blockers.append('隔离环境固定版本审阅不匹配')
        return {'driver': {'id': VM_DRIVER if isolated else DRIVER, 'name': '隔离 CPU 挖矿 · USDT/BSC' if isolated else 'CPU 挖矿 · USDT/BSC', 'network': 'mainnet', 'version': '6.26.0', 'category': 'pow'},
                'binding': {'plan_id': None, 'candidate_id': CANDIDATE_ID, 'candidate_name': state['route']['name'],
                            'fingerprint': hashlib.sha256(json.dumps({'wallet': wallet.get('address'), 'pool_uuid': pool.get('uuid'),
                                  'threshold': pool.get('threshold'), 'transport':state.get('transport'),'review': scoped, 'sha': MINER_SHA}, sort_keys=True).encode()).hexdigest()},
                'inputs': {'public_address': wallet.get('address', ''), 'pool_uuid': pool.get('uuid', ''),
                           'auto_payout':auto_payout,'transport':state.get('transport')},
                'blockers': blockers, 'artifact': {'url': LINUX_URL if isolated else MINER_URL, 'sha256': LINUX_SHA if isolated else MINER_SHA},
                'notes': ['矿池平台费约 1%；XMRig 开发者捐赠 1%。电费未计入，不保证盈利。',
                          '真实算力接受、矿池记账和钱包到账分别核验；达到付款门槛前不会声称到账。',
                          '矿池 SSL 使用自签名证书，本次固定首次连接的指纹；这不能替代独立的矿池身份认证。'],
                'scope': ('在独立 Ubuntu 虚拟机内运行，2个虚拟CPU、矿工2线程，不共享主机目录或剪贴板，网络只经固定矿池通道。' if isolated else '仅本次 CPU 挖矿；2 线程，不使用 GPU。')+f"收款为币安 Agent 钱包的 BSC 地址 {wallet.get('address', '待连接')}，"
                         f"USDT 合约 {USDT_BSC}。矿池门槛 {pool.get('threshold', '待核对')} USDT。"
                         + ('启用矿池达到门槛后的自动结算。' if auto_payout else '保留现有矿池结算设置。')
                         + '不开启钱包转账、交易或签名权限；不创建每日任务。',
                'containment': '整组进程受 Windows CPU/内存与退出保护限制，时长包括环境启动；没有主机共享目录，虚拟机只允许固定矿池转发。不会修改主机防护设置。' if isolated else 'Windows 限制 CPU 和进程组内存；限时停止。不开管理员权限、不安装驱动、不修改杀毒设置。资源限制不是安全沙箱。'}

    def collect(self, address):
        return pool_account(address)

    def payments(self, ident):
        if not re.fullmatch(r'[a-fA-F0-9-]{36}',ident):raise ValueError('矿池账户标识无效')
        data=public_json('/v5/account/'+ident+'/payments')
        if data.get('coin')!='USDT' or not isinstance(data.get('list'),list):raise ValueError('矿池付款记录格式改变，需要核对')
        return [{k:item.get(k) for k in ('id','status','tx','network','amount','timestamp')} for item in data['list'][:30]]

    def reconcile(self, job):
        account=self.collect(job['inputs']['public_address'])
        if account['uuid']!=job['inputs']['pool_uuid']:raise ValueError('收款账户与本轮记录不一致')
        delta=amount(account['balance'])-amount(job['pool_before']['balance'])
        payments=self.payments(account['uuid']);verified=[];errors=[]
        baseline={str(x) for x in job.get('payment_baseline',[])}
        for item in payments:
            tx=item.get('tx')
            if str(item.get('id')) in baseline or item.get('status')!='success' or item.get('network')!='BSC' or not isinstance(tx,str) or not re.fullmatch(r'0x[0-9a-fA-F]{64}',tx):continue
            try:
                chain=_rpc('eth_chainId',[])
                if chain!='0x38':raise ValueError('链上查询服务返回的不是 BSC')
                receipt=_rpc('eth_getTransactionReceipt',[tx])
                if not receipt:continue
                block=_rpc('eth_getBlockByNumber',[receipt['blockNumber'],False])
                latest=int(_rpc('eth_blockNumber',[]),16)
                decimals=int(_rpc('eth_call',[{'to':USDT_BSC,'data':'0x313ce567'},'latest']),16)
                proof=verify_payment(item,receipt,block,latest,decimals,job['inputs']['public_address'],job.get('started_at',job['created_at']))
                if proof:verified.append(proof)
            except (OSError,ValueError,KeyError,TypeError) as exc:errors.append(str(exc)[:200])
        credited=delta>0 or job.get('pool_credit_verified',False)
        delivery={'status':'wallet_received' if verified else 'pool_credited' if credited else 'awaiting_pool_credit' if job.get('contribution_verified') else 'no_accepted_shares',
                  'balance':account['balance'],'threshold':account['threshold'],'unit':'USDT','network':'BSC',
                  'onchain_verified':bool(verified),'payments':verified,'checked_at':now(),
                  'attribution':'pool_account','errors':errors}
        return {'pool_after':account,'pool_credit_delta':str(delta),'pool_credit_verified':bool(credited),
                'delivery':delivery,'rewards_verified':bool(verified)}

    def candidate(self):
        state=self.view()
        if not state['evidence_ready']:return None
        from .domain import normalize_candidate
        value=normalize_candidate({'name':'unMineable · CPU → USDT / BSC','category':'pow','url':URL,'identity_key':DRIVER,
            'summary':'提供 RandomX CPU 算力，由矿池换算为可交易的 USDT，结算到币安 Agent 钱包的 BSC 地址。不是挖 USDT 公链，也不保证扣除电费后盈利。',
            'market':{'token_issued':'yes','mainnet':'yes','transferable':'yes','cex_spot':'yes'},
            'evidence':[{'url':URL,'kind':'official','note':'官方支持 USDT/BSC 算力换算及结算。',
                         'checked_at':state['updated_at'],'claims':{'token_issued':'yes','mainnet':'yes','transferable':'yes'}},
                        {'url':'https://data-api.binance.vision/api/v3/ticker/24hr?symbol=BNBUSDT','kind':'primary',
                         'note':'USDT 现货交易对处于 TRADING 且有实际成交。本机还保存了此前币安 Agent 钱包对同一 USDT/BSC 合约返回的兑换报价。',
                         'checked_at':state['updated_at'],'claims':{'cex_spot':'yes'}}],
            'requirements':{'os':['windows'],'min_ram_gb':3,'min_disk_gb':.1,'min_vram_gb':0,'skill_level':'beginner'},
            'reward_unit':'USDT / BSC','participation':'open','checked_at':state['updated_at']})
        value.update(economic_eligibility={'eligible':True,'policy':'binance-wallet-tradable-v1','reason':'BSC 钱包网络、矿池结算与实时兑换报价均已核对'},
            compute_profile={'priority':'cpu','label':'CPU 优先','basis':'execution_route','reason':'已接入2线程 CPU 路线，不启用GPU。','sources':[URL]},
            launch={'status':'ready' if state['ready'] else 'preparing','label':'可以运行' if state['ready'] else '隔离环境准备中','can_configure':state['ready'],'owner':None if state['ready'] else 'software','reason':'收款和运行路线已准备好。' if state['ready'] else state['message'],
                    'next_step':'确认一次15分钟运行','plan_id':None,'blockers':[]},mining_route=True)
        return value

    def enable_payout(self, address, ident):
        account=pool_account(address)
        if account['uuid']!=ident:raise ValueError('矿池账户发生变化')
        if not account['auto_pay']:
            public_json('/v1/address/'+ident+'/setting/auto_pay',{'setting':True})
            account=pool_account(address)
            if not account['auto_pay']:raise ValueError('矿池未确认自动结算已开启，未开始挖矿')
        return account

    def shutdown(self):
        self.wallet_connection.shutdown()
        self.closing = True
        if self.thread: self.thread.join(2)


def prepare_spec(folder, inputs, log, cancelled, artifact_cache, free_port):
    address = inputs.get('public_address', '')
    account = pool_account(address)
    if account['uuid'] != inputs.get('pool_uuid'): raise ValueError('矿池账户发生变化，请重新准备')
    review()
    transport=pool_transport()
    if transport!=inputs.get('transport'):raise ValueError('矿池连接或证书指纹发生变化，请重新准备并确认')
    cache = Path(artifact_cache)
    cache.mkdir(parents=True, exist_ok=True)
    package = cache / 'xmrig-6.26.0-windows-x64.zip'
    valid = package.is_file() and hashlib.sha256(package.read_bytes()).hexdigest() == MINER_SHA
    if not valid:
        temporary = package.with_suffix('.download')
        size, digest, started = 0, hashlib.sha256(), time.monotonic()
        try:
            with opener().open(urllib.request.Request(MINER_URL, headers={'User-Agent':'Prospect/0.1'}), timeout=15) as response, temporary.open('wb') as target:
                while True:
                    if cancelled.is_set(): raise InterruptedError()
                    if time.monotonic()-started>180: raise ValueError('矿工下载超时')
                    part=response.read(65536)
                    if not part: break
                    size+=len(part)
                    if size>16*1024*1024: raise ValueError('矿工发布包超过限额')
                    target.write(part);digest.update(part)
            if digest.hexdigest()!=MINER_SHA: raise ValueError('矿工发布包 SHA-256 与官方校验值不符，未执行')
            os.replace(temporary,package)
        finally:
            temporary.unlink(missing_ok=True)
    log('XMRig 6.26.0 官方发布包 SHA-256 已核对；只提取矿工，不提取驱动和批处理。')
    executable=folder/'xmrig.exe'
    with zipfile.ZipFile(package) as archive:
        info=archive.getinfo('xmrig-6.26.0/xmrig.exe')
        if info.file_size>12*1024*1024: raise ValueError('矿工文件超过限额')
        raw=archive.read(info)
    if hashlib.sha256(raw).hexdigest()!=EXE_SHA:raise ValueError('矿工程序校验失败')
    executable.write_bytes(raw)
    api_port, token=free_port(),secrets.token_hex(24)
    worker='prospect'+folder.name[-10:]
    config={'autosave':False,'background':False,'colors':False,'title':False,'watch':False,'pause-on-battery':True,
            'http':{'enabled':True,'host':'127.0.0.1','port':api_port,'access-token':token,'restricted':True},
            'randomx':{'init':1,'mode':'light','1gb-pages':False,'rdmsr':False,'wrmsr':False,'numa':False},
            'cpu':{'enabled':True,'huge-pages':False,'huge-pages-jit':False,'priority':0,'yield':True,'rx':[-1,-1]},
            'opencl':{'enabled':False},'cuda':{'enabled':False},'donate-level':1,'donate-over-proxy':0,
            'pools':[{'algo':'rx/0','url':POOL,'user':'USDT:'+address+'.'+worker,'pass':'x','keepalive':True,'tls':True,
                      'tls-fingerprint':transport['certificate_sha256'],'socks5':transport['proxy']}],
            'print-time':10,'health-print-time':30,'retries':3,'retry-pause':5}
    path=folder/'miner.json';path.write_text(json.dumps(config),'utf-8')
    log('使用 RandomX 低内存模式与 2 条 CPU 线程；保留全部进程、权限和退出限制。')
    return {'driver':DRIVER,'argv':[str(executable),'--config='+str(path)],'executable_sha256':EXE_SHA,
            'rpc_port':api_port,'api_token':token,'worker':worker,'pool_before':account}


def miner_probe(spec):
    try:
        request=urllib.request.Request(f"http://127.0.0.1:{spec['rpc_port']}/2/summary",headers={'Authorization':'Bearer '+spec['api_token']})
        with urllib.request.build_opener(urllib.request.ProxyHandler({})).open(request,timeout=.8) as response:raw=response.read(65537)
        if len(raw)>65536:return None
        data=json.loads(raw);results=data.get('results') or {};connection=data.get('connection') or {}
        good=results.get('shares_good',connection.get('accepted',0));total=results.get('shares_total',0)
        if type(good) is not int or good<0 or good>10**7:return None
        return {'kind':'miner_pool_acceptance','accepted_shares':good,'total_shares':total,
                'hashrate_hs':(data.get('hashrate') or {}).get('total',[None])[0],
                'pool':connection.get('pool'),'algorithm':data.get('algo'),'worker':spec['worker'],'checked_at':now()}
    except (ValueError,OSError,TypeError,IndexError):return None


def _rpc(method, params):
    allowed={'eth_chainId','eth_getTransactionReceipt','eth_getBlockByNumber','eth_blockNumber','eth_call'}
    if method not in allowed:raise ValueError('只允许链上收款核验')
    request=urllib.request.Request('https://bsc-dataseed.binance.org/',
        data=json.dumps({'jsonrpc':'2.0','id':1,'method':method,'params':params}).encode(),
        headers={'Content-Type':'application/json','User-Agent':'Prospect/0.1 receipt verification'})
    with opener().open(request,timeout=10) as response:raw=response.read(200001)
    if len(raw)>200000:raise ValueError('链上响应超过限额')
    data=json.loads(raw)
    if 'error' in data:raise ValueError('链上查询暂时不可用；尚未核验到账')
    return data['result']


def verify_payment(payment, receipt, block, latest_block, decimals, address, started_at):
    """Pool status alone and wallet balance changes never establish delivery."""
    import datetime as dt
    if receipt.get('status')!='0x1' or receipt.get('transactionHash','').lower()!=payment['tx'].lower():return None
    number=int(receipt['blockNumber'],16)
    if block.get('hash','').lower()!=receipt.get('blockHash','').lower() or latest_block-number+1<12:return None
    if int(block['timestamp'],16)<dt.datetime.fromisoformat(started_at).timestamp():return None
    if not 0<=decimals<=36:return None
    topic='0xddf252ad1be2c89b69c2b068fc378daa952ba7f163c4a11628f55a4df523b3ef'
    transferred=0
    for item in receipt.get('logs',[]):
        topics=item.get('topics') or []
        if item.get('removed') or item.get('address','').lower()!=USDT_BSC.lower() or len(topics)!=3 or topics[0].lower()!=topic:continue
        if topics[2].lower()!='0x'+'0'*24+address[2:].lower():continue
        if not re.fullmatch(r'0x[0-9a-fA-F]{64}',item.get('data','')):continue
        transferred+=int(item['data'],16)
    received=Decimal(transferred)/(Decimal(10)**decimals)
    if received<=0 or received!=amount(payment['amount']):return None
    return {'tx_hash':payment['tx'],'amount':str(received),'unit':'USDT','network':'BSC','contract':USDT_BSC,
            'recipient':address,'confirmations':latest_block-number+1,'block':number,'verified_at':now(),
            'explorer':'https://bscscan.com/tx/'+payment['tx']}
