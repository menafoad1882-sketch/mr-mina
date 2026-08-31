# ─────────────────────────────────────────────────────────────────────────
#  صورة تشغيل نظام إدارة المدرس — تتضمّن Tesseract OCR + اللغة العربية
#  تعمل على Render (Docker) وأي استضافة تدعم Docker.
# ─────────────────────────────────────────────────────────────────────────
FROM python:3.12-slim

# حزم النظام: محرّك OCR + بيانات اللغة العربية + أدوات معالجة الصور/الـ PDF
RUN apt-get update && apt-get install -y --no-install-recommends \
        tesseract-ocr \
        tesseract-ocr-ara \
        tesseract-ocr-eng \
        libtesseract-dev \
        poppler-utils \
        libgl1 \
        libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/*

# تأكيد توفّر tesseract في المسار
ENV TESSERACT_CMD=/usr/bin/tesseract
ENV PATH="/usr/bin:${PATH}"

WORKDIR /app

# تثبيت متطلبات بايثون أولًا (طبقة كاش أفضل)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# نسخ بقية التطبيق
COPY . .

# المنفذ يُحدَّد من متغير البيئة PORT (Render يوفّره)، وإلا 10000 محليًا
ENV PORT=10000
EXPOSE 10000

# تشغيل الخادم عبر gunicorn
CMD gunicorn app:app --bind 0.0.0.0:${PORT} --workers 2 --timeout 120
