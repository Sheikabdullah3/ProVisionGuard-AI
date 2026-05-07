import cv2
import numpy as np
import os
import insightface
from insightface.app import FaceAnalysis

# உங்க பேரு இங்க மாத்துங்க
YOUR_NAME = "Sheik Abdullah"

print("🔄 Loading face recognition model...")
app = FaceAnalysis(name='buffalo_l')
app.prepare(ctx_id=0, det_size=(640, 640))
print("✅ Model loaded!")

# Reference photos load பண்ணுங்க
ref_dir = f"data/known_faces/whitelist/{YOUR_NAME}"
ref_embeddings = []

print(f"🔄 Loading your face photos from {ref_dir}...")

for img_file in os.listdir(ref_dir):
    if img_file.endswith(('.jpg', '.jpeg', '.png')):
        img_path = os.path.join(ref_dir, img_file)
        img = cv2.imread(img_path)
        faces = app.get(img)
        if faces:
            ref_embeddings.append(faces[0].embedding)
            print(f"  ✅ {img_file} loaded!")
        else:
            print(f"  ⚠️ {img_file} - face not detected, skip!")

if not ref_embeddings:
    print("❌ No faces found! Photos retake பண்ணுங்க")
    exit()

# Average embedding
avg_embedding = np.mean(ref_embeddings, axis=0)
print(f"\n✅ {len(ref_embeddings)} photos loaded! Starting camera...\n")

# Camera test
cap = cv2.VideoCapture(0)

while True:
    ret, frame = cap.read()
    if not ret:
        break

    faces = app.get(frame)

    for face in faces:
        # Similarity calculate
        similarity = np.dot(avg_embedding, face.embedding) / (
            np.linalg.norm(avg_embedding) * np.linalg.norm(face.embedding)
        )

        bbox = face.bbox.astype(int)

        if similarity > 0.6:
            label = f"✅ WHITELIST: {YOUR_NAME} ({similarity:.2f})"
            color = (0, 255, 0)   # Green
            bg_color = (0, 100, 0)
        else:
            label = f"🚨 STRANGER ({similarity:.2f})"
            color = (0, 0, 255)   # Red
            bg_color = (0, 0, 100)

        # Box draw
        cv2.rectangle(frame,
                      (bbox[0], bbox[1]),
                      (bbox[2], bbox[3]),
                      color, 2)

        # Label background
        cv2.rectangle(frame,
                      (bbox[0], bbox[1] - 35),
                      (bbox[2], bbox[1]),
                      bg_color, -1)

        # Label text
        cv2.putText(frame, label,
                    (bbox[0] + 4, bbox[1] - 10),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 255, 255), 2)

    # HUD
    cv2.putText(frame, "ProVisionGuard AI - Face Recognition",
                (10, 30), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 255, 0), 2)
    cv2.putText(frame, f"Faces: {len(faces)}",
                (10, 60), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 255, 255), 2)
    cv2.putText(frame, "Press Q to quit",
                (10, 90), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (200, 200, 200), 1)

    cv2.imshow("Face Recognition - ProVisionGuard", frame)

    if cv2.waitKey(1) & 0xFF == ord('q'):
        break

cap.release()
cv2.destroyAllWindows()
print("Done!")