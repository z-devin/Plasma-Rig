from transitions import Machine
import customtkinter as ctk
import serial
import threading
import time
import serial.tools.list_ports

# -----------------------
# Arduino Serial Setup
# -----------------------
BAUD_RATE = 9600

# -----------------------
# Observer Pattern Implementation
# -----------------------
class Observer:
    def update(self, subject, *args, **kwargs):
        pass

class Subject:
    def __init__(self):
        self._observers = []
    
    def attach(self, observer):
        if observer not in self._observers:
            self._observers.append(observer)
    
    def detach(self, observer):
        try:
            self._observers.remove(observer)
        except ValueError:
            pass
    
    def notify(self, *args, **kwargs):
        for observer in self._observers:
            observer.update(self, *args, **kwargs)

# -----------------------
# State Machine Definition
# -----------------------
class MotorController(Subject):
    states = ['Rest', 'Calibration', 'Manual Control', 'Target Distance']

    def __init__(self, serial_port=None):
        Subject.__init__(self)
        self.machine = Machine(model=self, states=MotorController.states, initial='Rest')
        self.machine.add_transition(trigger='start_calibration', source='Rest', dest='Calibration', 
                                   before='notify_state_change_before', after='calibrate')
        self.machine.add_transition(trigger='target_move', source='Rest', dest='Target Distance', 
                                   before='notify_state_change_before', after='move_to_target')
        self.machine.add_transition(trigger='manual_mode', source='Rest', dest='Manual Control', 
                                   before='notify_state_change_before', after='manual_control')
        self.machine.add_transition(trigger='go_rest', source='*', dest='Rest', 
                                   before='notify_state_change_before', after='on_rest')

        self.serial_port = serial_port
        self.serial_conn = None
        self.message_queue = []  # Initialize the message queue
        self.position_mm = -999  # Initialize position
        self.listening = False
        self.listen_thread = None
        self.connect_to_arduino()
    
    def notify_state_change_before(self):
        """Notify observers before state change"""
        self.notify(event='before_state_change', state=self.state)
        
    def notify_state_change_after(self):
        """Notify observers after state change"""
        self.notify(event='after_state_change', state=self.state)
    
    def connect_to_arduino(self):
        # Close existing connection if any
        if self.serial_conn and self.serial_conn.is_open:
            self.listening = False
            if self.listen_thread and self.listen_thread.is_alive():
                self.listen_thread.join(timeout=1.0)
            self.serial_conn.close()
            
        try:
            self.serial_conn = serial.Serial(self.serial_port, BAUD_RATE, timeout=1)
            time.sleep(2)
            
            self.listening = True
            self.listen_thread = threading.Thread(target=self.listen_to_arduino, daemon=True)
            self.listen_thread.start()
            
            # Notify of successful connection
            self.notify(event='connection_update', status='connected', port=self.serial_port)
            return True

        except Exception as e:
            print(f"Serial connection failed: {e}")
            self.notify(event='connection_update', status='failed', error=str(e))
            return False

    def set_serial_port(self, port):
        self.serial_port = port
        return self.connect_to_arduino()

    def send_command(self, cmd):
        if self.serial_conn and self.serial_conn.is_open:
            self.serial_conn.write((cmd + '\n').encode('utf-8'))

    def listen_to_arduino(self):
        # Continuously listen for messages from Arduino
        while self.listening and self.serial_conn and self.serial_conn.is_open:
            try:
                if self.serial_conn.in_waiting:
                    message = self.serial_conn.readline().decode('utf-8').strip()
                    if message:
                        # Add to message queue for GUI updates
                        self.message_queue.append(message)
                        
                        # Handle error messages
                        if message.startswith("ERROR:"):
                            error = message.split(":", 1)[1]
                            if self.state != 'Rest':
                                self.go_rest()
                                # Notify of state change
                                self.notify_state_change_after()

                        # Handle warning messages
                        elif message.startswith("WARNING:"):
                            warning = message.split(":", 1)[1]
                            print(f"Warning from Arduino: {warning}")

                        # Handle status messages
                        elif message.startswith("STATUS:"):
                            status = message.split(":", 1)[1]
                            if status == "CALIBRATION_COMPLETE":
                                # Important: We're in a different thread here
                                if self.state != 'Rest':
                                    self.go_rest()
                                    # Explicitly notify of state change
                                    self.notify_state_change_after()
                            elif status == "CALIBRATION_TIMEOUT":
                                if self.state != 'Rest':
                                    self.go_rest()
                                    self.notify_state_change_after()
                            elif status == "TARGET_COMPLETE":
                                if self.state != 'Rest':
                                    self.go_rest()
                                    self.notify_state_change_after()
                            elif status == "MANUAL_COMPLETE":
                                if self.state != 'Rest':
                                    self.go_rest()
                                    self.notify_state_change_after()
                            
                        # Handle position updates
                        elif message.startswith("POSITION:"):
                            try:
                                position_value = message.split(":", 1)[1].strip()
                                self.position_mm = float(position_value)
                                # Notify observers of position change
                                self.notify(event='position_update', position=self.position_mm)
                            except Exception as e:
                                print(f"Error processing position update: {e}")

            except Exception as e:
                print(f"Error reading from Arduino: {e}")
            time.sleep(0.01)

    def calibrate(self):
        def task():
            self.send_command("CALIBRATE")
        threading.Thread(target=task, daemon=True).start()

    def move_to_target(self):
        def task():
            if hasattr(self, 'target_distance') and self.target_distance is not None:
                self.send_command(f"TARGET:{self.target_distance:.6f}")
            else:
                self.go_rest()
                self.notify_state_change_after()
        threading.Thread(target=task, daemon=True).start()

    def manual_control(self):
        def task():
            self.send_command("MANUAL:READY")
        threading.Thread(target=task, daemon=True).start()

    def on_rest(self):
        def task():
            self.send_command("REST")
        threading.Thread(target=task, daemon=True).start()
        # Explicitly notify after entering rest state
        self.notify_state_change_after()

