"""
تصدير الامتحان إلى ملف Microsoft Word (.docx) منسّق وجاهز للطباعة.
"""
import io


LETTERS = ["أ", "ب", "ج", "د"]


QTYPE_AR = {
    "mcq": "اختر الإجابة الصحيحة",
    "truefalse": "ضع علامة (صح) أو (خطأ)",
    "complete": "أكمل ما يأتي",
    "explain": "بمَ تفسّر",
    "results": "ما النتائج المترتبة على",
    "meaning": "ما المقصود بـ",
    "compare": "قارن",
    "prove": "دلّل على",
    "map": "اكتب مدلول الأرقام على الخريطة التالية",
    "map_complete": "أكمل مدلول الأرقام على الخريطة التالية",
    # أنواع قديمة
    "matching": "وصّل من العمود (أ) لما يناسبه في (ب)",
    "ordering": "رتّب ما يأتي",
    "cause_effect": "سبب ونتيجة",
    "analysis": "تحليل واستنتاج",
    "short": "أجب عمّا يأتي",
}


def build_exam_docx(title, teacher, subject, questions, with_answers=False,
                    group=None, duration=None, grade=None, term=None):
    """يبني ملف docx للامتحان (عربي RTL كامل) ويرجّع bytes"""
    from docx import Document
    from docx.shared import Pt, RGBColor
    from docx.enum.text import WD_ALIGN_PARAGRAPH
    from docx.enum.section import WD_ORIENT
    from docx.oxml.ns import qn
    from docx.oxml import OxmlElement

    doc = Document()

    def _answer_line(paragraph, width_pt=260):
        """يضيف مساحة إجابة بخط سفلي فعلي (bottom border) بعرض ثابت — بدل نقاط كثيرة."""
        run = paragraph.add_run(" " * 40)
        # حدّ سفلي على الفقرة يعطي سطر إجابة نظيف بعرض ثابت
        pPr = paragraph._p.get_or_add_pPr()
        pbdr = OxmlElement("w:pBdr")
        bottom = OxmlElement("w:bottom")
        bottom.set(qn("w:val"), "single")
        bottom.set(qn("w:sz"), "6")
        bottom.set(qn("w:space"), "1")
        bottom.set(qn("w:color"), "808080")
        pbdr.append(bottom)
        pPr.append(pbdr)
        return run

    def _set(el, tag, **attrs):
        """ينشئ/يضيف عنصر XML بقيم w:val وغيرها."""
        child = OxmlElement(tag)
        for k, v in attrs.items():
            child.set(qn(k), v)
        el.append(child)
        return child

    # RTL على مستوى الفقرة (bidi) + المحاذاة لليمين
    def set_rtl(paragraph):
        p = paragraph._p
        pPr = p.get_or_add_pPr()
        # bidi يجب أن يأتي بقيمة صريحة
        existing = pPr.find(qn("w:bidi"))
        if existing is None:
            _set(pPr, "w:bidi", **{"w:val": "1"})
        paragraph.alignment = WD_ALIGN_PARAGRAPH.RIGHT
        # علّم كل الأشواط (runs) بأنها RTL أيضًا (يعالج النص المختلط عربي/أرقام)
        for run in paragraph.runs:
            _run_rtl(run)
        return paragraph

    def _run_rtl(run):
        rPr = run._element.get_or_add_rPr()
        if rPr.find(qn("w:rtl")) is None:
            _set(rPr, "w:rtl", **{"w:val": "1"})

    # أضف فقرة RTL جاهزة (كل ما يُكتب فيها لاحقًا يُعلَّم RTL)
    def add_rtl_paragraph(text=None, bold=False, size=None, color=None, italic=False):
        para = doc.add_paragraph()
        set_rtl(para)
        if text is not None:
            r = para.add_run(text)
            if bold:
                r.bold = True
            if italic:
                r.italic = True
            if size:
                r.font.size = Pt(size)
            if color:
                r.font.color.rgb = color
            _run_rtl(r)
        return para

    # الخط الافتراضي (عربي متوافق) لكل المستند + RTL على مستوى المستند
    style = doc.styles["Normal"]
    style.font.name = "Arial"
    style.font.size = Pt(13)
    rpr = style.element.get_or_add_rPr()
    rfonts = rpr.get_or_add_rFonts()
    rfonts.set(qn("w:ascii"), "Arial")
    rfonts.set(qn("w:hAnsi"), "Arial")
    rfonts.set(qn("w:cs"), "Arial")
    # اجعل RTL هو الافتراضي في نمط Normal (فقرة + شوط)
    ppr = style.element.get_or_add_pPr()
    if ppr.find(qn("w:bidi")) is None:
        _set(ppr, "w:bidi", **{"w:val": "1"})
    if rpr.find(qn("w:rtl")) is None:
        _set(rpr, "w:rtl", **{"w:val": "1"})

    # اجعل القسم (section) RTL + مقاس A4 والهوامش المناسبة
    from docx.shared import Cm
    for section in doc.sections:
        sectPr = section._sectPr
        if sectPr.find(qn("w:bidi")) is None:
            _set(sectPr, "w:bidi", **{"w:val": "1"})
        section.page_width = Cm(21.0)     # A4
        section.page_height = Cm(29.7)
        section.right_margin = Cm(2.2)
        section.left_margin = Cm(2.2)
        section.top_margin = Cm(1.8)
        section.bottom_margin = Cm(1.8)

    # الترويسة: اسم المدرس والمادة (وسط)
    head = doc.add_paragraph()
    head.alignment = WD_ALIGN_PARAGRAPH.CENTER
    _set(head._p.get_or_add_pPr(), "w:bidi", **{"w:val": "1"})
    run = head.add_run(f"{teacher} — {subject}")
    run.bold = True
    run.font.size = Pt(15)
    _run_rtl(run)

    # عنوان الامتحان المخصّص (وسط، بارز)
    t = doc.add_paragraph()
    t.alignment = WD_ALIGN_PARAGRAPH.CENTER
    _set(t._p.get_or_add_pPr(), "w:bidi", **{"w:val": "1"})
    tr = t.add_run(title)
    tr.bold = True
    tr.font.size = Pt(19)
    tr.font.color.rgb = RGBColor(0x1E, 0x3A, 0x8A)
    _run_rtl(tr)

    # الصف والترم (وسط) إن وُجدا
    sub_bits = [b for b in [grade, term] if b]
    if sub_bits:
        st = doc.add_paragraph()
        st.alignment = WD_ALIGN_PARAGRAPH.CENTER
        _set(st._p.get_or_add_pPr(), "w:bidi", **{"w:val": "1"})
        sr = st.add_run("   |   ".join(sub_bits))
        sr.bold = True
        sr.font.size = Pt(13)
        _run_rtl(sr)

    total = sum(q.get("marks", 1) for q in questions)
    info = doc.add_paragraph()
    set_rtl(info)
    info_txt = f"عدد الأسئلة: {len(questions)}   |   الدرجة الكلية: {total:g}"
    if duration:
        info_txt += f"   |   الزمن: {duration} دقيقة"
    info.add_run(info_txt)

    # حقول الطالب (الاسم / الفصل / التاريخ) بخطوط سفلية نظيفة
    sline = doc.add_paragraph()
    set_rtl(sline)
    grp = group or "____________"
    sline.add_run(f"الاسم: ______________________     الفصل: {grp}     التاريخ: ____________")

    sep = doc.add_paragraph()
    sep.alignment = WD_ALIGN_PARAGRAPH.CENTER
    _set(sep._p.get_or_add_pPr(), "w:bidi", **{"w:val": "1"})
    sep.add_run("═" * 40)

    # تعليمات
    instr = doc.add_paragraph()
    set_rtl(instr)
    instr.add_run("تعليمات: اقرأ الأسئلة جيدًا وأجب عن جميع الأسئلة بخط واضح.").italic = True

    # تجميع الأسئلة حسب النوع (يحافظ على ترتيب ظهور الأنواع)
    order = ["mcq", "truefalse", "complete", "map", "map_complete",
             "explain", "results", "meaning",
             "compare", "prove", "matching", "ordering", "cause_effect",
             "analysis", "short"]
    grouped = {}
    for q in questions:
        grouped.setdefault(q["type"], []).append(q)

    qnum = 0
    for typ in order:
        if typ not in grouped:
            continue
        # عنوان القسم
        sec = doc.add_paragraph()
        set_rtl(sec)
        sr = sec.add_run(f"■ {QTYPE_AR.get(typ, typ)}")
        sr.bold = True
        sr.font.size = Pt(14)
        sr.font.color.rgb = RGBColor(0x1D, 0x4E, 0xD8)

        for q in grouped[typ]:
            qnum += 1
            p = doc.add_paragraph()
            set_rtl(p)
            p.paragraph_format.space_before = Pt(8)
            # طبّع النقاط الكثيرة داخل نص السؤال إلى فراغ إجابة قصير موحّد
            import re as _re
            qtext = _re.sub(r"[.\u2026]{3,}", " ............ ", q.get("text", "")).strip()
            qtext = _re.sub(r"\s{2,}", " ", qtext)
            qr = p.add_run(f"{qnum}) {qtext}   ({q.get('marks',1):g} درجة)")
            qr.bold = True

            if typ == "mcq":
                for i, opt in enumerate(q.get("options", [])):
                    if not (opt or "").strip():
                        continue  # تجاهل الاختيارات الفارغة
                    op = doc.add_paragraph()
                    set_rtl(op)
                    # مسافة بادئة من اليمين (RTL) لتنسيق واضح للاختيارات
                    op.paragraph_format.right_indent = Pt(24)
                    mark = " ✔" if (with_answers and i == q.get("answer_index", 0)) else ""
                    r = op.add_run(f"{LETTERS[i]}) {opt}{mark}")
                    _run_rtl(r)
            elif typ == "truefalse":
                op = doc.add_paragraph()
                set_rtl(op)
                if with_answers:
                    op.add_run("    الإجابة: " + ("صح ✔" if q.get("answer") else "خطأ ✔"))
                else:
                    op.add_run("    (    ) صح            (    ) خطأ")
            elif typ == "matching":
                left = q.get("left", [])
                right = q.get("right", [])
                op = doc.add_paragraph()
                set_rtl(op)
                op.add_run("    العمود (أ):").bold = True
                for k, item in enumerate(left):
                    li = doc.add_paragraph()
                    set_rtl(li)
                    li.add_run(f"      {k+1}) {item}  (........)")
                op2 = doc.add_paragraph()
                set_rtl(op2)
                op2.add_run("    العمود (ب):").bold = True
                # نعرض العمود (ب) بترتيب مخلوط في ورقة الأسئلة، والحل بالترتيب لو answers
                disp = list(right)
                for k, item in enumerate(disp):
                    ri = doc.add_paragraph()
                    set_rtl(ri)
                    ri.add_run(f"      {chr(0x0623 + 0)}{k+1}. {item}")
                if with_answers and q.get("answer"):
                    ap = doc.add_paragraph(); set_rtl(ap)
                    a = ap.add_run(f"    الإجابة: {q['answer']}")
                    a.italic = True; a.font.color.rgb = RGBColor(0x15, 0x80, 0x3D)
            elif typ == "ordering":
                items = q.get("items") or q.get("answer_order", [])
                for k, item in enumerate(items):
                    li = doc.add_paragraph()
                    set_rtl(li)
                    li.add_run(f"    (....) {item}")
                if with_answers and q.get("answer"):
                    ap = doc.add_paragraph(); set_rtl(ap)
                    a = ap.add_run(f"    الترتيب الصحيح: {q['answer']}")
                    a.italic = True; a.font.color.rgb = RGBColor(0x15, 0x80, 0x3D)
            elif typ in ("map", "map_complete"):
                # أدرج صورة الخريطة (من data URI base64) داخل ملف Word
                img = q.get("map_image", "")
                if img and "," in img:
                    try:
                        import base64 as _b64
                        raw = _b64.b64decode(img.split(",", 1)[1])
                        from docx.shared import Inches
                        ip = doc.add_paragraph(); set_rtl(ip)
                        ip.add_run().add_picture(io.BytesIO(raw), width=Inches(4.5))
                    except Exception:
                        pass
                for it in q.get("map_items", []):
                    li = doc.add_paragraph()
                    set_rtl(li)
                    if with_answers and it.get("answer"):
                        r = li.add_run(f"    {it.get('num')}- {it.get('answer')}")
                        r.font.color.rgb = RGBColor(0x15, 0x80, 0x3D)
                    else:
                        li.add_run(f"    {it.get('num')}- ")
                        _answer_line(li)
            else:
                if with_answers and q.get("answer"):
                    ap = doc.add_paragraph()
                    set_rtl(ap)
                    ans = ap.add_run(f"    الإجابة النموذجية: {q['answer']}")
                    ans.italic = True
                    ans.font.color.rgb = RGBColor(0x15, 0x80, 0x3D)
                else:
                    # مساحة كتابة بأسطر إجابة نظيفة (خط سفلي بعرض ثابت) — بلا نقاط كثيرة
                    _lines = {"compare": 4, "explain": 2, "results": 3, "meaning": 2,
                              "prove": 3, "analysis": 3, "short": 2}.get(typ, 2)
                    for _ in range(_lines):
                        line = doc.add_paragraph()
                        set_rtl(line)
                        line.paragraph_format.space_after = Pt(10)
                        _answer_line(line)

    doc.add_paragraph()
    end = doc.add_paragraph()
    set_rtl(end)
    er = end.add_run("انتهت الأسئلة — مع تمنياتنا بالتوفيق")
    er.bold = True

    # تمريرة نهائية: اضمن RTL على كل فقرة وكل شوط في المستند (يعالج الأشواط التي
    # أُضيفت بعد استدعاء set_rtl، والنص المختلط عربي/أرقام/إنجليزي).
    for para in doc.paragraphs:
        p_pr = para._p.get_or_add_pPr()
        if p_pr.find(qn("w:bidi")) is None:
            _set(p_pr, "w:bidi", **{"w:val": "1"})
        if para.alignment not in (WD_ALIGN_PARAGRAPH.CENTER,):
            para.alignment = WD_ALIGN_PARAGRAPH.RIGHT
        for run in para.runs:
            _run_rtl(run)

    buf = io.BytesIO()
    doc.save(buf)
    buf.seek(0)
    return buf.getvalue()
