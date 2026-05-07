from ultralytics import YOLO
import cv2
import numpy as np
from collections import deque
import time

print("🔄 Loading Models...")
pose_model = YOLO('yolo11n-pose.pt')
face_model = YOLO('yolo11n-face.pt') \
    if False else None  # Optional
print("✅ Models Loaded!")

cap = cv2.VideoCapture(0)
W_CAP = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
H_CAP = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))

# ── Per-person state tracking ─────────────────────
class PersonState:
    def __init__(self, tid):
        self.tid              = tid
        self.first_seen       = time.time()

        # History buffers
        self.wrist_y_hist     = deque(maxlen=30)
        self.head_x_hist      = deque(maxlen=30)
        self.head_y_hist      = deque(maxlen=30)
        self.shoulder_hist    = deque(maxlen=30)
        self.bbox_hist        = deque(maxlen=30)

        # Scores (0.0 - 1.0)
        self.stress_score     = 0.0
        self.intent_score     = 0.0
        self.gaze_score       = 0.0
        self.motion_score     = 0.0
        self.loiter_score     = 0.0

        # Final
        self.threat_score     = 0.0
        self.threat_label     = "Analyzing..."
        self.threat_color     = (150, 150, 150)

        # Flags
        self.looking_around   = 0
        self.hiding_hands     = False
        self.sudden_moves     = 0

states = {}

# ── Keypoints ─────────────────────────────────────
KP = {
    'nose':0,'l_eye':1,'r_eye':2,
    'l_ear':3,'r_ear':4,
    'l_sho':5,'r_sho':6,
    'l_elb':7,'r_elb':8,
    'l_wri':9,'r_wri':10,
    'l_hip':11,'r_hip':12,
    'l_kne':13,'r_kne':14,
    'l_ank':15,'r_ank':16,
}

def get_kp(kps, name):
    k = kps[KP[name]]
    return float(k[0]), float(k[1]), float(k[2])

def angle_3pts(a, b, c):
    """Angle at B."""
    v1 = np.array([a[0]-b[0], a[1]-b[1]])
    v2 = np.array([c[0]-b[0], c[1]-b[1]])
    cos = np.dot(v1,v2)/(
        np.linalg.norm(v1)*np.linalg.norm(v2)+1e-6
    )
    return float(np.degrees(np.arccos(
        np.clip(cos,-1,1)
    )))

def smooth(new_val, old_val, alpha=0.3):
    """Exponential smoothing."""
    return alpha * new_val + (1-alpha) * old_val

# ── Signal Analyzers ──────────────────────────────

def analyze_gaze(kps, state):
    """
    Detect shifty eyes / repeated looking around.
    Uses nose + ear positions for head direction.
    """
    nx, ny, nc = get_kp(kps, 'nose')
    lex,ley,lec = get_kp(kps, 'l_ear')
    rex,rey,rec = get_kp(kps, 'r_ear')

    if nc < 0.3:
        return state.gaze_score

    # Head turn ratio
    # Normal: both ears roughly equal distance from nose
    # Looking side: one ear much closer
    if lec > 0.2 and rec > 0.2:
        l_dist = abs(nx - lex)
        r_dist = abs(nx - rex)
        ratio  = min(l_dist,r_dist) / (
            max(l_dist,r_dist) + 1e-6
        )
        # ratio near 0 = looking hard to one side
        head_turned = ratio < 0.35
    else:
        head_turned = False

    state.head_x_hist.append(nx / W_CAP)

    # Detect rapid side-to-side head movement
    gaze_variance = 0.0
    if len(state.head_x_hist) >= 10:
        gaze_variance = float(
            np.std(list(state.head_x_hist)[-10:])
        )

    # High variance = looking around nervously
    looking_around = gaze_variance > 0.025

    if looking_around:
        state.looking_around = min(
            state.looking_around + 1, 30
        )
    else:
        state.looking_around = max(
            state.looking_around - 1, 0
        )

    gaze_score = min(
        state.looking_around / 20.0 +
        (0.3 if head_turned else 0.0),
        1.0
    )
    return smooth(gaze_score, state.gaze_score)

