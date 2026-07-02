import cv2
import pylablib as pll
from pylablib.devices import IMAQdx
import time

print("Available cameras:", IMAQdx.list_cameras())

# 1. Define your target Blackfly IDs
CAMERA_ID_1 = "cam5" 
CAMERA_ID_2 = "cam8"  # Replace with your actual second camera ID (e.g., 'cam1', 'cam2')

print(f"Connecting to Camera 1: '{CAMERA_ID_1}' and Camera 2: '{CAMERA_ID_2}'...")
cam1 = IMAQdx.IMAQdxCamera(CAMERA_ID_1)
cam2 = IMAQdx.IMAQdxCamera(CAMERA_ID_2)

# 2. Configure and start both cameras
cam1.enable_raw_readout(False)
cam1.start_acquisition()

cam2.enable_raw_readout(False)
cam2.start_acquisition()

# Tracking variables for FPS
prev_time = time.time()
fps = 0

print("Press 'q' inside any frame window to quit.")
try:
    while True:
        # 3. Pull incoming frames from BOTH NI hardware buffers
        frame1 = cam1.read_newest_image()
        frame2 = cam2.read_newest_image()
        
        # Guard clause: If either camera hasn't populated a frame yet, wait slightly
        if frame1 is None or frame2 is None:
            time.sleep(0.1)  # Prevent CPU pinning
            print("no frame received")
            continue
            
        # 4. Convert both mono channels to 3-channel BGR matrices for YOLO/OpenCV processing
        color_frame1 = cv2.cvtColor(frame1, cv2.COLOR_GRAY2BGR)
        color_frame2 = cv2.cvtColor(frame2, cv2.COLOR_GRAY2BGR)

        # 5. Calculate real-time frame rate of the processing loop
        current_time = time.time()
        time_diff = current_time - prev_time
        if time_diff > 0:
            fps = 1.0 / time_diff
        prev_time = current_time
        fps_text = f"FPS: {fps:.1f}"

        # 6. Overlay FPS text on both streams
        for img in [color_frame1, color_frame2]:
            height, width = img.shape[:2]
            cv2.putText(img, fps_text, (20, height - 30), cv2.FONT_HERSHEY_SIMPLEX, 1.0, (0, 255, 0), 2, cv2.LINE_AA)

        # 7. Render separate windows for each camera
        cv2.imshow("Teledyne Blackfly - Cam 1", color_frame1)
        cv2.imshow("Teledyne Blackfly - Cam 2", color_frame2)
        
        # ALTERNATIVE: Side-by-side display (Uncomment below if both cameras share identical resolution)
        # if color_frame1.shape == color_frame2.shape:
        #     combined_frame = cv2.hconcat([color_frame1, color_frame2])
        #     cv2.imshow("Dual Camera Stream", combined_frame)
        
        if cv2.waitKey(1) & 0xFF == ord('q'):
            break

except Exception as e:
    print(f"An error occurred: {e}")

finally:
    # 8. Ensure BOTH hardware handles are closed cleanly back to the OS
    print("\nClosing hardware connections...")
    try:
        cam1.stop_acquisition()
        cam1.close()
    except Exception as e:
        print(f"Error releasing Camera 1: {e}")
        
    try:
        cam2.stop_acquisition()
        cam2.close()
    except Exception as e:
        print(f"Error releasing Camera 2: {e}")
        
    cv2.destroyAllWindows()
    print("Resources released cleanly.")