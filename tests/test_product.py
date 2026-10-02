import io
import tempfile
import unittest
import threading
from datetime import datetime, timezone, timedelta
from unittest.mock import patch as mock_patch, MagicMock
from werkzeug.security import generate_password_hash
from itsdangerous import URLSafeTimedSerializer
from relay.app import create_app
from relay.db import connect, now
from relay.worker import run_once, send_mail
from relay import connectors

def future(hours=24): return (datetime.now(timezone.utc)+timedelta(hours=hours)).isoformat()

class ProductTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.app=create_app({'TESTING':True,'DEMO_MODE':True,'DATABASE_PATH':self.temp.name+'/test.sqlite3','SECRET_KEY':'test-secret-only','COOKIE_SECURE':False})
        self.client=self.app.test_client()
        self.session=self.client.post('/api/auth/demo',headers={'X-Relay-Request':'1'}).get_json()
        self.headers={'X-CSRF-Token':self.session['csrf']}
    def tearDown(self): self.temp.cleanup()
    def post(self,path,data=None): return self.client.post('/api'+path,json=data or {},headers=self.headers)
    def patch(self,path,data): return self.client.patch('/api'+path,json=data,headers=self.headers)
    def workspace(self): return self.client.get('/api/workspace').get_json()
    def schedule(self,id=1,due=None):
        return self.post('/leads/'+str(id)+'/schedule',{'subject':'Hello','body':'Hello. Reply unsubscribe to opt out.','due_at':due or now()})
    def booking(self,id=1): return self.post('/leads/'+str(id)+'/book',{'starts_at':future(),'owner':'Alex'})
    def test_auth_and_csrf(self):
        anonymous=self.app.test_client()
        self.assertEqual(anonymous.get('/api/workspace').status_code,401)
        self.assertEqual(self.client.post('/api/leads',json={'name':'x'}).status_code,403)
        self.assertEqual(anonymous.post('/api/auth/demo').status_code,403)
        self.assertIn('HttpOnly',self.client.post('/api/auth/demo',headers={'X-Relay-Request':'1'}).headers['Set-Cookie'])
    def test_login_rate_limit_and_logout(self):
        for _ in range(5):
            self.assertEqual(self.client.post('/api/auth/login',json={'email':'demo@relay.local','password':'wrong'},headers={'X-Relay-Request':'1'}).status_code,401)
        self.assertEqual(self.client.post('/api/auth/login',json={'email':'demo@relay.local','password':'wrong'},headers={'X-Relay-Request':'1'}).status_code,429)
        self.assertEqual(self.post('/auth/logout').status_code,200)
        self.assertEqual(self.client.get('/api/workspace').status_code,401)
    def test_live_password_login_and_demo_disabled(self):
        app=create_app({'TESTING':True,'DEMO_MODE':False,'DATABASE_PATH':self.temp.name+'/live.sqlite3','SECRET_KEY':'x'*48})
        db=connect(app.config['DATABASE_PATH']); db.execute('INSERT INTO users(email,password_hash,name,created_at) VALUES (?,?,?,?)',('owner@example.com',generate_password_hash('correct-long-password',method='pbkdf2:sha256:600000'),'Owner',now()));db.close()
        client=app.test_client()
        self.assertEqual(client.post('/api/auth/demo',headers={'X-Relay-Request':'1'}).status_code,404)
        result=client.post('/api/auth/login',headers={'X-Relay-Request':'1'},json={'email':'owner@example.com','password':'correct-long-password'})
        self.assertEqual(result.status_code,200)
        self.assertEqual(client.get('/api/workspace').get_json()['leads'],[])
    def test_protected_and_control_leads_blocked(self):
        for id in (9,22,23,24,25): self.assertEqual(self.schedule(id).status_code,400)
        self.assertEqual(self.post('/leads/9/draft').status_code,400)
    def test_recent_contact_and_permission_evidence(self):
        result=self.post('/leads',{'name':'New Person','email':'new@example.com','consent':True})
        self.assertEqual(result.status_code,400)
        result=self.post('/leads',{'name':'New Person','email':'new@example.com','consent':True,'consent_note':'Form opt-in today','cohort':'treatment'})
        self.assertEqual(result.status_code,201)
        self.assertEqual(self.schedule(result.get_json()['lead']['id']).status_code,400)
    def test_schedule_persistence_and_dedup(self):
        self.assertEqual(self.schedule().status_code,201)
        self.assertEqual(self.schedule().status_code,400)
        second=create_app(dict(self.app.config))
        db=connect(second.config['DATABASE_PATH']);self.assertEqual(db.execute('SELECT COUNT(*) FROM jobs').fetchone()[0],1);db.close()
        self.assertEqual(run_once(self.app.config),1)
        self.assertEqual(run_once(self.app.config),0)
        self.assertEqual(self.workspace()['jobs'][0]['status'],'simulated')
    def test_future_job_not_dispatched(self):
        self.schedule(due=future());self.assertEqual(run_once(self.app.config),0)
        self.assertEqual(self.workspace()['jobs'][0]['status'],'queued')
    def test_edit_invalidates_approvals_and_optout(self):
        self.schedule();self.patch('/leads/1',{'opted_out':True})
        self.assertEqual(self.workspace()['jobs'][0]['status'],'cancelled')
        self.assertEqual(run_once(self.app.config),0)
        self.assertEqual(self.schedule().status_code,400)
    def test_full_outcome_and_refund_bounds(self):
        self.schedule();appt=self.booking().get_json()['appointment_id']
        self.assertEqual(self.workspace()['jobs'][0]['status'],'cancelled')
        self.assertEqual(self.post('/leads/1/payments',{'amount':'100','reference':'early'}).status_code,400)
        self.assertEqual(self.post('/appointments/'+str(appt),{'action':'attend'}).status_code,200)
        payment=self.post('/leads/1/payments',{'amount':'12000.25','reference':'txn-1'})
        self.assertEqual(payment.status_code,201);id=payment.get_json()['payment_id']
        self.assertEqual(self.post('/leads/1/payments',{'amount':'12000.25','reference':'txn-1'}).status_code,409)
        self.assertEqual(self.post('/leads/1/payments',{'amount':'0.001','reference':'precision'}).status_code,400)
        self.assertEqual(self.post('/leads/1/payments',{'amount':'2000.25','reference':'refund-1','kind':'refund','settlement_id':id}).status_code,201)
        self.assertEqual(self.post('/leads/1/payments',{'amount':'10000.01','reference':'refund-over','kind':'refund','settlement_id':id}).status_code,400)
        lead=self.workspace()['leads'][0];self.assertEqual(lead['gross']-lead['refunds'],1000000)
        events=self.client.get('/api/leads/1').get_json()['events'];self.assertTrue(any(x['kind']=='payment.refund' for x in events))
    def test_reschedule_and_cancel_invalidate_reminders(self):
        appt=self.booking().get_json()['appointment_id']
        path='/appointments/'+str(appt)
        reminder={'due_at':future(23),'body':'Your call is tomorrow. Reply unsubscribe.'}
        self.assertEqual(self.post(path+'/reminder',reminder).status_code,201)
        self.assertEqual(self.post(path+'/reminder',reminder).status_code,400)
        self.assertEqual(self.post(path,{'action':'reschedule','starts_at':future(48)}).status_code,200)
        self.assertEqual(self.workspace()['jobs'][0]['status'],'cancelled')
        self.assertEqual(self.post(path+'/reminder',{'due_at':future(47),'body':'Reply unsubscribe.'}).status_code,201)
        self.post(path,{'action':'cancel'})
        self.assertEqual(self.workspace()['jobs'][0]['status'],'cancelled')
    def test_import_is_atomic_and_default_permission_false(self):
        csv=b'name,email\nFirst,unique@example.com\nDuplicate,lead1@example.com\n'
        result=self.client.post('/api/leads/import',data={'file':(io.BytesIO(csv),'leads.csv')},headers=self.headers)
        self.assertEqual(result.status_code,409);self.assertEqual(len(self.workspace()['leads']),25)
        csv=b'name,email,context\nNew,new@example.com,=HYPERLINK("danger")\n'
        result=self.client.post('/api/leads/import',data={'file':(io.BytesIO(csv),'leads.csv')},headers=self.headers)
        self.assertEqual(result.status_code,201);self.assertFalse(self.workspace()['leads'][-1]['consent'])
    def test_email_rejects_header_and_multiple_recipient_injection(self):
        for address in ('a@example.com,b@example.com','a@example.com\nBcc:evil@example.com','<a@example.com>'):
            self.assertEqual(self.post('/leads',{'name':'X','email':address}).status_code,400)
    def test_export_escapes_formula_cells(self):
        self.patch('/leads/1',{'name':'=HYPERLINK("x")'})
        output=self.client.get('/api/leads/export').data.decode()
        self.assertIn("'=HYPERLINK",output)
    def test_mode_separation(self):
        with self.assertRaises(RuntimeError):create_app({'TESTING':True,'DEMO_MODE':False,'DATABASE_PATH':self.app.config['DATABASE_PATH'],'SECRET_KEY':'x'*48})
    def test_unsubscribe_requires_valid_token_and_cancels_jobs(self):
        self.schedule(); token=URLSafeTimedSerializer(self.app.config['SECRET_KEY'],salt='relay-unsubscribe').dumps(1)
        anonymous=self.app.test_client()
        self.assertEqual(anonymous.get('/unsubscribe/bad').status_code,400)
        self.assertEqual(anonymous.get('/unsubscribe/'+token).status_code,200)
        self.assertFalse(self.workspace()['leads'][0]['opted_out'])
        self.assertEqual(anonymous.post('/unsubscribe/'+token).status_code,200)
        self.assertTrue(self.workspace()['leads'][0]['opted_out']);self.assertEqual(self.workspace()['jobs'][0]['status'],'cancelled')
    def test_unknown_delivery_never_retried(self):
        self.schedule()
        config=dict(self.app.config,DEMO_MODE=False,LIVE_SEND_ENABLED=True,SMTP_HOST='test',SMTP_FROM='team@example.com')
        transport=MagicMock(side_effect=TimeoutError())
        self.assertEqual(run_once(config,transport),1)
        self.assertEqual(self.workspace()['jobs'][0]['status'],'unknown')
        self.assertEqual(run_once(config,transport),0);self.assertEqual(transport.call_count,1)
    def test_manual_unknown_reconciliation_requires_evidence(self):
        self.schedule();config=dict(self.app.config,DEMO_MODE=False,LIVE_SEND_ENABLED=True,SMTP_HOST='test',SMTP_FROM='team@example.com')
        run_once(config,MagicMock(side_effect=TimeoutError()))
        id=self.workspace()['jobs'][0]['id'];path='/jobs/'+str(id)+'/reconcile'
        self.assertEqual(self.post(path,{'outcome':'not_sent'}).status_code,400)
        self.assertEqual(self.post(path,{'outcome':'not_sent','note':'SMTP log confirms connection failed before DATA'}).status_code,200)
        self.assertEqual(self.schedule().status_code,201)
    def test_confirmed_acceptance_cannot_be_reconciled_twice(self):
        self.schedule();config=dict(self.app.config,DEMO_MODE=False,LIVE_SEND_ENABLED=True,SMTP_HOST='test',SMTP_FROM='team@example.com')
        run_once(config,MagicMock(side_effect=TimeoutError()))
        path='/jobs/'+str(self.workspace()['jobs'][0]['id'])+'/reconcile'
        data={'outcome':'accepted','note':'Verified SMTP transaction log','provider_id':'smtp-verified-1'}
        self.assertEqual(self.post(path,data).status_code,200)
        self.assertEqual(self.post(path,data).status_code,400)
        self.assertEqual(self.schedule().status_code,400)
    def test_crash_claim_becomes_unknown(self):
        self.schedule();db=connect(self.app.config['DATABASE_PATH'])
        db.execute("UPDATE jobs SET status='sending',claimed_at=?",((datetime.now(timezone.utc)-timedelta(minutes=6)).isoformat(),));db.close()
        self.assertEqual(run_once(self.app.config),0);self.assertEqual(self.workspace()['jobs'][0]['status'],'unknown')
    def test_two_workers_claim_once(self):
        self.schedule();result=[]
        threads=[threading.Thread(target=lambda:result.append(run_once(self.app.config))) for _ in range(2)]
        for t in threads:t.start()
        for t in threads:t.join()
        self.assertEqual(sum(result),1)
    def test_live_disabled_blocks_transport(self):
        self.schedule();transport=MagicMock()
        config=dict(self.app.config,DEMO_MODE=False,LIVE_SEND_ENABLED=False)
        run_once(config,transport);transport.assert_not_called();self.assertEqual(self.workspace()['jobs'][0]['status'],'blocked')
    def test_smtp_acceptance_recorded_not_delivered(self):
        self.schedule();config=dict(self.app.config,DEMO_MODE=False,LIVE_SEND_ENABLED=True,SMTP_HOST='test',SMTP_FROM='team@example.com')
        run_once(config,lambda *args:'provider-id')
        job=self.workspace()['jobs'][0];self.assertEqual(job['status'],'sent');self.assertEqual(job['provider_id'],'provider-id')
    def test_stale_reminder_snapshot_cannot_dispatch(self):
        appt=self.booking().get_json()['appointment_id']
        self.post('/appointments/'+str(appt)+'/reminder',{'due_at':now(),'body':'Reply unsubscribe.'})
        # Simulate an appointment update after a worker has chosen the reminder.
        db=connect(self.app.config['DATABASE_PATH']);db.execute('UPDATE appointments SET starts_at=? WHERE id=?',(future(48),appt));db.close()
        self.assertEqual(run_once(self.app.config),1)
        self.assertEqual(self.workspace()['jobs'][0]['status'],'cancelled')
    @mock_patch('relay.worker.smtplib.SMTP')
    def test_smtp_uses_tls_and_real_optout_link(self,smtp):
        self.schedule();db=connect(self.app.config['DATABASE_PATH'])
        job=dict(db.execute('SELECT * FROM jobs').fetchone());lead=dict(db.execute('SELECT * FROM leads WHERE id=1').fetchone());db.close()
        server=smtp.return_value.__enter__.return_value;server.send_message.return_value={}
        config=dict(self.app.config,SMTP_HOST='smtp.example.com',SMTP_PORT='587',SMTP_FROM='team@example.com',SMTP_USERNAME='test',SMTP_PASSWORD='fake-test-secret')
        identifier=send_mail(config,job,lead)
        server.starttls.assert_called_once();server.login.assert_called_once_with('test','fake-test-secret')
        message=server.send_message.call_args[0][0]
        self.assertEqual(message['To'],'lead1@example.com');self.assertIn('/unsubscribe/',message.get_content());self.assertEqual(message['Message-ID'],identifier)

class ConnectorTests(unittest.TestCase):
    @mock_patch('relay.connectors.fetch')
    def test_close_contact_mapping(self,fetch):
        fetch.return_value={'name':'Real Contact','emails':[{'email':'real@example.com'}]}
        row=connectors.contact('close','cont_123',{'CLOSE_API_KEY':'fake-test-key'})
        self.assertFalse(row['consent']);self.assertEqual(row['email'],'real@example.com')
        self.assertTrue(fetch.call_args[0][1]['Authorization'].startswith('Basic '))
    @mock_patch('relay.connectors.fetch')
    def test_highlevel_dnd_and_location(self,fetch):
        config={'HIGHLEVEL_TOKEN':'fake','HIGHLEVEL_LOCATION_ID':'loc_1'}
        fetch.return_value={'contact':{'name':'Contact','email':'a@example.com','locationId':'loc_1','dnd':False,'dndSettings':{'Email':{'status':'active'}}}}
        self.assertTrue(connectors.contact('highlevel','123',config)['opted_out'])
        fetch.return_value['contact']['locationId']='other'
        with self.assertRaises(ValueError):connectors.contact('highlevel','123',config)

if __name__=='__main__':unittest.main()
