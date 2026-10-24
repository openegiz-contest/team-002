#!/usr/bin/env python3
"""Integration smoke test against a *running* QazMine + OpenEgiz stack."""
import json
import sys
import time
from urllib.request import urlopen, Request

BASE='http://127.0.0.1:8765'

def get(path):
    with urlopen(BASE+path,timeout=30) as response:
        return json.load(response)

def post(path, body=None):
    req=Request(BASE+path, data=json.dumps(body or {}).encode(), method='POST',
                headers={'Content-Type':'application/json'})
    with urlopen(req,timeout=30) as response:
        return json.load(response)

def poll(check, seconds=30):
    start=time.monotonic()
    while time.monotonic()-start<seconds:
        x=get('/api/state')
        if check(x): return x
        time.sleep(2)
    raise RuntimeError('Ditto did not reflect expected state within 30 seconds')

try:
    print('1. Service:', get('/api/health'))
    s=get('/api/state')
    assert s['source']=='Eclipse Ditto REST API'
    assert len(s['twins'])>=13, 'not all Ditto twins exist'
    print('2. Read',len(s['twins']),'twins from Ditto')
    a=s['twins']['mine']['time_minutes']
    time.sleep(5)
    b=get('/api/state')['twins']['mine']['time_minutes']
    assert b>a, 'MQTT->Ditto state is not advancing'
    print('3. MQTT->Ditto time advanced:',a,'=>',b)
    print('4. Closing road via command API')
    post('/api/scenario', {'name':'road_closed','enabled':True})
    poll(lambda x:x['twins']['road-main']['state']=='closed')
    print('5. Ditto confirms road CLOSED')
    post('/api/scenario', {'name':'road_closed','enabled':False})
    poll(lambda x:x['twins']['road-main']['state']=='open')
    print('6. Ditto confirms road OPEN')
    r=get('/api/benchmark')
    assert all(k in r['results'] for k in ('basic','adaptive'))
    print('7. Deterministic benchmark:',r['results'])
    print('INTEGRATION PASS')
except Exception as exc:
    print('INTEGRATION FAILED:',exc,file=sys.stderr)
    sys.exit(1)
