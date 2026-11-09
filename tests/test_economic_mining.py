import copy
import datetime as dt
import io
import json
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import patch

from prospect.binance_wallet import _read, receive_address, usdt_quote, USDT_BSC
from prospect.executions import Executions
from prospect.mining import Mining, DRIVER, MINER_SHA, pool_account, miner_probe, verify_payment
from prospect.store import Store

ADDRESS='0x'+'a'*40
IDENT='11111111-1111-1111-1111-111111111111'
POOL={'uuid':IDENT,'network':'BSC','address':ADDRESS,'balance':'0','threshold':'1.5','auto_pay':False,'mining_fee':'1'}
TRANSPORT={'proxy':None,'certificate_sha256':'a'*64,'authentication':'first_use_pin','ca_authenticated':False}


class EconomicMiningTests(unittest.TestCase):
    def setUp(self):
        self.vm_patch=patch('prospect.mining.vm_prepared',return_value=True);self.vm_patch.start()
        self.temp=tempfile.TemporaryDirectory();self.path=Path(self.temp.name)
        self.store=Store(self.path/'state.db');self.mining=Mining(self.store,self.path)

    def tearDown(self):self.mining.shutdown();self.temp.cleanup();self.vm_patch.stop()

    def ready(self):
        self.mining._save(status='ready',verified_epoch=time.time(),wallet={'address':ADDRESS,'connected':True},pool=POOL,
                          market={'from_symbol':'USDT','to_amount':'0.002'},transport=TRANSPORT)

    def test_unverified_and_stale_routes_never_enter_discovery(self):
        self.assertIsNone(self.mining.candidate());self.assertTrue(self.mining.material()['blockers'])
        self.ready();self.assertTrue(self.mining.candidate()['economic_eligibility']['eligible'])
        self.mining._save(verified_epoch=time.time()-1801)
        self.assertIsNone(self.mining.candidate());self.assertFalse(self.mining.view()['ready'])

    def test_refresh_is_read_only_and_keeps_only_selected_wallet_data(self):
        with patch('prospect.mining.receive_address',return_value={'address':ADDRESS,'connected':True}),\
             patch('prospect.mining.usdt_quote',return_value={'from_symbol':'USDT','to_amount':'0.002'}),\
             patch('prospect.mining.live_market',return_value={'status':'TRADING'}),\
             patch('prospect.mining.public_json',return_value={'symbol':'USDT','payment_enabled':True,'chains':[{'network':'BSC','enabled':True}]}),\
             patch('prospect.mining.pool_account',return_value=POOL),patch('prospect.mining.pool_transport',return_value=TRANSPORT):
            self.mining.refresh();self.mining.thread.join(3)
        self.assertTrue(self.mining.view()['ready']);self.assertEqual(len(self.store.candidates()),1)
        self.assertFalse(self.mining.view()['pool']['auto_pay'])

    def test_metadata_network_disabled_excludes_route(self):
        with patch('prospect.mining.receive_address',return_value={'address':ADDRESS}),\
             patch('prospect.mining.usdt_quote',return_value={}),\
             patch('prospect.mining.live_market',return_value={'status':'TRADING'}),\
             patch('prospect.mining.public_json',return_value={'symbol':'USDT','payment_enabled':True,'chains':[{'network':'BSC','enabled':False}]}):
            self.mining.refresh();self.mining.thread.join(3)
        self.assertFalse(self.mining.view()['ready']);self.assertIsNone(self.mining.candidate())

    def test_verified_receiving_address_does_not_require_active_signing_session(self):
        self.store.set_setting('binance_receive_proof',{'address':ADDRESS,'chain_id':'56','receive_verified':True,'connected':False})
        self.store.set_setting('binance_usdt_quote_proof',{'checked_at':dt.datetime.now(dt.timezone.utc).isoformat(),'from_contract':USDT_BSC})
        with patch('prospect.mining.receive_address') as wallet,patch('prospect.mining.usdt_quote') as quote,\
             patch('prospect.mining.live_market',return_value={'status':'TRADING'}),\
             patch('prospect.mining.public_json',return_value={'symbol':'USDT','payment_enabled':True,'chains':[{'network':'BSC','enabled':True}]}),\
             patch('prospect.mining.pool_account',return_value=POOL),patch('prospect.mining.pool_transport',return_value=TRANSPORT):
            self.mining.refresh();self.mining.thread.join(3)
        wallet.assert_not_called();quote.assert_not_called()
        self.assertTrue(self.mining.view()['ready']);self.assertFalse(self.mining.view()['wallet']['connected'])

    def test_business_failure_is_not_returned_as_transport_error(self):
        self.mining._save(status='needs_attention',error='fixture wallet error',message='fixture wallet error')
        self.assertNotIn('error',self.mining.view());self.assertEqual(self.mining.view()['error_message'],'fixture wallet error')

    def test_wallet_adapter_cannot_send_sign_or_change_settings(self):
        for args in [('wallet','send'),('contract-call','execute'),('wallet','settings','--dailyLimit','1')]:
            with self.assertRaises(ValueError):_read(*args)

    def test_wallet_network_is_verified_at_runtime(self):
        with patch('prospect.binance_wallet._read',side_effect=[{'status':'CONNECTED'},[{'binanceChainId':'1'}]]):
            with self.assertRaisesRegex(ValueError,'不支持 BSC'):receive_address()

    def test_quote_must_be_positive_and_exact_asset_pair(self):
        for data in [{'fromCoinSymbol':'USDT','toCoinSymbol':'BNB','toCoinAmount':'NaN'},
                     {'fromCoinSymbol':'FAKE','toCoinSymbol':'BNB','toCoinAmount':'1'},
                     {'fromCoinSymbol':'USDT','toCoinSymbol':'BNB','toCoinAmount':'0'}]:
            with patch('prospect.binance_wallet._read',return_value=data):
                with self.assertRaises(ValueError):usdt_quote()

    def test_pool_network_must_match_wallet_and_never_leak_raw_keys(self):
        raw={'uuid':IDENT,'network':'BSC','address':ADDRESS,'balance':'0','payment_threshold':'1.5','auto':False,'enabled':True,
             'mining_key':'sensitive-fixture','referral_code':'sensitive-fixture','err_flags':{}}
        with patch('prospect.mining.public_json',return_value=raw):
            self.assertNotIn('sensitive-fixture',json.dumps(pool_account(ADDRESS)))
        for change in [{'network':'ETH'},{'address':'0x'+'b'*40},{'enabled':False},{'payment_threshold':'NaN'},{'err_flags':{'restricted':True}}]:
            with patch('prospect.mining.public_json',return_value=raw|change):
                with self.assertRaises(ValueError):pool_account(ADDRESS)

    def test_preview_cannot_change_payout_or_accept_arbitrary_parameters(self):
        self.ready();engine=Executions(self.store,type('Plans',(),{'plans':lambda _:[]})(),self.path)
        with patch.object(engine.mining,'enable_payout') as mutate:
            quote=engine.preview(DRIVER)
        self.assertTrue(quote['ready']);mutate.assert_not_called()
        self.assertEqual(quote['limits']['duration_seconds'],900)
        self.assertEqual(quote['artifact']['sha256'],MINER_SHA)
        self.assertFalse(quote['limits']['idle_only'])
        for inputs in [{'public_address':'0x'+'b'*40},{'command':'whoami'},{'auto_payout':'yes'}]:
            with self.assertRaises(ValueError):engine.preview(DRIVER,inputs=inputs)
        with self.assertRaises(ValueError):engine.preview(DRIVER,options={'memory_mb':128})
        # A fresh scope is invalidated when the wallet changes, before any process runs.
        self.mining._save(wallet={'address':'0x'+'b'*40,'connected':True})
        with self.assertRaises(ValueError):engine.start(quote['id'],'fixture',True)
        engine.shutdown()

    def test_hashrate_without_accepted_share_is_not_contribution(self):
        raw={'hashrate':{'total':[99]},'results':{'shares_good':0,'shares_total':0},'connection':{'pool':'rx.unmineable.com:443'}}
        response=io.BytesIO(json.dumps(raw).encode())
        with patch('prospect.mining.urllib.request.build_opener') as op:
            op.return_value.open.return_value.__enter__.return_value=response
            result=miner_probe({'rpc_port':1234,'api_token':'secret-fixture','worker':'fixture'})
        self.assertEqual(result['accepted_shares'],0);self.assertNotIn('secret-fixture',json.dumps(result))

    def test_automatic_payout_requires_server_verified_account(self):
        with patch('prospect.mining.pool_account',return_value=POOL),patch('prospect.mining.public_json') as write:
            with self.assertRaises(ValueError):self.mining.enable_payout(ADDRESS,'2'*36)
            write.assert_not_called()
        with patch('prospect.mining.pool_account',side_effect=[POOL,POOL|{'auto_pay':True}]),patch('prospect.mining.public_json') as write:
            self.assertTrue(self.mining.enable_payout(ADDRESS,IDENT)['auto_pay'])
            write.assert_called_once_with('/v1/address/'+IDENT+'/setting/auto_pay',{'setting':True})

    def test_no_payment_evidence_stays_pending_even_after_pool_credit(self):
        job={'inputs':{'public_address':ADDRESS,'pool_uuid':IDENT},'pool_before':POOL,'contribution_verified':True}
        with patch.object(self.mining,'collect',return_value=POOL|{'balance':'0.0001'}),patch.object(self.mining,'payments',return_value=[]):
            result=self.mining.reconcile(job)
        self.assertTrue(result['pool_credit_verified']);self.assertFalse(result['rewards_verified'])
        self.assertEqual(result['delivery']['status'],'pool_credited')

    def test_delivery_requires_exact_chain_receipt_transfer_and_confirmations(self):
        tx='0x'+'1'*64;blockhash='0x'+'2'*64
        payment={'tx':tx,'amount':'1.5','network':'BSC'}
        receipt={'status':'0x1','transactionHash':tx,'blockNumber':'0x64','blockHash':blockhash,
                 'logs':[{'address':USDT_BSC,'topics':['0xddf252ad1be2c89b69c2b068fc378daa952ba7f163c4a11628f55a4df523b3ef','0x'+'0'*64,'0x'+'0'*24+ADDRESS[2:]],
                          'data':'0x'+format(15*10**17,'064x')}]}
        block={'hash':blockhash,'timestamp':hex(int(time.time()))};start=(dt.datetime.now(dt.timezone.utc)-dt.timedelta(minutes=1)).isoformat()
        self.assertEqual(verify_payment(payment,receipt,block,111,18,ADDRESS,start)['amount'],'1.5')
        for change in [{'status':'0x0'},{'transactionHash':'0x'+'3'*64},{'blockHash':'0x'+'4'*64},{'logs':[]}]:
            self.assertIsNone(verify_payment(payment,receipt|change,block,111,18,ADDRESS,start))
        self.assertIsNone(verify_payment(payment,receipt,block,105,18,ADDRESS,start))
        self.assertIsNone(verify_payment(payment|{'amount':'2'},receipt,block,111,18,ADDRESS,start))
        wrong=copy.deepcopy(receipt);wrong['logs'][0]['address']='0x'+'f'*40
        self.assertIsNone(verify_payment(payment,wrong,block,111,18,ADDRESS,start))


if __name__=='__main__':unittest.main()
