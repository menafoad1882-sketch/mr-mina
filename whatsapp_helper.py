"""
مساعد الواتساب - يدعم وضعين:
1) link : روابط wa.me جاهزة (مجاني، تضغط إرسال بنفسك)  -- الافتراضي
2) api  : إرسال تلقائي عبر WhatsApp API (Meta / Twilio / UltraMsg)
"""
import re
import json
import urllib.request
import urllib.parse
import urllib.error
import database as db


def normalize_phone(phone):
    """تحويل الرقم المصري لصيغة دولية (2010...)"""
    if not phone:
        return ""
    p = re.sub(r"\D", "", phone)
    if p.startswith("00"):
        p = p[2:]
    if p.startswith("20"):
        return p
    if p.startswith("0"):
        return "2" + p
    if len(p) == 10:
        return "20" + p
    return p


def wa_link(phone, message):
    return f"https://wa.me/{normalize_phone(phone)}?text={urllib.parse.quote(message)}"


class _SafeDict(dict):
    """قاموس آمن للتنسيق: أي متغيّر غير معرّف يبقى فارغًا بدل رفع خطأ."""
    def __missing__(self, key):
        return ""


def template_is_complete(key):
    """هل القالب موجود وله نص غير فارغ؟ (للتحقّق قبل الإرسال)."""
    tpl = db.get_template(key)
    return bool(tpl and (tpl.get("body") or "").strip())


def render_template(key, **kwargs):
    """يجهّز نص رسالة من قالب محفوظ مع استبدال المتغيرات (آمن للمتغيرات الناقصة)."""
    tpl = db.get_template(key)
    body = (tpl["body"] if tpl else "") or ""
    defaults = {
        "teacher": db.get_setting("teacher_name", "الأستاذ"),
        "subject": db.get_setting("subject", "المادة"),
    }
    defaults.update({k: (v if v is not None else "") for k, v in kwargs.items()})
    try:
        # format_map مع _SafeDict: المتغيرات الناقصة تصبح فارغة بلا خطأ
        return body.format_map(_SafeDict(defaults))
    except (ValueError, IndexError):
        return body


def api_mode():
    return db.get_setting("wa_mode", "link") == "api"


def config_status():
    """
    فحص تشخيصي كامل لإعداد الواتساب. يرجّع dict:
    {ok, mode, provider, messages:[...]} لعرضه للمستخدم.
    """
    mode = db.get_setting("wa_mode", "link")
    provider = db.get_setting("wa_provider", "ultramsg")
    msgs = []
    if mode != "api":
        msgs.append("الوضع الحالي: روابط جاهزة (يدوي) — لا يوجد اتصال بأي خادم. "
                    "لتفعيل الإرسال التلقائي فعّل «إرسال تلقائي عبر API».")
        return {"ok": True, "mode": mode, "provider": provider, "messages": msgs}
    err = _validate(provider)
    if err:
        return {"ok": False, "mode": mode, "provider": provider, "messages": [err]}
    # تحقق من عدم وجود عنوان محلي
    if provider in ("ultramsg", "twilio"):
        raw = db.get_setting("wa_api_url", "").strip()
        target = _ultramsg_url(raw) if provider == "ultramsg" else raw
        if provider == "ultramsg" and _is_local_url(target):
            return {"ok": False, "mode": mode, "provider": provider,
                    "messages": ["الرابط يشير لخادم محلي (سبب خطأ 10061). استخدم خدمة سحابية."]}
    msgs.append(f"الإعدادات مكتملة للمزوّد: {provider}. اضغط «إرسال رسالة اختبار» للتأكد من الاتصال.")
    return {"ok": True, "mode": mode, "provider": provider, "messages": msgs}


def _clean_token(token, url=""):
    """ينظّف التوكن من المسافات، ويستخرجه لو المستخدم لصق الرابط كاملًا بـ token=..."""
    token = (token or "").strip().strip('"').strip("'")
    # لو التوكن لصق داخل حقل URL بالغلط
    if not token and url and "token=" in url:
        m = re.search(r"token=([^&\s]+)", url)
        if m:
            token = m.group(1)
    # لو التوكن نفسه فيه token=
    if token.startswith("token="):
        token = token[6:]
    return token.strip()


