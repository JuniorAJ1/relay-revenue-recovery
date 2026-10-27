import copy
import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import patch
from relay.preview import create_preview_app


class PreviewTests(unittest.TestCase):
    def setUp(self):
        self.app=create_preview_app()
        self.client=self.app.test_client()
        self.state=None

    def operation(self,path,body=None,method='GET'):
        response=self.client.post('/api/demo',json={'path':path,'method':method,'body':body or {},'state':self.state})
        self.assertEqual(response.status_code,200,response.get_data(as_text=True))
        packet=response.get_json()
        self.state=packet['state']
        return packet['result'],packet['status']

    def test_public_session_and_sample_only_health(self):
        self.assertTrue(self.client.get('/api/auth/session').get_json()['preview'])
        self.assertEqual(self.client.get('/health').get_json()['mode'],'isolated-preview')

    def test_preview_contains_business_records_and_no_sessions_or_credentials(self):
        data,status=self.operation('/workspace')
        self.assertEqual(status,200)
        self.assertEqual(len(data['leads']),25)
        self.assertEqual(set(self.state),{'leads','appointments','payments','jobs','events'})
        self.assertFalse(any(data['integrations'].values()))
        self.assertEqual(sum(p['cents']*(1 if p['kind']=='settlement' else -1) for p in data['payments']),3500000)

    def test_independent_sample_workspaces(self):
        self.operation('/workspace')
        lead={'name':'Sample Person','email':'sample@example.com','cohort':'treatment'}
        self.assertEqual(self.operation('/leads',lead,'POST')[1],201)
        self.assertEqual(len(self.operation('/workspace')[0]['leads']),26)
        self.state=None
        self.assertEqual(len(self.operation('/workspace')[0]['leads']),25)

    def test_real_product_rules_block_control_and_permissionless_leads(self):
        self.operation('/workspace')
        _,status=self.operation('/leads/9/draft',{},'POST')
        self.assertEqual(status,400)
        _,status=self.operation('/leads/25/draft',{},'POST')
        self.assertEqual(status,400)

    @patch('relay.worker.send_mail')
    def test_full_simulated_recovery_to_cash_and_refund(self,send_mail):
        self.operation('/workspace')
        body={'subject':'Sample follow-up','body':'Hi. Reply unsubscribe to stop.','due_at':datetime.now(timezone.utc).isoformat()}
        self.assertEqual(self.operation('/leads/1/schedule',body,'POST')[1],201)
        self.assertEqual(self.operation('/worker/demo-tick',{},'POST')[1],200)
        self.assertEqual(self.state['jobs'][0]['status'],'simulated')
        starts=(datetime.now(timezone.utc)+timedelta(days=1)).isoformat()
        result,status=self.operation('/leads/1/book',{'starts_at':starts,'owner':'Alex'},'POST')
        self.assertEqual(status,201)
        self.assertEqual(self.operation('/appointments/'+str(result['appointment_id']),{'action':'attend'},'POST')[1],200)
        payment,status=self.operation('/leads/1/payments',{'amount':'100','reference':'sample-flow'},'POST')
        self.assertEqual(status,201)
        self.assertEqual(self.operation('/leads/1/payments',{'amount':'20','reference':'sample-refund','kind':'refund','settlement_id':payment['payment_id']},'POST')[1],201)
        self.assertEqual(self.operation('/leads/1/payments',{'amount':'81','reference':'too-much','kind':'refund','settlement_id':payment['payment_id']},'POST')[1],400)
        lead=self.operation('/workspace')[0]['leads'][0]
        self.assertEqual(lead['gross']-lead['refunds'],8000)
        send_mail.assert_not_called()

    def test_unknown_paths_and_external_integration_actions_are_blocked(self):
        for path in ('/integrations/import','/auth/login','/../../.env','/unsubscribe/token'):
            response=self.client.post('/api/demo',json={'path':path,'method':'POST','body':{}})
            self.assertEqual(response.status_code,400)

    def test_snapshot_rejects_extra_tables_and_column_injection(self):
        self.operation('/workspace')
        invalid=copy.deepcopy(self.state);invalid['users']=[]
        response=self.client.post('/api/demo',json={'path':'/workspace','state':invalid})
        self.assertEqual(response.status_code,400)
        invalid=copy.deepcopy(self.state);invalid['leads'][0]['x); DROP TABLE leads;--']='x'
        response=self.client.post('/api/demo',json={'path':'/workspace','state':invalid})
        self.assertEqual(response.status_code,400)

    def test_export_returns_the_visitors_own_sample_records(self):
        self.operation('/workspace')
        self.operation('/leads/1',{'name':'Changed Sample'},'PATCH')
        result,status=self.operation('/leads/export')
        self.assertEqual(status,200)
        self.assertIn('Changed Sample',result['csv'])

    def test_preview_does_not_expose_original_live_endpoints(self):
        self.assertEqual(self.client.post('/api/leads',json={}).status_code,404)
        self.assertEqual(self.client.get('/api/workspace').status_code,404)
