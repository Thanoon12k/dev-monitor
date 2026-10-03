"""Mobile app course: 8 two-hour sessions, each with a checklist of steps."""
import json
import os

from flask import Blueprint, jsonify, render_template, request

bp = Blueprint("course", __name__, template_folder="../../templates")

STATE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "data", "course.json")

# (title, emoji, steps); a step starting with "مهمة:" is homework before the next session.
SESSIONS = [
    ("تجهيز الجهاز والانطلاقة", "🚀", [
        "الترحيب والتعارف وشرح فكرة الكورس (10 د)",
        "فحص الجهاز وحسابات GitHub و Claude Pro (10 د)",
        "تنصيب Git و VS Code وإضافة Flutter",
        "تنصيب Flutter SDK وإضافته للـ PATH",
        "تنصيب Android Studio و Command-line Tools",
        "flutter doctor كله ✔️ + قبول الرخص",
        "تجهيز محاكي أندرويد وتشغيله",
        "تنصيب Claude Code وتسجيل الدخول",
        "أول تطبيق بطلب من Claude وتشغيله على المحاكي",
        "فتح التطبيق على الآيفون عن طريق Safari والواي فاي",
        "رفع المشروع على GitHub",
        "مهمة: يشغّل التطبيق بروحه + 3 تعديلات + سكرين شوت",
        "مهمة: يكتب فكرة تطبيقه بفقرة",
    ]),
    ("شلون تحچي ويا الذكاء الاصطناعي", "🧠", [
        "مراجعة مهام الجلسة 1",
        "سر كتابة الطلب الصحيح لـ Claude",
        "الأخطاء الشائعة وشلون نتجنبها",
        "كتابة دستور المشروع (CLAUDE.md)",
        "تحويل الفكرة لخطة بـ Plan Mode",
        "مهمة: فكرة التطبيق مكتوبة بالتفصيل",
        "مهمة: خطة التطبيق جاهزة ومراجعة",
    ]),
    ("بناء شاشات التطبيق", "📲", [
        "مراجعة مهام الجلسة 2",
        "بناء الشاشة الرئيسية",
        "بناء القوائم والصفحات الفرعية",
        "التنقل بين الصفحات (قائمة سفلية/جانبية)",
        "شلون نرجع خطوة لورا إذا Claude خرب شي",
        "مهمة: كل الشاشات موجودة وتتنقل بينها",
    ]),
    ("التصميم الاحترافي", "🎨", [
        "مراجعة مهام الجلسة 3",
        "الألوان والخطوط وهوية التطبيق",
        "دعم العربي كامل (RTL)",
        "الوضع الليلي",
        "إعطاء Claude صورة تصميم ويبنيها",
        "التطبيق مرتب على كل أحجام الشاشات",
        "مهمة: سكرين شوت لكل الشاشات النهائية",
    ]),
    ("البيانات والحسابات", "🔐", [
        "مراجعة مهام الجلسة 4",
        "حفظ البيانات داخل الجهاز",
        "ربط قاعدة بيانات أونلاين مجانية",
        "تسجيل دخول بالإيميل و Google",
        "كل مستخدم يشوف بياناته بس",
        "مهمة: تسجيل الدخول شغال",
        "مهمة: إضافة وتعديل وحذف والبيانات محفوظة",
    ]),
    ("المزايا المتقدمة", "⚡", [
        "مراجعة مهام الجلسة 5",
        "الإشعارات",
        "رفع الصور والكاميرا",
        "ذكاء اصطناعي داخل التطبيق (مساعد/شات)",
        "Claude يلگه الأخطاء ويصلحها",
        "مهمة: ميزتين متقدمتين على الأقل",
        "مهمة: تجربة من شخصين وتصليح ملاحظاتهم",
    ]),
    ("التجهيز للنشر", "🛠️", [
        "مراجعة مهام الجلسة 6",
        "أيقونة التطبيق وشاشة البداية",
        "اسم التطبيق واللمسات الأخيرة",
        "بناء نسخة الأندرويد",
        "بناء نسخة الآيفون على Codemagic",
        "تنصيب على الآيفون بـ Sideloadly",
        "فحص أخير قبل النشر",
        "مهمة: التطبيق يشتغل على الأندرويد والآيفون",
        "مهمة: 3 أشخاص يجربوه",
    ]),
    ("النشر على الأندرويد والآيفون والتسليم", "🏆", [
        "مراجعة مهام الجلسة 7",
        "إنشاء حساب مطوّر Google Play",
        "إنشاء حساب Apple Developer",
        "رفع ونشر التطبيق على Google Play",
        "رفع ونشر التطبيق على App Store",
        "صور ووصف التطبيق للمتجر",
        "إضافة التطبيق للموقع الشخصي (الهدية)",
        "شلون يكمل ويطوّر بعد الكورس",
        "عرض نهائي وتسليم 🎓",
    ]),
]


def load():
    try:
        with open(STATE) as f:
            s = json.load(f)
    except (OSError, ValueError):
        s = {}
    s.setdefault("done", [])
    s.setdefault("notes", {})
    return s


def save(s):
    with open(STATE, "w") as f:
        json.dump(s, f, ensure_ascii=False, indent=2)


def _admin():
    from app import check_csrf, login_required
    return check_csrf, login_required


check_csrf, login_required = _admin()


@bp.route("/")
@login_required
def dashboard():
    s = load()
    done = set(s["done"])
    sessions, prev_complete = [], True
    for n, (title, emoji, steps) in enumerate(SESSIONS, 1):
        items = [{"key": f"{n}-{i}", "text": t, "task": t.startswith("مهمة:"), "done": f"{n}-{i}" in done}
                 for i, t in enumerate(steps)]
        c = sum(x["done"] for x in items)
        complete = c == len(items)
        sessions.append({"n": n, "title": title, "emoji": emoji, "steps": items, "count": c,
                         "total": len(items), "pct": round(100 * c / len(items)), "complete": complete,
                         "locked": not prev_complete, "note": s["notes"].get(str(n), "")})
        prev_complete = complete
    total = sum(x["total"] for x in sessions)
    count = sum(x["count"] for x in sessions)
    current = next((x["n"] for x in sessions if not x["complete"]), None)
    return render_template("course/dashboard.html", sessions=sessions, total=total, count=count,
                           pct=round(100 * count / total), current=current)


@bp.route("/toggle", methods=["POST"])
@login_required
def toggle():
    check_csrf()
    key = request.form.get("key", "")
    valid = {f"{n}-{i}" for n, (_, _, st) in enumerate(SESSIONS, 1) for i in range(len(st))}
    if key not in valid:
        return jsonify(ok=False), 400
    s = load()
    done = set(s["done"])
    done.symmetric_difference_update({key})
    s["done"] = sorted(done)
    save(s)
    return jsonify(ok=True, done=key in done)


@bp.route("/note", methods=["POST"])
@login_required
def note():
    check_csrf()
    n = request.form.get("n", "")
    if not n.isdigit() or not 1 <= int(n) <= len(SESSIONS):
        return jsonify(ok=False), 400
    s = load()
    s["notes"][n] = request.form.get("note", "")[:2000]
    save(s)
    return jsonify(ok=True)
