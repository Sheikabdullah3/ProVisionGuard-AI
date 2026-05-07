"""
ProVisionGuard AI v7.0 — Intent Analysis Engine
================================================
NEW in v7.0:
  ✅ Intent Analysis Engine  — WHO + WHY + NEXT ACTION prediction
  ✅ Micro-Expression Engine — 8-class emotion + stress/deception signals
  ✅ Gaze Intelligence       — Heatmap, scan count, fixation zones
  ✅ Trajectory Analysis     — Path pattern: direct/wander/stalk/flee
  ✅ Identity Classifier     — stranger/neighbor/family/staff/threat
  ✅ Behavior Timeline       — Per-person full history graph
  ✅ Combined Intent Score   — All signals fused into one profile
  ✅ Login System            — Session auth (from v6)
  ✅ SQLite Database         — Persistent storage (from v6)

Default Credentials:
  admin / pvg@admin123
  operator / pvg@1234

Run:   python app_v7.py
       python run_pvg.py  (with auto-restart)
Open:  http://localhost:5000
"""

import cv2, numpy as np, time, threading, os, queue, sys
import sqlite3, hashlib, secrets
from datetime import datetime
from collections import deque
from flask import (Flask, Response, render_template_string, jsonify,
                   send_file, request, redirect, url_for, session)
from flask_socketio import SocketIO

# ── SETTINGS ──────────────────────────────────────────────
SHOW_WINDOW   = False   # Set True to see camera popup
CAM0_SRC      = 0       # Primary camera index
CAM1_SRC      = None    # Set to 1 if second camera exists
USE_GPU       = True    # Auto-falls back to CPU if no CUDA
STREAM_FPS    = 25
STREAM_QUAL   = 75
NIGHT_THRESH  = 60      # avg brightness below this = night mode
CROWD_LIMIT   = 4       # alert if > N persons
ALERT_COOLDOWN= 15
SNAPSHOT_DIR  = 'data/snapshots'
REPORT_DIR    = 'data/reports'
DB_PATH       = 'data/pvg.db'

for d in [SNAPSHOT_DIR, REPORT_DIR,
          'data/known_faces/whitelist',
          'data/known_faces/blacklist',
          'data/known_faces/routine']:
    os.makedirs(d, exist_ok=True)

# ── FLASK ─────────────────────────────────────────────────
app = Flask(__name__)
app.config['SECRET_KEY'] = secrets.token_hex(32)
app.config['PERMANENT_SESSION_LIFETIME'] = 3600 * 8   # 8 hours
sio = SocketIO(app, cors_allowed_origins='*',
               async_mode='threading',
               ping_timeout=60,
               ping_interval=25)

# ── DATABASE SETUP ────────────────────────────────────────
def db_connect():
    con = sqlite3.connect(DB_PATH, check_same_thread=False)
    con.row_factory = sqlite3.Row
    return con

def db_init():
    con = db_connect()
    cur = con.cursor()
    # Users table
    cur.execute('''CREATE TABLE IF NOT EXISTS users (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        username TEXT UNIQUE NOT NULL,
        password_hash TEXT NOT NULL,
        role TEXT DEFAULT "operator",
        created_at TEXT DEFAULT CURRENT_TIMESTAMP
    )''')
    # Alerts table
    cur.execute('''CREATE TABLE IF NOT EXISTS alerts (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        time TEXT,
        label TEXT,
        name TEXT,
        score REAL,
        emotion TEXT,
        dist REAL,
        behaviors TEXT,
        cam INTEGER,
        snapshot_path TEXT,
        created_at TEXT DEFAULT CURRENT_TIMESTAMP
    )''')
    # Persons seen table
    cur.execute('''CREATE TABLE IF NOT EXISTS persons_seen (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT,
        category TEXT,
        first_seen TEXT,
        last_seen TEXT,
        total_visits INTEGER DEFAULT 1,
        max_threat REAL DEFAULT 0
    )''')
    # Plates table
    cur.execute('''CREATE TABLE IF NOT EXISTS plates (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        plate TEXT,
        cam INTEGER,
        seen_at TEXT DEFAULT CURRENT_TIMESTAMP
    )''')
    # Stats table
    cur.execute('''CREATE TABLE IF NOT EXISTS daily_stats (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        date TEXT UNIQUE,
        total_alerts INTEGER DEFAULT 0,
        critical_count INTEGER DEFAULT 0,
        high_count INTEGER DEFAULT 0,
        persons_detected INTEGER DEFAULT 0
    )''')
    # Seed default users
    def _hash(pw): return hashlib.sha256(pw.encode()).hexdigest()
    cur.execute("INSERT OR IGNORE INTO users (username,password_hash,role) VALUES (?,?,?)",
                ('admin', _hash('pvg@admin123'), 'admin'))
    cur.execute("INSERT OR IGNORE INTO users (username,password_hash,role) VALUES (?,?,?)",
                ('operator', _hash('pvg@1234'), 'operator'))
    con.commit(); con.close()
    print("✅ Database initialized: data/pvg.db")

db_init()

# DB write lock
_db_lock = threading.Lock()

def db_save_alert(entry, snapshot_path=''):
    try:
        with _db_lock:
            con = db_connect()
            con.execute('''INSERT INTO alerts
                (time,label,name,score,emotion,dist,behaviors,cam,snapshot_path)
                VALUES (?,?,?,?,?,?,?,?,?)''',
                (entry.get('time',''), entry.get('label',''),
                 entry.get('name',''), entry.get('score',0),
                 entry.get('emotion',''), entry.get('dist',0),
                 ','.join(entry.get('behaviors',[])),
                 entry.get('cam',0), snapshot_path))
            # Update daily stats
            today = datetime.now().strftime('%Y-%m-%d')
            lbl = entry.get('label', '')
            con.execute(
                "INSERT OR IGNORE INTO daily_stats (date) VALUES (?)", (today,))
            con.execute(
                "UPDATE daily_stats SET total_alerts=total_alerts+1 WHERE date=?", (today,))
            if lbl == 'CRITICAL':
                con.execute(
                    "UPDATE daily_stats SET critical_count=critical_count+1 WHERE date=?", (today,))
            elif lbl == 'HIGH':
                con.execute(
                    "UPDATE daily_stats SET high_count=high_count+1 WHERE date=?", (today,))
            con.commit(); con.close()
    except Exception as e:
        print(f"⚠ DB alert save error: {e}")

def db_save_plate(plate, cam):
    try:
        with _db_lock:
            con = db_connect()
            con.execute("INSERT INTO plates (plate,cam) VALUES (?,?)", (plate, cam))
            con.commit(); con.close()
    except: pass

def db_get_alerts(limit=100):
    try:
        con = db_connect()
        rows = con.execute(
            "SELECT * FROM alerts ORDER BY id DESC LIMIT ?", (limit,)
        ).fetchall()
        con.close()
        return [dict(r) for r in rows]
    except: return []

def db_get_stats():
    try:
        con = db_connect()
        total = con.execute("SELECT COUNT(*) as c FROM alerts").fetchone()['c']
        crits = con.execute("SELECT COUNT(*) as c FROM alerts WHERE label='CRITICAL'").fetchone()['c']
        highs = con.execute("SELECT COUNT(*) as c FROM alerts WHERE label='HIGH'").fetchone()['c']
        today = datetime.now().strftime('%Y-%m-%d')
        today_row = con.execute(
            "SELECT * FROM daily_stats WHERE date=?", (today,)
        ).fetchone()
        plates = con.execute(
            "SELECT COUNT(DISTINCT plate) as c FROM plates"
        ).fetchone()['c']
        con.close()
        return {
            'total_alerts': total, 'critical': crits, 'high': highs,
            'today_alerts': today_row['total_alerts'] if today_row else 0,
            'unique_plates': plates
        }
    except: return {}

# ── AUTH HELPERS ──────────────────────────────────────────
def _hash_pw(pw): return hashlib.sha256(pw.encode()).hexdigest()

def check_login(username, password):
    try:
        con = db_connect()
        user = con.execute(
            "SELECT * FROM users WHERE username=? AND password_hash=?",
            (username, _hash_pw(password))
        ).fetchone()
        con.close()
        return dict(user) if user else None
    except: return None

def login_required(f):
    from functools import wraps
    @wraps(f)
    def decorated(*args, **kwargs):
        if not session.get('logged_in'):
            return redirect(url_for('login_page'))
        return f(*args, **kwargs)
    return decorated

def admin_required(f):
    from functools import wraps
    @wraps(f)
    def decorated(*args, **kwargs):
        if not session.get('logged_in'):
            return redirect(url_for('login_page'))
        if session.get('role') != 'admin':
            return jsonify({'error': 'Admin access required'}), 403
        return f(*args, **kwargs)
    return decorated

# ── GLOBAL STATE ──────────────────────────────────────────
_lock        = threading.Lock()
_frame0      = None
_frame1      = None
_persons     = {}
_alerts      = deque(maxlen=100)
_fps         = 0.0
_night       = False
_crowd       = 0
_plates      = []
_weapons     = []
_zones       = []
_total_alerts= 0
_start_time  = time.time()
_ai_ready    = False    # True once models loaded
_ai_status   = "Loading models..."


# ── NIGHT VISION ──────────────────────────────────────────
def enhance_night(frame):
    lab = cv2.cvtColor(frame, cv2.COLOR_BGR2LAB)
    l, a, b = cv2.split(lab)
    clahe = cv2.createCLAHE(clipLimit=3.0, tileGridSize=(8,8))
    l = clahe.apply(l)
    table = np.array([((i/255.0)**0.55)*255 for i in range(256)], np.uint8)
    l = cv2.LUT(l, table)
    result = cv2.cvtColor(cv2.merge([l,a,b]), cv2.COLOR_LAB2BGR)
    result = cv2.bilateralFilter(result, 5, 50, 50)
    b2,g2,r2 = cv2.split(result)
    g2 = np.clip(g2.astype(np.int16)+8, 0, 255).astype(np.uint8)
    b2 = np.clip(b2.astype(np.int16)-5, 0, 255).astype(np.uint8)
    return cv2.merge([b2,g2,r2])

def is_dark(frame):
    return float(np.mean(cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY))) < NIGHT_THRESH

# ── ZONE TOOLS ────────────────────────────────────────────
def check_zones(cx, cy, zones, W, H):
    triggered = []
    for name, pts_norm, color in zones:
        pts = np.array([[int(p[0]*W), int(p[1]*H)] for p in pts_norm], np.int32)
        if cv2.pointPolygonTest(pts, (float(cx), float(cy)), False) >= 0:
            triggered.append(name)
    return triggered

def draw_zones(frame, zones):
    H, W = frame.shape[:2]
    ov = frame.copy()
    for name, pts_norm, color in zones:
        pts = np.array([[int(p[0]*W), int(p[1]*H)] for p in pts_norm], np.int32)
        cv2.fillPoly(ov, [pts], color)
        cv2.polylines(frame, [pts], True, color, 2)
        cx = int(np.mean([p[0]*W for p in pts_norm]))
        cy = int(np.mean([p[1]*H for p in pts_norm]))
        cv2.putText(frame, f"ZONE:{name}", (cx-30, cy),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.45, color, 2)
    cv2.addWeighted(ov, 0.12, frame, 0.88, 0, frame)

