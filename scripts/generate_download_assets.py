from pathlib import Path

from arabic_reshaper import reshape
from bidi.algorithm import get_display
from reportlab.lib.colors import HexColor
from reportlab.lib.enums import TA_LEFT, TA_RIGHT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import PageBreak, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle


ROOT = Path(__file__).resolve().parents[1]
DOWNLOADS = ROOT / "downloads"
FONT = "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"
FONT_BOLD = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"

pdfmetrics.registerFont(TTFont("DejaVu", FONT))
pdfmetrics.registerFont(TTFont("DejaVu-Bold", FONT_BOLD))

INK = HexColor("#273421")
OLIVE = HexColor("#526247")
GOLD = HexColor("#A97B2F")
PARCHMENT = HexColor("#FBF8EF")
RULE = HexColor("#D8C9A8")


def ar(text: str) -> str:
    return get_display(reshape(text))


def styles():
    return {
        "title": ParagraphStyle(
            "title", fontName="DejaVu-Bold", fontSize=22, leading=34,
            textColor=INK, alignment=TA_RIGHT, spaceAfter=8 * mm,
        ),
        "subtitle": ParagraphStyle(
            "subtitle", fontName="DejaVu", fontSize=11, leading=20,
            textColor=OLIVE, alignment=TA_RIGHT, spaceAfter=6 * mm,
        ),
        "heading": ParagraphStyle(
            "heading", fontName="DejaVu-Bold", fontSize=14, leading=24,
            textColor=GOLD, alignment=TA_RIGHT, spaceBefore=5 * mm, spaceAfter=2 * mm,
        ),
        "body": ParagraphStyle(
            "body", fontName="DejaVu", fontSize=10.5, leading=20,
            textColor=INK, alignment=TA_RIGHT, spaceAfter=3 * mm,
        ),
        "en": ParagraphStyle(
            "en", fontName="DejaVu", fontSize=9.5, leading=16,
            textColor=INK, alignment=TA_LEFT, spaceAfter=3 * mm,
        ),
        "small": ParagraphStyle(
            "small", fontName="DejaVu", fontSize=8.5, leading=14,
            textColor=OLIVE, alignment=TA_RIGHT,
        ),
    }


def decorate(canvas, doc):
    canvas.saveState()
    width, height = A4
    canvas.setFillColor(PARCHMENT)
    canvas.rect(0, 0, width, height, fill=1, stroke=0)
    canvas.setFillColor(INK)
    canvas.rect(0, height - 15 * mm, width, 15 * mm, fill=1, stroke=0)
    canvas.setFillColor(GOLD)
    canvas.rect(0, height - 15.8 * mm, width, 0.8 * mm, fill=1, stroke=0)
    canvas.setFont("DejaVu-Bold", 9)
    canvas.setFillColor(PARCHMENT)
    canvas.drawRightString(width - 18 * mm, height - 10 * mm, ar("سُطور من أوال 2.0"))
    canvas.setStrokeColor(RULE)
    canvas.line(18 * mm, 14 * mm, width - 18 * mm, 14 * mm)
    canvas.setFont("DejaVu", 8)
    canvas.setFillColor(OLIVE)
    canvas.drawString(18 * mm, 9 * mm, f"{doc.page}")
    canvas.drawRightString(width - 18 * mm, 9 * mm, ar("منصة التوثيق الرقمي للتراث"))
    canvas.restoreState()


def build_pdf(filename: str, story):
    doc = SimpleDocTemplate(
        str(DOWNLOADS / filename), pagesize=A4,
        rightMargin=20 * mm, leftMargin=20 * mm,
        topMargin=24 * mm, bottomMargin=20 * mm,
        title=filename,
    )
    doc.build(story, onFirstPage=decorate, onLaterPages=decorate)


def p(text, style):
    return Paragraph(ar(text), style)


