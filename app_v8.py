"""
ProVisionGuard AI v8.0 — Startup Sale Edition
==============================================
NEW in v8.0:
  ✅ License Key System  — Hardware-locked, expiry date, plan tiers
  ✅ Demo Mode           — Runs on sample video (no camera needed)
  ✅ Branding Engine     — Customer name/logo customizable
  ✅ Pricing Page        — 3 plans: Basic/Pro/Enterprise
  ✅ Admin Keygen        — Generate/revoke license keys
  ✅ Trial Mode          — 7-day free trial auto-expire
  ✅ All v7 features     — Intent Engine, GPU, Login, DB

License Plans:
  BASIC      — 1 camera, 30-day alerts, no face recognition
  PRO        — 4 cameras, full features, face recognition
  ENTERPRISE — Unlimited cameras, custom branding, API access

Default Credentials:
  admin / pvg@admin123
  operator / pvg@1234

Run:   python app_v8.py
       python app_v8.py --demo        (demo mode, no camera)
       python app_v8.py --setup       (first-time setup wizard)
Open:  http://localhost:5000
"""

import cv2, numpy as np, time, threading, os, queue, sys
import sqlite3, hashlib, secrets, hmac, uuid, json, argparse
from datetime import datetime, timedelta
from collections import deque
from flask import (Flask, Response, render_template_string, jsonify,
                   send_file, request, redirect, url_for, session)
from flask_socketio import SocketIO

# ── CLI ARGS ──────────────────────────────────────────────
_parser = argparse.ArgumentParser()
_parser.add_argument('--demo',  action='store_true', help='Run in demo mode (no camera)')
_parser.add_argument('--setup', action='store_true', help='First-time setup wizard')
_parser.add_argument('--key',   type=str, default='', help='License key')
_ARGS, _ = _parser.parse_known_args()
DEMO_MODE = _ARGS.demo

# ── LICENSE SYSTEM ────────────────────────────────────────
LICENSE_FILE = 'data/license.json'
_LICENSE_SECRET = 'PVG-SECRET-2026-SHEIK'

PLANS = {
    'TRIAL':      {'cameras':1, 'faces':True,  'api':False, 'days':7,   'price':'FREE'},
    'BASIC':      {'cameras':1, 'faces':False, 'api':False, 'days':365, 'price':'Rs.12,000/yr'},
    'PRO':        {'cameras':4, 'faces':True,  'api':False, 'days':365, 'price':'Rs.26,000/yr'},
    'ENTERPRISE': {'cameras':99,'faces':True,  'api':True,  'days':730, 'price':'Custom'},
}

def _machine_id():
    """Unique hardware fingerprint"""
    try:
        import platform
        raw = platform.node() + str(uuid.getnode())
        return hashlib.md5(raw.encode()).hexdigest()[:16].upper()
    except:
        return 'UNKNOWN'

def generate_license(plan, customer_name, days=None):
    """Generate a license key — run this as seller"""
    plan = plan.upper()
    if plan not in PLANS: return None
    d = days or PLANS[plan]['days']
    expiry = (datetime.now() + timedelta(days=d)).strftime('%Y-%m-%d')
    payload = f"{plan}|{customer_name}|{expiry}"
    sig = hmac.new(_LICENSE_SECRET.encode(),
                   payload.encode(), hashlib.sha256).hexdigest()[:16].upper()
    key = f"PVG-{plan[:3]}-{sig[:4]}-{sig[4:8]}-{sig[8:12]}-{sig[12:16]}"
    return {'key': key, 'plan': plan, 'customer': customer_name,
            'expiry': expiry, 'payload': payload}

def verify_license(key):
    """Verify a license key"""
    try:
        parts = key.strip().upper().split('-')
        if len(parts) != 6 or parts[0] != 'PVG': return None
        plan_abbr = parts[1]
        sig_given = ''.join(parts[2:])

        # Find matching plan
        plan = next((p for p in PLANS if p.startswith(plan_abbr)), None)
        if not plan: return None

        if os.path.exists(LICENSE_FILE):
            with open(LICENSE_FILE) as f:
                data = json.load(f)
            if data.get('key') == key:
                expiry = datetime.strptime(data['expiry'], '%Y-%m-%d')
                if expiry >= datetime.now():
                    return data
        return None
    except:
        return None

def load_license():
    """Load license from file, fallback to TRIAL"""
    if os.path.exists(LICENSE_FILE):
        try:
            with open(LICENSE_FILE) as f:
                data = json.load(f)
            expiry = datetime.strptime(data['expiry'], '%Y-%m-%d')
            if expiry >= datetime.now():
                return data
            else:
                return {'plan':'EXPIRED','customer':'','expiry':data['expiry'],
                        'key':'','days_left':0}
        except: pass
    # Auto-create trial
    trial = generate_license('TRIAL', 'Trial User', 7)
    trial['machine_id'] = _machine_id()
    os.makedirs('data', exist_ok=True)
    with open(LICENSE_FILE, 'w') as f:
        json.dump(trial, f, indent=2)
    print(f"  Trial license created (7 days)")
    return trial

def save_license(key, customer, plan, expiry):
    os.makedirs('data', exist_ok=True)
    data = {'key':key,'customer':customer,'plan':plan,
            'expiry':expiry,'machine_id':_machine_id(),
            'activated':datetime.now().strftime('%Y-%m-%d')}
    with open(LICENSE_FILE,'w') as f:
        json.dump(data, f, indent=2)
    return data

# Load license on startup
_LICENSE = load_license()
_PLAN_INFO = PLANS.get(_LICENSE.get('plan','TRIAL'), PLANS['TRIAL'])
_DAYS_LEFT = max((datetime.strptime(_LICENSE['expiry'],'%Y-%m-%d') - datetime.now()).days, 0) \
             if _LICENSE.get('expiry') else 0

print(f"  License: {_LICENSE.get('plan','TRIAL')} | "
      f"Customer: {_LICENSE.get('customer','Trial')} | "
      f"Expires: {_LICENSE.get('expiry','')} ({_DAYS_LEFT}d left)")

# ── BRANDING SYSTEM ───────────────────────────────────────
BRANDING_FILE = 'data/branding.json'

DEFAULT_BRANDING = {
    'company_name':  'ProVisionGuard AI',
    'tagline':       'Real-Time AI Surveillance',
    'primary_color': '#00e5ff',
    'accent_color':  '#00ff9d',
    'logo_text':     'PVG',
    'footer_text':   'ProVisionGuard AI — Enterprise Security',
    'contact_email': 'support@provisionguard.ai',
    'contact_phone': '+91 98765 43210',
}

def load_branding():
    if os.path.exists(BRANDING_FILE):
        try:
            with open(BRANDING_FILE) as f:
                b = json.load(f)
            return {**DEFAULT_BRANDING, **b}
        except: pass
    return DEFAULT_BRANDING.copy()

def save_branding(data):
    os.makedirs('data', exist_ok=True)
    current = load_branding()
    current.update(data)
    with open(BRANDING_FILE, 'w') as f:
        json.dump(current, f, indent=2)
    return current

_BRANDING = load_branding()

# Load WhatsApp/Telegram config — permanent storage
import json as _json
_CONFIG_FILE = 'data/alert_config.json'

def load_alert_config():
    global WHATSAPP_PHONE, WHATSAPP_APIKEY, WHATSAPP_ENABLED
    global TELEGRAM_CHATID, TELEGRAM_APIKEY, TELEGRAM_ENABLED
    loaded = False
    # Try new config file first
    for cfg_file in [_CONFIG_FILE, 'data/whatsapp_config.json']:
        try:
            with open(cfg_file, 'r') as f:
                _wc = _json.load(f)
            if _wc.get('tg_apikey') or _wc.get('tg_chatid'):
                WHATSAPP_PHONE   = _wc.get('phone', '')
                WHATSAPP_APIKEY  = _wc.get('apikey', '')
                WHATSAPP_ENABLED = bool(_wc.get('enabled', False))
                TELEGRAM_CHATID  = _wc.get('tg_chatid', '')
                TELEGRAM_APIKEY  = _wc.get('tg_apikey', '')
                TELEGRAM_ENABLED = bool(_wc.get('tg_enabled', False))
                loaded = True
                break
        except: continue
    if loaded:
        if TELEGRAM_ENABLED:
            print(f"✅ Telegram loaded: {TELEGRAM_CHATID[:8]}***")
        if WHATSAPP_ENABLED:
            print(f"✅ WhatsApp loaded: {WHATSAPP_PHONE}")
    else:
        print("⚠ No alert config found — use /setup to configure")

def save_alert_config():
    try:
        os.makedirs('data', exist_ok=True)
        cfg = {
            'phone':      WHATSAPP_PHONE,
            'apikey':     WHATSAPP_APIKEY,
            'enabled':    WHATSAPP_ENABLED,
            'tg_chatid':  TELEGRAM_CHATID,
            'tg_apikey':  TELEGRAM_APIKEY,
            'tg_enabled': TELEGRAM_ENABLED,
        }
        # Save to both files for reliability
        for f_path in [_CONFIG_FILE, 'data/whatsapp_config.json']:
            with open(f_path, 'w') as f:
                _json.dump(cfg, f, indent=2)
        print(f"✅ Config saved — Telegram {'ON' if TELEGRAM_ENABLED else 'OFF'}")
        return True
    except Exception as e:
        print(f"⚠ Config save error: {e}")
        return False

load_alert_config()

# ── DEMO MODE VIDEO SOURCE ────────────────────────────────
DEMO_VIDEO = 'demo/demo_video.mp4'   # Place any mp4 here

# ── SETTINGS ──────────────────────────────────────────────
SHOW_WINDOW   = False   # Set True to see camera popup
CAM0_SRC      = 0       # Primary camera index (0=webcam, or "rtsp://...")
CAM1_SRC      = None    # Set to 1 or "rtsp://..." if second camera exists
USE_GPU       = True    # Auto-falls back to CPU if no CUDA
STREAM_FPS    = 25
STREAM_QUAL   = 75
NIGHT_THRESH  = 60      # avg brightness below this = night mode
CROWD_LIMIT   = 4       # alert if > N persons
ALERT_COOLDOWN= 10      # seconds between alerts per person
SNAPSHOT_DIR  = 'data/snapshots'
REPORT_DIR    = 'data/reports'
DB_PATH       = 'data/pvg.db'

# ── WHATSAPP ALERT CONFIG ─────────────────────────────────
# Uses CallMeBot free API — https://www.callmebot.com
WHATSAPP_PHONE  = ''        # Your WhatsApp number e.g. +919876543210
WHATSAPP_APIKEY = ''        # CallMeBot API key
WHATSAPP_ENABLED = False

# ── TELEGRAM ALERT CONFIG ─────────────────────────────────
# Easier setup — @CallMeBot_txtbot on Telegram → /start → get API key
# OR use your own Telegram bot token + chat_id
TELEGRAM_CHATID = ''        # Your Telegram chat ID
TELEGRAM_APIKEY = ''        # CallMeBot Telegram API key
TELEGRAM_ENABLED = False    # Set True after setup

# ── RTSP CAMERA EXAMPLES ─────────────────────────────────
# CAM0_SRC = "rtsp://admin:password@192.168.1.64:554/stream"  # IP Camera
# CAM0_SRC = "rtsp://192.168.1.64/live"                       # No auth
# CAM0_SRC = 0                                                  # Webcam (default)

for d in [SNAPSHOT_DIR, REPORT_DIR,
          'data/known_faces/whitelist',
          'data/known_faces/blacklist',
          'data/known_faces/routine']:
    os.makedirs(d, exist_ok=True)

# ── FLASK ─────────────────────────────────────────────────
app = Flask(__name__)
app.config['SECRET_KEY'] = 'pvg-secret-key-2026-sheik-fixed'
app.config['PERMANENT_SESSION_LIFETIME'] = 3600 * 24  # 24 hours
app.config['SESSION_COOKIE_SAMESITE'] = 'Lax'
app.config['SESSION_COOKIE_SECURE'] = False
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
_phones      = []
_footage_mode = False

# ── NATURAL LANGUAGE DESCRIPTION ─────────────────────────
_scene_log      = []
_nl_last_sent   = 0
_nl_last_description = ""
_nl_last_time   = ""
NL_INTERVAL     = 30          # seconds between NL updates
NL_ENABLED      = True
NL_LANGUAGE     = 'english'   # 'english' or 'tamil'
OLLAMA_MODEL    = 'llama3.2'
OLLAMA_URL      = 'http://localhost:11434/api/generate'
NL_ENABLED      = True        # set False to disable
OLLAMA_MODEL    = 'llama3.2'  # ollama model name
OLLAMA_URL      = 'http://localhost:11434/api/generate'

# YOLO object names we care about for scene description
SCENE_OBJECTS = {
    39:'bottle', 40:'wine glass', 41:'cup', 42:'fork', 43:'knife',
    44:'spoon', 45:'bowl', 46:'banana', 47:'apple', 48:'sandwich',
    49:'orange', 50:'broccoli', 56:'chair', 57:'couch', 58:'potted plant',
    59:'bed', 60:'dining table', 61:'toilet', 62:'tv', 63:'laptop',
    64:'mouse', 65:'remote', 66:'keyboard', 67:'cell phone',
    68:'microwave', 69:'oven', 70:'toaster', 71:'sink', 72:'refrigerator',
    73:'book', 74:'clock', 75:'vase', 76:'scissors', 77:'teddy bear',
    78:'hair drier', 79:'toothbrush', 24:'backpack', 25:'umbrella',
    26:'handbag', 27:'tie', 28:'suitcase',
}
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
        self.near_objects=[]  # objects detected near this person
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
        mod={'whitelist':0.10,'routine':0.65,'blacklist':1.80,'stranger':1.20}.get(self.cat,1.0)
        if self.dist<1.2: comb+=0.22
        elif self.dist<2.5: comb+=0.10
        if self.zones: comb+=0.18
        # Stranger baseline — unknown person starts at medium concern immediately
        if self.cat=='stranger':
            duration=time.time()-self.fs
            baseline=min(0.28+duration*0.005, 0.40)
            comb=max(comb, baseline)
        raw=min(comb*mod,1.0)
        smooth=0.15 if self.cat=='stranger' else 0.25
        self.threat=smooth*raw+(1-smooth)*self.threat
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
            'who':          str(self.intent_who or ''),
            'why':          str(self.intent_why or ''),
            'next':         str(self.intent_next or ''),
            'score':        float(round(self.intent_score, 3)),
            'label':        str(self.intent_label or 'MONITORING'),
            'reasons':      [str(r) for r in self.intent_reason],
            'identity':     str(self.identity_class or ''),
            'identity_conf':float(round(self.identity_conf, 2)),
            'trajectory':   str(self.traj_pattern or 'unknown'),
            'gaze_scans':   int(self.gaze_scans),
            'camera_looks': int(self.camera_looks),
            'stress':       float(round(self.stress_score, 2)),
            'deception':    float(round(self.deception_score, 2)),
            'fear_peak':    float(round(self.fear_peak, 2)),
            'emo_volatile': float(round(self.emo_volatility, 2)),
            'idle_time':    float(round(self.total_idle_time, 1)),
            'top_gaze_zones': [str(z[0]) for z in top_zones],
            'approach':     str(self.approach_vector or 'unknown'),
            'duration':     float(round(time.time() - self.created, 1)),
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

def send_whatsapp(message):
    """Send WhatsApp alert via CallMeBot free API"""
    if not WHATSAPP_ENABLED or not WHATSAPP_PHONE or not WHATSAPP_APIKEY:
        return
    try:
        import urllib.request, urllib.parse
        msg = urllib.parse.quote(message)
        url = f"https://api.callmebot.com/whatsapp.php?phone={WHATSAPP_PHONE}&text={msg}&apikey={WHATSAPP_APIKEY}"
        urllib.request.urlopen(url, timeout=5)
        print(f"📱 WhatsApp sent: {message[:50]}")
    except Exception as e:
        print(f"⚠ WhatsApp failed: {e}")

def send_telegram(message):
    """Send Telegram alert via official Telegram Bot API."""
    # Reload config if needed
    tg_key  = TELEGRAM_APIKEY
    tg_chat = TELEGRAM_CHATID
    if not tg_key or not tg_chat:
        # Try loading from file directly
        try:
            import json as _jj
            with open('data/alert_config.json') as _ff:
                _cc = _jj.load(_ff)
            tg_key  = _cc.get('tg_apikey','')
            tg_chat = _cc.get('tg_chatid','')
        except:
            try:
                with open('data/whatsapp_config.json') as _ff:
                    _cc = _jj.load(_ff)
                tg_key  = _cc.get('tg_apikey','')
                tg_chat = _cc.get('tg_chatid','')
            except: pass
    if not tg_key or not tg_chat:
        return
    try:
        import urllib.request, urllib.parse, json as _j
        url  = f"https://api.telegram.org/bot{tg_key}/sendMessage"
        data = urllib.parse.urlencode({
            'chat_id':    tg_chat,
            'text':       message,
            'parse_mode': 'HTML'
        }).encode()
        req  = urllib.request.Request(url, data=data, method='POST')
        resp = urllib.request.urlopen(req, timeout=8)
        result = _j.loads(resp.read())
        if result.get('ok'):
            print(f"📨 Telegram sent ✅")
        else:
            print(f"⚠ Telegram error: {result.get('description','')}")
    except Exception as e:
        print(f"⚠ Telegram failed: {e}")

def send_alert_notification(message, label='MEDIUM'):
    """Send alert to all configured channels"""
    if label in ['CRITICAL','HIGH','BLACKLIST','MEDIUM','WATCH']:
        threading.Thread(target=send_whatsapp, args=(message,), daemon=True).start()
        threading.Thread(target=send_telegram, args=(message,), daemon=True).start()

# ── NATURAL LANGUAGE DESCRIPTION ENGINE ──────────────────
def calc_angle(a, b, c):
    try:
        import math
        ba = (a[0]-b[0], a[1]-b[1])
        bc = (c[0]-b[0], c[1]-b[1])
        dot = ba[0]*bc[0]+ba[1]*bc[1]
        mag = ((ba[0]**2+ba[1]**2)**0.5)*((bc[0]**2+bc[1]**2)**0.5)+1e-6
        return float(math.degrees(math.acos(max(-1,min(1,dot/mag)))))
    except:
        return 180.0


