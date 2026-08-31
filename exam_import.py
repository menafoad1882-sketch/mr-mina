"""
استيراد أسئلة الامتحان من ملف Word (.docx) — بدون أي ذكاء اصطناعي.

يعتمد على python-docx لقراءة الفقرات، ثم محلّل نصّي بقواعد واضحة يتعرّف على
أنواع الأسئلة العربية الشائعة (اختيار من متعدد، صح/خطأ، أكمل، بم تفسّر،
ما النتائج المترتبة على، ما المقصود، قارن، دلل) وعناوين الأقسام العربية
(أولاً/ثانياً/...).

المبدأ: لا يعيد صياغة أي سؤال ولا يخترع محتوى — فقط يحوّل ما كتبه المدرس إلى
بنية أسئلة قابلة للمراجعة قبل الإضافة للامتحان.
"""
import re

# أنواع الأسئلة المعروفة + الكلمات الدالة عليها في العناوين/النص
# (ترتيب الفحص مهم: الأطول/الأخصّ أولًا)
_TYPE_KEYWORDS = [
    ("results", ["ما النتائج المترتبة", "النتائج المترتبة", "ما النتائج"]),
    ("meaning", ["ما المقصود", "المقصود بـ", "المقصود ب", "عرّف", "عرف ", "بمَ نعرّف"]),
    ("explain", ["بم تفسّر", "بم تفسر", "بمَ تفسّر", "بمَ تفسر", "علّل", "علل ", "فسّر", "فسر "]),
    ("compare", ["قارن بين", "قارن", "المقارنة", "قارِن"]),
    ("prove", ["دلل على", "دلّل على", "دلل", "دلّل", "برهن", "أثبت صحة", "دلِّل"]),
    ("complete", ["أكمل", "اكمل", "أكمِل", "املأ الفراغ", "أكمل ما يأتي"]),
    ("truefalse", ["صح أو خطأ", "صح ام خطأ", "صح أم خطأ", "ضع علامة صح", "صواب أو خطأ",
                   "صح وخطأ", "صواب وخطأ"]),
    ("mcq", ["اختيار من متعدد", "اختر الإجابة", "اختر الاجابة", "اختر الصحيحة",
             "ضع دائرة", "اختر رمز"]),
]

# رؤوس الأقسام العربية (أولاً، ثانياً، ...) — لتحديد بداية قسم جديد
_ORDINALS = ["أولا", "أولاً", "ثانيا", "ثانياً", "ثالثا", "ثالثاً", "رابعا", "رابعاً",
             "خامسا", "خامساً", "سادسا", "سادساً", "سابعا", "سابعاً", "ثامنا", "ثامناً",
             "تاسعا", "تاسعاً", "عاشرا", "عاشراً"]

# بادئات بند السؤال: 1- , 1. , 1) , س1: , (1) , ١-
_Q_NUM_RE = re.compile(
    r"^\s*(?:س\s*[\.\-:]?\s*)?[\(]?\s*[0-9\u0660-\u0669]+\s*[\)\.\-:]\s*")
# بادئة خيار MCQ: أ) ب) ج) د)  أو  a) b) ...  أو  ١)
_OPT_RE = re.compile(r"^\s*[\(]?\s*([أ-يa-dA-D])\s*[\)\.\-:/]\s*(.+)$")

# باحث عن علامات الاختيارات داخل أي نص: حرف اختيار (عربي/إنجليزي) أو رقم
# (عربي/هندي) متبوعًا بفاصل ) . - / :  ، ويسمح بمسافة قبل الفاصل وبأقواس اختيارية.
_MARK_FINDER = re.compile(
    r"[\(\[]?\s*([أإآا-يa-fA-F]|[0-9\u0660-\u0669]+)\s*[\)\.\-/:]")

_AR_CHOICE_SEQ = ["أ", "ب", "ج", "د", "ه", "و"]
_EN_CHOICE_SEQ = ["a", "b", "c", "d", "e", "f"]
_NUM_CHOICE_SEQ = ["1", "2", "3", "4", "5", "6"]
_AR_DIGIT_MAP = str.maketrans("٠١٢٣٤٥٦٧٨٩", "0123456789")