def research_pdf(s):
    story = [
        Spacer(1, 8 * mm),
        p("البحث الكامل لمنصة سُطور من أوال 2.0", s["title"]),
        p("ملف بحثي جامع للمحتوى العلمي والمنهجي المنشور داخل المنصة التفاعلية", s["subtitle"]),
        p("الملخص", s["heading"]),
        p("تقدّم سُطور من أوال منصة بحثية حية لتوثيق تراث إقليم البحرين وجزيرة أوال، وتجمع بين السرد التاريخي والبيانات الدلالية والمخطوطات والمعالم والأعلام في تجربة رقمية قابلة للاستكشاف والاستشهاد.", s["body"]),
        p("المنهجية", s["heading"]),
        p("اعتمد المشروع منهجية علم التصميم البحثي بمراحل تحديد المشكلة، وصياغة الأهداف، والتصميم والتطوير، والعرض، والتقييم، ثم التواصل العلمي. كما راعى مبادئ التراث الرقمي والتشغيل البيني وإتاحة البيانات.", s["body"]),
        p("البنية التقنية", s["heading"]),
        p("تتكوّن المنصة من طبقة عرض تفاعلية، وطبقة بيانات أنطولوجية، وطبقة دلالية للتصدير بصيغة JSON-LD، وأدوات بحث وتنقّل، ومخرجات مفتوحة قابلة للقراءة آليًا.", s["body"]),
        p("التوثيق والتحقق", s["heading"]),
        p("تربط المنصة المعلومات بمصادرها وتعرض درجات التحقق، وتتيح للمستخدم الانتقال بين الشخصيات والمخطوطات والأماكن والأحداث ضمن سياق مترابط.", s["body"]),
        p("التقييم", s["heading"]),
        p("أظهرت مؤشرات المنصة المعلنة نتيجة 84.25 في مقياس قابلية الاستخدام SUS لعينة من 20 مشاركًا، ومعامل موثوقية كرونباخ ألفا قدره 0.891. كما تسجل نتائج Lighthouse المعلنة 98 للأداء، و100 لإمكانية الوصول، و96 لتحسين محركات البحث، و100 لأفضل الممارسات.", s["body"]),
        p("المخرجات المفتوحة", s["heading"]),
        p("تشمل المخرجات قاعدة بيانات دلالية بصيغة JSON-LD، وبيانات تقييم مجمعة مجهولة الهوية بصيغة CSV، ودليل المنصة، ومواد التوثيق الرقمي للتراث.", s["body"]),
        p("صيغة الاستشهاد المقترحة", s["heading"]),
        p("منصة «سطور من أوال 2.0» — النسخة التفاعلية المرافقة للبحث العلمي، جامعة البحرين، 2026. يُذكر رابط المنصة وتاريخ الوصول عند الاستشهاد.", s["body"]),
        Spacer(1, 4 * mm),
        Paragraph("Sutoor Min Awal 2.0 is a living research platform for documenting Bahrain and Awal heritage through linked cultural data, interactive narratives, and open scholarly outputs.", s["en"]),
    ]
    build_pdf("research-paper.pdf", story)


def lighthouse_pdf(s):
    rows = [
        [ar("المؤشر"), ar("النتيجة")],
        [ar("الأداء"), "98 / 100"],
        [ar("إمكانية الوصول"), "100 / 100"],
        [ar("تحسين محركات البحث"), "96 / 100"],
        [ar("أفضل الممارسات"), "100 / 100"],
    ]
    table = Table(rows, colWidths=[105 * mm, 45 * mm], hAlign="RIGHT")
    table.setStyle(TableStyle([
        ("FONTNAME", (0, 0), (-1, 0), "DejaVu-Bold"),
        ("FONTNAME", (0, 1), (-1, -1), "DejaVu"),
        ("FONTSIZE", (0, 0), (-1, -1), 10),
        ("BACKGROUND", (0, 0), (-1, 0), INK),
        ("TEXTCOLOR", (0, 0), (-1, 0), PARCHMENT),
        ("BACKGROUND", (0, 1), (-1, -1), HexColor("#F3EBD9")),
        ("TEXTCOLOR", (0, 1), (-1, -1), INK),
        ("ALIGN", (0, 0), (-1, -1), "RIGHT"),
        ("GRID", (0, 0), (-1, -1), 0.5, RULE),
        ("TOPPADDING", (0, 0), (-1, -1), 9),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 9),
    ]))
    story = [
        Spacer(1, 8 * mm),
        p("تقرير نتائج Lighthouse", s["title"]),
        p("ملخص قابل للتنزيل للمؤشرات المعلنة داخل منصة سُطور من أوال 2.0", s["subtitle"]),
        table,
        Spacer(1, 8 * mm),
        p("نطاق التقرير", s["heading"]),
        p("يوثق هذا الملف النتائج المعروضة داخل المنصة ويجعلها قابلة للفتح والتنزيل. لا يتضمن هذا الملخص ملف التدقيق الخام أو تفاصيل بيئة التشغيل، لذلك ينبغي الرجوع إلى سجل التدقيق الأصلي عند الحاجة إلى إعادة إنتاج القياس تقنيًا.", s["body"]),
        p("قراءة النتائج", s["heading"]),
        p("تشير النتائج المعلنة إلى أداء مرتفع، وإتاحة مكتملة في الاختبار، والتزام قوي بأفضل الممارسات، مع مجال محدود لتحسين عناصر تحسين محركات البحث.", s["body"]),
    ]
    build_pdf("lighthouse-report.pdf", story)


