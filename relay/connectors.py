"""Credential-gated, read-only CRM adapters. No credentials reach the client."""
import base64
import json
import re
from urllib.request import Request, urlopen
from urllib.error import URLError, HTTPError
from .service import ValidationError

def fetch(url, headers):
    try:
        with urlopen(Request(url,headers=headers),timeout=15) as response:
            return json.load(response)
    except HTTPError as exc:
        raise ValidationError('CRM request failed (HTTP '+str(exc.code)+'). Check credentials and contact access.')
    except (URLError,TimeoutError,ValueError):
        raise ValidationError('CRM could not be reached. No contact was imported.')

def contact(provider, external_id, config):
    if not isinstance(external_id,str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,120}',external_id):
        raise ValidationError('Enter a valid CRM contact ID.')
    if provider=='close':
        key=config.get('CLOSE_API_KEY')
        if not key: raise ValidationError('Close is not configured on the server.')
        auth=base64.b64encode((key+':').encode()).decode()
        row=fetch('https://api.close.com/api/v1/contact/'+external_id+'/',{'Authorization':'Basic '+auth})
        emails=row.get('emails',[])
        if not emails: raise ValidationError('This contact has no email address.')
        return {'name':row.get('name') or 'Unnamed contact','email':emails[0]['email'],
                'phone':(row.get('phones') or [{}])[0].get('phone',''),'source':'Close CRM',
                'context':'Imported from Close. Review CRM history and permissions before outreach.',
                'consent':False}
    if provider=='highlevel':
        key=config.get('HIGHLEVEL_TOKEN')
        location=config.get('HIGHLEVEL_LOCATION_ID')
        if not key or not location: raise ValidationError('HighLevel is not configured on the server.')
        row=fetch('https://services.leadconnectorhq.com/contacts/'+external_id,
                  {'Authorization':'Bearer '+key,'Version':'v3','Accept':'application/json'}).get('contact',{})
        if row.get('locationId')!=location: raise ValidationError('The contact belongs to another HighLevel location.')
        if not row.get('email'): raise ValidationError('This contact has no email address.')
        email_dnd=row.get('dndSettings',{}).get('Email',{}).get('status','').lower()
        return {'name':row.get('name') or ' '.join(filter(None,[row.get('firstName'),row.get('lastName')])) or 'Unnamed contact',
                'email':row['email'],'phone':row.get('phone',''),'source':'HighLevel',
                'owner':row.get('assignedTo') or '', 'opted_out':bool(row.get('dnd')) or email_dnd=='active',
                'protection_verified':isinstance(row.get('dnd'),bool),
                'context':'Imported from HighLevel. Review conversation history and permissions before outreach.',
                'consent':False}
    raise ValidationError('Unsupported CRM provider.')
