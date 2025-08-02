# summarize_llm_stats.py (v3)
# Fix: match benchmark keywords against the FULL dotted key path
# so keys like benchmarks.HumanEval.pass@1 are detected.
import os, sys, time, json, re
from typing import Dict, Any, List, Tuple
import requests

OWNER = "JonathanChavezTamales"
REPO = "llm-leaderboard"
BRANCH = "main"
TREE_URL = f"https://api.github.com/repos/{OWNER}/{REPO}/git/trees/{BRANCH}?recursive=1"
RAW_BASE = f"https://raw.githubusercontent.com/{OWNER}/{REPO}/{BRANCH}/"

USER_AGENT = "llm-stats-telegram-summary/3.0 (+https://llm-stats.com)"

CATEGORIES = {
    "Coding": ["humaneval", "livecodebench", "mbpp", "apps", "leetcode", "codeforces"],
    "Math": ["aime", "gsm8k", "amc", "olympiad"],
    "Reasoning": ["gpqa", "mmlu", "mmlu-pro", "bbh", "mmmu", "ifeval", "arc-c", "hellaswag"],
}

PREFERRED_METRICS = ["pass@1", "acc_norm", "acc", "accuracy", "score"]

def _headers(extra=None):
    h = {"Accept": "application/vnd.github+json", "User-Agent": USER_AGENT}
    tok = os.getenv("GITHUB_TOKEN") or os.getenv("GH_TOKEN")
    if tok:
        h["Authorization"] = f"Bearer {tok}"
    if extra:
        h.update(extra)
    return h

def _get(url: str, retry: int = 4, timeout: int = 30, headers: Dict[str, str] = None):
    for i in range(retry):
        r = requests.get(url, headers=(headers or _headers()), timeout=timeout)
        if r.status_code == 200:
            return r
        if r.status_code in (429, 500, 502, 503, 504) or (r.status_code == 403 and "rate limit" in r.text.lower()):
            time.sleep(2 ** i)
            continue
        if r.status_code == 403 and i < retry - 1:
            time.sleep(2 ** i + 1)
            continue
        raise RuntimeError(f"GET {url} failed: {r.status_code} {r.text[:200]}")
    raise RuntimeError(f"GET {url} failed after retries.")

def list_model_json_paths() -> List[str]:
    r = _get(TREE_URL)
    j = r.json()
    if "tree" not in j:
        raise RuntimeError(f"Unexpected tree response keys: {list(j.keys())}")
    paths = [it["path"] for it in j["tree"] if it.get("type") == "blob" and it.get("path","").startswith("models/") and it.get("path","").endswith(".json")]
    return paths

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
    if 1.0 < val <= 100.0:
        return val / 100.0
    return val

def _flatten_scores(obj: Any, path: str = "") -> Dict[str, float]:
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
        if val == val:
            out[path] = _maybe_percent_to_unit(val)
    return out

def extract_model_scores(model_json: Dict[str, Any]) -> Dict[str, float]:
    containers = []
    for k in ("benchmarks", "evals", "scores", "results", "metrics"):
        if k in model_json and isinstance(model_json[k], (dict, list)):
            containers.append(model_json[k])
    if not containers:
        containers.append(model_json)
    flattened = {}
    for c in containers:
        flattened.update(_flatten_scores(c))
    # Keep the FULL path as key (lowercased) so we don't lose benchmark names
    scores = {k.lower(): v for k, v in flattened.items()}
    return scores

def score_for_category(scores: Dict[str, float], keywords: List[str]) -> float:
    # Pick best value among keys that contain the benchmark keyword.
    # Prefer standard metric suffixes if multiple exist.
    candidates: List[Tuple[str, float]] = []
    for kw in keywords:
        for key, val in scores.items():
            if kw in key:
                candidates.append((key, val))
    if not candidates:
        return float("nan")
    # Prefer keys ending with common metric names
    def rank_key(k: str) -> int:
        for i, m in enumerate(PREFERRED_METRICS):
            if k.endswith(m):
                return i
        return len(PREFERRED_METRICS)
    best = sorted(candidates, key=lambda kv: (rank_key(kv[0]), -kv[1]))[0][1]
    return best

def pick_tops(all_models: List[Tuple[str, Dict[str, float]]], top_n: int = 5):
    tops = {}
    for cat, kws in CATEGORIES.items():
        bucket = []
        for name, scores in all_models:
            s = score_for_category(scores, kws)
            if s == s and 0.0 <= s <= 1.0:  # keep sane range
                bucket.append((name, s))
        seen, unique = set(), []
        for name, s in sorted(bucket, key=lambda x: x[1], reverse=True):
            if name not in seen:
                unique.append((name, s))
                seen.add(name)
        tops[cat] = unique[:top_n]
    return tops

def fmt_pct(x: float) -> str:
    return f"{round(x*100, 1)}%"

def build_message(tops: Dict[str, List[Tuple[str, float]]], model_count: int, scanned: int) -> str:
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
    lines.append(f"_scanned files: {scanned}_")
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
        paths = list_model_json_paths()
    except Exception as e:
        print(f"[error] Could not list model files: {e}", file=sys.stderr)
        sys.exit(1)

    all_models: List[Tuple[str, Dict[str, float]]] = []
    scanned = 0
    for relpath in paths:
        url = RAW_BASE + relpath
        try:
            r = _get(url, headers={"Accept": "application/json"})
            j = r.json()
            name = j.get("name") or j.get("id") or relpath.split("/")[-1].replace(".json", "")
            scores = extract_model_scores(j)
            all_models.append((name, scores))
            scanned += 1
        except Exception as e:
            print(f"[warn] Failed to parse {relpath}: {e}", file=sys.stderr)
            continue

    tops = pick_tops(all_models, top_n=5)
    msg = build_message(tops, model_count=len(all_models), scanned=scanned)

    send_telegram(msg)
    print(f"Sent summary to Telegram. files_scanned={scanned}, models={len(all_models)}")

if __name__ == "__main__":
    main()
