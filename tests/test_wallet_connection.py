import threading
import time
import unittest
from unittest.mock import patch,Mock
from prospect.binance_wallet import WalletConnection


class WalletConnectionTests(unittest.TestCase):
    def test_requires_explicit_confirmation(self):
        wallet=WalletConnection(lambda:None)
        with patch('prospect.binance_wallet._invoke') as invoke:
            with self.assertRaises(ValueError):wallet.start()
            invoke.assert_not_called()

    def test_does_not_expose_extra_cli_fields_and_waits_for_phone(self):
        entered=threading.Event();finish=threading.Event();connected=Mock()
        data={'urlForWeb':'https://app.binance.com/uni-qr/example','qrCodeId':'11111111-1111-1111-1111-111111111111','pairingCode':'a1b2c3','expireAt':str(int(time.time()*1000)+290000),'sessionId':'secret-fixture','clientId':'secret-fixture'}
        def invoke(args,**kwargs):
            if args==('auth','signin'):return data
            entered.set();finish.wait(3);return {'status':'SUCCESS','sessionId':'secret-fixture'}
        wallet=WalletConnection(connected)
        with patch('prospect.binance_wallet._invoke',side_effect=invoke) as command,patch('prospect.binance_wallet._read',return_value={'status':'CONNECTED'}):
            wallet.start(True);self.assertTrue(entered.wait(2))
            self.assertEqual(wallet.view()['status'],'waiting');self.assertNotIn('secret-fixture',str(wallet.view()))
            self.assertNotIn('qrCodeId',wallet.view());wallet.start(True);self.assertEqual(command.call_count,2)
            finish.set();wallet.thread.join(2)
        self.assertEqual(wallet.view()['status'],'connected');connected.assert_called_once()

    def test_refuses_foreign_login_url(self):
        wallet=WalletConnection(Mock())
        with patch('prospect.binance_wallet._invoke',return_value={'urlForWeb':'https://app.binance.com.evil.example/'}):
            wallet.start(True);wallet.thread.join(2)
        self.assertEqual(wallet.view()['status'],'error');self.assertNotIn('url',wallet.view())

    def test_verify_success_is_not_assumed_to_be_connected(self):
        wallet=WalletConnection(Mock())
        with patch('prospect.binance_wallet._invoke',return_value={'status':'ALREADY_CONNECTED'}),patch('prospect.binance_wallet._read',return_value={'status':'UNCONNECTED'}):
            wallet.start(True);wallet.thread.join(2)
        self.assertEqual(wallet.view()['status'],'error');wallet.on_connected.assert_not_called()


if __name__=='__main__':unittest.main()
