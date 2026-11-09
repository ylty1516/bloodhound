import tempfile
import unittest
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
from prospect.store import Store


class ParticipationStoreTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.store = Store(Path(self.tmp.name) / 'state.sqlite3')
        self.proposal = {'id':'request-one','candidate_id':'candidate-one','candidate_name':'fixture',
                         'revision':'v1','created_at':'2026-11-06T12:00:00+00:00','status':'pending',
                         'plan':{},'reasons':['fixture only'],'blockers':[],'readiness':'plan_review_only'}

    def tearDown(self): self.tmp.cleanup()

    def test_polling_and_concurrent_refresh_emit_one_request(self):
        with ThreadPoolExecutor(max_workers=8) as executor:
            list(executor.map(lambda _: self.store.sync_participation_requests([self.proposal]), range(32)))
        events = [e for e in self.store.events(1000) if e['kind']=='participation_requested']
        self.assertEqual(len(events), 1)

    def test_interest_is_not_execution_authority_and_survives_restart(self):
        self.store.sync_participation_requests([self.proposal])
        result = self.store.decide_participation('request-one','interested')
        self.assertFalse(result['execution_authorized'])
        self.assertEqual(self.store.runs(), [])
        restarted = Store(self.store.path)
        self.assertEqual(restarted.sync_participation_requests([self.proposal])[0]['status'], 'interested')

    def test_dismissal_is_not_repeated_by_heartbeat(self):
        self.store.sync_participation_requests([self.proposal])
        self.store.decide_participation('request-one','dismissed')
        revised = self.proposal | {'created_at':'2026-11-06T13:00:00+00:00'}
        self.assertEqual(self.store.sync_participation_requests([revised])[0]['status'],'dismissed')

    def test_closed_or_changed_request_cannot_be_accepted(self):
        self.store.sync_participation_requests([self.proposal])
        self.store.sync_participation_requests([])
        with self.assertRaises(ValueError): self.store.decide_participation('request-one','interested')
        newer = self.proposal | {'id':'request-two','revision':'v2'}
        self.assertEqual(self.store.sync_participation_requests([newer])[0]['status'], 'pending')

    def test_validation_provenance_preserves_original_record(self):
        raw = self.store.add_run({'id':'qa','mode':'simulation','status':'blocked'})
        self.store.annotate_validation_run('qa','browser QA record')
        self.assertEqual(self.store.runs()[0]['origin'],'validation')
        with self.store._connection() as connection:
            original = connection.execute('SELECT payload FROM runs WHERE id=?',('qa',)).fetchone()[0]
        self.assertNotIn('origin',original)
        self.assertEqual(raw['status'],'blocked')
        self.store.add_run({'id':'user','mode':'simulation','status':'blocked'})
        self.assertNotIn('origin',self.store.runs()[0])

    def test_revalidation_restores_intent_without_new_notification(self):
        for prior in ('pending','interested'):
            self.store.sync_participation_requests([self.proposal])
            if prior=='interested': self.store.decide_participation('request-one',prior)
            self.store.sync_participation_requests([])
            renewed=self.proposal | {'created_at':'2026-11-06T13:00:00+00:00'}
            row=self.store.sync_participation_requests([renewed])[0]
            self.assertEqual(row['status'],prior)
            self.assertEqual(row['created_at'],self.proposal['created_at'])
            self.assertFalse(row['execution_authorized'])
        self.assertEqual(sum(e['kind']=='participation_requested' for e in self.store.events(100)),1)

if __name__ == '__main__': unittest.main()
