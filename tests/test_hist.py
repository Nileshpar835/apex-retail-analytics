import cv2
import numpy as np
import matplotlib.pyplot as plt
from pathlib import Path

# Load a test image
img_path = Path("E:/curs/store-intelligence/data/image.png")
if img_path.exists():
    frame = cv2.imread(str(img_path))
    
    # Define a bbox (person region)
    x1, y1, x2, y2 = 100, 100, 300, 400
    person_crop = frame[y1:y2, x1:x2]
    
    # Convert to HSV
    hsv = cv2.cvtColor(person_crop, cv2.COLOR_BGR2HSV)
    
    # Histograms
    hist_h = cv2.calcHist([hsv], [0], None, [8], [0, 180])
    hist_s = cv2.calcHist([hsv], [1], None, [8], [0, 256])
    hist_v = cv2.calcHist([hsv], [2], None, [8], [0, 256])
    
    hist_h = cv2.normalize(hist_h, hist_h).flatten()
    hist_s = cv2.normalize(hist_s, hist_s).flatten()
    hist_v = cv2.normalize(hist_v, hist_v).flatten()
    
    # Plot
    fig, axes = plt.subplots(2, 2, figsize=(12, 8))
    
    axes[0, 0].imshow(cv2.cvtColor(person_crop, cv2.COLOR_BGR2RGB))
    axes[0, 0].set_title("Person Region")
    
    axes[0, 1].bar(range(8), hist_h, color='red')
    axes[0, 1].set_title("Hue (Color)")
    
    axes[1, 0].bar(range(8), hist_s, color='green')
    axes[1, 0].set_title("Saturation (Colorfulness)")
    
    axes[1, 1].bar(range(8), hist_v, color='blue')
    axes[1, 1].set_title("Value (Brightness)")
    
    plt.tight_layout()
    plt.savefig("histogram_test.png")
    print("Saved histogram_test.png")
else:
    print(f"Test image not found: {img_path}")