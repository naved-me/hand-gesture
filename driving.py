import ctypes
import math
import cv2
import mediapipe as mp

# DirectX Input Structures for ctypes
PUL = ctypes.POINTER(ctypes.c_ulong)

class KeyBdInput(ctypes.Structure):
    _fields_ = [("wVk", ctypes.c_ushort),
                ("wScan", ctypes.c_ushort),
                ("dwFlags", ctypes.c_ulong),
                ("time", ctypes.c_ulong),
                ("dwExtraInfo", PUL)]

class HardwareInput(ctypes.Structure):
    _fields_ = [("uMsg", ctypes.c_ulong),
                ("wParamL", ctypes.c_short),
                ("wParamH", ctypes.c_ushort)]

class MouseInput(ctypes.Structure):
    _fields_ = [("dx", ctypes.c_long),
                ("dy", ctypes.c_long),
                ("mouseData", ctypes.c_ulong),
                ("dwFlags", ctypes.c_ulong),
                ("time", ctypes.c_ulong),
                ("dwExtraInfo", PUL)]

class Input_I(ctypes.Union):
    _fields_ = [("ki", KeyBdInput),
                ("mi", MouseInput),
                ("hi", HardwareInput)]

class Input(ctypes.Structure):
    _fields_ = [("type", ctypes.c_ulong),
                ("ii", Input_I)]

# DirectX Scancodes
W = 0x11
A = 0x1E
S = 0x1F
D = 0x20

def PressKey(hexKeyCode):
    extra = ctypes.c_ulong(0)
    ii_ = Input_I()
    ii_.ki = KeyBdInput( 0, hexKeyCode, 0x0008, 0, ctypes.pointer(extra) )
    x = Input( ctypes.c_ulong(1), ii_ )
    ctypes.windll.user32.SendInput(1, ctypes.pointer(x), ctypes.sizeof(x))

def ReleaseKey(hexKeyCode):
    extra = ctypes.c_ulong(0)
    ii_ = Input_I()
    ii_.ki = KeyBdInput( 0, hexKeyCode, 0x0008 | 0x0002, 0, ctypes.pointer(extra) )
    x = Input( ctypes.c_ulong(1), ii_ )
    ctypes.windll.user32.SendInput(1, ctypes.pointer(x), ctypes.sizeof(x))

