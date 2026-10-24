"""QazMine Flow: deterministic, discrete-time open-pit haulage and ore blending.
All numerical values are *synthetic engineering assumptions*, not measured field data.
"""
from __future__ import annotations
from dataclasses import dataclass, field
from collections import deque
import heapq
import math

NAMESPACE = 'org.qazmine.flow'
COORDS = {'A': (126, 180), 'B': (126, 385), 'J': (402, 275),
          'C': (685, 210), 'D': (588, 442)}
# Distances in km chosen independently from image coordinates; synthetic site.
ROADS = {
    'road-a': ('A', 'J', 1.45),
    'road-b': ('B', 'J', 1.75),
    'road-main': ('J', 'C', 1.20),
    'road-detour-1': ('J', 'D', 1.35),
    'road-detour-2': ('D', 'C', 1.55),
}
GRADE = {'A': 0.45, 'B': 1.10}  # percent Cu by mass
FACE_CAP_T = {'A': 12000.0, 'B': 10000.0}
CAPACITY_T = 80.0
LOAD_RATE_TPH = 600.0  # each excavator, equivalent 80 t in 480 s
CRUSHER_RATE_TPH = 450.0
SPEED_EMPTY = 30.0
SPEED_LOADED = 21.0
TARGET_GRADE = 0.78


def route(start: str, end: str, closed: set[str]):
    """Shortest available path; returns sequence of (road_id, next_node)."""
    adj = {node: [] for node in COORDS}
    for name, (a, b, km) in ROADS.items():
        if name not in closed:
            adj[a].append((b, name, km))
            adj[b].append((a, name, km))
    frontier = [(0.0, start, [])]
    found = set()
    while frontier:
        length, node, path = heapq.heappop(frontier)
        if node == end:
            return path
        if node in found:
            continue
        found.add(node)
        for target, road_name, km in adj[node]:
            if target not in found:
                heapq.heappush(frontier, (length + km, target, path + [(road_name, target)]))
    return None


def path_length(path):
    return sum(ROADS[r][2] for r, _ in (path or []))


def weighted_grade(pairs):
    mass = sum(m for m, _ in pairs)
    return (sum(m*g for m, g in pairs)/mass) if mass else 0.0


@dataclass
class Truck:
    id: str
    node: str = 'C'
    state: str = 'idle'
    dest: str = ''
    assigned: str = ''
    road: str = ''
    next_node: str = ''
    progress_km: float = 0.0
    payload_t: float = 0.0
    grade: float = 0.0
    fuel_pct: float = 100.0
    trips: int = 0
    waiting_s: float = 0.0
    timer_s: float = 0.0
    speed_kmh: float = 0.0
    x: float = 0.0
    y: float = 0.0
    def __post_init__(self):
        self.x, self.y = COORDS[self.node]