def _norm_letter(l):
    """يوحّد أشكال الهمزة في حرف الاختيار (إ/آ/ا → أ) والأرقام العربية."""
    s = (l or "").replace("إ", "أ").replace("آ", "أ").replace("ا", "أ")
    return s.translate(_AR_DIGIT_MAP)


def _marker_value(raw):
    """يرجّع القيمة المُطبّعة لعلامة اختيار (حرف عربي/إنجليزي صغير/رقم) أو None."""
    v = _norm_letter(raw)
    if v in _AR_CHOICE_SEQ:
        return ("ar", v)
    low = (raw or "").lower()
    if low in _EN_CHOICE_SEQ:
        return ("en", low)
    if v in _NUM_CHOICE_SEQ:
        return ("num", v)
    return None


def split_marked_choices(text):
    """يقسّم نصًّا يحوي عدة علامات اختيار إلى قائمة اختيارات.

    يدعم العلامات: عربية (أ ب ج د)، إنجليزية (a b c d)، أرقام (1 2 3 4 / ١ ٢ ٣ ٤)
    مع أي فاصل ) . - / :  ومسافات قبله، على سطر واحد أو أسطر.
    يرجّع [] إن لم يجد تسلسلًا صحيحًا (علامتان متتاليتان على الأقل من بداية التسلسل).
    """
    if not text:
        return []
    matches = list(_MARK_FINDER.finditer(text))
    if len(matches) < 2:
        return []
    seqs = {"ar": _AR_CHOICE_SEQ, "en": _EN_CHOICE_SEQ, "num": _NUM_CHOICE_SEQ}
    best = []
    for start_i in range(len(matches)):
        mv = _marker_value(matches[start_i].group(1))
        if not mv:
            continue
        kind, val = mv
        seq = seqs[kind]
        # لا نبدأ إلا من أول عنصر في التسلسل (أ / a / 1)
        if val != seq[0]:
            continue
        run = []
        step = 0
        for m in matches[start_i:]:
            mv2 = _marker_value(m.group(1))
            if mv2 and mv2[0] == kind and step < len(seq) and mv2[1] == seq[step]:
                run.append(m)
                step += 1
            else:
                break
        if len(run) > len(best):
            best = run
    if len(best) < 2:
        return []
    choices = []
    for i, m in enumerate(best):
        start = m.end()
        end = best[i + 1].start() if i + 1 < len(best) else len(text)
        choices.append(text[start:end].strip())
    return [c for c in choices if c]

_AR_DIGITS = str.maketrans("٠١٢٣٤٥٦٧٨٩", "0123456789")


class ImportError_(Exception):
    pass


def _norm(s):
    """تطبيع للبحث عن الكلمات الدالة (يزيل التشكيل ويوحّد الألف)."""
    s = s or ""
    s = re.sub(r"[\u064B-\u0652\u0670]", "", s)
    s = s.replace("أ", "ا").replace("إ", "ا").replace("آ", "ا")
    return s.strip()


def _clean_line(t):
    """يزيل محارف التحكّم في الاتجاه (RTL/LTR marks) والمسافات غير المرئية."""
    if not t:
        return ""
    for ch in ("\u200e", "\u200f", "\u202a", "\u202b", "\u202c",
               "\u202d", "\u202e", "\u2066", "\u2067", "\u2068",
               "\u2069", "\ufeff", "\u00a0"):
        t = t.replace(ch, " " if ch == "\u00a0" else "")
    # وحّد التبويب إلى مسافة
    t = t.replace("\t", " ")
    return t.strip()


def _read_docx_lines(data):
    """يرجّع قائمة أسطر (فقرات + خلايا جداول) من ملف docx."""
    try:
        import docx
    except ImportError:
        raise ImportError_("مكتبة python-docx غير مثبّتة على الخادم.")
    import io
    doc = docx.Document(io.BytesIO(data))
    lines = []
    body = doc.element.body
    from docx.text.paragraph import Paragraph
    from docx.table import Table
    for child in body.iterchildren():
        if child.tag.endswith("}p"):
            t = Paragraph(child, doc).text
            if t is not None:
                lines.append(_clean_line(t))
        elif child.tag.endswith("}tbl"):
            tbl = Table(child, doc)
            for row in tbl.rows:
                for cell in row.cells:
                    ct = (cell.text or "").strip()
                    if ct:
                        for ln in ct.split("\n"):
                            lines.append(_clean_line(ln))
    return lines


