# Project Overview: AI Lifting Analytics (Squat POC)

## 🎯 The Goal
We are building a Proof of Concept (POC) for a computer vision-based fitness application. The system analyzes powerlifting movements to provide biomechanical feedback. 
**Current Scope:** ONLY the Squat exercise. 
**Input:** A side-profile (90-degree) video of a user performing squats.
**Output:** An annotated video (AR overlays) and a kinematic data summary (JSON/Dict) detailing depth (parallel break), concentric velocity, and sticking points.

## 🛠️ Tech Stack & Constraints
- **Language:** Python 3.10+
- **Pose Estimation:** MediaPipe (BlazePose) - *Used purely for feature extraction (X, Y, Z coordinates).*
- **Computer Vision & I/O:** OpenCV (`cv2`) - *For video parsing and AR overlay drawing.*
- **Math & Signal Processing:** NumPy, SciPy - *For time-series filtering (Savitzky-Golay/Butterworth) and vector mathematics.*
- **Constraint 1:** NO machine learning model training in this phase. We rely entirely on MediaPipe + Mathematical Heuristics.
- **Constraint 2:** Architecture MUST be decoupled. The pose extraction layer must be completely separate from the kinematics logic layer, so we can swap MediaPipe for YOLO-Pose in the future without rewriting the core logic.

## 🤖 AI Agent Directives & Personas

When working on this project, assume the role of an **Expert ML Engineer & Biomechanist**. Follow these architectural guidelines:

### 1. Module: Vision & Extraction (`extractor.py`)
- **Task:** Read video frames, pass them through MediaPipe, and extract specific landmarks.
- **Key Landmarks for Squat:** Hip (23/24), Knee (25/26), Ankle (27/28), and Wrist (15/16) as a proxy for the Barbell.
- **Output:** A structured time-series dataset (e.g., a Pandas DataFrame or a list of dicts) containing coordinates for each frame.

### 2. Module: Signal Processing (`filter.py`)
- **Task:** Raw coordinate data from video is noisy. Do NOT calculate velocities directly from raw pixel shifts.
- **Rule:** Implement a low-pass filter (e.g., Butterworth) or a Savitzky-Golay filter over the Y-coordinates of the wrists/hips to smooth the time-series before deriving velocity ($dy/dt$).

### 3. Module: Squat Kinematics Engine (`squat_logic.py`)
- **Task:** Apply mathematical heuristics to the smoothed time-series.
- **Rules to implement:**
  - **Rep Detection:** Define a repetition using peaks and valleys in the Y-coordinate of the hip/bar. (Start -> Descent -> Bottom/Hole -> Ascent -> Lockout).
  - **Depth Check:** Calculate the angle between the Hip, Knee, and Ankle vectors. A squat breaks parallel when the Hip Y-coordinate is lower than the Knee Y-coordinate.
  - **Sticking Point:** Find the local minimum in concentric velocity ($dy/dt$) during the ascent phase.

### 4. Module: Rendering (`visualizer.py`)
- **Task:** Draw insights back onto the video.
- **Rules:**
  - Draw the "Bar Path" (tracking the wrists) as a colored trail.
  - Overlay text displaying the Knee/Hip angle in real-time.
  - Flash a green indicator when "Below Parallel" is achieved.

## ⚠️ Coding Style & Patterns
- **Object-Oriented & Type Hinted:** Use Python `dataclasses` for representing a `FrameState` or `Repetition`. Use strict type hinting (`-> np.ndarray`, `-> float`).
- **Fail Gracefully:** If MediaPipe loses confidence in a landmark due to occlusion (e.g., weight plates hiding the knee), interpolate the missing data using the previous frames or skip the heuristic calculation for that frame gracefully. Do not crash.
- **Coordinate System Warning:** Remember that in OpenCV/Images, the Y-axis origin (0) is at the TOP left. Moving *down* (the eccentric phase of a squat) means the Y value is *increasing*. Moving *up* (concentric) means Y is *decreasing*. Handle signs carefully in velocity calculations.