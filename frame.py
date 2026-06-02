import cv2
import numpy as np
from ultralytics import YOLO
import os

model = YOLO(r'E:\store-intelligence (4)\store-intelligence\yolov8n.pt')
os.makedirs(r'E:\store-intelligence (4)\store-intelligence\annotated', exist_ok=True)

def is_black_uniform(frame, x1,y1,x2,y2):
    x1,y1,x2,y2 = max(0,int(x1)),max(0,int(y1)),min(frame.shape[1]-1,int(x2)),min(frame.shape[0]-1,int(y2))
    if x2<=x1 or y2<=y1: return False
    h = y2-y1
    if h < 15: return False
    crop = frame[y1:y2, x1:x2]
    hsv = cv2.cvtColor(crop, cv2.COLOR_BGR2HSV)
    black = cv2.inRange(hsv, np.array([0,0,0]), np.array([180,80,80]))
    torso = black[:int(h*0.5),:]
    lower = black[int(h*0.55):,:]
    tr = torso.sum()/(255*max(torso.size,1))
    lr = lower.sum()/(255*max(lower.size,1))
    return bool(tr > 0.42 and lr > 0.32)

CAMERAS = {
    'CAM_1': {
        'path': r'E:\store-intelligence (4)\store-intelligence\data\CCTV\CAM 1.mp4',
        'zones': [
            {'id':'FARMSTAY','label':'FarmStay','c':(50,100,255),'pts':np.array([(0,60),(350,60),(350,620),(0,620)])},
            {'id':'FACESHOP','label':'The Face Shop','c':(50,200,50),'pts':np.array([(350,60),(720,60),(720,620),(350,620)])},
            {'id':'GOODVIBES','label':'GoodVibes/DermaCo','c':(200,50,200),'pts':np.array([(720,60),(1020,60),(1020,620),(720,620)])},
            {'id':'MINIMALIST','label':'Minimalist','c':(255,150,0),'pts':np.array([(1020,60),(1300,60),(1300,620),(1020,620)])},
            {'id':'DERMDOC','label':'DermDoc','c':(0,220,220),'pts':np.array([(1300,60),(1600,60),(1600,620),(1300,620)])},
            {'id':'CENTER','label':'Center Display','c':(255,255,0),'pts':np.array([(430,650),(1080,650),(1080,1080),(430,1080)])},
        ], 'line': None
    },
    'CAM_2': {
        'path': r'E:\store-intelligence (4)\store-intelligence\data\CCTV\CAM 2.mp4',
        'zones': [
            {'id':'ACCESSORIES','label':'Accessories','c':(200,200,0),'pts':np.array([(0,80),(340,80),(340,900),(0,900)])},
            {'id':'ALPS_LOREAL','label':"Alps/L'Oreal",'c':(255,80,80),'pts':np.array([(340,80),(620,80),(620,760),(340,760)])},
            {'id':'6MARS_SWISS','label':'6Mars/Swiss','c':(80,255,80),'pts':np.array([(620,80),(840,80),(840,760),(620,760)])},
            {'id':'LAKME','label':'Lakme','c':(255,160,0),'pts':np.array([(840,80),(1060,80),(1060,760),(840,760)])},
            {'id':'FACES_MAYB','label':'Faces/Maybelline','c':(160,0,255),'pts':np.array([(1060,80),(1600,80),(1600,760),(1060,760)])},
            {'id':'FLOOR_DISP','label':'Floor Display','c':(0,200,255),'pts':np.array([(340,760),(980,760),(980,1080),(340,1080)])},
        ], 'line': None
    },
    'CAM_3': {
        'path': r'E:\store-intelligence (4)\store-intelligence\data\CCTV\CAM 3.mp4',
        'zones': [
            {'id':'INSIDE','label':'Store Interior','c':(0,255,100),'pts':np.array([(50,80),(1450,80),(1450,560),(50,560)])},
            {'id':'THRESHOLD','label':'Entry Threshold','c':(0,255,255),'pts':np.array([(180,510),(1320,510),(1320,680),(180,680)])},
            {'id':'OUTSIDE','label':'Outside','c':(0,50,255),'pts':np.array([(50,680),(1450,680),(1450,1060),(50,1060)])},
        ], 'line': 580  # y-pixel of entry line
    },
    'CAM_4': {
        'path': r'E:\store-intelligence (4)\store-intelligence\data\CCTV\CAM 4.mp4',
        'zones': [
            {'id':'SHELF_L','label':'Stock Shelves','c':(200,100,0),'pts':np.array([(0,80),(280,80),(280,970),(0,970)])},
            {'id':'WORK_FLOOR','label':'Work Floor','c':(0,180,180),'pts':np.array([(280,350),(950,350),(950,970),(280,970)])},
            {'id':'SHELF_R','label':'Shelf Right','c':(180,0,180),'pts':np.array([(920,80),(1920,80),(1920,660),(920,660)])},
            {'id':'DOOR','label':'Backroom Entry','c':(255,200,0),'pts':np.array([(280,80),(920,80),(920,350),(280,350)])},
        ], 'line': None
    },
    'CAM_5': {
        'path': r'E:\store-intelligence (4)\store-intelligence\data\CCTV\CAM 5.mp4',
        'zones': [
            {'id':'COUNTER','label':'Billing Counter','c':(255,100,0),'pts':np.array([(0,80),(640,80),(640,620),(0,620)])},
            {'id':'QUEUE','label':'Queue Area','c':(255,255,0),'pts':np.array([(0,620),(700,620),(700,1080),(0,1080)])},
            {'id':'APPROACH','label':'Approach','c':(0,255,200),'pts':np.array([(640,80),(1080,80),(1080,700),(640,700)])},
        ], 'line': None
    },
}

