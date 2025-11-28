import os
import shutil
import random
import yaml
from ultralytics import YOLO

# --- CONFIGURATION ---
RAW_DATA_DIR = "./dataset_raw"
PROJECT_DIR = "coin_project_v1"  # Where formatted data and models will be saved
TRAIN_RATIO = 0.8                # 80% training, 20% validation

# IMPORTANT: This must match the KEY_MAPPING from your auto_labeler.py
# The order (indices 0, 1, 2...) is critical.
CLASS_NAMES = {
    0: "gold",
    1: "spice",
    2: "deer",
    3: "man",
    4: "tree",
    # Add the rest of your classes here to match your dataset...
}

def setup_directories():
    """Creates the standard YOLO directory structure."""
    if os.path.exists(PROJECT_DIR):
        print(f"Warning: {PROJECT_DIR} already exists. Merging/Overwriting...")
    
    # YOLO expects:
    # project/
    #   train/images, train/labels
    #   val/images, val/labels
    for split in ['train', 'val']:
        os.makedirs(os.path.join(PROJECT_DIR, split, 'images'), exist_ok=True)
        os.makedirs(os.path.join(PROJECT_DIR, split, 'labels'), exist_ok=True)

def split_dataset():
    """Splits the raw images/txt files into train and val sets."""
    print("Organizing dataset...")
    
    # Get all pairs of (jpg, txt)
    files = [f for f in os.listdir(RAW_DATA_DIR) if f.endswith('.jpg')]
    # Filter out images that don't have a corresponding label file (if any)
    valid_files = [f for f in files if os.path.exists(os.path.join(RAW_DATA_DIR, f.replace('.jpg', '.txt')))]
    
    random.shuffle(valid_files)
    
    split_idx = int(len(valid_files) * TRAIN_RATIO)
    train_files = valid_files[:split_idx]
    val_files = valid_files[split_idx:]
    
    def copy_files(file_list, split_name):
        for filename in file_list:
            # Source paths
            src_img = os.path.join(RAW_DATA_DIR, filename)
            src_lbl = os.path.join(RAW_DATA_DIR, filename.replace('.jpg', '.txt'))
            
            # Dest paths
            dst_img = os.path.join(PROJECT_DIR, split_name, 'images', filename)
            dst_lbl = os.path.join(PROJECT_DIR, split_name, 'labels', filename.replace('.jpg', '.txt'))
            
            shutil.copy(src_img, dst_img)
            shutil.copy(src_lbl, dst_lbl)
            
    copy_files(train_files, 'train')
    copy_files(val_files, 'val')
    
    print(f"Dataset split: {len(train_files)} training, {len(val_files)} validation.")

def create_yaml_config():
    """Generates the data.yaml file required by YOLO."""
    # Convert absolute path for safety
    abs_path = os.path.abspath(PROJECT_DIR)
    
    data_yaml = {
        'path': abs_path,
        'train': 'train/images',
        'val': 'val/images',
        'names': CLASS_NAMES
    }
    
    yaml_path = os.path.join(PROJECT_DIR, 'data.yaml')
    with open(yaml_path, 'w') as f:
        yaml.dump(data_yaml, f, sort_keys=False)
    
    return yaml_path

def train():
    setup_directories()
    split_dataset()
    yaml_path = create_yaml_config()
    
    print("--- STARTING TRAINING ---")
    print("Using Transfer Learning on YOLOv8 Nano...")
    
    # Load the pretrained model (Transfer Learning)
    model = YOLO('yolov8n.pt') 
    
    # Train the model
    # imgsz=640: Standard YOLO resolution
    # epochs=100: Standard starting point, it stops early if it stops learning
    # batch=16: Good for most GPUs. Reduce to 8 if you run out of memory.
    model.train(
        data=yaml_path,
        epochs=100,
        imgsz=640,
        batch=16,
        name='coin_model_v1'
    )
    
    print("Training Complete!")
    print(f"Best model saved to: runs/detect/coin_model_v1/weights/best.pt")

if __name__ == "__main__":
    train()