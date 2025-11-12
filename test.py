#!/usr/bin/env python3
import cv2
from pyzbar import pyzbar
import numpy as np
import re
import sys

def decode_qr_optimized(image_data):
    """
    Оптимизированное декодирование QR с помощью pyzbar
    Использует только самые эффективные методы
    """
    print(f"[DEBUG] Начало декодирования QR")
    sys.stdout.flush()
    
    # Читаем изображение
    try:
        if isinstance(image_data, (str, Path)):
            img = cv2.imread(str(image_data))
        else:
            nparr = np.frombuffer(image_data, np.uint8)
            img = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
        
        if img is None:
            print("[DEBUG] Не удалось декодировать изображение")
            sys.stdout.flush()
            return []
        
        print(f"[DEBUG] Изображение: {img.shape}")
        sys.stdout.flush()
    except Exception as e:
        print(f"[DEBUG] Ошибка: {e}")
        sys.stdout.flush()
        return []
    
    found_urls = set()
    found_data = set()
    
    def test_decode(image, method=""):
        barcodes = pyzbar.decode(image)
        for barcode in barcodes:
            if barcode.type == 'QRCODE':
                try:
                    data = barcode.data.decode('utf-8', errors='ignore')
                    if data not in found_data:
                        found_data.add(data)
                        print(f"[DEBUG] {method}: Найден QR")
                        sys.stdout.flush()
                        urls = re.findall(r"https?://[^\s]+", data)
                        for url in urls:
                            found_urls.add(url.rstrip(")\"'"))
                except:
                    pass
    
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    
    # 1. Оригинал
    test_decode(img, "Оригинал")
    test_decode(gray, "Grayscale")
    
    # 2. Масштабирование (проверенные эффективные масштабы)
    for scale in [0.5, 0.75, 1.0, 1.5, 2.0, 2.5]:
        w = int(img.shape[1] * scale)
        h = int(img.shape[0] * scale)
        if 50 < w < 5000 and 50 < h < 5000:
            scaled = cv2.resize(gray, (w, h), interpolation=cv2.INTER_CUBIC)
            test_decode(scaled, f"Масштаб {scale}")
    
    # 3. Повороты (каждые 15 градусов достаточно)
    for angle in range(0, 360, 15):
        if angle == 0:
            continue
        center = (gray.shape[1] // 2, gray.shape[0] // 2)
        M = cv2.getRotationMatrix2D(center, angle, 1.0)
        rotated = cv2.warpAffine(gray, M, (gray.shape[1], gray.shape[0]))
        test_decode(rotated, f"Поворот {angle}°")
    
    # 4. CLAHE (улучшает контраст)
    for clip in [2.0, 3.0]:
        clahe = cv2.createCLAHE(clipLimit=clip, tileGridSize=(8, 8))
        enhanced = clahe.apply(gray)
        test_decode(enhanced, f"CLAHE {clip}")
    
    # 5. Морфологические операции (это помогло!)
    for ksize in [3, 5, 7]:
        kernel = np.ones((ksize, ksize), np.uint8)
        # Открытие (убирает мелкий шум)
        opened = cv2.morphologyEx(gray, cv2.MORPH_OPEN, kernel)
        test_decode(opened, f"Open {ksize}")
        # Закрытие (заполняет дырки)
        closed = cv2.morphologyEx(gray, cv2.MORPH_CLOSE, kernel)
        test_decode(closed, f"Close {ksize}")
    
    # 6. Адаптивная бинаризация
    for block in [11, 21, 31, 41]:
        for C in [2, 5, 10]:
            try:
                binary = cv2.adaptiveThreshold(gray, 255, 
                                              cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
                                              cv2.THRESH_BINARY, block, C)
                test_decode(binary, f"Bin {block}/{C}")
                test_decode(cv2.bitwise_not(binary), f"Inv {block}/{C}")
            except:
                pass
    
    # 7. OTSU
    _, otsu = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    test_decode(otsu, "OTSU")
    test_decode(cv2.bitwise_not(otsu), "OTSU inv")
    
    # 8. Bilateral filter (убирает шум, сохраняет края)
    bilateral = cv2.bilateralFilter(gray, 9, 75, 75)
    test_decode(bilateral, "Bilateral")
    
    # 9. Увеличение резкости
    kernel_sharp = np.array([[-1,-1,-1], [-1,9,-1], [-1,-1,-1]])
    sharpened = cv2.filter2D(gray, -1, kernel_sharp)
    test_decode(sharpened, "Sharp")
    
    # 10. Гамма-коррекция
    for gamma in [0.5, 1.5, 2.0]:
        invGamma = 1.0 / gamma
        table = np.array([((i / 255.0) ** invGamma) * 255 
                         for i in range(256)]).astype("uint8")
        gamma_img = cv2.LUT(gray, table)
        test_decode(gamma_img, f"Gamma {gamma}")
    
    # 11. Эквализация гистограммы
    equalized = cv2.equalizeHist(gray)
    test_decode(equalized, "Equalize")
    
    # 12. Разделение на части (если несколько QR)
    h, w = gray.shape
    parts = [
        gray[:h//2, :],      # Верх
        gray[h//2:, :],      # Низ
        gray[:, :w//2],      # Лево
        gray[:, w//2:],      # Право
    ]
    for i, part in enumerate(parts):
        test_decode(part, f"Часть {i+1}")
    
    print(f"[DEBUG] Найдено уникальных QR: {len(found_data)}, URL: {len(found_urls)}")
    sys.stdout.flush()
    
    return list(found_urls)