def _detect_type(text, current_section):
    """يحدّد نوع السؤال من نصّه، وإلا يستخدم نوع القسم الحالي."""
    n = _norm(text)
    for qtype, kws in _TYPE_KEYWORDS:
        for kw in kws:
            if _norm(kw) in n:
                return qtype
    return current_section


def _is_section_header(text):
    """لو السطر رأس قسم (أولاً: بم تفسّر) يرجّع نوع القسم، وإلا None."""
    # سطر يبدأ برقم سؤال ليس رأس قسم أبدًا (حتى لو احتوى نقطتين)
    if _Q_NUM_RE.match(text):
        return None
    n = _norm(text)
    # سطر يحوي علامات اختيارات (أ)..ب)..) ليس رأس قسم — هو سطر اختيارات
    if len(split_marked_choices(text)) >= 2:
        return None
    # يبدأ بترتيب عربي؟
    starts_ord = any(n.startswith(_norm(o)) for o in _ORDINALS)
    # أو سطر قصير ينتهي بنقطتين ويحوي كلمة دالة
    short_header = len(text) <= 40 and (":" in text or "：" in text)
    # أو سطر تعليمات قصير يحوي كلمة دالة على نوع (بدون نقطتين) مثل «اختر الإجابة الصحيحة»
    short_instruction = len(text) <= 45
    if not (starts_ord or short_header or short_instruction):
        return None
    for qtype, kws in _TYPE_KEYWORDS:
        for kw in kws:
            if _norm(kw) in n:
                return qtype
    # رأس قسم بدون نوع معروف (مثلاً «أسئلة») → نتجاهله كنوع
    if starts_ord:
        return "__section__"
    return None


def _strip_qnum(text):
    return _Q_NUM_RE.sub("", text).strip()


def _looks_like_question_start(text):
    """هل السطر يبدأ سؤالًا جديدًا (رقم/سؤال)؟"""
    return bool(_Q_NUM_RE.match(text))


# فواصل الاختيارات المضمّنة داخل القوسين (شرطات/شرطات مائلة/فواصل عربية)
_INLINE_SEP_RE = re.compile(r"\s*[-–—/،,]\s*")
# مجموعة أقواس في آخر السؤال تحوي الاختيارات: ( ... ) أو [ ... ] أو { ... }
_INLINE_PARENS_RE = re.compile(r"[\(\[\{（]([^\(\)\[\]\{\}（）]+)[\)\]\}）][\s\.\؟\?\!:،]*$")


def extract_inline_choices(text):
    """يستخرج اختيارات MCQ المضمّنة في نص السؤال داخل قوسين في آخره.

    مثال: «تحتل قارة أفريقيا المركز ..... من حيث المساحة ( الأول - الثاني - الثالث - الرابع )»
    يرجّع (نص_السؤال_بدون_القوسين، [الاختيارات]) أو (النص_الأصلي، []) إن لم يجد.
    يدعم الفواصل: -  –  —  /  ،  ,
    """
    if not text:
        return text, []
    m = _INLINE_PARENS_RE.search(text.strip())
    if not m:
        return text, []
    inner = m.group(1).strip()
    parts = [p.strip() for p in _INLINE_SEP_RE.split(inner) if p.strip()]
    # نعتبرها اختيارات فقط لو وُجد فاصلان (٢-٦ عناصر) — لتجنّب التقاط أقواس عادية
    if 2 <= len(parts) <= 6:
        new_text = text[:m.start()].rstrip()
        return new_text, parts
    return text, []


# اختيارات على نفس السطر مع السؤال: «... ؟ أ) القاهرة ب) الإسكندرية ج) أسوان د) الأقصر»
# نلتقط علامات الخيار (أ/ب/ج/د أو a-d) متبوعة بـ ) . - وسط السطر.
_SAMELINE_OPT_RE = re.compile(
    r"[\(]?\s*([أ-يa-dA-D])\s*[\)\.\-]\s*")