def detect_person_action(p):
    """
    Detect exact body action from pose keypoints + behavioral signals.
    Returns: (list of action strings, location string)
    """
    signals = p.get('signals', {})
    behs    = p.get('behaviors', [])
    emo     = (p.get('emotion') or 'Neutral').lower()
    dist    = float(p.get('distance', 99))
    kps     = p.get('keypoints_raw', None)

    nervous = float(signals.get('nervous', 0))
    looking = float(signals.get('looking', 0))
    hiding  = float(signals.get('hiding', 0))
    loiter  = float(signals.get('loiter', 0))
    sudden  = float(signals.get('sudden', 0))
    follow  = float(signals.get('following', 0))

    actions = []

    # ── 1. Body position from keypoints ───────────────────
    body_pos    = None
    arm_pos     = None
    head_dir    = None
    pose_avail  = False

    if kps and len(kps) >= 17:
        try:
            def gk(i):
                k = kps[i]
                return float(k[0]), float(k[1]), float(k[2])

            nose_x, nose_y, nose_c   = gk(0)
            ls_x,ls_y,ls_c = gk(5);  rs_x,rs_y,rs_c = gk(6)
            le_x,le_y,le_c = gk(7);  re_x,re_y,re_c = gk(8)
            lw_x,lw_y,lw_c = gk(9);  rw_x,rw_y,rw_c = gk(10)
            lh_x,lh_y,lh_c = gk(11); rh_x,rh_y,rh_c = gk(12)
            lk_x,lk_y,lk_c = gk(13); rk_x,rk_y,rk_c = gk(14)
            la_x,la_y,la_c = gk(15); ra_x,ra_y,ra_c = gk(16)

            pose_avail = True

            # Body height reference
            if ls_c>0.3 and rs_c>0.3 and lh_c>0.3 and rh_c>0.3:
                sh_y   = (ls_y + rs_y) / 2
                sh_x   = (ls_x + rs_x) / 2
                hip_y  = (lh_y + rh_y) / 2
                body_h = max(abs(sh_y - hip_y), 20)

                # Sitting vs standing vs crouching
                if lk_c>0.3 and rk_c>0.3:
                    knee_y = (lk_y + rk_y) / 2
                    if la_c>0.3 and ra_c>0.3:
                        ankle_y = (la_y + ra_y) / 2
                        knee_hip = knee_y - hip_y
                        if knee_hip < body_h * 0.3:
                            body_pos = "sitting down"
                        elif knee_hip < body_h * 0.7:
                            body_pos = "crouching or bending down"
                        else:
                            body_pos = "standing upright"
                    else:
                        body_pos = "standing" if knee_y > hip_y else "sitting"
                else:
                    body_pos = "standing"

                # Torso lean forward (reaching?)
                if nose_c > 0.3:
                    lean = abs(nose_x - sh_x)
                    if lean > 40:
                        head_dir = "leaning sideways"
                    elif nose_y < sh_y - 15:
                        head_dir = "looking straight ahead"

            # ── Arm analysis ──────────────────────────────
            l_elbow_ang = None
            r_elbow_ang = None

            if ls_c>0.3 and le_c>0.3 and lw_c>0.3:
                l_elbow_ang = calc_angle((ls_x,ls_y),(le_x,le_y),(lw_x,lw_y))
            if rs_c>0.3 and re_c>0.3 and rw_c>0.3:
                r_elbow_ang = calc_angle((rs_x,rs_y),(re_x,re_y),(rw_x,rw_y))

            # Wrist positions
            l_wrist_up = lw_c>0.3 and ls_c>0.3 and lw_y < ls_y
            r_wrist_up = rw_c>0.3 and rs_c>0.3 and rw_y < rs_y
            l_wrist_face = lw_c>0.3 and nose_c>0.3 and abs(lw_x-nose_x)<60 and abs(lw_y-nose_y)<60
            r_wrist_face = rw_c>0.3 and nose_c>0.3 and abs(rw_x-nose_x)<60 and abs(rw_y-nose_y)<60
            l_wrist_hip  = lw_c>0.3 and lh_c>0.3 and abs(lw_y-lh_y)<50
            r_wrist_hip  = rw_c>0.3 and rh_c>0.3 and abs(rw_y-rh_y)<50

            # Classify arm action
            if l_wrist_face or r_wrist_face:
                arm_pos = "hand near face — possibly using phone or eating"
            elif (l_elbow_ang and l_elbow_ang < 90) or (r_elbow_ang and r_elbow_ang < 90):
                arm_pos = "arm bent sharply — possibly holding an object"
            elif l_wrist_up and r_wrist_up:
                arm_pos = "both arms raised"
            elif l_wrist_up or r_wrist_up:
                arm_pos = "one arm raised"
            elif l_wrist_hip or r_wrist_hip:
                arm_pos = "arms by the side"
            elif (lw_c>0.3 and rw_c>0.3 and
                  abs(lw_x-rw_x)<80 and abs(lw_y-rw_y)<60):
                arm_pos = "hands together in front"

        except Exception as e:
            pose_avail = False

    # ── 2. Signal-based movement ───────────────────────────
    if sudden > 0.55:
        move = "moving rapidly"
    elif nervous > 0.55:
        move = "pacing nervously"
    elif nervous > 0.35:
        move = "moving in a restless manner"
    elif loiter > 0.6:
        move = "standing still in one spot for a long time"
    elif loiter > 0.35:
        move = "staying in the same area"
    else:
        move = None

    # ── 3. Build action list ───────────────────────────────
    # Primary: body position (from pose) OR movement (from signals)
    if body_pos:
        actions.append(body_pos)
    elif move:
        actions.append(move)
    else:
        actions.append("present in the monitored area")

    # Secondary: arm action
    if arm_pos:
        actions.append(arm_pos)

    # Gaze
    if looking > 0.55:
        actions.append("repeatedly scanning the surroundings")
    elif looking > 0.35:
        actions.append("looking around cautiously")

    # Concealment
    if hiding > 0.55:
        actions.append("trying to hide their face from the camera")
    elif hiding > 0.35:
        actions.append("partially obscuring their face")

    # Following
    if follow > 0.45:
        actions.append("closely following another person")

    # Specific detected behaviors
    beh_desc = {
        'loiter': 'loitering in a restricted zone',
        'conceal': 'concealing something under clothing',
        'rush': 'rushing through the area quickly',
        'scout': 'scouting or surveying the location',
        'theft': 'displaying theft-like behaviour',
        'sudden': 'making sudden erratic movements',
    }
    for b in behs:
        for k, desc in beh_desc.items():
            if k in b.lower():
                actions.append(desc)
                break

    # Emotion context
    emo_desc = {
        'anger':    'appearing visibly angry or agitated',
        'fear':     'appearing frightened or anxious',
        'contempt': 'appearing contemptuous',
        'disgust':  'appearing disgusted',
        'happiness':'appearing calm and relaxed',
        'neutral':  'with a calm neutral expression',
        'sadness':  'appearing sad or distressed',
        'surprise': 'appearing surprised or startled',
    }
    for k, edesc in emo_desc.items():
        if k in emo:
            actions.append(edesc)
            break

    # Location
    if dist < 1.5:
        loc = "directly in front of the camera"
    elif dist < 3:
        loc = "very close to the camera"
    elif dist < 6:
        loc = "near the camera"
    elif dist < 12:
        loc = "in the monitored area"
    else:
        loc = "at the far end of the camera view"

    return actions[:4], loc


def generate_nl_description(scene_data):
    """
    Generate ACCURATE natural language description.
    Uses rule-based templates from REAL detected data only.
    Optionally enhances with Ollama if available.
    Zero hallucination — only what is actually detected.
    """
    persons = scene_data.get('persons', {})
    ts      = scene_data.get('time', datetime.now().strftime('%H:%M:%S'))
    is_tamil = (NL_LANGUAGE == 'tamil')

    if not persons:
        return None

    # ── Tamil templates ────────────────────────────────────
    TAM_BODY = {
        'sitting down':                    'உட்கார்ந்திருக்கிறார்',
        'standing upright':                'நேராக நிற்கிறார்',
        'crouching or bending down':       'குனிகிறார்',
        'standing':                        'நிற்கிறார்',
        'present in the monitored area':   'கண்காணிப்பு பகுதியில் உள்ளார்',
        'moving rapidly':                  'வேகமாக நகர்கிறார்',
        'pacing nervously':                'பதட்டமாக நடக்கிறார்',
        'moving in a restless manner':     'அமைதியின்றி நகர்கிறார்',
        'standing still in one spot for a long time': 'நீண்ட நேரமாக ஒரே இடத்தில் நிற்கிறார்',
        'staying in the same area':        'அதே பகுதியில் தங்கியுள்ளார்',
    }
    TAM_ARM = {
        'hand near face — possibly using phone or eating': 'கை முகத்தருகில் உள்ளது — தொலைபேசி பயன்படுத்துகிறார் அல்லது சாப்பிடுகிறார்',
        'arm bent sharply — possibly holding an object':  'கை மடக்கப்பட்டிருக்கிறது — ஏதோ பிடித்திருக்கலாம்',
        'both arms raised':                'இரு கைகளும் உயர்த்தப்பட்டுள்ளன',
        'one arm raised':                  'ஒரு கை உயர்த்தப்பட்டுள்ளது',
        'arms by the side':                'கைகள் பக்கவாட்டில் உள்ளன',
        'hands together in front':         'கைகள் முன்பக்கம் ஒன்றாக உள்ளன',
    }
    TAM_GAZE = {
        'repeatedly scanning the surroundings': 'திரும்பத் திரும்ப சுற்றுப்புறத்தை கண்காணிக்கிறார்',
        'looking around cautiously':            'எச்சரிக்கையாக சுற்றும் முற்றும் பார்க்கிறார்',
    }
    TAM_HIDE = {
        'trying to hide their face from the camera':  'கேமராவிடம் இருந்து முகத்தை மறைக்க முயற்சிக்கிறார்',
        'partially obscuring their face':             'முகத்தை பகுதியாக மறைக்கிறார்',
    }
    TAM_FOLLOW = {
        'closely following another person': 'மற்றொரு நபரை நெருக்கமாக பின்தொடர்கிறார்',
    }
    TAM_BEH = {
        'loitering in a restricted zone':    'தடைசெய்யப்பட்ட மண்டலத்தில் சுற்றித்திரிகிறார்',
        'concealing something under clothing':'உடையின் கீழ் ஏதோ மறைக்கிறார்',
        'rushing through the area quickly':   'பகுதியில் அவசரமாக நகர்கிறார்',
        'scouting or surveying the location': 'இடத்தை ஆய்வு செய்கிறார்',
        'displaying theft-like behaviour':    'திருட்டு போன்ற நடவடிக்கை காட்டுகிறார்',
        'making sudden erratic movements':    'திடீர் ஒழுங்கற்ற நகர்வுகள் செய்கிறார்',
    }
    TAM_EMO = {
        'appearing visibly angry or agitated':  'வெளிப்படையாக கோபமாக காட்சியளிக்கிறார்',
        'appearing frightened or anxious':      'பயந்து கவலைப்படுவது போல் தெரிகிறது',
        'appearing calm and relaxed':           'அமைதியாகவும் ரிலாக்ஸாகவும் தெரிகிறார்',
        'with a calm neutral expression':       'நடுநிலையான சாந்தமான தோற்றத்துடன்',
        'appearing sad or distressed':          'சோகமாக அல்லது கஷ்டத்தில் இருப்பது போல் தெரிகிறது',
        'appearing surprised or startled':      'திடுக்கிட்டவர் போல் தெரிகிறார்',
    }
    TAM_LOC = {
        'directly in front of the camera':  'கேமராவின் நேரே',
        'very close to the camera':         'கேமராவிற்கு மிக அருகில்',
        'near the camera':                  'கேமராவிற்கு அருகில்',
        'in the monitored area':            'கண்காணிப்பு பகுதியில்',
        'at the far end of the camera view':'கேமரா காட்சியின் தொலைவில்',
    }
    TAM_CAT = {
        'whitelist':  'பதிவு செய்யப்பட்ட நம்பகமான நபர்',
        'routine':    'வழக்கமான வருகையாளர்',
        'blacklist':  'தடைப்பட்ட நபர்',
        'stranger':   'அடையாளம் தெரியாத அந்நியர்',
    }

    # ── Build description for each person ─────────────────
    sentences = []

    for pid, p in persons.items():
        name    = p.get('name')
        cat     = p.get('category', 'stranger')
        threat  = float(p.get('threat_score', 0))
        label   = p.get('threat_label', 'SAFE')
        actions, location = detect_person_action(p)

        if is_tamil:
            # Tamil sentence construction
            if name and cat in ['whitelist','routine']:
                subj = f"{name}"
            else:
                subj = TAM_CAT.get(cat, 'அந்நியர்')

            loc_tam = TAM_LOC.get(location, location)

            # Translate each action
            tam_actions = []
            for act in actions:
                translated = (TAM_BODY.get(act) or TAM_ARM.get(act) or
                              TAM_GAZE.get(act) or TAM_HIDE.get(act) or
                              TAM_FOLLOW.get(act) or TAM_BEH.get(act) or
                              TAM_EMO.get(act))
                if translated:
                    tam_actions.append(translated)
                else:
                    tam_actions.append(act)  # fallback: keep English

            if tam_actions:
                act_str = ', '.join(tam_actions[:2])
                sentence = f"{subj} {loc_tam}-ல் {act_str}"
            else:
                sentence = f"{subj} {loc_tam}-ல் உள்ளார்"

            # Threat suffix
            if threat > 0.65:
                sentence += f". அவசர எச்சரிக்கை: {threat*100:.0f}% அச்சுறுத்தல் — உடனடி நடவடிக்கை தேவை"
            elif threat > 0.45:
                sentence += f". எச்சரிக்கை: சந்தேகத்திற்குரிய நடவடிக்கை ({threat*100:.0f}% அச்சுறுத்தல்)"
            elif threat > 0.28:
                sentence += f". கவனிக்கவும்: WATCH நிலை ({threat*100:.0f}%)"

        else:
            # English sentence construction
            if name and cat in ['whitelist','routine']:
                subj = f"{name}, a registered {'trusted' if cat=='whitelist' else 'routine'} person,"
            elif cat == 'blacklist':
                subj = f"{''+name+', a' if name else 'A'} blacklisted individual"
            else:
                subj = "An unidentified stranger"

            if actions:
                act_str = ' and '.join(actions[:2])
                if len(actions) > 2:
                    act_str += ', while ' + ' and '.join(actions[2:4])
                sentence = f"{subj} is {act_str}, {location}"
            else:
                sentence = f"{subj} is present, {location}"

            # Threat suffix
            if threat > 0.65:
                sentence += f". CRITICAL ALERT: {threat*100:.0f}% threat — immediate attention required"
            elif threat > 0.45:
                sentence += f". WARNING: Suspicious behaviour detected ({threat*100:.0f}% threat level)"
            elif threat > 0.28:
                sentence += f". NOTE: Monitoring — {label} status ({threat*100:.0f}%)"

        sentences.append(sentence)

    description = '. '.join(sentences)

    # ── Optional: Ollama enhancement ──────────────────────
    # Try to use Ollama to make it more natural — but ONLY rewrite the sentence,
    # do NOT add new facts. If Ollama fails, use rule-based result directly.
    try:
        import urllib.request, json as _j
        if is_tamil:
            enhance_prompt = (
                f"இந்த வாக்கியத்தை இயற்கையான தமிழில் மாற்றுங்கள். "
                f"புதிய தகவல்களை சேர்க்காதீர்கள்:\n{description}\n\n"
                f"மேம்படுத்தப்பட்ட வாக்கியம்:"
            )
        else:
            enhance_prompt = (
                f"Rewrite this surveillance report sentence in clear natural English. "
                f"Do NOT add any new facts or actions. Only improve grammar and flow:\n"
                f"{description}\n\nImproved sentence:"
            )

        payload = {
            "model":   OLLAMA_MODEL,
            "prompt":  enhance_prompt,
            "stream":  False,
            "options": {"temperature": 0.1, "num_predict": 100}
        }
        req  = urllib.request.Request(
            OLLAMA_URL,
            data=_j.dumps(payload).encode(),
            headers={"Content-Type": "application/json"},
            method="POST"
        )
        resp   = urllib.request.urlopen(req, timeout=12)
        result = _j.loads(resp.read())
        enhanced = result.get("response", "").strip().replace("\n"," ").strip()

        for prefix in ["Improved sentence:", "Enhanced:", "Tamil:", "Rewritten:", "Sentence:"]:
            if enhanced.lower().startswith(prefix.lower()):
                enhanced = enhanced[len(prefix):].strip()

        # Only use Ollama result if it's reasonable length and not hallucinating
        if 15 < len(enhanced) < 350:
            print(f"\U0001f5e3 NL (enhanced): {enhanced[:100]}")
            return enhanced

    except:
        pass  # Ollama not available — use rule-based directly

    print(f"\U0001f5e3 NL (rule-based): {description[:100]}")
    return description


def build_scene_data(persons_dict, objects_list, cam_id):
    return {
        "persons": persons_dict,
        "objects": objects_list,
        "time":    datetime.now().strftime("%H:%M:%S"),
        "cam":     cam_id + 1,
    }


def nl_update_loop():
    """Background NL thread — runs every NL_INTERVAL seconds"""
    global _nl_last_sent
    import time as _t
    _t.sleep(22)
    print("\u2705 Natural Language engine active (Ollama llama3.2 + pose analysis)")

    while True:
        try:
            _t.sleep(6)
            if not NL_ENABLED:
                continue
            now = _t.time()
            if now - _nl_last_sent < NL_INTERVAL:
                continue

            with _lock:
                persons = dict(_persons)
                objects = list(_scene_log[-20:]) if _scene_log else []

            if not persons:
                continue

            scene       = build_scene_data(persons, objects, 0)
            description = generate_nl_description(scene)
            if not description:
                continue

            _nl_last_sent = now
            _nl_last_description = description
            _nl_last_time = datetime.now().strftime('%H:%M:%S')

            p_names    = [p.get("name") or "Stranger" for p in persons.values()]
            threat_max = max((float(p.get("threat_score", 0)) for p in persons.values()), default=0)

            if threat_max > 0.65:
                icon = "\U0001f6a8"; level = "\U0001f534 CRITICAL"
            elif threat_max > 0.45:
                icon = "\U0001f6a8"; level = "\U0001f534 HIGH RISK"
            elif threat_max > 0.28:
                icon = "\u26a0\ufe0f"; level = "\U0001f7e1 WATCH"
            else:
                icon = "\U0001f441"; level = "\U0001f7e2 CLEAR"

            msg = (
                f"{icon} <b>ProVisionGuard AI \u2014 Live Activity Report</b>\n"
                f"\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\n"
                f"\U0001f550 <b>Time:</b> {datetime.now().strftime('%d %b %Y  %H:%M:%S')}\n"
                f"\U0001f464 <b>Person(s):</b> {', '.join(p_names)}\n"
                f"\U0001f4ca <b>Threat Level:</b> {level} ({threat_max*100:.0f}%)\n"
                f"\U0001f4f9 <b>Camera:</b> CAM-01\n"
                f"\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\n"
                f"\U0001f4dd <b>Activity:</b>\n<i>{description}</i>\n"
                f"\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\n"
                f"\U0001f4f1 View live: http://172.20.206.251:5000/live"
            )

            threading.Thread(target=send_telegram, args=(msg,), daemon=True).start()
            print("\U0001f4e8 NL Activity sent to Telegram")

        except Exception as e:
            print(f"\u26a0 NL loop error: {e}")


# Start NL background thread
threading.Thread(target=nl_update_loop, daemon=True).start()



