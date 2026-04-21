import cv2
import numpy as np
import os
from ultralytics import YOLO  # Requires: pip install ultralytics

# --- CONFIGURATION ---
DATASET_DIR = "dataset_raw"
OUTPUT_DIR = "dataset_raw"
CONFIDENCE_THRESHOLD = 0.02  # Low threshold to catch everything (we filter manually anyway)

# DEFINE YOUR CLASSES
# Use -1 for the Class ID to indicate an "Empty" or "Ignore" category.
KEY_MAPPING = {
    'w': (0, "will"),
    'f': (1, "fount"),
    'e': (2, "ethos"),
    'c': (3, "cycle"),
    's': (4, "seed"),
    'x': (-1, "empty/ignore"), # Press 'x' to explicitly ignore this detection
    # Add others as needed...
}

BOX_COLOR = (0, 255, 0)
OTHER_COLOR = (255, 0, 0)

# Load the standard YOLOv8 Nano model (pretrained on COCO)
# We use this just to find "objects" - we don't care if it thinks they are donuts or clocks.
print("Loading YOLOv8 model for proposals...")
model = YOLO('yolov8n.pt')

def get_coin_proposals(image):
    """
    Uses a pre-trained YOLOv8 model to detect generic objects.
    This is often more robust than geometric circle detection because
    it detects 'object-ness' rather than just shapes.
    """
    # Run inference
    # classes=None : Detect everything (don't filter for specific classes yet)
    # agnostic_nms=True : Don't let multiple class boxes overlap on one object
    results = model(image, conf=CONFIDENCE_THRESHOLD, iou=0.4, agnostic_nms=True, verbose=False, classes=[74, 25])
    
    boxes = []
    
    # Extract bounding boxes from the first result (we only passed one image)
    for result in results:
        for box in result.boxes:
            # Get coordinates (x1, y1, x2, y2)
            x1, y1, x2, y2 = box.xyxy[0].cpu().numpy().astype(int)
            print(f"Class: {int(box.cls[0])} Conf: {float(box.conf[0]):.2f}")
            
            w = x2 - x1
            h = y2 - y1
            
            # Basic size filtering to ignore tiny noise or huge errors
            # Adjust these if your coins are smaller/larger in the image
            if w < 30 or h < 30: continue
            if w > 200 or h > 200: continue
            if min(w, h) / max(w, h) < 0.5: continue
            if w > image.shape[1] / 2: continue # Ignore massive boxes covering half screen
            
            boxes.append((x1, y1, w, h))
            
    return boxes

def save_yolo_label(image_filename, labels, image_shape):
    """
    Saves the list of labels to a .txt file in YOLO format.
    Format: class_id center_x center_y width height (normalized 0-1)
    """
    txt_filename = os.path.splitext(image_filename)[0] + ".txt"
    h_img, w_img = image_shape[:2]
    
    with open(txt_filename, 'w') as f:
        for (cls_id, x, y, w, h) in labels:
            # Normalize coordinates
            center_x = (x + w / 2) / w_img
            center_y = (y + h / 2) / h_img
            norm_w = w / w_img
            norm_h = h / h_img
            
            line = f"{cls_id} {center_x:.6f} {center_y:.6f} {norm_w:.6f} {norm_h:.6f}\n"
            f.write(line)
    
    print(f"Saved: {txt_filename}")

def main():
    if not os.path.exists(DATASET_DIR):
        print(f"Directory {DATASET_DIR} not found.")
        return

    images = [f for f in os.listdir(DATASET_DIR) if f.endswith('.jpg')]
    images.sort()

    print(f"Found {len(images)} images.")
    print("CONTROLS:")
    print(" [Key defined in MAPPING] : Assign Label")
    print(" [SPACE] : Skip/Ignore this proposal")
    print(" [ESC] : Quit")
    
    for img_file in images:
        full_path = os.path.join(DATASET_DIR, img_file)
        txt_path = os.path.splitext(full_path)[0] + ".txt"
        
        # Skip if already labeled
        if os.path.exists(txt_path):
            print(f"Skipping {img_file} (Already labeled)")
            continue
            
        img = cv2.imread(full_path)
        if img is None: continue
        
        # Get proposals from YOLO
        proposals = get_coin_proposals(img)
        current_labels = [] 
        
        print(f"Labeling {img_file}... Found {len(proposals)} proposals.")
        
        for i, box in enumerate(proposals):
            x, y, w, h = box
            
            while True:
                display = img.copy()
                
                # Draw all boxes in blue
                for bx in proposals:
                    bx_x, bx_y, bx_w, bx_h = bx
                    cv2.rectangle(display, (bx_x, bx_y), (bx_x+bx_w, bx_y+bx_h), OTHER_COLOR, 2)
                
                # Draw current target in GREEN
                cv2.rectangle(display, (x, y), (x+w, y+h), BOX_COLOR, 3)
                
                cv2.putText(display, f"Identify Proposal {i+1}/{len(proposals)}", (10, 30), 
                            cv2.FONT_HERSHEY_SIMPLEX, 0.7, BOX_COLOR, 2)
                
                y_offset = 60
                for k, v in KEY_MAPPING.items():
                    text = f"{k}: {v[1]}"
                    cv2.putText(display, text, (10, y_offset), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 255), 1)
                    y_offset += 20

                cv2.imshow("Auto Labeler (YOLO-Assisted)", display)
                key = cv2.waitKey(0)
                
                if key == 27: # ESC
                    return
                
                char = chr(key & 0xFF)
                
                if char == ' ': # SPACE to skip
                    print("Skipped.")
                    break 
                
                if char in KEY_MAPPING:
                    cls_id, cls_name = KEY_MAPPING[char]
                    
                    # Logic for "Empty/Ignore" category (ID = -1)
                    if cls_id == -1:
                        print(f"Marked as {cls_name} (Not saved).")
                        # Visual feedback: flash gray
                        cv2.rectangle(display, (x, y), (x+w, y+h), (128, 128, 128), -1)
                        cv2.imshow("Auto Labeler (YOLO-Assisted)", display)
                        cv2.waitKey(50)
                        break # Break logic loop, move to next proposal without saving

                    # Logic for valid labels
                    current_labels.append((cls_id, x, y, w, h))
                    print(f"Assigned: {cls_name}")
                    
                    cv2.rectangle(display, (x, y), (x+w, y+h), (0, 255, 0), -1)
                    cv2.imshow("Auto Labeler (YOLO-Assisted)", display)
                    cv2.waitKey(50) 
                    break 
                else:
                    print(f"Key '{char}' not mapped.")

        if current_labels:
            save_yolo_label(full_path, current_labels, img.shape)
        else:
            open(txt_path, 'w').close()

    cv2.destroyAllWindows()
    print("All images processed!")

if __name__ == "__main__":
    main()
