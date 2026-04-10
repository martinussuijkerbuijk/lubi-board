import cv2
import numpy as np
import json
import os
import time

# --- CONFIGURATION ---
CAPTURE_INTERVAL = 6.0  # Seconds between shots
DATASET_FOLDER = "./dataset_raw"
CALIBRATION_FILE = "./calibration_matrix.json"
BLEED_PADDING = 60      # Pixels of extra space around the grid (Prevents cutoff at corners)

def load_calibration():
    if not os.path.exists(CALIBRATION_FILE):
        print(f"Error: {CALIBRATION_FILE} not found. Run board_calibration.py first.")
        return None, None
    
    with open(CALIBRATION_FILE, 'r') as f:
        data = json.load(f)
        matrix = np.array(data["homography_matrix"])
        size = tuple(data["warped_size"])
        return matrix, size

def get_next_filename(folder):
    if not os.path.exists(folder):
        os.makedirs(folder)
    
    existing = [f for f in os.listdir(folder) if f.endswith('.jpg')]
    if not existing:
        return os.path.join(folder, "img_000.jpg")
    
    # Sort and find highest index
    indices = []
    for f in existing:
        try:
            idx = int(f.split('_')[1].split('.')[0])
            indices.append(idx)
        except:
            pass
    
    if not indices:
        return os.path.join(folder, "img_000.jpg")
        
    next_idx = max(indices) + 1
    return os.path.join(folder, f"img_{next_idx:03d}.jpg")

def main():
    matrix, warped_size = load_calibration()
    if matrix is None:
        return

    # --- APPLY BLEED PADDING ---
    # Shift the perspective transform to center the grid with padding
    # This prevents cutting off coins placed exactly on the corner grid points
    translation_matrix = np.array([
        [1, 0, BLEED_PADDING],
        [0, 1, BLEED_PADDING],
        [0, 0, 1]
    ])
    # Apply translation to the existing homography
    matrix = np.dot(translation_matrix, matrix)
    # Increase the output canvas size to accommodate the padding on all sides
    warped_size = (warped_size[0] + 2 * BLEED_PADDING, warped_size[1] + 2 * BLEED_PADDING)
    # ---------------------------

    cap = cv2.VideoCapture(0)
    # Use high res input, warp down to target
    cap.set(cv2.CAP_PROP_FRAME_WIDTH, 1920)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 1080)

    cap.set(cv2.CAP_PROP_AUTOFOCUS, 1)
    cap.set(cv2.CAP_PROP_FOCUS, 255) # Try changing this to 255 if 0 is blurry
    cap.set(cv2.CAP_PROP_EXPOSURE, 0)
    # Optional: Disable Auto-Exposure/White Balance for a truly "static" image
    cap.set(cv2.CAP_PROP_AUTO_EXPOSURE, 0.25) # 0.25 is often 'Manual' for C920

    last_capture_time = time.time()
    capturing = False # Press SPACE to start the auto-loop

    print(f"--- DATA COLLECTION STARTED ---")
    print(f"Saving to: {DATASET_FOLDER}")
    print(f"Padding added: {BLEED_PADDING}px border")
    print(f"1. Press SPACE to toggle Auto-Capture (Every {CAPTURE_INTERVAL}s).")
    print(f"2. Press 'q' to quit.")

    while True:
        ret, frame = cap.read()
        if not ret: break

        # 1. Apply Warp
        warped_frame = cv2.warpPerspective(frame, matrix, warped_size)
        display_frame = warped_frame.copy()

        # 2. Timer Logic
        current_time = time.time()
        elapsed = current_time - last_capture_time
        remaining = max(0, CAPTURE_INTERVAL - elapsed)

        if capturing:
            # Draw Timer Bar
            progress = elapsed / CAPTURE_INTERVAL
            bar_width = int(warped_size[0] * progress)
            
            # Color logic: Green = Safe to move, Red = About to snap
            color = (0, 255, 0)
            if progress > 0.8: color = (0, 0, 255) # Red warning
            
            cv2.rectangle(display_frame, (0, warped_size[1]-20), (bar_width, warped_size[1]), color, -1)
            cv2.putText(display_frame, f"SNAP IN: {remaining:.1f}s", (10, warped_size[1]-30), 
                        cv2.FONT_HERSHEY_SIMPLEX, 0.7, color, 2)

            # 3. Capture Trigger
            if elapsed >= CAPTURE_INTERVAL:
                filename = get_next_filename(DATASET_FOLDER)
                cv2.imwrite(filename, warped_frame) # Save the CLEAN warped frame, not display_frame
                print(f"Saved: {filename}")
                
                # Flash effect on screen
                cv2.rectangle(display_frame, (0,0), warped_size, (255,255,255), -1)
                
                last_capture_time = time.time()

        else:
            cv2.putText(display_frame, "PAUSED (Press SPACE)", (10, 30), 
                        cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 255, 255), 2)

        cv2.imshow("Data Collector", display_frame)
        
        key = cv2.waitKey(1) & 0xFF
        if key == ord('q'):
            break
        elif key == ord(' '):
            capturing = not capturing
            last_capture_time = time.time() # Reset timer on toggle

    cap.release()
    cv2.destroyAllWindows()

if __name__ == "__main__":
    main()