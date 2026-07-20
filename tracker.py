import threading
import time
from dataclasses import dataclass
from typing import Optional, Tuple

import cv2
import mediapipe as mp

import ctypes

import numpy as np


# Fix for some environments where the import name may be shadowed or partial.
# We expect MediaPipe Hands under `mediapipe.solutions.hands`.
if not hasattr(mp, "solutions"):
    raise ImportError(
        "mediapipe was imported but `mediapipe.solutions` is missing. "
        "Ensure you installed the correct package: `pip install mediapipe`. "
        "Also verify there is no local file/folder named `mediapipe.py` shadowing the library."
    )


@dataclass
class SmoothedPoint:

    x: float
    y: float


class HandTracker:
    """Vision/extraction/smoothing engine.


    Phase 2 adds:
    - Screen mapping from smoothed index fingertip
    - Kernel-level cursor movement via Win32 ctypes
    - Pinch detection + left click state machine
    """

    INDEX_FINGER_TIP_LANDMARK_ID = 8
    THUMB_TIP_LANDMARK_ID = 4

    def __init__(
        self,
        *,
        max_num_hands: int = 1,
        min_detection_confidence: float = 0.7,
        min_tracking_confidence: float = 0.7,
        alpha: float = 0.2,
        click_threshold: float = 30.0,
        release_threshold: float = 40.0,
        camera_src: int = 0,
    ) -> None:
        # Smoothing
        self.alpha = float(alpha)
        self._previous_smoothed: Optional[SmoothedPoint] = None

        # Pinch/click state
        self.click_threshold = float(click_threshold)
        self.release_threshold = float(release_threshold)
        self.is_clicking = False

        # Win32 APIs
        self.user32 = ctypes.windll.user32
        self._mouse_event_flags = {
            "left_down": 0x0002,
            "left_up": 0x0004,
        }

        # Display metrics
        self.screen_w = int(self.user32.GetSystemMetrics(0))
        self.screen_h = int(self.user32.GetSystemMetrics(1))

        # MediaPipe
        self.mp_hands = mp.solutions.hands
        self.mp_drawing = mp.solutions.drawing_utils
        self.mp_styles = mp.solutions.drawing_styles

        self.hands = self.mp_hands.Hands(
            static_image_mode=False,
            max_num_hands=max_num_hands,
            min_detection_confidence=min_detection_confidence,
            min_tracking_confidence=min_tracking_confidence,
        )


    # (Replaced by Phase-2 __init__ above)


    def reset(self) -> None:
        self._previous_smoothed = None

    def _ema_smooth(self, raw_x: float, raw_y: float) -> SmoothedPoint:
        if self._previous_smoothed is None:
            smoothed = SmoothedPoint(x=raw_x, y=raw_y)
        else:
            prev = self._previous_smoothed
            a = self.alpha
            smoothed = SmoothedPoint(
                x=(a * raw_x) + ((1.0 - a) * prev.x),
                y=(a * raw_y) + ((1.0 - a) * prev.y),
            )

        self._previous_smoothed = smoothed
        return smoothed

    def extract_fingertip_px(
        self,
        frame_w: int,
        frame_h: int,
        hand_landmarks,
        landmark_id: int,
    ) -> Tuple[float, float]:
        lm = hand_landmarks.landmark[landmark_id]
        raw_x = lm.x * frame_w
        raw_y = lm.y * frame_h
        return raw_x, raw_y

    def extract_index_fingertip_px(
        self, frame_w: int, frame_h: int, hand_landmarks
    ) -> Tuple[float, float]:
        return self.extract_fingertip_px(
            frame_w, frame_h, hand_landmarks, self.INDEX_FINGER_TIP_LANDMARK_ID
        )

    def extract_thumb_tip_px(
        self, frame_w: int, frame_h: int, hand_landmarks
    ) -> Tuple[float, float]:
        return self.extract_fingertip_px(
            frame_w, frame_h, hand_landmarks, self.THUMB_TIP_LANDMARK_ID
        )


    def _map_smoothed_to_screen_px(
        self,
        smoothed_x_px: float,
        smoothed_y_px: float,
        frame_w: int,
        frame_h: int,
    ) -> Tuple[int, int]:
        # Map camera frame pixel range -> screen pixel range using interpolation.
        # Use np.interp as requested.
        screen_x = np.interp(smoothed_x_px, [0, frame_w], [0, self.screen_w - 1])
        screen_y = np.interp(smoothed_y_px, [0, frame_h], [0, self.screen_h - 1])
        return int(round(screen_x)), int(round(screen_y))

    def _set_cursor_pos(self, x: int, y: int) -> None:
        self.user32.SetCursorPos(int(x), int(y))

    def _maybe_click(self, distance_px: float) -> None:
        if distance_px < self.click_threshold and not self.is_clicking:
            self.user32.mouse_event(self._mouse_event_flags["left_down"], 0, 0, 0, 0)
            self.is_clicking = True
        elif distance_px > self.release_threshold and self.is_clicking:
            self.user32.mouse_event(self._mouse_event_flags["left_up"], 0, 0, 0, 0)
            self.is_clicking = False

    def process_frame(
        self,
        frame_bgr,
        results=None,
    ) -> Tuple[
        any,
        Optional[Tuple[float, float]],
        Optional[Tuple[float, float]],
    ]:
        """Run inference, extract fingertips, apply EMA smoothing.

        Phase 2:
        - Move cursor to mapped smoothed index fingertip
        - Detect pinch using raw index-thumb distance and issue click events
        """
        frame_h, frame_w = frame_bgr.shape[:2]

        if results is None:
            frame_rgb = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2RGB)
            frame_rgb.flags.writeable = False
            results = self.hands.process(frame_rgb)
            frame_rgb.flags.writeable = True

        annotated = frame_bgr.copy()
        raw_xy: Optional[Tuple[float, float]] = None
        smoothed_xy: Optional[Tuple[float, float]] = None

        if results.multi_hand_landmarks:
            hand_landmarks = results.multi_hand_landmarks[0]

            # Raw points
            raw_ix, raw_iy = self.extract_index_fingertip_px(frame_w, frame_h, hand_landmarks)
            raw_tx, raw_ty = self.extract_thumb_tip_px(frame_w, frame_h, hand_landmarks)
            raw_xy = (raw_ix, raw_iy)

            # --- Anchor Separation (fix 1): use Landmark 5 (Index MCP/Base) for movement ---
            move_ix, move_iy = self.extract_fingertip_px(
                frame_w,
                frame_h,
                hand_landmarks,
                5,  # Landmark 5 = Index MCP
            )

            # EMA smoothing for cursor movement using Landmark 5
            smoothed = self._ema_smooth(move_ix, move_iy)
            smoothed_xy = (smoothed.x, smoothed.y)


            # --- Low Sensitivity Active Area (fix 2): map using margin box ---
            frame_margin = 75

            # Clip margins to valid frame extents
            x0 = int(min(max(frame_margin, 0), frame_w - 1))
            x1 = int(min(max(frame_w - frame_margin, 0), frame_w))
            y0 = int(min(max(frame_margin, 0), frame_h - 1))
            y1 = int(min(max(frame_h - frame_margin, 0), frame_h))

            # Draw Active Area rectangle for UX/debug
            cv2.rectangle(
                annotated,
                (x0, y0),
                (x1, y1),
                (255, 0, 0),
                thickness=2,
            )

            # Map smoothed move anchor (Landmark 5) within [frame_margin, frame_w-frame_margin]
            # to [0, screen_w] / [0, screen_h] with np.interp
            mapped_x = np.interp(smoothed.x, [x0, x1], [0, self.screen_w])
            mapped_y = np.interp(smoothed.y, [y0, y1], [0, self.screen_h])

            screen_x, screen_y = int(round(mapped_x)), int(round(mapped_y))
            self._set_cursor_pos(screen_x, screen_y)


            # Pinch detection (raw distance between Landmark 8 (Index Tip) and Landmark 4 (Thumb Tip))
            distance_px = float(np.linalg.norm([raw_ix - raw_tx, raw_iy - raw_ty]))
            self._maybe_click(distance_px)


            # Draw default MediaPipe hand skeleton.
            self.mp_drawing.draw_landmarks(
                annotated,
                hand_landmarks,
                self.mp_hands.HAND_CONNECTIONS,
                self.mp_styles.get_default_hand_landmarks_style(),
                self.mp_styles.get_default_hand_connections_style(),
            )

            # Draw a distinct, solid green circle ONLY on the smoothed coordinate.
            cx, cy = int(round(smoothed.x)), int(round(smoothed.y))
            radius = max(6, int(round(min(frame_w, frame_h) * 0.015)))
            cv2.circle(annotated, (cx, cy), radius, (0, 255, 0), thickness=-1)

        return annotated, raw_xy, smoothed_xy



