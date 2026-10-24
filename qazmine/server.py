"""QazMine service.
Telemetry is sent by MQTT as Ditto Protocol modify commands.
Every live browser state request reads the actual Ditto state, not the simulation object.
"""
from contextlib import asynccontextmanager
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import json
import logging
import os
import threading
import time
import requests
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel
import paho.mqtt.client as mqtt
from model import Mine, NAMESPACE, ROADS, COORDS, benchmark
from setup_twins import definitions

logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(message)s')
LOG = logging.getLogger('qazmine')
DITTO = os.getenv('DITTO_URL', 'http://ditto-nginx:80').rstrip('/')
DITTO_AUTH = (os.getenv('DITTO_USER', 'ditto'), os.environ['DITTO_PASSWORD'])
MQTT_HOST = os.getenv('MQTT_HOST', 'mosquitto')
TICK = float(os.getenv('SIM_TICK_SECONDS', '1'))
STEP = float(os.getenv('SIM_STEP_SECONDS', '20'))
TWIN_NAMES = [name.split(':', 1)[1] for name, _ in definitions()]
WEB = Path(__file__).parent / 'web'
lock = threading.RLock()
engine = Mine()
stop = threading.Event()
thread = None
mqtt_client = None


def transmit(snapshot):
    for name, feats in snapshot.items():
        msg = {
            'topic': f'{NAMESPACE}/{name}/things/twin/commands/modify',
            'path': '/features',
            'value': {k: {'properties': v} for k, v in feats.items()}
        }
        info = mqtt_client.publish('telemetry/'+name, json.dumps(msg, ensure_ascii=False), qos=0)
        if info.rc != mqtt.MQTT_ERR_SUCCESS:
            LOG.warning('MQTT publish failure %s %s', name, info.rc)


def loop():
    while not stop.is_set():
        try:
            with lock:
                engine.step(STEP)
                engine.validate()
                snap = engine.snapshot()
            transmit(snap)
        except Exception:
            LOG.exception('simulation tick error')
        stop.wait(TICK)


def connect_mqtt():
    client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id='qazmine-flow')
    for i in range(45):
        try:
            client.connect(MQTT_HOST, int(os.getenv('MQTT_PORT', '1883')), keepalive=30)
            client.loop_start()
            return client
        except OSError as exc:
            LOG.warning('MQTT unavailable (%s); retry %s', exc, i+1)
            time.sleep(2)
    raise RuntimeError('MQTT not available')


@asynccontextmanager
async def lifespan(app):
    global thread, mqtt_client
    mqtt_client = connect_mqtt()
    thread = threading.Thread(target=loop, daemon=True)
    thread.start()
    yield
    stop.set()
    thread.join(timeout=5)
    mqtt_client.loop_stop()
    mqtt_client.disconnect()


app = FastAPI(title='QazMine Flow', lifespan=lifespan)


@app.get('/')
def index():
    return FileResponse(WEB/'index.html')

@app.get('/app.js')
def js():
    return FileResponse(WEB/'app.js', media_type='text/javascript')

@app.get('/style.css')
def css():
    return FileResponse(WEB/'style.css', media_type='text/css')

@app.get('/api/health')
def health():
    return {'status':'ok','mqtt_connected':bool(mqtt_client and mqtt_client.is_connected()),
            'data_source':'Eclipse Ditto'}


def get_one(name):
    url = f'{DITTO}/api/2/things/{NAMESPACE}:{name}'
    res = requests.get(url, auth=DITTO_AUTH, timeout=7)
    res.raise_for_status()
    raw = res.json()
    feats = raw.get('features', {})
    return name, {key: detail.get('properties', {}).get('value') for key, detail in feats.items()}


@app.get('/api/state')
def state():
    # Parallel Ditto reads; NEVER serve the current state directly from engine.
    try:
        with ThreadPoolExecutor(max_workers=8) as pool:
            result = dict(pool.map(get_one, TWIN_NAMES))
        return {'source':'Eclipse Ditto REST API', 'twins':result,
                'roads': {k:{'a':a,'b':b,'km':km} for k,(a,b,km) in ROADS.items()},
                'coords':COORDS}
    except Exception as exc:
        LOG.warning('Ditto state unavailable: %s', exc)
        raise HTTPException(status_code=503, detail='Cannot read current Eclipse Ditto twin state')


class Scenario(BaseModel):
    name: str
    enabled: bool


@app.post('/api/scenario')
def set_scenario(value:Scenario):
    with lock:
        try:
            engine.scenario(value.name, value.enabled)
            # publish immediately; operator will observe twin changes via Ditto
            transmit(engine.snapshot())
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc))
        return {'accepted':True, 'active':engine.active_scenarios()}


@app.post('/api/reset')
def reset():
    global engine
    with lock:
        engine = Mine(mode=engine.mode)
        transmit(engine.snapshot())
    return {'accepted':True}


@app.post('/api/mode/{mode}')
def mode(mode:str):
    global engine
    if mode not in ('basic','adaptive'):
        raise HTTPException(status_code=400, detail='Invalid dispatch mode')
    with lock:
        engine = Mine(mode=mode)
        transmit(engine.snapshot())
    return {'accepted':True, 'mode':mode}


@app.get('/api/benchmark')
def compare():
    # Offline deterministic comparison, expressly labeled as synthetic experiment.
    return {'hours':4, 'assumptions':'same starting fleet and site; synthetic data',
            'results': benchmark(4)}
