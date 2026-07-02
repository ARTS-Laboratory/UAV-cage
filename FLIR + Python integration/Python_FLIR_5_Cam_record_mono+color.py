import cv2
import pylablib as pll
from pylablib.devices import IMAQdx
import time
import threading
import os
import sys
import tkinter as tk
from tkinter import ttk, messagebox

class CameraStream:
    def __init__(self, camera_id, lane_index):
        self.camera_id = camera_id
        self.lane_index = lane_index
        self.cam = IMAQdx.IMAQdxCamera(camera_id)
        
        # FIX: Re-enable raw row readout to bypass pylablib's format block
        self.cam.enable_raw_readout('rows') 
        
        self.frame = None
        self.running = False
        self.thread = None
        
        # Thread-safe image caches passed directly to the GUI
        self.current_rgb_frame = None
        self.current_display_frame = None
        self.width = 0
        self.height = 0
        
        # Independent performance timestamps
        self.prev_time = time.time()
        self.fps = 0.0

    def start(self):
        self.cam.start_acquisition()
        self.running = True
        self.thread = threading.Thread(target=self._update, args=(), daemon=True)
        self.thread.start()
        return self

    def _update(self):
        font = cv2.FONT_HERSHEY_SIMPLEX
        font_scale = 0.7
        thickness = 2

        while self.running:
            try:
                new_frame = self.cam.read_newest_image()
                if new_frame is not None:
                    # Capture the 2D matrix dimensions from the raw readout
                    h, w = new_frame.shape[:2]
                    self.width = w
                    self.height = h

                    # BACKGROUND COMPUTATION: Demosaicing the raw Bayer grid
                    # We use BayerBG2BGR here because it fixed your Red/Blue swap earlier
                    try:
                        color_frame = cv2.cvtColor(new_frame, cv2.COLOR_BayerBG2BGR)
                    except Exception:
                        color_frame = cv2.cvtColor(new_frame, cv2.COLOR_GRAY2BGR)

                    # Store full resolution pristine frame safely for disk writing
                    self.current_rgb_frame = color_frame

                    # BACKGROUND COMPUTATION: Downscale Preview Image Layout
                    display_frame = cv2.resize(color_frame, (768, 480))

                    # BACKGROUND COMPUTATION: Calculate Hardware FPS Rate
                    current_time = time.time()
                    time_diff = current_time - self.prev_time
                    if time_diff > 0:
                        self.fps = 1.0 / time_diff
                    self.prev_time = current_time

                    # BACKGROUND COMPUTATION: Render Text Overlay Matrix
                    fps_text = f"FPS: {self.fps:.1f}"
                    text_size = cv2.getTextSize(fps_text, font, font_scale, thickness)[0]
                    text_x = display_frame.shape[1] - text_size[0] - 20
                    text_y = text_size[1] + 20
                    
                    cv2.putText(display_frame, fps_text, (text_x, text_y), font, font_scale, (0, 255, 0), thickness, cv2.LINE_AA)

                    # Expose the completely processed frame to the GUI loop
                    self.current_display_frame = display_frame
                    self.frame = new_frame
                else:
                    time.sleep(0.002)
            except Exception as e:
                print(f"\n[THREAD ERROR] Camera {self.camera_id} loop crash: {e}")
                self.running = False

    def stop(self):
        self.running = False
        if self.thread:
            self.thread.join(timeout=0.5)
        try:
            self.cam.stop_acquisition()
            self.cam.close()
        except Exception:
            pass