# ── PERSON STATE ──────────────────────────────────────────
class PS:
    def __init__(self, tid):
        self.tid=tid; self.fs=time.time(); self.ls=time.time()
        self.name=None; self.cat='stranger'; self.fc=0.0
        self.emo='Neutral'; self.et=0.0
        self.dist=99.0; self.dh=deque(maxlen=8)
        self.threat=0.0; self.theft=0.0; self.la=0.0
        self.zones=[]
        self.sn_ph=deque(maxlen=45); self.sn_sh=deque(maxlen=20); self.sn=0.0
        self.sl_hx=deque(maxlen=60); self.sl_ld=None; self.sl_lt=deque(maxlen=20); self.sl=0.0
        self.sh_hf=0; self.sh_tf=0; self.sh=0.0
        self.si_ph=deque(maxlen=300); self.si=0.0
        self.ss_wh=deque(maxlen=20); self.ss_ch=deque(maxlen=20); self.ss_sp=0; self.ss=0.0
        self.sf=0.0

    def upd(self, cx, cy, kps, W, fd):
        # nervous
        self.sn_ph.append((cx,cy,time.time()))
        if len(self.sn_ph)>=6:
            pos=list(self.sn_ph); sp=[]
            for i in range(1,len(pos)):
                dx=pos[i][0]-pos[i-1][0]; dy=pos[i][1]-pos[i-1][1]; dt=pos[i][2]-pos[i-1][2]
                if dt>0: sp.append(np.sqrt(dx*dx+dy*dy)/dt)
            if len(sp)>=4:
                self.sn_sh.extend(sp[-4:])
                if len(self.sn_sh)>=8:
                    arr=list(self.sn_sh); cv_=np.std(arr)/(np.mean(arr)+1e-6)
                    stps=sum(1 for x in arr if x<8)
                    self.sn=0.3*min(cv_*0.5+(stps/len(arr))*0.5,1)+0.7*self.sn

        # loiter
        self.si_ph.append((cx,cy))
        dur=time.time()-self.fs; ts=min(dur/20,1.0); as_=0.0
        if len(self.si_ph)>=30:
            pts=list(self.si_ph)[-60:]; xs=[p[0] for p in pts]; ys=[p[1] for p in pts]
            area=(max(xs)-min(xs))*(max(ys)-min(ys))
            if area<8000: as_=1.0
            elif area<25000: as_=0.6
            elif area<60000: as_=0.3
        self.si=0.1*(ts*0.5+as_*0.5)+0.9*self.si

        if kps is None: return

        def gk(i):
            k=kps[i]; return float(k[0]),float(k[1]),float(k[2])

        nx,ny,nc=gk(0)
        lwx,lwy,lwc=gk(9); rwx,rwy,rwc=gk(10)
        lex,ley,lec=gk(3); rex,rey,rec=gk(4)

        # looking
        if nc>=0.3:
            self.sl_hx.append(nx/(W+1e-6))
            d=None
            if lec>0.2 and rec>0.2:
                l=abs(nx-lex); r=abs(nx-rex)
                if l<r*0.6: d='left'
                elif r<l*0.6: d='right'
                else: d='center'
            if d and d!=self.sl_ld and d!='center' and self.sl_ld: self.sl_lt.append(time.time())
            self.sl_ld=d
            now=time.time()
            while self.sl_lt and now-self.sl_lt[0]>30: self.sl_lt.popleft()
            v=float(np.std(list(self.sl_hx)[-15:])) if len(self.sl_hx)>=15 else 0
            ls=min((len(self.sl_lt)/10)*0.6+v*4*0.4,1.0)
            self.sl=0.35*ls+0.65*self.sl

        # hiding
        self.sh_tf+=1
        y1_=int(cy-(self.dh[-1]*50 if self.dh else 80))
        y2_=int(cy+(self.dh[-1]*50 if self.dh else 80))
        h=(not fd or nc<0.25)
        if not h and y2_>y1_: h=(ny-y1_)/(y2_-y1_+1e-6)>0.45
        if h: self.sh_hf+=1
        else: self.sh_hf=max(0,self.sh_hf-1)
        if self.sh_tf>0: self.sh=0.3*min(self.sh_hf/(self.sh_tf*0.4),1)+0.7*self.sh

        # sudden
        self.ss_ch.append((cx,cy,time.time()))
        if lwc>0.3: self.ss_wh.append(lwy)
        elif rwc>0.3: self.ss_wh.append(rwy)
        bv=wv=0.0
        if len(self.ss_ch)>=4:
            c2=list(self.ss_ch); dx=c2[-1][0]-c2[-4][0]; dy=c2[-1][1]-c2[-4][1]; dt=c2[-1][2]-c2[-4][2]
            bv=np.sqrt(dx*dx+dy*dy)/(dt*100+1e-6)
        if len(self.ss_wh)>=4:
            w=list(self.ss_wh); wv=abs(w[-1]-w[-4])/4
        if bv>18 or wv>22: self.ss_sp=min(self.ss_sp+3,30)
        else: self.ss_sp=max(self.ss_sp-1,0)
        sud=min((bv/25)*0.4+(wv/30)*0.3+(self.ss_sp/30)*0.3,1.0)
        self.ss=0.45*sud+0.55*self.ss

    def upd_follow(self, cx, cy, others):
        if not others: self.sf=max(0,self.sf-0.02); return
        md=min(np.sqrt((cx-ox)**2+(cy-oy)**2) for ox,oy in others)
        self.sf=min(self.sf+0.04,1.0) if md<130 else max(self.sf-0.02,0.0)

    def compute(self):
        sg={'nervous':self.sn,'looking':self.sl,'hiding':self.sh,
            'loiter':float(min(self.si,1)),'sudden':self.ss,
            'following':self.sf,'emotion':self.et}
        W={'nervous':0.12,'looking':0.18,'hiding':0.20,'loiter':0.12,'sudden':0.18,'following':0.10,'emotion':0.10}
        base=sum(sg[k]*W[k] for k in W)
        act=sum(1 for k in sg if sg[k]>0.35)
        bon=0.25 if act>=4 else 0.15 if act>=3 else 0.08 if act>=2 else 0.0
        comb=min(base+bon,1.0)
        mod={'whitelist':0.10,'routine':0.70,'blacklist':1.60,'stranger':1.00}.get(self.cat,1.0)
        if self.dist<1.2: comb+=0.18
        elif self.dist<2.5: comb+=0.08
        if self.zones: comb+=0.15
        self.threat=0.25*min(comb*mod,1.0)+0.75*self.threat
        # theft
        tw={'looking':0.20,'hiding':0.30,'loiter':0.20,'sudden':0.15,'nervous':0.15}
        tr=sum(sg[k]*tw[k] for k in tw)
        if sg['looking']>0.35 and sg['hiding']>0.30 and sg['loiter']>0.30: tr+=0.20
        tr+=min((time.time()-self.fs)/120,0.15)
        if self.cat=='whitelist': tr*=0.05
        if self.cat=='blacklist': tr*=1.8
        self.theft=float(min(tr,1.0))
        behs=[]
        if self.sh>0.30: behs.append('Concealing')
        if self.sl>0.35: behs.append('Scouting')
        if self.si>0.40: behs.append('Loitering')
        if self.ss>0.40: behs.append('Rushing')
        if self.sn>0.35: behs.append('Nervous')
        if self.sf>0.45: behs.append('Following')
        if self.zones: behs.append(f'Zone:{self.zones[0]}')
        if self.theft>0.55: behs.insert(0,'THEFT RISK')
        return self.threat, sg, behs