def guide_pdf(s):
    story = [
        Spacer(1, 8 * mm),
        p("دليل منصة سُطور من أوال 2.0", s["title"]),
        p("دليل مختصر للاستكشاف والبحث والتنزيل", s["subtitle"]),
        p("بدء الاستخدام", s["heading"]),
        p("استخدم شريط الأقسام الثاني للانتقال إلى فهارس الأعلام والمخطوطات والأماكن والأحداث، أو لفتح المعالم التفاعلية وسطور الأنساب ومشروع التوثيق الرقمي للتراث.", s["body"]),
        p("البحث والاستكشاف", s["heading"]),
        p("تدعم المنصة التصفح الموضوعي والبحث في السجلات. افتح أي بطاقة لقراءة الوصف والمصادر والروابط الدلالية المرتبطة بها.", s["body"]),
        p("المعالم التفاعلية", s["heading"]),
        p("تعرض صفحة المعالم خريطة استكشافية مستقلة. اختر المعلم لعرض معلوماته وسياقه داخل المدوّنة التراثية.", s["body"]),
        p("سطور الأنساب", s["heading"]),
        p("يوفّر قسم الأنساب قوالب متعددة لعرض الأشجار العائلية ومسارات النسب أفقيًا وعموديًا، مع أدوات مخصصة لبناء التصور المناسب.", s["body"]),
        p("التنزيلات", s["heading"]),
        p("تتوفر ملفات البحث والتقرير والدليل بصيغة PDF، والبيانات المجمعة المجهولة الهوية بصيغة CSV، وقاعدة البيانات الدلالية بصيغة JSON-LD مولّدة مباشرة من بيانات المنصة.", s["body"]),
        p("إتاحة الملفات", s["heading"]),
        p("يمكن فتح ملفات PDF في المتصفح أو قارئ PDF، وفتح CSV في برامج الجداول، وفتح JSON-LD في المتصفح أو محرر النصوص أو أدوات البيانات الدلالية.", s["body"]),
    ]
    build_pdf("platform-guide.pdf", story)


def aggregate_csv():
    content = "\ufeffmetric_ar,metric_en,value,unit,notes_ar\r\n"
    rows = [
        ("عدد المشاركين", "participant_count", "20", "participants", "بيانات مجمعة دون معرّفات شخصية"),
        ("متوسط مقياس قابلية الاستخدام", "sus_score", "84.25", "points", "الدرجة المعلنة في المنصة"),
        ("معامل كرونباخ ألفا", "cronbach_alpha", "0.891", "coefficient", "اتساق داخلي مرتفع"),
        ("حالة إخفاء الهوية", "anonymized", "true", "boolean", "لا يتضمن الملف بيانات فردية أو كاشفة"),
    ]
    for row in rows:
        content += ",".join(f'"{value}"' for value in row) + "\r\n"
    (DOWNLOADS / "sus-dataset-anonymous.csv").write_text(content, encoding="utf-8")


if __name__ == "__main__":
    DOWNLOADS.mkdir(parents=True, exist_ok=True)
    sheet = styles()
    research_pdf(sheet)
    lighthouse_pdf(sheet)
    guide_pdf(sheet)
    aggregate_csv()
