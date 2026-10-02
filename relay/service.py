"""Business rules shared by HTTP handlers and the delivery worker."""
import csv
import io
import re
import secrets
import json
from datetime import datetime, timezone, timedelta
from decimal import Decimal, InvalidOperation
from .db import now, event, transaction, record

class ValidationError(ValueError):
    pass

def text(value, label, limit=2000, required=False):
    if not isinstance(value, str):
        raise ValidationError(label + ' must be text.')
    value = value.strip()
    if len(value) > limit or (required and not value):
        raise ValidationError(label + ' is missing or too long.')
    return value

def email(value):
    value = text(value, 'Email', 254, True).lower()
    if not re.fullmatch(r'[a-z0-9._%+\-]+@[a-z0-9](?:[a-z0-9\-]*[a-z0-9])?(?:\.[a-z0-9](?:[a-z0-9\-]*[a-z0-9])?)+', value):
        raise ValidationError('Enter a valid email address.')
    return value

def timestamp(value, future=False):
    try:
        dt = datetime.fromisoformat(str(value).replace('Z','+00:00'))
        if dt.tzinfo is None:
            raise ValueError()
        dt = dt.astimezone(timezone.utc)
        if future and dt < datetime.now(timezone.utc) - timedelta(seconds=5):
            raise ValueError()
        return dt.isoformat(timespec='seconds')
    except (TypeError, ValueError):
        raise ValidationError('Use a valid time with a timezone; scheduled times cannot be in the past.')

def flag(value):
    if value not in (True, False, 0, 1):
        raise ValidationError('Use true or false for permission and protection fields.')
    return int(bool(value))

def amount(value):
    try:
        value = Decimal(str(value))
        if not value.is_finite() or value <= 0 or value > 1000000 or value.as_tuple().exponent < -2:
            raise InvalidOperation()
        return int(value * 100)
    except (InvalidOperation, ValueError, TypeError):
        raise ValidationError('Enter an amount between 0.01 and 1,000,000 with at most two decimal places.')

def get_lead(db, lead_id):
    lead = record(db.execute('SELECT * FROM leads WHERE id=?',(lead_id,)).fetchone())
    if not lead:
        raise ValidationError('Lead not found.')
    return lead

def protection(lead):
    if lead['opted_out']: return 'Opted out'
    if lead['customer']: return 'Existing customer'
    if lead['active']: return 'Active conversation'
    if not lead['consent'] or not lead['consent_note']: return 'Permission needs evidence'
    if lead['cohort'] == 'control': return 'Control group'
    return ''

def eligible(lead):
    reason = protection(lead)
    if reason: raise ValidationError(reason + ' — outreach is blocked.')
    if lead['status'] != 'ready':
        raise ValidationError('Only a ready lead can enter recovery outreach.')
    age = datetime.now(timezone.utc) - datetime.fromisoformat(lead['last_touch'])
    if age < timedelta(days=7):
        raise ValidationError('Recovery outreach requires at least 7 days since the last touch.')

def create_lead(db, data, actor, provider='', external_id=''):
    name = text(data.get('name',''), 'Name', 120, True)
    address = email(data.get('email',''))
    consent = flag(data.get('consent',False))
    evidence = text(data.get('consent_note',''), 'Permission evidence', 1000)
    if consent and not evidence:
        raise ValidationError('Record the source and date of contact permission.')
    cohort = data.get('cohort') or ('control' if secrets.randbelow(5)==0 else 'treatment')
    if cohort not in ('treatment','control'): raise ValidationError('Invalid cohort.')
    # Blank external IDs must not collide; every manual record has its own key.
    external_id = external_id or secrets.token_hex(12)
    cursor = db.execute('''INSERT INTO leads(name,email,phone,source,owner,context,last_touch,
      consent,consent_note,opted_out,customer,active,cohort,created_at,provider,external_id)
      VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)''',
      (name,address,text(data.get('phone',''),'Phone',40),text(data.get('source','Manual'),'Source',120),
       text(data.get('owner',''),'Owner',120),text(data.get('context',''),'Context',3000),
       timestamp(data.get('last_touch',now())),consent,evidence,flag(data.get('opted_out',False)),
       flag(data.get('customer',False)),flag(data.get('active',False)),cohort,now(),provider,external_id))
    event(db,cursor.lastrowid,actor,'lead.created','Lead created; cohort: '+cohort)
    return get_lead(db,cursor.lastrowid)