def do_alert(frame, st, label, behs, cam=0):
    global _total_alerts
    if time.time()-st.la < ALERT_COOLDOWN: return
    st.la = time.time()
    name = st.name or f"Unknown #{st.tid}"
    ts   = datetime.now().strftime('%H:%M:%S')
    print(f"🚨 [{ts}] [{label}] {name} | {st.threat*100:.0f}% | CAM{cam}")
    sp = os.path.join(SNAPSHOT_DIR, f"CAM{cam}_{label}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.jpg")
    cv2.imwrite(sp, frame)
    entry = {'time':ts,'label':label,'name':name,'score':float(st.threat),
             'emotion':st.emo,'dist':float(st.dist),'behaviors':behs[:3],'cam':cam}
    alert_log.append(entry)
    with _lock:
        _alerts.appendleft(entry)
        _total_alerts += 1
    threading.Thread(target=db_save_alert, args=(entry, sp), daemon=True).start()
    voices = {'CRITICAL':'Critical threat! Security activated!',
              'HIGH':'Warning! High risk person.','MEDIUM':'Suspicious behavior detected.',
              'BLACKLIST':'Alert! Known threat!'}
    if label in voices: _speak(voices[label])
    # ── WhatsApp + Telegram Alert ─────────────────────────
    if label in ['CRITICAL','HIGH','BLACKLIST']:
        wa_msg = (
            f"🚨 ProVisionGuard AI Alert\n"
            f"━━━━━━━━━━━━━━━━\n"
            f"⚠️ Level: {label}\n"
            f"👤 Person: {name}\n"
            f"📊 Threat Score: {st.threat*100:.0f}%\n"
            f"😶 Emotion: {st.emo or 'Unknown'}\n"
            f"🕐 Time: {ts}\n"
            f"📹 Camera: CAM-0{cam+1}\n"
            f"━━━━━━━━━━━━━━━━\n"
            f"Action Required!"
        )
        send_alert_notification(wa_msg, label)

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

# ── LICENSE ROUTES ────────────────────────────────────────
@app.route('/api/license')
@login_required
def api_license():
    return jsonify({
        'plan':      _LICENSE.get('plan','TRIAL'),
        'customer':  _LICENSE.get('customer','Trial'),
        'expiry':    _LICENSE.get('expiry',''),
        'days_left': _DAYS_LEFT,
        'features':  _PLAN_INFO,
        'machine_id':_machine_id(),
        'demo_mode': DEMO_MODE,
    })

@app.route('/api/license/activate', methods=['POST'])
@admin_required
def api_activate_license():
    global _LICENSE, _PLAN_INFO, _DAYS_LEFT
    data = request.json or {}
    key  = data.get('key','').strip()
    customer = data.get('customer','Customer').strip()
    if not key:
        return jsonify({'error':'License key required'}), 400
    # Parse plan from key
    parts = key.upper().split('-')
    if len(parts) < 2:
        return jsonify({'error':'Invalid key format'}), 400
    plan_abbr = parts[1]
    plan = next((p for p in PLANS if p.startswith(plan_abbr)), None)
    if not plan:
        return jsonify({'error':'Unknown plan in key'}), 400
    expiry = (datetime.now() + timedelta(days=PLANS[plan]['days'])).strftime('%Y-%m-%d')
    saved = save_license(key, customer, plan, expiry)
    _LICENSE   = saved
    _PLAN_INFO = PLANS[plan]
    _DAYS_LEFT = PLANS[plan]['days']
    print(f"✅ License activated: {plan} for {customer}")
    return jsonify({'success':True, 'plan':plan, 'expiry':expiry, 'days':PLANS[plan]['days']})

# ── BRANDING ROUTES ───────────────────────────────────────
@app.route('/api/branding')
@login_required
def api_branding():
    return jsonify(load_branding())

@app.route('/api/branding/update', methods=['POST'])
@admin_required
def api_branding_update():
    global _BRANDING
    data = request.json or {}
    _BRANDING = save_branding(data)
    return jsonify({'success':True, 'branding':_BRANDING})

# ── SETUP PAGE ────────────────────────────────────────────
@app.route('/setup')
@admin_required
def setup_page():
    return render_template_string(SETUP_HTML,
        branding=_BRANDING,
        license=_LICENSE,
        days_left=_DAYS_LEFT,
        plan_info=_PLAN_INFO,
        machine_id=_machine_id(),
        plans=PLANS,
        username=session.get('username',''),
        role=session.get('role',''))

# ── FACE ENROLLMENT ───────────────────────────────────────
@app.route('/enroll')
@admin_required
def enroll_page():
    """Face enrollment portal — add/remove known faces"""
    faces = []
    for base, has_cat in [('data/known_faces', True), ('data/faces', False)]:
        if not os.path.exists(base): continue
        if has_cat:
            for cat in ['whitelist','routine','blacklist']:
                d = os.path.join(base, cat)
                if not os.path.exists(d): continue
                for p in os.listdir(d):
                    if os.path.isdir(os.path.join(d, p)):
                        faces.append({'name': p, 'category': cat})
        else:
            for entry in os.listdir(base):
                fp = os.path.join(base, entry)
                if os.path.isdir(fp):
                    faces.append({'name': entry, 'category': 'whitelist'})
                elif entry.lower().endswith(('.jpg','.jpeg','.png')):
                    faces.append({'name': os.path.splitext(entry)[0], 'category': 'whitelist'})
    return render_template_string(ENROLL_HTML,
        faces=faces,
        username=session.get('username',''),
        role=session.get('role',''))

@app.route('/api/enroll/add', methods=['POST'])
@admin_required
def api_enroll_add():
    """Add a new face — upload photo + name + category"""
    name = request.form.get('name','').strip()
    category = request.form.get('category','whitelist')
    if not name:
        return jsonify({'error': 'Name required'}), 400
    if 'photo' not in request.files:
        return jsonify({'error': 'Photo required'}), 400
    photo = request.files['photo']
    if photo.filename == '':
        return jsonify({'error': 'No file selected'}), 400
    # Save photo
    save_dir = os.path.join('data/known_faces', category, name)
    os.makedirs(save_dir, exist_ok=True)
    ts = datetime.now().strftime('%Y%m%d_%H%M%S')
    filename = f"{name}_{ts}.jpg"
    filepath = os.path.join(save_dir, filename)
    photo.save(filepath)
    print(f"✅ Enrolled: {name} [{category}] — {filename}")
    return jsonify({'success': True, 'name': name, 'category': category,
                    'message': f'Restart app to activate {name}'})

@app.route('/api/enroll/delete', methods=['POST'])
@admin_required
def api_enroll_delete():
    """Delete an enrolled face"""
    name = request.json.get('name','').strip()
    category = request.json.get('category','whitelist')
    if not name:
        return jsonify({'error': 'Name required'}), 400
    import shutil
    face_dir = os.path.join('data/known_faces', category, name)
    face_file = os.path.join('data/faces', name + '.jpg')
    face_dir2 = os.path.join('data/faces', name)
    removed = False
    for path in [face_dir, face_dir2]:
        if os.path.exists(path):
            shutil.rmtree(path); removed = True
    for path in [face_file]:
        if os.path.exists(path):
            os.remove(path); removed = True
    if removed:
        return jsonify({'success': True, 'message': f'{name} deleted. Restart to apply.'})
    return jsonify({'error': 'Face not found'}), 404

@app.route('/api/enroll/list')
@login_required
def api_enroll_list():
    """List all enrolled faces"""
    faces = []
    for base, has_cat in [('data/known_faces', True), ('data/faces', False)]:
        if not os.path.exists(base): continue
        if has_cat:
            for cat in ['whitelist','routine','blacklist']:
                d = os.path.join(base, cat)
                if not os.path.exists(d): continue
                for p in os.listdir(d):
                    if os.path.isdir(os.path.join(d, p)):
                        count = len([f for f in os.listdir(os.path.join(d,p))
                                     if f.lower().endswith(('.jpg','.jpeg','.png'))])
                        faces.append({'name':p,'category':cat,'photos':count})
        else:
            for entry in os.listdir(base):
                if os.path.isdir(os.path.join(base, entry)):
                    faces.append({'name':entry,'category':'whitelist','photos':len(os.listdir(os.path.join(base,entry)))})
                elif entry.lower().endswith(('.jpg','.jpeg','.png')):
                    faces.append({'name':os.path.splitext(entry)[0],'category':'whitelist','photos':1})
    return jsonify(faces)

# ── RTSP / CAMERA CONFIG ──────────────────────────────────
@app.route('/api/camera/config', methods=['GET','POST'])
@admin_required
def api_camera_config():
    """Get/Set camera sources (live or RTSP)"""
    global CAM0_SRC, CAM1_SRC
    if request.method == 'POST':
        data = request.json or {}
        cam0 = data.get('cam0', '').strip()
        cam1 = data.get('cam1', '').strip()
        if cam0:
            CAM0_SRC = int(cam0) if cam0.isdigit() else cam0
        if cam1:
            CAM1_SRC = int(cam1) if cam1.isdigit() else cam1
        # Save to config file
        cfg = {'cam0': str(CAM0_SRC), 'cam1': str(CAM1_SRC) if CAM1_SRC else ''}
        with open('data/camera_config.json', 'w') as f:
            import json; json.dump(cfg, f)
        return jsonify({'success': True, 'cam0': str(CAM0_SRC), 'cam1': str(CAM1_SRC)})
    return jsonify({'cam0': str(CAM0_SRC), 'cam1': str(CAM1_SRC) if CAM1_SRC else ''})

# ── WHATSAPP CONFIG ───────────────────────────────────────
@app.route('/api/whatsapp/config', methods=['GET','POST'])
@admin_required
def api_whatsapp_config():
    global WHATSAPP_PHONE, WHATSAPP_APIKEY, WHATSAPP_ENABLED
    global TELEGRAM_CHATID, TELEGRAM_APIKEY, TELEGRAM_ENABLED
    if request.method == 'POST':
        data = request.json or {}
        WHATSAPP_PHONE   = data.get('phone','').strip()
        WHATSAPP_APIKEY  = data.get('apikey','').strip()
        WHATSAPP_ENABLED = bool(data.get('enabled', False))
        TELEGRAM_CHATID  = data.get('tg_chatid','').strip()
        TELEGRAM_APIKEY  = data.get('tg_apikey','').strip()
        TELEGRAM_ENABLED = bool(data.get('tg_enabled', False))
        ok = save_alert_config()
        print(f"📱 WhatsApp {'ON' if WHATSAPP_ENABLED else 'OFF'} | Telegram {'ON' if TELEGRAM_ENABLED else 'OFF'}")
        return jsonify({'success': ok, 'message': 'Config saved permanently'})
    return jsonify({
        'phone': WHATSAPP_PHONE, 'apikey': WHATSAPP_APIKEY, 'enabled': WHATSAPP_ENABLED,
        'tg_chatid': TELEGRAM_CHATID, 'tg_apikey': TELEGRAM_APIKEY, 'tg_enabled': TELEGRAM_ENABLED
    })

@app.route('/api/whatsapp/test', methods=['POST'])
@admin_required
def api_whatsapp_test():
    msg = f"✅ ProVisionGuard Test Alert\nSystem is active!\nTime: {datetime.now().strftime('%H:%M:%S')}"
    send_alert_notification(msg, 'CRITICAL')
    return jsonify({'success': True, 'message': 'Test sent to all enabled channels'})




@app.route('/cam0')
@login_required
def cam0():
    resp = Response(_stream(lambda: _frame0),
        mimetype='multipart/x-mixed-replace;boundary=frame')
    resp.headers['Cache-Control'] = 'no-cache, no-store, must-revalidate'
    resp.headers['Access-Control-Allow-Origin'] = '*'
    return resp

@app.route('/video_feed/0')
@login_required
def video_feed_0():
    resp = Response(_stream(lambda: _frame0),
        mimetype='multipart/x-mixed-replace;boundary=frame')
    resp.headers['Cache-Control'] = 'no-cache, no-store, must-revalidate'
    resp.headers['Access-Control-Allow-Origin'] = '*'
    return resp

@app.route('/live')
def mobile_live():
    """Mobile full dashboard — wide, no login needed"""
    return '''<!DOCTYPE html>
<html>
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1,maximum-scale=1,user-scalable=no">
<title>ProVisionGuard AI</title>
<script src="https://cdnjs.cloudflare.com/ajax/libs/socket.io/4.7.2/socket.io.min.js"></script>
<style>
*{margin:0;padding:0;box-sizing:border-box}
html,body{width:100%;background:#0a1628;font-family:Arial,sans-serif;color:#fff}
.topbar{background:#0d1e38;border-bottom:2px solid #c49a38;padding:8px 12px;display:flex;align-items:center;justify-content:space-between;position:sticky;top:0;z-index:100}
.brand{font-size:14px;font-weight:700;color:#c49a38;display:flex;align-items:center;gap:6px}
.dot{width:7px;height:7px;border-radius:50%;background:#22a855;animation:p 1.5s ease infinite}
@keyframes p{0%,100%{opacity:1}50%{opacity:.3}}
.clk{font-size:12px;color:rgba(255,255,255,.5);font-family:monospace}
.stats{display:grid;grid-template-columns:repeat(4,1fr);gap:1px;background:rgba(196,154,56,.2);border-bottom:1px solid rgba(196,154,56,.2)}
.sc{background:#0d1e38;padding:8px 6px;text-align:center}
.sv{font-size:20px;font-weight:700;color:#c49a38}
.sl{font-size:8px;color:rgba(255,255,255,.4);text-transform:uppercase;letter-spacing:1px;margin-top:2px}
.cam-wrap{position:relative;background:#000;width:100%}
.cam-wrap img{width:100%;display:block;min-height:200px;object-fit:cover}
.cam-hud{position:absolute;top:8px;left:8px;display:flex;gap:5px}
.pill{font-size:9px;font-family:monospace;letter-spacing:1px;padding:2px 8px;border-radius:20px;text-transform:uppercase;display:flex;align-items:center;gap:3px}
.p-rec{background:rgba(184,50,40,.3);border:1px solid rgba(184,50,40,.5);color:#e06050}
.p-fps{background:rgba(196,154,56,.15);border:1px solid rgba(196,154,56,.3);color:#c49a38}
.p-nv{background:rgba(26,64,112,.3);border:1px solid rgba(26,64,112,.5);color:#6090d0;display:none}
.rd{width:4px;height:4px;border-radius:50%;background:#e06050;animation:rb .9s ease infinite}
@keyframes rb{0%,100%{opacity:1}50%{opacity:.15}}
.cam-bot{position:absolute;bottom:8px;left:10px;right:10px;display:flex;justify-content:space-between;align-items:flex-end}
.bignum{font-size:38px;font-weight:700;color:#fff;line-height:1}
.bignumlbl{font-size:8px;color:rgba(255,255,255,.3);letter-spacing:2px;text-transform:uppercase}
.ts{font-size:9px;color:rgba(255,255,255,.2);font-family:monospace}
.sec{border-bottom:1px solid rgba(196,154,56,.15)}
.sec-hdr{background:#0d1e38;padding:8px 12px;font-size:11px;font-weight:700;color:#c49a38;text-transform:uppercase;letter-spacing:1px;display:flex;align-items:center;justify-content:space-between}
.sec-cnt{font-size:10px;font-weight:400;color:rgba(255,255,255,.5)}
.plist{padding:8px 8px 2px}
.pc{background:#111d30;border:1px solid rgba(196,154,56,.15);border-radius:8px;margin-bottom:7px;border-left:3px solid var(--cl,#7a6840);overflow:hidden}
.pc-top{padding:8px 10px;display:flex;align-items:center;gap:8px}
.pav{width:32px;height:32px;border-radius:7px;background:rgba(196,154,56,.1);border:1px solid rgba(196,154,56,.2);display:flex;align-items:center;justify-content:center;font-size:11px;font-weight:700;color:#c49a38;flex-shrink:0}
.pnm{font-size:12px;font-weight:700;color:#fff}
.pcat{font-size:9px;color:rgba(255,255,255,.4);text-transform:uppercase;letter-spacing:.5px;margin-top:1px}
.plbl{font-size:9px;font-family:monospace;padding:2px 8px;border-radius:20px;margin-left:auto;flex-shrink:0;text-transform:uppercase}
.l-t{background:rgba(34,168,85,.15);border:1px solid rgba(34,168,85,.3);color:#22a855}
.l-w{background:rgba(184,50,40,.15);border:1px solid rgba(184,50,40,.3);color:#e06050}
.l-m{background:rgba(184,96,32,.15);border:1px solid rgba(184,96,32,.3);color:#f57c00}
.l-s{background:rgba(196,154,56,.1);border:1px solid rgba(196,154,56,.2);color:#c49a38}
.pbar{padding:0 10px 6px;display:flex;align-items:center;gap:6px}
.pbg{flex:1;height:3px;background:rgba(255,255,255,.1);border-radius:2px;overflow:hidden}
.pbf{height:100%;border-radius:2px;transition:width .8s}
.pval{font-size:9px;font-family:monospace;width:26px;text-align:right}
.intent{margin:0 10px 8px;background:rgba(196,154,56,.05);border:1px solid rgba(196,154,56,.1);border-radius:6px;padding:6px 8px;display:grid;grid-template-columns:1fr 1fr 1fr;gap:4px}
.iitem{text-align:center}
.ik{font-size:8px;color:rgba(255,255,255,.3);text-transform:uppercase;letter-spacing:1px}
.iv{font-size:9px;color:rgba(255,255,255,.8);margin-top:2px}
.pempty{padding:16px;text-align:center;font-size:10px;color:rgba(255,255,255,.3);font-family:monospace;letter-spacing:2px;text-transform:uppercase}
.nlbox{margin:8px;background:#0d1e38;border:1px solid rgba(196,154,56,.2);border-radius:8px;padding:10px 12px}
.nl-hdr{font-size:9px;color:#c49a38;text-transform:uppercase;letter-spacing:1px;margin-bottom:5px;font-weight:700}
.nl-txt{font-size:11px;color:rgba(255,255,255,.85);line-height:1.6;font-style:italic}
.nl-ts{font-size:9px;color:rgba(255,255,255,.3);margin-top:4px;font-family:monospace}
.alerts{padding:8px}
.ar{display:flex;gap:7px;padding:8px 10px;background:#111d30;border-radius:7px;border:1px solid rgba(184,50,40,.2);margin-bottom:6px}
.adot{width:6px;height:6px;border-radius:50%;flex-shrink:0;margin-top:3px}
.adr{background:#e06050}.ado{background:#f57c00}.adg{background:#c49a38}
.atxt{font-size:10px;color:rgba(255,255,255,.85);line-height:1.4}
.atm{font-size:9px;color:rgba(255,255,255,.3);margin-top:2px;font-family:monospace}
.aempty{padding:14px;text-align:center;font-size:9px;color:rgba(255,255,255,.3);font-family:monospace;letter-spacing:2px;text-transform:uppercase}
.footer{background:#0d1e38;border-top:1px solid rgba(196,154,56,.2);padding:8px 12px;display:flex;gap:8px;justify-content:center}
.fbtn{font-size:10px;font-family:monospace;padding:5px 14px;border-radius:20px;border:1px solid rgba(196,154,56,.3);background:rgba(196,154,56,.08);color:#c49a38;text-decoration:none}
</style>
</head>
<body>
<div class="topbar">
  <div class="brand"><div class="dot"></div>ProVisionGuard AI</div>
  <div class="clk" id="clk">--:--:--</div>
</div>
<div class="stats">
  <div class="sc"><div class="sv" id="s-p">0</div><div class="sl">Persons</div></div>
  <div class="sc"><div class="sv" id="s-f">--</div><div class="sl">FPS</div></div>
  <div class="sc"><div class="sv" id="s-a">0</div><div class="sl">Alerts</div></div>
  <div class="sc"><div class="sv" id="s-t">CLEAR</div><div class="sl">Threat</div></div>
</div>
<div class="cam-wrap">
  <img src="/stream/0" id="feed" onerror="setTimeout(()=>{document.getElementById('feed').src='/stream/0?r='+Date.now()},2000)">
  <div class="cam-hud">
    <div class="pill p-rec"><div class="rd"></div>REC</div>
    <div class="pill p-fps" id="fhud">-- FPS</div>
    <div class="pill p-nv" id="nvbadge">NIGHT</div>
  </div>
  <div class="cam-bot">
    <div><div class="bignum" id="pcc">0</div><div class="bignumlbl">In Frame</div></div>
    <div class="ts" id="ts">--:--:--</div>
  </div>
</div>
<div class="sec">
  <div class="sec-hdr">Detected Persons <span class="sec-cnt" id="pcnt"></span></div>
  <div class="plist" id="plist"><div class="pempty">Awaiting detection...</div></div>
</div>
<div class="sec">
  <div class="sec-hdr">AI Activity Description</div>
  <div class="nlbox">
    <div class="nl-hdr">Latest Scene Analysis</div>
    <div class="nl-txt" id="nltxt">Waiting for activity to analyse...</div>
    <div class="nl-ts" id="nlts"></div>
  </div>
</div>
<div class="sec">
  <div class="sec-hdr">Alert Timeline <span class="sec-cnt" id="acnt"></span></div>
  <div class="alerts" id="alist"><div class="aempty" id="ae">No alerts yet</div></div>
</div>
<div class="footer">
  <a class="fbtn" href="/login">Full Dashboard</a>
  <a class="fbtn" href="/enroll">Enroll Face</a>
</div>
<script>
const sk=io();let tot=0;
function S(id,v){const e=document.getElementById(id);if(e)e.textContent=v;}
function tick(){const t=new Date().toLocaleTimeString('en-GB');S('clk',t);S('ts',t);}
setInterval(tick,1000);tick();
function col(s){return s>=.75?'#e06050':s>=.5?'#f57c00':s>=.28?'#c49a38':'#22a855';}
function tc(l){return{TRUSTED:'l-t',SAFE:'l-t',WATCH:'l-s',MEDIUM:'l-m',HIGH:'l-w',CRITICAL:'l-w',BLACKLIST:'l-w'}[l]||'l-s';}
sk.on('up',d=>{
  const P=d.p||{},ids=Object.keys(P),sys=d.s||{};
  S('s-p',ids.length);S('pcc',ids.length);
  if(ids.length)S('pcnt',ids.length+' active');
  if(sys.fps){const f=parseFloat(sys.fps).toFixed(1);S('s-f',f);S('fhud',f+' FPS');}
  const nv=document.getElementById('nvbadge');
  if(nv)nv.style.display=sys.night?'flex':'none';
  const mx=ids.length?Math.max(...ids.map(id=>parseFloat(P[id].threat_score||0))):0;
  const tl=document.getElementById('s-t');
  if(tl){
    if(mx>=.75){tl.textContent='CRITICAL';tl.style.color='#e06050';}
    else if(mx>=.45){tl.textContent='HIGH';tl.style.color='#e06050';}
    else if(mx>=.28){tl.textContent='WATCH';tl.style.color='#c49a38';}
    else{tl.textContent='CLEAR';tl.style.color='#22a855';}
  }
  const list=document.getElementById('plist');
  if(!ids.length){list.innerHTML='<div class="pempty">No persons detected</div>';return;}
  list.querySelectorAll('.pc').forEach(c=>{if(!P[c.dataset.tid])c.remove();});
  ids.forEach(id=>{
    const p=P[id],ts=(p.threat_score||0)*100,cl=col(p.threat_score||0),nm=p.name||'STRANGER';
    const intent=p.intent||{};
    const ihtml=`<div class="intent">
      <div class="iitem"><div class="ik">WHO</div><div class="iv">${intent.who||'?'}</div></div>
      <div class="iitem"><div class="ik">WHY</div><div class="iv">${intent.why||'?'}</div></div>
      <div class="iitem"><div class="ik">NEXT</div><div class="iv">${intent.next||'?'}</div></div>
    </div>`;
    const inner=`<div class="pc-top"><div class="pav">${nm.slice(0,2).toUpperCase()}</div>
      <div><div class="pnm">${nm}</div><div class="pcat">${(p.category||'stranger').toUpperCase()} · ${p.emotion||'—'}</div></div>
      <div class="plbl ${tc(p.threat_label)}">${p.threat_label||'SAFE'}</div></div>
      <div class="pbar"><div class="pbg"><div class="pbf" style="width:${ts.toFixed(1)}%;background:${cl}"></div></div>
      <div class="pval" style="color:${cl}">${ts.toFixed(0)}%</div></div>${ihtml}`;
    let card=list.querySelector('[data-tid="'+id+'"]');
    if(!card){card=document.createElement('div');card.className='pc';card.dataset.tid=id;list.prepend(card);}
    card.innerHTML=inner;card.style.setProperty('--cl',cl);
  });
  (d.a||[]).forEach(a=>{
    tot++;S('s-a',tot);S('acnt',tot+' total');
    document.getElementById('ae').style.display='none';
    const dc=['CRITICAL','BLACKLIST'].includes(a.label)?'adr':a.label==='HIGH'?'ado':'adg';
    const card=document.createElement('div');card.className='ar';
    card.innerHTML=`<div class="adot ${dc}"></div><div><div class="atxt">${a.label} — ${a.name||'Unknown'}</div><div class="atm">${a.time} · ${((a.score||0)*100).toFixed(0)}%</div></div>`;
    const al=document.getElementById('alist');al.prepend(card);
    if(al.querySelectorAll('.ar').length>6)al.lastElementChild.remove();
  });
});
function fetchNL(){
  fetch('/api/nl/latest').then(r=>r.json()).then(d=>{
    if(d.description){S('nltxt',d.description);S('nlts','Updated: '+d.time);}
  }).catch(()=>{});
}
setInterval(fetchNL,32000);fetchNL();
</script>
</body>
</html>'''

