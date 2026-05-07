"""
ProVisionGuard AI - Full Pipeline
Face Recognition + Emotion + Intent + Depth + Alerts
"""

import cv2
import numpy as np
import time
import threading
import os
from datetime import datetime
from collections import deque
from ultralytics import YOLO
from insightface.app import FaceAnalysis
from hsemotion_onnx.facial_emotions import HSEmotionRecognizer
import pyttsx3

# ══════════════════════════════════════════════════
#  CONFIG
# ══════════════════════════════════════════════════
FOCAL_LENGTH    = 414.12   # Your calibrated value (400-500 range)
KNOWN_HEIGHT    = 170.0   # cm average person
SAFE_DIST       = 2.0     # meters
CRITICAL_DIST   = 1.0     # meters
YOUR_NAME       = "Sheik Abdullah"  # whitelist folder name

FACE_DB_PATH    = "data/known_faces"
SNAPSHOT_DIR    = "data/snapshots"
os.makedirs(SNAPSHOT_DIR, exist_ok=True)

# Threat thresholds
THREAT_WATCH    = 0.30
THREAT_MEDIUM   = 0.50
THREAT_HIGH     = 0.70
THREAT_CRITICAL = 0.85

# Cooldowns
ALERT_COOLDOWN  = 20   # seconds between alerts
FACE_EVERY_N    = 5    # analyze face every N frames
EMOTION_EVERY_N = 8    # analyze emotion every N frames
# ══════════════════════════════════════════════════

print("=" * 55)
print("  ProVisionGuard AI — Full Pipeline")
print("=" * 55)
print("🔄 Loading models... please wait...")

# ── Load Models ───────────────────────────────────
yolo_det  = YOLO('yolo11n.pt')
yolo_pose = YOLO('yolo11n-pose.pt')

face_app  = FaceAnalysis(name='buffalo_l')
face_app.prepare(ctx_id=0, det_size=(640, 640))

emo_model = HSEmotionRecognizer(
    model_name='enet_b0_8_best_afew'
)

# TTS
tts_lock   = threading.Lock()
tts_engine = pyttsx3.init()
tts_engine.setProperty('rate', 155)
tts_engine.setProperty('volume', 1.0)

print("✅ All models loaded!")

# ──────────────────────────────────────────────────
#  Face Database
# ──────────────────────────────────────────────────
known_faces = {}

def load_face_db():
    print("🔄 Loading face database...")
    for cat in ['whitelist', 'routine', 'blacklist']:
        cat_dir = os.path.join(FACE_DB_PATH, cat)
        if not os.path.exists(cat_dir):
            continue
        for person in os.listdir(cat_dir):
            p_dir = os.path.join(cat_dir, person)
            if not os.path.isdir(p_dir):
                continue
            embs = []
            for f in os.listdir(p_dir):
                if not f.lower().endswith(
                    ('.jpg', '.jpeg', '.png')
                ):
                    continue
                img = cv2.imread(os.path.join(p_dir, f))
                if img is None:
                    continue
                faces = face_app.get(img)
                if faces:
                    embs.append(faces[0].embedding)
            if embs:
                known_faces[person] = {
                    'emb': np.mean(embs, axis=0),
                    'category': cat
                }
                print(f"  ✅ {person} [{cat}]")
    print(f"✅ {len(known_faces)} persons in database!")

load_face_db()

# ──────────────────────────────────────────────────
#  Person State Class
# ──────────────────────────────────────────────────
class PersonState:
    def __init__(self, tid):
        self.tid             = tid
        self.first_seen      = time.time()

        # Identity
        self.name            = None
        self.category        = "stranger"
        self.face_conf       = 0.0

        # Scores (0.0 - 1.0)
        self.emotion         = "Neutral"
        self.emotion_threat  = 0.0
        self.gaze_score      = 0.0
        self.stress_score    = 0.0
        self.motion_score    = 0.0
        self.loiter_score    = 0.0
        self.intent_score    = 0.0
        self.distance        = 99.0
        self.proximity_score = 0.0
        self.threat_score    = 0.0

        # History
        self.wrist_y_hist    = deque(maxlen=30)
        self.head_x_hist     = deque(maxlen=20)
        self.dist_hist       = deque(maxlen=8)
        self.looking_count   = 0
        self.sudden_moves    = 0

        # Alerts
        self.last_alert_time = 0
        self.snapshot_taken  = False

