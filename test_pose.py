from ultralytics import YOLO
import cv2
import numpy as np
from collections import deque

print("🔄 Loading YOLO Pose Model...")
model = YOLO('yolo11n-pose.pt')
print("✅ Model Loaded!")

cap = cv2.VideoCapture(0)

# ── Keypoint Indices (COCO 17) ────────────────────
KP = {
    'nose':           0,
    'left_eye':       1,  'right_eye':       2,
    'left_ear':       3,  'right_ear':       4,
    'left_shoulder':  5,  'right_shoulder':  6,
    'left_elbow':     7,  'right_elbow':     8,
    'left_wrist':     9,  'right_wrist':     10,
    'left_hip':       11, 'right_hip':       12,
    'left_knee':      13, 'right_knee':      14,
    'left_ankle':     15, 'right_ankle':     16,
}

# Per-person history (for velocity)
history = {}

# ─────────────────────────────────────────────────
def kp(keypoints, name):
    """Get (x, y, confidence) for a keypoint."""
    idx = KP[name]
    k   = keypoints[idx]
    return float(k[0]), float(k[1]), float(k[2])

def angle(a, b, c):
    """
    Calculate angle at point B formed by A-B-C.
    Returns angle in degrees (0-180).
    """
    ax, ay = a[0]-b[0], a[1]-b[1]
    cx, cy = c[0]-b[0], c[1]-b[1]
    dot    = ax*cx + ay*cy
    mag    = (np.sqrt(ax**2+ay**2) *
              np.sqrt(cx**2+cy**2) + 1e-6)
    angle_ = np.degrees(np.arccos(
        np.clip(dot/mag, -1.0, 1.0)
    ))
    return float(angle_)

def velocity(track_id, point_y):
    """Track vertical velocity for sudden movement."""
    if track_id not in history:
        history[track_id] = deque(maxlen=8)
    history[track_id].append(point_y)
    if len(history[track_id]) < 4:
        return 0.0
    recent = list(history[track_id])
    vel    = abs(recent[-1] - recent[-4])
    return vel

def draw_angle_arc(frame, b, angle_val, color):
    """Draw angle value near joint."""
    bx, by = int(b[0]), int(b[1])
    cv2.putText(
        frame, f"{angle_val:.0f}°",
        (bx+8, by-8),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.45, color, 1
    )

def draw_skeleton(frame, keypoints, color=(0,255,100)):
    """Draw skeleton connections."""
    connections = [
        ('left_shoulder',  'right_shoulder'),
        ('left_shoulder',  'left_elbow'),
        ('left_elbow',     'left_wrist'),
        ('right_shoulder', 'right_elbow'),
        ('right_elbow',    'right_wrist'),
        ('left_shoulder',  'left_hip'),
        ('right_shoulder', 'right_hip'),
        ('left_hip',       'right_hip'),
        ('left_hip',       'left_knee'),
        ('left_knee',      'left_ankle'),
        ('right_hip',      'right_knee'),
        ('right_knee',     'right_ankle'),
        ('nose',           'left_shoulder'),
        ('nose',           'right_shoulder'),
    ]
    for a_name, b_name in connections:
        ax, ay, ac = kp(keypoints, a_name)
        bx, by, bc = kp(keypoints, b_name)
        if ac > 0.3 and bc > 0.3:
            cv2.line(frame,
                     (int(ax), int(ay)),
                     (int(bx), int(by)),
                     color, 2)

    # Draw keypoint circles
    for name, idx in KP.items():
        x, y, c = kp(keypoints, name)
        if c > 0.3:
            cv2.circle(frame,
                       (int(x), int(y)),
                       4, (255,255,0), -1)
            cv2.circle(frame,
                       (int(x), int(y)),
                       4, color, 1)