def draw_zones(frame, zones, alpha=0.22):
    overlay = frame.copy()
    for z in zones:
        pts = z['pts'].reshape((-1,1,2)).astype(np.int32)
        cv2.fillPoly(overlay, [pts], z['c'])
    cv2.addWeighted(overlay, alpha, frame, 1-alpha, 0, frame)
    for z in zones:
        pts = z['pts'].reshape((-1,1,2)).astype(np.int32)
        cv2.polylines(frame, [pts], True, z['c'], 2)
        cx = int(z['pts'][:,0].mean())
        cy = int(z['pts'][:,1].mean())
        cv2.putText(frame, z['label'], (cx-50, cy), cv2.FONT_HERSHEY_SIMPLEX, 0.55, z['c'], 2)

for cam_id, cfg in CAMERAS.items():
    cap = cv2.VideoCapture(cfg['path'])
    total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    cap.set(cv2.CAP_PROP_POS_FRAMES, total//3)
    ok, frame = cap.read()
    if not ok:
        cap.release()
        continue
    
    draw_zones(frame, cfg['zones'])
    
    # Draw entry line for CAM_3
    if cfg.get('line'):
        ly = cfg['line']
        cv2.line(frame, (100, ly), (1820, ly), (0,255,0), 3)
        cv2.putText(frame, 'ENTRY/EXIT LINE', (800, ly-10), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0,255,0), 2)
    
    # Run detection on this frame
    res = model(frame, classes=[0], conf=0.28, verbose=False)
    if res and res[0].boxes is not None:
        for box in res[0].boxes:
            x1,y1,x2,y2 = [int(v) for v in box.xyxy[0].tolist()]
            conf = float(box.conf[0])
            staff = is_black_uniform(frame, x1,y1,x2,y2)
            color = (0,0,220) if staff else (0,220,0)
            label = f"STAFF {conf:.2f}" if staff else f"CUST {conf:.2f}"
            cv2.rectangle(frame, (x1,y1), (x2,y2), color, 2)
            cv2.rectangle(frame, (x1,y1-22), (x1+len(label)*10, y1), color, -1)
            cv2.putText(frame, label, (x1+2,y1-5), cv2.FONT_HERSHEY_SIMPLEX, 0.55, (255,255,255), 1)
    
        out = f'E:\\store-intelligence (4)\\store-intelligence\\annotated\\{cam_id}.jpg'
        cv2.imwrite(out, frame, [cv2.IMWRITE_JPEG_QUALITY, 90])
        print(f"Saved {out}")
        cap.release()

print("All annotated frames saved")