states     = {}
frame_count = 0

# ──────────────────────────────────────────────────
#  Helper Functions
# ──────────────────────────────────────────────────
def cosine_sim(a, b):
    n = np.linalg.norm(a) * np.linalg.norm(b)
    return float(np.dot(a, b) / (n + 1e-6))

def smooth(new_v, old_v, alpha=0.3):
    return alpha * new_v + (1.0 - alpha) * old_v

def get_kp(kps, idx):
    k = kps[idx]
    return float(k[0]), float(k[1]), float(k[2])

def get_distance_m(px_height):
    if px_height <= 0:
        return 99.0
    dist_cm = (KNOWN_HEIGHT * FOCAL_LENGTH) / px_height
    return dist_cm / 100.0

def crop_bbox(frame, x1, y1, x2, y2):
    H, W = frame.shape[:2]
    x1 = max(0, x1); y1 = max(0, y1)
    x2 = min(W, x2); y2 = min(H, y2)
    if x2 <= x1 or y2 <= y1:
        return None
    return frame[y1:y2, x1:x2]

# ──────────────────────────────────────────────────
#  Analysis Modules
# ──────────────────────────────────────────────────
def run_face_recognition(frame, x1, y1, x2, y2):
    """Identify person from face."""
    crop = crop_bbox(frame, x1, y1, x2, y2)
    if crop is None:
        return None, "stranger", 0.0

    faces = face_app.get(crop)
    if not faces:
        return None, "stranger", 0.0

    emb        = faces[0].embedding
    best_name  = None
    best_cat   = "stranger"
    best_score = 0.0

    for name, data in known_faces.items():
        sim = cosine_sim(emb, data['emb'])
        if sim > best_score:
            best_score = sim
            best_name  = name
            best_cat   = data['category']

    if best_score >= 0.55:
        return best_name, best_cat, best_score
    return None, "stranger", best_score


def run_emotion(frame, x1, y1, x2, y2):
    """Detect emotion from face crop."""
    crop = crop_bbox(frame, x1, y1, x2, y2)
    if crop is None:
        return "Neutral", 0.0

    try:
        rgb = cv2.cvtColor(crop, cv2.COLOR_BGR2RGB)
        emo, scores = emo_model.predict_emotions(
            rgb, logits=False
        )
        labels = [
            'Anger','Contempt','Disgust',
            'Fear','Happiness','Neutral',
            'Sadness','Surprise'
        ]
        sd = dict(zip(labels, scores))
        weights = {
            'Anger': 0.95, 'Disgust': 0.70,
            'Fear': 0.65,  'Contempt': 0.60,
            'Surprise': 0.35,'Sadness': 0.20,
            'Neutral': 0.05,'Happiness': 0.0
        }
        emo_threat = min(
            sum(sd.get(e,0)*w
                for e,w in weights.items()),
            1.0
        )
        return emo, float(emo_threat)
    except:
        return "Neutral", 0.0


