import cv2
import numpy as np
from ultralytics import YOLO

# ──────────────────────────────────────────────────
# ⭐ Calibration number இங்க paste பண்ணுங்க!
# calibrate_camera.py run பண்ணி கிடைச்ச number
FOCAL_LENGTH   = 414.12  # ← உங்க number இங்க வரும்
KNOWN_HEIGHT   = 170.0   # cm average person height
SAFE_DIST      = 2.0     # meters
CRITICAL_DIST  = 1.0     # meters
# ──────────────────────────────────────────────────

print("🔄 Loading YOLO Model...")
yolo  = YOLO('yolo11n.pt')
print("✅ Model Loaded!")

cap   = cv2.VideoCapture(0)
W_CAP = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
H_CAP = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))

# Per person distance history (smoothing)
dist_history = {}
frame_count  = 0

def smooth_distance(tid, new_dist):
    """Smooth distance to avoid flickering."""
    if tid not in dist_history:
        dist_history[tid] = []
    dist_history[tid].append(new_dist)
    if len(dist_history[tid]) > 8:
        dist_history[tid].pop(0)
    return float(np.median(dist_history[tid]))

def get_distance(px_height):
    """
    Physics formula:
    Distance = (Real Height × Focal Length) / Pixel Height
    """
    if px_height <= 0:
        return 99.0
    dist_cm = (KNOWN_HEIGHT * FOCAL_LENGTH) / px_height
    return dist_cm / 100.0  # convert to meters

def draw_distance_bar(frame, x1, y2, x2,
                      distance, color):
    """Draw proximity bar below bounding box."""
    bar_w    = x2 - x1
    # Closer = more filled
    fill_pct = max(0.0, min(1.0,
        1.0 - (distance / (SAFE_DIST * 1.5))
    ))
    fill_w   = int(fill_pct * bar_w)

    # Background
    cv2.rectangle(frame,
                  (x1, y2+3),
                  (x2, y2+13),
                  (30,30,30), -1)
    # Fill
    if fill_w > 0:
        cv2.rectangle(frame,
                      (x1, y2+3),
                      (x1+fill_w, y2+13),
                      color, -1)
    # Label
    cv2.putText(frame,
                "PROXIMITY",
                (x1, y2+23),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.35, (120,120,120), 1)

def draw_radar(frame, persons_info):
    """
    Mini radar showing person distances.
    """
    radar_x = W_CAP - 150
    radar_y = H_CAP - 150
    radar_r = 70

    # Background circle
    cv2.circle(frame,
               (radar_x, radar_y),
               radar_r, (20,20,20), -1)
    cv2.circle(frame,
               (radar_x, radar_y),
               radar_r, (50,50,50), 1)

    # Distance rings
    for r_pct in [0.33, 0.66, 1.0]:
        cv2.circle(frame,
                   (radar_x, radar_y),
                   int(radar_r * r_pct),
                   (40,40,40), 1)

    # Labels
    cv2.putText(frame, "1m",
                (radar_x+3,
                 radar_y - int(radar_r*0.33) + 4),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.3, (80,80,80), 1)
    cv2.putText(frame, "2m",
                (radar_x+3,
                 radar_y - int(radar_r*0.66) + 4),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.3, (80,80,80), 1)
    cv2.putText(frame, "3m",
                (radar_x+3,
                 radar_y - int(radar_r*1.0) + 4),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.3, (80,80,80), 1)

    # Camera icon (center)
    cv2.circle(frame,
               (radar_x, radar_y),
               5, (255,215,0), -1)
    cv2.putText(frame, "CAM",
                (radar_x-13, radar_y+14),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.3, (255,215,0), 1)

    # Plot each person on radar
    for p in persons_info:
        dist  = p['distance']
        tid   = p['tid']
        col   = p['color']

        # Map distance to radar pixels
        # 0m → center, 3m → edge
        r_px  = min(int((dist / 3.0) * radar_r),
                    radar_r - 5)

        # Approximate angle from bbox center
        bx    = (p['x1'] + p['x2']) // 2
        angle = ((bx / W_CAP) - 0.5) * 1.2

        px = radar_x + int(r_px * np.sin(angle))
        py = radar_y - int(r_px * np.cos(angle))

        cv2.circle(frame, (px, py), 7, col, -1)
        cv2.putText(frame,
                    f"{tid}",
                    (px+5, py-5),
                    cv2.FONT_HERSHEY_SIMPLEX,
                    0.35, (255,255,255), 1)

    # Radar title
    cv2.putText(frame, "RADAR",
                (radar_x-18,
                 radar_y + radar_r + 14),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.4, (150,150,150), 1)

