# NVIDIA Jetson Deployment Guide (Coin Project)

This guide assumes you have a Jetson Xavier NX or AGX Xavier running JetPack 5.x (Ubuntu 20.04).

## Step 1: System Dependencies

Update your system and install libraries required for OpenCV and PyTorch.

```bash
sudo apt-get update
sudo apt-get install python3-pip libopenblas-base libopenmpi-dev libomp-dev
sudo apt-get install libjpeg-dev zlib1g-dev libpython3-dev libavcodec-dev libavformat-dev
```

## Step 2: Install PyTorch & Torchvision (Jetson Version)

Do not simply run pip install torch. You must use NVIDIA's pre-built wheels.

Install PyTorch (v2.1.0 for JetPack 5.1):

```bash
wget [https://developer.download.nvidia.com/compute/redist/jp/v51/pytorch/torch-2.1.0a0+41361538.nv23.06-cp38-cp38-linux_aarch64.whl](https://developer.download.nvidia.com/compute/redist/jp/v51/pytorch/torch-2.1.0a0+41361538.nv23.06-cp38-cp38-linux_aarch64.whl)
pip3 install torch-2.1.0a0+41361538.nv23.06-cp38-cp38-linux_aarch64.whl
```

(Note: If you are on a different JetPack version, check NVIDIA's PyTorch catalog for the correct link.)

Install Torchvision (Must compile from source to match PyTorch):

```bash
git clone --branch v0.16.0 [https://github.com/pytorch/vision](https://github.com/pytorch/vision) torchvision   # v0.16 corresponds to PyTorch 2.1
cd torchvision
export BUILD_VERSION=0.16.0
python3 setup.py install --user
cd ..
```


## Step 3: Install Ultralytics (YOLO)

Now we install YOLO. Since we already installed torch manually, we tell pip to ignore dependencies to avoid breaking our setup.

```bash
pip3 install ultralytics --no-deps
pip3 install pandas psutil seaborn tqdm matplotlib scipy   # Install other dependencies manually
```


## Step 4: Transfer Your Files

Copy the following files from your PC to a folder on the Jetson (e.g., ~/coin_project/):

```runs/detect/coin_model_v1/weights/best.pt (Your trained model)

calibration_matrix.json (Your board calibration)

jetson_app.py (The script below)```

## Step 5: Export to TensorRT (.engine)

This is the most critical step for speed. We convert the PyTorch model (.pt) to a TensorRT Engine (.engine) optimized for the Xavier's GPU.
Run this command on the Jetson inside your project folder:

```bash
yolo export model=best.pt format=engine device=0
```

This will take 2-5 minutes. It will produce a file named best.engine.

## Step 6: Maximize Performance

Turn on the fans and set the Jetson to maximum power mode.

sudo jetson_clocks


## Step 7: Run the App

```bash
python3 jetson_app.py
```