def run_intent(kps, state, W, H):
    """Analyze gaze, stress, motion from pose."""

    # ── Keypoints ─────────────────────────────────
    nx, ny, nc   = get_kp(kps, 0)   # nose
    lsx,lsy,lsc  = get_kp(kps, 5)   # left shoulder
    rsx,rsy,rsc  = get_kp(kps, 6)   # right shoulder
    lwx,lwy,lwc  = get_kp(kps, 9)   # left wrist
    rwx,rwy,rwc  = get_kp(kps, 10)  # right wrist
    lhx,lhy,lhc  = get_kp(kps, 11)  # left hip
    rhx,rhy,rhc  = get_kp(kps, 12)  # right hip
    lex_,ley_,lec = get_kp(kps, 3)  # left ear
    rex_,rey_,rec = get_kp(kps, 4)  # right ear

    # ── GAZE: shifty eyes detection ───────────────
    gaze = state.gaze_score
    if nc > 0.3:
        state.head_x_hist.append(nx / (W + 1e-6))
        if len(state.head_x_hist) >= 10:
            variance = float(np.std(
                list(state.head_x_hist)[-10:]
            ))
            if variance > 0.022:
                state.looking_count = min(
                    state.looking_count + 1, 30
                )
            else:
                state.looking_count = max(
                    state.looking_count - 1, 0
                )

        # Head turned to side
        if lec > 0.2 and rec > 0.2:
            l_d = abs(nx - lex_)
            r_d = abs(nx - rex_)
            ratio = min(l_d, r_d) / (
                max(l_d, r_d) + 1e-6
            )
            side_look = ratio < 0.35
        else:
            side_look = False

        gaze = min(
            state.looking_count / 20.0 +
            (0.25 if side_look else 0.0),
            1.0
        )

    # ── STRESS: shoulder tension, self-touch ──────
    stress = 0.0
    if lsc > 0.3 and rsc > 0.3:
        sh_y  = (lsy + rsy) / 2
        sh_w  = abs(lsx - rsx) / (W + 1e-6)

        # Raised shoulders (tension)
        if sh_y / (H + 1e-6) < 0.28:
            stress += 0.25

        # Hunched (narrow shoulders)
        if sh_w < 0.12:
            stress += 0.20

    # Self-touching (hands near face)
    if nc > 0.3:
        for wx, wy, wc in [
            (lwx,lwy,lwc), (rwx,rwy,rwc)
        ]:
            if wc > 0.3:
                d = np.sqrt(
                    (wx-nx)**2 + (wy-ny)**2
                ) / (H + 1e-6)
                if d < 0.12:
                    stress += 0.25

    # Hiding hands (below hips)
    if lwc > 0.3 and lhc > 0.3:
        if lwy > lhy + 0.05 * H:
            stress += 0.15

    stress = min(stress, 1.0)

    # ── MOTION: sudden moves, restlessness ────────
    wrist_y = (lwy+rwy)/2 if (
        lwc > 0.3 and rwc > 0.3
    ) else ny
    state.wrist_y_hist.append(wrist_y)
    motion = 0.0

    if len(state.wrist_y_hist) >= 5:
        recent   = list(state.wrist_y_hist)
        velocity = abs(recent[-1] - recent[-4])
        variance = float(np.std(recent[-10:])
                         if len(recent) >= 10 else 0)

        if velocity > 18:
            state.sudden_moves = min(
                state.sudden_moves + 2, 20
            )
        else:
            state.sudden_moves = max(
                state.sudden_moves - 1, 0
            )

        motion = min(
            (velocity / 40.0) * 0.4 +
            (variance / 30.0) * 0.3 +
            (state.sudden_moves / 20.0) * 0.3,
            1.0
        )

    # ── LOITER: time spent in frame ───────────────
    loiter = min(
        (time.time() - state.first_seen) / 60.0,
        1.0
    )

    return (
        smooth(gaze,   state.gaze_score,   0.3),
        smooth(stress, state.stress_score, 0.3),
        smooth(motion, state.motion_score, 0.3),
        loiter
    )


def compute_threat(state):
    """
    Final weighted threat score.
    Category modifier applied.
    """
    # Base weights
    W_EMOTION  = 0.30
    W_INTENT   = 0.25
    W_GAZE     = 0.15
    W_STRESS   = 0.15
    W_MOTION   = 0.10
    W_LOITER   = 0.05

    raw = (
        state.emotion_threat  * W_EMOTION  +
        state.intent_score    * W_INTENT   +
        state.gaze_score      * W_GAZE     +
        state.stress_score    * W_STRESS   +
        state.motion_score    * W_MOTION   +
        state.loiter_score    * W_LOITER
    )

    # Category modifier
    modifiers = {
        'whitelist':  0.15,  # Family = very low threat
        'routine':    0.65,  # Staff  = medium baseline
        'blacklist':  1.50,  # Known bad = amplify
        'stranger':   1.00,  # Unknown   = normal
    }
    mod = modifiers.get(state.category, 1.0)

    # Proximity boost
    if state.distance < CRITICAL_DIST:
        raw += 0.20
    elif state.distance < SAFE_DIST:
        raw += 0.10

    return float(min(raw * mod, 1.0))


