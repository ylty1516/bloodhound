"""Narrow, read-only adapter to the user's official Binance Agentic Wallet CLI.

Never read credential files, import a wallet key, sign, trade, or send funds.
Only selected non-secret response fields leave this module.
"""
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import threading
import time
import urllib.request
import urllib.parse

USDT_BSC = '0x55d398326f99059fF775485246999027B3197955'
BNB_NATIVE = '0xEeeeeEeeeEeEeeEeEeEeeEEEeeeeEeeeeeeeEEeE'


def proxy_environment():
    env = os.environ.copy()
    # Node fetch does not otherwise use the Windows system proxy. Do not change
    # system settings, disable TLS, or send wallet credentials to a new API host.
    if os.name == 'nt':
        proxies = urllib.request.getproxies_registry()
        for scheme in ('http', 'https'):
            if proxies.get(scheme) and not env.get(scheme.upper() + '_PROXY'):
                env[scheme.upper() + '_PROXY'] = proxies[scheme]
    env['NODE_USE_ENV_PROXY'] = '1'
    env['NO_PROXY'] = 'localhost,127.0.0.1,::1'
    # The official CLI has a verbose mode which can print request credentials.
    for key in list(env):
        if key.upper() in {'DEBUG', 'BAW_DEBUG', 'WALLET_DEBUG', 'NODE_DEBUG'}:
            env.pop(key, None)
    return env


def _read(*args):
    allowed = {('wallet', 'status'), ('wallet', 'chains'), ('wallet', 'address'), ('wallet', 'settings')}
    quote = ('market-order', 'quote', '--fromTokenQty', '1.5', '--fromToken', USDT_BSC,
             '--toToken', BNB_NATIVE, '--binanceChainId', '56')
    if tuple(args) not in allowed and tuple(args) != quote:
        raise ValueError('钱包适配器只允许读取连接、网络、地址和 USDT 兑换报价')
    return _invoke(args)


def _invoke(args,timeout=25,on_process=None):
    launcher = shutil.which('baw.cmd' if os.name == 'nt' else 'baw')
    node = shutil.which('node')
    if not launcher or not node: raise ValueError('请先安装币安 Agent 钱包官方 CLI')
    entry = Path(launcher).parent / 'node_modules/@binance/agentic-wallet/dist/index.js'
    if not entry.is_file(): raise ValueError('未找到官方币安 Agent 钱包 CLI 入口')
    process=subprocess.Popen([node,str(entry),*args,'--json'],stdin=subprocess.DEVNULL,stdout=subprocess.PIPE,stderr=subprocess.PIPE,
                             encoding='utf-8',errors='replace',env=proxy_environment(),
                             creationflags=subprocess.CREATE_NO_WINDOW if os.name=='nt' else 0)
    if on_process:on_process(process)
    try:stdout,_=process.communicate(timeout=timeout)
    except subprocess.TimeoutExpired:
        process.kill();process.communicate()
        raise ValueError('币安钱包连接等待超时，请重新连接') from None
    try: body = json.loads(stdout)
    except ValueError: raise ValueError('币安钱包没有返回有效 JSON；未保存原始输出') from None
    if body.get('success') is not True:
        error = body.get('error') or {}
        # Do not propagate arbitrary data/HTTP headers from this third-party CLI.
        name, message = str(error.get('name', 'WALLET_ERROR')), str(error.get('message', ''))
        if re.search(r'sessionid|clientid|bearer|secret|private.?key|token=', message, re.I):
            message = '[已隐藏可能含凭据的错误详情]'
        raise ValueError(f'{name}: {message[:400]}')
    return body.get('data')