# ══════════════════════════════════════════════════════════
# INTENT ANALYSIS ENGINE v7.0
# Fuses: body language + micro-expression + gaze + trajectory
# Outputs: WHO + WHY + NEXT ACTION + Intent Score
# ══════════════════════════════════════════════════════════
class IntentEngine:
    """
    Per-person intent profiler.
    Call .update() every frame, .profile() for full output.
    """

    # ── Gaze zones (normalized 0-1 screen coords) ─────────
    GAZE_ZONES = {
        'entry':    (0.0, 0.0, 0.3, 1.0),   # left edge = door/entry
        'exit':     (0.7, 0.0, 1.0, 1.0),   # right edge = exit
        'cashier':  (0.3, 0.0, 0.7, 0.4),   # top center = cashier
        'shelves':  (0.1, 0.3, 0.9, 0.8),   # middle = shelves
        'camera':   (0.35,0.0, 0.65,0.25),  # top center = cameras
        'people':   None,                    # dynamic — other persons
    }

    def __init__(self, tid):
        self.tid = tid
        self.created = time.time()

        # ── Gaze tracking ─────────────────────────────────
        self.gaze_history   = deque(maxlen=300)  # (nx, ny, t)
        self.gaze_zone_hits = {}    # zone_name → count
        self.gaze_scans     = 0     # rapid left-right scan count
        self.last_gaze_dir  = None
        self.gaze_flip_times= deque(maxlen=30)
        self.camera_looks   = 0     # times looked at camera zone

        # ── Micro-expression ──────────────────────────────
        self.emo_history    = deque(maxlen=60)   # (emotion, scores_dict, t)
        self.stress_score   = 0.0
        self.deception_score= 0.0
        self.fear_peak      = 0.0
        self.emo_volatility = 0.0   # rapid emotion changes = stress

        # ── Trajectory ────────────────────────────────────
        self.traj_history   = deque(maxlen=500)  # (cx, cy, t)
        self.traj_pattern   = 'unknown'  # direct/wander/loiter/stalk/flee/scout
        self.revisit_zones  = {}    # grid_cell → visit_count
        self.speed_history  = deque(maxlen=30)
        self.direction_changes = deque(maxlen=20)
        self.approach_vector= None  # moving toward/away camera

        # ── Time × Zone ───────────────────────────────────
        self.zone_entry_times = {}  # zone → first_entry_time
        self.zone_dwell       = {}  # zone → total_seconds
        self.idle_periods     = []  # [(start,end)] standing still
        self.last_pos         = None
        self.still_since      = None
        self.total_idle_time  = 0.0

        # ── Identity classification ───────────────────────
        self.identity_class   = 'stranger'
        # stranger / neighbor / family / staff / scout / threat
        self.identity_conf    = 0.0
        self.visit_count      = 1   # how many times seen today
        self.familiar_score   = 0.0  # 0=never seen, 1=very familiar

        # ── Intent outputs (updated each frame) ───────────
        self.intent_who    = 'Unknown'
        self.intent_why    = 'Observing'
        self.intent_next   = 'Unknown'
        self.intent_score  = 0.0    # 0=benign, 1=threat
        self.intent_label  = 'MONITORING'
        self.intent_reason = []     # list of reason strings

        # ── Smoothing ─────────────────────────────────────
        self._smooth_intent = 0.0

    # ── Update every frame ────────────────────────────────
    def update(self, cx, cy, nose_xy, W, H, emo_name, emo_scores, cat, fc):
        now = time.time()

        # 1. Gaze update
        if nose_xy is not None:
            nx, ny = nose_xy[0] / W, nose_xy[1] / H
            self.gaze_history.append((nx, ny, now))
            self._update_gaze(nx, ny, now)

        # 2. Micro-expression update
        if emo_scores:
            self.emo_history.append((emo_name, emo_scores, now))
            self._update_micro(emo_name, emo_scores)

        # 3. Trajectory update
        ncx, ncy = cx / W, cy / H
        self.traj_history.append((ncx, ncy, now))
        self._update_trajectory(ncx, ncy, now)

        # 4. Time × Zone update
        self._update_time_zone(ncx, ncy, now)

        # 5. Identity classification
        self._update_identity(cat)

        # 6. Fuse all → intent
        if fc % 8 == 0:
            self._fuse_intent()

    # ── Gaze analysis ─────────────────────────────────────
    def _update_gaze(self, nx, ny, now):
        # Zone hit counting
        for zone, bounds in self.GAZE_ZONES.items():
            if bounds is None: continue
            x1, y1, x2, y2 = bounds
            if x1 <= nx <= x2 and y1 <= ny <= y2:
                self.gaze_zone_hits[zone] = self.gaze_zone_hits.get(zone, 0) + 1

        # Camera-looking detection
        cx1, cy1, cx2, cy2 = self.GAZE_ZONES['camera']
        if cx1 <= nx <= cx2 and cy1 <= ny <= cy2:
            self.camera_looks += 1

        # Rapid scan detection (left-right flipping)
        if len(self.gaze_history) >= 4:
            recent = list(self.gaze_history)[-8:]
            xs = [g[0] for g in recent]
            flips = sum(1 for i in range(1, len(xs)-1)
                       if (xs[i]-xs[i-1]) * (xs[i+1]-xs[i]) < -0.02)
            if flips >= 2:
                self.gaze_scans = min(self.gaze_scans + 1, 999)

    # ── Micro-expression analysis ─────────────────────────
    def _update_micro(self, emo_name, emo_scores):
        EMO_STRESS  = {'Fear':0.9,'Anger':0.7,'Disgust':0.6,'Contempt':0.5,'Surprise':0.3}
        EMO_DECEIVE = {'Contempt':0.8,'Disgust':0.5,'Surprise':0.4,'Fear':0.3}

        raw_stress = sum(emo_scores.get(e,0)*w for e,w in EMO_STRESS.items())
        raw_dec    = sum(emo_scores.get(e,0)*w for e,w in EMO_DECEIVE.items())

        self.stress_score   = 0.3*min(raw_stress,1.0) + 0.7*self.stress_score
        self.deception_score= 0.3*min(raw_dec,1.0)   + 0.7*self.deception_score
        self.fear_peak      = max(self.fear_peak, emo_scores.get('Fear',0))

        # Emotion volatility (rapid changes = anxiety)
        if len(self.emo_history) >= 6:
            recent_emos = [e[0] for e in list(self.emo_history)[-10:]]
            changes = sum(1 for i in range(1,len(recent_emos))
                         if recent_emos[i] != recent_emos[i-1])
            vol = changes / max(len(recent_emos)-1, 1)
            self.emo_volatility = 0.4*vol + 0.6*self.emo_volatility

    # ── Trajectory analysis ───────────────────────────────
    def _update_trajectory(self, ncx, ncy, now):
        if len(self.traj_history) < 5: return

        recent = list(self.traj_history)[-30:]

        # Speed
        if len(recent) >= 4:
            speeds = []
            for i in range(1, min(len(recent), 8)):
                dx = recent[-i][0] - recent[-i-1][0]
                dy = recent[-i][1] - recent[-i-1][1]
                dt = recent[-i][2] - recent[-i-1][2]
                if dt > 0:
                    speeds.append(np.sqrt(dx*dx+dy*dy)/dt)
            if speeds:
                self.speed_history.append(np.mean(speeds))

        # Revisit zones (10x10 grid)
        cell = (int(ncx*10), int(ncy*10))
        self.revisit_zones[cell] = self.revisit_zones.get(cell,0) + 1

        # Path area (small area = loitering/pacing)
        if len(self.traj_history) >= 60:
            pts = list(self.traj_history)[-60:]
            xs = [p[0] for p in pts]; ys = [p[1] for p in pts]
            area = (max(xs)-min(xs)) * (max(ys)-min(ys))

            # Revisit score
            revisit_cells = sum(1 for v in self.revisit_zones.values() if v >= 3)

            # Approach: moving toward center bottom (camera proximity)
            if len(recent) >= 10:
                dy_trend = recent[-1][1] - recent[-10][1]
                self.approach_vector = 'approaching' if dy_trend > 0.05 else (
                                       'retreating'  if dy_trend <-0.05 else 'static')

            # Classify trajectory pattern
            duration = now - self.created
            avg_speed = np.mean(list(self.speed_history)) if self.speed_history else 0

            if area < 0.005 and duration > 30:
                self.traj_pattern = 'loitering'
            elif area < 0.02 and revisit_cells > 5:
                self.traj_pattern = 'pacing'
            elif self.gaze_scans > 15 and area < 0.04:
                self.traj_pattern = 'scouting'
            elif avg_speed > 0.15:
                self.traj_pattern = 'fleeing' if self.approach_vector=='retreating' else 'moving'
            elif area < 0.01:
                self.traj_pattern = 'standing'
            else:
                self.traj_pattern = 'browsing'

    # ── Time × Zone analysis ──────────────────────────────
    def _update_time_zone(self, ncx, ncy, now):
        # Still detection
        if self.last_pos:
            lx, ly = self.last_pos
            dist = np.sqrt((ncx-lx)**2 + (ncy-ly)**2)
            if dist < 0.02:
                if self.still_since is None:
                    self.still_since = now
                else:
                    idle = now - self.still_since
                    self.total_idle_time = idle
            else:
                if self.still_since and (now - self.still_since) > 5:
                    self.idle_periods.append((self.still_since, now))
                self.still_since = None
        self.last_pos = (ncx, ncy)

    # ── Identity classification ───────────────────────────
    def _update_identity(self, cat):
        duration = time.time() - self.created

        if cat == 'whitelist':
            self.identity_class = 'staff_or_family'
            self.identity_conf  = 0.95
            self.familiar_score = 1.0
        elif cat == 'blacklist':
            self.identity_class = 'known_threat'
            self.identity_conf  = 0.99
        elif cat == 'routine':
            self.identity_class = 'regular_visitor'
            self.identity_conf  = 0.85
            self.familiar_score = 0.7
        else:
            # Stranger — classify by behavior
            relaxed = (self.stress_score < 0.25 and
                       self.gaze_scans < 5 and
                       self.traj_pattern in ['browsing','moving','standing'])
            nervous = (self.stress_score > 0.5 or
                       self.gaze_scans > 12 or
                       self.camera_looks > 3)
            scouting = (self.traj_pattern in ['scouting','pacing'] or
                        self.gaze_scans > 20)

            if scouting and nervous:
                self.identity_class = 'potential_threat'
                self.identity_conf  = min(0.4 + self.stress_score*0.4, 0.85)
            elif nervous:
                self.identity_class = 'suspicious_stranger'
                self.identity_conf  = min(0.3 + self.stress_score*0.3, 0.75)
            elif relaxed and duration > 10:
                self.identity_class = 'casual_visitor'
                self.identity_conf  = min(0.3 + duration/120, 0.8)
            else:
                self.identity_class = 'stranger'
                self.identity_conf  = 0.5

    # ── INTENT FUSION ─────────────────────────────────────
    def _fuse_intent(self):
        reasons = []
        now = time.time()
        duration = now - self.created

        # ── WHO ───────────────────────────────────────────
        who_map = {
            'staff_or_family':   'Known Person',
            'regular_visitor':   'Regular Visitor',
            'casual_visitor':    'Casual Visitor',
            'stranger':          'Stranger',
            'suspicious_stranger':'Suspicious Stranger',
            'potential_threat':  'Potential Threat',
            'known_threat':      'KNOWN THREAT',
        }
        self.intent_who = who_map.get(self.identity_class, 'Unknown')

        # ── WHY (purpose inference) ────────────────────────
        top_zone = max(self.gaze_zone_hits, key=self.gaze_zone_hits.get) \
                   if self.gaze_zone_hits else None

        if self.identity_class in ('staff_or_family','regular_visitor'):
            self.intent_why = 'Normal Activity'
        elif self.traj_pattern == 'scouting' and self.gaze_scans > 15:
            self.intent_why = 'Surveillance / Casing'
            reasons.append(f'Scanned area {self.gaze_scans}x')
        elif self.traj_pattern in ('loitering','pacing'):
            idle_m = int(self.total_idle_time // 60)
            idle_s = int(self.total_idle_time % 60)
            self.intent_why = 'Loitering / Waiting'
            reasons.append(f'Idle {idle_m}m{idle_s}s')
        elif self.camera_looks > 5:
            self.intent_why = 'Camera-Aware / Evasive'
            reasons.append(f'Checked camera {self.camera_looks}x')
        elif top_zone == 'cashier':
            self.intent_why = 'Interest in Cashier Area'
        elif top_zone == 'entry':
            self.intent_why = 'Monitoring Entry/Exit'
            reasons.append('Focused on entry zone')
        elif self.traj_pattern == 'browsing':
            self.intent_why = 'Browsing / Shopping'
        else:
            self.intent_why = 'Observing'

        # ── NEXT ACTION prediction ─────────────────────────
        avg_speed = np.mean(list(self.speed_history)) if self.speed_history else 0

        if self.approach_vector == 'approaching':
            if self.stress_score > 0.5:
                self.intent_next = 'Aggressive Approach Likely'
                reasons.append('Moving closer under stress')
            else:
                self.intent_next = 'Likely to Enter'
        elif self.approach_vector == 'retreating':
            self.intent_next = 'Likely to Leave'
        elif self.traj_pattern == 'loitering':
            if duration > 120:
                self.intent_next = 'Prolonged Stay — Act Expected'
                reasons.append(f'Idle {int(duration)}s')
            else:
                self.intent_next = 'Waiting / Observing'
        elif self.traj_pattern == 'scouting':
            self.intent_next = 'Planning Entry or Theft'
            reasons.append('Scout pattern detected')
        elif self.traj_pattern == 'pacing':
            self.intent_next = 'Anxious — Unpredictable'
        else:
            self.intent_next = 'Continuing Normal Activity'

        # ── INTENT SCORE (0-1) ────────────────────────────
        components = {
            'stress':       self.stress_score         * 0.20,
            'deception':    self.deception_score      * 0.12,
            'fear':         self.fear_peak             * 0.08,
            'gaze_scans':   min(self.gaze_scans/30,1) * 0.18,
            'cam_looks':    min(self.camera_looks/8,1)* 0.12,
            'trajectory':   self._traj_score()        * 0.18,
            'idle_time':    min(self.total_idle_time/120,1)*0.07,
            'volatility':   self.emo_volatility        * 0.05,
        }
        raw = sum(components.values())

        # Identity modifier
        mod = {'known_threat':2.0,'potential_threat':1.5,
               'suspicious_stranger':1.3,'stranger':1.0,
               'casual_visitor':0.7,'regular_visitor':0.4,
               'staff_or_family':0.1}.get(self.identity_class, 1.0)

        fused = min(raw * mod, 1.0)
        self._smooth_intent = 0.25*fused + 0.75*self._smooth_intent
        self.intent_score = self._smooth_intent

        # ── LABEL ─────────────────────────────────────────
        if self.identity_class == 'known_threat':
            self.intent_label = 'KNOWN THREAT'
        elif self.intent_score >= 0.75:
            self.intent_label = 'HIGH INTENT RISK'
        elif self.intent_score >= 0.55:
            self.intent_label = 'SUSPICIOUS'
        elif self.intent_score >= 0.35:
            self.intent_label = 'MONITORING'
        elif self.intent_score >= 0.15:
            self.intent_label = 'LOW RISK'
        else:
            self.intent_label = 'BENIGN'

        self.intent_reason = reasons[:3]

    def _traj_score(self):
        scores = {'loitering':0.7,'scouting':0.85,'pacing':0.65,
                  'standing':0.3,'browsing':0.1,'moving':0.15,
                  'fleeing':0.5,'unknown':0.2}
        return scores.get(self.traj_pattern, 0.2)

    # ── Public profile output ─────────────────────────────
    def profile(self):
        top_zones = sorted(self.gaze_zone_hits.items(),
                           key=lambda x: x[1], reverse=True)[:3]
        return {
            'who':          self.intent_who,
            'why':          self.intent_why,
            'next':         self.intent_next,
            'score':        round(self.intent_score, 3),
            'label':        self.intent_label,
            'reasons':      self.intent_reason,
            'identity':     self.identity_class,
            'identity_conf':round(self.identity_conf, 2),
            'trajectory':   self.traj_pattern,
            'gaze_scans':   self.gaze_scans,
            'camera_looks': self.camera_looks,
            'stress':       round(self.stress_score, 2),
            'deception':    round(self.deception_score, 2),
            'fear_peak':    round(self.fear_peak, 2),
            'emo_volatile': round(self.emo_volatility, 2),
            'idle_time':    round(self.total_idle_time, 1),
            'top_gaze_zones': [z[0] for z in top_zones],
            'approach':     self.approach_vector or 'unknown',
            'duration':     round(time.time() - self.created, 1),
        }


# Global intent engines dict (tid → IntentEngine)
_intent_engines = {}
_intent_lock = threading.Lock()

def get_intent_engine(tid):
    with _intent_lock:
        if tid not in _intent_engines:
            _intent_engines[tid] = IntentEngine(tid)
        return _intent_engines[tid]

def cleanup_intent_engines(active_tids):
    with _intent_lock:
        for tid in list(_intent_engines):
            if tid not in active_tids:
                del _intent_engines[tid]


def threat_label(score, cat):
    if cat=='whitelist': return 'TRUSTED',(0,220,100)
    if cat=='blacklist': return 'BLACKLIST',(0,0,200)
    if score>=0.82: return 'CRITICAL',(0,0,255)
    if score>=0.65: return 'HIGH',(0,50,255)
    if score>=0.45: return 'MEDIUM',(0,140,255)
    if score>=0.28: return 'WATCH',(0,210,190)
    return 'SAFE',(0,255,80)


# ── DRAW ──────────────────────────────────────────────────
def draw_box(frame, st, x1, y1, x2, y2, sg, behs, fc):
    tl, tc = threat_label(st.threat, st.cat)
    cv2.rectangle(frame,(x1,y1),(x2,y2),tc,2)
    nm=st.name or 'STRANGER'
    hdr=f"{nm} [{tl}] {st.threat*100:.0f}%"
    hw=max(len(hdr)*10,x2-x1)
    cv2.rectangle(frame,(x1,y1-42),(x1+hw,y1),tc,-1)
    cv2.putText(frame,hdr,(x1+4,y1-24),cv2.FONT_HERSHEY_SIMPLEX,0.52,(255,255,255),2)
    if st.theft>0.15:
        cv2.putText(frame,f"THEFT:{st.theft*100:.0f}%",(x1+4,y1-8),cv2.FONT_HERSHEY_SIMPLEX,0.34,(0,70,255),1)
    if behs:
        btxt=' · '.join([b for b in behs if b!='THEFT RISK'][:3])
        cv2.rectangle(frame,(x1,y2+1),(x2,y2+18),(8,8,8),-1)
        cv2.putText(frame,btxt,(x1+4,y2+13),cv2.FONT_HERSHEY_SIMPLEX,0.32,(255,180,0),1)
    if st.threat>=0.82 and fc%14<7:
        cv2.rectangle(frame,(x1-3,y1-46),(x2+3,y2+3),(0,0,255),3)
    # mini bars
    bw=x2-x1; by=y2+22
    rows=[('N',sg['nervous'],(80,130,255)),('G',sg['looking'],(0,200,255)),
          ('H',sg['hiding'],(130,50,255)),('L',sg['loiter'],(0,210,190)),
          ('M',sg['sudden'],(0,100,255)),('T',st.theft,(0,50,255))]
    for i,(lb,v,col) in enumerate(rows):
        y=by+i*12
        cv2.putText(frame,lb,(x1,y+9),cv2.FONT_HERSHEY_SIMPLEX,0.26,(90,90,90),1)
        cv2.rectangle(frame,(x1+14,y),(x2,y+9),(10,10,10),-1)
        fill=int(v*(bw-14))
        if fill>0: cv2.rectangle(frame,(x1+14,y),(x1+14+fill,y+9),col,-1)

# ── ALERT ─────────────────────────────────────────────────
alert_log   = []
_tts_engine = None
_tts_lock   = threading.Lock()

def _speak(txt):
    def _r():
        with _tts_lock:
            try:
                if _tts_engine:
                    _tts_engine.say(txt)
                    _tts_engine.runAndWait()
            except: pass
    threading.Thread(target=_r, daemon=True).start()

def do_alert(frame, st, label, behs, cam=0):
    global _total_alerts
    if time.time()-st.la < ALERT_COOLDOWN: return
    st.la = time.time()
    name = st.name or f"Unknown #{st.tid}"
    ts   = datetime.now().strftime('%H:%M:%S')
    print(f"🚨 [{ts}] [{label}] {name} | {st.threat*100:.0f}% | CAM{cam}")
    sp = os.path.join(SNAPSHOT_DIR, f"CAM{cam}_{label}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.jpg")
    cv2.imwrite(sp, frame)
    entry = {'time':ts,'label':label,'name':name,'score':st.threat,
             'emotion':st.emo,'dist':st.dist,'behaviors':behs[:3],'cam':cam}
    alert_log.append(entry)
    with _lock:
        _alerts.appendleft(entry)
        _total_alerts += 1
    # ── Save to SQLite DB ─────────────────────────────────
    threading.Thread(target=db_save_alert, args=(entry, sp), daemon=True).start()
    voices = {'CRITICAL':'Critical threat! Security activated!',
              'HIGH':'Warning! High risk person.','MEDIUM':'Suspicious behavior detected.',
              'BLACKLIST':'Alert! Known threat!'}
    if label in voices: _speak(voices[label])

# ── PDF REPORT ────────────────────────────────────────────
def make_pdf():
    try:
        from reportlab.lib.pagesizes import A4
        from reportlab.lib import colors
        from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
        from reportlab.lib.units import mm
        from reportlab.platypus import (SimpleDocTemplate, Paragraph,
            Spacer, Table, TableStyle, HRFlowable)
        from reportlab.lib.enums import TA_CENTER

        ts   = datetime.now().strftime('%Y%m%d_%H%M%S')
        path = os.path.join(REPORT_DIR, f'PVG_{ts}.pdf')
        doc  = SimpleDocTemplate(path, pagesize=A4,
            leftMargin=20*mm, rightMargin=20*mm,
            topMargin=18*mm, bottomMargin=18*mm)
        S = getSampleStyleSheet()
        def ps(name, **kw):
            return ParagraphStyle(name, **kw)

        story = []
        story.append(Paragraph('ProVisionGuard AI',
            ps('t', fontName='Helvetica-Bold', fontSize=22,
               alignment=TA_CENTER,
               textColor=colors.HexColor('#001830'))))
        story.append(Paragraph(
            f'Security Report — {datetime.now().strftime("%d %b %Y %H:%M")}',
            ps('s', fontName='Helvetica', fontSize=10,
               alignment=TA_CENTER,
               textColor=colors.HexColor('#446688'),
               spaceAfter=14)))
        story.append(HRFlowable(width='100%', thickness=2,
            color=colors.HexColor('#0088cc')))
        story.append(Spacer(1,10))

        with _lock:
            alerts = list(_alerts)
            tot    = _total_alerts

        crits  = sum(1 for a in alerts if a.get('label')=='CRITICAL')
        highs  = sum(1 for a in alerts if a.get('label')=='HIGH')
        thefts = sum(1 for a in alerts if 'THEFT' in ' '.join(a.get('behaviors',[])).upper())
        uptime = int(time.time()-_start_time)
        h,r=divmod(uptime,3600); m,s=divmod(r,60)

        # Summary table
        story.append(Paragraph('Summary', ps('sh',
            fontName='Helvetica-Bold', fontSize=13,
            textColor=colors.HexColor('#001830'), spaceAfter=6)))
        sd = [['Metric','Value'],
              ['Total Alerts', str(tot)],
              ['Critical Events', str(crits)],
              ['High Risk Events', str(highs)],
              ['Theft Risk Events', str(thefts)],
              ['System Uptime', f'{h:02d}:{m:02d}:{s:02d}']]
        st = Table(sd, colWidths=[80*mm, 80*mm])
        st.setStyle(TableStyle([
            ('BACKGROUND',(0,0),(-1,0),colors.HexColor('#001830')),
            ('TEXTCOLOR',(0,0),(-1,0),colors.white),
            ('FONTNAME',(0,0),(-1,0),'Helvetica-Bold'),
            ('FONTNAME',(0,1),(-1,-1),'Helvetica'),
            ('FONTSIZE',(0,0),(-1,-1),9),
            ('ROWBACKGROUNDS',(0,1),(-1,-1),[colors.HexColor('#f0f8ff'),colors.white]),
            ('GRID',(0,0),(-1,-1),0.5,colors.HexColor('#cce8ff')),
            ('TOPPADDING',(0,0),(-1,-1),4),('BOTTOMPADDING',(0,0),(-1,-1),4),
        ]))
        story.append(st)
        story.append(Spacer(1,14))

        # Alert log
        story.append(Paragraph('Alert Log (last 30)', ps('sh',
            fontName='Helvetica-Bold', fontSize=13,
            textColor=colors.HexColor('#001830'), spaceAfter=6)))
        if alerts:
            ld = [['Time','Level','Person','Score','Emo','Behaviors']]
            for a in list(reversed(alerts))[:30]:
                ld.append([a.get('time',''),a.get('label',''),
                           (a.get('name','') or '')[:16],
                           f"{a.get('score',0)*100:.0f}%",
                           a.get('emotion',''),
                           ', '.join(a.get('behaviors',[])[:2])[:24]])
            lt = Table(ld, colWidths=[20*mm,22*mm,32*mm,14*mm,20*mm,52*mm])
            lc_map = {'CRITICAL':colors.HexColor('#cc0022'),
                      'HIGH':colors.HexColor('#ee5500'),
                      'MEDIUM':colors.HexColor('#ee9900'),
                      'WATCH':colors.HexColor('#0088aa')}
            lt.setStyle(TableStyle([
                ('BACKGROUND',(0,0),(-1,0),colors.HexColor('#001830')),
                ('TEXTCOLOR',(0,0),(-1,0),colors.white),
                ('FONTNAME',(0,0),(-1,0),'Helvetica-Bold'),
                ('FONTNAME',(0,1),(-1,-1),'Helvetica'),
                ('FONTSIZE',(0,0),(-1,-1),7.5),
                ('ROWBACKGROUNDS',(0,1),(-1,-1),[colors.HexColor('#f5f9fc'),colors.white]),
                ('GRID',(0,0),(-1,-1),0.4,colors.HexColor('#ddeeff')),
                ('TOPPADDING',(0,0),(-1,-1),3),('BOTTOMPADDING',(0,0),(-1,-1),3),
            ]))
            for i,a in enumerate(list(reversed(alerts))[:30],1):
                c=lc_map.get(a.get('label',''))
                if c: lt.setStyle(TableStyle([('TEXTCOLOR',(1,i),(1,i),c),
                                              ('FONTNAME',(1,i),(1,i),'Helvetica-Bold')]))
            story.append(lt)
        else:
            story.append(Paragraph('No alerts during this period.',
                ps('b',fontName='Helvetica',fontSize=9,
                   textColor=colors.HexColor('#446688'))))

        story.append(Spacer(1,16))
        story.append(HRFlowable(width='100%',thickness=1,color=colors.HexColor('#cce8ff')))
        story.append(Spacer(1,5))
        story.append(Paragraph(
            f'ProVisionGuard AI v5.0  ·  Confidential  ·  {datetime.now().strftime("%d %b %Y")}',
            ps('f',fontName='Helvetica',fontSize=7,
               textColor=colors.HexColor('#aabbcc'),alignment=TA_CENTER)))
        doc.build(story)
        print(f"📄 Report: {path}")
        return path
    except Exception as e:
        print(f"❌ PDF error: {e}")
        return None


# ── MJPEG STREAMS ─────────────────────────────────────────
def _stream(get_frame):
    interval = 1.0 / STREAM_FPS
    blank = None
    while True:
        with _lock:
            frame = get_frame()
        if frame is not None:
            ok, buf = cv2.imencode('.jpg', frame,
                [cv2.IMWRITE_JPEG_QUALITY, STREAM_QUAL])
            if ok:
                yield (b'--frame\r\nContent-Type: image/jpeg\r\n\r\n'
                       + buf.tobytes() + b'\r\n')
        else:
            # Send small black frame while loading
            if blank is None:
                blank = np.zeros((480,640,3),np.uint8)
                cv2.putText(blank, _ai_status, (60,240),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0,180,220), 2)
            ok, buf = cv2.imencode('.jpg', blank,
                [cv2.IMWRITE_JPEG_QUALITY, 50])
            if ok:
                yield (b'--frame\r\nContent-Type: image/jpeg\r\n\r\n'
                       + buf.tobytes() + b'\r\n')
        time.sleep(interval)

