import argparse
import getpass
import time
from werkzeug.security import generate_password_hash
from relay.app import create_app
from relay.db import connect, now
from relay.service import email, ValidationError
from relay.worker import run_once

def main():
    parser=argparse.ArgumentParser(description='Run and administer Relay.')
    commands=parser.add_subparsers(dest='command',required=True)
    server=commands.add_parser('serve'); server.add_argument('--port',type=int,default=8766)
    admin=commands.add_parser('create-user'); admin.add_argument('--email',required=True); admin.add_argument('--name',required=True)
    worker=commands.add_parser('worker'); worker.add_argument('--once',action='store_true')
    args=parser.parse_args(); app=create_app()
    if args.command=='serve': app.run(host='127.0.0.1',port=args.port,debug=False)
    elif args.command=='create-user':
        address=email(args.email); password=getpass.getpass('New password (at least 12 characters): ')
        if len(password)<12 or len(password)>256: raise ValidationError('Use a password of 12–256 characters.')
        if password!=getpass.getpass('Confirm password: '): raise ValidationError('Passwords do not match.')
        db=connect(app.config['DATABASE_PATH'])
        try:
            db.execute('INSERT INTO users(email,password_hash,name,created_at) VALUES (?,?,?,?)',
                       (address,generate_password_hash(password,method='pbkdf2:sha256:600000'),args.name[:120],now()))
        finally: db.close()
        print('User created:',address)
    else:
        print('Worker running in', 'demo mode' if app.config['DEMO_MODE'] else 'live mode',flush=True)
        try:
            while True:
                count=run_once(app.config)
                if count: print('Processed',count,'jobs',flush=True)
                if args.once: break
                time.sleep(5)
        except KeyboardInterrupt: pass

if __name__=='__main__': main()