def extract_sameline_choices(text):
    """يستخرج اختيارات MCQ الموجودة على نفس سطر السؤال (بعد نصّه).

    مثال: «عاصمة مصر؟ أ) القاهرة ب) الإسكندرية ج) أسوان د) الأقصر»
    أو: «... من حيث المساحة أ) الأول ب ) الثاني ج ) الثالث د / الرابع»
    يرجّع (نص_السؤال، [الاختيارات]) أو (النص_الأصلي، []) إن لم يجد تسلسلًا صحيحًا.
    """
    if not text:
        return text, []
    matches = list(_MARK_FINDER.finditer(text))
    if len(matches) < 3:   # نطلب ٣ علامات على الأقل على نفس السطر
        return text, []
    seqs = {"ar": _AR_CHOICE_SEQ, "en": _EN_CHOICE_SEQ, "num": _NUM_CHOICE_SEQ}
    # حدّد بداية أطول تسلسل صحيح (أ ب ج .. / a b c .. / 1 2 3 ..) لفصل نص السؤال
    start_pos = None
    for start_i in range(len(matches)):
        mv = _marker_value(matches[start_i].group(1))
        if not mv:
            continue
        kind, val = mv
        seq = seqs[kind]
        if val != seq[0]:
            continue
        step = 0
        cnt = 0
        for m in matches[start_i:]:
            mv2 = _marker_value(m.group(1))
            if mv2 and mv2[0] == kind and step < len(seq) and mv2[1] == seq[step]:
                cnt += 1
                step += 1
            else:
                break
        if cnt >= 3:
            start_pos = matches[start_i].start()
            break
    if start_pos is None:
        return text, []
    qtext = text[:start_pos].strip()
    if not qtext:
        return text, []
    choices = split_marked_choices(text[start_pos:])
    if 2 <= len(choices) <= 6:
        return qtext, choices
    return text, []


def parse_docx(data):
    """
    يحلّل ملف Word ويرجّع قائمة أسئلة (dicts) جاهزة للمراجعة:
      {type, text, options[], correct, answer_text, marks}
    """
    lines = _read_docx_lines(data)
    questions = []
    current_section = None      # نوع القسم الحالي (من رأس القسم)
    cur = None                   # السؤال قيد التجميع

    def flush():
        nonlocal cur
        if cur and cur.get("text"):
            _finalize(cur)
            questions.append(cur)
        cur = None

    for raw in lines:
        line = (raw or "").strip()
        if not line:
            continue

        # ١) رأس قسم؟
        sec = _is_section_header(line)
        if sec is not None:
            flush()
            if sec != "__section__":
                current_section = sec
            # لو الرأس يحوي أيضًا سؤالًا بعد النقطتين، لا نعالجه هنا عادةً
            continue

        # ٢) خيار MCQ؟ (أ) ... )
        mopt = _OPT_RE.match(line)
        if mopt and cur is not None:
            # قد يحتوي السطر على عدة اختيارات مجمّعة (أ) ... ب) ... ج) ... د) ...)
            # على سطر واحد — قسّمها كلها بدل وضعها في اختيار واحد.
            multi = split_marked_choices(line)
            if len(multi) >= 2:
                cur.setdefault("options", [])
                cur.setdefault("_opt_letters", [])
                for ch in multi:
                    cur["options"].append(ch)
                    cur["_opt_letters"].append("")  # حروف غير صريحة (التصحيح افتراضي)
                cur["type"] = "mcq"
                continue
            cur.setdefault("options", [])
            cur.setdefault("_opt_letters", [])
            letter = mopt.group(1)
            cur["_opt_letters"].append(letter)
            cur["options"].append(mopt.group(2).strip())
            cur["type"] = "mcq"
            continue

        # ٣) سطر إجابة نموذجية صريح؟ (الإجابة: ... / الإجابة النموذجية: ...)
        n = _norm(line)
        if n.startswith(_norm("الإجابة")) and cur is not None:
            val = re.sub(r"^[^:：]*[:：]\s*", "", line).strip()
            cur["answer_text"] = val
            # لو MCQ والإجابة حرف
            m = re.match(r"^\s*([أ-يa-dA-D])\s*$", val)
            if m and cur.get("type") == "mcq":
                cur["_answer_letter"] = m.group(1)
            continue

        # ٣.٥) سطر اختيارات كامل يتبع سؤالًا مفتوحًا؟
        # (مثل «1) الأول 2) الثاني 3) الثالث 4) الرابع» — يبدأ برقم فيبدو سؤالًا،
        #  لكنه في الحقيقة سطر اختيارات. نتحقّق: يوجد سؤال مفتوح بلا اختيارات + السطر
        #  يحوي تسلسل علامات صحيحًا (٣ فأكثر).)
        if cur is not None and not cur.get("options"):
            _multi = split_marked_choices(line)
            if len(_multi) >= 3:
                cur.setdefault("options", [])
                cur.setdefault("_opt_letters", [])
                for ch in _multi:
                    cur["options"].append(ch)
                    cur["_opt_letters"].append("")
                cur["type"] = "mcq"
                continue

        # ٤) بداية سؤال جديد؟
        if _looks_like_question_start(line):
            flush()
            qtext = _strip_qnum(line)
            qtype = _detect_type(qtext, current_section) or "mcq"
            # قد يحتوي سطر السؤال نفسه على الاختيارات (نفس السطر) — استخرجها
            new_text, inl = extract_sameline_choices(qtext)
            cur = {"type": qtype, "text": qtext, "options": [], "_opt_letters": [],
                   "answer_text": "", "marks": 1}
            if inl:
                cur["text"] = new_text
                cur["options"] = inl
                cur["_opt_letters"] = ["" for _ in inl]
                cur["type"] = "mcq"
            continue

        # ٥) سطر تابع: لو عندنا سؤال مفتوح، نضيفه لنصه أو كخيار
        if cur is not None:
            # قد يكون استكمالًا لنص السؤال
            cur["text"] = (cur["text"] + " " + line).strip()
        else:
            # سطر حر قبل أي سؤال: قد يكون سؤالًا بلا ترقيم — أنشئ سؤالًا
            qtype = _detect_type(line, current_section)
            if qtype:
                cur = {"type": qtype, "text": _strip_qnum(line), "options": [],
                       "_opt_letters": [], "answer_text": "", "marks": 1}
    flush()
    # تنظيف الحقول المؤقتة
    for q in questions:
        q.pop("_opt_letters", None)
        q.pop("_answer_letter", None)
    return questions


