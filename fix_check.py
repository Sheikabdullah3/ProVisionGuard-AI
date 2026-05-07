"""
Quick diagnostic - run this first to find the problem
"""
import sys
print("="*50)
print("ProVisionGuard Diagnostic")
print("="*50)

# Test 1: OpenCV
try:
    import cv2
    cap = cv2.VideoCapture(0)
    ret, frame = cap.read()
    cap.release()
    if ret:
        print("✅ Camera OK")
    else:
        print("❌ Camera: opened but no frame")
except Exception as e:
    print(f"❌ Camera: {e}")

# Test 2: CUDA
try:
    from ultralytics import YOLO
    import torch
    print(f"✅ PyTorch: {torch.__version__}")
    print(f"✅ CUDA available: {torch.cuda.is_available()}")
    if torch.cuda.is_available():
        print(f"✅ GPU: {torch.cuda.get_device_name(0)}")
    else:
        print("⚠ CUDA not available - will use CPU")
except Exception as e:
    print(f"❌ YOLO/PyTorch: {e}")

# Test 3: Flask
try:
    import flask, flask_socketio
    print("✅ Flask + SocketIO OK")
except Exception as e:
    print(f"❌ Flask: {e}")

# Test 4: InsightFace
try:
    from insightface.app import FaceAnalysis
    print("✅ InsightFace OK")
except Exception as e:
    print(f"❌ InsightFace: {e}")

# Test 5: Emotion
try:
    from hsemotion_onnx.facial_emotions import HSEmotionRecognizer
    print("✅ HSEmotion OK")
except Exception as e:
    print(f"❌ HSEmotion: {e}")

# Test 6: ReportLab
try:
    from reportlab.lib.pagesizes import A4
    print("✅ ReportLab OK")
except Exception as e:
    print(f"⚠ ReportLab: {e} (pip install reportlab)")

# Test 7: EasyOCR
try:
    import easyocr
    print("✅ EasyOCR OK")
except Exception as e:
    print(f"⚠ EasyOCR: {e} (pip install easyocr)")

print("="*50)