def get_threat_info(score, category):
    """Return label, color, description."""
    if category == 'whitelist':
        return "TRUSTED",   (0, 255, 100),  "Family/Known Person"

    if score >= THREAT_CRITICAL:
        return "CRITICAL",  (0, 0, 255),    "IMMEDIATE THREAT!"
    elif score >= THREAT_HIGH:
        return "HIGH",      (0, 60, 255),   "HIGH RISK - ALERT!"
    elif score >= THREAT_MEDIUM:
        return "MEDIUM",    (0, 165, 255),  "Suspicious Behavior"
    elif score >= THREAT_WATCH:
        return "WATCH",     (0, 220, 200),  "Monitoring..."
    else:
        return "SAFE",      (0, 255, 0),    "Normal Behavior"

# ──────────────────────────────────────────────────
#  Alert System
# ──────────────────────────────────────────────────
alert_log  = []

def speak(text):
    """Non-blocking TTS."""
    def _speak():
        with tts_lock:
            try:
                tts_engine.say(text)
                tts_engine.runAndWait()
            except:
                pass
    threading.Thread(target=_speak,
                     daemon=True).start()

def save_snapshot(frame, state, threat_label):
    """Save annotated snapshot."""
    ts   = datetime.now().strftime("%Y%m%d_%H%M%S")
    name = state.name or f"ID{state.tid}"
    path = os.path.join(
        SNAPSHOT_DIR,
        f"{threat_label}_{name}_{ts}.jpg"
    )
    cv2.imwrite(path, frame)
    print(f"📸 Snapshot: {path}")
    return path

def try_send_telegram(message, img_path=None):
    """Telegram alert (configure bot token)."""
    # Configure these:
    BOT_TOKEN = os.environ.get("TG_BOT_TOKEN", "")
    CHAT_ID   = os.environ.get("TG_CHAT_ID",   "")

    if not BOT_TOKEN or not CHAT_ID:
        return  # Not configured

    try:
        import requests
        if img_path and os.path.exists(img_path):
            with open(img_path, 'rb') as f:
                requests.post(
                    f"https://api.telegram.org/"
                    f"bot{BOT_TOKEN}/sendPhoto",
                    data={
                        'chat_id': CHAT_ID,
                        'caption': message
                    },
                    files={'photo': f},
                    timeout=5
                )
        else:
            requests.post(
                f"https://api.telegram.org/"
                f"bot{BOT_TOKEN}/sendMessage",
                data={
                    'chat_id': CHAT_ID,
                    'text': message
                },
                timeout=5
            )
    except:
        pass

def trigger_alert(frame, state, threat_label, desc):
    """Full alert: voice + snapshot + telegram + log."""
    now = time.time()
    if now - state.last_alert_time < ALERT_COOLDOWN:
        return

    state.last_alert_time = now
    name = state.name or f"Unknown (ID:{state.tid})"

    # Log
    ts  = datetime.now().strftime("%H:%M:%S")
    log = {
        'time':   ts,
        'id':     state.tid,
        'name':   name,
        'threat': threat_label,
        'score':  f"{state.threat_score*100:.0f}%",
        'emotion':state.emotion,
        'dist':   f"{state.distance:.1f}m"
    }
    alert_log.append(log)
    if len(alert_log) > 20:
        alert_log.pop(0)

    print(f"\n🚨 ALERT [{ts}] | {threat_label} | "
          f"{name} | Score:{state.threat_score*100:.0f}%")

    # Snapshot
    snap = save_snapshot(frame, state, threat_label)

    # Voice alerts
    voice_map = {
        "CRITICAL": (
            "CRITICAL THREAT DETECTED! "
            "Security alert activated! "
            "Do not approach!"
        ),
        "HIGH": (
            "Warning! High risk individual detected. "
            "Security has been notified."
        ),
        "MEDIUM": (
            "Caution! Suspicious behavior detected. "
            "Please identify yourself."
        ),
        "WATCH": (
            "Hello, this area is under surveillance."
        )
    }
    voice_msg = voice_map.get(threat_label, "")
    if voice_msg:
        speak(voice_msg)

    # Telegram
    tg_msg = (
        f"🚨 ProVisionGuard Alert!\n"
        f"Level   : {threat_label}\n"
        f"Person  : {name}\n"
        f"Score   : {state.threat_score*100:.0f}%\n"
        f"Emotion : {state.emotion}\n"
        f"Distance: {state.distance:.1f}m\n"
        f"Time    : {ts}"
    )
    threading.Thread(
        target=try_send_telegram,
        args=(tg_msg, snap),
        daemon=True
    ).start()

