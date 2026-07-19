# Edge AI Hand Gesture OS Controller

A high-performance, real-time computer vision system that translates hand gestures into zero-latency Windows OS mouse movements and clicks. Engineered for Edge AI execution on local hardware without requiring heavy GPU compute.

## System Architecture

This project deliberately avoids slow, high-level automation libraries (like `PyAutoGUI`). Instead, it utilizes a decoupled tracking-to-kernel pipeline to achieve zero-latency input.

1. **Inference Engine:** Google MediaPipe (TFLite) extracts 21 3D hand landmarks in real-time.
2. **Mathematical Filter:** An Exponential Moving Average (EMA) filter processes raw camera coordinates to eliminate sensor noise and sub-pixel vibration.
3. **OS Kernel Injection:** Processed coordinates and click-states are injected directly into the Windows OS via the Win32 API (`ctypes.windll.user32`).

## Core Engineering Features

* **Zero-Latency Movement:** Direct `ctypes` mouse_event calls bypass Python's high-level interpreter lag.
* **EMA Smoothing:** Applies the formula $S_t = \alpha \cdot Y_t + (1 - \alpha) \cdot S_{t-1}$ (with $\alpha = 0.2$) to create a "shock absorber" effect for the cursor, preventing jitter.
* **Pinch-to-Click State Machine:** Uses Euclidean distance between Landmark 8 (Index Tip) and Landmark 4 (Thumb Tip). A state lock (`is_clicking`) prevents rapid-fire "machine gun" clicking caused by high webcam framerates.
* **Hardware Optimized:** Hardcoded `max_num_hands=1` limits the inference payload, allowing the system to run seamlessly on CPU or entry-level GPUs (e.g., GTX 1650) at 30+ FPS.

## Installation & Setup
**Clone the repository**