def _ultramsg_url(raw):
    """
    يطبّع رابط UltraMsg لأي صيغة يدخلها المستخدم:
    - "instance12345"                          -> https://api.ultramsg.com/instance12345/messages/chat
    - "https://api.ultramsg.com/instance12345" -> .../instance12345/messages/chat
    - رابط كامل صحيح                            -> كما هو
    """
    raw = (raw or "").strip().rstrip("/")
    if not raw:
        return raw
    # مجرد رقم الـ instance أو "instanceXXXX"
    if not raw.startswith("http"):
        inst = raw if raw.startswith("instance") else f"instance{raw}"
        return f"https://api.ultramsg.com/{inst}/messages/chat"
    # رابط كامل بالفعل
    if "/messages/" in raw:
        return raw
    # رابط أساسي بدون endpoint
    return raw + "/messages/chat"


def _log(phone, message, provider, success, response,
         status_code=0, error_type="", msg_type=""):
    """تسجيل محاولة إرسال في جدول wa_logs للتشخيص (مع كود HTTP ونوع الخطأ)."""
    try:
        conn = db.get_db()
        conn.execute(
            "INSERT INTO wa_logs(phone,message,provider,success,status_code,"
            "error_type,msg_type,response,created_at) VALUES(?,?,?,?,?,?,?,?,?)",
            (phone, (message or "")[:1000], provider, 1 if success else 0,
             int(status_code or 0), error_type, msg_type,
             str(response)[:2000], db.now()))
        conn.commit()
        conn.close()
    except Exception as e:
        print("[wa_log] تعذّر التسجيل:", e)


def _classify_error(status_code, resp):
    """
    يصنّف خطأ الإرسال بدقة بناءً على كود HTTP ومحتوى الرد.
    يرجّع (error_type, رسالة عربية واضحة, retryable).
    """
    text = str(resp)
    low = text.lower()

    # Cloudflare 1010 / حظر التوقيع — ليس خطأ بيانات اعتماد وغير قابل لإعادة المحاولة
    if "1010" in text or "browser_signature_banned" in low or "cloudflare" in low or "access denied" in low:
        return ("cloudflare_block",
                "🛡️ حظر من Cloudflare (خطأ 1010 - Access denied): تم رفض الطلب بناءً على "
                "«توقيع المتصفح». هذا ليس خطأ في التوكن أو رقم الـ Instance.\n"
                "تم بالفعل إرسال الطلب من الخادم بترويسة متصفح صحيحة؛ إذا استمر الحظر فقد يكون "
                "عنوان IP الخاص بالخادم محظورًا مؤقتًا من UltraMsg/Cloudflare. جرّب لاحقًا أو تواصل مع دعم UltraMsg.\n"
                "الرد الفعلي: " + text[:400], False)
    # بيانات اعتماد خاطئة (توكن/instance)
    if status_code == 401 or "invalid token" in low or "wrong token" in low or "unauthorized" in low:
        return ("invalid_credentials",
                "🔑 بيانات اعتماد غير صحيحة: التوكن غير صالح. تحقق من التوكن في لوحة UltraMsg.\n"
                "الرد: " + text[:400], False)
    if "instance" in low and ("not found" in low or "invalid" in low or "expired" in low):
        return ("invalid_instance",
                "📵 رقم الـ Instance غير صحيح أو منتهٍ أو غير متصل. تحقق من حالته في UltraMsg.\n"
                "الرد: " + text[:400], False)
    # 403 عام
    if status_code == 403:
        return ("forbidden",
                "⛔ 403 Forbidden: تم رفض الوصول من الخادم البعيد.\nالرد: " + text[:400], False)
    # 429 rate limit
    if status_code == 429 or "rate" in low and "limit" in low:
        return ("rate_limit",
                "⏳ تجاوز حد الإرسال (Rate limit). انتظر قليلًا ثم أعد المحاولة.\nالرد: " + text[:400], True)
    # فشل اتصال
    if status_code == 0:
        return ("connection_failure",
                "🔌 فشل الاتصال بخادم الـ API: " + text[:400], True)
    # خطأ خادم بعيد
    if status_code >= 500:
        return ("api_server_error",
                f"🖥️ خطأ في خادم الـ API ({status_code}). أعد المحاولة لاحقًا.\nالرد: " + text[:400], True)
    return ("api_error", f"فشل الإرسال ({status_code}): " + text[:400], False)


