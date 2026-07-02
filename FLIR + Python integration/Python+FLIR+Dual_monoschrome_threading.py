import cv2
import pylablib as pll
from pylablib.devices import IMAQdx
import time
import threading
import os
import tkinter as tk
from tkinter import ttk, messagebox

class CameraStream:
    def __init__(self, camera_id):
        self.camera_id = camera_id
        self.cam = IMAQdx.IMAQdxCamera(camera_id)
        self.cam.enable_raw_readout(False)
        self.frame = None
        self.running = False
        self.thread = None

    def start(self):
        self.cam.start_acquisition()
        self.running = True
        self.thread = threading.Thread(target=self._update, args=(), daemon=True)
        self.thread.start()
        return self

    def _update(self):
        while self.running:
            try:
                new_frame = self.cam.read_newest_image()
                if new_frame is not None:
                    self.frame = new_frame
                else:
                    time.sleep(0.002)
            except Exception:
                self.running = False

    def read(self):
        return self.frame

    def stop(self):
        self.running = False
        if self.thread:
            self.thread.join(timeout=0.5)
        try:
            self.cam.stop_acquisition()
            self.cam.close()
        except Exception:
            pass


class CameraControlPanel:
    def __init__(self, window):
        self.window = window
        self.window.title("Camera Control Panel")
        self.window.geometry("1000x180")  # Taller window profile to support the stacked row layout
        self.window.protocol("WM_DELETE_WINDOW", self.on_closing)
        
        # State variables
        self.cam1_stream = None
        self.cam2_stream = None
        self.is_streaming = False
        self.resolution_detected = False
        
        # Auto-save state variables
        self.is_auto_saving = False
        self.auto_save_job = None
        self.auto_save_interval = 1000
        
        self.frame_counter = 1
        
        # Configured Nested Directory Layout
        self.base_folder = "Frames"
        self.folder_cam1 = os.path.join(self.base_folder, "camera 1")
        self.folder_cam2 = os.path.join(self.base_folder, "camera 2")
        
        os.makedirs(self.folder_cam1, exist_ok=True)
        os.makedirs(self.folder_cam2, exist_ok=True)
        
        # Auto-detect available cameras
        try:
            self.available_cameras = [str(cam[0] if isinstance(cam, tuple) else cam) for cam in IMAQdx.list_cameras()]
        except Exception as e:
            self.available_cameras = []
            print(f"Error fetching camera list: {e}")

        self.setup_ui()

    def setup_ui(self):
        main_frame = ttk.Frame(self.window, padding=15)
        main_frame.pack(fill="both", expand=True)
        
        # --- ROW 0: Camera Selection Row ---
        ttk.Label(main_frame, text="Camera 1 ID:").grid(row=0, column=0, padx=5, pady=5, sticky="e")
        self.cam1_combo = ttk.Combobox(main_frame, values=self.available_cameras, width=12)
        self.cam1_combo.grid(row=0, column=1, padx=5, pady=5, sticky="w")
        if len(self.available_cameras) > 0: self.cam1_combo.current(0)
        
        ttk.Label(main_frame, text="Camera 2 ID:").grid(row=0, column=2, padx=5, pady=5, sticky="e")
        self.cam2_combo = ttk.Combobox(main_frame, values=self.available_cameras, width=12)
        self.cam2_combo.grid(row=0, column=3, padx=5, pady=5, sticky="w")
        if len(self.available_cameras) > 1: self.cam2_combo.current(1)
        elif len(self.available_cameras) > 0: self.cam2_combo.current(0)

        # Main Activation Button (Spans across the right action block columns)
        self.btn_toggle_feed = ttk.Button(main_frame, text="Start Live Feed", command=self.toggle_feed, width=15)
        self.btn_toggle_feed.grid(row=0, column=4, columnspan=2, padx=15, pady=5, sticky="ew")
        
        # --- ROW 1: Resolutions & Interval Configuration (Stacked Under IDs) ---
        ttk.Label(main_frame, text="Res 1:").grid(row=1, column=0, padx=5, pady=5, sticky="e")
        self.entry_res1 = ttk.Entry(main_frame, width=15, font=("Courier", 9))
        self.entry_res1.grid(row=1, column=1, padx=5, pady=5, sticky="w")
        self.set_entry_text(self.entry_res1, "Unknown")
        
        ttk.Label(main_frame, text="Res 2:").grid(row=1, column=2, padx=5, pady=5, sticky="e")
        self.entry_res2 = ttk.Entry(main_frame, width=15, font=("Courier", 9))
        self.entry_res2.grid(row=1, column=3, padx=5, pady=5, sticky="w")
        self.set_entry_text(self.entry_res2, "Unknown")
        
        ttk.Label(main_frame, text="Interval (ms):").grid(row=1, column=4, padx=5, pady=5, sticky="e")
        self.entry_interval = ttk.Entry(main_frame, width=12)
        self.entry_interval.insert(0, "1000")
        self.entry_interval.grid(row=1, column=5, padx=5, pady=5, sticky="w")

        # --- ROW 2: Frame Capturing Controls ---
        self.btn_toggle_auto = ttk.Button(main_frame, text="Start Auto Save", command=self.toggle_auto_save, state="disabled", width=15)
        self.btn_toggle_auto.grid(row=2, column=4, padx=5, pady=5, sticky="ew")
        
        self.btn_capture = ttk.Button(main_frame, text="Capture Frame (C)", command=lambda: self.capture_frames("MANUAL"), state="disabled", width=18)
        self.btn_capture.grid(row=2, column=5, padx=5, pady=5, sticky="ew")

        # --- ROW 3: Status Monitoring Footer ---
        self.status_lbl = ttk.Label(main_frame, text="Disconnected", foreground="red", font=("Helvetica", 10, "bold"))
        self.status_lbl.grid(row=3, column=0, columnspan=6, pady=8, sticky="w")

        # Global hotkey mapping for the manual C key
        self.window.bind('<KeyRelease-c>', lambda event: self.capture_frames("MANUAL"))
        self.window.bind('<KeyRelease-C>', lambda event: self.capture_frames("MANUAL"))

    def set_entry_text(self, entry_widget, text):
        entry_widget.config(state="normal")
        entry_widget.delete(0, tk.END)
        entry_widget.insert(0, text)
        entry_widget.config(state="readonly")

    def toggle_feed(self):
        if not self.is_streaming:
            cam1_id = self.cam1_combo.get()
            cam2_id = self.cam2_combo.get()
            
            if not cam1_id or not cam2_id:
                messagebox.showerror("Error", "Please pick valid IDs for both camera channels.")
                return
            if cam1_id == cam2_id:
                messagebox.showwarning("Warning", "Camera 1 and Camera 2 cannot share the same ID.")
                return
                
            try:
                self.status_lbl.config(text="Connecting to hardware...", foreground="orange")
                self.window.update()
                
                self.cam1_stream = CameraStream(cam1_id).start()
                self.cam2_stream = CameraStream(cam2_id).start()
                
                self.is_streaming = True
                self.resolution_detected = False
                self.btn_toggle_feed.config(text="Stop Live Feed")
                self.btn_capture.config(state="normal")
                self.btn_toggle_auto.config(state="normal")
                self.cam1_combo.config(state="disabled")
                self.cam2_combo.config(state="disabled")
                self.status_lbl.config(text=f"Streaming Active", foreground="green")
                
                self.update_loop()
                
            except Exception as e:
                self.stop_hardware()
                messagebox.showerror("Hardware Error", f"Initialization crash:\n{e}")
        else:
            self.stop_hardware()

    def stop_hardware(self):
        if self.is_auto_saving:
            self.stop_auto_save()

        self.is_streaming = False
        self.btn_toggle_feed.config(text="Start Live Feed")
        self.btn_capture.config(state="disabled")
        self.btn_toggle_auto.config(state="disabled")
        self.cam1_combo.config(state="normal")
        self.cam2_combo.config(state="normal")
        self.status_lbl.config(text="Disconnected", foreground="red")
        
        self.set_entry_text(self.entry_res1, "Unknown")
        self.set_entry_text(self.entry_res2, "Unknown")
        
        if self.cam1_stream: self.cam1_stream.stop()
        if self.cam2_stream: self.cam2_stream.stop()
        self.cam1_stream = None
        self.cam2_stream = None
        
        cv2.destroyAllWindows()

    def toggle_auto_save(self):
        if not self.is_auto_saving:
            try:
                interval = int(self.entry_interval.get())
                if interval < 50:
                    raise ValueError("Too fast")
            except ValueError:
                messagebox.showerror("Invalid Input", "Please enter a valid positive integer (Minimum: 50ms).")
                return

            self.auto_save_interval = interval
            self.is_auto_saving = True
            self.btn_toggle_auto.config(text="Stop Auto Save")
            self.entry_interval.config(state="disabled")
            self.status_lbl.config(text=f"Auto Saving Active (Every {self.auto_save_interval}ms)", foreground="blue")
            
            self.auto_save_loop()
        else:
            self.stop_auto_save()

    def stop_auto_save(self):
        self.is_auto_saving = False
        self.btn_toggle_auto.config(text="Start Auto Save")
        self.entry_interval.config(state="normal")
        if self.auto_save_job:
            self.window.after_cancel(self.auto_save_job)
            self.auto_save_job = None
        if self.is_streaming:
            self.status_lbl.config(text="Streaming Active (Auto Save Stopped)", foreground="green")

    def auto_save_loop(self):
        if not self.is_auto_saving or not self.is_streaming:
            return
        
        self.capture_frames(mode="AUTO")
        self.auto_save_job = self.window.after(self.auto_save_interval, self.auto_save_loop)

    def update_loop(self):
        if not self.is_streaming:
            return

        f1 = self.cam1_stream.read()
        f2 = self.cam2_stream.read()

        if f1 is not None and f2 is not None:
            if not self.resolution_detected:
                h1, w1 = f1.shape[:2]
                h2, w2 = f2.shape[:2]
                self.set_entry_text(self.entry_res1, f"{w1} x {h1}")
                self.set_entry_text(self.entry_res2, f"{w2} x {h2}")
                self.resolution_detected = True

            self.current_raw_f1 = cv2.cvtColor(f1, cv2.COLOR_GRAY2BGR)
            self.current_raw_f2 = cv2.cvtColor(f2, cv2.COLOR_GRAY2BGR)

            display_f1 = cv2.resize(self.current_raw_f1, (768, 480))
            display_f2 = cv2.resize(self.current_raw_f2, (768, 480))

            cv2.imshow(f"Live Feed - {self.cam1_combo.get()}", display_f1)
            cv2.imshow(f"Live Feed - {self.cam2_combo.get()}", display_f2)

        cv2.waitKey(1)
        self.window.after(20, self.update_loop)

    def capture_frames(self, mode="MANUAL"):
        if not self.is_streaming or not hasattr(self, 'current_raw_f1'):
            return

        img_name1 = os.path.join(self.folder_cam1, f"{self.frame_counter:04d}.jpg")
        img_name2 = os.path.join(self.folder_cam2, f"{self.frame_counter:04d}.jpg")

        cv2.imwrite(img_name1, self.current_raw_f1)
        cv2.imwrite(img_name2, self.current_raw_f2)

        if mode == "MANUAL":
            self.status_lbl.config(text=f"Manual Capture #{self.frame_counter:04d} saved.", foreground="blue")
        else:
            self.status_lbl.config(text=f"Auto Capture #{self.frame_counter:04d} saved.", foreground="blue")
            
        self.frame_counter += 1

    def on_closing(self):
        if self.is_streaming:
            self.stop_hardware()
        self.window.destroy()


if __name__ == "__main__":
    root = tk.Tk()
    app = CameraControlPanel(root)
    root.mainloop()