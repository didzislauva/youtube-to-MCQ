from youtube_transcript_api import YouTubeTranscriptApi
from urllib.parse import urlparse, parse_qs
from pathlib import Path
import os, json, re, textwrap, requests

def extract_video_id(url: str) -> str:
    q = urlparse(url)
    if q.hostname in ("www.youtube.com", "youtube.com", "m.youtube.com"):
        vids = parse_qs(q.query).get("v", [])
        if vids:
            return vids[0]
    if q.hostname == "youtu.be":
        return q.path.lstrip("/")
    raise ValueError(f"Nederīgs URL: {url}")

def get_transcript_new_api(url: str, preferred_langs=("lv","en")):
    vid = extract_video_id(url)
    api = YouTubeTranscriptApi()  # jaunajā interfeisā veido instanci
    tl = api.list(vid)            # NEVIS list_transcripts, bet list(...)
    # Mēģini manuālos, tad auto, tad jebkuru
    for lang in preferred_langs:
        try:
            t = tl.find_manually_created_transcript([lang])
            return t.fetch(), t.language_code, "manual"
        except Exception:
            pass
    for lang in preferred_langs:
        try:
            t = tl.find_generated_transcript([lang])
            return t.fetch(), t.language_code, "auto"
        except Exception:
            pass
    # Rezerves varianta paņemšana
    for t in tl:
        try:
            return t.fetch(), t.language_code, ("manual" if not t.is_generated else "auto")
        except Exception:
            continue
    return None, None, "not_found"

# Izsaukums
url = "https://www.youtube.com/watch?v=AFXLZ7FEJc4"
segments, lang, source = get_transcript_new_api(url, preferred_langs=("lv","en"))
print(lang, source, 0 if segments is None else len(segments))

def segments_to_plain_text_objects(segments, join_threshold=0.8):
    out, buf, last_end = [], [], None
    for s in segments:
        start = s.start
        end = s.start + (s.duration or 0)
        text = (s.text or "").replace("\n", " ").strip()
        if not text:
            continue
        if last_end is not None and (start - last_end) <= join_threshold:
            buf.append(text)
        else:
            if buf:
                out.append(" ".join(buf))
            buf = [text]
        last_end = end
    if buf:
        out.append(" ".join(buf))
    return "\n\n".join(out)

plain = segments_to_plain_text_objects(segments, join_threshold=0.8)
print(plain)



API_KEY = ":) :) :)"

MODEL = "sonar"
TARGET_LANG = "lv"
MAX_TOKENS = 900         # tighter to reduce verbosity
TEMPERATURE = 0.3        # slightly lower for format adherence


# Simple calculation
plain_length = len(plain)
TOTAL_QUESTIONS = 30

