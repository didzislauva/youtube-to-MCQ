# YouTube to MCQ Generator

## Apraksts

Šis Python skripts automātiski ģenerē MCQ (Multiple Choice Questions) jautājumus no YouTube video transkriptiem, izmantojot Perplexity API. Tas ir ideāls rīks skolotājiem, studentiem un satura veidotājiem, kuri vēlas ātri izveidot kvalitatīvus eksāmenu jautājumus no video materiāliem.

## 🚀 Galvenās funkcijas

- **Automātiska transkriptu iegūšana** no YouTube video (manuāli vai automātiski ģenerēti subtitri)
- **Inteliģenta teksta segmentēšana** optimālai apstrādei
- **Daudzvalodu atbalsts** (latviešu, angļu, vācu, krievu u.c.)
- **Perplexity AI integrācija** kvalitatīvu MCQ ģenerēšanai
- **JSON validācija** un kļūdu labošana
- **Konfigurējams jautājumu skaits** (5-30+ jautājumi)
- **Strukturēta izvade** JSON 


## 📦 Instalācija

### Priekšnosacījumi

```bash
pip install youtube-transcript-api requests pathlib
```


### Perplexity API atslēga

1. Reģistrējieties [Perplexity](https://www.perplexity.ai) un iegūstiet API atslēgu
2. Iestatiet vides mainīgo:
```bash
export PPLX_API_KEY="your-api-key-here"
```


## 💡 Lietošana

### Pamata lietošana

```python
from youtube_transcript_api import YouTubeTranscriptApi
from urllib.parse import urlparse, parse_qs
import os, json, re, textwrap, requests
from pathlib import Path

# Iestatiet API atslēgu
API_KEY = "your-perplexity-api-key"

# YouTube video URL
url = "https://www.youtube.com/watch?v=VIDEO_ID"

# Iegūstiet transkriptu
segments, lang, source = get_transcript_new_api(url, preferred_langs=("lv","en"))

# Konvertējiet uz tekstu
plain = segments_to_plain_text_objects(segments, join_threshold=0.8)

# Ģenerējiet MCQ
mcq_list, ok, issues = generate_mcq(
    chunks, lang="lv", model="sonar",
    per_chunk=3, total=30,
    max_tokens=900, temperature=0.3
)
```


### Parametru konfigurācija

```python
# MCQ parametri
TARGET_LANG = "lv"        # Izvades valoda (lv, en, de, ru)
TOTAL_QUESTIONS = 30      # Kopējais jautājumu skaits
MODEL = "sonar"           # Perplexity modelis (sonar - lētākais)
MAX_TOKENS = 900          # Maksimālais atbildes garums
TEMPERATURE = 0.3         # Radošuma līmenis (0.1-1.0)

# Teksta apstrādes parametri
MAX_CHARS_PER_CHUNK = 8000  # Maksimālais simbolu skaits vienā gabalā
```


## 📁 Projekta struktūra

```
youtube-mcq-generator/
├── main.py                 # Galvenais skripts
├── out_mcq/               # MCQ izvades mape
│   ├── mcq_lv_30.json    # JSON formāts
└── README.md
```


## 🔧 Funkciju apraksts

### `extract_video_id(url)`

Izņem YouTube video ID no dažādiem URL formātiem.

### `get_transcript_new_api(url, preferred_langs)`

Iegūst transkriptu ar prioritātes secību valodām.

### `segments_to_plain_text_objects(segments)`

Konvertē transkriptu segmentus uz tīru tekstu.

### `split_into_chunks(text, max_chars)`

Sadala tekstu optimālos gabalos AI apstrādei.

### `generate_mcq(chunks, **params)`

Galvenā funkcija MCQ ģenerēšanai ar Perplexity API.

## 📊 Izvades formāts

### JSON struktūra

```json
[
  {
    "question": "Kas ir gumijas galvenā īpašība?",
    "choices": {
      "A": "Cietība",
      "B": "Elastība",
      "C": "Trauslums",
      "D": "Smagums"
    },
    "correct": "B",
    "explanation": "Gumija ir elastīgs materiāls, kas var izstiepties un atgriezties sākotnējā formā."
  }
]
```



## 💰 Izmaksu aprēķins

### Tipisks 40-minūšu video (~40,000 rakstzīmes):

- **Tokeni**: ~10,000 input + ~3,000 output tokeni
- **Izmaksas ar "sonar" modeli**: ~\$0.01-0.02 par 30 MCQ
- **\$5 kredīts pietiek**: ~250-500 video apstrādei


### Izmaksu optimizācija:

- Izmantojiet "sonar" modeli (lētākais)
- Izslēdziet web search funkciju
- Ierobežojiet `max_tokens` līdz 900


## ⚙️ Konfigurācijas ieteikumi

### Kvalitātei:

```python
MODEL = "sonar-reasoning"  # Labāka loģika
TEMPERATURE = 0.2          # Zemāka variācija
MAX_TOKENS = 1200         # Garāki skaidrojumi
```


### Ātrumam/izmaksām:

```python
MODEL = "sonar"           # Ātrākais un lētākais
TEMPERATURE = 0.4         # Sabalansēts
MAX_TOKENS = 800          # Īsāki skaidrojumi
```


## 🐛 Problemātiku risināšana

### Problēma: Tukšs MCQ saraksts

```python
# Pārbaudiet debug_raw/ mapi
# Samaziniet TEMPERATURE uz 0.2
# Palieliniet max_tokens uz 1000
```


### Problēma: JSON parse kļūdas

```python
# Pārbaudiet parse_json_repair() funkciju
# Uzlabojiet prompt instrukcijas
# Izmantojiet mazākus chunk
```


### Problēma: Par maz jautājumu

```python
# Samaziniet MAX_CHARS_PER_CHUNK
# Palieliniet PER_CHUNK skaitu
# Pievienojiet max_passes=3
```


## 📈 Uzlabojumi un paplašinājumi

### Plānotie uzlabojumi:

- [ ] GUI interfeiss
- [ ] Batch apstrāde vairākiem video
- [ ] Automātiska grūtības līmeņa noteikšana
- [ ] Eksports QTI formātā
- [ ] Integrācija ar populārām LMS sistēmām


### Pielāgošana:

- Mainiet prompt šablonus specifiskām tēmām
- Pievienojiet papildu validācijas noteikumus
- Implementējiet daudzlīmeņu grūtības sistēmu


## 📄 Licence

MIT License - brīvi izmantojams personīgiem un komerciāliem projektiem.

## 🤝 Ieguldījums

Ieguldījumi ir gaidīti! Lūdzu:

1. Fork projektu
2. Izveidojiet feature branch
3. Commit izmaiņas
4. Push uz branch
5. Izveidojiet Pull Request

## 📞 Atbalsts

- Issues: GitHub Issues tab
- Dokumentācija: Wiki sadaļa
- Piemēri: `/examples` mape

***

**Piezīme**: Šis rīks ir paredzēts izglītības nolūkiem. Lūdzu, ievērojiet YouTube lietošanas noteikumus un autortiesības.
<span style="display:none">[^1][^2][^3][^4][^5][^6][^7][^8]</span>

<div style="text-align: center">⁂</div>

[^1]: https://pypi.org/project/youtube-transcript-api/

[^2]: https://github.com/jdepoix/youtube-transcript-api/blob/master/youtube_transcript_api/_api.py

[^3]: https://stackoverflow.com/questions/76856230/how-to-extract-youtube-video-transcripts-using-youtube-api-on-python

[^4]: https://python.langchain.com/docs/integrations/document_loaders/youtube_transcript/

[^5]: https://www.timsanteford.com/posts/downloading-youtube-transcripts-in-python-a-practical-approach/

[^6]: https://www.youtube.com/watch?v=TwJX9AHdnQg

[^7]: https://python.useinstructor.com/blog/2024/07/11/youtube-transcripts/

[^8]: https://www.reddit.com/r/Integromat/comments/1ei2n13/youtube_transcript/