# ──────────────────────────────────────────────────
#  Draw Functions
# ──────────────────────────────────────────────────
def draw_person_panel(frame, state, x1, y1, x2, y2,
                      fcount):
    """Draw full info panel for each person."""
    threat_label, t_col, t_desc = get_threat_info(
        state.threat_score, state.category
    )

    # ── Bounding box ──────────────────────────────
    cv2.rectangle(frame, (x1,y1), (x2,y2),
                  t_col, 2)

    # ── Header bar ────────────────────────────────
    name_str = state.name or "STRANGER"
    hdr = (f"ID:{state.tid}  {name_str}  "
           f"[{threat_label}]")
    hdr_w = max(len(hdr)*10, x2-x1)
    cv2.rectangle(frame,
                  (x1, y1-42), (x1+hdr_w, y1),
                  t_col, -1)
    cv2.putText(frame, hdr,
                (x1+4, y1-22),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.56, (255,255,255), 2)
    cv2.putText(frame, t_desc,
                (x1+4, y1-6),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.38, (220,220,220), 1)

    # ── Score bars below box ──────────────────────
    bar_x1 = x1
    bar_x2 = x2
    bar_w  = bar_x2 - bar_x1
    base_y = y2 + 6

    bars = [
        ("EMO",    state.emotion_threat,  (0,100,255)),
        ("GAZE",   state.gaze_score,      (0,180,255)),
        ("STRESS", state.stress_score,    (0,140,255)),
        ("MOTION", state.motion_score,    (0,165,255)),
        ("INTENT", state.intent_score,    (150,0,255)),
        ("THREAT", state.threat_score,    t_col),
    ]

    for i, (lbl, val, col) in enumerate(bars):
        y = base_y + i * 15

        # Label
        cv2.putText(frame, lbl,
                    (bar_x1, y+10),
                    cv2.FONT_HERSHEY_SIMPLEX,
                    0.36, (170,170,170), 1)

        # Bar bg
        cv2.rectangle(frame,
                      (bar_x1+50, y),
                      (bar_x2, y+11),
                      (30,30,30), -1)

        # Bar fill
        fill = int(val * (bar_w - 50))
        if fill > 0:
            cv2.rectangle(frame,
                          (bar_x1+50, y),
                          (bar_x1+50+fill, y+11),
                          col, -1)

        # Percent
        cv2.putText(frame,
                    f"{val*100:.0f}%",
                    (bar_x2-35, y+10),
                    cv2.FONT_HERSHEY_SIMPLEX,
                    0.35, (255,255,255), 1)

    # ── Distance display ──────────────────────────
    dist_y = base_y + len(bars)*15 + 12
    if state.distance < CRITICAL_DIST:
        d_col = (0, 0, 255)
        d_txt = f"⚠ {state.distance:.1f}m CRITICAL"
    elif state.distance < SAFE_DIST:
        d_col = (0, 165, 255)
        d_txt = f"! {state.distance:.1f}m CLOSE"
    else:
        d_col = (0, 255, 0)
        d_txt = f"✓ {state.distance:.1f}m SAFE"

    cv2.putText(frame, d_txt,
                (x1, dist_y),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.5, d_col, 2)

    # ── Emotion label ─────────────────────────────
    cv2.putText(frame,
                f"Emotion: {state.emotion}",
                (x1, dist_y+18),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.42, (200,200,200), 1)

    # ── Critical flash ────────────────────────────
    if (state.threat_score >= THREAT_CRITICAL
            and fcount % 15 < 8):
        cv2.rectangle(frame,
                      (x1-4, y1-46),
                      (x2+4, y2+4),
                      (0,0,255), 4)


