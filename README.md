# LLM Stats → Telegram (Daily)

يرسل لك **ملخص يومي** لأبرز نتائج موقع [llm-stats.com](https://llm-stats.com) على تيليجرام،
مقسّم إلى: Coding / Math / Reasoning.

**الآلية:** السكربت يسحب البيانات من المستودع المفتوح الذي يغذي الموقع (GitHub)
ثم يختار أعلى النماذج لكل فئة ويرسلها لك برسالة مختصرة.

## الإعداد (مرة وحدة)

1) أنشئ Repository جديد في GitHub (عام أو خاص).
2) ارفع هذه الملفات الأربع في جذر الريبو:
   - `summarize_llm_stats.py`
   - `requirements.txt`
   - `.github/workflows/daily-summary.yml`
   - `README.md`
3) من **Settings → Secrets and variables → Actions → New repository secret** أضف:
   - `TELEGRAM_BOT_TOKEN` (من @BotFather)
   - `TELEGRAM_CHAT_ID` (حط معرفك أو القناة/الجروب)
4) جدول التشغيل جاهز: يوميًا **06:00 UTC** (= **09:00 الرياض**). تقدر تشغّلها يدوي من تبويب **Actions**.

## قابلية التخصيص
- لو تبي تغيّر الكلمات المفتاحية المستخدمة للتصنيف (مثلاً إضافة `LiveCodeBench` لفئة الـ Coding)، عدّل القوائم داخل `CATEGORIES` في السكربت.
- السكربت يحاول يتعامل بمرونة مع تغيّر بنية البيانات ويستخرج أي قيمة رقمية موثوقة (0–1 أو %).
- المخرجات تكون مثل:
  ```
  — Coding:
    1. Model A: 93.1%
    2. Model B: 91.8%
  — Math:
    ...
  — Reasoning:
    ...
  ```

## ملاحظات
- المصدر: مستودع البيانات المفتوح لـ llm-stats (نفس بيانات الموقع).
- لو المستودع غيّر البنية بشكل جذري، حدّث قوائم الكلمات المفتاحية أو افتح Issue.
- لتجربة محلية: فعّل بايثون 3.11، ثم:
  ```bash
  pip install -r requirements.txt
  TELEGRAM_BOT_TOKEN=xxx TELEGRAM_CHAT_ID=yyy python summarize_llm_stats.py
  ```
