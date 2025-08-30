from flask import Flask, render_template, request, jsonify, send_file, Response
import os
import json
import re
import textwrap
import requests
from pathlib import Path
from youtube_transcript_api import YouTubeTranscriptApi
from urllib.parse import urlparse, parse_qs
import zipfile
import io
from datetime import datetime
import time

app = Flask(__name__)

# Configuration
API_KEY = "your_perplexity_key:)"
MODEL = "sonar"
MAX_TOKENS = 900
TEMPERATURE = 0.3

progress_updates = []



def extract_video_id(url: str) -> str:
    """Extract video ID from YouTube URL"""
    q = urlparse(url)
    if q.hostname in ("www.youtube.com", "youtube.com", "m.youtube.com"):
        vids = parse_qs(q.query).get("v", [])
        if vids:
            return vids[0]
    if q.hostname == "youtu.be":
        return q.path.lstrip("/")
    raise ValueError(f"Invalid YouTube URL: {url}")

def get_transcript(url: str, preferred_langs=("lv", "en")):
    """Get transcript from YouTube video using the new API interface"""
    vid = extract_video_id(url)
    
    try:
        # Use the NEW interface - create instance and call list()
        api = YouTubeTranscriptApi()
        transcript_list = api.list(vid)  # NOT list_transcripts!
        
        # Try manual transcripts first for preferred languages
        for lang in preferred_langs:
            try:
                transcript = transcript_list.find_manually_created_transcript([lang])
                segments = transcript.fetch()
                return segments, transcript.language_code, "manual"
            except Exception:
                pass
        
        # Try auto-generated transcripts for preferred languages
        for lang in preferred_langs:
            try:
                transcript = transcript_list.find_generated_transcript([lang])
                segments = transcript.fetch()
                return segments, transcript.language_code, "auto"
            except Exception:
                pass
        
        # Get any available transcript as fallback
        for transcript in transcript_list:
            try:
                segments = transcript.fetch()
                source = "manual" if not transcript.is_generated else "auto"
                return segments, transcript.language_code, source
            except Exception:
                continue
                
    except Exception as e:
        error_msg = str(e).lower()
        if "disabled" in error_msg:
            return None, None, "disabled: Transcripts are disabled for this video"
        elif "no transcript" in error_msg:
            return None, None, "not_found: No transcripts available for this video"
        else:
            return None, None, f"error: {str(e)}"
    
    return None, None, "not_found: No accessible transcripts found"

def emit_progress(step, status, message, details=None):
    """Emit progress update"""
    global progress_updates
    update = {
        'step': step,
        'status': status,  # 'success', 'error', 'processing'
        'message': message,
        'details': details,
        'timestamp': datetime.now().isoformat()
    }
    progress_updates.append(update)
    return update

def segments_to_plain_text(segments, join_threshold=0.8):
    """Convert transcript segments to plain text (from working notebook)"""
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

def split_into_chunks(text: str, max_chars: int = 8000, target_chunks=None):
    """Split text into manageable chunks"""
    if target_chunks:
        actual_chunk_size = len(text) // target_chunks
        max_chars = max(1000, actual_chunk_size)
    
    paras = [p.strip() for p in re.split(r"\n\s*\n", text) if p.strip()]
    chunks, buf, cur = [], [], 0
    
    for p in paras:
        if cur + len(p) + 2 <= max_chars:
            buf.append(p)
            cur += len(p) + 2
        else:
            if buf:
                chunks.append("\n\n".join(buf))
            buf = [p]
            cur = len(p) + 2
            
            if cur > max_chars:
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
                    buf = []
                    cur = 0
    
    if buf:
        chunks.append("\n\n".join(buf))
    return chunks

def call_pplx(model: str, messages, max_tokens=900, temperature=0.3, timeout=120):
    """Call Perplexity API"""
    headers = {
        "Authorization": f"Bearer {API_KEY}",
        "Content-Type": "application/json"
    }
    payload = {
        "model": model,
        "messages": messages,
        "max_tokens": max_tokens,
        "temperature": temperature
    }
    r = requests.post(
        "https://api.perplexity.ai/chat/completions",
        headers=headers,
        data=json.dumps(payload),
        timeout=timeout
    )
    r.raise_for_status()
    data = r.json()
    return data["choices"][0]["message"]["content"], data