def update_lead(db, lead_id, data, actor):
    lead = get_lead(db,lead_id)
    allowed = {'name':120,'email':254,'phone':40,'source':120,'owner':120,'context':3000,'consent_note':1000}
    changes = {}
    for key, limit in allowed.items():
        if key in data: changes[key] = email(data[key]) if key=='email' else text(data[key],key,limit,key=='name')
    for key in ('consent','opted_out','customer','active'):
        if key in data: changes[key] = flag(data[key])
    if 'last_touch' in data: changes['last_touch']=timestamp(data['last_touch'])
    proposed = dict(lead, **changes)
    if proposed['consent'] and not proposed['consent_note']:
        raise ValidationError('Contact permission requires recorded evidence.')
    if changes:
        db.execute('UPDATE leads SET '+','.join(k+'=?' for k in changes)+' WHERE id=?',(*changes.values(),lead_id))
        # Changes invalidate approvals, including recipient and ownership changes.
        db.execute("UPDATE jobs SET status='cancelled',error='Lead changed; review required' WHERE lead_id=? AND status='queued'",(lead_id,))
        if lead['status']=='waiting' and not db.execute("SELECT 1 FROM jobs WHERE lead_id=? AND status IN ('sending','sent','simulated','unknown')",(lead_id,)).fetchone():
            db.execute("UPDATE leads SET status='ready' WHERE id=?",(lead_id,))
        event(db,lead_id,actor,'lead.updated',json.dumps({k:{'before':lead[k],'after':v} for k,v in changes.items()},ensure_ascii=False))
    return get_lead(db,lead_id)

def queue_recovery(db, lead_id, data, actor):
    lead = get_lead(db,lead_id)
    eligible(lead)
    subject = text(data.get('subject',''),'Subject',200,True)
    if '\n' in subject or '\r' in subject: raise ValidationError('Subject must be one line.')
    body = text(data.get('body',''),'Message',6000,True)
    if 'unsubscribe' not in body.lower():
        raise ValidationError('Include an unsubscribe instruction in the message.')
    due = timestamp(data.get('due_at',now()),future=True)
    cursor = db.execute('''INSERT INTO jobs(lead_id,subject,body,recipient,due_at,created_at,approved_by)
      VALUES (?,?,?,?,?,?,?)''',(lead_id,subject,body,lead['email'],due,now(),actor))
    db.execute("UPDATE leads SET status='waiting' WHERE id=?",(lead_id,))
    event(db,lead_id,actor,'message.approved','Email approved; job '+str(cursor.lastrowid)+' scheduled for '+due)
    return cursor.lastrowid

def book(db, lead_id, data, actor):
    lead=get_lead(db,lead_id)
    if lead['status'] not in ('ready','waiting'): raise ValidationError('This lead already has an outcome. Review the appointment first.')
    starts=timestamp(data.get('starts_at',''),future=True)
    owner=text(data.get('owner',lead['owner']),'Appointment owner',120,True)
    cursor=db.execute('INSERT INTO appointments(lead_id,starts_at,owner,created_at) VALUES (?,?,?,?)',(lead_id,starts,owner,now()))
    db.execute("UPDATE jobs SET status='cancelled',error='Appointment booked' WHERE lead_id=? AND status='queued'",(lead_id,))
    db.execute("UPDATE leads SET status='booked',active=1 WHERE id=?",(lead_id,))
    event(db,lead_id,actor,'appointment.booked','Appointment '+str(cursor.lastrowid)+' at '+starts+'; owner: '+owner)
    return cursor.lastrowid

def appointment_action(db, appointment_id, data, actor):
    appt=record(db.execute('SELECT * FROM appointments WHERE id=?',(appointment_id,)).fetchone())
    if not appt or appt['status']!='booked': raise ValidationError('Only a booked appointment can be changed.')
    action=data.get('action')
    if action=='reschedule':
        starts=timestamp(data.get('starts_at',''),future=True)
        db.execute('UPDATE appointments SET starts_at=? WHERE id=?',(starts,appointment_id))
        detail='Rescheduled to '+starts
    elif action in ('cancel','attend','no_show'):
        status={'cancel':'cancelled','attend':'attended','no_show':'no_show'}[action]
        db.execute('UPDATE appointments SET status=? WHERE id=?',(status,appointment_id))
        db.execute('UPDATE leads SET status=?,active=? WHERE id=?',('attended' if action=='attend' else 'ready',int(action=='attend'),appt['lead_id']))
        detail=status
    else: raise ValidationError('Invalid appointment action.')
    db.execute("UPDATE jobs SET status='cancelled',error='Appointment changed' WHERE appointment_id=? AND status='queued'",(appointment_id,))
    event(db,appt['lead_id'],actor,'appointment.'+action,detail+'; old reminders cancelled')