def draw_alert_log(frame, W, H):
    """Draw recent alert log on right side."""
    if not alert_log:
        return

    log_x = W - 310
    log_y = 50
    panel_h = len(alert_log[-6:]) * 55 + 30

    cv2.rectangle(frame,
                  (log_x-5, log_y-20),
                  (W-5, log_y + panel_h),
                  (15,15,15), -1)
    cv2.putText(frame, "ALERT LOG",
                (log_x, log_y-5),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.5, (255,215,0), 1)

    for i, log in enumerate(alert_log[-6:]):
        y = log_y + 15 + i*50
        col_map = {
            "CRITICAL": (0,0,255),
            "HIGH":     (0,60,255),
            "MEDIUM":   (0,165,255),
            "WATCH":    (0,220,200)
        }
        col = col_map.get(log['threat'],
                          (150,150,150))

        cv2.rectangle(frame,
                      (log_x, y),
                      (W-10, y+42),
                      (25,25,25), -1)
        cv2.rectangle(frame,
                      (log_x, y),
                      (log_x+4, y+42),
                      col, -1)

        cv2.putText(frame,
                    f"{log['time']}  "
                    f"[{log['threat']}]",
                    (log_x+8, y+14),
                    cv2.FONT_HERSHEY_SIMPLEX,
                    0.45, col, 1)
        cv2.putText(frame,
                    f"{log['name']}  "
                    f"Score:{log['score']}",
                    (log_x+8, y+28),
                    cv2.FONT_HERSHEY_SIMPLEX,
                    0.4, (200,200,200), 1)
        cv2.putText(frame,
                    f"Emo:{log['emotion']}  "
                    f"Dist:{log['dist']}",
                    (log_x+8, y+40),
                    cv2.FONT_HERSHEY_SIMPLEX,
                    0.35, (150,150,150), 1)


def draw_hud(frame, persons, W, H, fps):
    """Top HUD bar."""
    cv2.rectangle(frame, (0,0), (W,42),
                  (12,12,12), -1)
    cv2.line(frame, (0,42), (W,42),
             (40,40,40), 1)

    cv2.putText(frame,
                "ProVisionGuard AI",
                (10, 28),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.85, (255,215,0), 2)

    status_x = 260
    cv2.putText(frame,
                f"Persons:{len(persons)}  "
                f"FPS:{fps:.0f}  "
                f"Alerts:{len(alert_log)}",
                (status_x, 27),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.52, (180,180,180), 1)

    ts = datetime.now().strftime("%H:%M:%S")
    cv2.putText(frame, ts,
                (W-90, 27),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.52, (120,120,120), 1)

# ──────────────────────────────────────────────────
#  Main Loop
# ──────────────────────────────────────────────────
cap     = cv2.VideoCapture(0)
W_CAP   = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
H_CAP   = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))

fps_times  = deque(maxlen=30)
fps_display = 0.0

print("\n✅ ProVisionGuard AI Started!")
print("   Press Q to quit")
print("   Press R to reset all states")
print("   Press S to save snapshot manually")
print("=" * 55)

