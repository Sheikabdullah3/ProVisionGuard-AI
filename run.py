"""
ProVisionGuard AI — Main System
=================================
Run this file to start everything:
  python run.py

Dashboard: http://localhost:5000
"""

import subprocess
import threading
import sys
import os
import time

def start_dashboard():
    """Start dashboard server in background."""
    try:
        from dashboard import (
            app, sio, dashboard_state,
            state_lock
        )
        print("✅ Dashboard starting on http://localhost:5000")
        sio.run(app, host='0.0.0.0',
                port=5000, debug=False,
                use_reloader=False)
    except Exception as e:
        print(f"⚠ Dashboard error: {e}")

def start_camera():
    """Start main detection system."""
    # Import dashboard state
    try:
        from dashboard import dashboard_state, state_lock
        DASHBOARD_AVAILABLE = True
    except:
        DASHBOARD_AVAILABLE = False
        print("⚠ Dashboard not available")

    import cv2
    import numpy as np
    import time
    import threading
    import os
    from datetime import datetime
    from collections import deque
    from ultralytics import YOLO
    from insightface.app import FaceAnalysis
    from hsemotion_onnx.facial_emotions import (
        HSEmotionRecognizer
    )
    import pyttsx3

    # ═══════════════════════════════════════════
    #  CONFIG
    # ═══════════════════════════════════════════
    CFG = {
        'focal_length'      : 450.0,
        'known_height_cm'   : 170.0,
        'safe_dist_m'       : 2.5,
        'critical_dist_m'   : 1.2,
        'face_db_path'      : 'data/known_faces',
        'face_threshold'    : 0.55,
        'loiter_seconds'    : 25,
        'look_count_limit'  : 12,
        'follow_dist_px'    : 120,
        'watch_threshold'   : 0.28,
        'medium_threshold'  : 0.48,
        'high_threshold'    : 0.68,
        'critical_threshold': 0.85,
        'alert_cooldown'    : 18,
        'snapshot_dir'      : 'data/snapshots',
        'face_every_n'      : 6,
        'emotion_every_n'   : 8,
    }
    os.makedirs(CFG['snapshot_dir'], exist_ok=True)

    print("=" * 55)
    print("  ProVisionGuard AI — Loading Models")
    print("=" * 55)

    yolo_det  = YOLO('yolo11n.pt')
    yolo_pose = YOLO('yolo11n-pose.pt')

    face_app  = FaceAnalysis(name='buffalo_l')
    face_app.prepare(ctx_id=0, det_size=(640,640))

    emo_model = HSEmotionRecognizer(
        model_name='enet_b0_8_best_afew'
    )

    tts_lock   = threading.Lock()
    tts_engine = pyttsx3.init()
    tts_engine.setProperty('rate', 148)
    tts_engine.setProperty('volume', 1.0)

    print("✅ All models loaded!")

    # ── Face DB ────────────────────────────────
    known_faces = {}

    def load_face_db():
        print("🔄 Loading face database...")
        for cat in ['whitelist','routine','blacklist']:
            cat_dir = os.path.join(
                CFG['face_db_path'], cat
            )
            if not os.path.exists(cat_dir):
                continue
            for person in os.listdir(cat_dir):
                p_dir = os.path.join(cat_dir, person)
                if not os.path.isdir(p_dir):
                    continue
                embs = []
                for f in os.listdir(p_dir):
                    if not f.lower().endswith(
                        ('.jpg','.jpeg','.png')
                    ):
                        continue
                    img = cv2.imread(
                        os.path.join(p_dir, f)
                    )
                    if img is None:
                        continue
                    faces = face_app.get(img)
                    if faces:
                        embs.append(
                            faces[0].embedding
                        )
                if embs:
                    known_faces[person] = {
                        'emb': np.mean(embs,axis=0),
                        'category': cat
                    }
                    print(f"  ✅ {person} [{cat}]")
        print(f"✅ {len(known_faces)} loaded!\n")

    load_face_db()

    # ── Signal Classes ─────────────────────────
    class Signal_NervousWalk:
        def __init__(self):
            self.pos_history   = deque(maxlen=45)
            self.speed_history = deque(maxlen=20)
            self.score         = 0.0

        def update(self, cx, cy):
            self.pos_history.append(
                (cx, cy, time.time())
            )
            if len(self.pos_history) < 6:
                return
            positions = list(self.pos_history)
            speeds = []
            for i in range(1, len(positions)):
                dx = (positions[i][0] -
                      positions[i-1][0])
                dy = (positions[i][1] -
                      positions[i-1][1])
                dt = (positions[i][2] -
                      positions[i-1][2])
                if dt > 0:
                    speeds.append(
                        np.sqrt(dx*dx+dy*dy)/dt
                    )
            if len(speeds) < 4:
                return
            self.speed_history.extend(speeds[-4:])
            if len(self.speed_history) < 8:
                return
            sp   = list(self.speed_history)
            mean = np.mean(sp)
            std  = np.std(sp)
            cv_r = std / (mean + 1e-6)
            stops = sum(1 for s in sp if s < 8.0)
            n = min(cv_r*0.5+(stops/len(sp))*0.5,1.0)
            self.score = 0.3*n + 0.7*self.score

        def get(self):
            return float(self.score)

    class Signal_LookingAround:
        def __init__(self):
            self.head_x_hist = deque(maxlen=60)
            self.turn_count  = 0
            self.last_dir    = None
            self.score       = 0.0
            self.look_times  = deque(maxlen=20)

        def update(self, nx, nc,
                   lex, lec, rex, rec, W):
            if nc < 0.3:
                return
            self.head_x_hist.append(
                nx / (W + 1e-6)
            )
            curr_dir = None
            if lec > 0.2 and rec > 0.2:
                l_d = abs(nx - lex)
                r_d = abs(nx - rex)
                if l_d < r_d * 0.6:
                    curr_dir = 'left'
                elif r_d < l_d * 0.6:
                    curr_dir = 'right'
                else:
                    curr_dir = 'center'
            if (curr_dir and
                    curr_dir != self.last_dir and
                    curr_dir != 'center' and
                    self.last_dir):
                self.look_times.append(time.time())
            self.last_dir = curr_dir
            now = time.time()
            while (self.look_times and
                   now-self.look_times[0] > 30):
                self.look_times.popleft()
            variance = 0.0
            if len(self.head_x_hist) >= 15:
                variance = float(np.std(
                    list(self.head_x_hist)[-15:]
                ))
            ls = min(
                (len(self.look_times) /
                 CFG['look_count_limit'])*0.6 +
                variance*4.0*0.4,
                1.0
            )
            self.score = 0.35*ls + 0.65*self.score

        def get(self):
            return float(self.score)

    class Signal_HidingFace:
        def __init__(self):
            self.hide_frames  = 0
            self.total_frames = 0
            self.score        = 0.0

        def update(self, face_det, nc,
                   ny, y1, y2):
            self.total_frames += 1
            hiding = False
            if not face_det or nc < 0.25:
                hiding = True
            elif y2 > y1:
                bh  = y2 - y1
                rel = (ny-y1)/(bh+1e-6)
                if rel > 0.45:
                    hiding = True
            if hiding:
                self.hide_frames += 1
            else:
                self.hide_frames = max(
                    0, self.hide_frames-1
                )
            if self.total_frames > 0:
                hr = min(
                    self.hide_frames /
                    (self.total_frames*0.4),
                    1.0
                )
                self.score = 0.3*hr+0.7*self.score

        def get(self):
            return float(self.score)

    class Signal_Loitering:
        def __init__(self):
            self.first_seen  = time.time()
            self.pos_history = deque(maxlen=300)
            self.score       = 0.0

        def update(self, cx, cy):
            self.pos_history.append((cx, cy))
            dur = time.time() - self.first_seen
            ts  = min(
                dur/CFG['loiter_seconds'], 1.0
            )
            as_ = 0.0
            if len(self.pos_history) >= 30:
                pts = list(self.pos_history)
                xs  = [p[0] for p in pts[-60:]]
                ys  = [p[1] for p in pts[-60:]]
                area = (max(xs)-min(xs)) * \
                       (max(ys)-min(ys))
                if area < 8000:
                    as_ = 1.0
                elif area < 25000:
                    as_ = 0.6
                elif area < 60000:
                    as_ = 0.3
            c = ts*0.5 + as_*0.5
            self.score = 0.1*c+0.9*self.score

        def get(self):
            return float(min(self.score, 1.0))

    class Signal_SuddenMovement:
        def __init__(self):
            self.wrist_hist  = deque(maxlen=20)
            self.center_hist = deque(maxlen=20)
            self.spikes      = 0
            self.score       = 0.0

        def update(self, cx, cy,
                   lwy, rwy, lwc, rwc):
            self.center_hist.append(
                (cx, cy, time.time())
            )
            wy = None
            if lwc>0.3 and rwc>0.3:
                wy = (lwy+rwy)/2
            elif lwc>0.3:
                wy = lwy
            elif rwc>0.3:
                wy = rwy
            if wy:
                self.wrist_hist.append(wy)
            bv = wv = 0.0
            if len(self.center_hist) >= 4:
                ch = list(self.center_hist)
                dx = ch[-1][0]-ch[-4][0]
                dy = ch[-1][1]-ch[-4][1]
                dt = ch[-1][2]-ch[-4][2]
                bv = np.sqrt(dx*dx+dy*dy) / \
                     (dt*100+1e-6)
            if len(self.wrist_hist) >= 4:
                wh = list(self.wrist_hist)
                wv = abs(wh[-1]-wh[-4])/4.0
            if bv > 18 or wv > 22:
                self.spikes = min(self.spikes+3,30)
            else:
                self.spikes = max(self.spikes-1,0)
            sud = min(
                (bv/25)*0.4+(wv/30)*0.3+
                (self.spikes/30)*0.3,
                1.0
            )
            self.score = 0.45*sud+0.55*self.score

        def get(self):
            return float(self.score)

    class Signal_Following:
        def __init__(self):
            self.score = 0.0

        def update(self, mx, my, others):
            if not others:
                self.score = max(
                    0, self.score-0.02
                )
                return
            md = min(
                np.sqrt((mx-ox)**2+(my-oy)**2)
                for ox,oy in others
            )
            lim = CFG['follow_dist_px']
            if md < lim:
                self.score = min(
                    self.score+0.04, 1.0
                )
            else:
                self.score = max(
                    self.score-0.02, 0.0
                )

        def get(self):
            return float(self.score)

    # ── Person State ───────────────────────────
    class PersonState:
        def __init__(self, tid):
            self.tid           = tid
            self.first_seen    = time.time()
            self.last_seen     = time.time()
            self.name          = None
            self.category      = "stranger"
            self.face_conf     = 0.0
            self.emotion       = "Neutral"
            self.emotion_threat = 0.0
            self.sig_nervous   = Signal_NervousWalk()
            self.sig_looking   = Signal_LookingAround()
            self.sig_hiding    = Signal_HidingFace()
            self.sig_loiter    = Signal_Loitering()
            self.sig_sudden    = Signal_SuddenMovement()
            self.sig_following = Signal_Following()
            self.distance      = 99.0
            self.dist_hist     = deque(maxlen=8)
            self.threat_score  = 0.0
            self.last_alert    = 0.0

        def compute(self):
            sigs = {
                'nervous':  self.sig_nervous.get(),
                'looking':  self.sig_looking.get(),
                'hiding':   self.sig_hiding.get(),
                'loiter':   self.sig_loiter.get(),
                'sudden':   self.sig_sudden.get(),
                'following':self.sig_following.get(),
                'emotion':  self.emotion_threat,
            }
            W = {
                'nervous':0.12,'looking':0.18,
                'hiding':0.20, 'loiter':0.12,
                'sudden':0.18, 'following':0.10,
                'emotion':0.10,
            }
            base   = sum(sigs[k]*W[k] for k in sigs)
            active = sum(
                1 for k in sigs if sigs[k] > 0.35
            )
            bonus  = (
                0.25 if active >= 4 else
                0.15 if active >= 3 else
                0.08 if active >= 2 else 0.0
            )
            combined = min(base+bonus, 1.0)
            mods = {
                'whitelist':0.10,'routine':0.70,
                'blacklist':1.60,'stranger':1.00,
            }
            mod = mods.get(self.category, 1.0)
            if self.distance < CFG['critical_dist_m']:
                combined += 0.18
            elif self.distance < CFG['safe_dist_m']:
                combined += 0.08
            final = float(min(combined*mod, 1.0))
            self.threat_score = (
                0.25*final + 0.75*self.threat_score
            )
            behaviors = []
            if sigs['nervous']   > 0.30:
                behaviors.append("Nervous Walk")
            if sigs['looking']   > 0.30:
                behaviors.append("Looking Around")
            if sigs['hiding']    > 0.30:
                behaviors.append("Hiding Face")
            if sigs['loiter']    > 0.35:
                behaviors.append("Loitering")
            if sigs['sudden']    > 0.35:
                behaviors.append("Sudden Move!")
            if sigs['following'] > 0.40:
                behaviors.append("Following!")
            return self.threat_score, sigs, behaviors

    # ── Helpers ────────────────────────────────
    def csim(a, b):
        n = np.linalg.norm(a)*np.linalg.norm(b)
        return float(np.dot(a,b)/(n+1e-6))

    def smth(new, old, a=0.3):
        return a*new+(1-a)*old

    def gkp(kps, idx):
        k = kps[idx]
        return float(k[0]),float(k[1]),float(k[2])

    def dm(ph):
        if ph <= 0:
            return 99.0
        return (CFG['known_height_cm'] *
                CFG['focal_length']) / (ph*100.0)

    def scrop(frame, x1, y1, x2, y2):
        H,W = frame.shape[:2]
        x1=max(0,x1);y1=max(0,y1)
        x2=min(W,x2);y2=min(H,y2)
        if x2<=x1 or y2<=y1:
            return None
        return frame[y1:y2,x1:x2].copy()

    def get_threat_info(score, cat):
        if cat == 'whitelist':
            return "TRUSTED",  (0,220,100)
        if cat == 'blacklist':
            return "BLACKLIST",(0,0,200)
        if score >= CFG['critical_threshold']:
            return "CRITICAL", (0,0,255)
        elif score >= CFG['high_threshold']:
            return "HIGH",     (0,50,255)
        elif score >= CFG['medium_threshold']:
            return "MEDIUM",   (0,140,255)
        elif score >= CFG['watch_threshold']:
            return "WATCH",    (0,210,190)
        return "SAFE",         (0,255,80)

    # ── Alert System ───────────────────────────
    alert_log  = []
    tts_lock   = threading.Lock()

    def speak_async(text):
        def _r():
            with tts_lock:
                try:
                    tts_engine.say(text)
                    tts_engine.runAndWait()
                except:
                    pass
        threading.Thread(
            target=_r, daemon=True
        ).start()

    def trigger_alert(frame, state, label, behs):
        now = time.time()
        if now-state.last_alert < CFG['alert_cooldown']:
            return
        state.last_alert = now
        name = state.name or f"Unknown #{state.tid}"
        ts   = datetime.now().strftime("%H:%M:%S")
        print(f"\n🚨 [{ts}] {label} | "
              f"{name} | "
              f"{state.threat_score*100:.1f}%")

        # Snapshot
        tf    = datetime.now().strftime("%Y%m%d_%H%M%S")
        spath = os.path.join(
            CFG['snapshot_dir'],
            f"{label}_{tf}.jpg"
        )
        cv2.imwrite(spath, frame)

        # Log entry
        entry = {
            'time':      ts,
            'label':     label,
            'name':      name,
            'score':     state.threat_score,
            'emotion':   state.emotion,
            'dist':      state.distance,
            'behaviors': behs[:3],
        }
        alert_log.append(entry)
        if len(alert_log) > 50:
            alert_log.pop(0)

        # Push to dashboard
        if DASHBOARD_AVAILABLE:
            with state_lock:
                dashboard_state[
                    'alert_log'
                ].appendleft(entry)

        # Voice
        voices = {
            "CRITICAL": (
                "Critical threat detected! "
                "Security alert activated!"
            ),
            "HIGH": (
                "Warning! High risk behavior. "
                "Security notified."
            ),
            "MEDIUM": (
                "Caution! Suspicious behavior. "
                "You are being monitored."
            ),
            "WATCH":
                "This area is under surveillance.",
            "BLACKLIST": (
                "Alert! Known threat detected!"
            ),
        }
        msg = voices.get(label, "")
        if msg:
            speak_async(msg)

    # ── Draw ───────────────────────────────────
    def draw_frame(frame, state,
                   x1,y1,x2,y2,
                   sigs, behs, fc):
        tl, tc = get_threat_info(
            state.threat_score, state.category
        )
        cv2.rectangle(frame,(x1,y1),(x2,y2),tc,2)
        name = state.name or "STRANGER"
        hdr  = f"{name}  [{tl}]  " \
               f"{state.threat_score*100:.0f}%"
        hw   = max(len(hdr)*10, x2-x1)
        cv2.rectangle(frame,
                      (x1,y1-44),(x1+hw,y1),
                      tc,-1)
        cv2.putText(frame, hdr,
                    (x1+4,y1-24),
                    cv2.FONT_HERSHEY_SIMPLEX,
                    0.55,(255,255,255),2)

        # Behavior tags
        if behs:
            btxt = " • ".join(behs[:3])
            cv2.rectangle(frame,
                          (x1,y2+1),(x2,y2+20),
                          (15,15,15),-1)
            cv2.putText(frame, btxt,
                        (x1+4,y2+14),
                        cv2.FONT_HERSHEY_SIMPLEX,
                        0.35,(255,200,0),1)

        # Score bars
        by  = y2 + 24
        bw  = x2 - x1
        items = [
            ("NERVOUS", sigs['nervous'],  (100,150,255)),
            ("LOOKING", sigs['looking'],  (0,200,255)),
            ("HIDING",  sigs['hiding'],   (50,100,255)),
            ("LOITER",  sigs['loiter'],   (150,50,255)),
            ("SUDDEN",  sigs['sudden'],   (0,100,255)),
            ("FOLLOW",  sigs['following'],(200,100,255)),
            ("EMOTION", sigs['emotion'],  (0,140,255)),
            ("THREAT",  state.threat_score, tc),
        ]
        for i,(lbl,val,col) in enumerate(items):
            y = by + i*14
            cv2.putText(frame, lbl,
                        (x1,y+10),
                        cv2.FONT_HERSHEY_SIMPLEX,
                        0.30,(140,140,140),1)
            cv2.rectangle(frame,
                          (x1+52,y),(x2,y+11),
                          (20,20,20),-1)
            fill = int(val*(bw-52))
            if fill > 0:
                cv2.rectangle(frame,
                              (x1+52,y),
                              (x1+52+fill,y+11),
                              col,-1)
            cv2.putText(frame,
                        f"{val*100:.0f}",
                        (x2-22,y+10),
                        cv2.FONT_HERSHEY_SIMPLEX,
                        0.30,(200,200,200),1)

        # Distance
        dy2 = by+len(items)*14+12
        if state.distance < CFG['critical_dist_m']:
            dc=(0,0,255)
            dt=f"⚠ {state.distance:.1f}m CRITICAL"
        elif state.distance < CFG['safe_dist_m']:
            dc=(0,165,255)
            dt=f"! {state.distance:.1f}m ALERT"
        else:
            dc=(0,255,80)
            dt=f"✓ {state.distance:.1f}m SAFE"
        cv2.putText(frame,dt,(x1,dy2),
                    cv2.FONT_HERSHEY_SIMPLEX,
                    0.46,dc,2)
        cv2.putText(frame,
                    f"Emo:{state.emotion}  "
                    f"In:{int(time.time()-state.first_seen)}s",
                    (x1,dy2+16),
                    cv2.FONT_HERSHEY_SIMPLEX,
                    0.35,(150,150,150),1)

        if (state.threat_score >=
                CFG['critical_threshold']
                and fc%14 < 7):
            cv2.rectangle(frame,
                          (x1-4,y1-48),
                          (x2+4,y2+4),
                          (0,0,255),4)

    # ── Main Loop ──────────────────────────────
    person_states = {}
    fps_buf       = deque(maxlen=30)
    fps_disp      = 0.0
    frame_count   = 0

    cap   = cv2.VideoCapture(0)
    W_CAP = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    H_CAP = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))

    print("\n✅ ProVisionGuard AI is LIVE!")
    print("   Q=Quit  R=Reset  S=Snapshot")
    if DASHBOARD_AVAILABLE:
        print("   🌐 Dashboard: http://localhost:5000")
    print("=" * 55)

    while True:
        ret, frame = cap.read()
        if not ret:
            break

        t0           = time.time()
        frame_count += 1
        H_F,W_F      = frame.shape[:2]
        active_ids   = []

        det_res  = yolo_det.track(
            frame, persist=True,
            classes=[0], verbose=False, conf=0.45
        )
        pose_res = yolo_pose.track(
            frame, persist=True,
            verbose=False, conf=0.45
        )

        pose_map = {}
        if (pose_res and
                pose_res[0].keypoints is not None
                and pose_res[0].boxes is not None):
            for i, kps in enumerate(
                pose_res[0].keypoints.data
            ):
                pb  = pose_res[0].boxes
                pid = (int(pb.id[i])
                       if pb.id is not None else i)
                pose_map[pid] = kps

        all_centers = []
        if (det_res and
                det_res[0].boxes is not None):
            for box in det_res[0].boxes:
                bx = box.xyxy[0].cpu().numpy()
                all_centers.append((
                    int((bx[0]+bx[2])/2),
                    int((bx[1]+bx[3])/2)
                ))

        dashboard_persons = {}

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

                s.dist_hist.append(dm(y2-y1))
                s.distance = float(
                    np.median(s.dist_hist)
                )

                # Face recognition
                if frame_count % CFG['face_every_n'] == 0:
                    crop = scrop(frame,x1,y1,x2,y2)
                    if crop is not None:
                        faces = face_app.get(crop)
                        if faces:
                            emb = faces[0].embedding
                            best_n  = None
                            best_c  = 'stranger'
                            best_sc = 0.0
                            for nm,dt in known_faces.items():
                                sim = csim(emb,dt['emb'])
                                if sim > best_sc:
                                    best_sc=sim
                                    best_n=nm
                                    best_c=dt['category']
                            if best_sc >= CFG['face_threshold']:
                                s.name     = best_n
                                s.category = best_c
                                s.face_conf= best_sc

                # Emotion
                if frame_count % CFG['emotion_every_n'] == 0:
                    crop = scrop(frame,x1,y1,x2,y2)
                    if crop is not None and crop.size>0:
                        try:
                            import cv2 as _cv2
                            rgb = _cv2.cvtColor(
                                crop,
                                _cv2.COLOR_BGR2RGB
                            )
                            emo,sc = emo_model.predict_emotions(
                                rgb,logits=False
                            )
                            lbls = [
                                'Anger','Contempt',
                                'Disgust','Fear',
                                'Happiness','Neutral',
                                'Sadness','Surprise'
                            ]
                            wts = {
                                'Anger':0.95,
                                'Disgust':0.70,
                                'Fear':0.65,
                                'Contempt':0.60,
                                'Surprise':0.35,
                                'Sadness':0.20,
                                'Neutral':0.05,
                                'Happiness':0.0
                            }
                            sd = dict(zip(lbls,sc))
                            et = min(sum(
                                sd.get(e,0)*w
                                for e,w in wts.items()
                            ),1.0)
                            s.emotion = emo
                            s.emotion_threat = smth(
                                float(et),
                                s.emotion_threat,0.4
                            )
                        except:
                            pass

                # Pose signals
                kps = pose_map.get(tid)
                fd  = (s.name is not None or
                       s.face_conf > 0.3)
                if kps is not None:
                    nx,ny,nc   = gkp(kps,0)
                    lsx,lsy,lsc= gkp(kps,5)
                    rsx,rsy,rsc= gkp(kps,6)
                    lwx,lwy,lwc= gkp(kps,9)
                    rwx,rwy,rwc= gkp(kps,10)
                    lex,ley,lec= gkp(kps,3)
                    rex,rey,rec= gkp(kps,4)
                    s.sig_nervous.update(cx,cy)
                    s.sig_looking.update(
                        nx,nc,lex,lec,rex,rec,W_F
                    )
                    s.sig_hiding.update(
                        fd,nc,ny,y1,y2
                    )
                    s.sig_sudden.update(
                        cx,cy,lwy,rwy,lwc,rwc
                    )
                else:
                    s.sig_nervous.update(cx,cy)
                    s.sig_hiding.update(
                        fd,0.0,0.0,y1,y2
                    )
                    s.sig_sudden.update(
                        cx,cy,0.0,0.0,0.0,0.0
                    )

                s.sig_loiter.update(cx,cy)
                others = [
                    c for j,c in
                    enumerate(all_centers) if j!=i
                ]
                s.sig_following.update(
                    cx,cy,others
                )

                score,sigs,behs = s.compute()
                tl,_ = get_threat_info(
                    s.threat_score, s.category
                )

                if (tl in [
                    "CRITICAL","HIGH",
                    "MEDIUM","BLACKLIST"
                ] and s.category != 'whitelist'):
                    trigger_alert(
                        frame,s,tl,behs
                    )

                draw_frame(
                    frame,s,x1,y1,x2,y2,
                    sigs,behs,frame_count
                )

                # Dashboard data
                dashboard_persons[str(tid)] = {
                    'name':         s.name,
                    'category':     s.category,
                    'threat_score': s.threat_score,
                    'threat_label': tl,
                    'emotion':      s.emotion,
                    'distance':     s.distance,
                    'behaviors':    behs,
                    'signals':      sigs,
                }

        # Cleanup
        for tid in list(person_states.keys()):
            if tid not in active_ids:
                if (time.time() -
                        person_states[tid].last_seen > 3):
                    del person_states[tid]

        # FPS
        fps_buf.append(time.time()-t0)
        if len(fps_buf)==30:
            fps_disp = 1.0/(np.mean(fps_buf)+1e-6)

        # HUD
        cv2.rectangle(frame,(0,0),(W_F,42),
                      (10,10,10),-1)
        cv2.putText(frame,"ProVisionGuard AI",
                    (10,28),
                    cv2.FONT_HERSHEY_SIMPLEX,
                    0.85,(255,215,0),2)
        ts = datetime.now().strftime("%H:%M:%S")
        cv2.putText(frame,
                    f"Persons:{len(active_ids)}"
                    f"  FPS:{fps_disp:.1f}"
                    f"  Alerts:{len(alert_log)}"
                    f"  {ts}",
                    (230,27),
                    cv2.FONT_HERSHEY_SIMPLEX,
                    0.48,(150,150,150),1)

        # Push to dashboard
        if DASHBOARD_AVAILABLE:
            with state_lock:
                dashboard_state['fps'] = fps_disp
                dashboard_state['persons'] = (
                    dashboard_persons
                )
                if frame is not None:
                    import base64
                    _,buf = cv2.imencode(
                        '.jpg',frame,
                        [cv2.IMWRITE_JPEG_QUALITY,72]
                    )
                    dashboard_state['frame_b64'] = (
                        base64.b64encode(
                            buf
                        ).decode('utf-8')
                    )

        cv2.imshow("ProVisionGuard AI", frame)
        key = cv2.waitKey(1) & 0xFF
        if key == ord('q'):
            break
        elif key == ord('r'):
            person_states.clear()
            alert_log.clear()
            print("🔄 Reset!")
        elif key == ord('s'):
            tf = datetime.now().strftime(
                "%Y%m%d_%H%M%S"
            )
            p  = os.path.join(
                CFG['snapshot_dir'],
                f"manual_{tf}.jpg"
            )
            cv2.imwrite(p,frame)
            print(f"📸 Saved: {p}")

    cap.release()
    cv2.destroyAllWindows()
    print(f"\n✅ Shutdown.")
    print(f"   Alerts    : {len(alert_log)}")
    print(f"   Snapshots : {CFG['snapshot_dir']}/")

# ── Entry Point ───────────────────────────────────
if __name__ == '__main__':
    # Start dashboard in background thread
    dash_thread = threading.Thread(
        target=start_dashboard, daemon=True
    )
    dash_thread.start()
    time.sleep(2)  # Wait for dashboard to start

    # Start main camera system
    start_camera()