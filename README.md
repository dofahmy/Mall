# ميجا مول وفر كاش V2 — Railway

## الجديد
- لعبة Mall Rush: خدمة طلبات الزبائن في الوقت المحدد؛ بدون استهلاك طاقة أو انتظار.
- كل جولة ناجحة تمنح عملات وخبرة وقطعًا لصناعة الأصول.
- لوحة الدمج السابقة موجودة داخل «ورشة الدمج والتصنيع» اختيارية.
- سوق تجريبي بين ثلاثة حسابات بعمولة افتراضية 10%. لا يوجد دفع أو سحب حقيقي.

## نشر مستقل على Railway
1. ارفع محتويات المجلد (وليس ZIP نفسه) إلى GitHub repo مستقل.
2. أنشئ مشروع Railway جديدًا Deploy from GitHub Repo.
3. اربط volume بالمسار /data.
4. اضبط Variables: DEMO_MODE=1 و DATABASE_PATH=/data/megamal.db.
5. Generate Domain من Networking.
6. اترك الخدمة القديمة منفصلة.

## محليًا
```bash
python -m pip install -r requirements.txt
DEMO_MODE=1 python app.py
```
افتح http://localhost:5000

## ملاحظات
وضع DEMO_MODE=1 يسمح لأي زائر بالاختبار على الحسابات الثلاثة، فلا تستخدمه للنشر العام. للاستخدام داخل تليجرام اضبط BOT_TOKEN وعطّل DEMO_MODE مع HTTPS. SQLite على volume مناسب للتجارب الصغيرة وليس لتوسّع 15000 لاعب متزامن.