class DrivingController:
    def __init__(self):
        self.active_keys = set()
        
        # Accumulators for simulated proportional input (Pulse Width Modulation)
        self.pwm_accumulators = {W: 0.0, S: 0.0, A: 0.0, D: 0.0}
        
        # Initialize MediaPipe
        self.mp_hands = mp.solutions.hands
        self.mp_drawing = mp.solutions.drawing_utils
        self.hands = self.mp_hands.Hands(
            static_image_mode=False,
            max_num_hands=2,
            min_detection_confidence=0.7,
            min_tracking_confidence=0.7
        )

    def apply_pwm(self, target_states):
        for key, val in target_states.items():
            if val <= 0.05:
                # Fully off
                if key in self.active_keys:
                    ReleaseKey(key)
                    self.active_keys.remove(key)
                self.pwm_accumulators[key] = 0.0
            elif val >= 0.95:
                # Fully on
                if key not in self.active_keys:
                    PressKey(key)
                    self.active_keys.add(key)
                self.pwm_accumulators[key] = 0.0
            else:
                # Proportional tapping
                self.pwm_accumulators[key] += val
                if self.pwm_accumulators[key] >= 1.0:
                    if key not in self.active_keys:
                        PressKey(key)
                        self.active_keys.add(key)
                    self.pwm_accumulators[key] -= 1.0
                else:
                    if key in self.active_keys:
                        ReleaseKey(key)
                        self.active_keys.remove(key)

    def release_all(self):
        for key in self.active_keys:
            ReleaseKey(key)
        self.active_keys.clear()
        self.pwm_accumulators = {W: 0.0, S: 0.0, A: 0.0, D: 0.0}

    def process_frame(self, frame_bgr, results=None):
        h, w, _ = frame_bgr.shape
        
        if results is None:
            rgb_frame = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2RGB)
            rgb_frame.flags.writeable = False
            results = self.hands.process(rgb_frame)
            rgb_frame.flags.writeable = True
            
        annotated_frame = frame_bgr.copy()
        
        if results.multi_hand_landmarks:
            for hand_landmarks in results.multi_hand_landmarks:
                self.mp_drawing.draw_landmarks(
                    annotated_frame, hand_landmarks, self.mp_hands.HAND_CONNECTIONS)
        
        if results.multi_hand_landmarks and len(results.multi_hand_landmarks) == 2:
            hand1 = results.multi_hand_landmarks[0]
            hand2 = results.multi_hand_landmarks[1]
            
            # Steering anchors (Landmark 9)
            s_lm1 = hand1.landmark[9]
            s_lm2 = hand2.landmark[9]
            
            # Throttle anchors (Landmark 4)
            t_lm1 = hand1.landmark[4]
            t_lm2 = hand2.landmark[4]
            
            s_x1, s_y1 = int(s_lm1.x * w), int(s_lm1.y * h)
            s_x2, s_y2 = int(s_lm2.x * w), int(s_lm2.y * h)
            
            t_x1, t_y1 = int(t_lm1.x * w), int(t_lm1.y * h)
            t_x2, t_y2 = int(t_lm2.x * w), int(t_lm2.y * h)
            
            if s_x1 < s_x2:
                s_lx, s_ly = s_x1, s_y1
                s_rx, s_ry = s_x2, s_y2
                t_lx, t_ly = t_x1, t_y1
                t_rx, t_ry = t_x2, t_y2
            else:
                s_lx, s_ly = s_x2, s_y2
                s_rx, s_ry = s_x1, s_y1
                t_lx, t_ly = t_x2, t_y2
                t_rx, t_ry = t_x1, t_y1
            
            # Angles & Distances
            s_dx = s_rx - s_lx
            s_dy = s_ry - s_ly
            angle = math.degrees(math.atan2(s_dy, s_dx))
            
            t_dx = t_rx - t_lx
            t_dy = t_ry - t_ly
            distance = math.hypot(t_dx, t_dy)
            
            # Maps to store proportion logic (0.0 to 1.0)
            target_states = {W: 0.0, S: 0.0, A: 0.0, D: 0.0}
            
            # Steering Logic
            if angle < -15:
                clamped = max(-40.0, angle)
                target_states[A] = (clamped - -15.0) / (-40.0 - -15.0)
            elif angle > 15:
                clamped = min(40.0, angle)
                target_states[D] = (clamped - 15.0) / (40.0 - 15.0)
            
            # Throttle/Brake Logic
            if distance < 180:
                clamped = max(80.0, distance)
                target_states[W] = (180.0 - clamped) / (180.0 - 80.0)
            elif distance > 260:
                clamped = min(360.0, distance)
                target_states[S] = (clamped - 260.0) / (360.0 - 260.0)
            
            # Send proportional key tapping!
            self.apply_pwm(target_states)
            
            # Visualization
            cv2.line(annotated_frame, (s_lx, s_ly), (s_rx, s_ry), (0, 255, 0), 3)
            cv2.circle(annotated_frame, (t_lx, t_ly), 8, (255, 255, 0), -1)
            cv2.circle(annotated_frame, (t_rx, t_ry), 8, (255, 255, 0), -1)
            
            cv2.putText(annotated_frame, f"Angle: {angle:.1f} deg", (20, 50), 
                        cv2.FONT_HERSHEY_SIMPLEX, 1, (255, 0, 0), 2)
            cv2.putText(annotated_frame, f"Dist: {distance:.1f} px", (20, 100), 
                        cv2.FONT_HERSHEY_SIMPLEX, 1, (255, 0, 0), 2)
                        
            steer_ui = target_states[D] if target_states[D] > 0 else -target_states[A]
            state_str = f"Steer: {steer_ui:.2f} | Thr: {target_states[W]:.2f} | Brk: {target_states[S]:.2f}"
            cv2.putText(annotated_frame, state_str, (20, 150), 
                        cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 0, 255), 2)
        else:
            self.release_all()
            cv2.putText(annotated_frame, "Hands < 2! Killswitch engaged.", (20, 50), 
                        cv2.FONT_HERSHEY_SIMPLEX, 1, (0, 0, 255), 2)
        
        return annotated_frame