# -----------------------
# Get Available Serial Ports
# -----------------------
def get_available_ports():
    """Returns a list of available serial ports"""
    ports = list(serial.tools.list_ports.comports())
    return [(p.device, f"{p.device} - {p.description}" if p.description else p.device) for p in ports]

# -----------------------
# GUI Definition
# -----------------------
class MotorApp(ctk.CTk, Observer):
    def __init__(self):
        ctk.CTk.__init__(self)
        Observer.__init__(self)
        
        self.controller = MotorController()
        self.controller.attach(self)  # Register as observer
        
        self.title("Motor State Controller")
        self.geometry("500x500")
        ctk.set_appearance_mode("dark")
        ctk.set_default_color_theme("blue")

        # Serial port selection section
        self.connection_frame = ctk.CTkFrame(self)
        self.connection_frame.pack(pady=10, fill="x", padx=20)
        
        ctk.CTkLabel(self.connection_frame, text="Serial Port:", 
                   font=("Arial", 14)).pack(side="left", padx=5)
        
        # Create a dropdown for port selection
        self.port_var = ctk.StringVar()
        self.port_combo = ctk.CTkComboBox(self.connection_frame, 
                                         variable=self.port_var, 
                                         width=200)
        self.port_combo.pack(side="left", padx=5)
        
        # Button appearance configuration for top controls
        top_button_config = {
            "fg_color": "#1f538d",       # Normal color
            "hover_color": "#14365d",    # Darker shade for hover
            "text_color": "white",
            "corner_radius": 6
        }
        
        # Connect button
        self.connect_button = ctk.CTkButton(self.connection_frame, 
                                          text="Connect", 
                                          command=self.on_connect,
                                          **top_button_config)
        self.connect_button.pack(side="left", padx=5)
        
        # Refresh ports button
        self.refresh_button = ctk.CTkButton(self, 
                                          text="Refresh Ports", 
                                          command=self.refresh_ports,
                                          width=100,
                                          **top_button_config)
        self.refresh_button.pack(pady=5)
        
        # Connection status label
        self.status_label = ctk.CTkLabel(self, 
                                       text="Not Connected", 
                                       text_color="#FF5555")
        self.status_label.pack(pady=5)

        # State display with more prominence
        self.state_frame = ctk.CTkFrame(self)
        self.state_frame.pack(pady=10, fill="x", padx=20)
        
        ctk.CTkLabel(self.state_frame, text="Current State:", 
                   font=("Arial", 14)).pack(side="left", padx=5)
        
        self.state_label = ctk.CTkLabel(self.state_frame, 
                                      text=f"{self.controller.state}", 
                                      font=("Arial", 16, "bold"),
                                      text_color="#00FF00")
        self.state_label.pack(side="left", padx=5)

        # Position display
        self.position_frame = ctk.CTkFrame(self)
        self.position_frame.pack(pady=5, fill="x", padx=20)
        
        ctk.CTkLabel(self.position_frame, text="Position:", 
                   font=("Arial", 14)).pack(side="left", padx=5)
        
        self.position_label = ctk.CTkLabel(self.position_frame, 
                                         text="Not Calibrated", 
                                         font=("Arial", 14, "bold"))
        self.position_label.pack(side="left", padx=5)

        # Main control buttons frame
        button_frame = ctk.CTkFrame(self)
        button_frame.pack(pady=10, fill="x", padx=20)
        
        # Button appearance configuration
        button_config = {
            "width": 180,
            "fg_color": "#1f538d",       # Normal color
            "hover_color": "#14365d",    # Darker shade for hover
            "text_color": "white",
            "corner_radius": 6
        }
        
        # Main control buttons with equal width
        self.calibrate_button = ctk.CTkButton(
            button_frame, 
            text="Calibrate", 
            command=self.on_calibrate,
            state="disabled",
            **button_config
        )
        self.calibrate_button.pack(pady=5)
        
        self.manual_button = ctk.CTkButton(
            button_frame, 
            text="Manual Control", 
            command=self.on_manual,
            state="disabled", 
            **button_config
        )
        self.manual_button.pack(pady=5)
        
        self.target_button = ctk.CTkButton(
            button_frame, 
            text="Target Position", 
            command=self.on_target,
            state="disabled",
            **button_config
        )
        self.target_button.pack(pady=5)
        
        self.rest_button = ctk.CTkButton(
            button_frame, 
            text="Go to Rest", 
            command=self.on_rest,
            state="disabled",
            **button_config
        )
        self.rest_button.pack(pady=5)

        # Debug information label
        ctk.CTkLabel(self, text="Communication Log:", 
                   font=("Arial", 12)).pack(anchor="w", padx=20, pady=(10, 0))
        
        # Log area with larger size
        self.log = ctk.CTkTextbox(self, width=350, height=150)
        self.log.pack(pady=5, padx=20, fill="both", expand=True)

        # Initialize port list
        self.refresh_ports()

        self.protocol("WM_DELETE_WINDOW", self.on_closing)
        self.update_loop()
    
    def refresh_ports(self):
        """Refresh the list of available serial ports"""
        ports = get_available_ports()
        
        # Clear existing values
        self.port_combo.configure(values=[])
        
        if ports:
            # Extract display values for combobox
            port_displays = [display for _, display in ports]
            self.port_combo.configure(values=port_displays)
            self.port_combo.set(port_displays[0])
            self.log_msg(f"Found {len(ports)} serial ports")
        else:
            self.log_msg("No serial ports found")
    
    def on_connect(self):
        """Connect to the selected serial port"""
        selected_display = self.port_var.get()
        
        # Extract port from the display string
        # Format is either "PORT" or "PORT - DESCRIPTION"
        port = selected_display.split(" - ")[0]
        
        if not port:
            self.log_msg("No port selected")
            return
        
        # Attempt connection
        self.log_msg(f"Connecting to {port}...")
        if self.controller.set_serial_port(port):
            self.log_msg(f"Connected to {port}")
            self.status_label.configure(text=f"Connected to {port}", text_color="#00FF00")
            
            # Enable controls
            self.enable_controls()
        else:
            self.log_msg(f"Failed to connect to {port}")
            self.status_label.configure(text=f"Connection failed", text_color="#FF5555")
    
    def enable_controls(self, enabled=True):
        """Enable or disable control buttons based on connection status"""
        # In CustomTkinter, we need to fully configure the button appearance
        # for each state to ensure proper hover effects
        
        if enabled:
            # When enabled, set normal colors with hover effect
            self.calibrate_button.configure(
                state="normal",
                fg_color="#1f538d",
                hover_color="#14365d",
                text_color="white"
            )
            self.manual_button.configure(
                state="normal",
                fg_color="#1f538d",
                hover_color="#14365d", 
                text_color="white"
            )
            self.target_button.configure(
                state="normal",
                fg_color="#1f538d",
                hover_color="#14365d",
                text_color="white"
            )
            self.rest_button.configure(
                state="normal",
                fg_color="#1f538d",
                hover_color="#14365d",
                text_color="white"
            )
        else:
            # When disabled, use gray colors with no hover
            disabled_color = "#565B5E"
            self.calibrate_button.configure(
                state="disabled",
                fg_color=disabled_color,
                text_color="gray70"
            )
            self.manual_button.configure(
                state="disabled",
                fg_color=disabled_color,
                text_color="gray70"
            )
            self.target_button.configure(
                state="disabled",
                fg_color=disabled_color,
                text_color="gray70"
            )
            self.rest_button.configure(
                state="disabled",
                fg_color=disabled_color,
                text_color="gray70"
            )

    def update(self, subject, event=None, **kwargs):
        """Handle updates from the observed controller"""
        if event == 'before_state_change' or event == 'after_state_change':
            # Use after(0) to ensure UI updates happen in the main thread
            self.after(0, lambda: self.update_state_display(subject.state))
            
        elif event == 'position_update':
            # Update position display
            position = kwargs.get('position', -999)
            self.after(0, lambda: self.update_position_display(position))
        
        elif event == 'connection_update':
            status = kwargs.get('status')
            if status == 'connected':
                port = kwargs.get('port', 'unknown')
                self.after(0, lambda: self.status_label.configure(
                    text=f"Connected to {port}", text_color="#00FF00"))
                self.after(0, lambda: self.enable_controls(True))
            elif status == 'failed':
                error = kwargs.get('error', 'unknown error')
                self.after(0, lambda: self.status_label.configure(
                    text=f"Connection failed: {error}", text_color="#FF5555"))
                self.after(0, lambda: self.enable_controls(False))
    
    def update_state_display(self, state):
        """Update the state display in the UI"""
        self.state_label.configure(text=f"{state}")
        # Log the state change
        self.log_msg(f"State changed to: {state}")
    
    def update_position_display(self, position):
        """Update the position display in the UI"""
        if position is None or position == -999:
            self.position_label.configure(text="Not Calibrated")
        else:
            self.position_label.configure(text=f"{position:.6f} mm")

    def on_closing(self):
        self.controller.go_rest()
        # Clean up the serial listener thread
        if hasattr(self.controller, 'listening'):
            self.controller.listening = False
            if hasattr(self.controller, 'listen_thread'):
                self.controller.listen_thread.join(timeout=1.0)
        self.destroy()  # Close the main window

    def log_msg(self, msg):
        self.log.insert("end", f"[{time.strftime('%H:%M:%S')}] {msg}\n")
        self.log.see("end")

    def update_loop(self):
        # Process any messages in the queue (just for logging)
        if self.controller.message_queue:
            messages = self.controller.message_queue.copy()
            self.controller.message_queue.clear()
            
            # Log the messages
            for message in messages:
                self.log_msg(f"<- Received: {message}")
        
        self.after(100, self.update_loop)  # More frequent updates

    def on_calibrate(self):
        # Create a simple dialog with safety checks
        safety_dialog = ctk.CTkToplevel(self)
        safety_dialog.title("Safety Checks")
        safety_dialog.geometry("450x200")
        safety_dialog.transient(self)
        safety_dialog.grab_set()
        
        ctk.CTkLabel(safety_dialog, 
                    text="Safety Confirmation Required:", 
                    font=("Arial", 14, "bold")).pack(pady=(15, 5))
        
        check1 = ctk.CTkCheckBox(safety_dialog, text="High voltage wires disconnected from electrodes")
        check1.pack(anchor="w", padx=20, pady=5)
        
        check2 = ctk.CTkCheckBox(safety_dialog, text="Pins 2 and 3 connected to electrodes")
        check2.pack(anchor="w", padx=20, pady=5)
        
        def on_confirm():
            if check1.get() and check2.get():
                safety_dialog.destroy()
                self.controller.start_calibration()
                self.log_msg("-> Sent: CALIBRATE") # Start calibration
            else:
                self.log_msg("Complete all safety checks to proceed")
        
        def on_cancel():
            safety_dialog.destroy()
            self.log_msg("Calibration cancelled")
        
        button_frame = ctk.CTkFrame(safety_dialog)
        button_frame.pack(pady=15)
        
        ctk.CTkButton(button_frame, text="Cancel", command=on_cancel).pack(side="left", padx=10)
        ctk.CTkButton(button_frame, text="Confirm & Start", command=on_confirm).pack(side="left", padx=10)

    def on_target(self):
        # First, check if system is calibrated
        if self.controller.position_mm is None or self.controller.position_mm == -999:
            # Show calibration warning
            calib_warning = ctk.CTkToplevel(self)
            calib_warning.title("Calibration Required")
            calib_warning.geometry("400x150")
            calib_warning.transient(self)
            calib_warning.grab_set()
            
            ctk.CTkLabel(calib_warning, 
                        text="System must be calibrated before setting a target position.",
                        font=("Arial", 14, "bold")).pack(pady=20)
            
            def close_warning():
                calib_warning.destroy()
                
            ctk.CTkButton(calib_warning, text="OK", command=close_warning).pack(pady=10)
            return
        
        # System is calibrated, show target input dialog
        target_dialog = ctk.CTkToplevel(self)
        target_dialog.title("Set Target Position")
        target_dialog.geometry("400x200")
        target_dialog.transient(self)
        target_dialog.grab_set()
        
        ctk.CTkLabel(target_dialog, 
                    text="Enter Target Position (mm):", 
                    font=("Arial", 14, "bold")).pack(pady=(15, 5))
        
        # Create entry field - no prefilling
        target_entry = ctk.CTkEntry(target_dialog, width=200)
        target_entry.pack(pady=10)
        
        def on_confirm():
            try:
                float_dist = float(target_entry.get())
                if float_dist < 0:
                    result_label.configure(text="Distance must be a positive number.", text_color="red")
                    return
                    
                target_dialog.destroy()
                self.controller.target_distance = float_dist
                self.controller.target_move()
                self.log_msg(f"-> Sent: TARGET:{float_dist}")
                
            except ValueError:
                result_label.configure(text="Invalid target distance. Please enter a number.", text_color="red")
        
        def on_cancel():
            target_dialog.destroy()
            self.log_msg("Target movement cancelled")
        
        # Add a label for error messages
        result_label = ctk.CTkLabel(target_dialog, text="", text_color="red")
        result_label.pack(pady=5)
        
        button_frame = ctk.CTkFrame(target_dialog)
        button_frame.pack(pady=15)
        
        ctk.CTkButton(button_frame, text="Cancel", command=on_cancel).pack(side="left", padx=10)
        ctk.CTkButton(button_frame, text="Move to Target", command=on_confirm).pack(side="left", padx=10)
        
        # Set focus to the entry field
        target_entry.focus_set()

    def on_manual(self):
        # Check if system is calibrated
        if self.controller.position_mm is None or self.controller.position_mm == -999:
            # Show calibration warning
            calib_warning = ctk.CTkToplevel(self)
            calib_warning.title("Calibration Required")
            calib_warning.geometry("400x150")
            calib_warning.transient(self)
            calib_warning.grab_set()
            
            ctk.CTkLabel(calib_warning, 
                        text="System must be calibrated before manual control.",
                        font=("Arial", 14, "bold")).pack(pady=20)
            
            def close_warning():
                calib_warning.destroy()
            
            ctk.CTkButton(calib_warning, text="OK", command=close_warning).pack(pady=10)
            return
        
        # Create popup window
        manual_popup = ctk.CTkToplevel(self)
        manual_popup.title("Manual Control")
        manual_popup.geometry("300x180")
        manual_popup.transient(self)
        manual_popup.grab_set()
        
        ctk.CTkLabel(manual_popup, 
                    text="Hold arrow keys to move motor",
                    font=("Arial", 14)).pack(pady=10)
        
        # Left and right buttons
        button_frame = ctk.CTkFrame(manual_popup)
        button_frame.pack(pady=10)
        
        left_button = ctk.CTkButton(button_frame, text="◄", width=40, height=40)
        left_button.pack(side="left", padx=10)
        
        right_button = ctk.CTkButton(button_frame, text="►", width=40, height=40)
        right_button.pack(side="left", padx=10)
        
        # For key tracking
        is_key_pressed = {"left": False, "right": False}
        active_command = None
        repeat_timer = None
        
        # Move motor function
        def move_motor():
            nonlocal repeat_timer
            if active_command:
                self.controller.send_command(active_command)
                repeat_timer = manual_popup.after(10, move_motor)  # 5ms repeat for faster response
        
        # Key press handler
        def on_key_press(event):
            nonlocal active_command, repeat_timer
            
            # Cancel any existing movement
            if repeat_timer:
                manual_popup.after_cancel(repeat_timer)
                repeat_timer = None
            
            # Set direction based on key
            if event.keysym == "Left" and not is_key_pressed["left"]:
                is_key_pressed["left"] = True
                is_key_pressed["right"] = False  # Ensure other key is cleared
                active_command = "MANUAL:CCW"
                move_motor()  # Start movement
                
            elif event.keysym == "Right" and not is_key_pressed["right"]:
                is_key_pressed["right"] = True
                is_key_pressed["left"] = False  # Ensure other key is cleared
                active_command = "MANUAL:CW"
                move_motor()  # Start movement
        
        # Key release handler
        def on_key_release(event):
            nonlocal active_command, repeat_timer
            
            if event.keysym == "Left":
                is_key_pressed["left"] = False
                
            elif event.keysym == "Right":
                is_key_pressed["right"] = False
            
            # If both keys are released, stop movement
            if not (is_key_pressed["left"] or is_key_pressed["right"]):
                active_command = None
                if repeat_timer:
                    manual_popup.after_cancel(repeat_timer)
                    repeat_timer = None
                self.controller.send_command("MANUAL:STOP")
        
        # Handler functions for button presses
        def start_button_command(command, key):
            nonlocal is_key_pressed
            is_key_pressed[key] = True
            for other_key in is_key_pressed:
                if other_key != key:
                    is_key_pressed[other_key] = False
                    
            nonlocal active_command, repeat_timer
            if repeat_timer:
                manual_popup.after_cancel(repeat_timer)
            
            active_command = command
            move_motor()
        
        def stop_button_command():
            nonlocal is_key_pressed, active_command, repeat_timer
            for key in is_key_pressed:
                is_key_pressed[key] = False
                
            active_command = None
            if repeat_timer:
                manual_popup.after_cancel(repeat_timer)
                repeat_timer = None
            
            self.controller.send_command("MANUAL:STOP")
        
        # Bind keys with general key press/release handlers
        manual_popup.bind("<KeyPress>", on_key_press)
        manual_popup.bind("<KeyRelease>", on_key_release)
        
        # Bind buttons with specific handlers
        left_button.bind("<ButtonPress>", lambda e: start_button_command("MANUAL:CW", "left"))
        left_button.bind("<ButtonRelease>", lambda e: stop_button_command())
        
        right_button.bind("<ButtonPress>", lambda e: start_button_command("MANUAL:CCW", "right"))
        right_button.bind("<ButtonRelease>", lambda e: stop_button_command())
        
        def close_popup():
            nonlocal repeat_timer
            # Stop any movement
            if repeat_timer:
                manual_popup.after_cancel(repeat_timer)
            
            self.controller.send_command("MANUAL:COMPLETE")
            manual_popup.destroy()
            self.log_msg("-> Exited Manual Control mode")
            self.controller.go_rest()
        
        # Add close button
        ctk.CTkButton(manual_popup, text="Close", 
                    command=close_popup).pack(pady=10)
        
        # Set close protocol
        manual_popup.protocol("WM_DELETE_WINDOW", close_popup)
        manual_popup.focus_set()  # Important to capture key events
        
        # Log entry to manual mode
        self.log_msg("-> Entered Manual Control mode")
        self.controller.manual_mode()

    def on_rest(self):
            self.controller.go_rest()
            self.log_msg("-> Back to Rest")

# -----------------------
# Run App
# -----------------------
if __name__ == "__main__":
    app = MotorApp()
    app.mainloop()