def build_mcq_prompt(chunk_text: str, lang="lv", n=3):
    """Build prompt for MCQ generation"""
    prompts = {
        "lv": {
            "system": (
                "Tu esi eksāmenu satura veidotājs. Izveido kvalitatīvus MCQ (viena pareizā atbilde) no dotā teksta. "
                "Neizdomā faktus. Atbildei jābūt TIKAI derīgam JSON masīvam."
            ),
            "user_template": """
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
"""
        },
        "en": {
            "system": (
                "You are an exam content creator. Create quality MCQs (one correct answer) from the given text. "
                "Don't invent facts. Response must be ONLY valid JSON array."
            ),
            "user_template": """
Language: {lang}
Number of questions: {n}

Strict requirements:
- Return ONLY JSON array (no other symbols, no text outside JSON).
- Use double quotes for both keys and string values.
- No trailing commas at end of lines.
- No comments or additional fields.
- If insufficient information, don't include question.
- If you can't 100% fulfill format, return empty array [].

Format:
[
  {{
    "question": "....",
    "choices": {{"A":"...","B":"...","C":"...","D":"..."}},
    "correct": "A",
    "explanation": "Brief justification from the given text."
  }},
  ...
]

Text:
{chunk_text}
"""
        }
    }
    
    prompt_set = prompts.get(lang, prompts["en"])
    system = {"role": "system", "content": prompt_set["system"]}
    user = {
        "role": "user", 
        "content": prompt_set["user_template"].format(
            lang=lang, n=n, chunk_text=chunk_text
        ).strip()
    }
    return [system, user]

def parse_json_repair(s: str):
    """Repair and parse JSON with common issues"""
    t = s.strip().replace("\r\n", "\n")
    
    # Remove trailing commas before ] or }
    t = re.sub(r",\s*([\]}])", r"\1", t)
    
    # Convert single-quoted keys/values to double quotes
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
    """Validate MCQ format"""
    ok = True
    issues = []
    for i, q in enumerate(mcq_list, 1):
        if not isinstance(q, dict):
            ok = False
            issues.append((i, "not dict"))
            continue
        if not {"question", "choices", "correct", "explanation"}.issubset(q):
            ok = False
            issues.append((i, "missing keys"))
            continue
        ch = q["choices"]
        if not isinstance(ch, dict) or set(ch.keys()) != {"A", "B", "C", "D"}:
            ok = False
            issues.append((i, "choices format"))
            continue
        if q["correct"] not in {"A", "B", "C", "D"} or not ch.get(q["correct"], "").strip():
            ok = False
            issues.append((i, "correct invalid/empty"))
        if not str(q["question"]).strip():
            ok = False
            issues.append((i, "empty question"))
        if not str(q["explanation"]).strip():
            ok = False
            issues.append((i, "empty explanation"))
    return ok, issues

