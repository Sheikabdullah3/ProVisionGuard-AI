import cv2
import numpy as np
from ultralytics import YOLO

yolo  = YOLO('yolo11n.pt')
cap   = cv2.VideoCapture(0)
W_CAP = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
H_CAP = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))

KNOWN_DISTANCE = 200.0  # cm (2 meters)
KNOWN_HEIGHT   = 170.0  # cm (average person)
focal_length   = None
calibrated     = False

print("=" * 50)
print("CAMERA CALIBRATION")
print("=" * 50)
print("Step 1: Exactly 2 METERS தூரத்துல நில்லுங்க")
print("Step 2: Full body camera-ல தெரியணும்")
print("Step 3: SPACE press → calibrate!")
print("Step 4: Q → quit")
print("=" * 50)

while True:
    ret, frame = cap.read()
    if not ret:
        break

    results = yolo.track(
        frame,
        persist=True,
        classes=[0],
        verbose=False,
        conf=0.5
    )

    display = frame.copy()

    # 2 meter guide lines
    cx = W_CAP // 2
    cv2.line(display, (cx-100, 0),
             (cx-100, H_CAP), (0,255,255), 1)
    cv2.line(display, (cx+100, 0),
             (cx+100, H_CAP), (0,255,255), 1)
    cv2.putText(display,
                "Stand between these lines",
                (cx-130, H_CAP-20),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.5, (0,255,255), 1)

    if results and results[0].boxes is not None:
        boxes = results[0].boxes
        if len(boxes) > 0:
            box           = boxes.xyxy[0].cpu().numpy()
            x1,y1,x2,y2  = [int(v) for v in box]
            px_height     = y2 - y1

            cv2.rectangle(display,
                          (x1,y1),(x2,y2),
                          (0,255,255), 2)

            cv2.putText(display,
                        f"Pixel Height: {px_height}px",
                        (x1+4, y1-10),
                        cv2.FONT_HERSHEY_SIMPLEX,
                        0.65, (0,255,255), 2)

            if calibrated and focal_length:
                dist_cm = (KNOWN_HEIGHT * focal_length) \
                          / (px_height + 1e-6)
                dist_m  = dist_cm / 100.0

                if dist_m < 1.0:
                    col = (0, 0, 255)
                elif dist_m < 2.0:
                    col = (0, 165, 255)
                else:
                    col = (0, 255, 0)

                cv2.putText(display,
                            f"Distance: {dist_m:.2f}m",
                            (x1+4, y2+28),
                            cv2.FONT_HERSHEY_SIMPLEX,
                            0.9, col, 2)

    # HUD
    cv2.rectangle(display, (0,0),(W_CAP,45),
                  (12,12,12), -1)

    if not calibrated:
        cv2.putText(display,
                    "Stand EXACTLY 2m away → Press SPACE",
                    (10,30),
                    cv2.FONT_HERSHEY_SIMPLEX,
                    0.7, (255,215,0), 2)
    else:
        cv2.putText(display,
                    f"CALIBRATED! FL={focal_length:.1f} | Move to test distance!",
                    (10,30),
                    cv2.FONT_HERSHEY_SIMPLEX,
                    0.6, (0,255,0), 2)

    cv2.imshow("ProVisionGuard - Camera Calibration",
               display)

    key = cv2.waitKey(1) & 0xFF

    if key == ord(' '):
        if results and results[0].boxes is not None:
            boxes = results[0].boxes
            if len(boxes) > 0:
                box       = boxes.xyxy[0].cpu().numpy()
                px_height = int(box[3]) - int(box[1])

                focal_length = (
                    px_height * KNOWN_DISTANCE
                ) / KNOWN_HEIGHT

                calibrated = True

                print("\n" + "="*50)
                print("✅ CALIBRATION SUCCESS!")
                print(f"   Pixel Height @ 2m : {px_height}px")
                print(f"   Focal Length      : {focal_length:.2f}")
                print("="*50)
                print(f"\n⭐ SAVE THIS NUMBER:")
                print(f"   FOCAL_LENGTH = {focal_length:.2f}")
                print("="*50)
            else:
                print("❌ No person! Try again.")

    elif key == ord('q'):
        break

cap.release()
cv2.destroyAllWindows()