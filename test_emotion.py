import cv2
import numpy as np
from hsemotion_onnx.facial_emotions import HSEmotionRecognizer

# Load model
print("🔄 Loading Emotion AI Model...")
recognizer = HSEmotionRecognizer(model_name='enet_b0_8_best_afew')
print("✅ Model Loaded!")

# Face detector
face_cascade = cv2.CascadeClassifier(
    cv2.data.haarcascades + 'haarcascade_frontalface_default.xml'
)

cap = cv2.VideoCapture(0)
frame_count = 0

current_emotion  = "Analyzing..."
current_threat   = "SAFE"
threat_color     = (0, 255, 0)
all_scores       = {}

print("✅ AI Emotion Detection Started! Press Q to quit")

# Threat mapping
THREAT_MAP = {
    'Anger':     ('🚨 HIGH THREAT',    (0, 0, 255)),
    'Disgust':   ('⚠️ MEDIUM THREAT', (0, 100, 255)),
    'Fear':      ('⚠️ MEDIUM THREAT', (0, 165, 255)),
    'Sadness':   ('👀 WATCH',          (0, 200, 200)),
    'Surprise':  ('👀 WATCH',          (0, 220, 220)),
    'Contempt':  ('⚠️ MEDIUM THREAT', (0, 140, 255)),
    'Neutral':   ('✅ SAFE',           (0, 255, 0)),
    'Happiness': ('✅ SAFE',           (0, 255, 100)),
}

while True:
    ret, frame = cap.read()
    if not ret:
        break

    frame_count += 1
    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)

    # Face detect every frame
    faces = face_cascade.detectMultiScale(
        gray, scaleFactor=1.1,
        minNeighbors=5, minSize=(60, 60)
    )

    for (x, y, w, h) in faces:
        # Analyze every 5th frame
        if frame_count % 5 == 0:
            face_crop = frame[y:y+h, x:x+w]
            face_rgb  = cv2.cvtColor(face_crop, cv2.COLOR_BGR2RGB)

            try:
                emotion, scores = recognizer.predict_emotions(
                    face_rgb, logits=False
                )
                current_emotion = emotion
                all_scores      = dict(zip(
                    ['Anger','Contempt','Disgust',
                     'Fear','Happiness','Neutral',
                     'Sadness','Surprise'],
                    scores
                ))
                threat_text, threat_color = THREAT_MAP.get(
                    emotion, ('UNKNOWN', (255,255,255))
                )
                current_threat = threat_text

            except Exception as e:
                pass

        # Box color based on threat
        _, box_color = THREAT_MAP.get(
            current_emotion, ('', (255,255,255))
        )

        # Face bounding box
        cv2.rectangle(frame,
                      (x, y), (x+w, y+h),
                      box_color, 2)

        # Emotion label on face
        cv2.rectangle(frame,
                      (x, y-32), (x+w, y),
                      box_color, -1)
        cv2.putText(frame,
                    current_emotion,
                    (x+5, y-10),
                    cv2.FONT_HERSHEY_SIMPLEX,
                    0.6, (255,255,255), 2)

    # ── HUD Panel ─────────────────────────────────
    cv2.rectangle(frame, (0, 0), (490, 290), (15,15,15), -1)
    cv2.line(frame, (0, 290), (490, 290), (50,50,50), 1)

    # Title
    cv2.putText(frame, "ProVisionGuard AI  |  Emotion Engine",
                (10, 25), cv2.FONT_HERSHEY_SIMPLEX,
                0.65, (255, 215, 0), 2)

    cv2.line(frame, (10, 33), (480, 33), (50,50,50), 1)

    # Current emotion + threat
    cv2.putText(frame, f"Emotion : {current_emotion}",
                (10, 58), cv2.FONT_HERSHEY_SIMPLEX,
                0.65, (255,255,255), 2)

    cv2.putText(frame, f"Status  : {current_threat}",
                (10, 85), cv2.FONT_HERSHEY_SIMPLEX,
                0.65, threat_color, 2)

    cv2.putText(frame, f"Faces   : {len(faces)}",
                (10, 108), cv2.FONT_HERSHEY_SIMPLEX,
                0.5, (150,150,150), 1)

    # Emotion breakdown bars
    if all_scores:
        cv2.putText(frame, "Emotion Breakdown:",
                    (10, 132),
                    cv2.FONT_HERSHEY_SIMPLEX,
                    0.48, (150,150,150), 1)

        bar_order  = ['Anger','Fear','Disgust',
                      'Happiness','Neutral','Sadness','Surprise']
        bar_colors = [
            (0,0,255),(0,165,255),(0,100,255),
            (0,255,100),(200,200,200),(0,200,200),(0,220,220)
        ]

        for i, (emo, col) in enumerate(zip(bar_order, bar_colors)):
            score = all_scores.get(emo, 0) * 100
            bar_w = int((score / 100) * 180)
            y_pos = 148 + i * 22

            # Label + score
            cv2.putText(frame,
                        f"{emo[:8]:8s} {score:5.1f}%",
                        (10, y_pos + 11),
                        cv2.FONT_HERSHEY_SIMPLEX,
                        0.42, (200,200,200), 1)

            # Bar bg
            cv2.rectangle(frame,
                          (130, y_pos),
                          (310, y_pos+14),
                          (40,40,40), -1)

            # Bar fill
            if bar_w > 0:
                cv2.rectangle(frame,
                              (130, y_pos),
                              (130+bar_w, y_pos+14),
                              col, -1)

    cv2.imshow("ProVisionGuard AI - Emotion Engine", frame)

    if cv2.waitKey(1) & 0xFF == ord('q'):
        break

cap.release()
cv2.destroyAllWindows()
print("✅ Done!")