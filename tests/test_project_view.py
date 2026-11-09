import copy
import unittest

from prospect.agent_checks import validate_report
from prospect.execution_drivers import PACKAGE_SHA,PACKAGE_URL
from prospect.executions import Executions
from prospect.project_view import compute_profile,launch_summary
from test_agent_checks import report


class ProjectViewTests(unittest.TestCase):
    def setUp(self):
        self.plan={'id':'p','execution_drivers':['opacra-testnet-node','opacra-testnet-cpu'],
            'recipe':{'id':'opacra-testnet','network':'testnet','artifact':{'url':PACKAGE_URL,'sha256':PACKAGE_SHA}},
            'recommendation':{'status':'audit_pending'}}

    def test_known_route_is_cpu_even_with_a_gpu_in_the_device(self):
        profile=compute_profile({'summary':'GPU CPU','requirements':{'min_vram_gb':6}},plan=self.plan)
        self.assertEqual(profile['priority'],'cpu');self.assertEqual(profile['basis'],'execution_route')
        self.assertEqual(profile['sources'],[PACKAGE_URL])

    def test_discovery_mentions_remain_unverified_and_ram_is_not_a_compute_preference(self):
        for summary,expected in [('CPU miner','cpu'),('GPU CUDA contribution','gpu'),('CPU or GPU','either'),('Browser tasks','unknown')]:
            p=compute_profile({'summary':summary,'requirements':{'min_vram_gb':6}})
            self.assertEqual(p['priority'],expected);self.assertNotEqual(p['basis'],'agent_report')
        self.assertEqual(compute_profile({'requirements':{'min_vram_gb':6}})['priority'],'unknown')

    def test_new_agent_report_needs_cited_compute_conclusion_and_old_reports_still_work(self):
        r=report();validate_report(r,{})
        r['compute_profile']={'priority':'gpu','reason':'Synthetic GPU route','sources':[r['sources'][0]['url']]}
        validated=validate_report(r,{})
        self.assertEqual(compute_profile({},validated)['label'],'GPU 优先')
        r['compute_profile']['sources']=[]
        with self.assertRaises(ValueError):validate_report(r,{})
        r['compute_profile']['sources']=['https://invented.example/']
        with self.assertRaises(ValueError):validate_report(r,{})

    def test_malformed_historical_profile_does_not_break_workspace(self):
        self.assertEqual(compute_profile({},report={'compute_profile':{'priority':'fake'}})['priority'],'unknown')

    def test_readiness_and_runtime_share_exact_version_hash_and_scope_checks(self):
        ready=copy.deepcopy(self.plan);ready['recommendation']={'status':'suggested_trial','audit':{'version':'1.0.0','artifact_sha256':PACKAGE_SHA,'method':'source_review'}}
        # readiness is a pure rule; it never downloads or launches a program.
        controller=object.__new__(Executions)
        self.assertTrue(controller.readiness(ready)['can_configure'])
        for field,value in [('artifact_sha256','0'*64),('version','2.0.0'),('method','official_web')]:
            changed=copy.deepcopy(ready);changed['recommendation']['audit'][field]=value
            self.assertFalse(controller.readiness(changed)['can_configure'])
        changed=copy.deepcopy(ready);changed['recipe']['artifact']['sha256']='0'*64
        self.assertFalse(controller.readiness(changed)['can_configure'])

    def test_missing_executor_and_pending_audit_explain_different_owners(self):
        missing=launch_summary({},None,None)
        self.assertEqual(missing['owner'],'software');self.assertFalse(missing['can_configure'])
        controller=object.__new__(Executions);pending=launch_summary({},self.plan,controller.readiness(self.plan))
        self.assertEqual(pending['status'],'preparing');self.assertEqual(pending['owner'],'agent');self.assertTrue(pending['testnet'])
        self.assertFalse(pending['can_configure'])

    def test_known_safety_failure_is_not_hidden_by_missing_executor(self):
        blocked=launch_summary({}, {'id':'p','execution_drivers':[],'recommendation':{'status':'security_concern','reason':'Synthetic evidence'}},None)
        self.assertEqual(blocked['status'],'unsafe');self.assertEqual(blocked['reason'],'Synthetic evidence')