def _is_local_url(url):
    """هل الرابط يشير لجهاز محلي/شبكة داخلية (سبب خطأ 10061)؟"""
    try:
        host = (urllib.parse.urlparse(url).hostname or "").lower()
    except Exception:
        return False
    if host in ("localhost", "127.0.0.1", "0.0.0.0", "::1", "host.docker.internal"):
        return True
    # عناوين الشبكة الداخلية
    if host.startswith(("192.168.", "10.", "169.254.")):
        return True
    if host.startswith("172."):
        parts = host.split(".")
        if len(parts) >= 2 and parts[1].isdigit() and 16 <= int(parts[1]) <= 31:
            return True
    return False


def _valid_cloud_url(url):
    """يتأكد أن الرابط سحابي صالح (https ومضيف حقيقي)."""
    try:
        u = urllib.parse.urlparse(url)
    except Exception:
        return False, "الرابط غير صالح"
    if u.scheme not in ("http", "https"):
        return False, "الرابط يجب أن يبدأ بـ https://"
    if not u.hostname or "." not in u.hostname:
        return False, "مضيف الرابط غير صالح"
    if _is_local_url(url):
        return False, ("الرابط يشير إلى خادم محلي (localhost/شبكة داخلية) — "
                       "هذا سبب الخطأ 10061. استخدم رابط خدمة سحابية حقيقية.")
    return True, ""


# User-Agent شبيه بالمتصفح — مطلوب لتفادي حظر Cloudflare (خطأ 1010 browser_signature_banned)
_UA = ("Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
       "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36")


def _http(req):
    """
    ينفّذ طلب HTTP من الخادم (backend) ويرجّع (نجاح, status_code, نص الرد).
    يضيف User-Agent متصفح لتفادي حظر Cloudflare. يقرأ جسم الخطأ بالتفصيل.
    """
    url = req.full_url if hasattr(req, "full_url") else str(getattr(req, "_full_url", ""))
    # أضف ترويسات متصفح إن لم تكن موجودة (تفادي Cloudflare 1010)
    if not req.has_header("User-agent"):
        req.add_header("User-Agent", _UA)
    if not req.has_header("Accept"):
        req.add_header("Accept", "application/json, text/plain, */*")
    req.add_header("Accept-Language", "ar,en;q=0.9")
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            body = r.read().decode("utf-8", "replace")
            return True, getattr(r, "status", 200), body
    except urllib.error.HTTPError as e:
        try:
            detail = e.read().decode("utf-8", "replace")
        except Exception:
            detail = ""
        return False, e.code, f"HTTP {e.code} {e.reason} — {detail}"
    except urllib.error.URLError as e:
        reason = getattr(e, "reason", e)
        rs = str(reason)
        if ("refused" in rs.lower() or "10061" in rs or "actively refused" in rs.lower()):
            hint = ""
            if _is_local_url(url):
                hint = ("\n\n⚠️ التطبيق يحاول الاتصال بخادم محلي (localhost) وهو غير متاح على "
                        "الاستضافة. غيّر إعدادات واتساب لاستخدام خدمة سحابية.")
            return False, 0, f"تعذّر الاتصال بالخادم (اتصال مرفوض): {rs}{hint}"
        if "timed out" in rs.lower() or "timeout" in rs.lower():
            return False, 0, "انتهت مهلة الاتصال بالخادم. تحقق من الإنترنت وحاول مجددًا."
        return False, 0, f"تعذّر الاتصال بالخادم: {rs}"
    except Exception as e:
        return False, 0, f"{type(e).__name__}: {e}"


def _validate(provider):
    """يتحقق من اكتمال وصحة إعدادات المزوّد قبل الإرسال. يرجّع رسالة خطأ أو None."""
    token = db.get_setting("wa_api_token", "").strip()
    if provider == "ultramsg":
        raw = db.get_setting("wa_api_url", "").strip()
        if not raw:
            return ("إعدادات UltraMsg ناقصة: أدخل رقم الـ Instance (مثل instance12345) "
                    "في خانة API URL.")
        if not token:
            return "إعدادات UltraMsg ناقصة: Token مطلوب"
        # تحقق من أن الرابط الناتج سحابي وليس محليًا
        ok, msg = _valid_cloud_url(_ultramsg_url(raw))
        if not ok:
            return f"رابط UltraMsg غير صالح: {msg}"
    elif provider == "meta":
        if not db.get_setting("wa_phone_id", "").strip():
            return "إعدادات Meta ناقصة: Phone Number ID مطلوب"
        if not token:
            return "إعدادات Meta ناقصة: Access Token مطلوب"
    elif provider == "twilio":
        if not db.get_setting("wa_api_url", "").strip():
            return "إعدادات Twilio ناقصة: Account SID مطلوب"
        if not token:
            return "إعدادات Twilio ناقصة: Auth Token مطلوب"
        if not db.get_setting("wa_from", "").strip():
            return "إعدادات Twilio ناقصة: رقم المُرسِل From مطلوب"
    else:
        return (f"مزود غير معروف: {provider}. اختر مزوّدًا سحابيًا "
                "(UltraMsg / Meta / Twilio) من الإعدادات.")
    return None


