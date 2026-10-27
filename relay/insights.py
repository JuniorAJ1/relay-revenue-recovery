"""Read-only operational signals. Flags describe evidence, never inferred lost revenue."""
from datetime import datetime, timezone, timedelta
from .service import protection


def snapshot(leads, jobs, appointments, payments, clock=None):
    clock = clock or datetime.now(timezone.utc)
    by_lead = {lead['id']: lead for lead in leads}
    lead_jobs = {}
    lead_appointments = {}
    gross = {}
    for job in jobs:
        lead_jobs.setdefault(job['lead_id'], []).append(job)
    for appointment in appointments:
        lead_appointments.setdefault(appointment['lead_id'], []).append(appointment)
    for payment in payments:
        if payment['kind'] == 'settlement':
            gross[payment['lead_id']] = gross.get(payment['lead_id'], 0) + payment['cents']

    rules = [
        ('delivery', 'Delivery needs review', 'critical', 'Check provider evidence before scheduling another send.', 'jobs'),
        ('unassigned', 'Recovery has no owner', 'high', 'Assign an accountable owner before reviewing outreach.', 'queue'),
        ('attendance', 'Attendance not recorded', 'high', 'Record the call outcome. An elapsed appointment is not proof of a no-show.', 'schedule'),
        ('unsettled', 'Attended, no settlement recorded', 'medium', 'Check the sales outcome and reconcile any provider settlement.', 'outcomes'),
        ('waiting', 'Follow-up has gone quiet', 'medium', 'Review the conversation and decide the next action.', 'queue'),
        ('recovery', 'Ready for a recovery review', 'low', 'Review context and permission before scheduling a follow-up.', 'queue'),
    ]
    matches = {rule[0]: {} for rule in rules}

    def add(rule, lead_id, evidence):
        if lead_id in by_lead:
            matches[rule][lead_id] = {'lead_id': lead_id, 'evidence': evidence}

    for job in jobs:
        if job['status'] in ('unknown', 'blocked'):
            add('delivery', job['lead_id'], 'Message #' + str(job['id']) + ' is ' + job['status'] + '. ' + (job.get('error') or 'Provider review required.'))
    for lead in leads:
        lead_id = lead['id']
        idle = max(0, (clock - datetime.fromisoformat(lead['last_touch'])).days)
        pending = any(job['status'] in ('queued', 'sending', 'unknown') for job in lead_jobs.get(lead_id, []))
        # Reuse the exact send protection policy; a flag never grants outreach permission.
        protected = protection(lead)
        eligible = not protected and lead['status'] == 'ready' and idle >= 7
        if eligible and not pending:
            rule = 'unassigned' if not lead['owner'].strip() else 'recovery'
            add(rule, lead_id, str(idle) + ' days since last touch; no recovery job is pending.' + (' No owner is assigned.' if rule == 'unassigned' else ''))
        sent_times = [datetime.fromisoformat(job.get('claimed_at') or job['created_at'])
                      for job in lead_jobs.get(lead_id, [])
                      if job['status'] in ('sent', 'simulated')]
        last_recorded_touch = max([datetime.fromisoformat(lead['last_touch'])] + sent_times)
        follow_up_idle = max(0, (clock - last_recorded_touch).days)
        if not protected and lead['status'] == 'waiting' and follow_up_idle >= 7 and not pending:
            add('waiting', lead_id, str(follow_up_idle) + ' days since the last recorded touch; awaiting reply with no pending job. Check the conversation before contacting.')
        history = lead_appointments.get(lead_id, [])
        overdue = [a for a in history if a['status'] == 'booked' and datetime.fromisoformat(a['starts_at']) < clock - timedelta(hours=1)]
        if overdue:
            latest = max(overdue, key=lambda a: a['starts_at'])
            starts = datetime.fromisoformat(latest['starts_at']).astimezone(timezone.utc).strftime('%d %b %Y, %H:%M UTC')
            add('attendance', lead_id, 'The call on ' + starts + ' still has a booked status.')
        if lead['status'] == 'attended' and any(a['status'] == 'attended' for a in history) and not gross.get(lead_id):
            add('unsettled', lead_id, 'Attendance is recorded, but no settlement exists in Relay. This does not establish that money is owed.')

    return {
        'generated_at': clock.isoformat(timespec='seconds'),
        'rules': [dict(id=key, title=title, severity=severity, action=action, route=route,
                       matches=list(matches[key].values())) for key, title, severity, action, route in rules],
        'basis': 'Current workspace records. Flags are review tasks, not lost-revenue estimates.',
    }