@app.route('/login', methods=['GET','POST'])
def login_page():
    error = ''
    if request.method == 'POST':
        username = request.form.get('username','').strip()
        password = request.form.get('password','')
        user = check_login(username, password)
        if user:
            session.permanent = True
            session['logged_in'] = True
            session['username'] = user['username']
            session['role'] = user['role']
            print(f"✅ Login: {username} [{user['role']}]")
            return redirect(url_for('index'))
        else:
            error = 'Invalid username or password'
    return render_template_string(LOGIN_HTML, error=error)

@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('login_page'))

@app.route('/api/users', methods=['GET'])
@admin_required
def api_users():
    con = db_connect()
    users = con.execute(
        "SELECT id,username,role,created_at FROM users ORDER BY id"
    ).fetchall()
    con.close()
    return jsonify([dict(u) for u in users])

@app.route('/api/users/add', methods=['POST'])
@admin_required
def api_add_user():
    data = request.json or {}
    username = data.get('username','').strip()
    password = data.get('password','')
    role = data.get('role','operator')
    if not username or not password:
        return jsonify({'error':'Username and password required'}), 400
    try:
        con = db_connect()
        con.execute(
            "INSERT INTO users (username,password_hash,role) VALUES (?,?,?)",
            (username, _hash_pw(password), role)
        )
        con.commit(); con.close()
        return jsonify({'success': True, 'username': username})
    except sqlite3.IntegrityError:
        return jsonify({'error': 'Username already exists'}), 409

@app.route('/api/users/delete/<int:uid>', methods=['DELETE'])
@admin_required
def api_delete_user(uid):
    if uid == 1:
        return jsonify({'error':'Cannot delete root admin'}), 403
    con = db_connect()
    con.execute("DELETE FROM users WHERE id=?", (uid,))
    con.commit(); con.close()
    return jsonify({'success': True})

@app.route('/api/db/alerts')
@login_required
def api_db_alerts():
    limit = min(int(request.args.get('limit', 50)), 500)
    return jsonify(db_get_alerts(limit))

@app.route('/api/db/stats')
@login_required
def api_db_stats():
    return jsonify(db_get_stats())


@app.route('/cam0')
@login_required
def cam0():
    return Response(_stream(lambda: _frame0),
        mimetype='multipart/x-mixed-replace;boundary=frame')

@app.route('/cam1')
@login_required
def cam1():
    return Response(_stream(lambda: _frame1),
        mimetype='multipart/x-mixed-replace;boundary=frame')

@app.route('/api/report')
@login_required
def api_report():
    path = make_pdf()
    if path and os.path.exists(path):
        return send_file(path, as_attachment=True,
            download_name=os.path.basename(path))
    return jsonify({'error':'Report generation failed'}), 500

@app.route('/api/status')
@login_required
def api_status():
    with _lock:
        return jsonify({
            'fps':_fps,'night':_night,'crowd':_crowd,
            'persons':len(_persons),'alerts':_total_alerts,
            'ai_ready':_ai_ready,'ai_status':_ai_status,
            'plates':_plates[-3:],'weapons':_weapons[-3:],
        })

@app.route('/')
@login_required
def index():
    return render_template_string(DASHBOARD_HTML,
        username=session.get('username',''),
        role=session.get('role','operator'))

# Push state to browser
def push_loop():
    last = 0
    while True:
        try:
            with _lock:
                persons = dict(_persons)
                alerts  = list(_alerts)
                fps     = _fps; night=_night
                crowd   = _crowd
                plates  = list(_plates[-3:])
                weapons = list(_weapons[-3:])
            new_a = []
            if len(alerts)>last:
                new_a=alerts[:len(alerts)-last]; last=len(alerts)
            sio.emit('up',{
                'p':persons,'a':new_a,
                's':{'fps':fps,'night':night,'crowd':crowd,
                     'plates':plates,'weapons':weapons,
                     'ready':_ai_ready}
            })
        except: pass
        time.sleep(0.12)

threading.Thread(target=push_loop, daemon=True).start()


