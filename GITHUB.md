# 🐙 رفع المشروع على GitHub

جهّزت لك المستودع (repo) محليًا مع أول commit جاهز. كل اللي عليك تعمله:

## 1) أنشئ مستودعًا جديدًا على GitHub
- ادخل على https://github.com/new
- اكتب اسم المستودع، مثلاً: `teacher-management-system`
- **مهم:** لا تختار "Add README" ولا "Add .gitignore" (لأنهم موجودين عندك بالفعل)
- اضغط **Create repository**

## 2) اربط المشروع وارفعه
افتح Terminal داخل مجلد `teacher_app` وشغّل الأوامر دي
(غيّر `USERNAME` و `REPO` باسمك واسم المستودع):

```bash
cd teacher_app

# لو أول مرة تستخدم git على الجهاز، عرّف نفسك:
git config --global user.name "اسمك"
git config --global user.email "your@email.com"

# اربط المستودع البعيد
git remote add origin https://github.com/USERNAME/REPO.git

# ارفع الكود
git branch -M main
git push -u origin main
```

GitHub هيطلب منك تسجيل الدخول:
- **اسم المستخدم:** اسمك على GitHub
- **كلمة المرور:** استخدم **Personal Access Token** (مش باسورد حسابك العادي)
  - أنشئه من: GitHub > Settings > Developer settings > Personal access tokens > Tokens (classic) > Generate new token
  - اختر صلاحية `repo` وانسخ التوكن واستخدمه ككلمة مرور.

## 3) التحديثات المستقبلية
كل ما تعدّل حاجة في الكود:
```bash
git add -A
git commit -m "وصف التعديل"
git push
```

---

## ✅ ملاحظات أمان مهمة
- ملف `teacher.db` (بيانات الطلاب) **لا يُرفع** — مستبعد في `.gitignore` لحماية الخصوصية.
- لا ترفع كلمات مرور الإيميل أو مفاتيح Supabase أو WhatsApp API في الكود — اضبطها من صفحة الإعدادات داخل الموقع (تُحفظ في قاعدة البيانات المحلية فقط).
- غيّر `app.secret_key` في `app.py` لقيمة عشوائية قبل النشر الحقيقي.
