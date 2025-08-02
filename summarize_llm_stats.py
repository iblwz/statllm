
# summarize_llm_stats.py — v7-ar.3
# Arabic full summary from llm-stats README with hardened parsing & sending.
import os, re, sys, requests, traceback

RAW_README = "https://raw.githubusercontent.com/JonathanChavezTamales/llm-leaderboard/main/README.md"
EXCLUDE_REGEX = os.getenv("EXCLUDE_REGEX", r"(?i)\b(llama|phi|gemma|mixtral|yi)\b")

COL_ALIASES = {
    "name": ["name", "model", "model name"],
    "provider": ["provider", "company"],
    "humaneval": ["humaneval", "human eval", "aider polyglot", "code"],
    "aime 2024": ["aime 2024", "aime-2024", "aime"],
    "gpqa": ["gpqa", "gpqa diamond", "knowledge"],
    "mmlu": ["mmlu"],
    "mmlu-pro": ["mmlu-pro", "mmlu pro"],
    "mmmu": ["mmmu", "multimodal"],
    "math": ["math", "gsm8k"],
}

PROVIDER_TOKENS = [
    ("OpenAI", ["gpt","o1","o2","o3","o4"]),
    ("Anthropic", ["claude"]),
    ("Google", ["gemini","palm"]),
    ("xAI", ["grok"]),
    ("Mistral", ["mistral"]),
    ("DeepSeek", ["deepseek"]),
    ("Alibaba/Qwen", ["qwen","qwen2","qwen2.5"]),
    ("Kimi", ["kimi"]),
    ("Cohere", ["cohere","command","aya"]),
    ("Perplexity", ["perplexity","pplx","sonar"]),
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

def _max_ignore_nan(vals):
    good = [v for v in vals if v == v]
    return max(good) if good else float('nan')

def fetch_readme():
    r = requests.get(RAW_README, timeout=45)
    if r.status_code != 200:
        raise RuntimeError(f"README fetch failed: {r.status_code}")
    # dump for diagnostics
    os.makedirs("debug", exist_ok=True)
    with open("debug/README.md","wb") as f: f.write(r.content)
    return r.text

def is_table_sep(line: str) -> bool:
    s = line.strip()
    if not s.startswith("|"): return False
    parts = [p.strip() for p in s.split("|")[1:-1]]
    if not parts: return False
    return all(re.fullmatch(r":?-{3,}:?", p) is not None for p in parts)

def parse_table(md):
    lines = [ln.rstrip() for ln in md.splitlines()]
    tables = []
    i = 0
    while i < len(lines)-1:
        if lines[i].strip().startswith("|") and i+1 < len(lines) and is_table_sep(lines[i+1]):
            j = i; buf = []
            while j < len(lines) and lines[j].strip().startswith("|"):
                buf.append(lines[j]); j += 1
            tables.append(buf); i = j
        else:
            i += 1

    def header_cols(s):
        return [c.strip().lower() for c in s.split("|") if c.strip()]

    chosen = None
    for t in tables:
        header = header_cols(t[0])
        if any(k in header for k in ["name","model"]) and any(any(a in header for a in arr) for arr in COL_ALIASES.values()):
            chosen = t; break
    if not chosen:
        return [], {}

    header = header_cols(chosen[0])
    # map columns using aliases
    col_idx = {}
    for key, aliases in COL_ALIASES.items():
        for a in aliases:
            if a in header:
                col_idx[key] = header.index(a); break

    rows = []
    for ln in chosen[2:]:
        if not ln.strip().startswith("|"): continue
        cols = [c.strip() for c in ln.split("|") if c.strip()]
        if len(cols) < 2: continue
        rows.append(cols)
    # log mapping
    with open("debug/parse_info.txt","w",encoding="utf-8") as f:
        f.write(f"header: {header}\n")
        f.write(f"mapped: {col_idx}\n")
        f.write(f"rows: {len(rows)}\n")
    return rows, col_idx

def infer_provider(name, provider_col):
    if provider_col and provider_col.strip():
        return provider_col.strip()
    low = name.lower()
    for label, tokens in PROVIDER_TOKENS:
        for t in tokens:
            if t in low:
                return label
    return "Other"

def build_models(rows, col_idx):
    models = []
    for cols in rows:
        name = cols[col_idx.get("name", 0)]
        if re.search(EXCLUDE_REGEX, name):
            continue
        provider_col = cols[col_idx.get("provider", -1)] if "provider" in col_idx else ""
        provider = infer_provider(name, provider_col)

        def g(colkey):
            if colkey not in col_idx: return float('nan')
            v = _norm(_to_float(cols[col_idx[colkey]]))
            return v

        scores = {
            "Coding": _max_ignore_nan([g("humaneval"), g("math")]),
            "Math": _max_ignore_nan([g("aime 2024"), g("math")]),
            "Knowledge": _max_ignore_nan([g("gpqa"), g("mmlu-pro"), g("mmlu")]),
            "Multimodal": g("mmmu"),
        }
        models.append({"name": name, "provider": provider, "scores": scores})
    return models

def group_by_provider(models):
    groups = {}
    for m in models:
        groups.setdefault(m["provider"], []).append(m)
    def avg(m):
        vals = [v for v in m["scores"].values() if v == v]
        return sum(vals)/len(vals) if vals else 0.0
    for prov in groups:
        groups[prov] = sorted(groups[prov], key=avg, reverse=True)
    return groups

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
        if len(curr) + len(block_text) > 3200:
            parts.append(curr.rstrip()); curr = header + block_text
        else:
            curr += block_text
    parts.append(curr.rstrip())
    parts[-1] += "\nالمصدر: llm-stats.com (البيانات من README)"
    return parts

def send_messages(msgs):
    token = os.getenv("TELEGRAM_BOT_TOKEN"); chat = os.getenv("TELEGRAM_CHAT_ID")
    if not token or not chat:
        print("Missing TELEGRAM_BOT_TOKEN or TELEGRAM_CHAT_ID.", file=sys.stderr); sys.exit(2)
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    for m in msgs:
        r = requests.post(url, json={"chat_id": chat, "text": m}, timeout=60)
        if r.status_code != 200:
            print(f"[warn] Telegram send failed: {r.status_code} {r.text[:200]}")
            # attempt line chunks
            if len(m) > 3200:
                chunks = []
                lines = m.split("\n")
                curr = ""
                for ln in lines:
                    if len(curr) + len(ln) + 1 > 3000:
                        chunks.append(curr); curr = ln
                    else:
                        curr = (curr + "\n" + ln) if curr else ln
                if curr: chunks.append(curr)
                for ch in chunks:
                    r2 = requests.post(url, json={"chat_id": chat, "text": ch}, timeout=60)
                    if r2.status_code != 200:
                        raise RuntimeError(f"Telegram send failed: {r2.status_code} {r2.text[:200]}")
            else:
                raise RuntimeError(f"Telegram send failed: {r.status_code} {r.text[:200]}")

def main():
    try:
        md = fetch_readme()
        rows, col_idx = parse_table(md)
        if not rows:
            raise SystemExit("لم أتعرف على جدول الـLeaderboard داخل README.")
        models = build_models(rows, col_idx)
        if not models:
            raise SystemExit("لم أجد موديلات مطابقة بعد الاستبعاد. راجع EXCLUDE_REGEX.")
        groups = group_by_provider(models)
        msgs = build_messages(groups)
        send_messages(msgs)
        print(f"[ok] Sent {len(msgs)} message(s). Providers: {list(groups.keys())}")
    except Exception as e:
        print("[error]", e)
        traceback.print_exc()
        # soft notify
        try:
            token = os.getenv("TELEGRAM_BOT_TOKEN"); chat = os.getenv("TELEGRAM_CHAT_ID")
            if token and chat:
                requests.post(f"https://api.telegram.org/bot{token}/sendMessage", json={"chat_id": chat, "text": f"⚠️ فشل الإرسال: {str(e)[:350]}"})
        except Exception:
            pass
        sys.exit(1)

if __name__ == "__main__":
    main()
