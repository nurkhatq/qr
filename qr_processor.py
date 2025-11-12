#!/usr/bin/env python3
import os
import re
import io
import json
from pathlib import Path
from datetime import datetime
import requests
import cv2
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
    
    # Для Streamlit Cloud используем secrets
    try:
        import streamlit as st
        if hasattr(st, 'secrets') and 'gcp_service_account' in st.secrets:
            credentials_dict = dict(st.secrets["gcp_service_account"])
            creds = Credentials.from_service_account_info(credentials_dict, scopes=scopes)
        else:
            # Локальная разработка
            creds = Credentials.from_service_account_file('credentials.json', scopes=scopes)
    except:
        # Локальная разработка
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
            # Делаем таблицу публичной для чтения
            spreadsheet.share('', perm_type='anyone', role='reader')
            print(f"[+] Создана новая таблица: {sheet_name}")
        
        try:
            worksheet = spreadsheet.worksheet("QR Data")
        except gspread.WorksheetNotFound:
            worksheet = spreadsheet.add_worksheet(title="QR Data", rows="1000", cols="20")
        
        existing_data = worksheet.get_all_values()
        
        # Подготавливаем данные с заголовками
        columns_order = ["uploaded_date", "pdf_date", "source_pdf", "seq", "place_number", "weight", "order"]
        df_ordered = df[columns_order].copy()
        
        if not existing_data or len(existing_data) == 0:
            # Первая запись - добавляем заголовки
            headers = ["Дата загрузки", "Дата приема-передачи", "Источник PDF", "№ п/п", "Номер места", "Вес", "Заказ"]
            data_to_append = [headers] + df_ordered.values.tolist()
            worksheet.update('A1', data_to_append, value_input_option='USER_ENTERED')
            print(f"[+] Добавлено {len(df)} новых строк в Google Sheets")
        else:
            # Есть данные - добавляем только новые строки
            existing_df = pd.DataFrame(existing_data[1:], columns=existing_data[0])
            
            # Находим строки, которых еще нет
            new_rows = []
            for _, row in df_ordered.iterrows():
                is_duplicate = False
                for _, existing_row in existing_df.iterrows():
                    # Проверяем по номеру места и заказу
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
    Извлекает все QR-коды из изображения.
    image_data: путь к файлу или bytes
    """
    # Читаем изображение
    if isinstance(image_data, (str, Path)):
        img = cv2.imread(str(image_data))
    else:
        nparr = np.frombuffer(image_data, np.uint8)
        img = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
    
    if img is None:
        return []
    
    urls = set()
    detector = cv2.QRCodeDetector()
    
    def try_detect(image):
        try:
            retval, decoded_info, points, _ = detector.detectAndDecodeMulti(image)
            if retval and decoded_info:
                for data in decoded_info:
                    if data:
                        matches = re.findall(r"https?://[^\s]+", data)
                        for m in matches:
                            urls.add(m.rstrip(")\"'"))
            return len(decoded_info) if retval else 0
        except:
            return 0
    
    # 1. Оригинал
    try_detect(img)
    
    # 2. Grayscale
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    try_detect(gray)
    
    # 3. Масштабирование
    for scale in [0.5, 1.5, 2.0]:
        width = int(img.shape[1] * scale)
        height = int(img.shape[0] * scale)
        scaled = cv2.resize(img, (width, height), interpolation=cv2.INTER_LINEAR)
        try_detect(scaled)
    
    # 4. Бинаризация
    for block_size in [11, 21, 31]:
        try:
            binary = cv2.adaptiveThreshold(gray, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, 
                                          cv2.THRESH_BINARY, block_size, 5)
            try_detect(binary)
            try_detect(cv2.bitwise_not(binary))
        except:
            pass
    
    # 5. OTSU
    try:
        _, otsu = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
        try_detect(otsu)
    except:
        pass
    
    # 6. CLAHE
    try:
        clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8,8))
        enhanced = clahe.apply(gray)
        try_detect(enhanced)
    except:
        pass
    
    # 7. Разделение на части
    h, w = img.shape[:2]
    parts = [
        img[0:h//2, :],
        img[h//2:h, :],
        img[:, 0:w//2],
        img[:, w//2:w],
    ]
    for part in parts:
        try_detect(part)
    
    return list(urls)

def download_pdf_to_memory(url, timeout=30):
    """Скачивает PDF в память и возвращает байты"""
    headers = {"User-Agent": USER_AGENT}
    try:
        r = requests.get(url, headers=headers, timeout=timeout)
        r.raise_for_status()
        return r.content
    except Exception as e:
        print(f"[!] Ошибка при скачивании {url}: {e}")
        raise

def extract_pdf_date(pdf_bytes):
    """Извлекает дату приема-передачи из PDF"""
    try:
        with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
            for page in pdf.pages:
                text = page.extract_text()
                if text:
                    # Ищем дату после "Дата приёма-передачи:" или "Дата приема-передачи:"
                    match = re.search(r'Дата\s+приёма[-­\s]*передачи[:\s]+(\d{2}\.\d{2}\.\d{4}\s+\d{2}:\d{2}:\d{2})', text, re.IGNORECASE)
                    if match:
                        return match.group(1)
                    
                    # Альтернативный формат
                    match = re.search(r'(\d{2}\.\d{2}\.\d{4}\s+\d{2}:\d{2}:\d{2})', text)
                    if match:
                        return match.group(1)
    except:
        pass
    return ""

def extract_table_rows_from_pdf(pdf_bytes, source_name):
    """Извлекает строки таблицы из PDF (из памяти)"""
    rows = []
    pdf_date = extract_pdf_date(pdf_bytes)
    
    try:
        with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
            for page in pdf.pages:
                # Извлечение таблиц
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
                
                # Извлечение текста
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
    except Exception as e:
        print(f"[!] Ошибка при чтении PDF: {e}")
        raise
    
    return rows

def normalize_row(item):
    """Превращает строку из PDF в нормальные колонки"""
    src = item.get("source_pdf", "")
    pdf_date = item.get("pdf_date", "")
    raw = item.get("raw_text") or " | ".join(item.get("raw_cells", []))
    raw = raw.replace("\u00ad", "-").strip()
    
    # Пропускаем заголовки
    if re.search(r"№\s*п/п|Номер места|Вес|Заказ", raw, re.IGNORECASE):
        return None
    
    # Таблица
    if item.get("raw_cells"):
        cells = [("" if c is None else str(c).strip().replace("\u00ad", "-")) for c in item["raw_cells"]]
        if len(cells) >= 3:
            seq = cells[0]
            place = cells[1]
            weight = cells[2]
            order = " ".join(cells[3:]) if len(cells) > 3 else ""
            order = re.sub(r'\s+', '', order)  # Убираем все пробелы
            return {
                "source_pdf": src,
                "pdf_date": pdf_date,
                "seq": seq,
                "place_number": place,
                "weight": weight,
                "order": order
            }
    
    # Текст
    tokens = re.split(r'\s+', raw)
    if len(tokens) >= 4:
        seq = tokens[0]
        place = tokens[1]
        weight = tokens[2]
        order = " ".join(tokens[3:])
        order = re.sub(r'\s+', '', order)  # Убираем все пробелы
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
    try:
        # Декодируем QR
        urls = decode_qr_from_image(image_data)
        qr_count = len(urls)
        
        if not urls:
            return True, 0, [], None
        
        all_rows = []
        
        # Обрабатываем каждый QR
        for idx, url in enumerate(urls):
            try:
                # Скачиваем PDF в память
                pdf_bytes = download_pdf_to_memory(url)
                
                # Извлекаем данные
                source_name = f"{filename}_QR{idx+1}.pdf"
                items = extract_table_rows_from_pdf(pdf_bytes, source_name)
                
                # Нормализуем строки
                for item in items:
                    normalized = normalize_row(item)
                    if normalized:
                        all_rows.append(normalized)
            
            except Exception as e:
                print(f"[!] Ошибка обработки QR #{idx+1}: {e}")
                continue
        
        return True, qr_count, all_rows, None
    
    except Exception as e:
        return False, 0, [], str(e)