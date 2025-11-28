import cv2
import numpy as np
import json
import os

# CONFIGURATION
# The desired output size for the flattened board (width, height)
# 640x640 is great for YOLOv8 (no resizing needed later)
WARPED_SIZE = (640, 640) 
CALIBRATION_FILE = "calibration_matrix.json"

# Global variables for mouse callback
points = []

def mouse_callback(event, x, y, flags, param):
    if event == cv2.EVENT_LBUTTONDOWN:
        if len(points) < 4:
            points.append((x, y))
            print(f"Point recorded: {x}, {y}")

def save_calibration(matrix):
    data = {"homography_matrix": matrix.tolist(), "warped_size": WARPED_SIZE}
    with open(CALIBRATION_FILE, 'w') as f:
        json.dump(data, f)
    print(f"Calibration saved to {CALIBRATION_FILE}")

def main():
    global points
    
    cap = cv2.VideoCapture(0)
    # Set to high resolution for accurate clicking
    cap.set(cv2.CAP_PROP_FRAME_WIDTH, 1920)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 1080)

    cv2.namedWindow("Calibration")
    cv2.setMouseCallback("Calibration", mouse_callback)

    print("--- CALIBRATION INSTRUCTIONS ---")
    print("1. Click the 4 corners of the grid in this order:")
    print("   TOP-LEFT -> TOP-RIGHT -> BOTTOM-RIGHT -> BOTTOM-LEFT")
    print("2. Press 'c' to calculate and preview the warp.")
    print("3. Press 's' to save and exit.")
    print("4. Press 'r' to reset points.")
    print("5. Press 'q' to quit without saving.")

    homography_matrix = None

    while True:
        ret, frame = cap.read()
        if not ret:
            break

        display_frame = frame.copy()

        # Draw clicked points
        for i, pt in enumerate(points):
            cv2.circle(display_frame, pt, 5, (0, 0, 255), -1)
            cv2.putText(display_frame, str(i+1), (pt[0]+10, pt[1]-10), 
                        cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 255, 0), 2)

        # Draw lines connecting points if we have 4
        if len(points) == 4:
            cv2.polylines(display_frame, [np.array(points)], True, (0, 255, 255), 2)

        cv2.imshow("Calibration", display_frame)

        # Show Preview window if matrix exists
        if homography_matrix is not None:
            warped = cv2.warpPerspective(frame, homography_matrix, WARPED_SIZE)
            cv2.imshow("Warped Preview", warped)

        key = cv2.waitKey(1) & 0xFF

        if key == ord('q'):
            break
        elif key == ord('r'):
            points = []
            homography_matrix = None
            print("Points reset.")
        elif key == ord('c'):
            if len(points) == 4:
                # Source points (from clicks)
                src_pts = np.float32(points)
                # Destination points (the flat square)
                dst_pts = np.float32([
                    [0, 0],
                    [WARPED_SIZE[0], 0],
                    [WARPED_SIZE[0], WARPED_SIZE[1]],
                    [0, WARPED_SIZE[1]]
                ])
                homography_matrix = cv2.getPerspectiveTransform(src_pts, dst_pts)
                print("Transformation calculated. Check the preview window.")
            else:
                print("Need exactly 4 points to calculate.")
        elif key == ord('s'):
            if homography_matrix is not None:
                save_calibration(homography_matrix)
                break
            else:
                print("Calculate (press 'c') before saving.")

    cap.release()
    cv2.destroyAllWindows()

if __name__ == "__main__":
    main()