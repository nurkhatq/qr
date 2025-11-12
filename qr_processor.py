#!/usr/bin/env python3
import os
import re
import io
import json
import sys
from pathlib import Path
from datetime import datetime
import requests
import cv2
from pyzbar import pyzbar
import pdfplumber
import pandas as pd
import numpy as np
import gspread
from google.oauth2.service_account import Credentials

# --- Настройки ---
USER_AGENT = "qr-to-csv-bot/1.1"
SPREADSHEET_NAME = "QR Data"

# ---------------- Google Sheets ----------------

def get_google_sheets_client():
    """Подключение к Google Sheets"""
    scopes = [
        'https://www.googleapis.com/auth/spreadsheets',
        'https://www.googleapis.com/auth/drive'
    ]
    
    try:
        import streamlit as st
        if hasattr(st, 'secrets') and 'gcp_service_account' in st.secrets:
            credentials_dict = dict(st.secrets["gcp_service_account"])
            creds = Credentials.from_service_account_info(credentials_dict, scopes=scopes)
        else:
            creds = Credentials.from_service_account_file('credentials.json', scopes=scopes)
    except:
        creds = Credentials.from_service_account_file('credentials.json', scopes=scopes)
    
    client = gspread.authorize(creds)
    return client

def update_google_sheet(df, sheet_name=SPREADSHEET_NAME):
    """Обновляет Google Sheets данными"""
    try:
        client = get_google_sheets_client()
        
        try:
            spreadsheet = client.open(sheet_name)
        except gspread.SpreadsheetNotFound:
            spreadsheet = client.create(sheet_name)
            spreadsheet.share('', perm_type='anyone', role='reader')
            print(f"[+] Создана новая таблица: {sheet_name}")
        
        try:
            worksheet = spreadsheet.worksheet("QR Data")
        except gspread.WorksheetNotFound:
            worksheet = spreadsheet.add_worksheet(title="QR Data", rows="1000", cols="20")
        
        existing_data = worksheet.get_all_values()
        
        columns_order = ["uploaded_date", "pdf_date", "source_pdf", "seq", "place_number", "weight", "order"]
        df_ordered = df[columns_order].copy()
        
        if not existing_data or len(existing_data) == 0:
            headers = ["Дата загрузки", "Дата приема-передачи", "Источник PDF", "№ п/п", "Номер места", "Вес", "Заказ"]
            data_to_append = [headers] + df_ordered.values.tolist()
            worksheet.update('A1', data_to_append, value_input_option='USER_ENTERED')
            print(f"[+] Добавлено {len(df)} новых строк в Google Sheets")
        else:
            existing_df = pd.DataFrame(existing_data[1:], columns=existing_data[0])
            
            new_rows = []
            for _, row in df_ordered.iterrows():
                is_duplicate = False
                for _, existing_row in existing_df.iterrows():
                    if (str(row['place_number']) == str(existing_row.get(existing_data[0][4] if len(existing_data[0]) > 4 else '', '')) and 
                        str(row['order']) == str(existing_row.get(existing_data[0][6] if len(existing_data[0]) > 6 else '', ''))):
                        is_duplicate = True
                        break
                if not is_duplicate:
                    new_rows.append(row.tolist())
            
            if new_rows:
                worksheet.append_rows(new_rows, value_input_option='USER_ENTERED')
                print(f"[+] Добавлено {len(new_rows)} новых строк в Google Sheets")
            else:
                print("[i] Новых данных для добавления нет")
        
        print(f"[+] Ссылка на таблицу: {spreadsheet.url}")
        return spreadsheet.url
        
    except Exception as e:
        print(f"[!] Ошибка при работе с Google Sheets: {e}")
        raise

# ---------------- Функции обработки QR ----------------

