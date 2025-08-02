# summarize_llm_stats.py (v6)
# Live-only summary from https://llm-stats.com with day-over-day (DoD) comparison.
# - Scrapes homepage sections via Playwright (Chromium):
#     * Best LLM - Code
#     * Best Multimodal LLM
#     * Best LLM - Knowledge
# - Compares with yesterday's saved snapshot (data/live_last.json) if present.
# - Saves today's snapshot and (optionally) commits it (set COMMIT_CHANGES=1 in env).
#
# Required secrets:
#   TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID
#
# Notes:
# - If live scrape fails, the script sends a short error message and exits 1.
import os, sys, json, re, time, subprocess
from typing import Dict, List, Tuple

def try_scrape_live_site() -> Dict[str, List[Tuple[str, float]]]:
    try:
        from playwright.sync_api import sync_playwright
    except Exception as e:
        print(f"[error] Playwright import failed: {e}", file=sys.stderr)
        return {}
    out: Dict[str, List[Tuple[str, float]]] = {}
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page()
            page.goto("https://llm-stats.com/", wait_until="networkidle")
            page.wait_for_timeout(2000)

            sections = [
                ("Code", "Best LLM - Code"),
                ("Multimodal", "Best Multimodal LLM"),
                ("Knowledge", "Best LLM - Knowledge"),
            ]

            for key, title in sections:
                title_loc = page.locator(f"text={title}").first
                if title_loc.count() == 0:
                    continue
                container = title_loc.locator("xpath=ancestor::section[1]")
                if container.count() == 0:
                    container = title_loc.locator("xpath=ancestor::div[1]")
                text = container.inner_text()
                lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
                order = ["1", "2", "3"]
                buf = []
                i = 0
                for idx, ln in enumerate(lines):
                    if i < 3 and ln.startswith(order[i]):
                        # Greedy parse for name + score in subsequent lines
                        name = None
                        score = None
                        # consume following lines until we find number
                        k = idx + 1
                        while k < len(lines) and (name is None or score is None):
                            t = lines[k]
                            # heuristic: first non-numeric-rich line after index is name
                            if name is None and not re.search(r"\d", t):
                                name = t
                            m = re.search(r"(\d{1,3}(?:\.\d)?)", t)
                            if m and score is None:
                                try:
                                    score = float(m.group(1))
                                except Exception:
                                    score = None
                            k += 1
                        if name and score is not None:
                            buf.append((name, score))
                            i += 1
                if buf:
                    out[key] = buf[:3]
            browser.close()
    except Exception as e:
        print(f"[error] live site scrape failed: {e}", file=sys.stderr)
        return {}
    return out

def load_last(path: str) -> Dict[str, List[Tuple[str, float]]]:
    try:
        with open(path, "r", encoding="utf-8") as f:
            raw = json.load(f)
        # normalize
        last = {k: [(t[0], float(t[1])) for t in v] for k, v in raw.items()}
        return last
    except Exception:
        return {}

def save_today(path: str, data: Dict[str, List[Tuple[str, float]]]) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

def maybe_commit(path: str) -> None:
    if os.getenv("COMMIT_CHANGES", "0") != "1":
        return
    try:
        subprocess.run(["git", "config", "user.email", "github-actions[bot]@users.noreply.github.com"], check=True)
        subprocess.run(["git", "config", "user.name", "github-actions[bot]"], check=True)
        subprocess.run(["git", "add", path], check=True)
        # commit only if there are changes
        res = subprocess.run(["git", "diff", "--cached", "--quiet"])
        if res.returncode != 0:
            subprocess.run(["git", "commit", "-m", "chore: update live_last.json"], check=True)
            subprocess.run(["git", "push"], check=True)
    except Exception as e:
        print(f"[warn] commit failed: {e}", file=sys.stderr)

def build_diff(today: List[Tuple[str, float]], yesterday: List[Tuple[str, float]]) -> List[str]:
    # returns list of suffix markers for each today row: ↑, ↓, ↔ and delta
    rank_y = {name: i for i, (name, _) in enumerate(yesterday, 1)}
    out = []
    for i, (name, s) in enumerate(today, 1):
        if name in rank_y:
            dy = rank_y[name] - i  # positive if moved up
            arrow = "↔" if dy == 0 else ("↑" if dy > 0 else "↓")
            # score delta
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

def build_message(live: Dict[str, List[Tuple[str, float]]], last: Dict[str, List[Tuple[str, float]]]) -> str:
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

def send_telegram(text: str) -> None:
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
    data = try_scrape_live_site()
    if not data:
        send_telegram("⚠️ تعذّر جلب الترتيب الحي من llm-stats.com اليوم. سأحاول غدًا.")
        sys.exit(1)

    last_path = os.path.join("data", "live_last.json")
    last = load_last(last_path)

    msg = build_message(data, last)
    send_telegram(msg)

    save_today(last_path, data)
    maybe_commit(last_path)
    print("Sent live summary and saved snapshot.")

if __name__ == "__main__":
    main()