def analyze_stress(kps, state):
    """
    Detect physical stress signals:
    - Raised / tense shoulders
    - Self-touching (hands near face/neck)
    - Hunched posture
    """
    lsx,lsy,lsc = get_kp(kps,'l_sho')
    rsx,rsy,rsc = get_kp(kps,'r_sho')
    lhx,lhy,lhc = get_kp(kps,'l_hip')
    rhx,rhy,rhc = get_kp(kps,'r_hip')
    lwx,lwy,lwc = get_kp(kps,'l_wri')
    rwx,rwy,rwc = get_kp(kps,'r_wri')
    nx, ny, nc  = get_kp(kps,'nose')

    stress = 0.0

    if lsc > 0.3 and rsc > 0.3:
        sh_avg_y  = (lsy + rsy) / 2
        hip_avg_y = (lhy + rhy) / 2 \
            if lhc>0.3 and rhc>0.3 else sh_avg_y+100

        torso_h   = abs(hip_avg_y - sh_avg_y)

        # Raised shoulders:
        # shoulders closer to ears = tension
        # normalized shoulder height
        sh_raise_ratio = sh_avg_y / (H_CAP + 1e-6)

        # Unusually high shoulders = tense
        if sh_raise_ratio < 0.30:
            stress += 0.25

        # Hunched: shoulder width narrow
        sh_width = abs(lsx - rsx) / (W_CAP + 1e-6)
        if sh_width < 0.12:
            stress += 0.20

    # Self-touching: wrist near face
    if nc > 0.3:
        if lwc > 0.3:
            l_face_dist = np.sqrt(
                (lwx-nx)**2 + (lwy-ny)**2
            ) / H_CAP
            if l_face_dist < 0.12:
                stress += 0.25  # touching face

        if rwc > 0.3:
            r_face_dist = np.sqrt(
                (rwx-nx)**2 + (rwy-ny)**2
            ) / H_CAP
            if r_face_dist < 0.12:
                stress += 0.25

    # Hiding hands: wrists below hips
    if lwc>0.3 and lhc>0.3:
        if lwy > lhy + 0.05*H_CAP:
            stress += 0.15
            state.hiding_hands = True
        else:
            state.hiding_hands = False

    return smooth(min(stress, 1.0), state.stress_score)

def analyze_motion(kps, state):
    """
    Detect suspicious motion patterns:
    - Sudden movements
    - Pacing / restless movement
    - Hesitation (stop-start walking)
    """
    lwx,lwy,lwc = get_kp(kps,'l_wri')
    rwx,rwy,rwc = get_kp(kps,'r_wri')
    nx, ny, nc  = get_kp(kps,'nose')

    wrist_y = (lwy+rwy)/2 if lwc>0.3 and rwc>0.3 \
        else ny

    state.wrist_y_hist.append(wrist_y)

    if len(state.wrist_y_hist) < 5:
        return state.motion_score

    recent    = list(state.wrist_y_hist)

    # Velocity: movement speed
    velocity  = abs(recent[-1] - recent[-4])

    # Variance: restless = high variance
    variance  = float(np.std(recent[-10:])
                      if len(recent)>=10 else 0)

    # Sudden spike detection
    if velocity > 20:
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

    return smooth(motion, state.motion_score)

def analyze_loitering(state):
    """
    Time spent in frame = loitering score.
    Longer = more suspicious (for stranger).
    """
    duration = time.time() - state.first_seen
    # 0 sec → 0.0
    # 30 sec → 0.5
    # 60 sec → 1.0
    score = min(duration / 60.0, 1.0)
    return score

def compute_intent(state):
    """
    Combine all signals → final intent score.
    """
    # Weights
    W_GAZE    = 0.25
    W_STRESS  = 0.30
    W_MOTION  = 0.25
    W_LOITER  = 0.20

    score = (
        state.gaze_score   * W_GAZE  +
        state.stress_score * W_STRESS +
        state.motion_score * W_MOTION +
        state.loiter_score * W_LOITER
    )
    return min(score, 1.0)

def get_threat_label(score, duration):
    """Convert score to label."""
    if score >= 0.75:
        return (
            "CRITICAL THREAT",
            (0, 0, 255),
            "HIGH INTENT DETECTED"
        )
    elif score >= 0.55:
        return (
            "HIGH THREAT",
            (0, 60, 255),
            "SUSPICIOUS BEHAVIOR"
        )
    elif score >= 0.38:
        return (
            "MEDIUM THREAT",
            (0, 165, 255),
            "STRESS SIGNALS DETECTED"
        )
    elif score >= 0.22:
        return (
            "WATCH",
            (0, 220, 200),
            "MONITORING"
        )
    else:
        return (
            "SAFE",
            (0, 255, 0),
            "NORMAL BEHAVIOR"
        )

