"""Durable delivery queue. Ambiguous sends are never retried automatically."""
import smtplib
import ssl
from email.message import EmailMessage
from email.utils import make_msgid
from datetime import datetime, timezone, timedelta
from itsdangerous import URLSafeTimedSerializer
from .db import connect, transaction, now, event
from .service import protection, get_lead
from .connectors import contact

def send_mail(config, job, lead):
    message=EmailMessage()
    message['From']=config['SMTP_FROM']; message['To']=job['recipient']; message['Subject']=job['subject']
    identifier=make_msgid(domain=config['SMTP_FROM'].split('@')[-1]); message['Message-ID']=identifier
    token=URLSafeTimedSerializer(config['SECRET_KEY'],salt='relay-unsubscribe').dumps(lead['id'])
    link=config['APP_BASE_URL'].rstrip('/')+'/unsubscribe/'+token
    message['List-Unsubscribe']='<'+link+'>'
    message.set_content(job['body']+'\n\nUnsubscribe: '+link)
    with smtplib.SMTP(config['SMTP_HOST'],int(config.get('SMTP_PORT') or 587),timeout=15) as smtp:
        smtp.ehlo(); smtp.starttls(context=ssl.create_default_context()); smtp.ehlo()
        if config.get('SMTP_USERNAME'): smtp.login(config['SMTP_USERNAME'],config['SMTP_PASSWORD'])
        rejected=smtp.send_message(message)
        if rejected: raise smtplib.SMTPRecipientsRefused(rejected)
    return identifier

def run_once(config, transport=None):
    db=connect(config['DATABASE_PATH']); processed=0
    try:
        with transaction(db):
            # A process may have crashed after handing the message to SMTP.
            cutoff=(datetime.now(timezone.utc)-timedelta(minutes=5)).isoformat(timespec='seconds')
            stale=list(db.execute("SELECT * FROM jobs WHERE status='sending' AND claimed_at<?",(cutoff,)))
            for job in stale:
                db.execute("UPDATE jobs SET status='unknown',error='Worker interrupted; reconcile provider before another send' WHERE id=?",(job['id'],))
                event(db,job['lead_id'],'Worker','message.unknown','Interrupted job '+str(job['id'])+' requires manual reconciliation')
        # Claim each job in its own committed transaction before any network IO.
        for _ in range(20):
            with transaction(db):
                job=db.execute("SELECT * FROM jobs WHERE status='queued' AND due_at<=? ORDER BY due_at,id LIMIT 1",(now(),)).fetchone()
                if not job: break
                job=dict(job)
                db.execute("UPDATE jobs SET status='sending',claimed_at=? WHERE id=?",(now(),job['id']))
            with transaction(db):
                lead=get_lead(db,job['lead_id'])
                reason=''
                if lead['email']!=job['recipient']: reason='Recipient changed'
                elif job['kind']=='recovery':
                    reason=protection(lead)
                    if lead['status']!='waiting': reason=reason or 'Lead has progressed'
                else:
                    appt=db.execute('SELECT * FROM appointments WHERE id=?',(job['appointment_id'],)).fetchone()
                    if not appt or appt['status']!='booked' or appt['starts_at']<=now() or appt['starts_at']!=job['appointment_starts_at']:
                        reason='Appointment changed or elapsed'
                    if lead['opted_out'] or not lead['consent'] or not lead['consent_note']: reason='Contact permission revoked'
                if reason:
                    status='cancelled'; error=reason; provider_id=''
                elif config['DEMO_MODE']:
                    status='simulated'; error=''; provider_id='DEMO-'+str(job['id'])
                elif not config['LIVE_SEND_ENABLED'] or not config.get('SMTP_HOST') or not config.get('SMTP_FROM'):
                    status='blocked'; error='Live SMTP delivery is disabled or unconfigured'; provider_id=''
                else:
                    try:
                        if lead['provider']=='highlevel':
                            remote=contact('highlevel',lead['external_id'],config)
                            if not remote['protection_verified'] or remote['opted_out'] or remote['email'].lower()!=job['recipient']:
                                if remote['opted_out']: db.execute('UPDATE leads SET opted_out=1 WHERE id=?',(lead['id'],))
                                else: db.execute('UPDATE leads SET consent=0 WHERE id=?',(lead['id'],))
                                raise ValueError('CRM protection changed; message blocked')
                        provider_id=(transport or send_mail)(config,job,lead)
                        status='sent'; error=''
                    except (smtplib.SMTPRecipientsRefused,smtplib.SMTPAuthenticationError,ValueError) as exc:
                        status='blocked'; error='Delivery rejected or CRM protection changed; review configuration and contact'; provider_id=''
                    except Exception:
                        # Even a connection error can happen after SMTP accepted DATA.
                        status='unknown'; error='Delivery outcome unknown; check SMTP records before sending again'; provider_id=''
                db.execute('UPDATE jobs SET status=?,error=?,provider_id=? WHERE id=?',(status,error,provider_id,job['id']))
                if status in ('blocked','cancelled') and job['kind']=='recovery':
                    db.execute("UPDATE leads SET status='ready' WHERE id=? AND status='waiting'",(lead['id'],))
                event(db,lead['id'],'Worker','message.'+status,'Job '+str(job['id'])+(': '+error if error else '; '+('SMTP accepted; delivery not confirmed' if status=='sent' else 'Demo only; nothing sent')))
                processed+=1
        return processed
    finally: db.close()
