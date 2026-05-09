"""Mouse control with Head Tracking + Hand Gestures."""

import time
import math
import cv2

from .connection import GalaxyBudsConnection

try:
    import mediapipe as mp
    HAS_MEDIAPIPE = True
except Exception as e:
    print(f"DEBUG: MediaPipe unavailable: {e}")
    HAS_MEDIAPIPE = False

try:
    import pyautogui
    pyautogui.FAILSAFE = False
    HAS_MOUSE_BACKEND = True
except Exception as e:
    print(f"DEBUG: PyAutoGUI unavailable: {e}")
    HAS_MOUSE_BACKEND = False


class GestureController:
    def __init__(self):
        self.active = False
        if HAS_MEDIAPIPE:
            try:
                self.mp_hands = mp.solutions.hands
                self.hands = self.mp_hands.Hands(max_num_hands=1, min_detection_confidence=0.7, min_tracking_confidence=0.7)
                self.mp_draw = mp.solutions.drawing_utils
                self.active = True
            except Exception as e:
                print(f"MediaPipe Error: {e}")

        self.is_dragging = False
        self.last_click_time = 0
        self.click_cooldown = 0.5

    def process(self, frame, mouse_x, mouse_y):
        if not self.active or not HAS_MOUSE_BACKEND:
            return frame, "No Hand Track"

        rgb_frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        results = self.hands.process(rgb_frame)
        status = "Open Hand"

        if results.multi_hand_landmarks:
            for hand_landmarks in results.multi_hand_landmarks:
                self.mp_draw.draw_landmarks(frame, hand_landmarks, self.mp_hands.HAND_CONNECTIONS)
                h, w, _ = frame.shape
                coords = [(int(lm.x * w), int(lm.y * h)) for lm in hand_landmarks.landmark]

                thumb_tip, index_tip, middle_tip = coords[4], coords[8], coords[12]
                ring_tip, pinky_tip = coords[16], coords[20]
                index_mcp, middle_mcp, ring_mcp, pinky_mcp, wrist = coords[5], coords[9], coords[13], coords[17], coords[0]

                dist_thumb_index = math.hypot(thumb_tip[0]-index_tip[0], thumb_tip[1]-index_tip[1])
                dist_thumb_middle = math.hypot(thumb_tip[0]-middle_tip[0], thumb_tip[1]-middle_tip[1])

                is_fist = (
                    math.hypot(index_tip[0]-wrist[0], index_tip[1]-wrist[1]) < math.hypot(index_mcp[0]-wrist[0], index_mcp[1]-wrist[1]) and
                    math.hypot(middle_tip[0]-wrist[0], middle_tip[1]-wrist[1]) < math.hypot(middle_mcp[0]-wrist[0], middle_mcp[1]-wrist[1]) and
                    math.hypot(ring_tip[0]-wrist[0], ring_tip[1]-wrist[1]) < math.hypot(ring_mcp[0]-wrist[0], ring_mcp[1]-wrist[1]) and
                    math.hypot(pinky_tip[0]-wrist[0], pinky_tip[1]-wrist[1]) < math.hypot(pinky_mcp[0]-wrist[0], pinky_mcp[1]-wrist[1])
                )

                if is_fist:
                    status = "FIST (Drag)"
                    if not self.is_dragging:
                        pyautogui.mouseDown(x=mouse_x, y=mouse_y, button="left")
                        self.is_dragging = True
                else:
                    if self.is_dragging:
                        pyautogui.mouseUp(x=mouse_x, y=mouse_y, button="left")
                        self.is_dragging = False

                    if dist_thumb_index < 30:
                        status = "LEFT CLICK"
                        if time.time() - self.last_click_time > self.click_cooldown:
                            pyautogui.click(x=mouse_x, y=mouse_y, button="left")
                            self.last_click_time = time.time()
                    elif dist_thumb_middle < 30:
                        status = "RIGHT CLICK"
                        if time.time() - self.last_click_time > self.click_cooldown:
                            pyautogui.click(x=mouse_x, y=mouse_y, button="right")
                            self.last_click_time = time.time()
        elif self.is_dragging:
            pyautogui.mouseUp(x=mouse_x, y=mouse_y, button="left")
            self.is_dragging = False

        return frame, status


class HeadMouseController:
    def __init__(self, sensitivity=15.0):
        self.sensitivity = sensitivity
        self.center_yaw = 0.0
        self.center_pitch = 0.0
        self.calibrated = False
        self.screen_w, self.screen_h = pyautogui.size() if HAS_MOUSE_BACKEND else (1920, 1080)
        self.cx = self.screen_w / 2
        self.cy = self.screen_h / 2
        self.current_x = self.cx
        self.current_y = self.cy

    def calibrate(self, quat):
        euler = quat.to_euler()
        self.center_yaw = euler[2]
        self.center_pitch = euler[1]
        self.calibrated = True

    def update(self, quat):
        if not self.calibrated or not HAS_MOUSE_BACKEND:
            return self.current_x, self.current_y

        euler = quat.to_euler()
        dx = euler[2] - self.center_yaw
        dy = euler[1] - self.center_pitch

        self.current_x = max(0, min(self.screen_w, self.cx + dx * self.sensitivity))
        self.current_y = max(0, min(self.screen_h, self.cy - dy * self.sensitivity))
        pyautogui.moveTo(self.current_x, self.current_y)
        return self.current_x, self.current_y


def run_mouse_mode(conn: GalaxyBudsConnection):
    if not HAS_MOUSE_BACKEND:
        print("Error: PyAutoGUI not available. Install: pip install pyautogui")
        return
    if not HAS_MEDIAPIPE:
        print("Error: MediaPipe not available. Install: pip install mediapipe")
        return

    head_ctrl = HeadMouseController(sensitivity=25.0)
    gesture_ctrl = GestureController()
    cap = cv2.VideoCapture(0)
    if not cap.isOpened():
        print("Webcam error")
        return

    last_ka = time.time()
    while conn.latest_quaternion is None:
        conn.run_loop(0.1)
        if time.time() - last_ka >= 2.0:
            conn.send_keep_alive()
            last_ka = time.time()

    input("Press ENTER when looking at screen center...")
    head_ctrl.calibrate(conn.latest_quaternion)

    try:
        while True:
            conn.run_loop(0.01)
            if time.time() - last_ka >= 2.0:
                conn.send_keep_alive()
                last_ka = time.time()

            mx, my = (0, 0)
            if conn.latest_quaternion:
                mx, my = head_ctrl.update(conn.latest_quaternion)

            ret, frame = cap.read()
            if ret:
                frame = cv2.flip(frame, 1)
                frame, status = gesture_ctrl.process(frame, int(mx), int(my))
                small = cv2.resize(frame, (240, int(240 * (frame.shape[0] / frame.shape[1]))))
                color = (0, 255, 0) if "CLICK" not in status else (0, 0, 255)
                cv2.putText(small, status, (5, 20), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 0, 0), 3)
                cv2.putText(small, status, (5, 20), cv2.FONT_HERSHEY_SIMPLEX, 0.6, color, 1)
                cv2.imshow("Gestures", small)

            if cv2.waitKey(1) & 0xFF == 27:
                break
    finally:
        cap.release()
        cv2.destroyAllWindows()