def analyze(keypoints, track_id, W, H):
    """
    Full angle-based behavior analysis.
    Returns: behavior, color, threat, threat_color, details
    """
    # ── Extract all needed keypoints ─────────────
    lsx, lsy, lsc = kp(keypoints, 'left_shoulder')
    rsx, rsy, rsc = kp(keypoints, 'right_shoulder')
    lex, ley, lec = kp(keypoints, 'left_elbow')
    rex, rey, rec = kp(keypoints, 'right_elbow')
    lwx, lwy, lwc = kp(keypoints, 'left_wrist')
    rwx, rwy, rwc = kp(keypoints, 'right_wrist')
    lhx, lhy, lhc = kp(keypoints, 'left_hip')
    rhx, rhy, rhc = kp(keypoints, 'right_hip')
    lkx, lky, lkc = kp(keypoints, 'left_knee')
    rkx, rky, rkc = kp(keypoints, 'right_knee')
    nsx, nsy, nsc = kp(keypoints, 'nose')

    # Confidence gate
    if lsc < 0.3 and rsc < 0.3:
        return "Low Visibility", (100,100,100), "SAFE", (0,255,0), {}

    # ── Angle Calculations ────────────────────────

    # Left arm angle (shoulder→elbow→wrist)
    l_arm_ang = 180.0
    if lsc>0.3 and lec>0.3 and lwc>0.3:
        l_arm_ang = angle(
            (lsx,lsy), (lex,ley), (lwx,lwy)
        )

    # Right arm angle
    r_arm_ang = 180.0
    if rsc>0.3 and rec>0.3 and rwc>0.3:
        r_arm_ang = angle(
            (rsx,rsy), (rex,rey), (rwx,rwy)
        )

    # Left shoulder raise angle (hip→shoulder→elbow)
    l_raise_ang = 0.0
    if lhc>0.3 and lsc>0.3 and lec>0.3:
        l_raise_ang = angle(
            (lhx,lhy), (lsx,lsy), (lex,ley)
        )

    # Right shoulder raise angle
    r_raise_ang = 0.0
    if rhc>0.3 and rsc>0.3 and rec>0.3:
        r_raise_ang = angle(
            (rhx,rhy), (rsx,rsy), (rex,rey)
        )

    # Spine angle (shoulder midpoint → hip midpoint)
    spine_ang = 90.0
    if lsc>0.3 and rsc>0.3 and lhc>0.3 and rhc>0.3:
        sh_mid = ((lsx+rsx)/2, (lsy+rsy)/2)
        hp_mid = ((lhx+rhx)/2, (lhy+rhy)/2)
        # Vertical reference point
        vert   = (sh_mid[0], hp_mid[1])
        spine_ang = angle(sh_mid, hp_mid, vert)

    # Left knee angle (hip→knee→ankle)
    l_knee_ang = 180.0
    if lhc>0.3 and lkc>0.3:
        lax, lay, lac = kp(keypoints, 'left_ankle')
        if lac>0.3:
            l_knee_ang = angle(
                (lhx,lhy),(lkx,lky),(lax,lay)
            )

    # Right knee angle
    r_knee_ang = 180.0
    if rhc>0.3 and rkc>0.3:
        rax, ray, rac = kp(keypoints, 'right_ankle')
        if rac>0.3:
            r_knee_ang = angle(
                (rhx,rhy),(rkx,rky),(rax,ray)
            )

    # ── Velocity (sudden movement) ────────────────
    wrist_mid_y = (lwy + rwy) / 2
    vel         = velocity(track_id, wrist_mid_y)
    sudden      = vel > 18

    # ── Shoulder width ratio (fighting stance) ────
    sh_width = abs(lsx - rsx) / (W + 1e-6)
    wide     = sh_width > 0.28

    # ── Detection Rules ───────────────────────────

    details = {
        'L_Arm':    f"{l_arm_ang:.0f}°",
        'R_Arm':    f"{r_arm_ang:.0f}°",
        'L_Raise':  f"{l_raise_ang:.0f}°",
        'R_Raise':  f"{r_raise_ang:.0f}°",
        'Spine':    f"{spine_ang:.0f}°",
        'Velocity': f"{vel:.1f}px",
    }

    # Rule 1: Attack pose
    # Both arms raised AND sudden movement
    if (l_raise_ang > 120 and r_raise_ang > 120
            and sudden):
        return (
            "ATTACK POSE DETECTED!",
            (0, 0, 255),
            "CRITICAL THREAT",
            (0, 0, 255),
            details
        )

    # Rule 2: Both arms raised high
    if l_raise_ang > 130 and r_raise_ang > 130:
        return (
            "Both Arms Raised High!",
            (0, 30, 255),
            "HIGH THREAT",
            (0, 30, 255),
            details
        )

    # Rule 3: Punching motion
    # Arm nearly straight + high velocity
    if ((l_arm_ang > 155 or r_arm_ang > 155)
            and sudden):
        return (
            "Punching Motion!",
            (0, 60, 255),
            "HIGH THREAT",
            (0, 60, 255),
            details
        )

    # Rule 4: One arm raised aggressively
    if l_raise_ang > 140 or r_raise_ang > 140:
        return (
            "Aggressive Arm Raise",
            (0, 120, 255),
            "HIGH THREAT",
            (0, 120, 255),
            details
        )

    # Rule 5: Sudden fast movement
    if sudden and vel > 30:
        return (
            "Sudden Fast Movement!",
            (0, 165, 255),
            "MEDIUM THREAT",
            (0, 165, 255),
            details
        )

    # Rule 6: Crouch / attack squat
    if l_knee_ang < 110 and r_knee_ang < 110:
        return (
            "Crouching Stance!",
            (0, 180, 255),
            "MEDIUM THREAT",
            (0, 180, 255),
            details
        )

    # Rule 7: Wide fighting stance
    if wide and (l_raise_ang > 90 or r_raise_ang > 90):
        return (
            "Fighting Stance",
            (0, 200, 255),
            "MEDIUM THREAT",
            (0, 200, 255),
            details
        )

    # Rule 8: Moderate arm raise
    if l_raise_ang > 90 or r_raise_ang > 90:
        return (
            "Arm Raised - Watch",
            (0, 220, 200),
            "WATCH",
            (0, 220, 200),
            details
        )

    # Rule 9: Sudden moderate movement
    if sudden:
        return (
            "Sudden Movement",
            (0, 220, 180),
            "WATCH",
            (0, 220, 180),
            details
        )

    # Rule 10: Forward aggressive lean
    if spine_ang > 25:
        return (
            "Forward Lean",
            (0, 230, 150),
            "WATCH",
            (0, 230, 150),
            details
        )

    # Safe
    return (
        "Normal Posture",
        (0, 255, 0),
        "SAFE",
        (0, 255, 0),
        details
    )


