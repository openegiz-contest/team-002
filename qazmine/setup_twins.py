"""Create QazMine twins in Eclipse Ditto, parent before children (idempotent)."""
import base64
import json
import os
import sys
import time
import urllib.error
import urllib.request
from model import Mine, NAMESPACE, ROADS, COORDS, GRADE

URL = os.getenv('DITTO_URL', 'http://localhost:8080').rstrip('/')
PASS = os.environ.get('DITTO_PASSWORD')
USER = os.getenv('DITTO_USER', 'ditto')


def definitions():
    snap = Mine().snapshot()
    objs = []
    def add(name, label, kind, parent=None, **attributes):
        attrs = {'name': label, 'kind': kind, '_isType': False, 'contest': 'qazmine', **attributes}
        if parent:
            attrs['_parents'] = f'{NAMESPACE}:{parent}'
        body = {'policyId': 'default:basic_policy', 'attributes': attrs,
                'features': {k: {'properties': v} for k, v in snap[name].items()}}
        objs.append((f'{NAMESPACE}:{name}', body))
    add('mine', 'QazMine copper open pit', 'mine', origin='synthetic')
    for f in ('a', 'b'):
        x,y = COORDS[f.upper()]
        add(f'face-{f}', f'Ore face {f.upper()}', 'ore-face', 'mine', x=x, y=y,
            grade_cu_pct=GRADE[f.upper()])
        add(f'exc-{f}', f'Excavator EX-{f.upper()}', 'excavator', f'face-{f}')
    for road, (a,b,km) in ROADS.items():
        add(road, road.replace('-', ' ').upper(), 'road', 'mine', start=a, end=b, length_km=km)
    add('crusher', 'Primary crusher CR-01', 'crusher', 'mine', x=COORDS['C'][0], y=COORDS['C'][1])
    for idx in range(1, 4):
        add(f'haul-{idx:02d}', f'Haul Truck HT-{idx:02d}', 'haul-truck', 'mine', capacity_t=80)
    return objs


def run():
    if not PASS:
        raise RuntimeError('Missing DITTO_PASSWORD environment variable')
    auth = 'Basic ' + base64.b64encode(f'{USER}:{PASS}'.encode()).decode()
    for name, body in definitions():
        for i in range(30):
            try:
                req = urllib.request.Request(f'{URL}/api/2/things/{name}',
                     data=json.dumps(body).encode('utf8'), method='PUT',
                     headers={'Authorization': auth, 'Content-Type':'application/json'})
                with urllib.request.urlopen(req, timeout=15) as res:
                    print('ditto:', res.status, name, flush=True)
                break
            except (urllib.error.URLError, TimeoutError) as exc:
                if i == 29:
                    print(f'ERROR creating {name}: {exc}', file=sys.stderr)
                    return 1
                time.sleep(3)
    print(f'{len(definitions())} QazMine twins created/updated', flush=True)
    return 0

if __name__ == '__main__':
    sys.exit(run())