while True:
    ret, frame = cap.read()
    if not ret:
        break

    t_start      = time.time()
    frame_count += 1
    H_F, W_F     = frame.shape[:2]
    active_ids   = []

    # ── Run YOLO detection ────────────────────────
    det_results = yolo_det.track(
        frame,
        persist=True,
        classes=[0],
        verbose=False,
        conf=0.45
    )

    # ── Run YOLO pose ─────────────────────────────
    pose_results = yolo_pose.track(
        frame,
        persist=True,
        verbose=False,
        conf=0.45
    )

    # ── Build person list from detection ──────────
    det_persons = []
    if (det_results and
            det_results[0].boxes is not None):
        boxes = det_results[0].boxes
        for i, box in enumerate(boxes):
            x1,y1,x2,y2 = [
                int(v) for v in
                box.xyxy[0].cpu().numpy()
            ]
            tid = int(box.id[0]) \
                if box.id is not None else i
            det_persons.append({
                'tid': tid,
                'bbox': (x1,y1,x2,y2)
            })

    # ── Get pose keypoints ────────────────────────
    pose_kps = {}
    if (pose_results and
            pose_results[0].keypoints is not None
            and pose_results[0].boxes is not None):
        pkps   = pose_results[0].keypoints.data
        pboxes = pose_results[0].boxes
        for i, kps in enumerate(pkps):
            pid = int(pboxes.id[i]) \
                if pboxes.id is not None else i
            pose_kps[pid] = kps

    # ── Process each person ───────────────────────
    for p in det_persons:
        tid       = p['tid']
        x1,y1,x2,y2 = p['bbox']
        active_ids.append(tid)

        # Init state
        if tid not in states:
            states[tid] = PersonState(tid)
        s = states[tid]

        # ── Distance ──────────────────────────────
        px_h        = y2 - y1
        raw_dist    = get_distance_m(px_h)
        s.dist_hist.append(raw_dist)
        s.distance  = float(np.median(s.dist_hist))

        # ── Face Recognition (every N frames) ─────
        if frame_count % FACE_EVERY_N == 0:
            name, cat, conf = run_face_recognition(
                frame, x1, y1, x2, y2
            )
            if conf > s.face_conf or name:
                s.name       = name
                s.category   = cat
                s.face_conf  = conf

        # ── Emotion (every N frames) ───────────────
        if frame_count % EMOTION_EVERY_N == 0:
            emo, emo_thr = run_emotion(
                frame, x1, y1, x2, y2
            )
            s.emotion        = emo
            s.emotion_threat = smooth(
                emo_thr, s.emotion_threat, 0.4
            )

        # ── Intent (from pose) ────────────────────
        if tid in pose_kps:
            g, st, mo, lo = run_intent(
                pose_kps[tid], s, W_F, H_F
            )
            s.gaze_score   = g
            s.stress_score = st
            s.motion_score = mo
            s.loiter_score = lo
            s.intent_score = smooth(
                (g+st+mo)/3.0,
                s.intent_score, 0.3
            )

        # ── Final Threat Score ────────────────────
        s.threat_score = smooth(
            compute_threat(s),
            s.threat_score,
            0.25
        )

        # ── Alert Trigger ─────────────────────────
        thr_label, _, _ = get_threat_info(
            s.threat_score, s.category
        )
        if (thr_label in
                ["CRITICAL","HIGH","MEDIUM"]
                and s.category != 'whitelist'):
            trigger_alert(
                frame, s, thr_label, ""
            )

        # ── Draw panel ────────────────────────────
        draw_person_panel(
            frame, s, x1, y1, x2, y2,
            frame_count
        )

    # ── Cleanup old states ────────────────────────
    for tid in list(states.keys()):
        if tid not in active_ids:
            del states[tid]

    # ── Alert log panel ───────────────────────────
    draw_alert_log(frame, W_F, H_F)

    # ── FPS ───────────────────────────────────────
    fps_times.append(time.time() - t_start)
    if len(fps_times) == 30:
        fps_display = 1.0 / (
            np.mean(fps_times) + 1e-6
        )

    # ── HUD ───────────────────────────────────────
    draw_hud(frame, det_persons,
             W_F, H_F, fps_display)

    cv2.imshow("ProVisionGuard AI", frame)

    # ── Keys ──────────────────────────────────────
    key = cv2.waitKey(1) & 0xFF
    if key == ord('q'):
        break
    elif key == ord('r'):
        states.clear()
        alert_log.clear()
        print("🔄 Reset!")
    elif key == ord('s'):
        ts  = datetime.now().strftime(
            "%Y%m%d_%H%M%S"
        )
        path = os.path.join(
            SNAPSHOT_DIR, f"manual_{ts}.jpg"
        )
        cv2.imwrite(path, frame)
        print(f"📸 Manual snapshot: {path}")

cap.release()
cv2.destroyAllWindows()
print("\n✅ ProVisionGuard AI Shutdown.")
print(f"   Total Alerts : {len(alert_log)}")
print(f"   Snapshots in : {SNAPSHOT_DIR}/")