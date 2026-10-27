"""Isolated public walkthrough: reuse the product API with browser-held sample state.

There is no shared customer database. Each operation runs against a fresh temporary
SQLite database and returns business records only. No credentials or sessions are
serialized. This endpoint is deliberately unsuitable for real customer information.
"""
import io
import re
import sqlite3
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from flask import Flask, jsonify, request, send_from_directory
from .app import create_app, ROOT
from .db import connect, transaction

TABLES = ('leads', 'appointments', 'payments', 'events', 'jobs')
OPERATIONS = (
    ('GET', r'/workspace'), ('GET', r'/leads/\d+'), ('GET', r'/leads/export'),
    ('POST', r'/leads'), ('PATCH', r'/leads/\d+'), ('POST', r'/leads/import'),
    ('POST', r'/leads/\d+/(draft|schedule|book|payments)'),
    ('POST', r'/appointments/\d+'), ('POST', r'/appointments/\d+/reminder'),
    ('POST', r'/jobs/\d+/(cancel|reconcile)'), ('POST', r'/worker/demo-tick'),
)


def sample_history(db):
    """Make the fictional history useful to explore, with explicit sample evidence."""
    clock = datetime.now(timezone.utc)
    for index, row in enumerate(db.execute('SELECT id FROM payments ORDER BY id').fetchall()):
        at = (clock-timedelta(days=[21,13,4,7][index % 4])).isoformat(timespec='seconds')
        db.execute('UPDATE payments SET at=? WHERE id=?', (at,row['id']))
    # One elapsed booking and two future appointments demonstrate separate actions.
    for index, row in enumerate(db.execute('SELECT id FROM appointments WHERE status=\'booked\' ORDER BY id').fetchall()):
        at=(clock+timedelta(days=[-2,1,2][index % 3])).isoformat(timespec='seconds')
        db.execute('UPDATE appointments SET starts_at=? WHERE id=?',(at,row['id']))
    db.execute("UPDATE leads SET owner='' WHERE id=4")


def restore(db, state):
    if not isinstance(state,dict) or set(state) != set(TABLES):
        raise ValueError('Invalid sample workspace. Reset the demo to continue.')
    with transaction(db):
        for table in reversed(TABLES):
            db.execute('DELETE FROM '+table)
        for table in TABLES:
            rows=state[table]
            if not isinstance(rows,list) or len(rows)>400:
                raise ValueError('Sample workspace limit reached. Reset the demo to continue.')
            columns=[row['name'] for row in db.execute('PRAGMA table_info('+table+')')]
            for row in sorted(rows,key=lambda r:r.get('id',0) if isinstance(r,dict) else 0):
                if not isinstance(row,dict) or set(row)!=set(columns):
                    raise ValueError('Invalid sample record. Reset the demo to continue.')
                if any(not isinstance(v,(str,int,type(None))) or isinstance(v,str) and len(v)>12000 for v in row.values()):
                    raise ValueError('Sample record is too large or invalid.')
                db.execute('INSERT INTO '+table+' ('+','.join(columns)+') VALUES ('+','.join('?' for _ in columns)+')',
                           [row[column] for column in columns])


def create_preview_app():
    app=Flask(__name__,static_folder=str(ROOT/'static'),static_url_path='/static')
    app.config['MAX_CONTENT_LENGTH']=1024*1024

    @app.after_request
    def headers(response):
        response.headers['X-Content-Type-Options']='nosniff'
        response.headers['X-Frame-Options']='DENY'
        response.headers['Referrer-Policy']='same-origin'
        response.headers['X-Robots-Tag']='noindex, nofollow'
        response.headers['Content-Security-Policy']="default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'; base-uri 'self'; form-action 'self'"
        if request.path.startswith('/api/'):
            response.headers['Cache-Control']='no-store'
        return response

    @app.get('/')
    def home():
        return send_from_directory(ROOT/'static','index.html')

    @app.get('/health')
    def health():
        return jsonify(status='ok',mode='isolated-preview')

    @app.get('/api/auth/session')
    def session():
        return jsonify(user={'name':'Demo operator','email':'demo@relay.local'},csrf='',demo=True,preview=True)

    @app.post('/api/demo')
    def operation():
        payload=request.get_json(silent=True)
        if not isinstance(payload,dict):
            return jsonify(error='Send a sample operation.'),400
        method=payload.get('method','GET'); path=payload.get('path','')
        if not isinstance(path,str) or not any(method==verb and re.fullmatch(pattern,path) for verb,pattern in OPERATIONS):
            return jsonify(error='This action is unavailable in the public walkthrough.'),400
        with tempfile.TemporaryDirectory(prefix='relay-preview-') as directory:
            # Explicit overrides guarantee that this wrapper cannot reach live services.
            core=create_app({'DEMO_MODE':True,'DATABASE_PATH':str(Path(directory)/'sample.sqlite3'),
                'SECRET_KEY':'public-sample-workspace-not-an-authentication-boundary',
                'COOKIE_SECURE':False,'LIVE_SEND_ENABLED':False,
                **{key:'' for key in ('CLOSE_API_KEY','HIGHLEVEL_TOKEN','HIGHLEVEL_LOCATION_ID',
                                      'SMTP_HOST','SMTP_USERNAME','SMTP_PASSWORD','SMTP_FROM')}})
            db=connect(core.config['DATABASE_PATH'])
            try:
                if payload.get('state') is not None:
                    restore(db,payload['state'])
                else:
                    sample_history(db)
                client=core.test_client()
                auth=client.post('/api/auth/demo',headers={'X-Relay-Request':'1'}).get_json()
                kwargs={'headers':{'X-CSRF-Token':auth['csrf']}}
                body=payload.get('body')
                if path=='/leads/import':
                    if not isinstance(body,dict) or not isinstance(body.get('csv'),str) or len(body['csv'])>100000:
                        raise ValueError('Use a sample CSV below 100 KB.')
                    kwargs['data']={'file':(io.BytesIO(body['csv'].encode()),'sample.csv')}
                elif method!='GET':
                    if not isinstance(body,dict):
                        raise ValueError('Send a JSON object for the sample action.')
                    kwargs['json']=body
                response=client.open('/api'+path,method=method,**kwargs)
                result=response.get_json(silent=True) if response.is_json else {'csv':response.get_data(as_text=True)}
                state={table:[dict(row) for row in db.execute('SELECT * FROM '+table+' ORDER BY id')] for table in TABLES}
                return jsonify(result=result,state=state,status=response.status_code)
            except (ValueError,KeyError,TypeError,sqlite3.Error):
                return jsonify(error='The sample workspace could not be loaded. Reset the demo and try again.'),400
            finally:
                db.close()
    return app


app=create_preview_app()
