# summarize_llm_stats.py
# Fetches LLM benchmark data backing https://llm-stats.com from its public GitHub dataset
# and sends a concise Telegram summary grouped by Coding / Math / Reasoning.
#
# Runs daily on GitHub Actions (06:00 UTC). Configure TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID
# in your repo secrets.
import os
import sys
import time
import json
import re
from typing import Dict, Any, List, Tuple
import requests

GITHUB_MODELS_URL = "https://api.github.com/repos/JonathanChavezTamales/llm-leaderboard/contents/models"
USER_AGENT = "llm-stats-telegram-summary/1.0 (+https://llm-stats.com)"

# Categories and the keywords often used for each benchmark family
CATEGORIES = {
    "Coding": [
        "humaneval", "livecodebench", "mbpp", "apps", "leetcode", "codeforces", "codexhumaneval"
    ],
    "Math": [
        "aime", "aime-2024", "aime-2025", "math", "gsm8k", "amc", "olympiad", "olympiadbench"
    ],
    "Reasoning": [
        "gpqa", "gpqa-diamond", "mmlu", "mmlu-pro", "bbh", "mmmu", "ifeval", "arc-c", "hellaswag"
    ],
}

def _request_json(url: str, headers: Dict[str, str] = None, retry: int = 3, timeout: int = 30):
    h = {"Accept": "application/vnd.github+json", "User-Agent": USER_AGENT}
    if headers:
        h.update(headers)
    for i in range(retry):
        r = requests.get(url, headers=h, timeout=timeout)
        if r.status_code == 200:
            try:
                return r.json()
            except Exception:
                pass
        elif r.status_code in (429, 500, 502, 503, 504):
            time.sleep(2 ** i)
            continue
        else:
            # Non-retryable; break
            break
    raise RuntimeError(f"Failed to GET {url} (status={getattr(r, 'status_code', '?')})")

def list_model_files() -> List[Dict[str, Any]]:
    items = _request_json(GITHUB_MODELS_URL)
    files = [it for it in items if it.get("type") == "file" and it.get("name", "").endswith(".json")]
    # Some repos might organize subfolders; include them as well
    dirs = [it for it in items if it.get("type") == "dir"]
    for d in dirs:
        try:
            subitems = _request_json(d.get("url"))
            files.extend([it for it in subitems if it.get("type") == "file" and it.get("name", "").endswith(".json")])
        except Exception:
            pass
    return files

NUM_RE = re.compile(r"([0-9]+(?:\.[0-9]+)?)")

def _to_float(x) -> float:
    if x is None:
        return float("nan")
    if isinstance(x, (int, float)):
        return float(x)
    if isinstance(x, str):
        m = NUM_RE.search(x.replace("%", ""))
        if not m:
            return float("nan")
        return float(m.group(1))
    return float("nan")

def _maybe_percent_to_unit(val: float) -> float:
    # Normalize 0-100 to 0-1 if needed
    if val > 1.0 and val <= 100.0:
        return val / 100.0
    return val

def _flatten_scores(obj: Any, path: str = "") -> Dict[str, float]:
    """Traverse dicts/lists and pick numeric leaf values keyed by a dotted path."""
    out = {}
    if isinstance(obj, dict):
        for k, v in obj.items():
            key = f"{path}.{k}" if path else str(k)
            out.update(_flatten_scores(v, key))
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            out.update(_flatten_scores(v, f"{path}[{i}]"))
    else:
        val = _to_float(obj)
        if val == val:  # not NaN
            out[path] = _maybe_percent_to_unit(val)
    return out

def extract_model_scores(model_json: Dict[str, Any]) -> Dict[str, float]:
    # Common containers to look into
    containers = []
    for k in ("benchmarks", "evals", "scores", "results", "metrics"):
        if k in model_json and isinstance(model_json[k], (dict, list)):
            containers.append(model_json[k])
    if not containers:
        # Try full document as last resort
        containers.append(model_json)

    flattened = {}
    for c in containers:
        flattened.update(_flatten_scores(c))

    # Build a simple mapping: short_key -> score
    scores = {}
    for full_key, v in flattened.items():
        # Shorten key to last segment and normalize
        short = full_key.split(".")[-1].lower()
        short = short.replace("_acc", "").replace("_score", "").replace("_pct", "").replace("%", "")
        scores[short] = v
    return scores

def score_for_category(scores: Dict[str, float], keywords: List[str]) -> float:
    # Return the best (max) score found among any aliases
    best = float("nan")
    for kw in keywords:
        for k, v in scores.items():
            if kw in k:
                if v == v:
                    best = max(best, v) if best == best else v
    return best

def pick_tops(all_models: List[Tuple[str, Dict[str, float]]], top_n: int = 5):
    tops = {}
    for cat, kws in CATEGORIES.items():
        bucket = []
        for name, scores in all_models:
            s = score_for_category(scores, kws)
            if s == s:
                bucket.append((name, s))
        # Unique models, sorted desc
        seen = set()
        unique = []
        for name, s in sorted(bucket, key=lambda x: x[1], reverse=True):
            if name not in seen:
                unique.append((name, s))
                seen.add(name)
        tops[cat] = unique[:top_n]
    return tops

def fmt_pct(x: float) -> str:
    return f"{round(x*100, 1)}%"

def build_message(tops: Dict[str, List[Tuple[str, float]]], model_count: int) -> str:
    lines = []
    lines.append("📊 **LLM Stats — Daily Summary**")
    lines.append(f"Models scanned: {model_count}")
    lines.append("")
    for cat in ("Coding", "Math", "Reasoning"):
        lines.append(f"— {cat}:")
        if not tops.get(cat):
            lines.append("  • لا توجد بيانات")
            continue
        for i, (name, s) in enumerate(tops[cat], 1):
            lines.append(f"  {i}. {name}: {fmt_pct(s)}")
        lines.append("")
    lines.append("Source: llm-stats.com • Data repo: github.com/JonathanChavezTamales/llm-leaderboard")
    return "\n".join(lines)

def send_telegram(message: str) -> None:
    token = os.getenv("TELEGRAM_BOT_TOKEN")
    chat_id = os.getenv("TELEGRAM_CHAT_ID")
    if not token or not chat_id:
        print("Missing TELEGRAM_BOT_TOKEN or TELEGRAM_CHAT_ID env vars.", file=sys.stderr)
        sys.exit(2)
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    payload = {"chat_id": chat_id, "text": message, "parse_mode": "Markdown"}
    r = requests.post(url, json=payload, timeout=30)
    if r.status_code != 200:
        raise RuntimeError(f"Telegram send failed: {r.status_code} {r.text}")

def main():
    try:
        files = list_model_files()
    except Exception as e:
        print(f"[error] Could not list model files: {e}", file=sys.stderr)
        sys.exit(1)

    all_models: List[Tuple[str, Dict[str, float]]] = []
    for it in files:
        try:
            j = _request_json(it.get("download_url"))
            name = j.get("name") or j.get("id") or it.get("name", "").replace(".json", "")
            scores = extract_model_scores(j)
            all_models.append((name, scores))
        except Exception as e:
            # Skip bad files but continue
            print(f"[warn] Failed to parse {it.get('name')}: {e}", file=sys.stderr)
            continue

    tops = pick_tops(all_models, top_n=5)
    msg = build_message(tops, model_count=len(all_models))

    send_telegram(msg)
    print("Sent summary to Telegram.")

if __name__ == "__main__":
    main()