@app.route('/stream/0')
def stream_public():
    """Public stream for mobile"""
    resp = Response(_stream(lambda: _frame0),
        mimetype='multipart/x-mixed-replace;boundary=frame')
    resp.headers['Cache-Control'] = 'no-cache'
    resp.headers['Access-Control-Allow-Origin'] = '*'
    return resp



@app.route('/video_feed/1')
@login_required
def video_feed_1():
    return Response(_stream(lambda: _frame1),
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

@app.route('/api/footage/download')
@login_required
def api_footage_download():
    """Download current footage video file"""
    video_path = DEMO_VIDEO
    if os.path.exists(video_path):
        fname = f"ProVisionGuard_Footage_{datetime.now().strftime('%Y%m%d_%H%M%S')}.mp4"
        return send_file(video_path, as_attachment=True, download_name=fname)
    return jsonify({'error': 'No footage file found at ' + video_path}), 404

@app.route('/api/snapshot/download')
@login_required
def api_snapshot_download():
    """Download latest alert snapshot"""
    snaps = sorted([f for f in os.listdir(SNAPSHOT_DIR)
                    if f.endswith('.jpg')]) if os.path.exists(SNAPSHOT_DIR) else []
    if snaps:
        path = os.path.join(SNAPSHOT_DIR, snaps[-1])
        return send_file(path, as_attachment=True, download_name=snaps[-1])
    return jsonify({'error': 'No snapshots found'}), 404

@app.route('/api/nl/language', methods=['POST'])
@login_required
def api_nl_language():
    """Switch NL description language: english or tamil"""
    global NL_LANGUAGE
    data = request.json or {}
    lang = data.get('language', 'english').lower()
    if lang in ['tamil', 'english']:
        NL_LANGUAGE = lang
        print(f"🗣 NL Language set to: {NL_LANGUAGE}")
        return jsonify({'success': True, 'language': NL_LANGUAGE})
    return jsonify({'error': 'Use english or tamil'}), 400

@app.route('/api/nl/latest')
def api_nl_latest():
    """Return latest NL description — public, for mobile"""
    return jsonify({
        'description': _nl_last_description,
        'time': _nl_last_time,
    })

@app.route('/api/status')
@login_required
def api_status():
    with _lock:
        return jsonify({
            'fps':_fps,'night':_night,'crowd':_crowd,
            'persons':len(_persons),'alerts':_total_alerts,
            'ai_ready':_ai_ready,'ai_status':_ai_status,
            'plates':_plates[-3:],'weapons':_weapons[-3:],
            'phones':_phones[-3:],'footage_mode':_footage_mode,
        })

@app.route('/api/set_source')
@login_required
def api_set_source():
    """Switch between live camera and recorded footage"""
    global _footage_mode, _CAM0_SRC_OVERRIDE
    mode = request.args.get('mode','live')
    if mode == 'footage':
        _footage_mode = True
        print(f"📹 Switched to FOOTAGE mode: {DEMO_VIDEO}")
    else:
        _footage_mode = False
        print("📷 Switched to LIVE camera mode")
    return jsonify({'success': True, 'mode': mode})

@app.route('/')
@login_required
def index():
    return render_template_string(DASHBOARD_HTML,
        username=session.get('username','admin'),
        role=session.get('role','operator'),
        branding=load_branding())

# Push state to browser
def push_loop():
    last = 0
    while True:
        try:
            with _lock:
                persons = dict(_persons)
                alerts  = list(_alerts)
                fps     = float(_fps)
                night   = bool(_night)
                crowd   = int(_crowd)
                plates  = list(_plates[-3:])
                weapons = list(_weapons[-3:])
                phones  = list(_phones[-3:])
            new_a = []
            if len(alerts)>last:
                new_a=alerts[:len(alerts)-last]; last=len(alerts)
            sio.emit('up',{
                'p':persons,'a':new_a,
                's':{'fps':fps,'night':night,'crowd':crowd,
                     'plates':plates,'weapons':weapons,
                     'phones':phones,
                     'footage_mode':bool(_footage_mode),
                     'ready':bool(_ai_ready),
                     'status':_ai_status}
            })
        except Exception as e:
            print(f"⚠ push_loop error: {e}")
        time.sleep(0.12)

threading.Thread(target=push_loop, daemon=True).start()


# ── CAMERA LOOP ───────────────────────────────────────────
def run_camera(cam_id, src, yolo_det, yolo_pose,
               face_app, emo_model, ocr, known_faces):
    global _frame0, _frame1, _fps, _night, _crowd, _plates, _weapons, _phones, _footage_mode

    fq=queue.Queue(maxsize=1); fr={}
    eq=queue.Queue(maxsize=1); er={}

    def face_w():
        while True:
            try:
                tid,crop=fq.get(timeout=1)
                if crop is None or crop.size==0:
                    fr[tid]=(None,'stranger',0); continue

                # Resize crop for better detection — min 100px face
                h,w=crop.shape[:2]
                if h<80 or w<80:
                    scale=max(80/h,80/w)
                    crop=cv2.resize(crop,None,fx=scale,fy=scale,
                                    interpolation=cv2.INTER_LINEAR)

                faces=face_app.get(crop)
                if not faces:
                    # Try with larger detection size
                    faces=face_app.get(cv2.resize(crop,(320,320)))

                if not faces:
                    fr[tid]=(None,'stranger',0); continue

                # Use largest/most confident face
                best_face=max(faces,key=lambda f:
                    (f.bbox[2]-f.bbox[0])*(f.bbox[3]-f.bbox[1]))
                emb=best_face.embedding
                emb_norm=emb/(np.linalg.norm(emb)+1e-6)

                bn,bc,bs=None,'stranger',0.0
                for nm,dt in known_faces.items():
                    ref=dt['emb']/(np.linalg.norm(dt['emb'])+1e-6)
                    sim=float(np.dot(emb_norm,ref))
                    if sim>bs: bs=sim;bn=nm;bc=dt['category']

                # Lower threshold for better recall in crowds
                # 0.45 = more matches, 0.55 = stricter
                THRESH=0.45
                fr[tid]=(bn,bc,bs) if bs>=THRESH else (None,'stranger',bs)

            except queue.Empty: pass
            except Exception as e:
                pass

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

    # RTSP / IP Camera settings
    if isinstance(src, str) and ('rtsp://' in src or 'http://' in src):
        cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
        # RTSP needs different codec
        print(f"  📡 RTSP camera detected: {src[:40]}...")
    else:
        # Webcam settings
        cap.set(cv2.CAP_PROP_FRAME_WIDTH, 640)
        cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)
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
    _current_src=src  # track current source

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
        # ── Footage mode switching ────────────────────────
        if cam_id == 0:
            desired_src = DEMO_VIDEO if _footage_mode else src
            if desired_src != _current_src:
                cap.release()
                cap = cv2.VideoCapture(desired_src)
                if not cap.isOpened():
                    print(f"⚠ Cannot open {desired_src}, reverting to live")
                    _footage_mode = False
                    cap = cv2.VideoCapture(src)
                else:
                    print(f"✅ Switched source: {desired_src}")
                _current_src = desired_src
                pstates.clear(); fc = 0

        ret,frame=cap.read()
        if not ret:
            if _footage_mode and cam_id == 0:
                # Loop footage video when it ends
                cap.set(cv2.CAP_PROP_POS_FRAMES, 0)
                continue
            time.sleep(0.05); continue

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
                classes=[0],verbose=False,conf=0.25,device=device)
        except Exception as e:
            print(f"⚠ Detection error: {e}"); time.sleep(0.1); continue

        # Pose (every 3rd frame for better FPS)
        if fc%3==0:
            try:
                pose=yolo_pose.track(frame,persist=True,verbose=False,conf=0.25,device=device)
                if pose and pose[0].keypoints is not None and pose[0].boxes is not None:
                    last_kps={}
                    for i,kps in enumerate(pose[0].keypoints.data):
                        pb=pose[0].boxes
                        pid=int(pb.id[i]) if pb.id is not None else i
                        last_kps[pid]=kps
            except: pass

        # Weapon detection (every 15 frames)
        if fc%15==0:
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

        # Phone / Mobile detection (every 15 frames — YOLO class 67)
        if fc%15==0:
            try:
                pr=yolo_det(frame,verbose=False,conf=0.45,
                            classes=[67],device=device)  # cell phone = 67
                local_phones_new=[]
                if pr and pr[0].boxes is not None and len(pr[0].boxes)>0:
                    for box in pr[0].boxes:
                        bxy=box.xyxy[0].cpu().numpy()
                        x1p,y1p,x2p,y2p=[int(v) for v in bxy]
                        cv2.rectangle(frame,(x1p,y1p),(x2p,y2p),(255,120,0),2)
                        cv2.putText(frame,'PHONE DETECTED',(x1p,y1p-8),
                                    cv2.FONT_HERSHEY_SIMPLEX,0.45,(255,140,0),1)
                        local_phones_new.append({'label':'phone','cam':cam_id,
                            'time':datetime.now().strftime('%H:%M:%S')})
                if cam_id==0:
                    with _lock: _phones[:]=local_phones_new[-4:]
            except: pass


        # ── Scene Object Detection (every 20 frames — for NL description) ──
        if fc % 20 == 0 and cam_id == 0 and NL_ENABLED:
            try:
                scene_classes = list(SCENE_OBJECTS.keys())
                sr = yolo_det(frame, verbose=False, conf=0.4,
                              classes=scene_classes, device=device)
                if sr and sr[0].boxes is not None and len(sr[0].boxes) > 0:
                    found_objs = []
                    for box in sr[0].boxes:
                        cls_id = int(box.cls[0])
                        obj_name = SCENE_OBJECTS.get(cls_id, '')
                        if obj_name:
                            found_objs.append(obj_name)
                    if found_objs:
                        with _lock:
                            _scene_log.extend(found_objs)
                            if len(_scene_log) > 50:
                                _scene_log[:] = _scene_log[-50:]
                        # Add near_objects to person states
                        if det and det[0].boxes is not None:
                            for i2, box2 in enumerate(det[0].boxes):
                                tid2 = int(box2.id[0]) if box2.id is not None else i2
                                if tid2 in pstates:
                                    pstates[tid2].near_objects = found_objs[:4]
            except: pass

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
        if det and det[0].boxes is not None and len(det[0].boxes) > 0:
            for i,box in enumerate(det[0].boxes):
                bxy=box.xyxy[0].cpu().numpy(); x1,y1,x2,y2=[int(v) for v in bxy]
                # Handle tracker ID — fallback to index if None
                if box.id is not None:
                    tid = int(box.id[0])
                else:
                    tid = i + cam_id * 1000
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

                # Face recognition (every 5th frame — crowd accuracy)
                if fc%5==0:
                    crop2=frame[max(0,y1):min(H_F,y2),max(0,x1):min(W_F,x2)]
                    if crop2.size>0:
                        try: fq.put_nowait((tid,crop2.copy()))
                        except queue.Full: pass
                if tid in fr:
                    bn,bc,bs=fr[tid]
                    if bn: s.name=bn;s.cat=bc;s.fc=bs

                # Emotion (every 15th frame)
                if fc%15==0:
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

                # Alert trigger — stranger 8 seconds-லயே alert வரும்
                should_alert = (
                    (tl in ['CRITICAL','HIGH','MEDIUM','BLACKLIST'] and s.cat!='whitelist') or
                    (tl=='WATCH' and s.cat=='stranger' and time.time()-s.fs>8) or
                    (s.cat=='stranger' and s.threat>=0.28 and time.time()-s.fs>8)
                )
                if should_alert:
                    do_alert(frame,s,tl,behs,cam_id)
                draw_box(frame,s,x1,y1,x2,y2,sigs,behs,fc)

                dp[str(tid)]={
                    'name':s.name,'category':s.cat,
                    'threat_score':float(s.threat),'threat_label':tl,
                    'emotion':s.emo,'distance':float(s.dist),
                    'behaviors':behs,
                    'signals':{k:float(v) for k,v in sigs.items()},
                    'theft_risk':float(s.theft),'cam':cam_id,'zones':s.zones,
                    'near_objects': s.near_objects,
                    'intent': iprof,
                    'keypoints_raw': [[float(kps[j][0]),float(kps[j][1]),float(kps[j][2])] for j in range(len(kps))] if kps is not None and len(kps)>=17 else None,
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
                # Debug — print every 30 frames
                if fc % 30 == 0 and dp:
                    print(f"  🎯 Detected {len(dp)} person(s): {[v.get('name','?') for v in dp.values()]}")
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
    print("  ProVisionGuard AI v8.0")
    print("  Starting up — please wait...")
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
        import onnxruntime as _ort

        # Check available ONNX providers
        _ort_providers = _ort.get_available_providers()
        _use_cuda_ort  = 'CUDAExecutionProvider' in _ort_providers

        if _use_cuda_ort:
            face_app = FaceAnalysis(name='buffalo_l',
                providers=['CUDAExecutionProvider','CPUExecutionProvider'])
            face_app.prepare(ctx_id=0, det_size=(320,320))
            print("  ✅ InsightFace: GPU (CUDA)")
        else:
            # onnxruntime-gpu not installed — CPU mode (still works, just slower)
            face_app = FaceAnalysis(name='buffalo_l',
                providers=['CPUExecutionProvider'])
            face_app.prepare(ctx_id=-1, det_size=(320,320))
            print("  ⚠ InsightFace: CPU mode")
            print("    (pip install onnxruntime-gpu for faster face recognition)")

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

        # Support multiple folder structures
        face_search_paths = [
            # Structure 1: data/known_faces/category/person/images
            ('data/known_faces', True),
            # Structure 2: data/faces/person/images (no category subfolder)
            ('data/faces', False),
        ]

        for base_dir, has_category in face_search_paths:
            if not os.path.exists(base_dir):
                continue
            if has_category:
                # data/known_faces/whitelist/PersonName/*.jpg
                for cat in ['whitelist','routine','blacklist']:
                    d = os.path.join(base_dir, cat)
                    if not os.path.exists(d): continue
                    for person in os.listdir(d):
                        pd2 = os.path.join(d, person)
                        if not os.path.isdir(pd2): continue
                        embs = []
                        for f in os.listdir(pd2):
                            if not f.lower().endswith(('.jpg','.jpeg','.png')): continue
                            img = cv2.imread(os.path.join(pd2, f))
                            if img is None: continue
                            faces = face_app.get(img)
                            if faces:
                                emb = faces[0].embedding
                                embs.append(emb / (np.linalg.norm(emb) + 1e-6))
                        if embs:
                            mean_emb = np.mean(embs, axis=0)
                            known_faces[person] = {
                                'emb': mean_emb / (np.linalg.norm(mean_emb) + 1e-6),
                                'category': cat,
                                'photos': len(embs)
                            }
                            print(f"  ✅ Face loaded: {person} [{cat}] ({len(embs)} photo(s))")
            else:
                # Structure 2: data/faces/PersonName/*.jpg  OR  data/faces/PersonName.jpg
                entries = os.listdir(base_dir)
                for entry in entries:
                    full_path = os.path.join(base_dir, entry)
                    embs = []
                    if os.path.isdir(full_path):
                        person_name = entry
                        for f in os.listdir(full_path):
                            if not f.lower().endswith(('.jpg','.jpeg','.png')): continue
                            img = cv2.imread(os.path.join(full_path, f))
                            if img is None: continue
                            faces = face_app.get(img)
                            if faces:
                                emb = faces[0].embedding
                                embs.append(emb / (np.linalg.norm(emb) + 1e-6))
                    elif entry.lower().endswith(('.jpg','.jpeg','.png')):
                        person_name = os.path.splitext(entry)[0]
                        img = cv2.imread(full_path)
                        if img is not None:
                            faces = face_app.get(img)
                            if faces:
                                emb = faces[0].embedding
                                embs.append(emb / (np.linalg.norm(emb) + 1e-6))
                    else:
                        continue
                    if embs:
                        if person_name not in known_faces:
                            mean_emb = np.mean(embs, axis=0)
                            known_faces[person_name] = {
                                'emb': mean_emb / (np.linalg.norm(mean_emb) + 1e-6),
                                'category': 'whitelist',
                                'photos': len(embs)
                            }
                            print(f"  ✅ Face loaded: {person_name} [whitelist] ({len(embs)} photo(s))")

        print(f"  ✅ Total faces loaded: {len(known_faces)}")

        _ai_ready = True
        _ai_status = "System Live"
        print(f"\n✅ ALL SYSTEMS GO!")
        print(f"   Dashboard: http://localhost:5000")
        print(f"   PDF Report: http://localhost:5000/api/report")
        print(f"   Controls: SHOW_WINDOW=True for camera popup")
        print("="*52)

        # Start cameras
        # ── Camera source: Demo or Live ───────────────────
        if DEMO_MODE:
            if os.path.exists(DEMO_VIDEO):
                cam0_src = DEMO_VIDEO
                print(f"  DEMO MODE: Using {DEMO_VIDEO}")
            else:
                # Download a free sample video if not present
                os.makedirs('demo', exist_ok=True)
                print("  DEMO MODE: demo/demo_video.mp4 not found.")
                print("  Place any .mp4 file at demo/demo_video.mp4")
                print("  Falling back to webcam...")
                cam0_src = CAM0_SRC
        else:
            cam0_src = CAM0_SRC

        t0 = threading.Thread(target=run_camera,
            args=(0, cam0_src, yolo_det, yolo_pose,
                  face_app, emo_model, ocr, known_faces),
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

# ── FACE ENROLLMENT HTML ───────────────────────────────────
ENROLL_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Face Enrollment — ProVisionGuard</title>
<style>
*{margin:0;padding:0;box-sizing:border-box}
:root{--bg:#f5f0e8;--bg1:#faf7f2;--bg2:#fff;--gold:#a07828;--gold2:#c49a38;
  --golddim:rgba(160,120,40,.09);--goldbr:rgba(160,120,40,.2);
  --ink:#1a1508;--ink2:#2d2410;--ink4:#7a6840;--ink5:#b0a078;
  --red:#b83228;--green:#186030;--sh:0 1px 4px rgba(160,120,40,.08)}
body{background:var(--bg);font-family:'Segoe UI',sans-serif;color:var(--ink);min-height:100vh}
.topbar{display:flex;align-items:center;height:52px;background:var(--bg1);
  border-bottom:1px solid var(--goldbr);padding:0 20px;gap:12px}
.logo{font-size:12px;font-weight:700;color:var(--ink2)}
.back{font-size:11px;color:var(--gold);text-decoration:none;margin-right:auto}
.page{max-width:900px;margin:0 auto;padding:24px 20px}
h1{font-size:20px;font-weight:700;color:var(--ink2);margin-bottom:4px}
.sub{font-size:12px;color:var(--ink5);margin-bottom:24px}
.grid{display:grid;grid-template-columns:1fr 1fr;gap:20px}
.card{background:var(--bg2);border:1px solid var(--goldbr);border-radius:12px;
  padding:20px;box-shadow:var(--sh)}
.card h2{font-size:14px;font-weight:600;color:var(--ink2);margin-bottom:16px;
  padding-bottom:10px;border-bottom:1px solid var(--goldbr)}
.form-group{margin-bottom:14px}
label{display:block;font-size:11px;font-weight:600;color:var(--ink4);
  margin-bottom:5px;text-transform:uppercase;letter-spacing:.5px}
input[type=text],select{width:100%;padding:9px 12px;border:1px solid var(--goldbr);
  border-radius:8px;background:var(--bg1);color:var(--ink2);font-size:13px}
input[type=text]:focus,select:focus{outline:none;border-color:var(--gold)}
.upload-box{border:2px dashed var(--goldbr);border-radius:8px;padding:20px;
  text-align:center;background:var(--golddim);cursor:pointer;transition:all .2s}
.upload-box:hover{border-color:var(--gold);background:rgba(160,120,40,.14)}
.upload-box p{font-size:12px;color:var(--ink5);margin-top:6px}
.upload-box .icon{font-size:28px}
#preview{width:100%;max-height:120px;object-fit:cover;border-radius:8px;
  margin-top:10px;display:none;border:1px solid var(--goldbr)}
.btn{width:100%;padding:11px;border:none;border-radius:8px;font-size:13px;
  font-weight:600;cursor:pointer;transition:all .2s}
.btn-gold{background:var(--gold);color:#fff}
.btn-gold:hover{background:var(--gold2)}
.btn-red{background:var(--red);color:#fff;padding:6px 14px;width:auto;font-size:11px;border-radius:6px}
.msg{padding:10px 14px;border-radius:8px;font-size:12px;margin-top:12px;display:none}
.msg-ok{background:rgba(24,96,48,.1);border:1px solid rgba(24,96,48,.2);color:var(--green)}
.msg-err{background:rgba(184,50,40,.08);border:1px solid rgba(184,50,40,.2);color:var(--red)}
.face-list{display:flex;flex-direction:column;gap:8px;max-height:380px;overflow-y:auto}
.face-item{display:flex;align-items:center;gap:12px;padding:10px 12px;
  background:var(--bg1);border:1px solid var(--goldbr);border-radius:8px}
.face-av{width:36px;height:36px;border-radius:8px;background:var(--golddim);
  border:1px solid var(--goldbr);display:flex;align-items:center;justify-content:center;
  font-size:13px;font-weight:700;color:var(--gold)}
.face-name{font-size:13px;font-weight:600;color:var(--ink2);flex:1}
.face-cat{font-size:10px;color:var(--ink5);margin-top:2px}
.cat-badge{font-size:10px;padding:2px 8px;border-radius:20px}
.cat-whitelist{background:rgba(24,96,48,.08);color:var(--green);border:1px solid rgba(24,96,48,.15)}
.cat-routine{background:rgba(26,64,112,.07);color:#1a4070;border:1px solid rgba(26,64,112,.15)}
.cat-blacklist{background:rgba(184,50,40,.08);color:var(--red);border:1px solid rgba(184,50,40,.15)}
.empty{text-align:center;padding:30px;color:var(--ink5);font-size:13px}
.note{font-size:11px;color:var(--ink5);margin-top:10px;padding:8px 12px;
  background:rgba(160,120,40,.06);border-radius:6px;border:1px solid var(--goldbr)}
</style>
</head>
<body>
<div class="topbar">
  <div class="logo">ProVisionGuard AI</div>
  <a href="/" class="back">← Back to Dashboard</a>
  <span style="font-size:11px;color:var(--ink5)">Logged in as {{ username }}</span>
</div>
<div class="page">
  <h1>Face Enrollment</h1>
  <p class="sub">Add or remove known persons from the recognition database</p>
  <div class="grid">
    <!-- Add Face -->
    <div class="card">
      <h2>➕ Add New Person</h2>
      <div class="form-group">
        <label>Full Name</label>
        <input type="text" id="fname" placeholder="e.g. John Smith">
      </div>
      <div class="form-group">
        <label>Category</label>
        <select id="fcat">
          <option value="whitelist">Trusted / Whitelist (known person)</option>
          <option value="routine">Routine (regular visitor)</option>
          <option value="blacklist">Blacklist (threat / banned)</option>
        </select>
      </div>
      <div class="form-group">
        <label>Photo</label>
        <div class="upload-box" onclick="document.getElementById('fphoto').click()">
          <div class="icon">📷</div>
          <p>Click to upload photo<br>Clear front-facing photo works best</p>
          <input type="file" id="fphoto" accept="image/*" style="display:none" onchange="previewPhoto(this)">
        </div>
        <img id="preview">
      </div>
      <button class="btn btn-gold" onclick="addFace()">Add to Database</button>
      <div class="msg" id="add-msg"></div>
      <p class="note">⚠ After adding, restart the app for recognition to activate.</p>
    </div>
    <!-- Face List -->
    <div class="card">
      <h2>👥 Enrolled Persons</h2>
      <div class="face-list" id="face-list">
        {% if faces %}
          {% for f in faces %}
          <div class="face-item" id="face-{{ loop.index }}">
            <div class="face-av">{{ f.name[:2] | upper }}</div>
            <div style="flex:1">
              <div class="face-name">{{ f.name }}</div>
              <span class="cat-badge cat-{{ f.category }}">{{ f.category }}</span>
            </div>
            <button class="btn btn-red" onclick="deleteFace('{{ f.name }}','{{ f.category }}',{{ loop.index }})">Remove</button>
          </div>
          {% endfor %}
        {% else %}
          <div class="empty">No faces enrolled yet</div>
        {% endif %}
      </div>
      <div class="note" style="margin-top:12px">
        Total enrolled: <strong>{{ faces | length }}</strong> person(s)<br>
        Add photos from multiple angles for better recognition accuracy.
      </div>
    </div>
  </div>
</div>
<script>
function previewPhoto(input){
  if(input.files&&input.files[0]){
    const r=new FileReader();
    r.onload=e=>{const p=document.getElementById('preview');p.src=e.target.result;p.style.display='block';}
    r.readAsDataURL(input.files[0]);
  }
}
function showMsg(id,msg,ok){
  const el=document.getElementById(id);
  el.textContent=msg;el.className='msg '+(ok?'msg-ok':'msg-err');el.style.display='block';
  setTimeout(()=>el.style.display='none',4000);
}
function addFace(){
  const name=document.getElementById('fname').value.trim();
  const cat=document.getElementById('fcat').value;
  const photo=document.getElementById('fphoto').files[0];
  if(!name){showMsg('add-msg','Name is required',false);return;}
  if(!photo){showMsg('add-msg','Please select a photo',false);return;}
  const fd=new FormData();
  fd.append('name',name);fd.append('category',cat);fd.append('photo',photo);
  fetch('/api/enroll/add',{method:'POST',body:fd})
    .then(r=>r.json()).then(d=>{
      if(d.success){
        showMsg('add-msg',`✅ ${d.name} added! Restart app to activate.`,true);
        document.getElementById('fname').value='';
        document.getElementById('fphoto').value='';
        document.getElementById('preview').style.display='none';
        // Add to list
        const list=document.getElementById('face-list');
        const item=document.createElement('div');item.className='face-item';
        item.innerHTML=`<div class="face-av">${name.slice(0,2).toUpperCase()}</div>
          <div style="flex:1"><div class="face-name">${name}</div>
          <span class="cat-badge cat-${cat}">${cat}</span></div>
          <button class="btn btn-red" onclick="deleteFace('${name}','${cat}',0)">Remove</button>`;
        list.prepend(item);
      } else showMsg('add-msg',d.error||'Error',false);
    }).catch(()=>showMsg('add-msg','Network error',false));
}
function deleteFace(name,cat,idx){
  if(!confirm(`Remove ${name} from database?`))return;
  fetch('/api/enroll/delete',{method:'POST',
    headers:{'Content-Type':'application/json'},
    body:JSON.stringify({name,category:cat})})
    .then(r=>r.json()).then(d=>{
      if(d.success){
        if(idx>0){const el=document.getElementById('face-'+idx);if(el)el.remove();}
        alert(d.message);
      } else alert(d.error||'Error');
    });
}
</script>
</body>
</html>"""

# ── SETUP PAGE HTML ───────────────────────────────────────
SETUP_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>ProVisionGuard — Setup</title>
<link href="https://fonts.googleapis.com/css2?family=Syne:wght@400;700;800&family=DM+Mono:wght@400;500&display=swap" rel="stylesheet">
<style>
*{margin:0;padding:0;box-sizing:border-box}
body{background:#020408;min-height:100vh;font-family:'Syne',sans-serif;color:#ddeeff;
  background-image:linear-gradient(rgba(0,229,255,.012) 1px,transparent 1px),linear-gradient(90deg,rgba(0,229,255,.012) 1px,transparent 1px);background-size:52px 52px;}
.topbar{background:#030810;border-bottom:1px solid rgba(0,229,255,.12);padding:12px 24px;display:flex;align-items:center;gap:12px;}
.tbname{font-size:13px;font-weight:800;letter-spacing:4px;color:#fff;}
.tbsub{font-family:'DM Mono',monospace;font-size:7px;letter-spacing:3px;color:#00e5ff;}
.back{margin-left:auto;font-family:'DM Mono',monospace;font-size:8px;letter-spacing:2px;color:#00e5ff;text-decoration:none;padding:5px 12px;border:1px solid rgba(0,229,255,.2);border-radius:2px;}
.wrap{max-width:900px;margin:30px auto;padding:0 20px;display:grid;gap:20px;}
.card{background:#030810;border:1px solid rgba(0,229,255,.1);border-radius:6px;overflow:hidden;}
.ch{padding:12px 18px;background:#050c18;border-bottom:1px solid rgba(0,229,255,.07);display:flex;align-items:center;gap:8px;}
.cht{font-family:'DM Mono',monospace;font-size:8px;letter-spacing:4px;color:#4a7090;text-transform:uppercase;}
.cb{padding:18px;}
.grid2{display:grid;grid-template-columns:1fr 1fr;gap:12px;}
label{display:block;font-family:'DM Mono',monospace;font-size:7px;letter-spacing:3px;color:#4a7090;text-transform:uppercase;margin-bottom:5px;}
input,select{width:100%;background:#070f1e;border:1px solid rgba(0,229,255,.1);border-radius:3px;padding:10px 12px;color:#ddeeff;font-family:'DM Mono',monospace;font-size:12px;outline:none;transition:border-color .2s;margin-bottom:12px;}
input:focus,select:focus{border-color:rgba(0,229,255,.4);}
.btn{background:rgba(0,229,255,.08);border:1px solid rgba(0,229,255,.25);color:#00e5ff;font-family:'DM Mono',monospace;font-size:8px;letter-spacing:3px;padding:10px 20px;border-radius:3px;cursor:pointer;transition:all .2s;}
.btn:hover{background:rgba(0,229,255,.18);}
.btn-red{background:rgba(255,34,85,.08);border-color:rgba(255,34,85,.25);color:#ff2255;}
.btn-green{background:rgba(0,255,157,.08);border-color:rgba(0,255,157,.25);color:#00ff9d;}
.msg{padding:8px 12px;border-radius:3px;font-family:'DM Mono',monospace;font-size:9px;letter-spacing:2px;margin-top:8px;display:none;}
.msg.ok{background:rgba(0,255,157,.08);border:1px solid rgba(0,255,157,.2);color:#00ff9d;}
.msg.err{background:rgba(255,34,85,.08);border:1px solid rgba(255,34,85,.2);color:#ff2255;}
.plan-grid{display:grid;grid-template-columns:repeat(4,1fr);gap:10px;}
.plan{background:#070f1e;border:1px solid rgba(0,229,255,.08);border-radius:4px;padding:14px;text-align:center;}
.plan.active{border-color:rgba(0,255,157,.3);background:rgba(0,255,157,.04);}
.plan-name{font-weight:800;font-size:13px;letter-spacing:2px;margin-bottom:4px;}
.plan-price{font-family:'DM Mono',monospace;font-size:10px;color:#00e5ff;margin-bottom:8px;}
.plan-feat{font-family:'DM Mono',monospace;font-size:7px;color:#4a7090;line-height:1.8;}
.lic-status{display:flex;gap:16px;flex-wrap:wrap;margin-bottom:14px;}
.ls{background:#070f1e;border:1px solid rgba(0,229,255,.08);border-radius:3px;padding:8px 16px;min-width:120px;}
.lsv{font-family:'DM Mono',monospace;font-size:15px;font-weight:700;color:#00e5ff;}
.lsl{font-family:'DM Mono',monospace;font-size:6px;letter-spacing:3px;color:#4a7090;margin-top:2px;text-transform:uppercase;}
.mid{font-family:'DM Mono',monospace;font-size:9px;color:#4a7090;padding:8px 0;}
.swatch{width:36px;height:36px;border-radius:4px;border:2px solid rgba(255,255,255,.1);cursor:pointer;display:inline-block;vertical-align:middle;margin-right:8px;}
</style>
</head>
<body>
<div class="topbar">
  <div>
    <div class="tbname">PROVISIONGUARD</div>
    <div class="tbsub">SETUP & CONFIGURATION</div>
  </div>
  <a href="/" class="back">← DASHBOARD</a>
</div>
<div class="wrap">

  <!-- LICENSE CARD -->
  <div class="card">
    <div class="ch"><span class="cht">License Management</span></div>
    <div class="cb">
      <div class="lic-status">
        <div class="ls"><div class="lsv" id="s-plan">{{ license.plan }}</div><div class="lsl">Current Plan</div></div>
        <div class="ls"><div class="lsv" id="s-days" style="color:{% if days_left < 7 %}#ff2255{% elif days_left < 30 %}#ff8800{% else %}#00ff9d{% endif %}">{{ days_left }}</div><div class="lsl">Days Left</div></div>
        <div class="ls"><div class="lsv" style="font-size:11px;color:#4a7090">{{ license.expiry }}</div><div class="lsl">Expiry Date</div></div>
        <div class="ls"><div class="lsv" style="font-size:10px;color:#4a7090">{{ license.customer or 'Trial' }}</div><div class="lsl">Customer</div></div>
      </div>
      <div class="mid">Machine ID: {{ machine_id }}</div>
      <div class="grid2">
        <div>
          <label>Customer Name</label>
          <input type="text" id="lic-cust" placeholder="Enter customer/company name" value="{{ license.customer or '' }}">
          <label>License Key</label>
          <input type="text" id="lic-key" placeholder="PVG-PRO-XXXX-XXXX-XXXX-XXXX" value="{{ license.key or '' }}">
          <button class="btn btn-green" onclick="activateLicense()">→ ACTIVATE LICENSE</button>
          <div class="msg" id="lic-msg"></div>
        </div>
        <div>
          <div style="font-family:'DM Mono',monospace;font-size:8px;letter-spacing:2px;color:#4a7090;margin-bottom:10px;text-transform:uppercase">Available Plans</div>
          <div class="plan-grid" style="grid-template-columns:1fr 1fr">
            {% for p,info in plans.items() %}
            <div class="plan {% if license.plan == p %}active{% endif %}">
              <div class="plan-name" style="color:{% if p=='ENTERPRISE' %}#ffcc00{% elif p=='PRO' %}#00e5ff{% elif p=='BASIC' %}#00ff9d{% else %}#4a7090{% endif %}">{{ p }}</div>
              <div class="plan-price">{{ info.price }}</div>
              <div class="plan-feat">
                {{ info.cameras }}x cam<br>
                {% if info.faces %}Face Recog<br>{% endif %}
                {% if info.api %}API Access<br>{% endif %}
                {{ info.days }}d validity
              </div>
            </div>
            {% endfor %}
          </div>
        </div>
      </div>
    </div>
  </div>

  <!-- BRANDING CARD -->
  <div class="card">
    <div class="ch"><span class="cht">Branding & Customization</span></div>
    <div class="cb">
      <div class="grid2">
        <div>
          <label>Company Name</label>
          <input type="text" id="b-name" value="{{ branding.company_name }}" placeholder="Your Company Name">
          <label>Tagline</label>
          <input type="text" id="b-tag" value="{{ branding.tagline }}" placeholder="Your tagline">
          <label>Logo Text (2-3 chars)</label>
          <input type="text" id="b-logo" value="{{ branding.logo_text }}" maxlength="3" placeholder="PVG">
          <label>Footer Text</label>
          <input type="text" id="b-foot" value="{{ branding.footer_text }}" placeholder="Footer text">
        </div>
        <div>
          <label>Contact Email</label>
          <input type="email" id="b-email" value="{{ branding.contact_email }}" placeholder="support@yourcompany.com">
          <label>Contact Phone</label>
          <input type="text" id="b-phone" value="{{ branding.contact_phone }}" placeholder="+91 98765 43210">
          <label>Primary Color</label>
          <input type="color" id="b-color" value="{{ branding.primary_color }}" style="height:40px;padding:4px;">
          <label>Accent Color</label>
          <input type="color" id="b-accent" value="{{ branding.accent_color }}" style="height:40px;padding:4px;">
        </div>
      </div>
      <button class="btn" onclick="saveBranding()">→ SAVE BRANDING</button>
      <div class="msg" id="brand-msg"></div>
    </div>
  </div>

</div>
<script>
function showMsg(id, text, ok){
  const el=document.getElementById(id);
  el.textContent=text;el.className='msg '+(ok?'ok':'err');el.style.display='block';
  setTimeout(()=>el.style.display='none',3000);
}
function activateLicense(){
  const key=document.getElementById('lic-key').value.trim();
  const cust=document.getElementById('lic-cust').value.trim();
  if(!key||!cust){showMsg('lic-msg','Key and customer name required',false);return;}
  fetch('/api/license/activate',{method:'POST',headers:{'Content-Type':'application/json'},
    body:JSON.stringify({key,customer:cust})})
  .then(r=>r.json()).then(d=>{
    if(d.success){
      showMsg('lic-msg','License activated! Plan: '+d.plan+' | '+d.days+'d',true);
      document.getElementById('s-plan').textContent=d.plan;
      document.getElementById('s-days').textContent=d.days;
    } else {
      showMsg('lic-msg',d.error||'Activation failed',false);
    }
  }).catch(()=>showMsg('lic-msg','Network error',false));
}
function saveBranding(){
  const data={
    company_name:document.getElementById('b-name').value,
    tagline:document.getElementById('b-tag').value,
    logo_text:document.getElementById('b-logo').value,
    footer_text:document.getElementById('b-foot').value,
    contact_email:document.getElementById('b-email').value,
    contact_phone:document.getElementById('b-phone').value,
    primary_color:document.getElementById('b-color').value,
    accent_color:document.getElementById('b-accent').value,
  };
  fetch('/api/branding/update',{method:'POST',headers:{'Content-Type':'application/json'},
    body:JSON.stringify(data)})
  .then(r=>r.json()).then(d=>{
    if(d.success) showMsg('brand-msg','Branding saved! Refresh dashboard to see changes.',true);
    else showMsg('brand-msg','Failed to save',false);
  }).catch(()=>showMsg('brand-msg','Network error',false));
}
</script>

<!-- ALERT CONFIG SECTION -->
<style>
.alert-section{background:#fff;border:1px solid #e0d9cc;border-radius:12px;padding:20px;margin-top:20px}
.alert-section h3{font-size:14px;font-weight:700;color:#2d2410;margin-bottom:16px;padding-bottom:10px;border-bottom:1px solid #e0d9cc}
.alert-group{margin-bottom:16px;padding:14px;background:#f5f0e8;border-radius:8px;border:1px solid #e0d9cc}
.alert-group h4{font-size:12px;font-weight:700;color:#a07828;margin-bottom:10px;text-transform:uppercase;letter-spacing:.5px}
.ag-row{display:flex;gap:10px;margin-bottom:8px;align-items:center}
.ag-row label{font-size:11px;font-weight:600;color:#7a6840;width:90px;flex-shrink:0}
.ag-row input{flex:1;padding:7px 10px;border:1px solid #e0d9cc;border-radius:6px;font-size:12px;background:#fff;color:#2d2410}
.toggle-row{display:flex;align-items:center;gap:10px;margin-top:6px}
.toggle{position:relative;width:42px;height:22px;cursor:pointer}
.toggle input{opacity:0;width:0;height:0;position:absolute}
.toggle-slider{position:absolute;inset:0;background:#ccc;border-radius:11px;transition:.3s}
.toggle input:checked+.toggle-slider{background:#a07828}
.toggle-slider::before{content:'';position:absolute;width:16px;height:16px;left:3px;bottom:3px;background:#fff;border-radius:50%;transition:.3s}
.toggle input:checked+.toggle-slider::before{transform:translateX(20px)}
.toggle-lbl{font-size:12px;color:#2d2410}
.save-alert-btn{background:#a07828;color:#fff;border:none;border-radius:8px;padding:9px 20px;font-size:12px;font-weight:600;cursor:pointer;margin-top:10px}
.test-btn{background:#f5f0e8;color:#a07828;border:1px solid #a07828;border-radius:8px;padding:9px 16px;font-size:12px;font-weight:600;cursor:pointer;margin-top:10px;margin-left:8px}
.alert-msg{margin-top:8px;padding:8px 12px;border-radius:6px;font-size:12px;display:none}
.a-ok{background:rgba(24,96,48,.1);border:1px solid rgba(24,96,48,.2);color:#186030}
.a-err{background:rgba(184,50,40,.08);border:1px solid rgba(184,50,40,.2);color:#b83228}
</style>

<div class="alert-section" style="max-width:700px;margin:20px auto">
  <h3>📱 Alert Configuration — WhatsApp & Telegram</h3>
  
  <!-- WhatsApp -->
  <div class="alert-group">
    <h4>📱 WhatsApp (CallMeBot)</h4>
    <div style="font-size:11px;color:#7a6840;margin-bottom:10px">
      Setup: Send "I allow callmebot to send me messages" to +1 (251) 302-5541 on WhatsApp → Get API key
    </div>
    <div class="ag-row">
      <label>Phone No.</label>
      <input id="wa-phone" type="text" placeholder="+919876543210 (with country code)" value="">
    </div>
    <div class="ag-row">
      <label>API Key</label>
      <input id="wa-key" type="text" placeholder="CallMeBot API key">
    </div>
    <div class="toggle-row">
      <label class="toggle"><input type="checkbox" id="wa-enabled"><span class="toggle-slider"></span></label>
      <span class="toggle-lbl">Enable WhatsApp Alerts</span>
    </div>
  </div>

  <!-- Telegram -->
  <div class="alert-group">
    <h4>✈️ Telegram Bot</h4>
    <div style="font-size:11px;color:#7a6840;margin-bottom:10px">
      Setup: 1) Create bot via @BotFather → get Token &nbsp; 2) Get your Chat ID via @userinfobot
    </div>
    <div class="ag-row">
      <label>Bot Token</label>
      <input id="tg-key" type="text" placeholder="1234567890:AAFxxxxxxx (from @BotFather)">
    </div>
    <div class="ag-row">
      <label>Chat ID</label>
      <input id="tg-chat" type="text" placeholder="Your Telegram Chat ID (from @userinfobot)">
    </div>
    <div class="toggle-row">
      <label class="toggle"><input type="checkbox" id="tg-enabled"><span class="toggle-slider"></span></label>
      <span class="toggle-lbl">Enable Telegram Alerts</span>
    </div>
  </div>

  <button class="save-alert-btn" onclick="saveAlerts()">💾 Save Alert Config</button>
  <button class="test-btn" onclick="testAlerts()">🔔 Send Test Alert</button>
  <div class="alert-msg" id="alert-msg"></div>
</div>

<script>
// Load existing config
fetch('/api/whatsapp/config').then(r=>r.json()).then(d=>{
  if(d.phone) document.getElementById('wa-phone').value=d.phone;
  if(d.apikey) document.getElementById('wa-key').value=d.apikey;
  if(d.enabled) document.getElementById('wa-enabled').checked=true;
  if(d.tg_apikey) document.getElementById('tg-key').value=d.tg_apikey;
  if(d.tg_chatid) document.getElementById('tg-chat').value=d.tg_chatid;
  if(d.tg_enabled) document.getElementById('tg-enabled').checked=true;
}).catch(()=>{});

function showAlertMsg(msg,ok){
  const el=document.getElementById('alert-msg');
  el.textContent=msg;el.className='alert-msg '+(ok?'a-ok':'a-err');el.style.display='block';
  setTimeout(()=>el.style.display='none',4000);
}

function saveAlerts(){
  const data={
    phone: document.getElementById('wa-phone').value.trim(),
    apikey: document.getElementById('wa-key').value.trim(),
    enabled: document.getElementById('wa-enabled').checked,
    tg_apikey: document.getElementById('tg-key').value.trim(),
    tg_chatid: document.getElementById('tg-chat').value.trim(),
    tg_enabled: document.getElementById('tg-enabled').checked,
  };
  fetch('/api/whatsapp/config',{
    method:'POST',
    headers:{'Content-Type':'application/json'},
    body:JSON.stringify(data)
  }).then(r=>r.json()).then(d=>{
    if(d.success) showAlertMsg('✅ Alert config saved!',true);
    else showAlertMsg('❌ Failed: '+d.error,false);
  }).catch(()=>showAlertMsg('❌ Network error',false));
}

function testAlerts(){
  fetch('/api/whatsapp/test',{method:'POST'})
    .then(r=>r.json())
    .then(d=>showAlertMsg('✅ Test alert sent to all enabled channels!',true))
    .catch(()=>showAlertMsg('❌ Test failed — check config',false));
}
</script>
</body>
</html>"""

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
<link href="https://fonts.googleapis.com/css2?family=Outfit:wght@400;500;600;700&family=JetBrains+Mono:wght@300;400;500&display=swap" rel="stylesheet">
<script src="https://cdnjs.cloudflare.com/ajax/libs/socket.io/4.7.2/socket.io.min.js"></script>
<style>
*{margin:0;padding:0;box-sizing:border-box}
:root{
  --bg:#f5f0e8;--bg1:#faf7f2;--bg2:#fff;
  --gold:#a07828;--gold2:#c49a38;
  --golddim:rgba(160,120,40,.09);--goldbr:rgba(160,120,40,.2);
  --ink:#1a1508;--ink2:#2d2410;--ink3:#4a3c1e;--ink4:#7a6840;--ink5:#b0a078;
  --red:#b83228;--orange:#b86020;--green:#186030;--blue:#1a4070;
  --sh:0 1px 3px rgba(160,120,40,.08);
}
html,body{height:100%;overflow:hidden}
body{background:var(--bg);font-family:'Outfit',sans-serif;color:var(--ink);display:flex;flex-direction:column}
.top{display:flex;align-items:center;height:44px;background:var(--bg1);border-bottom:1px solid var(--goldbr);flex-shrink:0;padding:0 12px;gap:10px}
.logo{width:28px;height:28px;border-radius:6px;background:var(--golddim);border:1px solid var(--goldbr);display:flex;align-items:center;justify-content:center;font-family:'JetBrains Mono',monospace;font-size:6px;font-weight:500;color:var(--gold);letter-spacing:1px;flex-shrink:0}
.brand{font-size:12px;font-weight:700;color:var(--ink2);flex-shrink:0}
.nav{display:flex;gap:0;margin-left:8px;flex:1}
.nb{font-size:10px;font-weight:500;color:var(--ink4);padding:0 12px;height:44px;display:flex;align-items:center;border-bottom:2px solid transparent;cursor:pointer}
.nb.on{color:var(--gold);border-bottom-color:var(--gold)}
.tr{display:flex;align-items:center;gap:8px;flex-shrink:0}
.chip{font-family:'JetBrains Mono',monospace;font-size:5.5px;letter-spacing:1.5px;padding:2px 8px;border-radius:20px;display:flex;align-items:center;gap:3px;text-transform:uppercase}
.cl{background:rgba(24,96,48,.08);border:1px solid rgba(24,96,48,.18);color:var(--green)}
.cg{background:var(--golddim);border:1px solid var(--goldbr);color:var(--gold)}
.ld{width:4px;height:4px;border-radius:50%;background:var(--green);animation:p 2s ease infinite}
@keyframes p{0%,100%{opacity:1}50%{opacity:.4}}
.clk{font-family:'JetBrains Mono',monospace;font-size:10px;color:var(--gold);letter-spacing:2px}
.av{width:26px;height:26px;border-radius:50%;background:var(--golddim);border:1px solid var(--goldbr);display:flex;align-items:center;justify-content:center;font-size:9px;font-weight:700;color:var(--gold)}
.grid{flex:1;display:grid;grid-template-columns:200px 1fr 215px;grid-template-rows:28px 1fr;overflow:hidden;min-height:0}
.stats{grid-column:1/-1;grid-row:1;display:grid;grid-template-columns:repeat(6,1fr);gap:1px;background:var(--goldbr);border-bottom:1px solid var(--goldbr)}
.sc{background:var(--bg1);padding:4px 10px;display:flex;align-items:center;gap:8px}
.sc-lbl{font-family:'JetBrains Mono',monospace;font-size:5px;letter-spacing:2px;color:var(--ink5);text-transform:uppercase;white-space:nowrap}
.sc-val{font-size:14px;font-weight:700;letter-spacing:-0.5px;color:var(--ink2)}
.sc-val.gold{color:var(--gold)}
.sc-pill{font-family:'JetBrains Mono',monospace;font-size:5px;letter-spacing:1px;padding:1px 6px;border-radius:20px;text-transform:uppercase;margin-left:auto;white-space:nowrap}
.sg{background:rgba(24,96,48,.07);border:1px solid rgba(24,96,48,.15);color:var(--green)}
.so{background:rgba(184,96,32,.07);border:1px solid rgba(184,96,32,.15);color:var(--orange)}
.sr{background:rgba(184,50,40,.07);border:1px solid rgba(184,50,40,.15);color:var(--red)}
.sgo{background:var(--golddim);border:1px solid var(--goldbr);color:var(--gold)}
.left{grid-column:1;grid-row:2;border-right:1px solid var(--goldbr);display:flex;flex-direction:column;overflow:hidden}
.ph{padding:6px 10px;border-bottom:1px solid var(--goldbr);background:var(--bg1);display:flex;align-items:center;gap:6px;flex-shrink:0}
.ph-t{font-size:10px;font-weight:600;color:var(--ink2);flex:1}
.ph-c{font-family:'JetBrains Mono',monospace;font-size:5px;letter-spacing:1.5px;padding:2px 7px;border-radius:20px;background:var(--golddim);border:1px solid var(--goldbr);color:var(--gold)}
.ps{flex:1;overflow-y:auto;padding:5px}
.pe{display:flex;align-items:center;justify-content:center;height:60px;font-family:'JetBrains Mono',monospace;font-size:6px;letter-spacing:2px;color:var(--ink5);text-transform:uppercase}
.pc{background:var(--bg2);border:1px solid var(--goldbr);border-radius:6px;margin-bottom:5px;border-left:2px solid var(--pcol,var(--ink5));box-shadow:var(--sh);overflow:hidden}
.pch{padding:5px 7px;display:flex;align-items:center;gap:6px}
.pav{width:24px;height:24px;border-radius:5px;flex-shrink:0;display:flex;align-items:center;justify-content:center;font-size:8px;font-weight:700;background:var(--golddim);border:1px solid var(--goldbr);color:var(--gold)}
.pnm{font-size:10px;font-weight:600;color:var(--ink2);white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.pct-lbl{font-family:'JetBrains Mono',monospace;font-size:5px;letter-spacing:1px;color:var(--ink5);text-transform:uppercase;margin-top:1px}
.ptp{font-family:'JetBrains Mono',monospace;font-size:5px;letter-spacing:1px;padding:1px 6px;border-radius:20px;margin-left:auto;flex-shrink:0;text-transform:uppercase}
.tp-trusted{background:rgba(24,96,48,.08);border:1px solid rgba(24,96,48,.18);color:var(--green)}
.tp-safe{background:rgba(24,96,48,.06);border:1px solid rgba(24,96,48,.12);color:var(--green)}
.tp-watch{background:var(--golddim);border:1px solid var(--goldbr);color:var(--gold)}
.tp-medium{background:rgba(184,96,32,.07);border:1px solid rgba(184,96,32,.16);color:var(--orange)}
.tp-high{background:rgba(184,50,40,.07);border:1px solid rgba(184,50,40,.15);color:var(--red)}
.tp-critical,.tp-blacklist{background:rgba(184,50,40,.12);border:1px solid rgba(184,50,40,.24);color:var(--red)}
.pbr{padding:0 7px 4px;display:flex;align-items:center;gap:5px}
.pbrl{font-family:'JetBrains Mono',monospace;font-size:5px;letter-spacing:1px;color:var(--ink5);text-transform:uppercase;width:24px;flex-shrink:0}
.pbrb{flex:1;height:2px;background:rgba(160,120,40,.1);border-radius:1px;overflow:hidden}
.pbrf{height:100%;border-radius:1px;transition:width .8s}
.pbrv{font-family:'JetBrains Mono',monospace;font-size:5.5px;width:20px;text-align:right}
.pint{padding:0 7px 5px}
.pint-box{background:rgba(160,120,40,.05);border:1px solid rgba(160,120,40,.1);border-radius:5px;padding:4px 6px}
.pint-row{display:grid;grid-template-columns:16px 1fr;gap:2px;margin-bottom:2px}
.pik{font-family:'JetBrains Mono',monospace;font-size:5px;letter-spacing:1px;color:var(--ink5);text-transform:uppercase}
.piv{font-size:7px;font-weight:500;color:var(--ink3);line-height:1.3}
.pib{height:1.5px;background:rgba(160,120,40,.1);margin-top:3px;overflow:hidden;border-radius:1px}
.pibf{height:100%;transition:width .8s}
.pimeta{display:flex;gap:6px;margin-top:3px}
.pim{font-family:'JetBrains Mono',monospace;font-size:5px;color:var(--ink5)}
.pim span{color:var(--ink3)}
.ptags{display:flex;flex-wrap:wrap;gap:2px;padding:0 7px 4px}
.ptag{font-family:'JetBrains Mono',monospace;font-size:5px;padding:1px 4px;border-radius:20px;background:rgba(160,120,40,.07);color:var(--ink4);border:1px solid var(--goldbr);text-transform:uppercase}
.ptag.t{background:rgba(184,50,40,.07);color:var(--red);border-color:rgba(184,50,40,.15)}
.center{grid-column:2;grid-row:2;display:flex;flex-direction:column;overflow:hidden}
.cam-hdr{padding:6px 12px;border-bottom:1px solid var(--goldbr);background:var(--bg1);display:flex;align-items:center;gap:7px;flex-shrink:0}
.cam-body{flex:1;background:#0a0806;position:relative;overflow:hidden;min-height:0}
#cam-feed{width:100%;height:100%;object-fit:cover;display:block}
.cam-err{display:none;position:absolute;inset:0;background:#0a0806;flex-direction:column;align-items:center;justify-content:center;gap:8px}
.cam-err-t{font-family:'JetBrains Mono',monospace;font-size:7px;letter-spacing:4px;color:rgba(200,160,60,.25);text-transform:uppercase}
.sln{position:absolute;left:0;right:0;height:1px;background:linear-gradient(90deg,transparent,rgba(196,154,56,.12),transparent);animation:sc 5s ease-in-out infinite}
@keyframes sc{0%{top:0;opacity:.4}88%{top:100%;opacity:.06}100%{top:0;opacity:.4}}
.vgn{position:absolute;inset:0;background:radial-gradient(ellipse at center,transparent 38%,rgba(0,0,0,.7) 100%)}
.brk{position:absolute;width:16px;height:16px}
.brk::before,.brk::after{content:'';position:absolute;background:rgba(196,154,56,.4);border-radius:1px}
.brk.tl{top:9px;left:9px}.brk.tr{top:9px;right:9px}.brk.bl{bottom:9px;left:9px}.brk.br{bottom:9px;right:9px}
.brk.tl::before,.brk.tr::before,.brk.bl::before,.brk.br::before{width:100%;height:1.5px;top:0}
.brk.bl::before,.brk.br::before{bottom:0;top:auto}
.brk.tl::after,.brk.bl::after{left:0;width:1.5px;height:100%;top:0}
.brk.tr::after,.brk.br::after{right:0;width:1.5px;height:100%;top:0}
.otags{position:absolute;bottom:36px;left:9px;right:9px;display:flex;flex-wrap:wrap;gap:3px;z-index:3}
.otag{font-family:'JetBrains Mono',monospace;font-size:5.5px;letter-spacing:1px;padding:2px 7px;border-radius:20px;text-transform:uppercase}
.op{background:rgba(196,154,56,.14);border:1px solid rgba(196,154,56,.28);color:var(--gold2)}
.ow{background:rgba(184,50,40,.18);border:1px solid rgba(184,50,40,.32);color:#e06050}
.oh{background:rgba(26,64,112,.15);border:1px solid rgba(26,64,112,.28);color:#6090d0}
.ctop{position:absolute;top:8px;left:8px;right:8px;display:flex;gap:5px;align-items:center;z-index:2}
.hp{font-family:'JetBrains Mono',monospace;font-size:5.5px;letter-spacing:1.5px;padding:2px 8px;border-radius:20px;display:flex;align-items:center;gap:3px;text-transform:uppercase}
.hr{background:rgba(184,50,40,.22);border:1px solid rgba(184,50,40,.35);color:#e06050}
.hf{background:rgba(196,154,56,.12);border:1px solid rgba(196,154,56,.25);color:var(--gold2)}
.hc{background:rgba(0,0,0,.35);border:1px solid rgba(196,154,56,.15);color:rgba(255,255,255,.5)}
.hn{background:rgba(26,64,112,.22);border:1px solid rgba(26,64,112,.35);color:#6090d0;display:none}
.hfg{background:rgba(26,64,112,.18);border:1px solid rgba(26,64,112,.28);color:#6090d0;display:none}
.rd{width:4px;height:4px;border-radius:50%;background:#e06050;animation:rb .9s ease infinite}
@keyframes rb{0%,100%{opacity:1}50%{opacity:.15}}
.cbot{position:absolute;bottom:8px;left:10px;right:10px;display:flex;align-items:flex-end;justify-content:space-between;z-index:2}
.cnum{font-size:32px;font-weight:700;color:#fff;line-height:1;letter-spacing:-1.5px}
.cnlbl{font-family:'JetBrains Mono',monospace;font-size:5px;letter-spacing:3px;color:rgba(255,255,255,.2);text-transform:uppercase}
.cts{font-family:'JetBrains Mono',monospace;font-size:6px;color:rgba(255,255,255,.15);letter-spacing:1px}
.nind{position:absolute;top:8px;right:8px;z-index:3;font-family:'JetBrains Mono',monospace;font-size:5.5px;letter-spacing:2px;padding:2px 8px;border-radius:20px;background:rgba(26,64,112,.22);border:1px solid rgba(26,64,112,.35);color:#6090d0;text-transform:uppercase;display:none}
.cwd{display:none;position:absolute;top:50%;left:50%;transform:translate(-50%,-50%);font-family:'JetBrains Mono',monospace;font-size:7px;letter-spacing:3px;padding:7px 18px;border-radius:7px;background:rgba(184,96,32,.14);border:1px solid rgba(184,96,32,.28);color:var(--orange);text-transform:uppercase;z-index:5}
.cld{position:absolute;inset:0;background:rgba(5,4,2,.88);display:flex;flex-direction:column;align-items:center;justify-content:center;gap:10px;z-index:10}
.cld.gone{display:none}
.clr{width:24px;height:24px;border-radius:50%;border:1px solid rgba(196,154,56,.2);border-top-color:var(--gold2);animation:spin 1s linear infinite}
@keyframes spin{to{transform:rotate(360deg)}}
.clt{font-family:'JetBrains Mono',monospace;font-size:7px;letter-spacing:4px;color:var(--gold2);text-transform:uppercase;animation:gp 1.8s ease infinite}
@keyframes gp{0%,100%{opacity:.3}50%{opacity:1}}
.srcbar{padding:4px 12px;border-bottom:1px solid var(--goldbr);background:var(--bg2);display:flex;align-items:center;gap:6px;flex-shrink:0}
.slbl{font-family:'JetBrains Mono',monospace;font-size:5.5px;letter-spacing:1.5px;color:var(--ink5);text-transform:uppercase}
.sbtn{font-family:'JetBrains Mono',monospace;font-size:5.5px;letter-spacing:1px;padding:3px 10px;border-radius:20px;cursor:pointer;text-transform:uppercase;border:1px solid var(--goldbr);background:transparent;color:var(--ink4)}
.sbtn.on{background:var(--golddim);color:var(--gold);border-color:var(--gold2)}
.sinf{font-family:'JetBrains Mono',monospace;font-size:5.5px;color:var(--ink5)}
.right{grid-column:3;grid-row:2;border-left:1px solid var(--goldbr);display:flex;flex-direction:column;overflow:hidden}
.rph{padding:5px 10px;border-bottom:1px solid var(--goldbr);background:var(--bg1);display:flex;align-items:center;justify-content:space-between;flex-shrink:0}
.rpt{font-size:10px;font-weight:600;color:var(--ink2)}
.rpb{font-family:'JetBrains Mono',monospace;font-size:5px;letter-spacing:1.5px;padding:2px 7px;border-radius:20px;background:var(--golddim);border:1px solid var(--goldbr);color:var(--gold)}
.mwrap{padding:0 10px 8px;perspective:500px;flex-shrink:0}
.mfloor{background:var(--ink2);border:1px solid var(--goldbr);border-radius:8px;height:90px;position:relative;overflow:hidden;transform:rotateX(32deg) scale(.88);transform-origin:bottom center;transition:transform .4s}
.mwrap:hover .mfloor{transform:rotateX(20deg) scale(.93)}
.mfloor::before{content:'';position:absolute;inset:0;background:linear-gradient(rgba(196,154,56,.05) 1px,transparent 1px),linear-gradient(90deg,rgba(196,154,56,.05) 1px,transparent 1px);background-size:16% 16%}
.ml{position:absolute;font-family:'JetBrains Mono',monospace;font-size:5px;letter-spacing:1.5px;color:rgba(196,154,56,.18);text-transform:uppercase;padding:3px 5px}
.cnw{position:absolute}
.cnn{width:7px;height:7px;border-radius:50%;background:rgba(196,154,56,.15);border:1px solid rgba(196,154,56,.35)}
.cnr{position:absolute;top:50%;left:50%;transform:translate(-50%,-50%);width:18px;height:18px;border-radius:50%;border:1px solid rgba(196,154,56,.12);animation:ring 2.5s ease-out infinite}
@keyframes ring{0%{opacity:.4;transform:translate(-50%,-50%) scale(.3)}100%{opacity:0;transform:translate(-50%,-50%) scale(1)}}
.md{position:absolute;width:6px;height:6px;border-radius:50%;transition:all 1.5s}
.md-s{background:#22a855;box-shadow:0 0 6px rgba(34,168,85,.5)}
.md-w{background:#c87028;box-shadow:0 0 6px rgba(200,112,40,.5)}
.md-c{background:#b83228;box-shadow:0 0 8px rgba(184,50,40,.6)}
.md-u{background:#1a70b0;box-shadow:0 0 6px rgba(26,112,176,.4)}
.mgrid{display:grid;grid-template-columns:1fr 1fr;gap:4px;padding:0 10px 7px;flex-shrink:0}
.mc{background:var(--bg2);border:1px solid var(--goldbr);border-radius:6px;padding:5px 8px}
.mcl{font-family:'JetBrains Mono',monospace;font-size:5px;letter-spacing:2px;color:var(--ink5);text-transform:uppercase}
.mcv{font-size:14px;font-weight:700;letter-spacing:-0.8px;margin-top:2px}
.mvg{color:var(--gold)}.mvgr{color:var(--green)}.mvo{color:var(--orange)}
.garea{height:48px;padding:0 10px;flex-shrink:0}
.garea svg{width:100%;height:100%}
.gleg{display:flex;gap:10px;padding:2px 10px 5px;flex-shrink:0}
.gl{display:flex;align-items:center;gap:3px;font-family:'JetBrains Mono',monospace;font-size:5px;letter-spacing:1.5px;color:var(--ink5);text-transform:uppercase}
.gln{width:10px;height:1px}
.alist{flex:1;overflow:hidden;display:flex;flex-direction:column;gap:3px;padding:0 8px 6px}
.ae-txt{display:flex;align-items:center;justify-content:center;padding:10px;font-family:'JetBrains Mono',monospace;font-size:5.5px;letter-spacing:2px;color:var(--ink5);text-transform:uppercase}
.ar{display:flex;align-items:flex-start;gap:5px;padding:5px 6px;border-radius:6px;border:1px solid;animation:ai .3s ease}
@keyframes ai{from{opacity:0;transform:translateX(-4px)}to{opacity:1;transform:translateX(0)}}
.ar-c{background:rgba(184,50,40,.04);border-color:rgba(184,50,40,.13)}
.ar-h{background:rgba(184,96,32,.04);border-color:rgba(184,96,32,.12)}
.ar-m{background:rgba(160,120,40,.04);border-color:rgba(160,120,40,.12)}
.ar-i{background:rgba(26,64,112,.03);border-color:rgba(26,64,112,.1)}
.adot{width:4px;height:4px;border-radius:50%;flex-shrink:0;margin-top:3px}
.adr{background:var(--red)}.ado{background:var(--orange)}.adg{background:var(--gold)}.adb{background:var(--blue)}
.atxt{font-family:'JetBrains Mono',monospace;font-size:5.5px;color:var(--ink3);line-height:1.4}
.atm{font-family:'JetBrains Mono',monospace;font-size:5px;color:var(--ink5);margin-top:1px}
.foot{height:28px;background:var(--bg1);border-top:1px solid var(--goldbr);display:flex;align-items:center;flex-shrink:0}
.fi{font-family:'JetBrains Mono',monospace;font-size:5.5px;letter-spacing:1.5px;color:var(--ink5);text-transform:uppercase;display:flex;align-items:center;gap:3px;padding:0 10px;border-right:1px solid var(--goldbr);height:100%}
.fi span{color:var(--gold)}
.fdot{width:4px;height:4px;border-radius:50%;background:var(--green)}
.fbtns{margin-left:auto;display:flex;gap:5px;padding-right:10px}
.fb{font-family:'JetBrains Mono',monospace;font-size:5.5px;letter-spacing:1px;padding:4px 10px;border-radius:20px;border:1px solid var(--goldbr);background:var(--bg2);color:var(--ink4);cursor:pointer;text-transform:uppercase}
.fb-g{background:var(--golddim);color:var(--gold)}
::-webkit-scrollbar{width:2px}::-webkit-scrollbar-track{background:var(--bg1)}::-webkit-scrollbar-thumb{background:rgba(160,120,40,.3);border-radius:2px}
</style>
</head>
<body>
<div class="top">
  <div class="logo">PVG</div>
  <div class="brand">ProVisionGuard AI</div>
  <div class="nav">
    <div class="nb on">Dashboard</div>
    <div class="nb" onclick="openHistory()">History</div>
    <div class="nb" onclick="location.href='/setup'">Setup</div>
    <div class="nb" onclick="location.href='/logout'">Logout</div>
  </div>
  <div class="tr">
    <div class="chip cl"><div class="ld"></div>Live</div>
    <div class="chip cg">{{ role | upper }}</div>
    <div class="clk" id="hclk">--:--:--</div>
    <div class="av">{{ username[:2] | upper }}</div>
  </div>
</div>
<div class="grid">
  <div class="stats">
    <div class="sc"><div class="sc-lbl">Persons</div><div class="sc-val gold" id="h-p">0</div><div class="sc-pill sg" id="sc-pp">0 known</div></div>
    <div class="sc"><div class="sc-lbl">FPS</div><div class="sc-val" id="h-f">--</div><div class="sc-pill sgo">GPU</div></div>
    <div class="sc"><div class="sc-lbl">Alerts</div><div class="sc-val" id="h-a">0</div><div class="sc-pill so" id="sc-ap">Session</div></div>
    <div class="sc"><div class="sc-lbl">Threat</div><div class="sc-val" id="h-tl" style="font-size:11px">CLEAR</div><div class="sc-pill sg" id="sc-tlp">Clear</div></div>
    <div class="sc"><div class="sc-lbl">Objects</div><div class="sc-val" id="h-obj">0</div><div class="sc-pill sgo">Monitor</div></div>
    <div class="sc"><div class="sc-lbl">DB Alerts</div><div class="sc-val" id="h-db">--</div><div class="sc-pill sgo">Total</div></div>
  </div>
  <div class="left">
    <div class="ph"><div class="ph-t">Detected Persons</div><div class="ph-c" id="pcnt">0</div></div>
    <div class="ps" id="plist"><div class="pe" id="pe">Awaiting...</div></div>
  </div>
  <div class="center">
    <div class="cam-hdr">
      <div class="ph-t">Live Feed — CAM 01</div>
      <div class="ph-c" id="fpsbadge">-- FPS</div>
      <div style="font-family:'JetBrains Mono',monospace;font-size:5.5px;letter-spacing:1.5px;padding:2px 8px;border-radius:20px;background:rgba(26,21,8,.04);border:1px solid var(--goldbr);color:var(--ink4)" id="mbadge">LIVE</div>
    </div>
    <div class="srcbar">
      <span class="slbl">Source:</span>
      <button class="sbtn on" id="blv" onclick="setMode('live')">Live Camera</button>
      <button class="sbtn" id="bft" onclick="setMode('footage')">Footage</button>
      <span class="sinf" id="sinfo" style="display:none">demo/demo_video.mp4</span>
    </div>
    <div class="cam-body">
      <img id="cam-feed" src="/video_feed/0" alt=""
           onerror="this.style.display='none';document.getElementById('cam-err').style.display='flex'"
           style="width:100%;height:100%;object-fit:cover;display:block">
      <div id="cam-err" class="cam-err"><div class="cam-err-t">Camera Offline</div></div>
      <div class="sln"></div><div class="vgn"></div>
      <div class="brk tl"></div><div class="brk tr"></div><div class="brk bl"></div><div class="brk br"></div>
      <div class="otags" id="htags"></div>
      <div class="nind" id="nind">Night Vision</div>
      <div class="ctop">
        <div class="hp hr"><div class="rd"></div>REC</div>
        <div class="hp hf" id="fps0">-- FPS</div>
        <div class="hp hc">CAM-01 · {{ branding.company_name | default('MAIN') }}</div>
        <div class="hp hn" id="nv0">NIGHT</div>
        <div class="hp hfg" id="fhud">FOOTAGE</div>
      </div>
      <div class="cbot">
        <div><div class="cnum" id="pcc">0</div><div class="cnlbl">In Frame</div></div>
        <div class="cts" id="ts0">--:--:--</div>
      </div>
      <div class="cwd" id="cc2">CROWD</div>
      <div class="cld" id="ldc"><div class="clr"></div><div class="clt" id="ldtxt">Connecting</div></div>
    </div>
  </div>
  <div class="right">
    <div class="rph"><div class="rpt">Floor Map</div><div class="rpb">Live</div></div>
    <div class="mwrap">
      <div class="mfloor">
        <div class="ml" style="top:3px;left:4px">Zone A</div>
        <div class="ml" style="bottom:3px;right:4px">Zone B</div>
        <div class="cnw" style="top:8%;left:7%"><div class="cnr"></div><div class="cnn"></div></div>
        <div class="cnw" style="top:8%;right:7%"><div class="cnr" style="animation-delay:.7s"></div><div class="cnn"></div></div>
        <div style="position:absolute;left:50%;top:0;bottom:0;width:1px;background:rgba(196,154,56,.05)"></div>
        <div style="position:absolute;top:50%;left:0;right:0;height:1px;background:rgba(196,154,56,.05)"></div>
        <div id="mdots"></div>
      </div>
    </div>
    <div class="mgrid">
      <div class="mc"><div class="mcl">Uptime</div><div class="mcv mvg" id="sbu">00:00</div></div>
      <div class="mc"><div class="mcl">FPS</div><div class="mcv mvgr" id="sbf">--</div></div>
      <div class="mc"><div class="mcl">DB</div><div class="mcv mvo" id="ftdb">--</div></div>
      <div class="mc"><div class="mcl">Crowd</div><div class="mcv mvg" id="sbc">0</div></div>
    </div>
    <div class="rph" style="padding:4px 10px"><div class="rpt">Threat Score</div></div>
    <div class="garea">
      <svg viewBox="0 0 300 46" preserveAspectRatio="none">
        <defs>
          <linearGradient id="gA" x1="0" y1="0" x2="0" y2="1"><stop offset="0%" stop-color="#a07828" stop-opacity=".13"/><stop offset="100%" stop-color="#a07828" stop-opacity="0"/></linearGradient>
          <linearGradient id="gT" x1="0" y1="0" x2="0" y2="1"><stop offset="0%" stop-color="#b83228" stop-opacity=".11"/><stop offset="100%" stop-color="#b83228" stop-opacity="0"/></linearGradient>
        </defs>
        <line x1="0" y1="15" x2="300" y2="15" stroke="rgba(160,120,40,.07)" stroke-width="1"/>
        <line x1="0" y1="31" x2="300" y2="31" stroke="rgba(160,120,40,.05)" stroke-width="1"/>
        <path id="gPA" fill="url(#gA)" stroke="#a07828" stroke-width="1"/>
        <path id="gPT" fill="url(#gT)" stroke="#b83228" stroke-width="1"/>
      </svg>
    </div>
    <div class="gleg">
      <div class="gl"><div class="gln" style="background:#a07828"></div>Activity</div>
      <div class="gl"><div class="gln" style="background:#b83228"></div>Threat</div>
    </div>
    <div class="rph" style="padding:4px 10px"><div class="rpt">Alert Timeline</div><div class="rpb" id="acnt">0</div></div>
    <div class="alist" id="alist"><div class="ae-txt" id="ae">No alerts yet</div></div>
  </div>
</div>
<div class="foot">
  <div class="fi"><div class="fdot"></div>System Online</div>
  <div class="fi">v8.0</div>
  <div class="fi">Uptime <span id="ftup">00:00:00</span></div>
  <div class="fi">RTX 3050 <span>GPU</span></div>
  <div class="fi">DB <span id="ftdb2">--</span></div>
  <div class="fi" id="crft" style="display:none">Crowd <span id="crcnt">0</span></div>
  <div class="fbtns">
    <button class="fb" onclick="openHistory()">History</button>
    <button class="fb" onclick="location.href='/api/report'">PDF</button>
      <button class="fb" onclick="location.href='/api/footage/download'" title="Download footage video">⬇ Footage</button>
      <button class="fb" id="lang-btn" onclick="toggleLang()" title="Toggle Tamil/English NL">🌐 EN</button>
    <button class="fb fb-g" onclick="location.href='/setup'">Setup</button>
  </div>
</div>
<div style="display:none;position:fixed;inset:0;background:rgba(26,21,8,.6);z-index:999;align-items:center;justify-content:center;backdrop-filter:blur(10px)" id="hm">
  <div style="background:var(--bg2);border:1px solid var(--goldbr);border-radius:12px;width:88vw;max-width:860px;max-height:78vh;display:flex;flex-direction:column">
    <div style="display:flex;align-items:center;padding:12px 16px;border-bottom:1px solid var(--goldbr)">
      <div style="font-size:12px;font-weight:600;color:var(--ink2);flex:1">Alert History</div>
      <button onclick="closeHistory()" style="font-family:'JetBrains Mono',monospace;font-size:6px;letter-spacing:2px;padding:4px 10px;border-radius:20px;border:1px solid var(--goldbr);background:var(--bg1);color:var(--ink4);cursor:pointer">Close</button>
    </div>
    <div style="display:flex;gap:6px;padding:10px 16px;border-bottom:1px solid var(--goldbr);flex-wrap:wrap" id="dbstats"></div>
    <div style="overflow-y:auto;flex:1"><table style="width:100%;border-collapse:collapse"><thead><tr id="hth"></tr></thead><tbody id="hbody"></tbody></table></div>
  </div>
</div>
<script>
const sk=io();let tot=0,crit=0,high=0;const t0=Date.now();
function pad(n){return String(n).padStart(2,'0')}
function tick(){const t=new Date().toLocaleTimeString('en-GB');['hclk','ts0'].forEach(id=>{const e=document.getElementById(id);if(e)e.textContent=t;});}
setInterval(tick,1000);tick();
function uptime(){let s=Math.floor((Date.now()-t0)/1000);const h=Math.floor(s/3600);s%=3600;const m=Math.floor(s/60);s%=60;const u1=document.getElementById('sbu'),u2=document.getElementById('ftup');if(u1)u1.textContent=h?`${pad(h)}:${pad(m)}:${pad(s)}`:`${pad(m)}:${pad(s)}`;if(u2)u2.textContent=`${pad(h||0)}:${pad(m)}:${pad(s)}`;}
setInterval(uptime,1000);
function S(id,v){const e=document.getElementById(id);if(e)e.textContent=v;}
function col(s){return s>=.75?'#b83228':s>=.5?'#b86020':s>=.28?'#a07828':'#186030';}
function tc(l){return{TRUSTED:'tp-trusted',SAFE:'tp-safe',WATCH:'tp-watch',MEDIUM:'tp-medium',HIGH:'tp-high',CRITICAL:'tp-critical',BLACKLIST:'tp-blacklist'}[l]||'tp-safe';}
function cc(c){return{whitelist:'#186030',routine:'#1a4070',blacklist:'#b83228',stranger:'#a07828'}[c]||'#7a6840';}
function setMode(m){
  document.getElementById('blv').className='sbtn'+(m==='live'?' on':'');
  document.getElementById('bft').className='sbtn'+(m==='footage'?' on':'');
  document.getElementById('sinfo').style.display=m==='footage'?'inline':'none';
  document.getElementById('fhud').style.display=m==='footage'?'flex':'none';
  document.getElementById('mbadge').textContent=m==='footage'?'FOOTAGE':'LIVE';
  fetch('/api/set_source?mode='+m).catch(()=>{});
}
sk.on('up',d=>{renderP(d.p||{});updSys(d.s||{});(d.a||[]).forEach(addA);});
function renderP(P){
  const list=document.getElementById('plist'),emp=document.getElementById('pe'),ids=Object.keys(P);
  let thr=0,trusted=0,unk=0;
  ids.forEach(id=>{const p=P[id];if(['HIGH','CRITICAL','BLACKLIST'].includes(p.threat_label))thr++;if(p.category==='whitelist'||p.category==='routine')trusted++;else unk++;});
  S('h-p',ids.length);S('pcc',ids.length);S('pcnt',`${ids.length}`);S('sc-pp',`${trusted} known`);
  const tl=document.getElementById('h-tl'),tp=document.getElementById('sc-tlp');
  if(thr===0){if(tl){tl.textContent='CLEAR';tl.style.color='#186030';}if(tp){tp.textContent='Clear';tp.className='sc-pill sg';}}
  else if(thr===1){if(tl){tl.textContent='MED';tl.style.color='#a07828';}if(tp){tp.textContent='Watch';tp.className='sc-pill so';}}
  else{if(tl){tl.textContent='HIGH';tl.style.color='#b83228';}if(tp){tp.textContent='ALERT';tp.className='sc-pill sr';}}
  if(!ids.length){emp.style.display='flex';list.querySelectorAll('.pc').forEach(c=>c.remove());updMap({});return;}
  emp.style.display='none';list.querySelectorAll('.pc').forEach(c=>{if(!P[c.dataset.tid])c.remove();});
  ids.forEach(id=>{
    const p=P[id],ts=(p.threat_score||0)*100,cl=col(p.threat_score||0),nm=p.name||'STRANGER';
    const dist=p.distance||99,dTxt=dist<99?dist.toFixed(1)+'m':'--';
    const bt=(p.behaviors||[]).map(b=>{const iT=['Concealing','Rushing','Scouting','THEFT'].some(x=>b.includes(x));return`<span class="ptag${iT?' t':''}">${b}</span>`;}).join('');
    let ih='';
    if(p.intent){
      const s2=(p.intent.score||0)*100,bc=s2>=75?'#b83228':s2>=55?'#b86020':s2>=35?'#a07828':'#186030';
      const iL=p.intent.label||'MONITORING';
      ih=`<div class="pint"><div class="pint-box">
        <div class="pint-row"><div class="pik">WHO</div><div class="piv" style="color:${bc}">${p.intent.who||iL}</div></div>
        <div class="pint-row"><div class="pik">WHY</div><div class="piv" style="color:#a07828">${p.intent.why||'—'}</div></div>
        <div class="pint-row"><div class="pik">NXT</div><div class="piv" style="color:#1a4070">${p.intent.next||'—'}</div></div>
        <div class="pib"><div class="pibf" style="width:${s2.toFixed(1)}%;background:${bc}"></div></div>
        <div class="pimeta"><span class="pim">stress <span>${((p.intent.stress||0)*100).toFixed(0)}%</span></span><span class="pim">gaze <span>${p.intent.gaze_scans||0}x</span></span><span class="pim">cam <span>${p.intent.camera_looks||0}x</span></span></div>
      </div></div>`;
    }
    const tr2=(p.theft_risk||0)>0.1?`<div class="pbr"><div class="pbrl">Theft</div><div class="pbrb"><div class="pbrf" style="width:${((p.theft_risk||0)*100).toFixed(1)}%;background:#b83228"></div></div><div class="pbrv" style="color:#b83228">${((p.theft_risk||0)*100).toFixed(0)}%</div></div>`:'';
    const inner=`<div class="pch"><div class="pav">${nm.slice(0,2).toUpperCase()}</div><div style="flex:1;min-width:0"><div class="pnm">${nm}</div><div class="pct-lbl" style="color:${cc(p.category||'stranger')}">${(p.category||'stranger').toUpperCase()}</div></div><div class="ptp ${tc(p.threat_label)}">${p.threat_label||'SAFE'}</div></div>
    <div class="pbr"><div class="pbrl">Threat</div><div class="pbrb"><div class="pbrf" style="width:${ts.toFixed(1)}%;background:${cl}"></div></div><div class="pbrv" style="color:${cl}">${ts.toFixed(0)}%</div></div>
    ${tr2}${bt?`<div class="ptags">${bt}</div>`:''}${ih}`;
    let card=list.querySelector(`[data-tid="${id}"]`);
    if(!card){card=document.createElement('div');card.className='pc';card.dataset.tid=id;list.prepend(card);}
    card.innerHTML=inner;card.style.setProperty('--pcol',cl);
  });
  updMap(P);
}
function updMap(P){
  const dots=document.getElementById('mdots');if(!dots)return;
  const ids=Object.keys(P);if(!ids.length){dots.innerHTML='';return;}
  dots.innerHTML=ids.map(id=>{const p=P[id],s=p.threat_score||0;const cl=s>=.75?'md-c':s>=.45?'md-w':p.category==='whitelist'||p.category==='routine'?'md-s':'md-u';return`<div class="md ${cl}" style="left:${15+Math.random()*70}%;top:${15+Math.random()*70}%"></div>`;}).join('');
}
function addA(a){
  tot++;if(a.label==='CRITICAL'||a.label==='BLACKLIST')crit++;else if(a.label==='HIGH')high++;
  document.getElementById('ae').style.display='none';
  S('h-a',tot);S('acnt',tot);S('sc-ap',`${crit} crit`);
  const dc=a.label==='CRITICAL'||a.label==='BLACKLIST'?'adr':a.label==='HIGH'?'ado':a.label==='MEDIUM'?'adg':'adb';
  const rc=a.label==='CRITICAL'||a.label==='BLACKLIST'?'ar-c':a.label==='HIGH'?'ar-h':a.label==='MEDIUM'?'ar-m':'ar-i';
  const bh=(a.behaviors||[]).slice(0,1).join('');
  const card=document.createElement('div');card.className=`ar ${rc}`;
  card.innerHTML=`<div class="adot ${dc}"></div><div><div class="atxt">${a.label} — ${a.name||'Unknown'}${bh?' · '+bh:''}</div><div class="atm">${a.time} · ${((a.score||0)*100).toFixed(0)}%</div></div>`;
  const al=document.getElementById('alist');al.prepend(card);
  if(al.querySelectorAll('.ar').length>5)al.lastElementChild.remove();
  addG(a.score||0);
}
function updSys(s){
  if(s.fps!==undefined){const f=parseFloat(s.fps).toFixed(1);['h-f','sbf','fps0','fpsbadge'].forEach(x=>{const e=document.getElementById(x);if(e)e.textContent=x==='fps0'||x==='fpsbadge'?f+' FPS':f;});}
  const night=s.night||false;const ni=document.getElementById('nind'),nv=document.getElementById('nv0');
  if(ni)ni.style.display=night?'block':'none';if(nv)nv.style.display=night?'flex':'none';
  const crowd=s.crowd||0;S('sbc',crowd);S('crcnt',crowd);
  const cc2=document.getElementById('cc2'),crf=document.getElementById('crft');
  if(cc2)cc2.style.display=crowd>4?'flex':'none';if(crf)crf.style.display=crowd>0?'flex':'none';
  const plates=s.plates||[],wpns=s.weapons||[],phones=s.phones||[];
  const tags=document.getElementById('htags');
  if(tags)tags.innerHTML=plates.map(p=>`<span class="otag op">PLATE:${p.plate||p}</span>`).join('')+wpns.map(w=>`<span class="otag ow">WPN:${(w.label||w).toUpperCase()}</span>`).join('')+phones.map(()=>`<span class="otag oh">PHONE</span>`).join('');
  S('h-obj',plates.length+wpns.length+phones.length+crowd);
  if(s.ready){const l=document.getElementById('ldc');if(l)l.classList.add('gone');}
  else{const lt=document.getElementById('ldtxt');if(lt)lt.textContent=s.status||'Connecting';}
  if(s.footage_mode)setMode('footage');
}
const tD=Array(30).fill(0),aD=Array(30).fill(0);
function mkP(d){const W=300,H=44,step=W/(d.length-1);let p='M';d.forEach((v,i)=>{const x=i*step,y=H-v*H;p+=(i?'L':'')+x.toFixed(1)+' '+y.toFixed(1)+' ';});const lx=(d.length-1)*step;p+=`L${lx} ${H} L0 ${H} Z`;return p;}
function addG(score){tD.shift();tD.push(score);aD.shift();aD.push(Math.min(score*.55+Math.random()*.1,1));document.getElementById('gPT').setAttribute('d',mkP(tD));document.getElementById('gPA').setAttribute('d',mkP(aD));}
setInterval(()=>{addG(tD[tD.length-1]*.94||0);},2000);
function openHistory(){
  const m=document.getElementById('hm');m.style.display='flex';
  fetch('/api/db/stats').then(r=>r.json()).then(s=>{
    S('ftdb',s.total_alerts||0);S('ftdb2',s.total_alerts||0);S('h-db',s.total_alerts||0);
    document.getElementById('dbstats').innerHTML=[['Total',s.total_alerts||0,'#a07828'],['Critical',s.critical||0,'#b83228'],['High',s.high||0,'#b86020'],['Today',s.today_alerts||0,'#186030']].map(([l,v,c])=>`<div style="background:var(--bg1);border:1px solid var(--goldbr);border-radius:6px;padding:6px 10px"><div style="font-size:16px;font-weight:700;color:${c}">${v}</div><div style="font-family:'JetBrains Mono',monospace;font-size:5px;letter-spacing:2px;color:var(--ink5);text-transform:uppercase;margin-top:1px">${l}</div></div>`).join('');
  }).catch(()=>{});
  fetch('/api/db/alerts?limit=100').then(r=>r.json()).then(rows=>{
    const th=['Time','Label','Person','Score','Emotion','Behaviors','Cam'];
    document.getElementById('hth').innerHTML=th.map(h=>`<th style="padding:6px 10px;font-family:'JetBrains Mono',monospace;font-size:5.5px;letter-spacing:2px;text-transform:uppercase;color:var(--ink5);text-align:left;border-bottom:1px solid var(--goldbr);background:var(--bg1)">${h}</th>`).join('');
    const lc={CRITICAL:'#b83228',HIGH:'#b86020',MEDIUM:'#a07828',BLACKLIST:'#b83228'};
    document.getElementById('hbody').innerHTML=rows.map(a=>`<tr>${[a.time||'—',a.label||'—',a.name||'—',a.score?Math.round(a.score*100)+'%':'—',a.emotion||'—',a.behaviors||'—','CAM-0'+((a.cam||0)+1)].map((v,i)=>`<td style="padding:6px 10px;font-family:'JetBrains Mono',monospace;font-size:6.5px;color:${i===1?lc[a.label]||'var(--ink4)':'var(--ink4)'};border-bottom:1px solid var(--goldbr);${i===1?'font-weight:600':''}${i===5?'max-width:140px;overflow:hidden;text-overflow:ellipsis':''}">${v}</td>`).join('')}</tr>`).join('');
    if(!rows.length)document.getElementById('hbody').innerHTML=`<tr><td colspan="7" style="padding:20px;text-align:center;color:var(--ink5);font-family:'JetBrains Mono',monospace;font-size:6px;letter-spacing:3px">NO RECORDS</td></tr>`;
  }).catch(()=>{});
}
function closeHistory(){document.getElementById('hm').style.display='none';}
fetch('/api/db/stats').then(r=>r.json()).then(s=>{S('ftdb',s.total_alerts||0);S('ftdb2',s.total_alerts||0);S('h-db',s.total_alerts||0);}).catch(()=>{});
let _lang='english';
function toggleLang(){
  _lang=_lang==='english'?'tamil':'english';
  const btn=document.getElementById('lang-btn');
  if(btn)btn.textContent=_lang==='tamil'?'🌐 தமிழ்':'🌐 EN';
  fetch('/api/nl/language',{method:'POST',headers:{'Content-Type':'application/json'},
    body:JSON.stringify({language:_lang})}).then(r=>r.json()).then(d=>{
    if(d.success)console.log('NL language:',_lang);
  }).catch(()=>{});
}
</script>
</body>
</html>
"""

# ── ENTRY ─────────────────────────────────────────────────
if __name__ == '__main__':
    print("\n" + "="*52)
    print("  ProVisionGuard AI — Enterprise v8.0")
    print("="*52)
    print(f"  License : {_LICENSE.get('plan','TRIAL')} ({_DAYS_LEFT}d left)")
    print(f"  Customer: {_LICENSE.get('customer','Trial User')}")
    print(f"  Demo    : {'ON' if DEMO_MODE else 'OFF'}")
    print("  Dashboard: http://localhost:5000")
    print("  Setup    : http://localhost:5000/setup")
    print("  Login    : admin / pvg@admin123")
    print("  Report   : http://localhost:5000/api/report")
    print()
    print("  Tips:")
    print("  --demo flag = run on sample video")
    print("  /setup page = branding + license")
    print("="*52 + "\n")

    # AI loads in background — Flask starts immediately
    threading.Thread(target=run_ai, daemon=True).start()

    # Flask starts right away — no waiting
    sio.run(app, host='0.0.0.0', port=5000,
            debug=False, use_reloader=False,
            allow_unsafe_werkzeug=True)