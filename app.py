import streamlit as st
import pandas as pd
import time
from datetime import datetime
from io import BytesIO
import traceback

# Импорт функций
from qr_processor import process_single_image, update_google_sheet

# Конфигурация
st.set_page_config(
    page_title="QR Scanner → Google Sheets",
    page_icon="📊",
    layout="wide"
)

# Инициализация session_state
if 'processing' not in st.session_state:
    st.session_state.processing = False
if 'results' not in st.session_state:
    st.session_state.results = None
if 'df' not in st.session_state:
    st.session_state.df = None
if 'uploaded_successfully' not in st.session_state:
    st.session_state.uploaded_successfully = False
if 'upload_time' not in st.session_state:
    st.session_state.upload_time = None

# Стили
st.markdown("""
    <style>
    .big-font {
        font-size: 24px !important;
        font-weight: bold;
    }
    .success-box {
        padding: 20px;
        border-radius: 10px;
        background-color: #d4edda;
        border: 1px solid #c3e6cb;
    }
    .warning-box {
        padding: 20px;
        border-radius: 10px;
        background-color: #fff3cd;
        border: 1px solid #ffeeba;
    }
    </style>
""", unsafe_allow_html=True)

# Проверка на автообновление после успешной загрузки
if st.session_state.uploaded_successfully and st.session_state.upload_time:
    elapsed = time.time() - st.session_state.upload_time
    if elapsed >= 2:
        st.session_state.processing = False
        st.session_state.results = None
        st.session_state.df = None
        st.session_state.uploaded_successfully = False
        st.session_state.upload_time = None
        st.rerun()

# Заголовок
st.title("📊 QR Code Scanner → Google Sheets")
st.markdown("### Сканируйте QR-коды и отправляйте данные в Google Sheets")
st.markdown("---")

# Загрузка файлов
uploaded_files = st.file_uploader(
    "📁 Загрузите изображения с QR-кодами",
    type=['png', 'jpg', 'jpeg', 'bmp', 'webp'],
    accept_multiple_files=True,
    help="Выберите одно или несколько изображений",
    disabled=st.session_state.processing
)

if uploaded_files and not st.session_state.processing:
    st.success(f"✅ Загружено: **{len(uploaded_files)}** файлов")
    
    # Превью
    if len(uploaded_files) <= 4:
        cols = st.columns(len(uploaded_files))
        for idx, file in enumerate(uploaded_files):
            with cols[idx]:
                st.image(file, caption=file.name, width=200)
    else:
        with st.expander(f"👁️ Показать все {len(uploaded_files)} изображений"):
            cols = st.columns(4)
            for idx, file in enumerate(uploaded_files):
                with cols[idx % 4]:
                    st.image(file, caption=file.name, width=150)
    
    st.markdown("---")
    
    # Кнопка обработки
    if st.button("🚀 Начать обработку", type="primary", use_container_width=True):
        st.session_state.processing = True
        st.rerun()

# Процесс обработки
if st.session_state.processing and uploaded_files:
    st.markdown("### ⚙️ Обработка изображений")
    
    progress_bar = st.progress(0)
    status_container = st.container()
    
    all_rows = []
    results = []
    upload_datetime = datetime.now().strftime("%d.%m.%Y %H:%M:%S")
    
    for idx, uploaded_file in enumerate(uploaded_files):
        with status_container:
            st.markdown(f"#### 📄 {idx + 1}/{len(uploaded_files)}: `{uploaded_file.name}`")
            
            col1, col2 = st.columns([1, 3])
            
            with col1:
                st.image(uploaded_file, width=200)
            
            with col2:
                start_time = time.time()
                
                # Обработка
                try:
                    image_bytes = uploaded_file.read()
                    uploaded_file.seek(0)
                    
                    # Логирование размера файла
                    st.info(f"📊 Размер файла: {len(image_bytes) / 1024:.1f} KB")
                    
                    with st.spinner("🔍 Сканирую QR-коды..."):
                        success, qr_count, rows, error = process_single_image(image_bytes, uploaded_file.name)
                    
                    # Детальное логирование
                    if not success:
                        st.error(f"❌ Ошибка: {error}")
                        with st.expander("🔍 Детали ошибки"):
                            st.code(error)
                        results.append({
                            'file': uploaded_file.name,
                            'status': 'error',
                            'qr_count': 0,
                            'rows_count': 0,
                            'error': error
                        })
                    elif qr_count == 0:
                        st.warning(f"⚠️ QR-коды не найдены")
                        st.info("💡 Попробуйте:")
                        st.markdown("""
                        - Загрузить более четкое фото
                        - Убедиться, что QR-код полностью виден
                        - Улучшить освещение
                        - Проверить, что изображение не повреждено
                        """)
                        results.append({
                            'file': uploaded_file.name,
                            'status': 'no_qr',
                            'qr_count': 0,
                            'rows_count': 0
                        })
                    else:
                        st.success(f"✅ Найдено QR: **{qr_count}** | Извлечено строк: **{len(rows)}**")
                        all_rows.extend(rows)
                        results.append({
                            'file': uploaded_file.name,
                            'status': 'success',
                            'qr_count': qr_count,
                            'rows_count': len(rows)
                        })
                    
                    elapsed = time.time() - start_time
                    st.caption(f"⏱️ Обработано за {elapsed:.1f}с")
                
                except Exception as e:
                    error_details = traceback.format_exc()
                    st.error(f"❌ Критическая ошибка: {str(e)}")
                    with st.expander("🔍 Полная трассировка ошибки"):
                        st.code(error_details)
                    results.append({
                        'file': uploaded_file.name,
                        'status': 'error',
                        'qr_count': 0,
                        'rows_count': 0,
                        'error': str(e)
                    })
            
            st.markdown("---")
        
        progress_bar.progress((idx + 1) / len(uploaded_files))
    
    st.session_state.results = results
    
    if all_rows:
        df = pd.DataFrame(all_rows)
        df['uploaded_date'] = upload_datetime
        df.drop_duplicates(inplace=True)
        st.session_state.df = df
    else:
        st.session_state.df = None
    
    st.session_state.processing = False
    st.rerun()