# ── Main Loop ─────────────────────────────────────
while True:
    ret, frame = cap.read()
    if not ret:
        break

    H, W = frame.shape[:2]

    results = model.track(
        frame,
        persist=True,
        verbose=False,
        conf=0.45
    )

    persons = []

    if (results and
            results[0].keypoints is not None and
            results[0].boxes is not None):

        kps_list = results[0].keypoints.data
        boxes    = results[0].boxes

        for i, kps in enumerate(kps_list):
            tid = (int(boxes.id[i])
                   if boxes.id is not None else i)

            beh, b_col, thr, t_col, det = analyze(
                kps, tid, W, H
            )

            persons.append({
                'id': tid, 'behavior': beh,
                'b_col': b_col, 'threat': thr,
                't_col': t_col, 'details': det,
                'kps': kps
            })

            # Draw skeleton
            draw_skeleton(frame, kps, b_col)

            # Bounding box
            box = boxes.xyxy[i].cpu().numpy()
            x1,y1,x2,y2 = (int(box[0]),int(box[1]),
                            int(box[2]),int(box[3]))

            cv2.rectangle(frame,(x1,y1),(x2,y2),
                          t_col, 2)

            # Label
            lbl = f"ID:{tid} | {beh}"
            lbl_w = len(lbl) * 10
            cv2.rectangle(frame,
                          (x1, y1-36),
                          (x1+lbl_w, y1),
                          t_col, -1)
            cv2.putText(frame, lbl,
                        (x1+4, y1-12),
                        cv2.FONT_HERSHEY_SIMPLEX,
                        0.55, (255,255,255), 2)

            # Angle labels on joints
            if det:
                draw_angle_arc(
                    frame,
                    (kps[KP['left_elbow']][0],
                     kps[KP['left_elbow']][1]),
                    float(det['L_Arm'].replace('°','')),
                    b_col
                )
                draw_angle_arc(
                    frame,
                    (kps[KP['right_elbow']][0],
                     kps[KP['right_elbow']][1]),
                    float(det['R_Arm'].replace('°','')),
                    b_col
                )

            # Threat meter bar
            cv2.rectangle(frame,
                          (x1,y2+2),(x2,y2+10),
                          (40,40,40),-1)
            cv2.rectangle(frame,
                          (x1,y2+2),(x2,y2+10),
                          t_col,-1)

    # ── HUD ───────────────────────────────────────
    hud_h = 45 + len(persons) * 55
    cv2.rectangle(frame,(0,0),(510,hud_h),
                  (12,12,12),-1)
    cv2.line(frame,(10,32),(500,32),(50,50,50),1)

    cv2.putText(frame,
                "ProVisionGuard AI  |  Pose Engine",
                (10,23),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.65,(255,215,0),2)

    for idx, p in enumerate(persons):
        base = 48 + idx * 55

        # Threat status
        cv2.putText(frame,
                    f"ID:{p['id']}  [{p['threat']}]  {p['behavior']}",
                    (10, base),
                    cv2.FONT_HERSHEY_SIMPLEX,
                    0.55, p['t_col'], 2)

        # Angle details
        if p['details']:
            d = p['details']
            detail_str = (
                f"LArm:{d.get('L_Arm','?')} "
                f"RArm:{d.get('R_Arm','?')} "
                f"LRaise:{d.get('L_Raise','?')} "
                f"RRaise:{d.get('R_Raise','?')} "
                f"Vel:{d.get('Velocity','?')}"
            )
            cv2.putText(frame, detail_str,
                        (10, base+22),
                        cv2.FONT_HERSHEY_SIMPLEX,
                        0.4, (150,150,150), 1)

    if not persons:
        cv2.putText(frame,
                    "No person detected",
                    (10,50),
                    cv2.FONT_HERSHEY_SIMPLEX,
                    0.6,(150,150,150),1)

    cv2.putText(frame,
                f"Persons:{len(persons)} | Q=quit",
                (10, hud_h-6),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.42,(80,80,80),1)

    cv2.imshow("ProVisionGuard AI - Pose Engine", frame)

    if cv2.waitKey(1) & 0xFF == ord('q'):
        break

cap.release()
cv2.destroyAllWindows()
print("✅ Done!")