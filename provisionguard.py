"""
ProVisionGuard AI — Professional Intent Detection
================================================
Detects: Robbery, Shop theft, Intrusion, ATM threats
Behaviors: Nervous walk, Loitering, Hiding face,
           Repeated looking, Sudden moves, Following
================================================
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
#  CONFIGURATION
# ══════════════════════════════════════════════════
CFG = {
    # Camera
    'focal_length'     : 450.0,   # Your calibrated FL
    'known_height_cm'  : 170.0,   # Average person height
    'safe_dist_m'      : 2.5,
    'critical_dist_m'  : 1.2,

    # Face DB
    'face_db_path'     : 'data/known_faces',
    'face_threshold'   : 0.55,

    # Behavior timewindow
    'buffer_seconds'   : 30,      # track 30s of behavior
    'fps_assumed'      : 15,      # analysis fps

    # Thresholds
    'loiter_seconds'   : 25,      # suspicious loiter
    'look_count_limit' : 12,      # repeated looks
    'follow_dist_px'   : 120,     # following distance

    # Threat levels
    'watch_threshold'  : 0.28,
    'medium_threshold' : 0.48,
    'high_threshold'   : 0.68,
    'critical_threshold': 0.85,

    # Alerts
    'alert_cooldown'   : 18,      # seconds
    'snapshot_dir'     : 'data/snapshots',

    # Analysis frequency
    'face_every_n'     : 6,
    'emotion_every_n'  : 8,
}

os.makedirs(CFG['snapshot_dir'], exist_ok=True)

# ══════════════════════════════════════════════════
#  MODEL LOADING
# ══════════════════════════════════════════════════
print("=" * 60)
print("  ProVisionGuard AI — Loading...")
print("=" * 60)

yolo_det  = YOLO('yolo11n.pt')
yolo_pose = YOLO('yolo11n-pose.pt')

face_app  = FaceAnalysis(name='buffalo_l')
face_app.prepare(ctx_id=0, det_size=(640, 640))

emo_model = HSEmotionRecognizer(
    model_name='enet_b0_8_best_afew'
)

tts_lock   = threading.Lock()
tts_engine = pyttsx3.init()
tts_engine.setProperty('rate', 148)
tts_engine.setProperty('volume', 1.0)

print("✅ All models ready!")

# ══════════════════════════════════════════════════
#  FACE DATABASE
# ══════════════════════════════════════════════════
known_faces = {}

def load_face_db():
    print("🔄 Loading face database...")
    db_path = CFG['face_db_path']
    for cat in ['whitelist', 'routine', 'blacklist']:
        cat_dir = os.path.join(db_path, cat)
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
                img = cv2.imread(
                    os.path.join(p_dir, f)
                )
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
    print(f"✅ {len(known_faces)} persons loaded!\n")

load_face_db()

# ══════════════════════════════════════════════════
#  BEHAVIOR SIGNALS
# Each signal is a small class that tracks
#  one specific suspicious behavior over time.
# ══════════════════════════════════════════════════

class Signal_NervousWalk:
    """
    Detects hesitation walking:
    person moves slowly, stops, starts again
    unlike normal confident walking.
    """
    def __init__(self):
        self.pos_history   = deque(maxlen=45)
        self.speed_history = deque(maxlen=20)
        self.score         = 0.0

    def update(self, center_x, center_y):
        self.pos_history.append(
            (center_x, center_y, time.time())
        )
        if len(self.pos_history) < 6:
            return

        positions = list(self.pos_history)
        speeds    = []
        for i in range(1, len(positions)):
            dx = positions[i][0] - positions[i-1][0]
            dy = positions[i][1] - positions[i-1][1]
            dt = positions[i][2] - positions[i-1][2]
            if dt > 0:
                speed = np.sqrt(dx*dx + dy*dy) / dt
                speeds.append(speed)

        if len(speeds) < 4:
            return

        self.speed_history.extend(speeds[-4:])

        if len(self.speed_history) < 8:
            return

        sp   = list(self.speed_history)
        mean = np.mean(sp)
        std  = np.std(sp)

        # Nervous walk = high variance in speed
        # (stop-start pattern)
        cv_ratio = std / (mean + 1e-6)

        # Count full stops
        stops = sum(1 for s in sp if s < 8.0)

        nervous = min(
            cv_ratio * 0.5 +
            (stops / len(sp)) * 0.5,
            1.0
        )
        self.score = 0.3 * nervous + 0.7 * self.score

    def get(self):
        return float(self.score)


class Signal_LookingAround:
    """
    Detects repeated head turns:
    person nervously looks left/right/behind
    checking for security or witnesses.
    """
    def __init__(self):
        self.head_x_hist  = deque(maxlen=60)
        self.turn_count   = 0
        self.last_dir     = None
        self.score        = 0.0
        self.look_times   = deque(maxlen=20)

    def update(self, nose_x, nose_conf,
               lear_x, lear_c,
               rear_x, rear_c,
               frame_w):
        if nose_conf < 0.3:
            return

        norm_x = nose_x / (frame_w + 1e-6)
        self.head_x_hist.append(norm_x)

        # Detect direction from ear visibility
        curr_dir = None
        if lear_c > 0.3 and rear_c > 0.3:
            l_dist = abs(nose_x - lear_x)
            r_dist = abs(nose_x - rear_x)
            if l_dist < r_dist * 0.6:
                curr_dir = 'left'
            elif r_dist < l_dist * 0.6:
                curr_dir = 'right'
            else:
                curr_dir = 'center'

        # Count direction changes
        if (curr_dir is not None and
                curr_dir != self.last_dir and
                curr_dir != 'center' and
                self.last_dir is not None):
            self.turn_count += 1
            self.look_times.append(time.time())

        self.last_dir = curr_dir

        # Remove old look events (>30 seconds)
        now = time.time()
        while (self.look_times and
               now - self.look_times[0] > 30):
            self.look_times.popleft()

        # Variance in head position
        if len(self.head_x_hist) >= 15:
            variance = float(np.std(
                list(self.head_x_hist)[-15:]
            ))
        else:
            variance = 0.0

        recent_looks = len(self.look_times)
        look_score   = min(
            (recent_looks /
             CFG['look_count_limit']) * 0.6 +
            variance * 4.0 * 0.4,
            1.0
        )
        self.score = 0.35 * look_score + 0.65 * self.score

    def get(self):
        return float(self.score)


class Signal_HidingFace:
    """
    Detects face hiding behavior:
    - hood pulled down
    - hand covering face
    - looking down to avoid cameras
    - turning away from camera
    """
    def __init__(self):
        self.hide_frames  = 0
        self.total_frames = 0
        self.score        = 0.0

    def update(self, face_detected,
               nose_conf, nose_y,
               bbox_y1, bbox_y2):
        self.total_frames += 1

        hiding = False

        # No face detected = hiding
        if not face_detected or nose_conf < 0.25:
            hiding = True

        # Face very low in bbox = looking down
        elif bbox_y2 > bbox_y1:
            bbox_h     = bbox_y2 - bbox_y1
            nose_rel_y = (nose_y - bbox_y1) / (
                bbox_h + 1e-6
            )
            # Normal face: top 40% of body bbox
            if nose_rel_y > 0.45:
                hiding = True

        if hiding:
            self.hide_frames += 1
        else:
            self.hide_frames = max(
                0, self.hide_frames - 1
            )

        if self.total_frames > 0:
            hide_ratio = min(
                self.hide_frames /
                (self.total_frames * 0.4),
                1.0
            )
            self.score = (
                0.3 * hide_ratio +
                0.7 * self.score
            )

    def get(self):
        return float(self.score)


class Signal_Loitering:
    """
    Detects loitering:
    person stays in same area too long
    without clear purpose.
    """
    def __init__(self):
        self.first_seen    = time.time()
        self.pos_history   = deque(maxlen=300)
        self.score         = 0.0

    def update(self, cx, cy):
        self.pos_history.append((cx, cy))

        duration = time.time() - self.first_seen

        # Time component
        time_score = min(
            duration / CFG['loiter_seconds'],
            1.0
        )

        # Area component: staying in small area
        area_score = 0.0
        if len(self.pos_history) >= 30:
            positions = list(self.pos_history)
            xs = [p[0] for p in positions[-60:]]
            ys = [p[1] for p in positions[-60:]]
            spread_x  = max(xs) - min(xs)
            spread_y  = max(ys) - min(ys)
            area      = spread_x * spread_y

            # Small area = loitering
            # Large area = moving around
            if area < 8000:      # very small area
                area_score = 1.0
            elif area < 25000:
                area_score = 0.6
            elif area < 60000:
                area_score = 0.3
            else:
                area_score = 0.0

        combined = (
            time_score * 0.5 +
            area_score * 0.5
        )
        self.score = 0.1 * combined + 0.9 * self.score

    def get(self):
        return float(min(self.score, 1.0))


class Signal_SuddenMovement:
    """
    Detects sudden fast movements:
    lunging, grabbing, running away.
    """
    def __init__(self):
        self.wrist_hist   = deque(maxlen=20)
        self.center_hist  = deque(maxlen=20)
        self.spike_count  = 0
        self.score        = 0.0

    def update(self, center_x, center_y,
               lwrist_y, rwrist_y,
               lw_conf,  rw_conf):
        self.center_hist.append(
            (center_x, center_y, time.time())
        )

        wrist_y = None
        if lw_conf > 0.3 and rw_conf > 0.3:
            wrist_y = (lwrist_y + rwrist_y) / 2.0
        elif lw_conf > 0.3:
            wrist_y = lwrist_y
        elif rw_conf > 0.3:
            wrist_y = rwrist_y

        if wrist_y is not None:
            self.wrist_hist.append(wrist_y)

        # Body velocity
        body_vel = 0.0
        if len(self.center_hist) >= 4:
            ch = list(self.center_hist)
            dx = ch[-1][0] - ch[-4][0]
            dy = ch[-1][1] - ch[-4][1]
            dt = ch[-1][2] - ch[-4][2]
            body_vel = np.sqrt(dx*dx + dy*dy) / (
                dt * 100 + 1e-6
            )

        # Wrist velocity
        wrist_vel = 0.0
        if len(self.wrist_hist) >= 4:
            wh = list(self.wrist_hist)
            wrist_vel = abs(wh[-1] - wh[-4]) / 4.0

        # Spike detection
        if body_vel > 18 or wrist_vel > 22:
            self.spike_count = min(
                self.spike_count + 3, 30
            )
        else:
            self.spike_count = max(
                self.spike_count - 1, 0
            )

        sudden = min(
            (body_vel / 25.0) * 0.4 +
            (wrist_vel / 30.0) * 0.3 +
            (self.spike_count / 30.0) * 0.3,
            1.0
        )
        self.score = 0.45 * sudden + 0.55 * self.score

    def get(self):
        return float(self.score)


class Signal_Following:
    """
    Detects if person is following another person:
    maintains close distance while mirroring movement.
    """
    def __init__(self):
        self.follow_score  = 0.0
        self.mirror_count  = 0

    def update(self, my_cx, my_cy,
               other_persons):
        """
        other_persons: list of (cx, cy) of others
        """
        if not other_persons:
            self.follow_score = max(
                0, self.follow_score - 0.02
            )
            return

        # Find closest other person
        min_dist = float('inf')
        for (ox, oy) in other_persons:
            d = np.sqrt(
                (my_cx-ox)**2 + (my_cy-oy)**2
            )
            if d < min_dist:
                min_dist = d

        follow_lim = CFG['follow_dist_px']

        if min_dist < follow_lim:
            self.follow_score = min(
                self.follow_score + 0.04, 1.0
            )
        else:
            self.follow_score = max(
                self.follow_score - 0.02, 0.0
            )

    def get(self):
        return float(self.follow_score)


# ══════════════════════════════════════════════════
#  PERSON STATE — holds ALL signals + identity
# ══════════════════════════════════════════════════
class PersonState:
    def __init__(self, tid):
        self.tid             = tid
        self.first_seen      = time.time()
        self.last_seen       = time.time()

        # Identity
        self.name            = None
        self.category        = "stranger"
        self.face_conf       = 0.0

        # Emotion
        self.emotion         = "Neutral"
        self.emotion_threat  = 0.0

        # Behavior signals
        self.sig_nervous     = Signal_NervousWalk()
        self.sig_looking     = Signal_LookingAround()
        self.sig_hiding      = Signal_HidingFace()
        self.sig_loiter      = Signal_Loitering()
        self.sig_sudden      = Signal_SuddenMovement()
        self.sig_following   = Signal_Following()

        # Distance
        self.distance        = 99.0
        self.dist_hist       = deque(maxlen=8)

        # Final scores
        self.threat_score    = 0.0
        self.threat_label    = "Analyzing"
        self.threat_color    = (150, 150, 150)

        # Alert
        self.last_alert      = 0.0

        # Behavior sequence log
        self.behavior_log    = deque(maxlen=10)

    def log_behavior(self, behavior):
        now = datetime.now().strftime("%H:%M:%S")
        if (not self.behavior_log or
                self.behavior_log[-1][1] != behavior):
            self.behavior_log.append((now, behavior))

    def compute_threat(self):
        """
        Weighted combination of all signals.
        Sequence bonus applied if multiple
        signals active together.
        """
        s = {
            'nervous':   self.sig_nervous.get(),
            'looking':   self.sig_looking.get(),
            'hiding':    self.sig_hiding.get(),
            'loiter':    self.sig_loiter.get(),
            'sudden':    self.sig_sudden.get(),
            'following': self.sig_following.get(),
            'emotion':   self.emotion_threat,
        }

        # Weights per signal
        W = {
            'nervous':   0.12,
            'looking':   0.18,
            'hiding':    0.20,
            'loiter':    0.12,
            'sudden':    0.18,
            'following': 0.10,
            'emotion':   0.10,
        }

        base_score = sum(
            s[k] * W[k] for k in s
        )

        # SEQUENCE BONUS
        # Multiple behaviors together = more suspicious
        active = sum(
            1 for k in s
            if s[k] > 0.35
        )

        sequence_bonus = 0.0
        if active >= 4:
            sequence_bonus = 0.25   # Very suspicious
        elif active >= 3:
            sequence_bonus = 0.15   # Suspicious
        elif active >= 2:
            sequence_bonus = 0.08   # Slightly suspicious

        combined = min(
            base_score + sequence_bonus,
            1.0
        )

        # Category modifier
        mods = {
            'whitelist':  0.10,
            'routine':    0.70,
            'blacklist':  1.60,
            'stranger':   1.00,
        }
        mod = mods.get(self.category, 1.0)

        # Proximity boost
        if self.distance < CFG['critical_dist_m']:
            combined += 0.18
        elif self.distance < CFG['safe_dist_m']:
            combined += 0.08

        final = float(min(combined * mod, 1.0))

        # Smooth
        self.threat_score = (
            0.25 * final +
            0.75 * self.threat_score
        )

        # Label active behaviors
        active_behaviors = []
        if s['nervous']   > 0.30:
            active_behaviors.append("Nervous Walk")
            self.log_behavior("Nervous Walk")
        if s['looking']   > 0.30:
            active_behaviors.append("Looking Around")
            self.log_behavior("Looking Around")
        if s['hiding']    > 0.30:
            active_behaviors.append("Hiding Face")
            self.log_behavior("Hiding Face")
        if s['loiter']    > 0.35:
            active_behaviors.append("Loitering")
            self.log_behavior("Loitering")
        if s['sudden']    > 0.35:
            active_behaviors.append("Sudden Move!")
            self.log_behavior("Sudden Move!")
        if s['following'] > 0.40:
            active_behaviors.append("Following!")
            self.log_behavior("Following!")

        return self.threat_score, s, active_behaviors


# ══════════════════════════════════════════════════
#  GLOBAL STATE
# ══════════════════════════════════════════════════
person_states = {}
alert_log     = []
frame_count   = 0

# ══════════════════════════════════════════════════
#  HELPERS
# ══════════════════════════════════════════════════
def cosine_sim(a, b):
    n = (np.linalg.norm(a) *
         np.linalg.norm(b) + 1e-6)
    return float(np.dot(a, b) / n)

def smooth(new, old, a=0.3):
    return a * new + (1.0 - a) * old

def get_kp(kps, idx):
    k = kps[idx]
    return float(k[0]), float(k[1]), float(k[2])

def dist_meters(px_h):
    if px_h <= 0:
        return 99.0
    return (CFG['known_height_cm'] *
            CFG['focal_length']) / (px_h * 100.0)

def safe_crop(frame, x1, y1, x2, y2, pad=0):
    H, W = frame.shape[:2]
    x1 = max(0, x1-pad);  y1 = max(0, y1-pad)
    x2 = min(W, x2+pad);  y2 = min(H, y2+pad)
    if x2 <= x1 or y2 <= y1:
        return None
    return frame[y1:y2, x1:x2].copy()

def get_threat_info(score, category):
    if category == 'whitelist':
        return "TRUSTED",   (0,220,100), "Known Person"
    if category == 'blacklist':
        return "BLACKLIST", (0,0,200),   "Known Threat!"
    if score >= CFG['critical_threshold']:
        return "CRITICAL",  (0,0,255),   "IMMEDIATE THREAT!"
    elif score >= CFG['high_threshold']:
        return "HIGH",      (0,50,255),  "HIGH RISK DETECTED"
    elif score >= CFG['medium_threshold']:
        return "MEDIUM",    (0,140,255), "Suspicious Behavior"
    elif score >= CFG['watch_threshold']:
        return "WATCH",     (0,210,190), "Monitoring"
    else:
        return "SAFE",      (0,255,80),  "Normal Behavior"

# ══════════════════════════════════════════════════
#  ALERT SYSTEM
# ══════════════════════════════════════════════════
def speak_async(text):
    def _run():
        with tts_lock:
            try:
                tts_engine.say(text)
                tts_engine.runAndWait()
            except:
                pass
    threading.Thread(
        target=_run, daemon=True
    ).start()

def trigger_alert(frame, state,
                  threat_label, behaviors):
    now = time.time()
    if now - state.last_alert < CFG['alert_cooldown']:
        return
    state.last_alert = now

    name = state.name or f"Unknown ID:{state.tid}"
    ts   = datetime.now().strftime("%H:%M:%S")

    # Console log
    print(f"\n{'='*55}")
    print(f"🚨 ALERT [{ts}]")
    print(f"   Level    : {threat_label}")
    print(f"   Person   : {name}")
    print(f"   Score    : {state.threat_score*100:.1f}%")
    print(f"   Emotion  : {state.emotion}")
    print(f"   Distance : {state.distance:.1f}m")
    print(f"   Behaviors: {', '.join(behaviors)}")
    print(f"{'='*55}")

    # Save snapshot
    ts_file = datetime.now().strftime(
        "%Y%m%d_%H%M%S"
    )
    snap_path = os.path.join(
        CFG['snapshot_dir'],
        f"{threat_label}_{ts_file}.jpg"
    )
    annotated = frame.copy()
    cv2.putText(
        annotated,
        f"ALERT: {threat_label} | {name}",
        (10, 30),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.8, (0, 0, 255), 2
    )
    cv2.imwrite(snap_path, annotated)

    # Alert log
    alert_log.append({
        'time':      ts,
        'label':     threat_label,
        'name':      name,
        'score':     state.threat_score,
        'emotion':   state.emotion,
        'dist':      state.distance,
        'behaviors': behaviors[:3],
    })
    if len(alert_log) > 15:
        alert_log.pop(0)

    # Voice
    voice = {
        "CRITICAL": (
            "Critical threat detected! "
            "Security alert activated immediately!"
        ),
        "HIGH": (
            "Warning! High risk behavior detected. "
            "Security has been notified."
        ),
        "MEDIUM": (
            "Caution! Suspicious behavior detected. "
            "You are being monitored."
        ),
        "WATCH": (
            "This area is under surveillance."
        ),
        "BLACKLIST": (
            "Alert! Known threat detected. "
            "Authorities have been notified."
        ),
    }
    msg = voice.get(threat_label, "")
    if msg:
        speak_async(msg)

    # Telegram (optional)
    tg_token = os.environ.get("TG_TOKEN", "")
    tg_chat  = os.environ.get("TG_CHAT",  "")
    if tg_token and tg_chat:
        def _tg():
            try:
                import requests
                text = (
                    f"🚨 ProVisionGuard Alert!\n"
                    f"Level    : {threat_label}\n"
                    f"Person   : {name}\n"
                    f"Score    : {state.threat_score*100:.1f}%\n"
                    f"Emotion  : {state.emotion}\n"
                    f"Distance : {state.distance:.1f}m\n"
                    f"Behaviors: {', '.join(behaviors)}\n"
                    f"Time     : {ts}"
                )
                with open(snap_path, 'rb') as f:
                    requests.post(
                        f"https://api.telegram.org/"
                        f"bot{tg_token}/sendPhoto",
                        data={
                            'chat_id': tg_chat,
                            'caption': text
                        },
                        files={'photo': f},
                        timeout=5
                    )
            except:
                pass
        threading.Thread(
            target=_tg, daemon=True
        ).start()

# ══════════════════════════════════════════════════
#  DRAWING
# ══════════════════════════════════════════════════
def draw_person(frame, state, x1, y1, x2, y2,
                signals, behaviors, fc):

    threat_label, t_col, t_desc = get_threat_info(
        state.threat_score, state.category
    )

    # ── Main bounding box ─────────────────────────
    cv2.rectangle(frame,
                  (x1, y1), (x2, y2),
                  t_col, 2)

    # ── Identity header ───────────────────────────
    name_str = state.name or "STRANGER"
    cat_icon = {
        'whitelist': '✓',
        'blacklist': '!',
        'routine':   '~',
        'stranger':  '?'
    }.get(state.category, '?')

    header = (f"{cat_icon} {name_str}  "
              f"[{threat_label}]  "
              f"{state.threat_score*100:.0f}%")
    hw     = len(header) * 10
    hw     = max(hw, x2-x1)

    cv2.rectangle(frame,
                  (x1, y1-44), (x1+hw, y1),
                  t_col, -1)
    cv2.putText(frame, header,
                (x1+4, y1-25),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.55, (255,255,255), 2)
    cv2.putText(frame, t_desc,
                (x1+4, y1-8),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.38, (230,230,230), 1)

    # ── Active behaviors strip ────────────────────
    if behaviors:
        beh_str = "  •  ".join(behaviors[:4])
        cv2.rectangle(frame,
                      (x1, y2+1),
                      (x2, y2+20),
                      (20,20,20), -1)
        cv2.putText(frame, beh_str,
                    (x1+4, y2+14),
                    cv2.FONT_HERSHEY_SIMPLEX,
                    0.38, (255,200,0), 1)

    # ── Signal bars ───────────────────────────────
    bar_base = y2 + 24
    bar_w    = x2 - x1
    sig_list = [
        ("NERVOUS",   signals['nervous'],   (100,150,255)),
        ("LOOKING",   signals['looking'],   (0,200,255)),
        ("HIDING",    signals['hiding'],    (50,100,255)),
        ("LOITER",    signals['loiter'],    (150,50,255)),
        ("SUDDEN",    signals['sudden'],    (0,100,255)),
        ("FOLLOW",    signals['following'], (200,100,255)),
        ("EMOTION",   signals['emotion'],   (0,140,255)),
        ("THREAT",    state.threat_score,   t_col),
    ]

    for i, (lbl, val, col) in enumerate(sig_list):
        y = bar_base + i * 14

        cv2.putText(frame, lbl,
                    (x1, y+10),
                    cv2.FONT_HERSHEY_SIMPLEX,
                    0.33, (160,160,160), 1)

        cv2.rectangle(frame,
                      (x1+56, y),
                      (x2, y+11),
                      (25,25,25), -1)

        fill = int(val * (bar_w - 56))
        if fill > 0:
            cv2.rectangle(frame,
                          (x1+56, y),
                          (x1+56+fill, y+11),
                          col, -1)

        cv2.putText(frame,
                    f"{val*100:.0f}",
                    (x2-24, y+10),
                    cv2.FONT_HERSHEY_SIMPLEX,
                    0.33, (220,220,220), 1)

    # ── Distance display ──────────────────────────
    dist_y = bar_base + len(sig_list)*14 + 12
    if state.distance < CFG['critical_dist_m']:
        dc = (0,0,255)
        dt = f"⚠ {state.distance:.1f}m CRITICAL"
    elif state.distance < CFG['safe_dist_m']:
        dc = (0,165,255)
        dt = f"! {state.distance:.1f}m ALERT"
    else:
        dc = (0,255,80)
        dt = f"✓ {state.distance:.1f}m SAFE"

    cv2.putText(frame, dt,
                (x1, dist_y),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.48, dc, 2)

    # Emotion
    cv2.putText(frame,
                f"Emotion: {state.emotion}",
                (x1, dist_y+16),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.38, (180,180,180), 1)

    # Duration
    dur = int(time.time() - state.first_seen)
    cv2.putText(frame,
                f"In frame: {dur}s",
                (x1, dist_y+30),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.38, (120,120,120), 1)

    # ── Critical flash border ─────────────────────
    if (state.threat_score >= CFG['critical_threshold']
            and fc % 14 < 7):
        cv2.rectangle(frame,
                      (x1-5, y1-48),
                      (x2+5, y2+5),
                      (0, 0, 255), 4)


def draw_alert_panel(frame, W, H):
    if not alert_log:
        return

    panel_x = W - 305
    panel_y = 50
    rows    = alert_log[-5:]
    ph      = len(rows) * 52 + 28

    cv2.rectangle(frame,
                  (panel_x-5, panel_y-22),
                  (W-5, panel_y+ph),
                  (12,12,12), -1)

    cv2.putText(frame, "RECENT ALERTS",
                (panel_x, panel_y-6),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.48, (255,215,0), 1)

    label_col = {
        "CRITICAL":  (0,0,255),
        "HIGH":      (0,50,255),
        "MEDIUM":    (0,140,255),
        "WATCH":     (0,210,190),
        "BLACKLIST": (0,0,180),
    }

    for i, a in enumerate(rows):
        y   = panel_y + 8 + i*50
        col = label_col.get(a['label'],
                             (150,150,150))

        cv2.rectangle(frame,
                      (panel_x, y),
                      (W-10, y+44),
                      (22,22,22), -1)
        cv2.rectangle(frame,
                      (panel_x, y),
                      (panel_x+4, y+44),
                      col, -1)

        cv2.putText(frame,
                    f"{a['time']}  [{a['label']}]",
                    (panel_x+8, y+14),
                    cv2.FONT_HERSHEY_SIMPLEX,
                    0.45, col, 1)
        cv2.putText(frame,
                    f"{a['name']}  "
                    f"{a['score']*100:.0f}%",
                    (panel_x+8, y+28),
                    cv2.FONT_HERSHEY_SIMPLEX,
                    0.4, (200,200,200), 1)

        beh_str = ", ".join(a['behaviors'])
        cv2.putText(frame,
                    beh_str[:35],
                    (panel_x+8, y+41),
                    cv2.FONT_HERSHEY_SIMPLEX,
                    0.33, (140,140,140), 1)


def draw_hud(frame, n_persons, fps, W):
    cv2.rectangle(frame, (0,0), (W,42),
                  (10,10,10), -1)
    cv2.line(frame, (0,42), (W,42),
             (35,35,35), 1)

    cv2.putText(frame,
                "ProVisionGuard AI",
                (10, 28),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.88, (255,215,0), 2)

    ts = datetime.now().strftime("%d/%m %H:%M:%S")
    cv2.putText(frame,
                (f"Persons:{n_persons}  "
                 f"FPS:{fps:.1f}  "
                 f"Alerts:{len(alert_log)}  "
                 f"{ts}"),
                (230, 27),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.50, (160,160,160), 1)


# ══════════════════════════════════════════════════
#  MAIN LOOP
# ══════════════════════════════════════════════════
cap     = cv2.VideoCapture(0)
W_CAP   = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
H_CAP   = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
fps_buf = deque(maxlen=30)
fps_disp = 0.0

print("\n✅ ProVisionGuard AI is LIVE!")
print("   Q = Quit  |  R = Reset  |  S = Snapshot")
print("=" * 60)

while True:
    ret, frame = cap.read()
    if not ret:
        break

    t0           = time.time()
    frame_count += 1
    H_F, W_F     = frame.shape[:2]
    active_ids   = []

    # ── Detection ─────────────────────────────────
    det_res  = yolo_det.track(
        frame, persist=True,
        classes=[0], verbose=False, conf=0.45
    )
    pose_res = yolo_pose.track(
        frame, persist=True,
        verbose=False, conf=0.45
    )

    # ── Parse poses ───────────────────────────────
    pose_map = {}
    if (pose_res and
            pose_res[0].keypoints is not None and
            pose_res[0].boxes is not None):
        pkps = pose_res[0].keypoints.data
        pb   = pose_res[0].boxes
        for i, kps in enumerate(pkps):
            pid = (int(pb.id[i])
                   if pb.id is not None else i)
            pose_map[pid] = kps

    # ── Person centers (for following detection) ──
    all_centers = []
    if (det_res and
            det_res[0].boxes is not None):
        for box in det_res[0].boxes:
            bx = box.xyxy[0].cpu().numpy()
            cx = int((bx[0]+bx[2])/2)
            cy = int((bx[1]+bx[3])/2)
            all_centers.append((cx, cy))

    # ── Process each person ───────────────────────
    if (det_res and
            det_res[0].boxes is not None):
        boxes = det_res[0].boxes

        for i, box in enumerate(boxes):
            bxy = box.xyxy[0].cpu().numpy()
            x1,y1,x2,y2 = [int(v) for v in bxy]
            tid = (int(box.id[0])
                   if box.id is not None else i)

            active_ids.append(tid)

            if tid not in person_states:
                person_states[tid] = PersonState(tid)
            s = person_states[tid]
            s.last_seen = time.time()

            cx = int((x1+x2)/2)
            cy = int((y1+y2)/2)
            ph = y2 - y1

            # ── Distance ──────────────────────────
            s.dist_hist.append(dist_meters(ph))
            s.distance = float(
                np.median(s.dist_hist)
            )

            # ── Face recognition ──────────────────
            if frame_count % CFG['face_every_n'] == 0:
                crop = safe_crop(
                    frame, x1, y1, x2, y2
                )
                if crop is not None:
                    faces = face_app.get(crop)
                    if faces:
                        emb = faces[0].embedding
                        best_n  = None
                        best_c  = 'stranger'
                        best_sc = 0.0
                        for nm, dt in known_faces.items():
                            sim = cosine_sim(
                                emb, dt['emb']
                            )
                            if sim > best_sc:
                                best_sc = sim
                                best_n  = nm
                                best_c  = dt['category']
                        if best_sc >= CFG['face_threshold']:
                            s.name      = best_n
                            s.category  = best_c
                            s.face_conf = best_sc

            # ── Emotion ───────────────────────────
            if frame_count % CFG['emotion_every_n'] == 0:
                crop = safe_crop(
                    frame, x1, y1, x2, y2
                )
                if crop is not None and crop.size > 0:
                    try:
                        rgb = cv2.cvtColor(
                            crop, cv2.COLOR_BGR2RGB
                        )
                        emo, sc = emo_model.predict_emotions(
                            rgb, logits=False
                        )
                        lbls = [
                            'Anger','Contempt',
                            'Disgust','Fear',
                            'Happiness','Neutral',
                            'Sadness','Surprise'
                        ]
                        wts = {
                            'Anger':0.95,'Disgust':0.70,
                            'Fear':0.65,'Contempt':0.60,
                            'Surprise':0.35,'Sadness':0.20,
                            'Neutral':0.05,'Happiness':0.0
                        }
                        sd = dict(zip(lbls, sc))
                        et = min(sum(
                            sd.get(e,0)*w
                            for e,w in wts.items()
                        ), 1.0)
                        s.emotion = emo
                        s.emotion_threat = smooth(
                            float(et),
                            s.emotion_threat, 0.4
                        )
                    except:
                        pass

            # ── Behavior signals from pose ─────────
            kps = pose_map.get(tid)
            face_detected = (s.name is not None or
                             s.face_conf > 0.3)

            if kps is not None:
                nx,  ny,  nc  = get_kp(kps, 0)
                lsx, lsy, lsc = get_kp(kps, 5)
                rsx, rsy, rsc = get_kp(kps, 6)
                lwx, lwy, lwc = get_kp(kps, 9)
                rwx, rwy, rwc = get_kp(kps, 10)
                lex, ley, lec = get_kp(kps, 3)
                rex, rey, rec = get_kp(kps, 4)

                # Update each signal
                s.sig_nervous.update(cx, cy)
                s.sig_looking.update(
                    nx, nc,
                    lex, lec,
                    rex, rec,
                    W_F
                )
                s.sig_hiding.update(
                    face_detected,
                    nc, ny,
                    y1, y2
                )
                s.sig_sudden.update(
                    cx, cy,
                    lwy, rwy,
                    lwc, rwc
                )
            else:
                # No pose → still update some signals
                s.sig_nervous.update(cx, cy)
                s.sig_hiding.update(
                    face_detected,
                    0.0, 0.0,
                    y1, y2
                )
                s.sig_sudden.update(
                    cx, cy,
                    0.0, 0.0,
                    0.0, 0.0
                )

            # Loitering always updated
            s.sig_loiter.update(cx, cy)

            # Following: pass other centers
            others = [
                c for j, c in
                enumerate(all_centers)
                if j != i
            ]
            s.sig_following.update(cx, cy, others)

            # ── Compute final threat ──────────────
            threat_sc, signals, behaviors = (
                s.compute_threat()
            )

            # ── Trigger alert ─────────────────────
            tl, _, _ = get_threat_info(
                s.threat_score, s.category
            )
            if (tl in ["CRITICAL","HIGH",
                        "MEDIUM","BLACKLIST"]
                    and s.category != 'whitelist'):
                trigger_alert(
                    frame, s, tl, behaviors
                )

            # ── Draw ──────────────────────────────
            draw_person(
                frame, s, x1, y1, x2, y2,
                signals, behaviors, frame_count
            )

    # ── Cleanup stale states ──────────────────────
    for tid in list(person_states.keys()):
        if tid not in active_ids:
            if (time.time() -
                    person_states[tid].last_seen > 3):
                del person_states[tid]

    # ── UI ────────────────────────────────────────
    draw_alert_panel(frame, W_F, H_F)

    fps_buf.append(time.time() - t0)
    if len(fps_buf) == 30:
        fps_disp = 1.0 / (np.mean(fps_buf)+1e-6)

    draw_hud(frame, len(active_ids),
             fps_disp, W_F)

    cv2.imshow("ProVisionGuard AI", frame)

    key = cv2.waitKey(1) & 0xFF
    if key == ord('q'):
        break
    elif key == ord('r'):
        person_states.clear()
        alert_log.clear()
        print("🔄 All states reset!")
    elif key == ord('s'):
        ts  = datetime.now().strftime(
            "%Y%m%d_%H%M%S"
        )
        p   = os.path.join(
            CFG['snapshot_dir'],
            f"manual_{ts}.jpg"
        )
        cv2.imwrite(p, frame)
        print(f"📸 Snapshot saved: {p}")

cap.release()
cv2.destroyAllWindows()
print(f"\n✅ Shutdown.")
print(f"   Alerts     : {len(alert_log)}")
print(f"   Snapshots  : {CFG['snapshot_dir']}/")