class MultiCameraControlPanel:
    def __init__(self, window):
        self.window = window
        self.window.title("Multi-Camera Master Control Dashboard")
        self.window.geometry("820x250")  
        self.window.protocol("WM_DELETE_WINDOW", self.on_closing)
        
        self.NUM_CHANNELS = 5
        
        self.streams = [None] * self.NUM_CHANNELS
        self.res_detected = [False] * self.NUM_CHANNELS
        self.combos = []
        self.res_entries = []
        
        self.is_streaming = False
        self.is_auto_saving = False
        self.auto_save_job = None
        self.auto_save_interval = 1000
        self.frame_counter = 1
        
        if getattr(sys, 'frozen', False):
            exe_dir = os.path.dirname(sys.executable)
        else:
            exe_dir = os.path.dirname(os.path.abspath(__file__))
            
        self.base_folder = os.path.join(exe_dir, "Frames")
        
        try:
            detected = [str(cam[0] if isinstance(cam, tuple) else cam) for cam in IMAQdx.list_cameras()]
            self.dropdown_options = ["None"] + detected
        except Exception as e:
            self.dropdown_options = ["None"]
            print(f"Hardware scan error: {e}")

        self.setup_ui()

    def setup_ui(self):
        main_frame = ttk.Frame(self.window, padding=15)
        main_frame.pack(fill="both", expand=True)
        
        for i in range(self.NUM_CHANNELS):
            ttk.Label(main_frame, text=f"Camera {i+1} ID:").grid(row=i, column=0, padx=5, pady=3, sticky="e")
            
            combo = ttk.Combobox(main_frame, values=self.dropdown_options, width=12, state="readonly")
            combo.grid(row=i, column=1, padx=5, pady=3, sticky="w")
            
            if i + 1 < len(self.dropdown_options):
                combo.current(i + 1)
            else:
                combo.current(0)  
            self.combos.append(combo)
            
            ttk.Label(main_frame, text="Res:").grid(row=i, column=2, padx=5, pady=3, sticky="e")
            res_entry = ttk.Entry(main_frame, width=14, font=("Courier", 9))
            res_entry.grid(row=i, column=3, padx=5, pady=3, sticky="w")
            self.set_entry_text(res_entry, "None")
            self.res_entries.append(res_entry)

        self.btn_toggle_feed = ttk.Button(main_frame, text="Start Live Feed", command=self.toggle_feed, width=16)
        self.btn_toggle_feed.grid(row=0, column=4, columnspan=2, padx=25, pady=3, sticky="ew")
        
        ttk.Label(main_frame, text="Interval (ms):").grid(row=1, column=4, padx=5, pady=3, sticky="e")
        self.entry_interval = ttk.Entry(main_frame, width=10)
        self.entry_interval.insert(0, "1000")
        self.entry_interval.grid(row=1, column=5, padx=5, pady=3, sticky="w")
        
        self.btn_toggle_auto = ttk.Button(main_frame, text="Start Auto Save", command=self.toggle_auto_save, state="disabled", width=16)
        self.btn_toggle_auto.grid(row=2, column=4, columnspan=2, padx=25, pady=3, sticky="ew")
        
        self.btn_capture = ttk.Button(main_frame, text="Capture Frame (C)", command=lambda: self.capture_frames("MANUAL"), state="disabled", width=16)
        self.btn_capture.grid(row=3, column=4, columnspan=2, padx=25, pady=3, sticky="ew")

        self.status_lbl = ttk.Label(main_frame, text="Disconnected", foreground="red", font=("Helvetica", 10, "bold"))
        self.status_lbl.grid(row=self.NUM_CHANNELS, column=0, columnspan=6, pady=10, sticky="w")

        self.window.bind('<KeyRelease-c>', lambda event: self.capture_frames("MANUAL"))
        self.window.bind('<KeyRelease-C>', lambda event: self.capture_frames("MANUAL"))

    def set_entry_text(self, entry_widget, text):
        entry_widget.config(state="normal")
        entry_widget.delete(0, tk.END)
        entry_widget.insert(0, text)
        entry_widget.config(state="readonly")

    def toggle_feed(self):
        if not self.is_streaming:
            active_selections = {}
            
            for i in range(self.NUM_CHANNELS):
                selection = self.combos[i].get()
                if selection != "None":
                    if selection in active_selections.values():
                        messagebox.showerror("Conflict Error", f"Camera ID '{selection}' is selected multiple times.")
                        return
                    active_selections[i] = selection
            
            if not active_selections:
                messagebox.showwarning("Selection Missing", "Please configure at least one active Camera ID.")
                return
                
            try:
                self.status_lbl.config(text="Booting up active channels...", foreground="orange")
                self.window.update()
                
                for idx, cam_id in active_selections.items():
                    os.makedirs(os.path.join(self.base_folder, f"camera {idx+1}"), exist_ok=True)
                    self.streams[idx] = CameraStream(cam_id, idx).start()
                    self.res_detected[idx] = False
                
                self.is_streaming = True
                self.btn_toggle_feed.config(text="Stop Live Feed")
                self.btn_capture.config(state="normal")
                self.btn_toggle_auto.config(state="normal")
                
                for combo in self.combos: combo.config(state="disabled")
                self.status_lbl.config(text=f"Active Streaming Channels: {len(active_selections)}", foreground="green")
                
                self.update_feed_loop()
                
            except Exception as e:
                self.stop_hardware()
                messagebox.showerror("Hardware Error", f"Initialization failed:\n{e}")
        else:
            self.stop_hardware()

    def stop_hardware(self):
        if self.is_auto_saving:
            self.stop_auto_save()

        self.is_streaming = False
        self.btn_toggle_feed.config(text="Start Live Feed")
        self.btn_capture.config(state="disabled")
        self.btn_toggle_auto.config(state="disabled")
        
        for idx, combo in enumerate(self.combos):
            combo.config(state="readonly")
            self.set_entry_text(self.res_entries[idx], "None")
            
        self.status_lbl.config(text="Disconnected", foreground="red")
        
        for i in range(self.NUM_CHANNELS):
            if self.streams[i] is not None:
                self.streams[i].stop()
                self.streams[i] = None
        
        cv2.destroyAllWindows()

    def toggle_auto_save(self):
        if not self.is_auto_saving:
            try:
                interval = int(self.entry_interval.get())
                if interval < 50: raise ValueError
            except ValueError:
                messagebox.showerror("Invalid Input", "Enter a positive integer interval (Minimum: 50ms).")
                return

            self.auto_save_interval = interval
            self.is_auto_saving = True
            self.btn_toggle_auto.config(text="Stop Auto Save")
            self.entry_interval.config(state="disabled")
            self.status_lbl.config(text=f"Auto Recording Active (Every {self.auto_save_interval}ms)", foreground="blue")
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

    def update_feed_loop(self):
        if not self.is_streaming:
            return

        for i in range(self.NUM_CHANNELS):
            if self.streams[i] is not None:
                display_frame = self.streams[i].current_display_frame
                
                if display_frame is None:
                    continue
                
                if not self.res_detected[i]:
                    w = self.streams[i].width
                    h = self.streams[i].height
                    self.set_entry_text(self.res_entries[i], f"{w} x {h}")
                    self.res_detected[i] = True

                cv2.imshow(f"Live Feed - Camera {i+1} ({self.combos[i].get()})", display_frame)

        cv2.waitKey(1)
        # 5ms polling loop catches frames as fast as the background thread finishes them
        self.window.after(5, self.update_feed_loop)

    def capture_frames(self, mode="MANUAL"):
        if not self.is_streaming:
            return

        saved_any = False
        for i in range(self.NUM_CHANNELS):
            if self.streams[i] is not None and self.streams[i].current_rgb_frame is not None:
                target_dir = os.path.join(self.base_folder, f"camera {i+1}")
                filename = os.path.join(target_dir, f"{self.frame_counter:04d}.jpg")
                
                cv2.imwrite(filename, self.streams[i].current_rgb_frame)
                saved_any = True

        if saved_any:
            lbl_text = f"Manual Capture #{self.frame_counter:04d} saved." if mode == "MANUAL" else f"Auto Capture #{self.frame_counter:04d} saved."
            self.status_lbl.config(text=lbl_text, foreground="blue")
            self.frame_counter += 1

    def on_closing(self):
        if self.is_streaming:
            self.stop_hardware()
        self.window.destroy()


if __name__ == "__main__":
    root = tk.Tk()
    app = MultiCameraControlPanel(root)
    root.mainloop()