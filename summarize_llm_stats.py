
# summarize_llm_stats.py — v7-ar.1 (Arabic, with logging)
import os, re, sys, requests, traceback, json

RAW_README = "https://raw.githubusercontent.com/JonathanChavezTamales/llm-leaderboard/main/README.md"
EXCLUDE_REGEX = os.getenv("EXCLUDE_REGEX", r"(?i)\b(llama|phi|gemma|mixtral|yi)\b")

COL_ALIASES = {
    "name": ["name", "model", "model name"],
    "provider": ["provider", "company"],
    "humaneval": ["humaneval", "human eval", "aider polyglot", "code"],
    "aime2024": ["aime 2024", "aime-2024", "aime"],
    "gpqa": ["gpqa", "gpqa diamond", "knowledge"],
    "mmlu": ["mmlu"],
    "mmlupro": ["mmlu-pro", "mmlu pro"],
    "mmmu": ["mmmu", "multimodal"],
    "math": ["math", "gsm8k"],
}

PROVIDER_PATTERNS = [
    ("OpenAI", r"(?i)\b(gpt|o1|o3|o4)\b"),
    ("Anthropic", r"(?i)\b(claude)\b"),
    ("Google", r"(?i)\b(gemini|palm)\b"),
    ("xAI", r"(?i)\b(grok)\b"),
    ("Mistral", r"(?i)\b(mistral)\b"),
    ("DeepSeek", r"(?i)\b(deepseek)\b"),
    ("Alibaba/Qwen", r"(?i)\b(qwen)\b"),
    ("Kimi", r"(?i)\b(kimi)\b"),
    ("Cohere", r"(?i)\b(cohere|command)\b"),
    ("Perplexity", r"(?i)\b(perplexity|pplx|sonar)\b"),
    ("Other", r".*"),
]

CAT_AR = {
    "Coding": "البرمجة",
    "Math": "الرياضيات",
    "Knowledge": "المعرفة",
    "Multimodal": "متعدد الوسائط",
}
PROVIDER_AR = {
    "OpenAI": "أوبن أي آي",
    "Anthropic": "أنثروبيك",
    "Google": "قوقل",
    "xAI": "xAI",
    "Mistral": "ميسترال",
    "DeepSeek": "ديب سيك",
    "Alibaba/Qwen": "علي بابا / كُوين",
    "Kimi": "كيمي",
    "Cohere": "كوهير",
    "Perplexity": "بيربليكسيتي",
    "Other": "أخرى",
}

def _to_float(text):
    if text is None: return float("nan")
    if isinstance(text, (int, float)): return float(text)
    s = str(text).strip().replace("%","").replace(",","")
    m = re.search(r"([0-9]+(?:\.[0-9]+)?)", s)
    if not m: return float("nan")
    try: return float(m.group(1))
    except: return float("nan")

def _norm(x):
    if x != x: return x
    return x/100.0 if 1 < x <= 100 else x

def fetch_readme():
    print(f"[info] fetching README: {RAW_README}")
    r = requests.get(RAW_README, timeout=45)
    print(f"[info] status: {r.status_code}, bytes: {len(r.content)}")
    if r.status_code != 200:
        raise RuntimeError(f"README fetch failed: {r.status_code}")
    # dump for debugging
    os.makedirs("debug", exist_ok=True)
    with open("debug/README.md", "wb") as f:
        f.write(r.content)
    return r.text

def parse_table(md):
    lines = [ln.rstrip() for ln in md.splitlines()]
    tables = []
    i = 0
    while i < len(lines)-1:
        if lines[i].strip().startswith("|") and "|" in lines[i] and set(lines[i+1].replace(" ","")) >= set("|-:"):
            j = i; buf = []
            while j < len(lines) and lines[j].strip().startswith("|"):
                buf.append(lines[j]); j += 1
            tables.append(buf); i = j
        else:
            i += 1
    print(f"[info] found {len(tables)} markdown table(s)")
    def header_cols(s): return [c.strip().lower() for c in s.split("|") if c.strip()]
    chosen = None
    for idx, t in enumerate(tables):
        header = header_cols(t[0])
        if any(k in header for k in ["name","model"]) and any(any(a in header for a in arr) for arr in COL_ALIASES.values()):
            chosen = t; print(f"[info] using table #{idx} columns: {header}"); break
    if not chosen: return [], {}

    header = header_cols(chosen[0])
    col_idx = {}
    for key, aliases in COL_ALIASES.items():
        for a in aliases:
            if a in header:
                col_idx[key] = header.index(a); break
    print(f"[info] mapped columns: {col_idx}")
    rows = []
    for ln in chosen[2:]:
        if not ln.strip().startswith("|"): continue
        cols = [c.strip() for c in ln.split("|") if c.strip()]
        if len(cols) < 2: continue
        rows.append(cols)
    print(f"[info] parsed rows: {len(rows)}")
    # dump a sample row
    if rows: print(f"[info] sample row: {rows[0][:min(8, len(rows[0]))]}")
    return rows, col_idx

