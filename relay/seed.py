from datetime import datetime, timezone, timedelta
from werkzeug.security import generate_password_hash
import secrets
from .db import now, transaction, event
from .service import create_lead

def seed(db):
    with transaction(db):
        db.execute('INSERT OR IGNORE INTO users(email,password_hash,name,created_at) VALUES (?,?,?,?)',
                   ('demo@relay.local',generate_password_hash(secrets.token_urlsafe(32),method='pbkdf2:sha256:600000'),'Demo operator',now()))
        if db.execute('SELECT 1 FROM leads LIMIT 1').fetchone(): return
        names=['Priya Shah','Marcus Reed','Elena Torres','James Walker','Aisha Bennett','Oliver Grant',
               'Nora Evans','Daniel Kim','Sofia Martin','Theo Brooks','Amelia Clark','Leo Patel',
               'Isabel Chen','Ethan Hughes','Maya Foster','Lucas Hayes','Zara Wilson','Noah Carter',
               'Chloe Lewis','Adam Scott','Freya Moore','Ben Collins','Lily Parker','Owen Adams','Grace Wright']
        for i,name in enumerate(names):
            lead=create_lead(db,{'name':name,'email':'lead'+str(i+1)+'@example.com',
                'source':['VSL opt-in','Webinar','Demo no-show'][i%3],'owner':['Alex','Jordan','Taylor'][i%3],
                'last_touch':(datetime.now(timezone.utc)-timedelta(days=[18,12,24,7,31,9][i%6])).isoformat(),
                'context':['Asked about onboarding. No response to the last follow-up.',
                           'Interested in the offer but asked to revisit after a busy month.',
                           'Missed the demo; no reschedule attempt is recorded.'][i%3],
                'consent':i!=24,'consent_note':'Fictional opt-in for the demo workspace' if i!=24 else '',
                'opted_out':i==21,'customer':i==22,'active':i==23,
                'cohort':'control' if i in (8,9,16,17) else 'treatment'},'Sample setup')
            if 10<=i<=20:
                status='waiting' if i<13 else 'booked' if i<16 else 'attended' if i<18 else 'collected'
                db.execute('UPDATE leads SET status=? WHERE id=?',(status,lead['id']))
                if i>=13:
                    appt_status='booked' if i<16 else 'attended'
                    starts=(datetime.now(timezone.utc)+timedelta(days=1) if i<16 else datetime.now(timezone.utc)-timedelta(days=2)).isoformat()
                    db.execute('INSERT INTO appointments(lead_id,starts_at,status,owner,created_at) VALUES (?,?,?,?,?)',
                               (lead['id'],starts,appt_status,lead['owner'],now()))
                if i>=18:
                    cents=[1200000,1500000,1000000][i-18]
                    cursor=db.execute("INSERT INTO payments(lead_id,reference,cents,kind,at,actor,note) VALUES (?,?,?,'settlement',?,'Sample setup','Fictional transaction')",
                                      (lead['id'],'SAMPLE-'+str(i),cents,now()))
                    if i==19:
                        db.execute("INSERT INTO payments(lead_id,reference,cents,kind,settlement_id,at,actor) VALUES (?,? ,200000,'refund',?,?,'Sample setup')",
                                   (lead['id'],'SAMPLE-REFUND',cursor.lastrowid,now()))
                event(db,lead['id'],'Sample setup','sample.history','Fictional pipeline history: '+status)