def queue_reminder(db, appointment_id, data, actor):
    appt=record(db.execute('SELECT * FROM appointments WHERE id=?',(appointment_id,)).fetchone())
    if not appt or appt['status']!='booked': raise ValidationError('Appointment is no longer booked.')
    lead=get_lead(db,appt['lead_id'])
    if lead['opted_out'] or not lead['consent'] or not lead['consent_note']:
        raise ValidationError('Permission is required for a reminder.')
    due=timestamp(data.get('due_at',''),future=True)
    if due>=appt['starts_at']: raise ValidationError('Schedule the reminder before the appointment.')
    subject=text(data.get('subject','Your upcoming call'),'Subject',200,True)
    if '\n' in subject or '\r' in subject: raise ValidationError('Subject must be one line.')
    body=text(data.get('body',''),'Message',6000,True)
    if 'unsubscribe' not in body.lower(): raise ValidationError('Include an unsubscribe instruction.')
    if db.execute("SELECT 1 FROM jobs WHERE appointment_id=? AND status IN ('queued','sending','unknown')",(appointment_id,)).fetchone():
        raise ValidationError('This appointment already has a pending reminder.')
    db.execute('''INSERT INTO jobs(lead_id,subject,body,recipient,due_at,created_at,approved_by,kind,appointment_id,appointment_starts_at)
      VALUES (?,?,?,?,?,?,?,'reminder',?,?)''',(lead['id'],subject,body,lead['email'],due,now(),actor,appointment_id,appt['starts_at']))
    event(db,lead['id'],actor,'reminder.approved','Reviewed appointment reminder scheduled for '+due)

def payment(db, lead_id, data, actor):
    lead=get_lead(db,lead_id)
    cents=amount(data.get('amount'))
    reference=text(data.get('reference',''),'Transaction reference',160,True)
    kind=data.get('kind','settlement')
    parent=None
    if kind=='settlement':
        if lead['status'] not in ('attended','collected'): raise ValidationError('Record attendance before a settlement.')
    elif kind=='refund':
        parent=data.get('settlement_id')
        settlement=db.execute("SELECT * FROM payments WHERE id=? AND lead_id=? AND kind='settlement'",(parent,lead_id)).fetchone()
        if not settlement: raise ValidationError('Select the original settlement.')
        refunded=db.execute("SELECT COALESCE(SUM(cents),0) FROM payments WHERE settlement_id=? AND kind='refund'",(parent,)).fetchone()[0]
        if cents>settlement['cents']-refunded: raise ValidationError('Refund exceeds the unrefunded settlement balance.')
    else: raise ValidationError('Invalid transaction type.')
    cursor=db.execute('INSERT INTO payments(lead_id,reference,cents,kind,settlement_id,at,actor,note) VALUES (?,?,?,?,?,?,?,?)',
      (lead_id,reference,cents,kind,parent,now(),actor,text(data.get('note',''),'Evidence note',1500)))
    if kind=='settlement': db.execute("UPDATE leads SET status='collected',customer=1 WHERE id=?",(lead_id,))
    event(db,lead_id,actor,'payment.'+kind,reference+'; USD '+str(Decimal(cents)/100)+' (manually reconciled)')
    return cursor.lastrowid

def import_csv(db, content, actor):
    try:
        reader=csv.DictReader(io.StringIO(content.decode('utf-8-sig')))
        if not reader.fieldnames or not {'name','email'}.issubset(reader.fieldnames):
            raise ValidationError('CSV must contain name and email columns.')
        rows=list(reader)
    except (UnicodeError,csv.Error): raise ValidationError('Upload a UTF-8 CSV file.')
    if not 1<=len(rows)<=1000: raise ValidationError('Import between 1 and 1,000 rows at a time.')
    imported=[]
    for i,row in enumerate(rows,2):
        for key in ('consent','opted_out','customer','active'):
            raw=(row.get(key) or '').strip().lower()
            if raw not in ('','false','true','0','1'): raise ValidationError('Invalid boolean in CSV row '+str(i))
            row[key]=raw in ('true','1')
        if not row.get('last_touch'): row['last_touch']=now()
        if not row.get('cohort'): row.pop('cohort',None)
        try: imported.append(create_lead(db,row,actor)['id'])
        except ValidationError as exc: raise ValidationError('CSV row '+str(i)+': '+str(exc))
    return imported