def infer_provider(name, provider_col):
    if provider_col and provider_col.strip(): return provider_col.strip()
    for label, pat in PROVIDER_PATTERNS:
        if re.search(pat, name): return label
    return "Other"

def build_models(rows, col_idx):
    models = []
    for cols in rows:
        name = cols[col_idx.get("name", 0)]
        if re.search(EXCLUDE_REGEX, name): continue
        prov = infer_provider(name, cols[col_idx.get("provider", -1)] if "provider" in col_idx else "")
        def g(key):
            if key not in col_idx: return float("nan")
            v = _to_float(cols[col_idx[key]]); return _norm(v)
        scores = {
            "Coding": max(g("humaneval"), g("math")),
            "Math": max(g("aime2024"), g("math")),
            "Knowledge": max(g("gpqa"), g("mmlupro"), g("mmlu")),
            "Multimodal": g("mmmu"),
        }
        models.append({"name": name, "provider": prov, "scores": scores})
    print(f"[info] models after filter: {len(models)}")
    return models

def group_by_provider(models):
    groups = {}
    for m in models: groups.setdefault(m["provider"], []).append(m)
    def avg(m):
        vals = [v for v in m["scores"].values() if v == v]
        return sum(vals)/len(vals) if vals else 0.0
    for prov in groups: groups[prov] = sorted(groups[prov], key=avg, reverse=True)
    return groups

CAT_AR = CAT_AR
PROVIDER_AR = PROVIDER_AR
def fmt_pct(x): return f"{round(x*100,1)}%" if x==x else "—"

def build_messages(groups):
    order = ["OpenAI","Anthropic","Google","xAI","Mistral","DeepSeek","Alibaba/Qwen","Kimi","Cohere","Perplexity","Other"]
    parts = []; header = "📊 ملخّص النماذج — تقرير يومي\n"; curr = header
    for prov in order:
        if prov not in groups: continue
        prov_name = PROVIDER_AR.get(prov, prov)
        block = [f"— {prov_name}:"]
        for m in groups[prov]:
            s = m["scores"]
            line = (f"  • {m['name']}: "
                    f"{CAT_AR['Coding']} {fmt_pct(s['Coding'])}، "
                    f"{CAT_AR['Math']} {fmt_pct(s['Math'])}، "
                    f"{CAT_AR['Knowledge']} {fmt_pct(s['Knowledge'])}، "
                    f"{CAT_AR['Multimodal']} {fmt_pct(s['Multimodal'])}")
            block.append(line)
        block_text = "\n".join(block) + "\n\n"
        if len(curr) + len(block_text) > 3800:
            parts.append(curr.rstrip()); curr = header + block_text
        else:
            curr += block_text
    parts.append(curr.rstrip()); parts[-1] += "\nالمصدر: llm-stats.com (البيانات من README)"
    return parts

def send_messages(msgs):
    token = os.getenv("TELEGRAM_BOT_TOKEN"); chat = os.getenv("TELEGRAM_CHAT_ID")
    if not token or not chat: print("Missing TELEGRAM_BOT_TOKEN or TELEGRAM_CHAT_ID.", file=sys.stderr); sys.exit(2)
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    for m in msgs:
        r = requests.post(url, json={"chat_id": chat, "text": m, "parse_mode": "Markdown"}, timeout=60)
        if r.status_code != 200:
            raise RuntimeError(f"Telegram send failed: {r.status_code} {r.text}")

def main():
    try:
        md = fetch_readme()
        rows, col_idx = parse_table(md)
        if not rows:
            # dump a short file to artifact even when parse fails
            os.makedirs("debug", exist_ok=True)
            with open("debug/README_head.txt", "w", encoding="utf-8") as f:
                f.write(md[:5000])
            raise SystemExit("No leaderboard table parsed from README.")
        models = build_models(rows, col_idx)
        groups = group_by_provider(models)
        msgs = build_messages(groups)
        send_messages(msgs)
        print(f"[ok] Sent {len(msgs)} Telegram messages. Providers: {list(groups.keys())}")
    except Exception as e:
        print("[error]", e)
        traceback.print_exc()
        # notify on Telegram briefly
        try:
            token = os.getenv("TELEGRAM_BOT_TOKEN"); chat = os.getenv("TELEGRAM_CHAT_ID")
            if token and chat:
                import requests
                text = f"⚠️ فشل التلخيص: {str(e)[:350]}"
                requests.post(f"https://api.telegram.org/bot{token}/sendMessage", json={"chat_id": chat, "text": text})
        except Exception:
            pass
        sys.exit(1)

if __name__ == "__main__":
    main()
