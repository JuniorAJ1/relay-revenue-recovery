import csv
import hashlib
import io
import os
import secrets
import sqlite3
from datetime import datetime, timezone, timedelta
from pathlib import Path
from functools import wraps
from dotenv import load_dotenv
from flask import Flask, request, jsonify, g, send_from_directory, make_response
from werkzeug.security import check_password_hash
from itsdangerous import URLSafeTimedSerializer, BadSignature, SignatureExpired
from .db import connect, init, transaction, now, event, record
from . import service, connectors

ROOT=Path(__file__).resolve().parent.parent

def create_app(overrides=None):
    load_dotenv(ROOT/'.env')
    app=Flask(__name__,static_folder=str(ROOT/'static'),static_url_path='/static')
    demo=os.getenv('DEMO_MODE','true').lower()=='true'
    app.config.update(DEMO_MODE=demo,DATABASE_PATH=os.getenv('DATABASE_PATH',str(ROOT/'instance/relay.sqlite3')),
        COOKIE_SECURE=os.getenv('COOKIE_SECURE','false').lower()=='true',MAX_CONTENT_LENGTH=2*1024*1024,
        LIVE_SEND_ENABLED=os.getenv('LIVE_SEND_ENABLED','false').lower()=='true',
        APP_BASE_URL=os.getenv('APP_BASE_URL','http://127.0.0.1:8766'),
        **{key:os.getenv(key,'') for key in ('SECRET_KEY','SMTP_HOST','SMTP_PORT','SMTP_USERNAME',
           'SMTP_PASSWORD','SMTP_FROM','CLOSE_API_KEY','HIGHLEVEL_TOKEN','HIGHLEVEL_LOCATION_ID')})
    if overrides: app.config.update(overrides)
    if not app.config['SECRET_KEY']:
        if not app.config['DEMO_MODE']: raise RuntimeError('Set SECRET_KEY for a live workspace.')
        secret_path=Path(app.config['DATABASE_PATH']).parent/'demo-secret'
        secret_path.parent.mkdir(parents=True,exist_ok=True)
        if not secret_path.exists():
            fd=os.open(secret_path,os.O_CREAT|os.O_EXCL|os.O_WRONLY,0o600)
            with os.fdopen(fd,'w') as out: out.write(secrets.token_urlsafe(48))
        app.config['SECRET_KEY']=secret_path.read_text()
    if not app.config['DEMO_MODE'] and not app.config['TESTING']:
        if len(app.config['SECRET_KEY'])<32 or app.config['SECRET_KEY'].startswith('replace-'):
            raise RuntimeError('Use a random SECRET_KEY of at least 32 characters.')
        if not app.config['COOKIE_SECURE'] or not app.config['APP_BASE_URL'].startswith('https://'):
            raise RuntimeError('Live mode requires COOKIE_SECURE=true and an HTTPS APP_BASE_URL.')
    init(app.config['DATABASE_PATH'],app.config['DEMO_MODE'])
    if app.config['DEMO_MODE']:
        from .seed import seed
        db=connect(app.config['DATABASE_PATH']); seed(db); db.close()

    @app.before_request
    def context():
        g.db=connect(app.config['DATABASE_PATH']); g.user=None; g.session=None
        token=request.cookies.get('relay_session','')
        if token:
            row=g.db.execute('''SELECT sessions.*,users.email,users.name FROM sessions JOIN users ON users.id=sessions.user_id
               WHERE token_hash=? AND expires_at>?''',(hashlib.sha256(token.encode()).hexdigest(),now())).fetchone()
            if row: g.user={'id':row['user_id'],'email':row['email'],'name':row['name']}; g.session=record(row)

    @app.teardown_request
    def close_db(exc):
        if hasattr(g,'db'): g.db.close()

    @app.after_request
    def headers(response):
        response.headers['X-Content-Type-Options']='nosniff'
        response.headers['Referrer-Policy']='same-origin'
        response.headers['X-Frame-Options']='DENY'
        response.headers['Content-Security-Policy']="default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'; base-uri 'self'; form-action 'self'"
        if request.path.startswith('/api/'): response.headers['Cache-Control']='no-store'
        return response

    def authenticated(fn):
        @wraps(fn)
        def wrapper(*args,**kwargs):
            if not g.user: return jsonify(error='Sign in to continue.'),401
            if request.method not in ('GET','HEAD'):
                supplied=request.headers.get('X-CSRF-Token','')
                if not secrets.compare_digest(supplied,g.session['csrf']): return jsonify(error='Session verification failed. Reload the page.'),403
            return fn(*args,**kwargs)
        return wrapper

    def payload():
        data=request.get_json(silent=True)
        if not isinstance(data,dict): raise service.ValidationError('Send a JSON object.')
        return data

    def new_session(user):
        token=secrets.token_urlsafe(32); csrf=secrets.token_urlsafe(24)
        old=request.cookies.get('relay_session','')
        with transaction(g.db):
            g.db.execute('DELETE FROM sessions WHERE expires_at<? OR token_hash=?',(now(),hashlib.sha256(old.encode()).hexdigest()))
            g.db.execute('INSERT INTO sessions VALUES (?,?,?,?)',(hashlib.sha256(token.encode()).hexdigest(),user['id'],csrf,
                        (datetime.now(timezone.utc)+timedelta(hours=12)).isoformat(timespec='seconds')))
        response=jsonify(user={'email':user['email'],'name':user['name']},csrf=csrf,demo=app.config['DEMO_MODE'])
        response.set_cookie('relay_session',token,httponly=True,secure=app.config['COOKIE_SECURE'],samesite='Strict',max_age=43200)
        return response

    @app.errorhandler(service.ValidationError)
    def invalid(exc): return jsonify(error=str(exc)),400
    @app.errorhandler(sqlite3.IntegrityError)
    def duplicate(exc): return jsonify(error='Duplicate email, transaction reference, or pending action. Refresh and review the existing record.'),409
    @app.errorhandler(413)
    def too_large(exc): return jsonify(error='Upload is too large. Maximum file size is 2 MB.'),413
    @app.errorhandler(500)
    def failure(exc): return jsonify(error='The request failed. Check the server log; your transaction was rolled back.'),500

    @app.get('/')
    def home(): return send_from_directory(ROOT/'static','index.html')
    @app.get('/health')
    def health(): return jsonify(status='ok',mode='demo' if app.config['DEMO_MODE'] else 'live')
    @app.get('/api/auth/session')
    def session(): return jsonify(user=g.user,csrf=g.session['csrf'] if g.session else '',demo=app.config['DEMO_MODE'])
    @app.post('/api/auth/demo')
    def demo_login():
        if not app.config['DEMO_MODE']: return jsonify(error='Demo login is disabled.'),404
        if request.headers.get('X-Relay-Request')!='1': return jsonify(error='Invalid request.'),403
        return new_session(g.db.execute("SELECT * FROM users WHERE email='demo@relay.local'").fetchone())
    @app.post('/api/auth/login')
    def login():
        if request.headers.get('X-Relay-Request')!='1': return jsonify(error='Invalid request.'),403
        data=payload(); address=service.email(data.get('email',''))
        fingerprint=hashlib.sha256((str(request.remote_addr)+'|'+address).encode()).hexdigest()
        with transaction(g.db):
            attempt=g.db.execute('SELECT * FROM login_attempts WHERE fingerprint=?',(fingerprint,)).fetchone()
            cutoff=(datetime.now(timezone.utc)-timedelta(minutes=15)).isoformat(timespec='seconds')
            if attempt and attempt['window_start']>cutoff and attempt['count']>=5:
                return jsonify(error='Too many attempts. Try again in 15 minutes.'),429
            if not attempt or attempt['window_start']<=cutoff:
                g.db.execute('INSERT OR REPLACE INTO login_attempts VALUES (?,0,?)',(fingerprint,now()))
            user=g.db.execute('SELECT * FROM users WHERE email=?',(address,)).fetchone()
            password=data.get('password','')
            if not isinstance(password,str) or len(password)>256 or not user or not check_password_hash(user['password_hash'],password):
                g.db.execute('UPDATE login_attempts SET count=count+1 WHERE fingerprint=?',(fingerprint,))
                return jsonify(error='Email or password is incorrect.'),401
            g.db.execute('DELETE FROM login_attempts WHERE fingerprint=?',(fingerprint,))
        return new_session(user)
    @app.post('/api/auth/logout')
    @authenticated
    def logout():
        g.db.execute('DELETE FROM sessions WHERE token_hash=?',(g.session['token_hash'],))
        response=jsonify(ok=True); response.delete_cookie('relay_session'); return response

    @app.get('/api/workspace')
    @authenticated
    def workspace():
        leads=[record(x) for x in g.db.execute('SELECT * FROM leads ORDER BY id')]
        payments=[record(x) for x in g.db.execute('SELECT * FROM payments ORDER BY id DESC')]
        for lead in leads:
            lead['reason']=service.protection(lead)
            lead['idle']=max(0,(datetime.now(timezone.utc)-datetime.fromisoformat(lead['last_touch'])).days)
            lead['gross']=sum(p['cents'] for p in payments if p['lead_id']==lead['id'] and p['kind']=='settlement')
            lead['refunds']=sum(p['cents'] for p in payments if p['lead_id']==lead['id'] and p['kind']=='refund')
        return jsonify(leads=leads,payments=payments,
          jobs=[record(x) for x in g.db.execute('SELECT * FROM jobs ORDER BY id DESC')],
          appointments=[record(x) for x in g.db.execute('SELECT * FROM appointments ORDER BY id DESC')],
          integrations={'close':bool(app.config['CLOSE_API_KEY']),
            'highlevel':bool(app.config['HIGHLEVEL_TOKEN'] and app.config['HIGHLEVEL_LOCATION_ID']),
            'smtp':bool(app.config['SMTP_HOST'] and app.config['SMTP_FROM']),
            'live_enabled':app.config['LIVE_SEND_ENABLED']},demo=app.config['DEMO_MODE'])
    @app.get('/api/leads/<int:lead_id>')
    @authenticated
    def detail(lead_id):
        return jsonify(lead=service.get_lead(g.db,lead_id),events=[record(x) for x in g.db.execute('SELECT * FROM events WHERE lead_id=? ORDER BY id DESC',(lead_id,))])
    @app.post('/api/leads')
    @authenticated
    def add_lead():
        with transaction(g.db): lead=service.create_lead(g.db,payload(),g.user['email'])
        return jsonify(lead=lead),201
    @app.patch('/api/leads/<int:lead_id>')
    @authenticated
    def edit_lead(lead_id):
        with transaction(g.db): lead=service.update_lead(g.db,lead_id,payload(),g.user['email'])
        return jsonify(lead=lead)
    @app.post('/api/leads/import')
    @authenticated
    def upload():
        file=request.files.get('file')
        if not file: raise service.ValidationError('Choose a CSV file.')
        with transaction(g.db): ids=service.import_csv(g.db,file.read(),g.user['email'])
        return jsonify(imported=len(ids)),201
    @app.get('/api/leads/export')
    @authenticated
    def export():
        buffer=io.StringIO(); writer=csv.writer(buffer)
        columns=['id','name','email','source','owner','status','cohort','consent','consent_note','opted_out','last_touch']
        writer.writerow(columns)
        for lead in g.db.execute('SELECT * FROM leads ORDER BY id'):
            # Neutralize spreadsheet formula injection in exported text.
            writer.writerow([("'"+str(lead[k]) if str(lead[k]).startswith(('=','+','-','@','\t','\r')) else lead[k]) for k in columns])
        response=make_response(buffer.getvalue()); response.headers['Content-Type']='text/csv; charset=utf-8'
        response.headers['Content-Disposition']='attachment; filename=relay-leads.csv'; return response
    @app.post('/api/leads/<int:lead_id>/draft')
    @authenticated
    def draft(lead_id):
        lead=service.get_lead(g.db,lead_id); service.eligible(lead)
        first=lead['name'].split()[0]
        body=f"Hi {first},\n\nYou previously expressed interest in speaking with our team. Is that still something you’re considering? Happy to answer your questions or help you find a time for a short call.\n\n{lead['owner'] or g.user['name']}\n\nReply unsubscribe if you would prefer no further emails."
        if 'no-show' in lead['source'].lower(): body=body.replace('You previously expressed interest in speaking with our team.','We missed you on the last call.')
        return jsonify(subject='A quick follow-up',body=body,engine='Contextual template')
    @app.post('/api/leads/<int:lead_id>/schedule')
    @authenticated
    def schedule(lead_id):
        with transaction(g.db): job=service.queue_recovery(g.db,lead_id,payload(),g.user['email'])
        return jsonify(job_id=job),201
    @app.post('/api/jobs/<int:job_id>/cancel')
    @authenticated
    def cancel(job_id):
        with transaction(g.db):
            job=g.db.execute('SELECT * FROM jobs WHERE id=?',(job_id,)).fetchone()
            if not job or job['status']!='queued': raise service.ValidationError('Only a queued job can be cancelled.')
            g.db.execute("UPDATE jobs SET status='cancelled' WHERE id=?",(job_id,))
            if job['kind']=='recovery': g.db.execute("UPDATE leads SET status='ready' WHERE id=? AND status='waiting'",(job['lead_id'],))
            event(g.db,job['lead_id'],g.user['email'],'message.cancelled','Job '+str(job_id))
        return jsonify(ok=True)
    @app.post('/api/worker/demo-tick')
    @authenticated
    def tick():
        if not app.config['DEMO_MODE']: return jsonify(error='Run the separate worker in live mode.'),403
        from .worker import run_once
        return jsonify(processed=run_once(app.config))
    @app.post('/api/jobs/<int:job_id>/reconcile')
    @authenticated
    def reconcile(job_id):
        data=payload()
        outcome=data.get('outcome')
        note=service.text(data.get('note',''),'Provider reconciliation evidence',1500,True)
        provider_id=service.text(data.get('provider_id',''),'Provider message reference',200)
        if outcome not in ('accepted','not_sent'): raise service.ValidationError('Choose accepted or confirmed not sent.')
        if outcome=='accepted' and not provider_id: raise service.ValidationError('Record the provider message reference.')
        with transaction(g.db):
            job=g.db.execute('SELECT * FROM jobs WHERE id=?',(job_id,)).fetchone()
            if not job or job['status']!='unknown': raise service.ValidationError('Only an unknown outcome can be reconciled.')
            status='sent' if outcome=='accepted' else 'blocked'
            g.db.execute('UPDATE jobs SET status=?,provider_id=?,error=? WHERE id=?',(status,provider_id,'Manually reconciled: '+note,job_id))
            if outcome=='not_sent' and job['kind']=='recovery':
                g.db.execute("UPDATE leads SET status='ready' WHERE id=? AND status='waiting'",(job['lead_id'],))
            event(g.db,job['lead_id'],g.user['email'],'message.reconciled','Job '+str(job_id)+'; '+outcome+'; reference: '+provider_id+'; evidence: '+note)
        return jsonify(ok=True)
    @app.post('/api/leads/<int:lead_id>/book')
    @authenticated
    def booking(lead_id):
        with transaction(g.db): id_=service.book(g.db,lead_id,payload(),g.user['email'])
        return jsonify(appointment_id=id_),201
    @app.post('/api/appointments/<int:appointment_id>')
    @authenticated
    def change_booking(appointment_id):
        with transaction(g.db): service.appointment_action(g.db,appointment_id,payload(),g.user['email'])
        return jsonify(ok=True)
    @app.post('/api/appointments/<int:appointment_id>/reminder')
    @authenticated
    def reminder(appointment_id):
        with transaction(g.db): service.queue_reminder(g.db,appointment_id,payload(),g.user['email'])
        return jsonify(ok=True),201
    @app.post('/api/leads/<int:lead_id>/payments')
    @authenticated
    def ledger(lead_id):
        with transaction(g.db): id_=service.payment(g.db,lead_id,payload(),g.user['email'])
        return jsonify(payment_id=id_),201
    @app.post('/api/integrations/import')
    @authenticated
    def crm_import():
        if app.config['DEMO_MODE']: raise service.ValidationError('Use a separate live workspace for real CRM data.')
        data=payload(); provider=data.get('provider'); external_id=data.get('external_id')
        row=connectors.contact(provider,external_id,app.config)
        with transaction(g.db): lead=service.create_lead(g.db,row,g.user['email'],provider,external_id)
        return jsonify(lead=lead),201

    @app.route('/unsubscribe/<token>',methods=['GET','POST'])
    def unsubscribe(token):
        try: lead_id=URLSafeTimedSerializer(app.config['SECRET_KEY'],salt='relay-unsubscribe').loads(token,max_age=7776000)
        except (BadSignature,SignatureExpired): return 'This link is invalid or expired. Please contact the sender.',400
        lead=service.get_lead(g.db,lead_id)
        if request.method=='GET':
            return '<!doctype html><title>Unsubscribe · Relay</title><h1>Stop follow-up emails</h1><p>Confirm to stop recovery and reminder emails from this workspace.</p><form method="post"><button>Unsubscribe</button></form>'
        with transaction(g.db):
            service.update_lead(g.db,lead_id,{'opted_out':True},'Recipient unsubscribe link')
        return '<!doctype html><title>Unsubscribed</title><h1>You’re unsubscribed.</h1><p>Your preference has been saved.</p>'
    return app