class AsyncVideoCapture:
    """Background-thread webcam frame grabber for lower latency."""

    def __init__(self, src: int = 0, *, width: Optional[int] = None, height: Optional[int] = None) -> None:
        self.src = src
        self.cap = cv2.VideoCapture(src)
        if width is not None:
            self.cap.set(cv2.CAP_PROP_FRAME_WIDTH, int(width))
        if height is not None:
            self.cap.set(cv2.CAP_PROP_FRAME_HEIGHT, int(height))

        self._lock = threading.Lock()
        self._latest_frame = None
        self._running = False
        self._thread: Optional[threading.Thread] = None

    def start(self) -> None:
        if self._running:
            return
        self._running = True
        self._thread = threading.Thread(target=self._reader_loop, daemon=True)
        self._thread.start()

    def _reader_loop(self) -> None:
        while self._running:
            ok, frame = self.cap.read()
            if ok:
                with self._lock:
                    self._latest_frame = frame
            # Small sleep to prevent busy looping.
            time.sleep(0.001)

    def get_latest_frame(self):
        with self._lock:
            return None if self._latest_frame is None else self._latest_frame.copy()

    def stop(self) -> None:
        self._running = False
        if self._thread is not None:
            self._thread.join(timeout=1.0)
        try:
            self.cap.release()
        except Exception:
            pass


def main() -> None:
    tracker = HandTracker(
        max_num_hands=1,
        min_detection_confidence=0.7,
        min_tracking_confidence=0.7,
        alpha=0.2,
        click_threshold=30.0,
        release_threshold=40.0,
    )


    cam = AsyncVideoCapture(0)
    cam.start()

    window_name = "Hand Tracker (smoothed index fingertip)"
    cv2.namedWindow(window_name, cv2.WINDOW_NORMAL)

    try:
        while True:
            frame = cam.get_latest_frame()
            if frame is None:
                time.sleep(0.01)
                continue

            annotated, _raw_xy, _smoothed_xy = tracker.process_frame(frame)

            cv2.imshow(window_name, annotated)
            key = cv2.waitKey(1) & 0xFF
            # Press 'q' to quit.
            if key == ord('q'):
                break


    finally:
        cam.stop()
        cv2.destroyAllWindows()


if __name__ == "__main__":
    main()

