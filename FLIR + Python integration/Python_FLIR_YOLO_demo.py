import cv2
import pylablib as pll
from pylablib.devices import IMAQdx
import time
from ultralytics import YOLO

# 1. Load the YOLO model (nano version is best for high real-time FPS)
model = YOLO("yolov8n.pt") 
print(IMAQdx.list_cameras())

# 2. Target your true Blackfly ID
CAMERA_ID = "cam9" 

print(f"Connecting to machine vision camera '{CAMERA_ID}'...")
cam = IMAQdx.IMAQdxCamera(CAMERA_ID)

# Enable raw row readout to pipe the native Bayer matrix directly to Python
cam.enable_raw_readout('rows')
cam.start_acquisition()

# Tracking variables for FPS
prev_time = 0
fps = 0

print("Streaming with YOLO Detection... Press 'q' inside the window to quit.")
try:
    while True:
        # Pull incoming frame from the NI hardware buffer
        frame = cam.read_newest_image()
        
        if frame is None:
            time.sleep(0.005)  # Prevent CPU pinning
            continue
            
        # Convert the raw Bayer matrix into standard BGR color space
        color_frame = cv2.cvtColor(frame, cv2.COLOR_BayerBG2BGR)

        # Run YOLO Inference on the native color frame
        results = model(color_frame, stream=True, verbose=False)
        
        # Extract bounding boxes and paint them onto our display frame
        for result in results:
            color_frame = result.plot()  # Modifies frame to include boxes, labels, and scores

        # --- NEW: Resize the display frame to 1080 x 720 ---
        color_frame = cv2.resize(color_frame, (1080, 720))

        # Calculate real-time frame rate
        current_time = time.time()
        time_diff = current_time - prev_time
        if time_diff > 0:
            fps = 1.0 / time_diff
        prev_time = current_time

        # Format and render the FPS text string near the bottom
        fps_text = f"FPS: {fps:.1f}"
        height, width = color_frame.shape[:2]
        text_position = (20, height - 30)
        
        # Draw text (using green [0, 255, 0])
        cv2.putText(color_frame, fps_text, text_position, cv2.FONT_HERSHEY_SIMPLEX, 1.0, (0, 255, 0), 2, cv2.LINE_AA)

        # Render the final image window with detections and frame rate embedded
        cv2.imshow("Teledyne Blackfly - NI Stream + YOLO", color_frame)
        
        if cv2.waitKey(1) & 0xFF == ord('q'):
            break

except Exception as e:
    print(f"An error occurred: {e}")

finally:
    # Release memory handles and hardware resources back to Windows
    cam.stop_acquisition()
    cam.close()
    cv2.destroyAllWindows()