class Mine:
    def __init__(self, mode='adaptive'):
        if mode not in ('adaptive', 'basic'):
            raise ValueError('mode must be adaptive or basic')
        self.mode = mode
        self.time_s = 0.0
        self.closed = set()
        self.broken = set()
        self.crusher_factor = 1.0
        self.trucks = [Truck(f'haul-{i:02d}', node='C') for i in range(1, 4)]
        self.faces = dict(FACE_CAP_T)
        self.exc_busy = {'A': None, 'B': None}
        self.crusher_busy = None
        self.ore_mined_t = 0.0
        self.delivered_t = 0.0
        self.cu_grade_t = 0.0
        self.history = deque()
        self.events = deque(maxlen=25)
        self._log('Digital mine initialized')

    def _log(self, what):
        self.events.appendleft({'time_min': round(self.time_s/60, 1), 'text': what})

    def scenario(self, which, enabled):
        if which == 'road_closed':
            if enabled: self.closed.add('road-main')
            else: self.closed.discard('road-main')
        elif which == 'excavator_failure':
            if enabled: self.broken.add('B')
            else: self.broken.discard('B')
        elif which == 'crusher_reduced':
            self.crusher_factor = 0.5 if enabled else 1.0
        else:
            raise ValueError('unknown scenario')
        self._log(f'{which}: {"ON" if enabled else "OFF"}')

    def _choose_face(self, truck):
        candidates = [f for f in GRADE if self.faces[f] >= CAPACITY_T and f not in self.broken]
        if not candidates:
            return None
        if self.mode == 'basic':
            # Fixed rule: preferred low-grade face. No blending/queue optimization.
            return 'A' if 'A' in candidates else candidates[0]
        # Predict blended grade from physical, mass-weighted ore already fed.
        # Encourage approaching target AND avoiding queue/long path; deterministic.
        def score(face):
            predicted = weighted_grade([(self.delivered_t, self.feed_grade), (CAPACITY_T, GRADE[face])])
            grade_penalty = abs(predicted - TARGET_GRADE) * 220.0
            queue = sum(t.state in ('loading', 'waiting_load') and t.assigned == face for t in self.trucks)
            distance = path_length(route(truck.node, face, self.closed))
            if math.isinf(distance): return math.inf
            return grade_penalty + queue*3.0 + distance*1.5
        candidates = [f for f in candidates if route(truck.node, f, self.closed) is not None]
        return min(candidates, key=score) if candidates else None

    @property
    def feed_grade(self):
        return self.cu_grade_t / self.delivered_t if self.delivered_t else 0.0

    def _drive(self, t: Truck, dt):
        speed = SPEED_LOADED if t.state == 'hauling' else SPEED_EMPTY
        remaining = speed * dt / 3600.0
        t.speed_kmh = 0.0
        while remaining > 1e-9:
            if not t.road:
                if t.node == t.dest:
                    return True
                options = route(t.node, t.dest, self.closed)
                if not options:
                    return False
                t.road, t.next_node = options[0]
                t.progress_km = 0.0
            if t.road in self.closed:
                # No teleportation. Vehicle stops where it is until road reopened.
                return False
            a, b, km = ROADS[t.road]
            d = min(remaining, km - t.progress_km)
            t.progress_km += d
            remaining -= d
            t.fuel_pct = max(0.0, t.fuel_pct - d*(0.78 if t.state == 'hauling' else 0.48))
            t.speed_kmh = speed
            start = b if t.next_node == a else a
            ratio = min(1.0, t.progress_km/km)
            ax, ay = COORDS[start]
            bx, by = COORDS[t.next_node]
            t.x = ax + ratio * (bx-ax)
            t.y = ay + ratio * (by-ay)
            if t.progress_km + 1e-9 >= km:
                t.node = t.next_node
                t.road = ''
                t.next_node = ''
                t.progress_km = 0.0
                if t.node == t.dest:
                    return True
            else:
                break
        return t.node == t.dest and not t.road

    def step(self, dt=20.0):
        assert 0 < dt <= 60
        self.time_s += dt
        for t in self.trucks:
            if t.state == 'idle':
                choice = self._choose_face(t)
                if choice is not None:
                    t.assigned = choice
                    t.dest = choice
                    t.state = 'travel_to_face'
                    self._log(f'{t.id} assigned to face {choice}')
            if t.state == 'travel_to_face':
                if self._drive(t, dt):
                    t.state = 'waiting_load'
                    t.speed_kmh = 0
            elif t.state == 'waiting_load':
                t.waiting_s += dt
                t.speed_kmh = 0
                if t.assigned not in self.broken and self.exc_busy[t.assigned] is None:
                    self.exc_busy[t.assigned] = t.id
                    t.timer_s = 0
                    t.state = 'loading'
            elif t.state == 'loading':
                t.speed_kmh = 0
                # Breakdown freezes loading without losing ore or truck location.
                if t.assigned not in self.broken:
                    t.timer_s += dt
                    if t.timer_s >= CAPACITY_T / LOAD_RATE_TPH * 3600:
                        face = t.assigned
                        if self.faces[face] >= CAPACITY_T:
                            self.faces[face] -= CAPACITY_T
                            self.ore_mined_t += CAPACITY_T
                            t.payload_t = CAPACITY_T
                            t.grade = GRADE[face]
                            t.state = 'hauling'
                            t.dest = 'C'
                            t.timer_s = 0
                            self.exc_busy[face] = None
                        else:
                            self.exc_busy[face] = None
                            t.state = 'idle'
            elif t.state == 'hauling':
                if self._drive(t, dt):
                    t.state = 'waiting_crusher'
                    t.speed_kmh = 0
            elif t.state == 'waiting_crusher':
                t.waiting_s += dt
                t.speed_kmh = 0
                if self.crusher_busy is None:
                    self.crusher_busy = t.id
                    t.timer_s = 0
                    t.state = 'dumping'
            elif t.state == 'dumping':
                t.speed_kmh = 0
                t.timer_s += dt
                unloading_s = t.payload_t / (CRUSHER_RATE_TPH * self.crusher_factor) * 3600
                if t.timer_s >= unloading_s:
                    self.delivered_t += t.payload_t
                    self.cu_grade_t += t.payload_t * t.grade
                    self.history.append((self.time_s, t.payload_t))
                    t.payload_t = 0
                    t.grade = 0
                    t.trips += 1
                    t.timer_s = 0
                    self.crusher_busy = None
                    t.state = 'idle'
        while self.history and self.history[0][0] < self.time_s - 3600:
            self.history.popleft()

    def snapshot(self):
        window_s = max(1.0, min(self.time_s, 3600))
        throughput = sum(m for _, m in self.history)*3600/window_s
        state = {
            'mine': {
                'time_minutes': (self.time_s/60, 'min'),
                'ore_mined': (self.ore_mined_t, 't'),
                'ore_delivered': (self.delivered_t, 't'),
                'feed_grade': (self.feed_grade, '% Cu'),
                'target_grade': (TARGET_GRADE, '% Cu'),
                'average_wait': (sum(t.waiting_s for t in self.trucks)/60/len(self.trucks), 'min'),
                'mode': (self.mode, ''),
                'scenarios': (','.join(self.active_scenarios()), ''),
            },
            'crusher': {
                'state': ('unloading' if self.crusher_busy else 'idle', ''),
                'throughput': (throughput, 't/h'),
                'rated_capacity': (CRUSHER_RATE_TPH*self.crusher_factor, 't/h'),
                'queue': (sum(t.state == 'waiting_crusher' for t in self.trucks), 'trucks'),
                'tonnes_total': (self.delivered_t, 't'),
            },
        }
        for face in ('A', 'B'):
            state[f'face-{face.lower()}'] = {
                'ore_remaining': (self.faces[face], 't'),
                'grade': (GRADE[face], '% Cu'),
            }
            state[f'exc-{face.lower()}'] = {
                'state': ('maintenance' if face in self.broken else 'loading' if self.exc_busy[face] else 'idle', ''),
                'truck': (self.exc_busy[face] or '-', ''),
                'bucket_rate': (LOAD_RATE_TPH, 't/h'),
            }
        for road in ROADS:
            state[road] = {
                'state': ('closed' if road in self.closed else 'open', ''),
                'length': (ROADS[road][2], 'km'),
            }
        for t in self.trucks:
            state[t.id] = {
                'state': (t.state, ''), 'assigned_face': (t.assigned or '-', ''),
                'road': (t.road or '-', ''), 'x': (t.x, 'map-x'), 'y': (t.y, 'map-y'),
                'speed': (t.speed_kmh, 'km/h'), 'payload': (t.payload_t, 't'),
                'grade': (t.grade, '% Cu'), 'fuel': (t.fuel_pct, '%'),
                'trips': (t.trips, 'trips'), 'wait': (t.waiting_s/60, 'min'),
            }
        return {name: {k: {'value': round(v, 3) if isinstance(v, float) else v, 'unit': unit}
                       for k, (v, unit) in features.items()} for name, features in state.items()}

    def active_scenarios(self):
        active = []
        if 'road-main' in self.closed: active.append('road_closed')
        if 'B' in self.broken: active.append('excavator_failure')
        if self.crusher_factor < 1: active.append('crusher_reduced')
        return active

    def validate(self):
        assert 0 <= self.delivered_t <= self.ore_mined_t + 1e-8
        assert abs(self.ore_mined_t + sum(self.faces.values()) - sum(FACE_CAP_T.values())) <= 1e-6
        assert self.ore_mined_t - self.delivered_t - sum(t.payload_t for t in self.trucks) < 1e-6
        for t in self.trucks:
            assert -1e-8 <= t.payload_t <= CAPACITY_T + 1e-8
            assert 0 <= t.fuel_pct <= 100
            assert t.node in COORDS


def benchmark(hours=4):
    result = {}
    for mode in ('basic', 'adaptive'):
        mine = Mine(mode=mode)
        for _ in range(int(hours*3600/20)):
            mine.step(20)
            mine.validate()
        result[mode] = {
            'tonnes': round(mine.delivered_t, 1),
            'grade': round(mine.feed_grade, 3),
            'grade_error': round(abs(mine.feed_grade-TARGET_GRADE), 3),
            'avg_wait_minutes': round(sum(t.waiting_s for t in mine.trucks)/60/len(mine.trucks), 1),
        }
    return result
