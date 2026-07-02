import cv2
import pylablib as pll
from pylablib.devices import IMAQdx
import time



print(IMAQdx.list_cameras())
# 2. Target your true Blackfly ID (e.g., 'cam1')
CAMERA_ID = "cam5" 

print(f"Connecting to machine vision camera '{CAMERA_ID}'...")
cam = IMAQdx.IMAQdxCamera(CAMERA_ID)

# Ensure raw readout is disabled for native Mono processing
cam.enable_raw_readout(False)
cam.start_acquisition()

# Tracking variables for FPS
prev_time = 0
fps = 0

print("Press 'q' inside the window to quit.")
try:
    while True:
        # Pull incoming frame from the NI hardware buffer
        frame = cam.read_newest_image()
        
        if frame is None:
            time.sleep(0.005)  # Prevent CPU pinning
            continue
            
        # 3. Shape Preparation:
        # Your Blackfly is Monochrome, but YOLO expects a 3-channel matrix.
        # We duplicate the mono channel across Blue, Green, and Red channels.
        color_frame = cv2.cvtColor(frame, cv2.COLOR_GRAY2BGR)

        
        # 6. Calculate real-time frame rate
        current_time = time.time()
        time_diff = current_time - prev_time
        if time_diff > 0:
            fps = 1.0 / time_diff
        prev_time = current_time

        # Format and render the FPS text string near the bottom
        fps_text = f"FPS: {fps:.1f}"
        height, width = color_frame.shape[:2]
        text_position = (20, height - 30)
        
        # Draw text (using green [0, 255, 0] since our frame is now BGR color space)
        cv2.putText(color_frame, fps_text, text_position, cv2.FONT_HERSHEY_SIMPLEX, 1.0, (0, 255, 0), 2, cv2.LINE_AA)

        # Render the final image window with detections and frame rate embedded
        cv2.imshow("Teledyne Blackfly - NI Stream", color_frame)
        
        if cv2.waitKey(1) & 0xFF == ord('q'):
            break

except Exception as e:
    print(f"An error occurred: {e}")

finally:
    # Release memory handles and hardware resources back to Windows
    cam.stop_acquisition()
    cam.close()
    cv2.destroyAllWindows()