def decode_qr_from_image(image_data):
    """
    Оптимизированное декодирование QR с помощью pyzbar
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
    
    # 2. Масштабирование
    for scale in [0.5, 0.75, 1.0, 1.5, 2.0, 2.5]:
        w = int(img.shape[1] * scale)
        h = int(img.shape[0] * scale)
        if 50 < w < 5000 and 50 < h < 5000:
            scaled = cv2.resize(gray, (w, h), interpolation=cv2.INTER_CUBIC)
            test_decode(scaled, f"Масштаб {scale}")
    
    # 3. Повороты
    for angle in range(0, 360, 15):
        if angle == 0:
            continue
        center = (gray.shape[1] // 2, gray.shape[0] // 2)
        M = cv2.getRotationMatrix2D(center, angle, 1.0)
        rotated = cv2.warpAffine(gray, M, (gray.shape[1], gray.shape[0]))
        test_decode(rotated, f"Поворот {angle}°")
    
    # 4. CLAHE
    for clip in [2.0, 3.0]:
        clahe = cv2.createCLAHE(clipLimit=clip, tileGridSize=(8, 8))
        enhanced = clahe.apply(gray)
        test_decode(enhanced, f"CLAHE {clip}")
    
    # 5. Морфологические операции
    for ksize in [3, 5, 7]:
        kernel = np.ones((ksize, ksize), np.uint8)
        opened = cv2.morphologyEx(gray, cv2.MORPH_OPEN, kernel)
        test_decode(opened, f"Open {ksize}")
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
    
    # 8. Bilateral filter
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
    
    # 11. Эквализация
    equalized = cv2.equalizeHist(gray)
    test_decode(equalized, "Equalize")
    
    # 12. Разделение на части
    h, w = gray.shape
    test_decode(gray[:h//2, :], "Верх")
    test_decode(gray[h//2:, :], "Низ")
    test_decode(gray[:, :w//2], "Лево")
    test_decode(gray[:, w//2:], "Право")
    
    print(f"[DEBUG] Найдено уникальных QR: {len(found_data)}, URL: {len(found_urls)}")
    sys.stdout.flush()
    
    return list(found_urls)

def download_pdf_to_memory(url, timeout=30):
    """Скачивает PDF в память и возвращает байты"""
    print(f"[DEBUG] Скачивание PDF...")
    sys.stdout.flush()
    headers = {"User-Agent": USER_AGENT}
    try:
        r = requests.get(url, headers=headers, timeout=timeout)
        r.raise_for_status()
        print(f"[DEBUG] PDF скачан: {len(r.content)} байт")
        sys.stdout.flush()
        return r.content
    except Exception as e:
        print(f"[!] Ошибка при скачивании: {e}")
        sys.stdout.flush()
        raise

def extract_pdf_date(pdf_bytes):
    """Извлекает дату приема-передачи из PDF"""
    try:
        with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
            for page in pdf.pages:
                text = page.extract_text()
                if text:
                    match = re.search(r'Дата\s+приёма[-­\s]*передачи[:\s]+(\d{2}\.\d{2}\.\d{4}\s+\d{2}:\d{2}:\d{2})', text, re.IGNORECASE)
                    if match:
                        return match.group(1)
                    match = re.search(r'(\d{2}\.\d{2}\.\d{4}\s+\d{2}:\d{2}:\d{2})', text)
                    if match:
                        return match.group(1)
    except:
        pass
    return ""

def extract_table_rows_from_pdf(pdf_bytes, source_name):
    """Извлекает строки таблицы из PDF"""
    print(f"[DEBUG] Извлечение данных из PDF")
    sys.stdout.flush()
    rows = []
    pdf_date = extract_pdf_date(pdf_bytes)
    
    try:
        with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
            for page in pdf.pages:
                try:
                    tables = page.extract_tables()
                except Exception:
                    tables = None
                
                if tables:
                    for table in tables:
                        for trow in table:
                            if not any(cell and str(cell).strip() for cell in (trow or [])):
                                continue
                            rows.append({
                                "source_pdf": source_name,
                                "pdf_date": pdf_date,
                                "raw_cells": [("" if c is None else str(c).strip()) for c in trow]
                            })
                
                text = page.extract_text()
                if text:
                    for line in text.splitlines():
                        line = line.strip()
                        if re.match(r'^\d+\s+\S+', line):
                            rows.append({
                                "source_pdf": source_name,
                                "pdf_date": pdf_date,
                                "raw_text": line
                            })
        print(f"[DEBUG] Извлечено строк: {len(rows)}")
        sys.stdout.flush()
    except Exception as e:
        print(f"[!] Ошибка при чтении PDF: {e}")
        sys.stdout.flush()
        raise
    
    return rows

def normalize_row(item):
    """Превращает строку из PDF в нормальные колонки"""
    src = item.get("source_pdf", "")
    pdf_date = item.get("pdf_date", "")
    raw = item.get("raw_text") or " | ".join(item.get("raw_cells", []))
    raw = raw.replace("\u00ad", "-").strip()
    
    if re.search(r"№\s*п/п|Номер места|Вес|Заказ", raw, re.IGNORECASE):
        return None
    
    if item.get("raw_cells"):
        cells = [("" if c is None else str(c).strip().replace("\u00ad", "-")) for c in item["raw_cells"]]
        if len(cells) >= 3:
            seq = cells[0]
            place = cells[1]
            weight = cells[2]
            order = " ".join(cells[3:]) if len(cells) > 3 else ""
            order = re.sub(r'\s+', '', order)
            return {
                "source_pdf": src,
                "pdf_date": pdf_date,
                "seq": seq,
                "place_number": place,
                "weight": weight,
                "order": order
            }
    
    tokens = re.split(r'\s+', raw)
    if len(tokens) >= 4:
        seq = tokens[0]
        place = tokens[1]
        weight = tokens[2]
        order = " ".join(tokens[3:])
        order = re.sub(r'\s+', '', order)
        return {
            "source_pdf": src,
            "pdf_date": pdf_date,
            "seq": seq,
            "place_number": place,
            "weight": weight,
            "order": order
        }
    
    return None

def process_single_image(image_data, filename):
    """
    Обрабатывает одно изображение и возвращает результат
    Возвращает: (success, qr_count, rows, error_message)
    """
    print(f"[DEBUG] ========== Начало обработки: {filename} ==========")
    sys.stdout.flush()
    
    try:
        urls = decode_qr_from_image(image_data)
        qr_count = len(urls)
        
        print(f"[DEBUG] Найдено QR кодов: {qr_count}")
        sys.stdout.flush()
        
        if not urls:
            return True, 0, [], None
        
        all_rows = []
        
        for idx, url in enumerate(urls):
            try:
                print(f"[DEBUG] Обработка QR #{idx+1}/{qr_count}")
                sys.stdout.flush()
                
                pdf_bytes = download_pdf_to_memory(url)
                source_name = f"{filename}_QR{idx+1}.pdf"
                items = extract_table_rows_from_pdf(pdf_bytes, source_name)
                
                normalized_count = 0
                for item in items:
                    normalized = normalize_row(item)
                    if normalized:
                        all_rows.append(normalized)
                        normalized_count += 1
                
                print(f"[DEBUG] QR #{idx+1}: Нормализовано {normalized_count} строк")
                sys.stdout.flush()
            
            except Exception as e:
                print(f"[!] Ошибка обработки QR #{idx+1}: {e}")
                sys.stdout.flush()
                continue
        
        print(f"[DEBUG] ========== Завершено: {filename}, всего строк: {len(all_rows)} ==========")
        sys.stdout.flush()
        return True, qr_count, all_rows, None
    
    except Exception as e:
        print(f"[DEBUG] ========== ОШИБКА: {filename} ==========")
        sys.stdout.flush()
        import traceback
        error_trace = traceback.format_exc()
        print(error_trace)
        sys.stdout.flush()
        return False, 0, [], str(e)