# ── CAMERA LOOP ───────────────────────────────────────────
def run_camera(cam_id, src, yolo_det, yolo_pose,
               face_app, emo_model, ocr, known_faces):
    global _frame0, _frame1, _fps, _night, _crowd, _plates, _weapons

    fq=queue.Queue(maxsize=1); fr={}
    eq=queue.Queue(maxsize=1); er={}

    def face_w():
        while True:
            try:
                tid,crop=fq.get(timeout=1)
                faces=face_app.get(crop)
                if not faces: fr[tid]=(None,'stranger',0); continue
                emb=faces[0].embedding
                bn,bc,bs=None,'stranger',0.0
                for nm,dt in known_faces.items():
                    n=np.linalg.norm(emb)*np.linalg.norm(dt['emb'])
                    sim=float(np.dot(emb,dt['emb'])/(n+1e-6))
                    if sim>bs: bs=sim;bn=nm;bc=dt['category']
                fr[tid]=(bn,bc,bs) if bs>=0.55 else (None,'stranger',bs)
            except queue.Empty: pass

    def emo_w():
        lbls=['Anger','Contempt','Disgust','Fear','Happiness','Neutral','Sadness','Surprise']
        wts={'Anger':0.95,'Disgust':0.70,'Fear':0.65,'Contempt':0.60,
             'Surprise':0.35,'Sadness':0.20,'Neutral':0.05,'Happiness':0.0}
        while True:
            try:
                tid,crop=eq.get(timeout=1)
                if crop.size==0: continue
                rgb=cv2.cvtColor(crop,cv2.COLOR_BGR2RGB)
                emo,scs=emo_model.predict_emotions(rgb,logits=False)
                sd=dict(zip(lbls,scs))
                et=min(sum(sd.get(e,0)*w for e,w in wts.items()),1.0)
                er[tid]=(emo,float(et))
            except queue.Empty: pass
            except: pass

    threading.Thread(target=face_w,daemon=True).start()
    threading.Thread(target=emo_w,daemon=True).start()

    cap=cv2.VideoCapture(src)
    cap.set(cv2.CAP_PROP_FRAME_WIDTH,640)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT,480)
    cap.set(cv2.CAP_PROP_FPS, 30)
    cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
    cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*'MJPG'))

    if not cap.isOpened():
        print(f"⚠ Camera {cam_id} not found (src={src})")
        return

    W=int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    H=int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    print(f"✅ Camera {cam_id}: {W}x{H}")

    pstates={}; fps_buf=deque(maxlen=30)
    fc=0; last_kps={}; local_fps=0.0
    local_plates=[]; local_weapons=[]

    # ── GPU Device Selection ───────────────────────────────
    try:
        import torch
        if USE_GPU and torch.cuda.is_available():
            device = '0'
            gpu_name = torch.cuda.get_device_name(0)
            print(f"✅ GPU Active: {gpu_name}")
        else:
            device = 'cpu'
            print("⚠ Running on CPU (no CUDA)")
    except ImportError:
        device = 'cpu'
        print("⚠ PyTorch not found — CPU mode")

    while True:
        ret,frame=cap.read()
        if not ret: time.sleep(0.05); continue

        t0=time.time(); fc+=1
        H_F,W_F=frame.shape[:2]; active=[]

        # Night vision
        dark=is_dark(frame)
        if cam_id==0:
            with _lock: _night=dark
        if dark: frame=enhance_night(frame)

        # Zones
        with _lock: zones=list(_zones)
        if zones: draw_zones(frame,zones)

        # Person detection + tracking (GPU)
        try:
            det=yolo_det.track(frame,persist=True,
                classes=[0],verbose=False,conf=0.45,device=device)
        except Exception as e:
            print(f"⚠ Detection error: {e}"); time.sleep(0.1); continue

        # Pose (every other frame for speed)
        if fc%2==0:
            try:
                pose=yolo_pose.track(frame,persist=True,verbose=False,conf=0.45,device=device)
                if pose and pose[0].keypoints is not None and pose[0].boxes is not None:
                    last_kps={}
                    for i,kps in enumerate(pose[0].keypoints.data):
                        pb=pose[0].boxes
                        pid=int(pb.id[i]) if pb.id is not None else i
                        last_kps[pid]=kps
            except: pass

        # Weapon detection (every 8 frames, reuse yolo_det)
        if fc%8==0:
            try:
                wr=yolo_det(frame,verbose=False,conf=0.5,
                            classes=[43,76],device=device)  # knife=43, scissors=76
                if wr and wr[0].boxes is not None and len(wr[0].boxes)>0:
                    for box in wr[0].boxes:
                        cls=int(box.cls[0])
                        nm2=yolo_det.names.get(cls,'object')
                        bxy=box.xyxy[0].cpu().numpy()
                        x1,y1,x2,y2=[int(v) for v in bxy]
                        cv2.rectangle(frame,(x1,y1),(x2,y2),(0,0,255),3)
                        cv2.putText(frame,f"WEAPON:{nm2.upper()}",(x1,y1-8),
                                    cv2.FONT_HERSHEY_SIMPLEX,0.55,(0,0,255),2)
                        local_weapons.append({'label':nm2,'cam':cam_id})
                    if len(local_weapons)>6: local_weapons=local_weapons[-6:]
                    if cam_id==0:
                        with _lock: _weapons[:]=local_weapons
            except: pass

        # Crowd count
        cnt=len(det[0].boxes) if det and det[0].boxes is not None else 0
        if cam_id==0:
            with _lock: _crowd=cnt
        if cnt>CROWD_LIMIT:
            cv2.putText(frame,f"⚠ CROWD: {cnt}",(W_F//2-80,46),
                        cv2.FONT_HERSHEY_SIMPLEX,0.8,(0,30,255),2)

        # License plate OCR (every 25 frames)
        if ocr and fc%25==0:
            try:
                gray=cv2.cvtColor(frame,cv2.COLOR_BGR2GRAY)
                res=ocr.readtext(gray,detail=1,
                    allowlist='ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789 ')
                for _,txt,conf in res:
                    if conf>0.7 and len(txt.strip())>=4:
                        local_plates.append({'plate':txt.strip().upper(),
                            'time':datetime.now().strftime('%H:%M:%S'),'cam':cam_id})
                if len(local_plates)>8: local_plates=local_plates[-8:]
                if cam_id==0:
                    with _lock: _plates[:]=local_plates
            except: pass

        # Centers for following
        centers=[]
        if det and det[0].boxes is not None:
            for box in det[0].boxes:
                bx=box.xyxy[0].cpu().numpy()
                centers.append((int((bx[0]+bx[2])/2),int((bx[1]+bx[3])/2)))

        dp={}
        if det and det[0].boxes is not None:
            for i,box in enumerate(det[0].boxes):
                bxy=box.xyxy[0].cpu().numpy(); x1,y1,x2,y2=[int(v) for v in bxy]
                tid=int(box.id[0]) if box.id is not None else i+cam_id*1000
                active.append(tid)
                if tid not in pstates: pstates[tid]=PS(tid)
                s=pstates[tid]; s.ls=time.time()
                cx=int((x1+x2)/2); cy=int((y1+y2)/2)

                # Distance
                ph=y2-y1
                d=450.0*170.0/(ph*100.0) if ph>0 else 99.0
                s.dh.append(d); s.dist=float(np.median(s.dh))

                # Zone check
                s.zones=check_zones(cx,cy,zones,W_F,H_F)

                # Face
                if fc%8==0:
                    crop2=frame[max(0,y1):min(H_F,y2),max(0,x1):min(W_F,x2)]
                    if crop2.size>0:
                        try: fq.put_nowait((tid,crop2.copy()))
                        except queue.Full: pass
                if tid in fr:
                    bn,bc,bs=fr[tid]
                    if bn: s.name=bn;s.cat=bc;s.fc=bs

                # Emotion
                if fc%12==0:
                    crop2=frame[max(0,y1):min(H_F,y2),max(0,x1):min(W_F,x2)]
                    if crop2.size>0:
                        try: eq.put_nowait((tid,crop2.copy()))
                        except queue.Full: pass
                if tid in er:
                    emo,et=er[tid]; s.emo=emo; s.et=0.4*et+0.6*s.et

                # Signals
                kps=last_kps.get(tid)
                s.upd(cx,cy,kps,W_F,(s.name is not None or s.fc>0.3))
                others=[(c[0],c[1]) for j,c in enumerate(centers) if j!=i]
                s.upd_follow(cx,cy,others)

                score,sigs,behs=s.compute()
                tl,_=threat_label(s.threat,s.cat)

                # ── Intent Engine update ───────────────────
                ie = get_intent_engine(tid)
                nose_xy = None
                if kps is not None:
                    try:
                        nk = kps[0]
                        if float(nk[2]) > 0.25:
                            nose_xy = (float(nk[0]), float(nk[1]))
                    except: pass
                emo_scores_dict = {}
                if tid in er:
                    _emo_lbls=['Anger','Contempt','Disgust','Fear',
                               'Happiness','Neutral','Sadness','Surprise']
                    # er stores (emo_name, et_float) — rebuild approximate dict
                    emo_nm = er[tid][0]
                    emo_scores_dict = {e:(1.0 if e==emo_nm else 0.05)
                                       for e in _emo_lbls}
                ie.update(cx,cy,nose_xy,W_F,H_F,
                          s.emo, emo_scores_dict, s.cat, fc)
                iprof = ie.profile()

                # Overlay intent on frame
                il_color = {
                    'BENIGN':(0,220,80),'LOW RISK':(0,200,180),
                    'MONITORING':(0,180,255),'SUSPICIOUS':(0,80,255),
                    'HIGH INTENT RISK':(0,0,220),'KNOWN THREAT':(0,0,180)
                }.get(iprof['label'],(0,150,255))
                # Intent bar below person box
                itxt = f"INTENT:{iprof['label']}  WHO:{iprof['who'][:10]}"
                cv2.rectangle(frame,(x1,y2+90),(x2,y2+108),(6,6,6),-1)
                cv2.putText(frame,itxt,(x1+2,y2+103),
                            cv2.FONT_HERSHEY_SIMPLEX,0.28,il_color,1)
                # Next action
                cv2.rectangle(frame,(x1,y2+109),(x2,y2+122),(4,4,4),-1)
                cv2.putText(frame,f"NEXT:{iprof['next'][:28]}",
                            (x1+2,y2+120),cv2.FONT_HERSHEY_SIMPLEX,
                            0.26,(180,180,80),1)

                if tl in ['CRITICAL','HIGH','MEDIUM','BLACKLIST'] and s.cat!='whitelist':
                    do_alert(frame,s,tl,behs,cam_id)
                draw_box(frame,s,x1,y1,x2,y2,sigs,behs,fc)

                dp[str(tid)]={
                    'name':s.name,'category':s.cat,
                    'threat_score':s.threat,'threat_label':tl,
                    'emotion':s.emo,'distance':s.dist,
                    'behaviors':behs,'signals':sigs,
                    'theft_risk':s.theft,'cam':cam_id,'zones':s.zones,
                    'intent': iprof,
                }

        # Cleanup stale
        for tid in list(pstates):
            if tid not in active and time.time()-pstates[tid].ls>4:
                del pstates[tid]; fr.pop(tid,None); er.pop(tid,None)
        cleanup_intent_engines(set(active))

        # FPS
        fps_buf.append(time.time()-t0)
        local_fps=1.0/(np.mean(fps_buf)+1e-6) if len(fps_buf)==30 else local_fps

        # HUD
        cv2.rectangle(frame,(0,0),(W_F,38),(4,4,4),-1)
        cv2.putText(frame,f"ProVisionGuard | CAM-0{cam_id+1}",
                    (8,24),cv2.FONT_HERSHEY_SIMPLEX,0.68,(255,215,0),2)
        ts2=datetime.now().strftime('%H:%M:%S')
        mode='NIGHT' if dark else 'DAY'
        cv2.putText(frame,f"P:{len(active)} FPS:{local_fps:.0f} {mode} {ts2}",
                    (W_F-250,24),cv2.FONT_HERSHEY_SIMPLEX,0.4,(90,90,90),1)
        if dark:
            cv2.putText(frame,"◉ NIGHT MODE",(8,H_F-10),
                        cv2.FONT_HERSHEY_SIMPLEX,0.42,(0,255,150),1)

        # Store
        with _lock:
            if cam_id==0:
                _frame0=frame.copy(); _fps=local_fps
                _persons.clear(); _persons.update(dp)
            else:
                _frame1=frame.copy()

        # Optional window (disabled by default = no popup)
        if SHOW_WINDOW:
            cv2.imshow(f'ProVisionGuard CAM-0{cam_id+1}',frame)
            key=cv2.waitKey(1)&0xFF
            if key==ord('q'): break
            elif key==ord('r'): pstates.clear();fr.clear();er.clear()
            elif key==ord('s'):
                p=os.path.join(SNAPSHOT_DIR,f"CAM{cam_id}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.jpg")
                cv2.imwrite(p,frame); print(f"📸 {p}")
            elif key==ord('z') and cam_id==0:
                with _lock:
                    _zones.append(('RESTRICTED',[(0.25,0.3),(0.75,0.3),(0.75,0.9),(0.25,0.9)],(0,50,255)))
                print("🔴 Zone added!")
            elif key==ord('c') and cam_id==0:
                with _lock: _zones.clear(); print("✅ Zones cleared!")

    cap.release()
    if SHOW_WINDOW: cv2.destroyAllWindows()


# ── AI LOADER ─────────────────────────────────────────────
def run_ai():
    global _ai_ready, _ai_status, _tts_engine

    def status(msg):
        global _ai_status
        _ai_status = msg
        print(f"  {msg}")

    print("="*52)
    print("  ProVisionGuard AI v5.0")
    print("  GPU: RTX 3050")
    print("="*52)

    try:
        import torch as _torch
        _cuda_ok = _torch.cuda.is_available()
        _gpu_name = _torch.cuda.get_device_name(0) if _cuda_ok else 'CPU'
        print(f"  Device: {'GPU — ' + _gpu_name if _cuda_ok else 'CPU'}")

        from ultralytics import YOLO
        status("Loading YOLO detection...")
        yolo_det = YOLO('yolo11n.pt')
        if _cuda_ok:
            yolo_det.to('cuda')

        status("Loading YOLO pose...")
        yolo_pose = YOLO('yolo11n-pose.pt')
        if _cuda_ok:
            yolo_pose.to('cuda')

        # GPU warm-up (first inference is always slow)
        status("Warming up GPU...")
        import numpy as _np
        _dummy = _np.zeros((480,640,3), dtype=_np.uint8)
        yolo_det(_dummy, verbose=False)
        yolo_pose(_dummy, verbose=False)
        print("  ✅ GPU warmed up")

        status("Loading face recognition...")
        from insightface.app import FaceAnalysis
        face_app = FaceAnalysis(name='buffalo_l')
        face_app.prepare(ctx_id=0 if _cuda_ok else -1, det_size=(320,320))

        status("Loading emotion model...")
        from hsemotion_onnx.facial_emotions import HSEmotionRecognizer
        emo_model = HSEmotionRecognizer(model_name='enet_b0_8_best_afew')

        status("Loading OCR...")
        ocr = None
        try:
            import easyocr
            ocr = easyocr.Reader(['en'], gpu=True)
            print("  ✅ EasyOCR GPU ready")
        except Exception as e:
            print(f"  ⚠ EasyOCR skipped: {e}")

        status("Loading TTS...")
        try:
            import pyttsx3
            _tts_engine = pyttsx3.init()
            _tts_engine.setProperty('rate',150)
        except: pass

        status("Loading face database...")
        known_faces = {}
        for cat in ['whitelist','routine','blacklist']:
            d=os.path.join('data/known_faces',cat)
            if not os.path.exists(d): continue
            for person in os.listdir(d):
                pd2=os.path.join(d,person)
                if not os.path.isdir(pd2): continue
                embs=[]
                for f in os.listdir(pd2):
                    if not f.lower().endswith(('.jpg','.jpeg','.png')): continue
                    img=cv2.imread(os.path.join(pd2,f))
                    if img is None: continue
                    faces=face_app.get(img)
                    if faces: embs.append(faces[0].embedding)
                if embs:
                    known_faces[person]={'emb':np.mean(embs,axis=0),'category':cat}
                    print(f"  ✅ {person} [{cat}]")
        print(f"  ✅ {len(known_faces)} persons loaded")

        _ai_ready = True
        _ai_status = "System Live"
        print(f"\n✅ ALL SYSTEMS GO!")
        print(f"   Dashboard: http://localhost:5000")
        print(f"   PDF Report: http://localhost:5000/api/report")
        print(f"   Controls: SHOW_WINDOW=True for camera popup")
        print("="*52)

        # Start cameras
        t0 = threading.Thread(target=run_camera,
            args=(0,CAM0_SRC,yolo_det,yolo_pose,
                  face_app,emo_model,ocr,known_faces),
            daemon=True)
        t0.start()

        if CAM1_SRC is not None:
            time.sleep(2)
            t1=threading.Thread(target=run_camera,
                args=(1,CAM1_SRC,yolo_det,yolo_pose,
                      face_app,emo_model,ocr,known_faces),
                daemon=True)
            t1.start()

        # Auto hourly report
        def auto_rep():
            while True:
                time.sleep(3600)
                make_pdf()
                print("📄 Hourly report saved")
        threading.Thread(target=auto_rep,daemon=True).start()

        t0.join()

    except Exception as e:
        _ai_status = f"Error: {e}"
        print(f"❌ AI Error: {e}")
        import traceback; traceback.print_exc()


# ── DASHBOARD HTML ────────────────────────────────────────
# ── LOGIN PAGE HTML ───────────────────────────────────────
LOGIN_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>ProVisionGuard — Login</title>
<link href="https://fonts.googleapis.com/css2?family=Syne:wght@400;700;800&family=DM+Mono:wght@400;500&display=swap" rel="stylesheet">
<style>
*{margin:0;padding:0;box-sizing:border-box}
body{background:#020408;min-height:100vh;display:flex;align-items:center;justify-content:center;
  font-family:'Syne',sans-serif;
  background-image:linear-gradient(rgba(0,229,255,.012) 1px,transparent 1px),
    linear-gradient(90deg,rgba(0,229,255,.012) 1px,transparent 1px);
  background-size:52px 52px;}
.card{background:#030810;border:1px solid rgba(0,229,255,.12);border-radius:6px;
  padding:44px 40px;width:380px;position:relative;overflow:hidden;}
.card::before{content:"";position:absolute;top:0;left:0;right:0;height:2px;
  background:linear-gradient(90deg,transparent,#00e5ff 40%,rgba(0,120,255,.6) 70%,transparent);}
.logo{display:flex;align-items:center;gap:10px;margin-bottom:32px;}
.lsvg{width:36px;height:36px;}
.lnm{font-size:14px;font-weight:800;letter-spacing:5px;color:#fff;text-transform:uppercase;}
.lsub{font-family:'DM Mono',monospace;font-size:7px;letter-spacing:4px;color:#00e5ff;margin-top:3px;}
h2{font-size:11px;font-weight:700;letter-spacing:5px;color:#4a7090;text-transform:uppercase;margin-bottom:22px;}
.field{margin-bottom:16px;}
label{display:block;font-family:'DM Mono',monospace;font-size:8px;letter-spacing:3px;
  color:#4a7090;text-transform:uppercase;margin-bottom:7px;}
input{width:100%;background:#070f1e;border:1px solid rgba(0,229,255,.1);border-radius:3px;
  padding:12px 14px;color:#ddeeff;font-family:'DM Mono',monospace;font-size:13px;
  outline:none;transition:border-color .2s;}
input:focus{border-color:rgba(0,229,255,.4);}
.btn{width:100%;margin-top:22px;background:rgba(0,229,255,.08);border:1px solid rgba(0,229,255,.25);
  color:#00e5ff;font-family:'DM Mono',monospace;font-size:9px;letter-spacing:4px;
  padding:13px;border-radius:3px;cursor:pointer;text-transform:uppercase;transition:all .2s;}
.btn:hover{background:rgba(0,229,255,.15);border-color:#00e5ff;}
.err{background:rgba(255,34,85,.08);border:1px solid rgba(255,34,85,.2);color:#ff2255;
  font-family:'DM Mono',monospace;font-size:9px;letter-spacing:2px;padding:10px 13px;
  border-radius:3px;margin-bottom:16px;text-align:center;}
.hint{margin-top:18px;text-align:center;font-family:'DM Mono',monospace;
  font-size:8px;letter-spacing:2px;color:#1a3248;}
</style>
</head>
<body>
<div class="card">
  <div class="logo">
    <svg class="lsvg" viewBox="0 0 36 36" fill="none">
      <rect x=".5" y=".5" width="35" height="35" rx="4" stroke="#00e5ff" stroke-opacity=".22"/>
      <circle cx="18" cy="18" r="10" stroke="#00e5ff" stroke-opacity=".4" stroke-width="1"/>
      <circle cx="18" cy="18" r="5" stroke="#00e5ff" stroke-width="1.2" stroke-opacity=".8"/>
      <circle cx="18" cy="18" r="2" fill="#00e5ff"/>
    </svg>
    <div><div class="lnm">ProVisionGuard</div><div class="lsub">ENTERPRISE AI v7.0</div></div>
  </div>
  <h2>Secure Access</h2>
  {% if error %}<div class="err">⚠ {{ error }}</div>{% endif %}
  <form method="POST">
    <div class="field">
      <label>Username</label>
      <input type="text" name="username" autocomplete="username" autofocus required>
    </div>
    <div class="field">
      <label>Password</label>
      <input type="password" name="password" autocomplete="current-password" required>
    </div>
    <button type="submit" class="btn">→ Access Dashboard</button>
  </form>
  <div class="hint">Unauthorized access is prohibited and logged.</div>
</div>
</body>
</html>"""

DASHBOARD_HTML = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>ProVisionGuard AI</title>
<link href="https://fonts.googleapis.com/css2?family=Syne:wght@400;600;700;800&family=DM+Mono:wght@300;400;500&family=Syne+Mono&display=swap" rel="stylesheet">
<script src="https://cdnjs.cloudflare.com/ajax/libs/socket.io/4.7.2/socket.io.min.js"></script>
<style>
*{margin:0;padding:0;box-sizing:border-box}
:root{
  --bg0:#020408;--bg1:#030810;--bg2:#050c18;--bg3:#070f1e;
  --c1:#00e5ff;--c3:#00ff9d;--c4:#ff2255;--c5:#ff8800;--c6:#ffcc00;
  --c1a:rgba(0,229,255,.08);--c3a:rgba(0,255,157,.08);
  --c4a:rgba(255,34,85,.08);--c5a:rgba(255,136,0,.08);
  --bd:rgba(0,229,255,.07);--bd2:rgba(0,229,255,.16);
  --t1:#ddeeff;--t2:#4a7090;--t3:#1a3248;
  --fh:"Syne",sans-serif;--fm:"DM Mono",monospace;--fmm:"Syne Mono",monospace;
}
html,body{height:100%;background:var(--bg0);color:var(--t1);font-family:var(--fh);overflow:hidden;}
body{background-image:linear-gradient(rgba(0,229,255,.012) 1px,transparent 1px),linear-gradient(90deg,rgba(0,229,255,.012) 1px,transparent 1px);background-size:52px 52px;}
::-webkit-scrollbar{width:2px}::-webkit-scrollbar-thumb{background:var(--bd2);border-radius:2px}
/* layout */
#app{display:grid;grid-template-rows:54px 1fr 40px;height:100vh;}
#mid{display:grid;grid-template-columns:290px 1fr 1fr 265px;overflow:hidden;min-height:0;}
/* header */
#hdr{background:var(--bg1);border-bottom:1px solid var(--bd2);display:flex;align-items:center;padding:0 18px;gap:0;position:relative;}
#hdr::after{content:"";position:absolute;bottom:0;left:0;right:0;height:1px;
  background:linear-gradient(90deg,transparent,var(--c1) 30%,rgba(0,120,255,.6) 60%,transparent);
  background-size:300% 100%;animation:hl 5s linear infinite;}
@keyframes hl{0%{background-position:300% 0}100%{background-position:-300% 0}}
.bsvg{width:32px;height:32px;flex-shrink:0;}
.bnm{font-size:13px;font-weight:800;letter-spacing:5px;color:#fff;text-transform:uppercase;margin-left:10px;}
.bvr{font-family:var(--fm);font-size:7px;letter-spacing:4px;color:var(--c1);margin-top:2px;}
.hd{width:1px;height:24px;background:var(--bd2);margin:0 16px;}
.hmet{display:flex;gap:22px;}
.hm{display:flex;flex-direction:column;align-items:center;}
.hmv{font-family:var(--fmm);font-size:19px;font-weight:700;line-height:1;letter-spacing:1px;}
.hml{font-family:var(--fm);font-size:6px;letter-spacing:4px;color:var(--t3);margin-top:2px;text-transform:uppercase;}
.hrgt{margin-left:auto;display:flex;align-items:center;gap:12px;}
.chip{display:flex;align-items:center;gap:5px;padding:4px 11px;border-radius:2px;font-family:var(--fmm);font-size:7px;letter-spacing:3px;}
.clive{border:1px solid rgba(0,255,157,.25);background:var(--c3a);color:var(--c3);}
.cnight{border:1px solid rgba(0,229,255,.25);background:var(--c1a);color:var(--c1);display:none;}
.ccrowd{border:1px solid rgba(255,34,85,.3);background:var(--c4a);color:var(--c4);display:none;}
.cload{border:1px solid rgba(255,136,0,.25);background:var(--c5a);color:var(--c5);}
.pip{width:5px;height:5px;border-radius:50%;background:currentColor;box-shadow:0 0 6px currentColor;animation:pp 1.4s ease infinite;}
@keyframes pp{0%,100%{opacity:1;transform:scale(1)}50%{opacity:.4;transform:scale(1.8)}}
#hclk{font-family:var(--fmm);font-size:10px;letter-spacing:3px;color:var(--t3);}
/* panels */
.panel{background:var(--bg1);border-right:1px solid var(--bd);display:flex;flex-direction:column;overflow:hidden;min-height:0;}
.panel.last{border-right:none;border-left:1px solid var(--bd);}
.ph{padding:9px 13px;background:var(--bg2);border-bottom:1px solid var(--bd);display:flex;align-items:center;gap:7px;flex-shrink:0;}
.pht{font-family:var(--fm);font-size:8px;letter-spacing:4px;color:var(--t2);text-transform:uppercase;}
.phb{margin-left:auto;font-family:var(--fmm);font-size:9px;padding:2px 8px;border-radius:2px;background:var(--c1a);border:1px solid rgba(0,229,255,.14);color:var(--c1);min-width:24px;text-align:center;}
.pscr{flex:1;overflow-y:auto;padding:7px;display:flex;flex-direction:column;gap:6px;min-height:0;}
/* person card */
.pc{background:var(--bg3);border:1px solid var(--bd);border-radius:3px;overflow:hidden;animation:si .2s ease;position:relative;}
.pc::before{content:"";position:absolute;left:0;top:0;bottom:0;width:2px;background:var(--pcol,var(--c1));}
@keyframes si{from{opacity:0;transform:translateY(-4px)}to{opacity:1;transform:translateY(0)}}
.pct{padding:8px 10px 8px 12px;display:flex;align-items:center;gap:7px;border-bottom:1px solid var(--bd);}
.pcav{width:30px;height:30px;border-radius:2px;background:var(--c1a);border:1px solid var(--bd2);display:flex;align-items:center;justify-content:center;font-family:var(--fmm);font-size:10px;color:var(--c1);flex-shrink:0;}
.pcnm{font-size:12px;font-weight:700;color:#fff;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;}
.pcct{font-family:var(--fm);font-size:7px;letter-spacing:2px;margin-top:1px;}
.tp{font-family:var(--fmm);font-size:7px;letter-spacing:2px;padding:2px 7px;border-radius:2px;flex-shrink:0;text-transform:uppercase;}
.tp-trusted{background:rgba(0,255,157,.1);border:1px solid rgba(0,255,157,.22);color:var(--c3)}
.tp-safe{background:rgba(0,255,157,.05);border:1px solid rgba(0,255,157,.1);color:#00cc7a}
.tp-watch{background:var(--c1a);border:1px solid rgba(0,229,255,.18);color:var(--c1)}
.tp-medium{background:var(--c5a);border:1px solid rgba(255,136,0,.22);color:var(--c5)}
.tp-high{background:var(--c4a);border:1px solid rgba(255,34,85,.22);color:var(--c4)}
.tp-critical{background:rgba(255,34,85,.14);border:1px solid rgba(255,34,85,.38);color:var(--c4);animation:cg .5s ease infinite alternate}
@keyframes cg{to{box-shadow:0 0 7px rgba(255,34,85,.5)}}
.tp-blacklist{background:rgba(120,0,15,.2);border:1px solid rgba(120,0,15,.5);color:var(--c4)}
.pcb{padding:8px 10px 8px 12px;}
.rrow{display:flex;align-items:center;gap:8px;margin-bottom:6px;}
.rw{position:relative;width:42px;height:42px;flex-shrink:0;}
.rw svg{transform:rotate(-90deg)}
.rp{position:absolute;inset:0;display:flex;align-items:center;justify-content:center;font-family:var(--fmm);font-size:9px;color:#fff;}
.bset{flex:1}
.br{display:flex;align-items:center;gap:4px;margin-bottom:2px;}
.brl{font-family:var(--fm);font-size:6px;letter-spacing:1px;color:var(--t3);width:36px;flex-shrink:0;}
.brt{flex:1;height:2px;background:rgba(255,255,255,.04);border-radius:1px;overflow:hidden;}
.brf{height:100%;border-radius:1px;transition:width .5s ease;}
.brv{font-family:var(--fmm);font-size:6px;color:var(--t3);width:15px;text-align:right;}
.trbox{margin-top:5px;padding:4px 6px;background:rgba(255,34,85,.05);border:1px solid rgba(255,34,85,.1);border-radius:2px;}
.trlbl{font-family:var(--fm);font-size:6px;letter-spacing:3px;color:var(--c4);text-transform:uppercase;margin-bottom:3px;}
.trbar{height:2px;background:rgba(255,34,85,.08);border-radius:1px;overflow:hidden;}
.trfill{height:100%;border-radius:1px;background:linear-gradient(90deg,var(--c5),var(--c4));transition:width .6s ease;}
.pctags{display:flex;flex-wrap:wrap;gap:2px;margin-top:4px;}
.beh{font-family:var(--fm);font-size:6px;padding:1px 5px;border-radius:2px;background:var(--c5a);border:1px solid rgba(255,136,0,.15);color:var(--c5);text-transform:uppercase;}
.beh.t{background:var(--c4a);border:1px solid rgba(255,34,85,.18);color:var(--c4);}
.pcft{padding:5px 10px 5px 12px;border-top:1px solid var(--bd);display:flex;justify-content:space-between;}
.pft{font-family:var(--fm);font-size:7px;color:var(--t3);}
.pft span{color:var(--t1);}
/* intel strip */
.ist{padding:5px 13px;background:var(--bg2);border-bottom:1px solid var(--bd);display:flex;align-items:center;gap:6px;flex-shrink:0;min-height:26px;overflow:hidden;}
.istlbl{font-family:var(--fm);font-size:6px;letter-spacing:3px;color:var(--t3);}
.itag{font-family:var(--fm);font-size:6px;letter-spacing:1px;padding:1px 6px;border-radius:2px;text-transform:uppercase;white-space:nowrap;}
.itag.p{background:var(--c1a);border:1px solid rgba(0,229,255,.15);color:var(--c1);}
.itag.w{background:var(--c4a);border:1px solid rgba(255,34,85,.2);color:var(--c4);}
/* feed panels */
.fp{background:var(--bg0);display:flex;flex-direction:column;overflow:hidden;min-height:0;border-right:1px solid var(--bd);}
.fb{flex:1;position:relative;overflow:hidden;display:flex;align-items:center;justify-content:center;background:#000;min-height:0;}
.fb img{width:100%;height:100%;object-fit:contain;display:block;}
.hc{position:absolute;width:16px;height:16px;border-color:var(--c1);border-style:solid;opacity:.28;pointer-events:none;}
.hc.tl{top:7px;left:7px;border-width:1px 0 0 1px}.hc.tr{top:7px;right:7px;border-width:1px 1px 0 0}
.hc.bl{bottom:7px;left:7px;border-width:0 0 1px 1px}.hc.br{bottom:7px;right:7px;border-width:0 1px 1px 0}
.fhud{position:absolute;top:8px;left:10px;display:flex;align-items:center;gap:5px;font-family:var(--fm);font-size:8px;letter-spacing:3px;color:var(--c1);opacity:.7;pointer-events:none;}
.frec{width:5px;height:5px;border-radius:50%;background:var(--c4);box-shadow:0 0 5px var(--c4);animation:pp 1s ease infinite;}
.fts{position:absolute;top:8px;right:10px;font-family:var(--fmm);font-size:8px;letter-spacing:2px;color:var(--c1);opacity:.55;pointer-events:none;}
.fnv{position:absolute;bottom:34px;right:8px;font-family:var(--fm);font-size:7px;letter-spacing:3px;color:var(--c3);opacity:.8;display:none;pointer-events:none;}
.conn{position:absolute;inset:0;display:flex;flex-direction:column;align-items:center;justify-content:center;gap:8px;background:var(--bg0);}
.cr{width:38px;height:38px;border-radius:50%;border:1px solid var(--bd);border-top-color:var(--c1);animation:sp 1s linear infinite;}
@keyframes sp{to{transform:rotate(360deg)}}
.ctxt{font-family:var(--fmm);font-size:8px;letter-spacing:5px;color:var(--t3);}
.cbig{font-family:var(--fh);font-size:28px;font-weight:800;letter-spacing:8px;color:rgba(0,229,255,.04);}
.fsb2{height:36px;flex-shrink:0;background:var(--bg2);border-top:1px solid var(--bd);display:flex;align-items:center;justify-content:space-around;padding:0 8px;}
.fs{display:flex;flex-direction:column;align-items:center;}
.fsv{font-family:var(--fmm);font-size:12px;font-weight:700;letter-spacing:1px;line-height:1;}
.fsl{font-family:var(--fm);font-size:5px;letter-spacing:3px;color:var(--t3);margin-top:2px;text-transform:uppercase;}
/* alerts */
.ac{background:var(--bg3);border:1px solid var(--bd);border-radius:3px;overflow:hidden;animation:si .2s ease;position:relative;}
.ac::before{content:"";position:absolute;left:0;top:0;bottom:0;width:2px;background:var(--acol,var(--c1));}
.acin{padding:7px 8px 7px 11px;}
.ach{display:flex;align-items:center;justify-content:space-between;margin-bottom:2px;}
.actm{font-family:var(--fm);font-size:7px;letter-spacing:1px;color:var(--t3);}
.acnm{font-size:11px;font-weight:700;color:#fff;margin-bottom:2px;}
.acmt{display:flex;gap:6px;font-family:var(--fm);font-size:7px;color:var(--t3);}
.acbh{display:flex;flex-wrap:wrap;gap:2px;margin-top:3px;}
.abeh{font-family:var(--fm);font-size:6px;padding:1px 4px;border-radius:2px;background:var(--c5a);border:1px solid rgba(255,136,0,.15);color:var(--c5);}
/* footer */
#ftr{background:var(--bg1);border-top:1px solid var(--bd);display:flex;align-items:center;padding:0 18px;gap:16px;}
.fi{font-family:var(--fm);font-size:7px;letter-spacing:3px;color:var(--t3);display:flex;align-items:center;gap:4px;text-transform:uppercase;}
.fi span{color:var(--c1);}
.fdot{width:4px;height:4px;border-radius:50%;background:var(--c3);box-shadow:0 0 4px var(--c3);}
.rpbtn{margin-left:auto;font-family:var(--fmm);font-size:7px;letter-spacing:3px;padding:5px 13px;border-radius:2px;cursor:pointer;background:var(--c1a);border:1px solid rgba(0,229,255,.2);color:var(--c1);text-decoration:none;transition:all .2s;}
.rpbtn:hover{background:rgba(0,229,255,.15);border-color:var(--c1);}
.empty{flex:1;display:flex;flex-direction:column;align-items:center;justify-content:center;gap:6px;}
.ei{font-size:18px;opacity:.12;}.et{font-family:var(--fm);font-size:8px;letter-spacing:4px;color:var(--t3);}
/* intent panel */
.ibox{margin-top:5px;padding:6px 8px;background:rgba(0,180,255,.04);border:1px solid rgba(0,180,255,.1);border-radius:2px;}
.ilbl{font-family:var(--fm);font-size:6px;letter-spacing:3px;color:rgba(0,200,255,.6);text-transform:uppercase;margin-bottom:4px;}
.irow{display:flex;align-items:flex-start;gap:5px;margin-bottom:3px;}
.ik{font-family:var(--fm);font-size:6px;letter-spacing:2px;color:var(--t3);width:30px;flex-shrink:0;text-transform:uppercase;}
.iv{font-family:var(--fm);font-size:7px;color:var(--t1);flex:1;}
.itag2{font-family:var(--fm);font-size:6px;padding:1px 5px;border-radius:2px;margin-right:2px;}
.it-benign{background:rgba(0,220,80,.08);border:1px solid rgba(0,220,80,.15);color:#00dc50;}
.it-low{background:rgba(0,200,180,.08);border:1px solid rgba(0,200,180,.15);color:#00c8b4;}
.it-monitor{background:var(--c1a);border:1px solid rgba(0,229,255,.15);color:var(--c1);}
.it-suspicious{background:var(--c5a);border:1px solid rgba(255,136,0,.2);color:var(--c5);}
.it-high{background:var(--c4a);border:1px solid rgba(255,34,85,.25);color:var(--c4);animation:cg .6s ease infinite alternate;}
.it-threat{background:rgba(120,0,20,.2);border:1px solid rgba(180,0,20,.4);color:#ff2255;animation:cg .4s ease infinite alternate;}
.iscores{display:flex;gap:4px;flex-wrap:wrap;margin-top:3px;}
.iscore{font-family:var(--fm);font-size:6px;padding:1px 4px;border-radius:2px;background:rgba(0,229,255,.05);border:1px solid rgba(0,229,255,.08);color:var(--t3);}
.iscore span{color:var(--t1);}
.ibar{height:2px;background:rgba(0,229,255,.06);border-radius:1px;overflow:hidden;margin-top:4px;}
.ibarfill{height:100%;border-radius:1px;transition:width .6s ease;}
</style>
</head>
<body>
<div id="app">
<header id="hdr">
  <svg class="bsvg" viewBox="0 0 32 32" fill="none">
    <rect x=".5" y=".5" width="31" height="31" rx="3" stroke="#00e5ff" stroke-opacity=".22"/>
    <circle cx="16" cy="16" r="9" stroke="#00e5ff" stroke-opacity=".4" stroke-width="1"/>
    <circle cx="16" cy="16" r="4.5" stroke="#00e5ff" stroke-width="1.1" stroke-opacity=".7"/>
    <circle cx="16" cy="16" r="1.8" fill="#00e5ff" opacity=".9"/>
    <line x1="16" y1="4"  x2="16" y2="8.5" stroke="#00e5ff" stroke-width=".9" stroke-opacity=".5"/>
    <line x1="16" y1="23.5" x2="16" y2="28" stroke="#00e5ff" stroke-width=".9" stroke-opacity=".5"/>
    <line x1="4"  y1="16" x2="8.5"  y2="16" stroke="#00e5ff" stroke-width=".9" stroke-opacity=".5"/>
    <line x1="23.5" y1="16" x2="28" y2="16" stroke="#00e5ff" stroke-width=".9" stroke-opacity=".5"/>
  </svg>
  <div><div class="bnm">ProVisionGuard</div><div class="bvr">ENTERPRISE AI v7.0</div></div>
  <div class="hd"></div>
  <div class="hmet">
    <div class="hm"><div class="hmv" id="h-p" style="color:var(--c1)">0</div><div class="hml">Persons</div></div>
    <div class="hm"><div class="hmv" id="h-t" style="color:var(--c4)">0</div><div class="hml">Threats</div></div>
    <div class="hm"><div class="hmv" id="h-a" style="color:var(--c5)">0</div><div class="hml">Alerts</div></div>
    <div class="hm"><div class="hmv" id="h-f" style="color:var(--c3)">0.0</div><div class="hml">FPS</div></div>
    <div class="hm"><div class="hmv" id="h-c" style="color:var(--c6)">0</div><div class="hml">Crowd</div></div>
  </div>
  <div class="hrgt">
    <div class="chip clive"><div class="pip"></div>LIVE</div>
    <div class="chip cnight" id="nc"><div class="pip"></div>NIGHT</div>
    <div class="chip ccrowd" id="cc2"><div class="pip"></div>CROWD</div>
    <div class="chip cload" id="ldc"><div class="pip"></div><span id="ldtxt">LOADING</span></div>
    <div id="hclk">--:--:--</div>
    <div style="width:1px;height:24px;background:rgba(0,229,255,.07);margin:0 6px"></div>
    <div style="font-family:var(--fm);font-size:7px;letter-spacing:2px;color:var(--t2)">{{ username|upper }}</div>
    <a href="/logout" style="font-family:var(--fm);font-size:7px;letter-spacing:2px;color:var(--c4);text-decoration:none;padding:4px 9px;border:1px solid rgba(255,34,85,.2);border-radius:2px;background:var(--c4a)">EXIT</a>
  </div>
</header>
<div id="mid">
  <!-- Persons -->
  <div class="panel">
    <div class="ph"><svg width="8" height="8" viewBox="0 0 8 8"><circle cx="4" cy="4" r="3" stroke="#00e5ff" fill="none" stroke-width=".8" opacity=".6"/><circle cx="4" cy="4" r="1.2" fill="#00e5ff"/></svg><span class="pht">Active Persons</span><span class="phb" id="pcc">0</span></div>
    <div class="ist"><span class="istlbl">INTEL</span><span id="ptags"></span><span id="wtags"></span></div>
    <div class="pscr" id="plist"><div class="empty" id="pe"><div class="ei">◎</div><div class="et">No Detections</div></div></div>
  </div>
  <!-- Camera 0 -->
  <div class="fp">
    <div class="ph"><div class="frec" style="margin-right:1px"></div><span class="pht">Camera 01 — Primary</span><span class="phb" id="fps0" style="color:var(--c3)">0.0</span></div>
    <div class="fb" id="fb0">
      <div class="hc tl"></div><div class="hc tr"></div><div class="hc bl"></div><div class="hc br"></div>
      <div class="fhud"><div class="frec"></div>CAM-01</div>
      <div class="fts" id="ts0">--:--:--</div>
      <div class="fnv" id="nv0">◉ NIGHT MODE</div>
      <div class="conn" id="cn0"><div class="cr"></div><div class="cbig">CAM-01</div><div class="ctxt">INITIALIZING...</div></div>
      <img id="f0" src="/cam0" style="display:none" onload="this.style.display='block';document.getElementById('cn0').style.display='none'">
    </div>
    <div class="fsb2">
      <div class="fs"><div class="fsv" id="sb-p" style="color:var(--c1)">0</div><div class="fsl">Persons</div></div>
      <div class="fs"><div class="fsv" id="sb-t" style="color:var(--c4)">0</div><div class="fsl">Threats</div></div>
      <div class="fs"><div class="fsv" id="sb-a" style="color:var(--c5)">0</div><div class="fsl">Alerts</div></div>
      <div class="fs"><div class="fsv" id="sb-u" style="color:var(--c3)">00:00</div><div class="fsl">Uptime</div></div>
      <div class="fs"><div class="fsv" id="sb-f" style="color:var(--c6)">0.0</div><div class="fsl">FPS</div></div>
    </div>
  </div>
  <!-- Camera 1 -->
  <div class="fp">
    <div class="ph"><div class="frec" style="margin-right:1px"></div><span class="pht">Camera 02 — Secondary</span><span class="phb" style="color:var(--t2)">STANDBY</span></div>
    <div class="fb" id="fb1">
      <div class="hc tl"></div><div class="hc tr"></div><div class="hc bl"></div><div class="hc br"></div>
      <div class="fhud"><div class="frec"></div>CAM-02</div>
      <div class="fts" id="ts1">--:--:--</div>
      <div class="fnv" id="nv1">◉ NIGHT MODE</div>
      <div class="conn" id="cn1"><div class="cr"></div><div class="cbig">CAM-02</div><div class="ctxt">STANDBY</div></div>
      <img id="f1" src="/cam1" style="display:none" onload="this.style.display='block';document.getElementById('cn1').style.display='none'">
    </div>
    <div class="fsb2">
      <div class="fs"><div class="fsv" style="color:var(--t3)">—</div><div class="fsl">Persons</div></div>
      <div class="fs"><div class="fsv" style="color:var(--t3)">—</div><div class="fsl">Threats</div></div>
      <div class="fs"><div class="fsv" style="color:var(--t3)">—</div><div class="fsl">Alerts</div></div>
      <div class="fs"><div class="fsv" style="color:var(--t3)">—</div><div class="fsl">Night</div></div>
      <div class="fs"><div class="fsv" style="color:var(--t3)">—</div><div class="fsl">FPS</div></div>
    </div>
  </div>
  <!-- Alerts -->
  <div class="panel last">
    <div class="ph"><svg width="8" height="8" viewBox="0 0 8 8"><path d="M4 1L7 7H1z" stroke="#ff2255" fill="rgba(255,34,85,.18)" stroke-width=".8"/></svg><span class="pht">Alert Feed</span><span class="phb" id="acc" style="color:var(--c4);border-color:rgba(255,34,85,.18);background:var(--c4a)">0</span></div>
    <div class="pscr" id="alist"><div class="empty" id="ae"><div class="ei">⬡</div><div class="et">All Clear</div></div></div>
  </div>
</div>
<footer id="ftr">
  <div class="fi"><div class="fdot"></div>System <span>ONLINE</span></div>
  <div class="fi">v<span>6.0</span></div>
  <div class="fi">Uptime <span id="ft-up">00:00:00</span></div>
  <div class="fi" id="ni-ft" style="display:none">Night <span>ON</span></div>
  <div class="fi">Crowd <span id="cr-ft">0</span></div>
  <div class="fi">DB Alerts <span id="ft-db">—</span></div>
  <button class="rpbtn" onclick="openHistory()" style="border:none;cursor:pointer">⊞ HISTORY</button>
  <a class="rpbtn" href="/api/report" target="_blank">↓ PDF REPORT</a>
</footer>
</div>
<!-- ── HISTORY MODAL ───────────────────────────────────── -->
<div id="hist-modal" style="display:none;position:fixed;inset:0;background:rgba(2,4,8,.92);z-index:999;overflow-y:auto;padding:30px 20px;">
  <div style="max-width:900px;margin:0 auto;background:#030810;border:1px solid rgba(0,229,255,.15);border-radius:6px;overflow:hidden;">
    <div style="display:flex;align-items:center;padding:14px 18px;background:#050c18;border-bottom:1px solid rgba(0,229,255,.08);">
      <span style="font-family:'DM Mono',monospace;font-size:8px;letter-spacing:4px;color:#4a7090;text-transform:uppercase;">Alert History — Database</span>
      <button onclick="closeHistory()" style="margin-left:auto;background:rgba(255,34,85,.08);border:1px solid rgba(255,34,85,.2);color:#ff2255;font-family:'DM Mono',monospace;font-size:8px;letter-spacing:2px;padding:5px 12px;border-radius:2px;cursor:pointer;">✕ CLOSE</button>
    </div>
    <div style="padding:10px 14px;display:flex;gap:10px;flex-wrap:wrap;border-bottom:1px solid rgba(0,229,255,.06);" id="db-stats-bar"></div>
    <div style="overflow-x:auto;"><table id="hist-table" style="width:100%;border-collapse:collapse;font-family:'DM Mono',monospace;font-size:9px;">
      <thead><tr style="background:#050c18;color:#4a7090;">
        <th style="padding:8px 12px;text-align:left;letter-spacing:2px;">TIME</th>
        <th style="padding:8px 12px;text-align:left;letter-spacing:2px;">LEVEL</th>
        <th style="padding:8px 12px;text-align:left;letter-spacing:2px;">PERSON</th>
        <th style="padding:8px 12px;text-align:left;letter-spacing:2px;">SCORE</th>
        <th style="padding:8px 12px;text-align:left;letter-spacing:2px;">EMOTION</th>
        <th style="padding:8px 12px;text-align:left;letter-spacing:2px;">BEHAVIORS</th>
        <th style="padding:8px 12px;text-align:left;letter-spacing:2px;">CAM</th>
      </tr></thead>
      <tbody id="hist-body"></tbody>
    </table></div>
  </div>
</div>
<script>
const sk=io();let tot=0;const t0=Date.now();
function tick(){const t=new Date().toLocaleTimeString("en-GB");
  ["hclk","ts0","ts1"].forEach(id=>{const el=document.getElementById(id);if(el)el.textContent=t;});}
setInterval(tick,1000);tick();
function uptime(){let s=Math.floor((Date.now()-t0)/1000);
  const h=Math.floor(s/3600);s%=3600;const m=Math.floor(s/60);s%=60;
  const p=n=>String(n).padStart(2,"0");
  const el1=document.getElementById("sb-u"),el2=document.getElementById("ft-up");
  if(el1)el1.textContent=h?`${p(h)}:${p(m)}:${p(s)}`:`${p(m)}:${p(s)}`;
  if(el2)el2.textContent=`${p(h||0)}:${p(m)}:${p(s)}`;}
setInterval(uptime,1000);
const TL={TRUSTED:"trusted",SAFE:"safe",WATCH:"watch",MEDIUM:"medium",HIGH:"high",CRITICAL:"critical",BLACKLIST:"blacklist"};
function tc(l){return TL[l]||"safe";}
function sc(s){return s>=.82?"#ff2255":s>=.65?"#ff2255":s>=.45?"#ff8800":s>=.28?"#00e5ff":"#00ff9d";}
function cc(c){return{whitelist:"#00ff9d",routine:"#00e5ff",blacklist:"#ff2255",stranger:"#ff8800"}[c]||"#1a3248";}
function sgc(k){return{nervous:"#4a80ff",looking:"#00c8ff",hiding:"#7a40ff",loiter:"#00e0cc",sudden:"#ff8800",following:"#ff40c0",emotion:"#0099ff"}[k]||"#1a3248";}
function ring(s,r=15){const c=21,cf=2*Math.PI*r,d=cf*(1-s),col=sc(s);
  return`<svg width="42" height="42" viewBox="0 0 42 42" style="transform:rotate(-90deg)"><circle cx="${c}" cy="${c}" r="${r}" fill="none" stroke="rgba(255,255,255,.03)" stroke-width="2"/><circle cx="${c}" cy="${c}" r="${r}" fill="none" stroke="${col}" stroke-width="2" stroke-dasharray="${cf.toFixed(1)}" stroke-dashoffset="${d.toFixed(1)}" stroke-linecap="round"/></svg>`;}
sk.on("up",d=>{renderP(d.p||{});updS(d.s||{});(d.a||[]).forEach(addA);});
function renderP(P){
  const list=document.getElementById("plist"),empty=document.getElementById("pe"),ids=Object.keys(P);
  let thr=0;ids.forEach(id=>{if(["HIGH","CRITICAL","BLACKLIST"].includes(P[id].threat_label))thr++;});
  ["h-p","sb-p"].forEach(x=>{const e=document.getElementById(x);if(e)e.textContent=ids.length;});
  ["h-t","sb-t"].forEach(x=>{const e=document.getElementById(x);if(e)e.textContent=thr;});
  const pc=document.getElementById("pcc");if(pc)pc.textContent=ids.length;
  if(!ids.length){empty.style.display="flex";list.querySelectorAll(".pc").forEach(c=>c.remove());return;}
  empty.style.display="none";
  list.querySelectorAll(".pc").forEach(c=>{if(!P[c.dataset.tid])c.remove();});
  ids.forEach(id=>{
    const p=P[id],tcc=tc(p.threat_label),col=sc(p.threat_score||0);
    const sg=p.signals||{},nm=p.name||"STRANGER",catC=cc(p.category||"stranger");
    const sk2=["nervous","looking","hiding","loiter","sudden","following","emotion"];
    const sl=["NERVS","GAZE","HIDE","LOITR","MOVE","FOLO","EMOT"];
    const bH=sk2.map((k,i)=>{const v=(sg[k]||0)*100,c2=sgc(k);
      return`<div class="br"><div class="brl">${sl[i]}</div><div class="brt"><div class="brf" style="width:${v.toFixed(1)}%;background:${c2}"></div></div><div class="brv">${v.toFixed(0)}</div></div>`;}).join("");
    const tr=p.theft_risk||0;
    const tH=tr>0.15?`<div class="trbox"><div class="trlbl">⚠ THEFT ${(tr*100).toFixed(0)}%</div><div class="trbar"><div class="trfill" style="width:${(tr*100).toFixed(1)}%"></div></div></div>`:"";
    const bhH=(p.behaviors||[]).map(b=>{const isT=["Concealing","Rushing","Scouting","THEFT"].some(x=>b.includes(x));return`<span class="beh ${isT?"t":""}">${b}</span>`;}).join("");
    const dist=p.distance||99;const dT=dist<1.2?`<span style="color:var(--c4)">⚠${dist.toFixed(1)}m</span>`:dist<2.5?`<span style="color:var(--c5)">!${dist.toFixed(1)}m</span>`:`<span style="color:var(--c3)">✓${dist.toFixed(1)}m</span>`;
    const inner=`<div class="pct"><div class="pcav">${nm.slice(0,2).toUpperCase()}</div><div style="flex:1;min-width:0"><div class="pcnm">${nm}</div><div class="pcct" style="color:${catC}">${(p.category||"stranger").toUpperCase()} · CAM-0${(p.cam||0)+1}</div></div><div class="tp tp-${tcc}">${p.threat_label||"SAFE"}</div></div>
    <div class="pcb"><div class="rrow"><div class="rw">${ring(p.threat_score||0)}<div class="rp">${((p.threat_score||0)*100).toFixed(0)}</div></div><div class="bset">${bH}</div></div>${tH}${bhH?`<div class="pctags">${bhH}</div>`:""}</div>
    ${intentHTML(p.intent)}
    <div class="pcft"><div class="pft">DIST ${dT}</div><div class="pft">EMO <span>${p.emotion||"–"}</span></div><div class="pft">ID <span>#${id}</span></div></div>`;
    let card=list.querySelector(`[data-tid="${id}"]`);
    if(!card){card=document.createElement("div");card.className="pc";card.dataset.tid=id;list.prepend(card);}
    card.innerHTML=inner;card.style.setProperty("--pcol",col);
  });
}
function addA(a){
  tot++;document.getElementById("ae").style.display="none";
  ["h-a","sb-a","acc"].forEach(x=>{const e=document.getElementById(x);if(e)e.textContent=tot;});
  const col=sc(a.score||0),tcc=tc(a.label);
  const bH=(a.behaviors||[]).map(b=>`<span class="abeh">${b}</span>`).join("");
  const card=document.createElement("div");card.className="ac";card.style.setProperty("--acol",col);
  card.innerHTML=`<div class="acin"><div class="ach"><span class="tp tp-${tcc}">${a.label}</span><span class="actm">${a.time} · CAM-0${(a.cam||0)+1}</span></div><div class="acnm">${a.name||"Unknown"}</div><div class="acmt"><span>${((a.score||0)*100).toFixed(0)}%</span><span>${a.emotion||""}</span><span>${a.dist?a.dist.toFixed(1)+"m":""}</span></div>${bH?`<div class="acbh">${bH}</div>`:""}</div>`;
  document.getElementById("alist").prepend(card);
  const cards=document.getElementById("alist").querySelectorAll(".ac");
  if(cards.length>25)cards[cards.length-1].remove();
}
function updS(s){
  if(s.fps!==undefined){const f=s.fps.toFixed(1);["h-f","sb-f","fps0"].forEach(x=>{const e=document.getElementById(x);if(e)e.textContent=f;});}
  const night=s.night||false;
  const nc=document.getElementById("nc"),ni=document.getElementById("ni-ft"),nv=document.getElementById("nv0");
  if(nc)nc.style.display=night?"flex":"none";
  if(ni)ni.style.display=night?"flex":"none";
  if(nv)nv.style.display=night?"block":"none";
  const crowd=s.crowd||0;
  const hc=document.getElementById("h-c"),cc2=document.getElementById("cc2"),cf=document.getElementById("cr-ft");
  if(hc)hc.textContent=crowd;if(cf)cf.textContent=crowd;
  if(cc2)cc2.style.display=crowd>4?"flex":"none";
  const plates=s.plates||[];const pt=document.getElementById("ptags");
  if(pt)pt.innerHTML=plates.map(p=>`<span class="itag p">🚗 ${p.plate||p}</span>`).join("");
  const wpns=s.weapons||[];const wt=document.getElementById("wtags");
  if(wt)wt.innerHTML=wpns.map(w=>`<span class="itag w">⚠ ${(w.label||w).toUpperCase()}</span>`).join("");
  const ldc=document.getElementById("ldc"),ldtxt=document.getElementById("ldtxt");
  if(s.ready&&ldc){ldc.style.display="none";}
  else if(ldtxt&&!s.ready){ldtxt.textContent=s.status||"LOADING";}
}
// ── Intent Panel ─────────────────────────────────────────
function intentHTML(intent){
  if(!intent) return "";
  const lmap={"BENIGN":"it-benign","LOW RISK":"it-low","MONITORING":"it-monitor",
    "SUSPICIOUS":"it-suspicious","HIGH INTENT RISK":"it-high","KNOWN THREAT":"it-threat"};
  const cls=lmap[intent.label]||"it-monitor";
  const sc=(intent.score||0)*100;
  const barCol=sc>=75?"#ff2255":sc>=55?"#ff8800":sc>=35?"#00e5ff":"#00ff9d";
  const reasons=(intent.reasons||[]).map(r=>`<span class="iscore">${r}</span>`).join("");
  const zones=(intent.top_gaze_zones||[]).map(z=>`<span class="iscore">gaze:${z}</span>`).join("");
  return `<div class="ibox">
    <div class="ilbl">Intent Analysis</div>
    <div class="irow"><div class="ik">WHO</div><div class="iv"><span class="itag2 ${cls}">${intent.who||"Unknown"}</span></div></div>
    <div class="irow"><div class="ik">WHY</div><div class="iv" style="color:var(--c5)">${intent.why||"—"}</div></div>
    <div class="irow"><div class="ik">NEXT</div><div class="iv" style="color:var(--c6)">${intent.next||"—"}</div></div>
    <div class="irow"><div class="ik">PATH</div><div class="iv">${intent.trajectory||"—"}</div></div>
    <div class="ibar"><div class="ibarfill" style="width:${sc.toFixed(1)}%;background:${barCol}"></div></div>
    <div class="iscores" style="margin-top:3px">
      <span class="iscore">stress <span>${((intent.stress||0)*100).toFixed(0)}%</span></span>
      <span class="iscore">gaze <span>${intent.gaze_scans||0}x</span></span>
      <span class="iscore">cam-looks <span>${intent.camera_looks||0}x</span></span>
      <span class="iscore">idle <span>${intent.idle_time||0}s</span></span>
      ${reasons}${zones}
    </div>
  </div>`;
}
// ── DB History Modal ──────────────────────────────────────
function openHistory(){
  document.getElementById("hist-modal").style.display="block";
  fetch("/api/db/stats").then(r=>r.json()).then(s=>{
    const bar=document.getElementById("db-stats-bar");
    const ftdb=document.getElementById("ft-db");
    if(ftdb)ftdb.textContent=s.total_alerts||0;
    bar.innerHTML=[
      ["Total Alerts",s.total_alerts||0,"#00e5ff"],
      ["Critical",s.critical||0,"#ff2255"],
      ["High",s.high||0,"#ff8800"],
      ["Today",s.today_alerts||0,"#00ff9d"],
      ["Unique Plates",s.unique_plates||0,"#ffcc00"]
    ].map(([l,v,c])=>`<div style="background:#070f1e;border:1px solid rgba(0,229,255,.08);border-radius:3px;padding:8px 16px;min-width:100px;">
      <div style="font-family:'DM Mono',monospace;font-size:18px;font-weight:700;color:${c}">${v}</div>
      <div style="font-family:'DM Mono',monospace;font-size:7px;letter-spacing:3px;color:#4a7090;margin-top:2px;text-transform:uppercase">${l}</div>
    </div>`).join("");
  }).catch(()=>{});
  fetch("/api/db/alerts?limit=100").then(r=>r.json()).then(rows=>{
    const tbody=document.getElementById("hist-body");
    const lc={"CRITICAL":"#ff2255","HIGH":"#ff8800","MEDIUM":"#ffcc00","WATCH":"#00e5ff","BLACKLIST":"#ff2255"};
    tbody.innerHTML=rows.map((a,i)=>`<tr style="background:${i%2===0?"#030810":"#040c14"};border-bottom:1px solid rgba(0,229,255,.04);">
      <td style="padding:7px 12px;color:#4a7090">${a.time||a.created_at?.slice(11,19)||"—"}</td>
      <td style="padding:7px 12px;color:${lc[a.label]||"#00e5ff"};font-weight:700">${a.label||"—"}</td>
      <td style="padding:7px 12px;color:#ddeeff">${a.name||"Unknown"}</td>
      <td style="padding:7px 12px;color:#00ff9d">${a.score?Math.round(a.score*100)+"%":"—"}</td>
      <td style="padding:7px 12px;color:#4a7090">${a.emotion||"—"}</td>
      <td style="padding:7px 12px;color:#4a7090;max-width:200px;overflow:hidden;text-overflow:ellipsis">${a.behaviors||"—"}</td>
      <td style="padding:7px 12px;color:#4a7090">CAM-0${(a.cam||0)+1}</td>
    </tr>`).join("");
    if(!rows.length)tbody.innerHTML=`<tr><td colspan="7" style="padding:30px;text-align:center;color:#1a3248;letter-spacing:3px">NO RECORDS FOUND</td></tr>`;
  }).catch(()=>{});
}
function closeHistory(){document.getElementById("hist-modal").style.display="none";}
// Load DB stats on page load
fetch("/api/db/stats").then(r=>r.json()).then(s=>{
  const el=document.getElementById("ft-db");if(el)el.textContent=s.total_alerts||0;
}).catch(()=>{});
</script>
</body>
</html>"""

# ── ENTRY ─────────────────────────────────────────────────
if __name__ == '__main__':
    print("\n" + "="*52)
    print("  ProVisionGuard AI — Enterprise v7.0")
    print("="*52)
    print("  GPU      : RTX 3050 (CUDA auto)")
    print("  Dashboard: http://localhost:5000")
    print("  Login    : admin / pvg@admin123")
    print("            operator / pvg@1234")
    print("  Report   : http://localhost:5000/api/report")
    print("  Status   : http://localhost:5000/api/status")
    print()
    print("  NOTE: No camera popup by default.")
    print("  Set SHOW_WINDOW=True for local preview.")
    print("  Auto-restart: run 'python run_pvg.py'")
    print("="*52 + "\n")

    # AI loads in background — Flask starts immediately
    threading.Thread(target=run_ai, daemon=True).start()

    # Flask starts right away — no waiting
    sio.run(app, host='0.0.0.0', port=5000,
            debug=False, use_reloader=False,
            allow_unsafe_werkzeug=True)