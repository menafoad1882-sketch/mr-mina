"""
نقطة الدخول لـ Vercel (Serverless Function).
Vercel بيستدعي المتغير `app` من هنا لكل طلب.
كل الكود الحقيقي موجود في app.py في جذر المشروع.
"""
import os
import sys

# أضف جذر المشروع للمسار عشان نقدر نستورد app.py
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import app  # noqa: E402

# Vercel يبحث عن كائن باسم app
