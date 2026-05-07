from ultralytics import YOLO
import cv2

# First time internet தேவை — model auto download ஆகும் (~6MB)
model = YOLO("yolo11n.pt")

cap = cv2.VideoCapture(0)

print("✅ Detection started! Press Q to quit")

while True:
    ret, frame = cap.read()
    if not ret:
        break

    # Person detection + tracking
    results = model.track(frame, persist=True, classes=[0], verbose=False)

    # Draw boxes
    annotated = results[0].plot()

    # Person count
    person_count = len(results[0].boxes) if results[0].boxes else 0

    cv2.putText(annotated, f"Persons Detected: {person_count}", (10, 30),
                cv2.FONT_HERSHEY_SIMPLEX, 1, (0, 255, 0), 2)

    cv2.putText(annotated, "ProVisionGuard AI", (10, 65),
                cv2.FONT_HERSHEY_SIMPLEX, 0.8, (255, 255, 0), 2)

    cv2.imshow("Detection Test", annotated)

    if cv2.waitKey(1) & 0xFF == ord('q'):
        break

cap.release()
cv2.destroyAllWindows()
print("Done!")