import cv2
import os

# உங்க பேரு இங்க மாத்துங்க
YOUR_NAME = "Sheik Abdullah"

save_dir = f"data/known_faces/whitelist/{YOUR_NAME}"
os.makedirs(save_dir, exist_ok=True)

cap = cv2.VideoCapture(0)
photos_taken = 0
angles = [
    "1/5 - Look STRAIGHT at camera",
    "2/5 - Turn slightly LEFT",
    "3/5 - Turn slightly RIGHT",
    "4/5 - Tilt head UP slightly",
    "5/5 - NORMAL expression"
]

print("📸 Face Capture Started!")
print("SPACE key press பண்ண = Photo எடுக்கும்")
print("Q = Quit\n")

while photos_taken < 5:
    ret, frame = cap.read()
    if not ret:
        break

    # Instructions show பண்ணுங்க
    cv2.putText(frame, angles[photos_taken], (10, 30),
                cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 255, 0), 2)
    cv2.putText(frame, "Press SPACE to capture", (10, 65),
                cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 255, 0), 2)
    cv2.putText(frame, f"Photos taken: {photos_taken}/5", (10, 100),
                cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 255, 255), 2)

    cv2.imshow("Face Capture - ProVisionGuard", frame)

    key = cv2.waitKey(1) & 0xFF

    if key == ord(' '):
        path = f"{save_dir}/photo_{photos_taken + 1}.jpg"
        cv2.imwrite(path, frame)
        print(f"✅ Photo {photos_taken + 1}/5 saved!")
        photos_taken += 1

    elif key == ord('q'):
        break

cap.release()
cv2.destroyAllWindows()

if photos_taken == 5:
    print(f"\n🎉 Done! 5 photos saved in {save_dir}")
    print("Next: python test_face.py run பண்ணுங்க!")
else:
    print(f"\n⚠️ Only {photos_taken} photos taken. 5 வேணும்!")