print("✅ Depth Detection Started! Press Q to quit")
print(f"   Safe Distance    : {SAFE_DIST}m")
print(f"   Critical Distance: {CRITICAL_DIST}m")
print(f"   Focal Length     : {FOCAL_LENGTH}")

while True:
    ret, frame = cap.read()
    if not ret:
        break

    frame_count += 1

    results = yolo.track(
        frame,
        persist=True,
        classes=[0],
        verbose=False,
        conf=0.45
    )

    persons_info = []
    active_ids   = []

    if (results and
            results[0].boxes is not None):

        boxes = results[0].boxes

        for i, box in enumerate(boxes):
            x1,y1,x2,y2 = [
                int(v) for v in
                box.xyxy[0].cpu().numpy()
            ]
            tid = int(box.id[0]) \
                if box.id is not None else i

            active_ids.append(tid)

            # Calculate distance
            px_height    = y2 - y1
            raw_dist     = get_distance(px_height)
            distance     = smooth_distance(
                tid, raw_dist
            )

            # Status
            if distance < CRITICAL_DIST:
                status = "⚠ TOO CLOSE!"
                color  = (0, 0, 255)

            elif distance < SAFE_DIST:
                status = "PROXIMITY ALERT"
                color  = (0, 165, 255)

            else:
                status = "SAFE"
                color  = (0, 255, 0)

            persons_info.append({
                'tid': tid,
                'distance': distance,
                'status': status,
                'color': color,
                'x1': x1, 'y1': y1,
                'x2': x2, 'y2': y2,
            })

            # Bounding box
            cv2.rectangle(frame,
                          (x1,y1),(x2,y2),
                          color, 2)

            # Header label
            lbl   = f"ID:{tid}  {distance:.1f}m  {status}"
            lbl_w = len(lbl) * 10
            cv2.rectangle(frame,
                          (x1, y1-38),
                          (x1+lbl_w, y1),
                          color, -1)
            cv2.putText(frame, lbl,
                        (x1+4, y1-12),
                        cv2.FONT_HERSHEY_SIMPLEX,
                        0.58, (255,255,255), 2)

            # Distance bar
            draw_distance_bar(
                frame, x1, y2, x2,
                distance, color
            )

            # Alert flash for critical
            if (distance < CRITICAL_DIST and
                    frame_count % 15 < 8):
                cv2.rectangle(frame,
                              (x1-4, y1-4),
                              (x2+4, y2+4),
                              (0,0,255), 3)
                cv2.putText(frame,
                            "! CRITICAL !",
                            (x1, y2+40),
                            cv2.FONT_HERSHEY_SIMPLEX,
                            0.7, (0,0,255), 2)

    # Cleanup old histories
    for tid in list(dist_history.keys()):
        if tid not in active_ids:
            del dist_history[tid]

    # Draw radar
    draw_radar(frame, persons_info)

    # ── HUD ───────────────────────────────────────
    cv2.rectangle(frame, (0,0),(W_CAP, 42),
                  (12,12,12), -1)
    cv2.putText(frame,
                "ProVisionGuard AI  |  Depth Engine",
                (10,27),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.7, (255,215,0), 2)

    # Person list
    list_y = 60
    for p in persons_info:
        cv2.putText(
            frame,
            f"ID:{p['tid']}  →  "
            f"{p['distance']:.2f}m  "
            f"|  {p['status']}",
            (10, list_y),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.55, p['color'], 2
        )
        list_y += 25

    # Legend
    legends = [
        (f"> {SAFE_DIST}m   SAFE",       (0,255,0)),
        (f"< {SAFE_DIST}m   ALERT",      (0,165,255)),
        (f"< {CRITICAL_DIST}m   CRITICAL",(0,0,255)),
    ]
    leg_y = H_CAP - 70
    cv2.rectangle(frame,
                  (0, leg_y-15),
                  (200, H_CAP),
                  (12,12,12), -1)
    for txt, col in legends:
        cv2.putText(frame, txt,
                    (8, leg_y),
                    cv2.FONT_HERSHEY_SIMPLEX,
                    0.45, col, 1)
        leg_y += 20

    cv2.putText(frame,
                "Q = quit",
                (W_CAP-80, H_CAP-10),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.4, (80,80,80), 1)

    cv2.imshow(
        "ProVisionGuard AI - Depth Engine",
        frame
    )

    if cv2.waitKey(1) & 0xFF == ord('q'):
        break

cap.release()
cv2.destroyAllWindows()
print("✅ Done!")