# Aim for 8-12 chunks (sweet spot for variety vs API calls)
target_chunks = min(12, max(8, TOTAL_QUESTIONS // 3))
MAX_CHARS_PER_CHUNK = max(1000, plain_length // target_chunks)
PER_CHUNK = max(1, (TOTAL_QUESTIONS + target_chunks - 1) // target_chunks)  # ceiling division

print(f"Text: {plain_length:,} chars → {target_chunks} chunks of ~{MAX_CHARS_PER_CHUNK} chars")
print(f"Strategy: {PER_CHUNK} questions per chunk → up to {target_chunks * PER_CHUNK} total")



def split_into_chunks(text: str, max_chars: int = 8000, target_chunks=None):
    # If we have a target chunk count, try to hit it
    if target_chunks:
        actual_chunk_size = len(text) // target_chunks
        max_chars = max(1000, actual_chunk_size)  # minimum 1000 chars
    
    paras = [p.strip() for p in re.split(r"\n\s*\n", text) if p.strip()]
    chunks, buf, cur = [], [], 0
    
    for p in paras:
        if cur + len(p) + 2 <= max_chars:
            buf.append(p); cur += len(p) + 2
        else:
            if buf: chunks.append("\n\n".join(buf))
            buf = [p]; cur = len(p) + 2
            
            # If this paragraph alone exceeds max_chars, split it further
            if cur > max_chars:
                # Split long paragraphs by sentences or character limits
                sentences = re.split(r'[.!?]+', p)
                temp_chunk = ""
                for sent in sentences:
                    if len(temp_chunk) + len(sent) < max_chars:
                        temp_chunk += sent + ". "
                    else:
                        if temp_chunk.strip():
                            chunks.append(temp_chunk.strip())
                        temp_chunk = sent + ". "
                if temp_chunk.strip():
                    buf = [temp_chunk.strip()]
                    cur = len(temp_chunk)
                else:
                    buf = []; cur = 0
    
    if buf: chunks.append("\n\n".join(buf))
    return chunks

chunks = split_into_chunks(plain, max_chars=MAX_CHARS_PER_CHUNK)
print(f"Chunks: {len(chunks)}, total chars: {sum(len(c) for c in chunks)}")

def call_pplx(model: str, messages, max_tokens=900, temperature=0.3, timeout=120):
    headers = {"Authorization": f"Bearer {API_KEY}", "Content-Type": "application/json"}
    payload = {"model": model, "messages": messages, "max_tokens": max_tokens, "temperature": temperature}
    r = requests.post("https://api.perplexity.ai/chat/completions",
                      headers=headers, data=json.dumps(payload), timeout=timeout)
    r.raise_for_status()
    data = r.json()
    return data["choices"][0]["message"]["content"], data

def build_mcq_prompt(chunk_text: str, lang="lv", n=3):
    system = {
        "role": "system",
        "content": (
            "Tu esi eksāmenu satura veidotājs. Izveido kvalitatīvus MCQ (viena pareizā atbilde) no dotā teksta. "
            "Neizdomā faktus. Atbildei jābūt TIKAI derīgam JSON masīvam."
        ),
    }
    user = {
        "role": "user",
        "content": textwrap.dedent(f"""
        Valoda: {lang}
        Jautājumu skaits: {n}

        Stingras prasības:
        - Atgriez TIKAI JSON masīvu (bez citiem simboliem, bez teksta ārpus JSON).
        - Izmanto dubultpēdiņas gan atslēgām, gan virkņu vērtībām.
        - Nav lieku komatu rindas beigās.
        - Nav komentāru vai papildlauku.
        - Ja pietrūkst informācijas, jautājumu neiekļauj.
        - Ja nevari 100% izpildīt formātu, atgriez tukšu masīvu [].

        Formāts:
        [
          {{
            "question": "....",
            "choices": {{"A":"...","B":"...","C":"...","D":"..."}},
            "correct": "A",
            "explanation": "Īss pamatojums no dotā teksta."
          }},
          ...
        ]

        Teksts:
        {chunk_text}
        """).strip()
    }
    return [system, user]

def parse_json_strict(s: str):
    s = s.strip()
    if not (s.startswith("[") and s.endswith("]")):
        raise ValueError("Not a JSON array")
    return json.loads(s)

def parse_json_repair(s: str):
    # Minimal plain-text repair (no fence handling)
    t = s.strip().replace("\r\n", "\n")

    # Remove trailing commas before ] or }
    t = re.sub(r",\s*([\]}])", r"\1", t)

    # Convert single-quoted keys/values to double quotes (heuristic)
    t = re.sub(r'(?P<pre>[\{\s,])\'(?P<key>[^\'\n\r\t]+)\'\s*:', r'\g<pre>"\g<key>":', t)
    t = re.sub(r':\s*\'(?P<val>[^\'\\\n\r]*)\'(?P<post>[\s,\}\]])', r': "\g<val>"\g<post>', t)

    # Isolate first array/object
    fa, la = t.find("["), t.rfind("]")
    fo, lo = t.find("{"), t.rfind("}")
    if fa != -1 and la != -1 and fa < la:
        t = t[fa:la+1]
    elif fo != -1 and lo != -1 and fo < lo:
        t = t[fo:lo+1]

    return json.loads(t)

def validate_mcq_list(mcq_list):
    ok = True; issues = []
    for i, q in enumerate(mcq_list, 1):
        if not isinstance(q, dict):
            ok=False; issues.append((i,"not dict")); continue
        if not {"question","choices","correct","explanation"}.issubset(q):
            ok=False; issues.append((i,"missing keys")); continue
        ch = q["choices"]
        if not isinstance(ch, dict) or set(ch.keys()) != {"A","B","C","D"}:
            ok=False; issues.append((i,"choices format")); continue
        if q["correct"] not in {"A","B","C","D"} or not ch.get(q["correct"], "").strip():
            ok=False; issues.append((i,"correct invalid/empty"))
        if not str(q["question"]).strip():
            ok=False; issues.append((i,"empty question"))
        if not str(q["explanation"]).strip():
            ok=False; issues.append((i,"empty explanation"))
    return ok, issues

def generate_mcq(chunks, lang="lv", model="sonar", per_chunk=3, total=30,
                 max_tokens=900, temperature=0.3, log_failed=True):
    out = []
    debug_dir = Path("debug_raw"); debug_dir.mkdir(exist_ok=True)

    for i, ch in enumerate(chunks):
        need = total - len(out)
        if need <= 0: break
        ask = min(per_chunk, need)

        msgs = build_mcq_prompt(ch, lang=lang, n=ask)
        content, meta = call_pplx(model, msgs, max_tokens=max_tokens, temperature=temperature)

        parsed = None
        try:
            parsed = parse_json_strict(content)
        except Exception:
            # try repair
            try:
                parsed = parse_json_repair(content)
            except Exception:
                if log_failed:
                    (debug_dir / f"chunk_{i}.txt").write_text(content, encoding="utf-8")
                print(f"Chunk {i} parse failed, saved raw.")
                continue

        if isinstance(parsed, dict):
            parsed = [parsed]
        if isinstance(parsed, list):
            out.extend(parsed)

    out = out[:total]
    ok, issues = validate_mcq_list(out)
    return out, ok, issues

mcq_list, ok, issues = generate_mcq(
    chunks, lang=TARGET_LANG, model=MODEL,
    per_chunk=PER_CHUNK, total=TOTAL_QUESTIONS,
    max_tokens=MAX_TOKENS, temperature=TEMPERATURE,
    log_failed=True
)

print("Valid:", ok, "issues:", issues[:5], "count:", len(mcq_list))
out_dir = Path("out_mcq"); out_dir.mkdir(parents=True, exist_ok=True)
(out_dir / f"mcq_{TARGET_LANG}_{TOTAL_QUESTIONS}.json").write_text(
    json.dumps(mcq_list, ensure_ascii=False, indent=2), encoding="utf-8"
)
print("Saved:", out_dir / f"mcq_{TARGET_LANG}_{TOTAL_QUESTIONS}.json")



