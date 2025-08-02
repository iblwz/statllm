# summarize_llm_stats.py (v6.3)
# Live-only scraper + DEBUG mode that dumps HTML, screenshot, and text lines as artifacts.
import os, sys, json, re, subprocess, pathlib

SECTION_TITLES = {
    "Code": "Best LLM - Code",
    "Multimodal": "Best Multimodal LLM",
    "Knowledge": "Best LLM - Knowledge",
}

DEBUG = os.getenv("DEBUG", "0") == "1"
DUMP_DIR = pathlib.Path("/tmp/llmstats")
if DEBUG:
    DUMP_DIR.mkdir(parents=True, exist_ok=True)

def try_scrape_live_site():
    try:
        from playwright.sync_api import sync_playwright
    except Exception as e:
        print(f"[error] Playwright import failed: {e}", file=sys.stderr)
        return {}, ""
    out = {}
    html_snapshot = ""
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page(viewport={"width": 1280, "height": 2400})
            page.goto("https://llm-stats.com/", wait_until="networkidle")
            page.wait_for_timeout(2500)

            if DEBUG:
                html_snapshot = page.content()
                page.screenshot(path=str(DUMP_DIR / "fullpage.png"), full_page=True)

            def clean_lines(text: str):
                lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
                return [re.sub(r"\s+", " ", ln) for ln in lines]

            def is_bad_name(ln: str, title: str) -> bool:
                low = ln.lower()
                if not ln or ln == title: return True
                if "best llm" in low or low.startswith("best "): return True
                if "benchmark" in low: return True
                if sum(ch.isdigit() for ch in ln) > len(ln) // 2: return True
                return False

            for key, title in SECTION_TITLES.items():
                tl = page.locator(f"text={title}").first
                if tl.count() == 0:
                    continue

                # Prefer closest parent card that contains ordered ranks
                candidates = [
                    tl.locator("xpath=ancestor::*[self::section or self::div][1]"),
                    tl.locator("xpath=ancestor::section[1]"),
                    tl.locator("xpath=ancestor::div[1]"),
                ]
                container = None
                for cand in candidates:
                    if cand.count() and cand.locator("text=1").count() and cand.locator("text=2").count():
                        container = cand; break
                if container is None:
                    container = candidates[0] if candidates[0].count() else tl

                text = container.inner_text()
                lines = clean_lines(text)
                if DEBUG:
                    (DUMP_DIR / f"{key}_lines.txt").write_text("\n".join(lines), encoding="utf-8")
                    (DUMP_DIR / f"{key}_html.html").write_text(container.evaluate("node => node.outerHTML"), encoding="utf-8")

                # slice segments per rank
                rank_positions = []
                for i, ln in enumerate(lines):
                    if ln in ("1", "1.", "1 .") or ln.startswith("1 "): rank_positions.append(i)
                    if ln in ("2", "2.", "2 .") or ln.startswith("2 "): rank_positions.append(i)
                    if ln in ("3", "3.", "3 .") or ln.startswith("3 "): rank_positions.append(i)
                rank_positions = sorted(set(rank_positions))

                rows = []
                for r_idx, pos in enumerate(rank_positions[:3]):
                    next_pos = rank_positions[r_idx+1] if r_idx+1 < len(rank_positions) else len(lines)
                    seg = lines[pos:next_pos]

                    # name = first non-bad line in next few
                    name = None
                    for segln in seg[1:8]:
                        if not is_bad_name(segln, title):
                            name = segln; break
                    # score = first 2-3 digit number (maybe .d) in seg
                    score = None
                    for segln in seg[:10]:
                        m = re.search(r"\b(\d{2,3}(?:\.\d)?)\b", segln)
                        if m:
                            val = float(m.group(1))
                            if 10 <= val <= 100:
                                score = val; break
                    if name and score is not None:
                        rows.append((name, score))

                if rows:
                    out[key] = rows[:3]

            browser.close()
    except Exception as e:
        print(f"[error] live site scrape failed: {e}", file=sys.stderr)
        return {}, html_snapshot
    return out, html_snapshot

def load_last(path: str):
    try:
        import json
        with open(path, "r", encoding="utf-8") as f:
            raw = json.load(f)
        return {k: [(t[0], float(t[1])) for t in v] for k, v in raw.items()}
    except Exception:
        return {}

def save_today(path: str, data):
    import json
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

def maybe_commit(path: str):
    if os.getenv("COMMIT_CHANGES", "0") != "1":
        return
    try:
        subprocess.run(["git", "config", "user.email", "github-actions[bot]@users.noreply.github.com"], check=True)
        subprocess.run(["git", "config", "user.name", "github-actions[bot]"], check=True)
        subprocess.run(["git", "add", path], check=True)
        res = subprocess.run(["git", "diff", "--cached", "--quiet"])
        if res.returncode != 0:
            subprocess.run(["git", "commit", "-m", "chore: update live_last.json"], check=True)
            subprocess.run(["git", "push"], check=True)
    except Exception as e:
        print(f"[warn] commit failed: {e}", file=sys.stderr)

def build_diff(today, yesterday):
    rank_y = {name: i for i, (name, _) in enumerate(yesterday, 1)}
    out = []
    for i, (name, s) in enumerate(today, 1):
        if name in rank_y:
            dy = rank_y[name] - i
            arrow = "↔" if dy == 0 else ("↑" if dy > 0 else "↓")
            prev_score = dict(yesterday).get(name, None)
            ds = ""
            if prev_score is not None:
                delta = round(s - prev_score, 1)
                if delta != 0:
                    sign = "+" if delta > 0 else ""
                    ds = f" ({sign}{delta})"
            out.append(f" {arrow}{ds}")
        else:
            out.append(" ↑(new)")
    return out

def build_message(live, last):
    lines = []
    lines.append("📊 LLM Stats — Daily Summary (Live)")
    lines.append("")
    for cat in ("Code","Multimodal","Knowledge"):
        if cat in live:
            lines.append(f"— {cat}:")
            diffs = build_diff(live.get(cat, []), last.get(cat, [])) if last else [""]*len(live.get(cat, []))
            for i, (pair, mark) in enumerate(zip(live[cat], diffs), 1):
                name, score = pair
                lines.append(f"  {i}. {name}: {score}{mark}")
            lines.append("")
    lines.append("Source: llm-stats.com (live)")
    return "\n".join(lines)

def send_telegram(text: str):
    import requests
    token = os.getenv("TELEGRAM_BOT_TOKEN")
    chat_id = os.getenv("TELEGRAM_CHAT_ID")
    if not token or not chat_id:
        print("Missing TELEGRAM_BOT_TOKEN or TELEGRAM_CHAT_ID.", file=sys.stderr)
        sys.exit(2)
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    r = requests.post(url, json={"chat_id": chat_id, "text": text, "parse_mode": "Markdown"}, timeout=60)
    if r.status_code != 200:
        raise RuntimeError(f"Telegram send failed: {r.status_code} {r.text}")

def main():
    data, html = try_scrape_live_site()
    if not data:
        send_telegram("⚠️ تعذّر جلب الترتيب الحي من llm-stats.com اليوم. سأحاول غدًا.")
        sys.exit(1)

    last_path = os.path.join("data", "live_last.json")
    last = load_last(last_path)

    msg = build_message(data, last)
    send_telegram(msg)

    save_today(last_path, data)
    maybe_commit(last_path)

    if DEBUG and html:
        (DUMP_DIR / "page.html").write_text(html, encoding="utf-8")

    print("Sent live summary and saved snapshot.")

if __name__ == "__main__":
    main()