class WalletConnection:
    """User-initiated official sign-in only; never signs/sends/trades."""
    def __init__(self,on_connected):
        self.on_connected=on_connected;self.lock=threading.RLock();self.thread=None;self.process=None;self.closing=False
        self.state={'status':'idle','message':'用币安 App 扫码连接，钱包凭据由官方 CLI 管理'}

    def view(self):
        with self.lock:
            result={k:self.state[k] for k in ('status','message','url','pairing_code','expires_at') if k in self.state}
            return {'supported':True,**result}

    def start(self,confirmed=False):
        if confirmed is not True:raise ValueError('请先确认连接币安 Agent 钱包，再打开官方扫码登录')
        with self.lock:
            if self.closing:raise ValueError('服务正在停止')
            if self.thread and self.thread.is_alive():return self.view()
            self.state={'status':'starting','message':'正在打开币安官方扫码登录'}
            self.thread=threading.Thread(target=self._run,daemon=True);self.thread.start()
            return self.view()

    def _run(self):
        def process_started(process):
            with self.lock:
                self.process=process
                if self.closing and process.poll() is None:process.terminate()
        try:
            data=_invoke(('auth','signin'),on_process=process_started)
            if data.get('status')!='ALREADY_CONNECTED':
                url=data.get('urlForWeb','');parsed=urllib.parse.urlsplit(url)
                if parsed.scheme!='https' or parsed.hostname not in ('app.binance.com','web3.binance.com') or parsed.username or parsed.password:
                    raise ValueError('钱包返回的登录地址不是已核对的币安官方域名')
                ident=data.get('qrCodeId','');code=data.get('pairingCode','')
                if not re.fullmatch(r'[0-9a-fA-F-]{36}',ident) or not re.fullmatch(r'[a-zA-Z0-9]{4,16}',code):raise ValueError('币安登录信息格式无效')
                expires=int(data.get('expireAt','0'))
                if not time.time()*1000<expires<time.time()*1000+600000:raise ValueError('币安登录二维码已经过期，请重新连接')
                with self.lock:self.state={'status':'waiting','message':'请用币安 App 扫码，核对配对码后确认登录','url':url,'pairing_code':code,'expires_at':expires}
                verified=_invoke(('auth','verify','--qrCodeId',ident),timeout=315,on_process=process_started)
                if verified.get('status')!='SUCCESS':raise ValueError('币安尚未确认本机登录完成')
            if _read('wallet','status').get('status')!='CONNECTED':raise ValueError('币安 App 已处理请求，但本机尚未连接，请重新扫码')
            with self.lock:self.state={'status':'connected','message':'币安钱包已连接，正在重新核对收款地址与交易通道'}
            self.on_connected()
        except Exception as exc:
            with self.lock:self.state={'status':'error','message':str(exc)[:500]}
        finally:
            with self.lock:self.process=None

    def shutdown(self):
        with self.lock:
            self.closing=True
            if self.process and self.process.poll() is None:self.process.terminate()
        if self.thread:self.thread.join(2)


def receive_address():
    state = _read('wallet', 'status')
    if not isinstance(state, dict) or state.get('status') != 'CONNECTED':
        raise ValueError('币安 Agent 钱包尚未登录；请先用币安 App 确认登录')
    chains = _read('wallet', 'chains')
    if not isinstance(chains, list) or not any(str(c.get('binanceChainId')) == '56' for c in chains):
        raise ValueError('当前币安 Agent 钱包不支持 BSC 网络')
    addresses = _read('wallet', 'address')
    address = next((c.get('address') for c in (addresses or {}).get('addresses', [])
                    if str(c.get('binanceChainId')) == '56'), None)
    if not isinstance(address, str) or not re.fullmatch(r'0x[0-9a-fA-F]{40}', address) or int(address, 16) == 0:
        raise ValueError('币安钱包未返回有效的 BSC 收款地址')
    settings = _read('wallet', 'settings')
    return {'connected': True, 'address': address, 'chain_id': '56', 'network': 'BSC',
            'session_expires_at': settings.get('sessionExpireTime'),
            'supported_chains': [{'id': str(c.get('binanceChainId')), 'name': c.get('name')} for c in chains]}


def usdt_quote():
    data = _read('market-order', 'quote', '--fromTokenQty', '1.5', '--fromToken', USDT_BSC,
                 '--toToken', BNB_NATIVE, '--binanceChainId', '56')
    if not isinstance(data, dict) or data.get('fromCoinSymbol') != 'USDT' or data.get('toCoinSymbol') != 'BNB':
        raise ValueError('没有取得 USDT/BSC 的有效兑换报价')
    from decimal import Decimal, InvalidOperation
    try:
        value = Decimal(str(data.get('toCoinAmount')))
        if not value.is_finite() or value <= 0 or Decimal(str(data.get('fromCoinAmount'))) != Decimal('1.5'): raise ValueError()
    except (ValueError, InvalidOperation): raise ValueError('兑换报价数量无效') from None
    return {'from_symbol': 'USDT', 'from_amount': '1.5', 'from_contract': USDT_BSC,
            'to_symbol': 'BNB', 'to_contract': BNB_NATIVE, 'to_amount': str(value),
            'chain_id': '56', 'source': 'Binance Agentic Wallet · market-order quote', 'trade_executed': False}
