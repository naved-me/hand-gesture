import cv2
import mediapipe as mp
import ctypes
import time

from tracker import HandTracker, AsyncVideoCapture
from driving import DrivingController

def main():
    # Initialize both controllers
    # Note: tracker expects to process hand 0.
    tracker = HandTracker(
        max_num_hands=2, 
        min_detection_confidence=0.7,
        min_tracking_confidence=0.7,
        alpha=0.2,
        click_threshold=30.0,
        release_threshold=40.0,
    )
    driver = DrivingController()

    # We use a global MediaPipe instance for routing
    mp_hands = mp.solutions.hands
    hands = mp_hands.Hands(
        static_image_mode=False,
        max_num_hands=2,
        min_detection_confidence=0.7,
        min_tracking_confidence=0.7
    )

    # Use the async camera thread for low latency
    cam = AsyncVideoCapture(0)
    cam.start()

    window_name = "Unified Hand Controller (2 Hands = Drive, 1 Hand = Mouse)"
    cv2.namedWindow(window_name, cv2.WINDOW_NORMAL)

    # State tracking to cleanly release inputs when transitioning
    was_driving = False
    
    try:
        while True:
            frame = cam.get_latest_frame()
            if frame is None:
                time.sleep(0.01)
                continue

            # Flip horizontally for selfie-view display
            frame = cv2.flip(frame, 1)

            # Process with global mediapipe
            frame_rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            frame_rgb.flags.writeable = False
            results = hands.process(frame_rgb)
            frame_rgb.flags.writeable = True

            annotated_frame = frame.copy()
            num_hands = len(results.multi_hand_landmarks) if results.multi_hand_landmarks else 0

            if num_hands == 2:
                # 2 Hands -> Driving Mechanism
                was_driving = True
                annotated_frame = driver.process_frame(frame, results=results)
                cv2.putText(annotated_frame, "[Mode] DRIVING (2 Hands)", (20, 30), 
                            cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 255, 0), 2)
            elif num_hands == 1:
                # 1 Hand -> Tracker Mechanism
                if was_driving:
                    driver.release_all()
                    was_driving = False
                
                # HandTracker returns a tuple: annotated, raw_xy, smoothed_xy
                annotated_frame, _, _ = tracker.process_frame(frame, results=results)
                cv2.putText(annotated_frame, "[Mode] MOUSE (1 Hand)", (20, 30), 
                            cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 255, 0), 2)
            else:
                # 0 Hands -> Safety Reset
                if was_driving:
                    driver.release_all()
                    was_driving = False
                tracker.reset()

                cv2.putText(annotated_frame, "[Mode] WAITING (0 Hands)", (20, 30), 
                            cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 0, 255), 2)

            cv2.imshow(window_name, annotated_frame)

            # Global Quit Hotkey 'Q' (0x51) OR OpenCV window 'q'
            if (cv2.waitKey(1) & 0xFF == ord('q')) or (ctypes.windll.user32.GetAsyncKeyState(0x51) & 0x8000):
                break

    finally:
        driver.release_all()
        cam.stop()
        cv2.destroyAllWindows()

if __name__ == "__main__":
    main()
