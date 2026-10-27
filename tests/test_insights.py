import copy
import unittest
from datetime import datetime, timedelta, timezone
from relay.insights import snapshot


class InsightTests(unittest.TestCase):
    def setUp(self):
        self.clock = datetime(2026, 10, 21, 12, tzinfo=timezone.utc)

    def lead(self, number=1, **overrides):
        return dict(id=number, owner='Alex', status='ready', consent=1,
                    consent_note='Recorded permission', opted_out=0, customer=0,
                    active=0, cohort='treatment',
                    last_touch=(self.clock-timedelta(days=8)).isoformat(), **overrides)

    def run_snapshot(self, leads, jobs=None, appointments=None, payments=None):
        return snapshot(leads,jobs or [],appointments or [],payments or [],clock=self.clock)

    def matches(self, result, rule):
        return next(r['matches'] for r in result['rules'] if r['id']==rule)

    def test_protection_and_pending_jobs_prevent_recovery_flags(self):
        leads=[self.lead()]
        for number,changes in enumerate([{'opted_out':1},{'customer':1},{'active':1},
                {'cohort':'control'},{'consent_note':''},{'consent':0},
                {'last_touch':self.clock.isoformat()}],2):
            lead=self.lead(number);lead.update(changes);leads.append(lead)
        lead=self.lead(9);leads.append(lead)
        jobs=[dict(id=1,lead_id=9,status='queued')]
        result=self.run_snapshot(leads,jobs)
        self.assertEqual([m['lead_id'] for m in self.matches(result,'recovery')],[1])

    def test_unassigned_is_a_distinct_action_and_snapshot_is_read_only(self):
        lead=self.lead();lead['owner']=' '
        original=copy.deepcopy(lead)
        result=self.run_snapshot([lead])
        self.assertEqual(len(self.matches(result,'unassigned')),1)
        self.assertEqual(self.matches(result,'recovery'),[])
        self.assertEqual(lead,original)

    def test_waiting_requires_seven_idle_days_and_no_pending_send(self):
        leads=[self.lead(i) for i in range(1,5)]
        for lead in leads:lead['status']='waiting'
        leads[1]['last_touch']=(self.clock-timedelta(days=6,hours=23)).isoformat()
        leads[3]['cohort']='control'
        result=self.run_snapshot(leads,[dict(id=1,lead_id=3,status='unknown',error='Check SMTP')])
        self.assertEqual([m['lead_id'] for m in self.matches(result,'waiting')],[1])
        self.assertEqual([m['lead_id'] for m in self.matches(result,'delivery')],[3])

    def test_elapsed_booking_does_not_invent_a_no_show(self):
        lead=self.lead();lead.update(status='booked',active=1)
        appointment=dict(id=3,lead_id=1,status='booked',starts_at=(self.clock-timedelta(minutes=59)).isoformat())
        self.assertEqual(self.matches(self.run_snapshot([lead],appointments=[appointment]),'attendance'),[])
        appointment['starts_at']=(self.clock-timedelta(minutes=61)).isoformat()
        result=self.run_snapshot([lead],appointments=[appointment])
        self.assertEqual(len(self.matches(result,'attendance')),1)
        self.assertEqual(appointment['status'],'booked')
        appointment['status']='cancelled'
        self.assertEqual(self.matches(self.run_snapshot([lead],appointments=[appointment]),'attendance'),[])

    def test_recent_accepted_send_prevents_a_false_stale_follow_up(self):
        lead=self.lead();lead['status']='waiting'
        job=dict(id=1,lead_id=1,status='sent',created_at=(self.clock-timedelta(days=9)).isoformat(),
                 claimed_at=(self.clock-timedelta(hours=3)).isoformat())
        self.assertEqual(self.matches(self.run_snapshot([lead],[job]),'waiting'),[])
        job['claimed_at']=(self.clock-timedelta(days=8)).isoformat()
        self.assertEqual(len(self.matches(self.run_snapshot([lead],[job]),'waiting')),1)

    def test_attendance_without_settlement_is_not_a_claim_of_debt(self):
        lead=self.lead();lead.update(status='attended',active=1)
        appointment=dict(id=1,lead_id=1,status='attended',starts_at=self.clock.isoformat())
        result=self.run_snapshot([lead],appointments=[appointment])
        self.assertIn('does not establish',self.matches(result,'unsettled')[0]['evidence'])
        payments=[dict(lead_id=1,kind='settlement',cents=10000),dict(lead_id=1,kind='refund',cents=10000)]
        result=self.run_snapshot([lead],appointments=[appointment],payments=payments)
        self.assertEqual(self.matches(result,'unsettled'),[])

    def test_delivery_flags_are_deduplicated_and_include_protected_contacts(self):
        lead=self.lead();lead['opted_out']=1
        jobs=[dict(id=i,lead_id=1,status=status,error='Needs evidence',created_at=self.clock.isoformat())
              for i,status in enumerate(['unknown','blocked','sent','simulated','cancelled','queued'],1)]
        result=self.run_snapshot([lead],jobs)
        self.assertEqual(len(self.matches(result,'delivery')),1)
        self.assertEqual(self.matches(result,'recovery'),[])