# Результаты
if st.session_state.results is not None:
    st.markdown("---")
    st.markdown("### 📊 Результаты обработки")
    
    results = st.session_state.results
    df = st.session_state.df
    
    # Статистика
    total_files = len(results)
    success_files = sum(1 for r in results if r['status'] == 'success')
    total_qr = sum(r['qr_count'] for r in results)
    total_rows = sum(r['rows_count'] for r in results)
    
    cols = st.columns(4)
    with cols[0]:
        st.metric("📁 Обработано файлов", total_files)
    with cols[1]:
        st.metric("✅ Успешно", success_files)
    with cols[2]:
        st.metric("🔍 Найдено QR", total_qr)
    with cols[3]:
        st.metric("📋 Извлечено строк", total_rows)
    
    # Детальная таблица
    with st.expander("📝 Подробная информация по файлам"):
        result_df = pd.DataFrame([
            {
                "Файл": r['file'],
                "QR-кодов": r['qr_count'],
                "Строк данных": r['rows_count'],
                "Статус": "✅ OK" if r['status'] == 'success' else "⚠️ Нет QR" if r['status'] == 'no_qr' else "❌ Ошибка"
            }
            for r in results
        ])
        st.dataframe(result_df, width=None, hide_index=True)
    
    # Данные
    if df is not None and len(df) > 0:
        st.markdown("---")
        st.markdown("### 📋 Извлеченные данные")
        
        display_df = df[['uploaded_date', 'pdf_date', 'source_pdf', 'seq', 'place_number', 'weight', 'order']].copy()
        display_df.columns = ['Дата загрузки', 'Дата приема-передачи', 'Источник PDF', '№ п/п', 'Номер места', 'Вес', 'Заказ']
        
        st.dataframe(display_df, width=None, height=400)
        
        # Кнопка отправки
        st.markdown("---")
        col1, col2 = st.columns([2, 1])
        
        with col1:
            if st.button("📤 Отправить в Google Sheets", type="primary", use_container_width=True):
                try:
                    with st.spinner("📤 Отправка данных..."):
                        sheet_url = update_google_sheet(df)
                    
                    st.success("✅ Данные успешно отправлены!")
                    st.markdown(f"### [🔗 Открыть таблицу]({sheet_url})")
                    st.balloons()
                    
                    st.session_state.uploaded_successfully = True
                    st.session_state.upload_time = time.time()
                    
                    with st.spinner("Страница обновится через 2 секунды..."):
                        time.sleep(2)
                    
                    st.rerun()
                
                except Exception as e:
                    error_details = traceback.format_exc()
                    st.error(f"❌ Ошибка отправки: {str(e)}")
                    with st.expander("🔍 Детали ошибки"):
                        st.code(error_details)
                    st.info("Проверьте:")
                    st.markdown("""
                    - Secrets настроены правильно в Streamlit Cloud
                    - Service account имеет доступ к таблице
                    - Интернет-соединение работает
                    """)
        
        with col2:
            if st.button("🔄 Новая обработка", use_container_width=True):
                st.session_state.results = None
                st.session_state.df = None
                st.session_state.processing = False
                st.session_state.uploaded_successfully = False
                st.session_state.upload_time = None
                st.rerun()
    
    else:
        st.warning("⚠️ Данные не найдены")
        st.info("Возможные причины:")
        st.markdown("""
        - QR-коды не были распознаны
        - PDF не содержат табличных данных
        - Низкое качество изображений
        """)
        
        if st.button("🔄 Попробовать снова", type="primary"):
            st.session_state.results = None
            st.session_state.df = None
            st.session_state.processing = False
            st.session_state.uploaded_successfully = False
            st.session_state.upload_time = None
            st.rerun()

# Футер
st.markdown("---")
st.markdown("""
<div style='text-align: center; color: gray;'>
    <p>💡 <b>Совет:</b> Для лучших результатов используйте четкие фото с хорошим освещением</p>
    <p>🔒 Все обработки выполняются в памяти без сохранения файлов</p>
</div>
""", unsafe_allow_html=True)