def draw_intent_panel(frame, state, x1, y1, x2, y2):
    """Draw per-person intent analysis panel."""
    t_label, t_color, t_desc = get_threat_label(
        state.threat_score,
        time.time() - state.first_seen
    )

    # Box
    cv2.rectangle(frame,
                  (x1,y1),(x2,y2),
                  t_color, 2)

    # Header bar
    cv2.rectangle(frame,
                  (x1,y1-40),(x2,y1),
                  t_color, -1)
    cv2.putText(frame,
                f"ID:{state.tid}  {t_label}",
                (x1+4, y1-14),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.55, (255,255,255), 2)

    # Threat description
    cv2.putText(frame,
                t_desc,
                (x1+4, y1-2),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.38, (200,200,200), 1)

    # Score bars below box
    bar_y = y2 + 8
    bar_w = x2 - x1

    signals = [
        ("GAZE",   state.gaze_score,   (0,200,255)),
        ("STRESS", state.stress_score, (0,100,255)),
        ("MOTION", state.motion_score, (0,165,255)),
        ("LOITER", state.loiter_score, (150,0,255)),
        ("INTENT", state.threat_score, t_color),
    ]

    for i,(lbl,val,col) in enumerate(signals):
        y = bar_y + i*16

        # Label
        cv2.putText(frame, f"{lbl}",
                    (x1, y+10),
                    cv2.FONT_HERSHEY_SIMPLEX,
                    0.38, (180,180,180), 1)

        # Bar bg
        cv2.rectangle(frame,
                      (x1+52, y),
                      (x2, y+11),
                      (30,30,30), -1)

        # Bar fill
        fill = int(val * (bar_w - 52))
        if fill > 0:
            cv2.rectangle(frame,
                          (x1+52, y),
                          (x1+52+fill, y+11),
                          col, -1)

        # Value
        cv2.putText(frame,
                    f"{val*100:.0f}%",
                    (x2-35, y+10),
                    cv2.FONT_HERSHEY_SIMPLEX,
                    0.35, (255,255,255), 1)

# ── Main Loop ─────────────────────────────────────
frame_count = 0

while True:
    ret, frame = cap.read()
    if not ret:
        break

    frame_count += 1

    results = pose_model.track(
        frame,
        persist=True,
        verbose=False,
        conf=0.45
    )

    active_ids = []

    if (results and
            results[0].keypoints is not None and
            results[0].boxes is not None):

        kps_list = results[0].keypoints.data
        boxes    = results[0].boxes

        for i, kps in enumerate(kps_list):
            tid = int(boxes.id[i]) \
                if boxes.id is not None else i

            active_ids.append(tid)

            # Init state
            if tid not in states:
                states[tid] = PersonState(tid)
            s = states[tid]

            # ── Analyze all signals ───────────────
            s.gaze_score   = analyze_gaze(kps, s)
            s.stress_score = analyze_stress(kps, s)
            s.motion_score = analyze_motion(kps, s)
            s.loiter_score = analyze_loitering(s)
            s.threat_score = smooth(
                compute_intent(s),
                s.threat_score,
                alpha=0.25
            )

            # Bounding box
            box = boxes.xyxy[i].cpu().numpy()
            x1,y1,x2,y2 = (
                int(box[0]),int(box[1]),
                int(box[2]),int(box[3])
            )

            # Draw intent panel
            draw_intent_panel(
                frame, s, x1, y1, x2, y2
            )

    # Cleanup old states
    for tid in list(states.keys()):
        if tid not in active_ids:
            del states[tid]

    # ── Global HUD ────────────────────────────────
    cv2.rectangle(frame,(0,0),(500,38),
                  (12,12,12),-1)
    cv2.putText(frame,
                "ProVisionGuard AI  |  Intent Engine",
                (10,25),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.7,(255,215,0),2)
    cv2.putText(frame,
                f"Tracking: {len(active_ids)} person(s)  |  Q=quit",
                (10,36),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.38,(100,100,100),1)

    cv2.imshow(
        "ProVisionGuard AI - Intent Engine",
        frame
    )

    if cv2.waitKey(1) & 0xFF == ord('q'):
        break

cap.release()
cv2.destroyAllWindows()
print("✅ Done!")