def _finalize(q):
    """يضبط الحقول النهائية لكل سؤال حسب نوعه."""
    qtype = q.get("type", "mcq")
    # صح/خطأ: أزل علامة (   ) من النص
    if qtype == "truefalse":
        q["text"] = re.sub(r"[\(（]\s*[\)）]", "", q["text"]).strip()
        q["text"] = re.sub(r"\.{2,}", "", q["text"]).strip()
    # MCQ: حدّد الإجابة الصحيحة
    if qtype == "mcq":
        opts = q.get("options", [])
        # لو لم تُلتقط اختيارات كأسطر منفصلة، جرّب استخراجها من داخل قوسين في نص السؤال
        # (صيغة شائعة: «... المركز ..... من حيث المساحة ( الأول - الثاني - الثالث - الرابع )»)
        if len(opts) < 2:
            new_text, inline = extract_inline_choices(q.get("text", ""))
            if inline:
                q["text"] = new_text
                opts = inline
                q["options"] = inline
                q["_opt_letters"] = []   # لا حروف صريحة → التصحيح يبقى افتراضيًا
        # وإلا: اختيارات على نفس سطر السؤال (أ) ... ب) ... ج) ... د) ...)
        if len(opts) < 2:
            new_text, same = extract_sameline_choices(q.get("text", ""))
            if same:
                q["text"] = new_text
                opts = same
                q["options"] = same
                q["_opt_letters"] = []
        letters = q.get("_opt_letters", [])
        correct = "a"
        al = q.get("_answer_letter")
        if al and al in letters:
            idx = letters.index(al)
            correct = ["a", "b", "c", "d"][idx] if idx < 4 else "a"
        q["correct"] = correct
        # أكمل الخيارات الناقصة
        q["option_a"] = opts[0] if len(opts) > 0 else ""
        q["option_b"] = opts[1] if len(opts) > 1 else ""
        q["option_c"] = opts[2] if len(opts) > 2 else ""
        q["option_d"] = opts[3] if len(opts) > 3 else ""
        # لو أقل من خيارين → قد يكون تصنيفًا خاطئًا؛ نتركه MCQ لكن المراجعة ستُظهره
    q.setdefault("marks", 1)
    return q
