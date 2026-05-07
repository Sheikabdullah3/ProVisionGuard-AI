import cv2

cap = cv2.VideoCapture(0)

if not cap.isOpened():
    print("❌ Camera not found!")
    exit()

print("✅ Camera found! Press Q to quit")

while True:
    ret, frame = cap.read()
    if not ret:
        print("❌ Frame read failed!")
        break

    cv2.putText(frame, "ProVisionGuard AI - Camera OK!", (10, 30),
                cv2.FONT_HERSHEY_SIMPLEX, 1, (0, 255, 0), 2)

    cv2.imshow("Camera Test", frame)

    if cv2.waitKey(1) & 0xFF == ord('q'):
        break

cap.release()
cv2.destroyAllWindows()
print("Done!")