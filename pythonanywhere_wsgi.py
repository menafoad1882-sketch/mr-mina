"""
═══════════════════════════════════════════════════════════════════════════
  ملف WSGI للنشر على PythonAnywhere
═══════════════════════════════════════════════════════════════════════════

PythonAnywhere لا يستخدم gunicorn — بل ملف WSGI يشير إلى تطبيق Flask.

📋 طريقة الاستخدام:
1. من تبويب "Web" في PythonAnywhere، افتح ملف الـ WSGI الخاص بموقعك
   (مساره عادةً: /var/www/USERNAME_pythonanywhere_com_wsgi.py).
2. امسح محتواه بالكامل، والصق محتوى هذا الملف.
3. عدّل السطر PROJECT_HOME أدناه ليطابق مسار مشروعك على PythonAnywhere
   (عادةً: /home/USERNAME/teacher_app  — استبدل USERNAME باسم حسابك).
4. عدّل SECRET_KEY لأي نص عشوائي طويل.
5. احفظ الملف واضغط "Reload" في تبويب Web.

⚠️ مهم (الخطة المجانية):
- الخطة المجانية تحظر الاتصال بالإنترنت الخارجي (عدا قائمة بيضاء لا تشمل Supabase).
- لذلك لا تضبط DATABASE_URL — سيستخدم الموقع SQLite تلقائيًا، وبياناته لا تضيع
  لأن نظام ملفات PythonAnywhere دائم.
- بالمثل: إرسال واتساب/الذكاء الاصطناعي الخارجي/الإيميل الخارجي قد لا يعمل على الخطة
  المجانية بسبب نفس الحظر → استخدم «المولّد المحلي» لتوليد الامتحانات.

📷 OCR للملفات الممسوحة (يعمل على PythonAnywhere):
- tesseract مثبّت مسبقًا على PythonAnywhere في /usr/bin/tesseract مع دعم العربية (ara)،
  والتطبيق يكتشف مساره تلقائيًا — فقراءة الـ PDF الممسوح تعمل بلا إعداد إضافي.
- في Bash console شغّل مرة واحدة لتثبيت مكتبات بايثون:
    pip3.10 install --user -r requirements.txt
- لو ظهر أن اللغة العربية غير متاحة، يمكن (اختياريًا) ضبط مفتاح OCR سحابي
  (OCR.space) من الإعدادات — لكنه يحتاج حسابًا مدفوعًا يسمح بالإنترنت الخارجي.
"""
import os
import sys

# ── 1) مسار المشروع على PythonAnywhere (عدّله ليطابق حسابك) ──────────────
PROJECT_HOME = "/home/USERNAME/teacher_app"   # ← استبدل USERNAME باسم حسابك
if PROJECT_HOME not in sys.path:
    sys.path.insert(0, PROJECT_HOME)

# ── 2) متغيرات البيئة ────────────────────────────────────────────────────
os.environ["FLASK_ENV"] = "production"
# مفتاح تأمين الجلسات — غيّره لأي نص عشوائي طويل قبل الاستخدام الحقيقي
os.environ.setdefault("SECRET_KEY", "CHANGE-ME-to-a-long-random-string")

# على الخطة المجانية: لا تضبط DATABASE_URL (Supabase محظور) — سيُستخدم SQLite.
# على خطة مدفوعة تريد Supabase؟ أزل التعليق واضبط الرابط:
# os.environ["DATABASE_URL"] = "postgresql://postgres:PASSWORD@db.xxxx.supabase.co:5432/postgres"

# مكان قاعدة بيانات SQLite (دائم على PythonAnywhere). الافتراضي مجلد المشروع.
os.environ.setdefault("DATA_DIR", PROJECT_HOME)

# ── 3) استيراد تطبيق Flask ليجده خادم WSGI باسم "application" ─────────────
from app import app as application  # noqa: E402