def generate_mcq_with_progress(chunks, lang="lv", model="sonar", per_chunk=3, total=30,
                              max_tokens=900, temperature=0.3):
    """Generate MCQs from text chunks with progress tracking"""
    out = []
    
    emit_progress("generate_mcqs", "processing", f"Starting MCQ generation for {len(chunks)} chunks")
    
    for i, ch in enumerate(chunks):
        need = total - len(out)
        if need <= 0:
            break
        ask = min(per_chunk, need)
        
        emit_progress("generate_mcqs", "processing", 
                     f"Processing chunk {i+1}/{len(chunks)} - requesting {ask} questions")
        
        try:
            msgs = build_mcq_prompt(ch, lang=lang, n=ask)
            content, meta = call_pplx(model, msgs, max_tokens=max_tokens, temperature=temperature)
            
            parsed = None
            try:
                parsed = json.loads(content.strip())
            except Exception:
                try:
                    parsed = parse_json_repair(content)
                except Exception:
                    emit_progress("generate_mcqs", "error", 
                                 f"Failed to parse JSON for chunk {i+1}")
                    continue
            
            if isinstance(parsed, dict):
                parsed = [parsed]
            if isinstance(parsed, list):
                out.extend(parsed)
                emit_progress("generate_mcqs", "success", 
                             f"Generated {len(parsed)} questions from chunk {i+1}")
                
        except Exception as e:
            emit_progress("generate_mcqs", "error", 
                         f"Error processing chunk {i+1}: {str(e)}")
            continue
    
    out = out[:total]
    ok, issues = validate_mcq_list(out)
    
    if ok:
        emit_progress("validate", "success", f"Validation completed - {len(out)} valid questions")
    else:
        emit_progress("validate", "error", f"Validation issues found: {len(issues)} problems")
    
    return out, ok, issues

@app.route('/')
def index():
    """Main page"""
    return render_template('index.html')


@app.route('/progress')
def progress():
    """Server-sent events endpoint for progress updates"""
    def generate():
        global progress_updates
        sent_count = 0
        
        while True:
            if sent_count < len(progress_updates):
                for update in progress_updates[sent_count:]:
                    yield f"data: {json.dumps(update)}\n\n"
                sent_count = len(progress_updates)
            time.sleep(0.1)  # Check for updates every 100ms
            
    return Response(generate(), mimetype='text/event-stream',
                   headers={'Cache-Control': 'no-cache'})

