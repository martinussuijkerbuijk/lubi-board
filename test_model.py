from ultralytics import YOLO
model = YOLO("runs/detect/coin_model_v2/weights/best.pt")
results = model("dataset_raw/img_150.jpg", conf=0.1)
for r in results:
	for box in r.boxes:
		print(r.names[int(box.cls[0])], float(box.conf[0]))