def send_api(phone, message, msg_type="general"):
    """
    إرسال واتساب من الخادم (backend) عبر API المزوّد المُعدّ.
    - التوكن يُقرأ من قاعدة البيانات في الخادم ولا يُكشف في المتصفح إطلاقًا.
    - يرجّع (نجاح؟, رسالة تفصيلية دقيقة).
    - يسجّل كل محاولة في wa_logs مع كود HTTP ونوع الخطأ.
    - لا يعيد المحاولة على Cloudflare 1010 (غير قابل لإعادة المحاولة).
    """
    provider = db.get_setting("wa_provider", "ultramsg")
    to = normalize_phone(phone)

    if not to:
        _log(phone, message, provider, False, "رقم هاتف غير صالح",
             error_type="invalid_phone", msg_type=msg_type)
        return False, "رقم هاتف ولي الأمر غير صالح أو فارغ"

    err = _validate(provider)
    if err:
        _log(to, message, provider, False, err,
             error_type="config", msg_type=msg_type)
        return False, err

    token = db.get_setting("wa_api_token", "").strip()
    try:
        status = 0
        if provider == "ultramsg":
            raw_url = db.get_setting("wa_api_url", "").strip()
            api_url = _ultramsg_url(raw_url)
            token = _clean_token(token, raw_url)
            data = urllib.parse.urlencode({
                "token": token, "to": to, "body": message}).encode()
            req = urllib.request.Request(
                api_url, data=data, method="POST",
                headers={"Content-Type": "application/x-www-form-urlencoded"})
            ok, status, resp = _http(req)
            # UltraMsg قد يرجّع 200 مع خطأ منطقي؛ افحص المحتوى
            if ok:
                try:
                    j = json.loads(resp)
                    if isinstance(j, dict) and (str(j.get("sent")).lower() == "false" or j.get("error")):
                        ok = False
                        resp = "UltraMsg: " + str(j.get("error") or j.get("message") or resp)
                except Exception:
                    pass

        elif provider == "meta":
            phone_id = db.get_setting("wa_phone_id", "").strip()
            url = f"https://graph.facebook.com/v20.0/{phone_id}/messages"
            payload = json.dumps({
                "messaging_product": "whatsapp", "to": to,
                "type": "text", "text": {"body": message}}).encode()
            req = urllib.request.Request(url, data=payload, method="POST", headers={
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json"})
            ok, status, resp = _http(req)

        elif provider == "twilio":
            import base64
            sid = db.get_setting("wa_api_url", "").strip()
            from_ = db.get_setting("wa_from", "").strip()
            url = f"https://api.twilio.com/2010-04-01/Accounts/{sid}/Messages.json"
            from_val = from_ if from_.startswith("whatsapp") else f"whatsapp:+{normalize_phone(from_)}"
            data = urllib.parse.urlencode({
                "From": from_val, "To": f"whatsapp:+{to}", "Body": message}).encode()
            auth = base64.b64encode(f"{sid}:{token}".encode()).decode()
            req = urllib.request.Request(url, data=data, method="POST", headers={
                "Authorization": f"Basic {auth}"})
            ok, status, resp = _http(req)
        else:
            _log(to, message, provider, False, "مزود غير معروف",
                 error_type="config", msg_type=msg_type)
            return False, "مزود غير معروف"

        if ok:
            _log(to, message, provider, True, resp,
                 status_code=status, error_type="", msg_type=msg_type)
            return True, "تم الإرسال بنجاح"

        # فشل: صنّف الخطأ بدقة
        etype, human, _retryable = _classify_error(status, resp)
        _log(to, message, provider, False, resp,
             status_code=status, error_type=etype, msg_type=msg_type)
        return False, human

    except Exception as e:
        msg = f"خطأ غير متوقع أثناء الإرسال عبر {provider}: {type(e).__name__}: {e}"
        _log(to, message, provider, False, msg,
             error_type="exception", msg_type=msg_type)
        return False, msg