@app.route('/process', methods=['POST'])
def process_video():
    """Process YouTube video and generate MCQs with progress tracking"""
    global progress_updates
    progress_updates = []  # Reset progress
    
    try:
        data = request.json
        url = data.get('url', '').strip()
        lang = data.get('language', 'en')
        num_questions = int(data.get('num_questions', 20))
        
        # Step 1: Initialize
        emit_progress("initialize", "success", "Initializing request", {
            'url': url,
            'questions': num_questions,
            'language': lang
        })
        
        if not url:
            emit_progress("initialize", "error", "YouTube URL is required")
            return jsonify({'error': 'YouTube URL is required'}), 400
        
        # Step 2: Extract video ID
        emit_progress("extract_id", "processing", "Extracting video ID from URL")
        try:
            video_id = extract_video_id(url)
            emit_progress("extract_id", "success", f"Video ID extracted: {video_id}")
        except Exception as e:
            emit_progress("extract_id", "error", f"Invalid YouTube URL: {str(e)}")
            return jsonify({'error': f'Invalid YouTube URL: {str(e)}'}), 400
        
        # Step 3: Get transcript
        emit_progress("transcript", "processing", "Fetching video transcript")
        segments, transcript_lang, source = get_transcript(url, preferred_langs=(lang, "en"))
        
        if segments is None:
            emit_progress("transcript", "error", f"Could not get transcript: {source}")
            return jsonify({'error': f'Could not get transcript: {source}'}), 400
        
        emit_progress("transcript", "success", f"Transcript fetched successfully", {
            'language': transcript_lang,
            'source': source,
            'segments': len(segments)
        })
        
        # Step 4: Convert to plain text
        emit_progress("convert_text", "processing", "Converting transcript to plain text")
        plain_text = segments_to_plain_text(segments)
        
        if len(plain_text) < 500:
            emit_progress("convert_text", "error", "Transcript too short to generate meaningful questions")
            return jsonify({'error': 'Transcript too short to generate meaningful questions'}), 400
        
        emit_progress("convert_text", "success", f"Text converted successfully ({len(plain_text):,} characters)")
        
        # Step 5: Split into chunks
        emit_progress("split_chunks", "processing", "Splitting text into processing chunks")
        target_chunks = min(12, max(8, num_questions // 3))
        max_chars_per_chunk = max(1000, len(plain_text) // target_chunks)
        per_chunk = max(1, (num_questions + target_chunks - 1) // target_chunks)
        
        chunks = split_into_chunks(plain_text, max_chars=max_chars_per_chunk)
        emit_progress("split_chunks", "success", f"Text split into {len(chunks)} chunks")
        
        # Step 6: Generate MCQs
        mcq_list, ok, issues = generate_mcq_with_progress(
            chunks, 
            lang=lang, 
            model=MODEL,
            per_chunk=per_chunk, 
            total=num_questions,
            max_tokens=MAX_TOKENS, 
            temperature=TEMPERATURE
        )
        
        # Step 7: Final completion
        emit_progress("complete", "success", f"Process completed successfully - {len(mcq_list)} questions generated")
        
        return jsonify({
            'success': True,
            'mcqs': mcq_list,
            'transcript_info': {
                'language': transcript_lang,
                'source': source,
                'length': len(segments),
                'text_length': len(plain_text)
            },
            'generation_info': {
                'chunks_used': len(chunks),
                'questions_generated': len(mcq_list),
                'validation_ok': ok,
                'issues': issues[:5]
            }
        })
        
    except Exception as e:
        emit_progress("error", "error", f"Unexpected error: {str(e)}")
        return jsonify({'error': str(e)}), 500

@app.route('/download/<format>')
def download_mcqs(format):
    """Download MCQs in specified format"""
    mcqs = request.args.get('data')
    if not mcqs:
        return jsonify({'error': 'No data provided'}), 400
    
    try:
        mcq_data = json.loads(mcqs)
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        
        if format == 'json':
            output = io.StringIO()
            json.dump(mcq_data, output, ensure_ascii=False, indent=2)
            output.seek(0)
            
            return send_file(
                io.BytesIO(output.getvalue().encode('utf-8')),
                mimetype='application/json',
                as_attachment=True,
                download_name=f'mcqs_{timestamp}.json'
            )
            
        elif format == 'txt':
            output = io.StringIO()
            for i, mcq in enumerate(mcq_data, 1):
                output.write(f"Question {i}: {mcq['question']}\n\n")
                for choice, text in mcq['choices'].items():
                    marker = "✓ " if choice == mcq['correct'] else "  "
                    output.write(f"{marker}{choice}) {text}\n")
                output.write(f"\nExplanation: {mcq['explanation']}\n")
                output.write("-" * 80 + "\n\n")
            
            output.seek(0)
            return send_file(
                io.BytesIO(output.getvalue().encode('utf-8')),
                mimetype='text/plain',
                as_attachment=True,
                download_name=f'mcqs_{timestamp}.txt'
            )
            
    except Exception as e:
        return jsonify({'error': str(e)}), 500

# HTML Template
HTML_TEMPLATE = '''<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>YouTube to MCQ Generator</title>
    <style>
        * {
            margin: 0;
            padding: 0;
            box-sizing: border-box;
        }
        
        body {
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            min-height: 100vh;
            padding: 20px;
        }
        
        .container {
            max-width: 1200px;
            margin: 0 auto;
            background: white;
            border-radius: 20px;
            box-shadow: 0 20px 40px rgba(0,0,0,0.1);
            overflow: hidden;
        }
        
        .header {
            background: linear-gradient(135deg, #ff6b6b, #4ecdc4);
            color: white;
            padding: 40px;
            text-align: center;
        }
        
        .header h1 {
            font-size: 2.5em;
            margin-bottom: 10px;
            font-weight: 700;
        }
        
        .header p {
            font-size: 1.2em;
            opacity: 0.9;
        }
        
        .form-section {
            padding: 40px;
        }
        
        .form-group {
            margin-bottom: 25px;
        }
        
        label {
            display: block;
            margin-bottom: 8px;
            font-weight: 600;
            color: #333;
        }
        
        input, select {
            width: 100%;
            padding: 15px;
            border: 2px solid #e1e5e9;
            border-radius: 10px;
            font-size: 16px;
            transition: all 0.3s ease;
        }
        
        input:focus, select:focus {
            outline: none;
            border-color: #4ecdc4;
            box-shadow: 0 0 0 3px rgba(78, 205, 196, 0.1);
        }
        
        .form-row {
            display: grid;
            grid-template-columns: 1fr 1fr;
            gap: 20px;
        }
        
        .generate-btn {
            background: linear-gradient(135deg, #ff6b6b, #4ecdc4);
            color: white;
            border: none;
            padding: 18px 40px;
            border-radius: 50px;
            font-size: 18px;
            font-weight: 600;
            cursor: pointer;
            transition: all 0.3s ease;
            width: 100%;
            margin-top: 20px;
        }
        
        .generate-btn:hover {
            transform: translateY(-2px);
            box-shadow: 0 10px 20px rgba(0,0,0,0.1);
        }
        
        .generate-btn:disabled {
            opacity: 0.6;
            cursor: not-allowed;
            transform: none;
        }
        
        .loading {
            display: none;
            text-align: center;
            padding: 40px;
        }
        
        .spinner {
            border: 4px solid #f3f3f3;
            border-top: 4px solid #4ecdc4;
            border-radius: 50%;
            width: 50px;
            height: 50px;
            animation: spin 1s linear infinite;
            margin: 0 auto 20px;
        }
        
        @keyframes spin {
            0% { transform: rotate(0deg); }
            100% { transform: rotate(360deg); }
        }
        
        .results {
            display: none;
            padding: 40px;
            border-top: 1px solid #e1e5e9;
        }
        
        .results-header {
            display: flex;
            justify-content: space-between;
            align-items: center;
            margin-bottom: 30px;
        }
        
        .download-buttons {
            display: flex;
            gap: 10px;
        }
        
        .download-btn {
            background: #28a745;
            color: white;
            border: none;
            padding: 10px 20px;
            border-radius: 8px;
            cursor: pointer;
            text-decoration: none;
            font-size: 14px;
        }
        
        .download-btn:hover {
            background: #218838;
        }
        
        .mcq-item {
            background: #f8f9fa;
            border-radius: 15px;
            padding: 25px;
            margin-bottom: 20px;
            border-left: 5px solid #4ecdc4;
        }
        
        .mcq-question {
            font-size: 1.1em;
            font-weight: 600;
            margin-bottom: 15px;
            color: #333;
        }
        
        .mcq-choices {
            margin-bottom: 15px;
        }
        
        .choice {
            padding: 10px 15px;
            margin: 8px 0;
            border-radius: 8px;
            transition: all 0.2s ease;
        }
        
        .choice.correct {
            background: #d4edda;
            border: 2px solid #28a745;
            font-weight: 600;
        }
        
        .choice.incorrect {
            background: #f8f9fa;
            border: 1px solid #dee2e6;
        }
        
        .mcq-explanation {
            background: #e3f2fd;
            padding: 15px;
            border-radius: 8px;
            font-style: italic;
            color: #1565c0;
        }
        
        .error {
            background: #f8d7da;
            color: #721c24;
            padding: 20px;
            border-radius: 10px;
            margin: 20px 0;
        }
        
        .info {
            background: #d1ecf1;
            color: #0c5460;
            padding: 15px;
            border-radius: 8px;
            margin-bottom: 20px;
            font-size: 14px;
        }
        .progress-section {
            display: none;
            padding: 40px;
            border-top: 1px solid #e1e5e9;
        }

        .progress-item {
            display: flex;
            align-items: center;
            padding: 12px 20px;
            margin: 8px 0;
            border-radius: 8px;
            border-left: 4px solid transparent;
            background: #f8f9fa;
            transition: all 0.3s ease;
        }

        .progress-item.success {
            background: #d4edda;
            border-left-color: #28a745;
        }

        .progress-item.error {
            background: #f8d7da;
            border-left-color: #dc3545;
        }

        .progress-item.processing {
            background: #d1ecf1;
            border-left-color: #17a2b8;
        }

        .progress-icon {
            margin-right: 12px;
            font-weight: bold;
            min-width: 20px;
        }

        .progress-icon.success::before { content: "✅"; }
        .progress-icon.error::before { content: "❌"; }
        .progress-icon.processing::before { content: "🔄"; }

        .progress-message {
            flex-grow: 1;
            font-weight: 500;
        }

        .progress-details {
            font-size: 0.9em;
            color: #666;
            margin-top: 4px;
        }
        
        @media (max-width: 768px) {
            .form-row {
                grid-template-columns: 1fr;
            }
            
            .results-header {
                flex-direction: column;
                gap: 15px;
            }
            
            .download-buttons {
                width: 100%;
                justify-content: center;
            }
        }
    </style>
</head>
<body>
    <div class="container">
        <div class="header">
            <h1>YouTube to MCQ Generator</h1>
            <p>Convert YouTube videos into multiple choice questions automatically</p>
        </div>
        
        <div class="form-section">
            <form id="mcq-form">
                <div class="form-group">
                    <label for="url">YouTube URL</label>
                    <input type="url" id="url" name="url" placeholder="https://www.youtube.com/watch?v=..." required>
                </div>
                
                <div class="form-row">
                    <div class="form-group">
                        <label for="language">Language</label>
                        <select id="language" name="language">
                            <option value="en">English</option>
                            <option value="lv">Latvian</option>
                            <option value="es">Spanish</option>
                            <option value="fr">French</option>
                            <option value="de">German</option>
                        </select>
                    </div>
                    
                    <div class="form-group">
                        <label for="num_questions">Number of Questions</label>
                        <select id="num_questions" name="num_questions">
                            <option value="10">10 Questions</option>
                            <option value="20" selected>20 Questions</option>
                            <option value="30">30 Questions</option>
                            <option value="40">40 Questions</option>
                            <option value="50">50 Questions</option>
                        </select>
                    </div>
                </div>
                
                <button type="submit" class="generate-btn" id="generate-btn">
                    Generate MCQs
                </button>
            </form>
        </div>

        <div class="progress-section" id="progress-section">
            <h2>Processing Progress</h2>
            <div id="progress-container"></div>
        </div>
        
        <div class="loading" id="loading">
            <div class="spinner"></div>
            <p>Processing video and generating questions...</p>
            <p style="font-size: 14px; color: #666; margin-top: 10px;">This may take 1-3 minutes depending on video length</p>
        </div>
        
        <div class="results" id="results">
            <div class="results-header">
                <h2>Generated Questions</h2>
                <div class="download-buttons">
                    <button class="download-btn" onclick="downloadMCQs('json')">Download JSON</button>
                    <button class="download-btn" onclick="downloadMCQs('txt')">Download TXT</button>
                </div>
            </div>
            <div id="mcq-container"></div>
        </div>
        
        <div class="error" id="error" style="display: none;"></div>
    </div>

   <script>
        let currentMCQs = [];
        let eventSource = null;

        document.getElementById('mcq-form').addEventListener('submit', async function(e) {
            e.preventDefault();
            
            const formData = new FormData(e.target);
            const data = {
                url: formData.get('url'),
                language: formData.get('language'),
                num_questions: formData.get('num_questions')
            };
            
            // Show progress section and hide others
            document.getElementById('progress-section').style.display = 'block';
            document.getElementById('results').style.display = 'none';
            document.getElementById('error').style.display = 'none';
            document.getElementById('generate-btn').disabled = true;
            document.getElementById('progress-container').innerHTML = '';
            
            // Start listening to progress updates
            startProgressUpdates();
            
            try {
                const response = await fetch('/process', {
                    method: 'POST',
                    headers: {
                        'Content-Type': 'application/json',
                    },
                    body: JSON.stringify(data)
                });
                
                const result = await response.json();
                
                if (result.success) {
                    currentMCQs = result.mcqs;
                    // Wait a bit for final progress updates
                    setTimeout(() => {
                        displayResults(result);
                        stopProgressUpdates();
                    }, 1000);
                } else {
                    showError(result.error || 'Unknown error occurred');
                    stopProgressUpdates();
                }
                
            } catch (error) {
                showError('Network error: ' + error.message);
                stopProgressUpdates();
            } finally {
                document.getElementById('generate-btn').disabled = false;
            }
        });

        function startProgressUpdates() {
            if (eventSource) {
                eventSource.close();
            }
            
            eventSource = new EventSource('/progress');
            
            eventSource.onmessage = function(event) {
                const progress = JSON.parse(event.data);
                addProgressItem(progress);
            };
            
            eventSource.onerror = function(error) {
                console.error('Progress stream error:', error);
            };
        }

        function stopProgressUpdates() {
            if (eventSource) {
                eventSource.close();
                eventSource = null;
            }
        }

        function addProgressItem(progress) {
            const container = document.getElementById('progress-container');
            const item = document.createElement('div');
            item.className = `progress-item ${progress.status}`;
            
            let detailsHtml = '';
            if (progress.details) {
                if (typeof progress.details === 'object') {
                    detailsHtml = '<div class="progress-details">';
                    for (const [key, value] of Object.entries(progress.details)) {
                        detailsHtml += `${key}: ${value}, `;
                    }
                    detailsHtml = detailsHtml.slice(0, -2) + '</div>';
                } else {
                    detailsHtml = `<div class="progress-details">${progress.details}</div>`;
                }
            }
            
            item.innerHTML = `
                <div class="progress-icon ${progress.status}"></div>
                <div>
                    <div class="progress-message">${progress.message}</div>
                    ${detailsHtml}
                </div>
            `;
            
            container.appendChild(item);
            container.scrollTop = container.scrollHeight; // Auto-scroll to bottom
        }

        // [Keep your existing displayResults, showError, and downloadMCQs functions unchanged]
        function displayResults(result) {
            const container = document.getElementById('mcq-container');
            const info = result.transcript_info;
            const genInfo = result.generation_info;
            
            let html = `
                <div class="info">
                    <strong>Video Info:</strong> ${info.language} transcript (${info.source}), 
                    ${info.length} segments, ${info.text_length.toLocaleString()} characters<br>
                    <strong>Generation:</strong> ${genInfo.questions_generated} questions from ${genInfo.chunks_used} chunks
                </div>
            `;
            
            result.mcqs.forEach((mcq, index) => {
                html += `
                    <div class="mcq-item">
                        <div class="mcq-question">${index + 1}. ${mcq.question}</div>
                        <div class="mcq-choices">
                            ${Object.entries(mcq.choices).map(([key, value]) => 
                                `<div class="choice ${key === mcq.correct ? 'correct' : 'incorrect'}">
                                    ${key}) ${value}
                                </div>`
                            ).join('')}
                        </div>
                        <div class="mcq-explanation">
                            <strong>Explanation:</strong> ${mcq.explanation}
                        </div>
                    </div>
                `;
            });
            
            container.innerHTML = html;
            document.getElementById('results').style.display = 'block';
        }

        function showError(message) {
            const errorDiv = document.getElementById('error');
            errorDiv.textContent = message;
            errorDiv.style.display = 'block';
        }

        function downloadMCQs(format) {
            if (currentMCQs.length === 0) {
                alert('No MCQs to download');
                return;
            }
            
            const data = encodeURIComponent(JSON.stringify(currentMCQs));
            window.location.href = `/download/${format}?data=${data}`;
        }
        </script>
</body>
</html>'''

# Create templates directory and save template
def create_template():
    templates_dir = Path("templates")
    templates_dir.mkdir(exist_ok=True)
    (templates_dir / "index.html").write_text(HTML_TEMPLATE, encoding="utf-8")

if __name__ == '__main__':
    create_template()
    
    # Create output directories
    Path("out_mcq").mkdir(exist_ok=True)
    Path("debug_raw").mkdir(exist_ok=True)
    
    print("Starting YouTube to MCQ Generator...")
    print("Open http://localhost:5000 in your browser")
    app.run(debug=True, host='0.0.0.0', port=5000)
