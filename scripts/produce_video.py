"""
DS24 Produce Video v9
Pipeline: Fish Audio TTS → Pexels Hintergrundbild → JSON2Video → Airtable
github-genai komplett entfernt (nanobanana_api_key ist kein Gemini-Key!)
Globaler try/except: jede unhandled Exception landet in Letzter_Fehler
"""

import sys, os, time, json, traceback

AT_TOKEN  = os.environ['AIRTABLE_TOKEN']
GH_TOKEN  = os.environ['GH_TOKEN']
FORCED_ID = os.environ.get('FORCED_RECORD_ID', '').strip()

BASE_ID   = 'apppfrE10FwXz9IMY'
TABLE_ID  = 'tblm1szgXQZc0mRle'   # endet auf kleines l, nicht I!
CFG_TABLE = 'tblHq1P7Z7bE7hUEj'
REPO      = 'DigiPartner73/ds24-links'

try:
    import requests
except Exception as e:
    print(f'IMPORT FEHLER: {e}'); sys.exit(1)

AT_H = {'Authorization': f'Bearer {AT_TOKEN}', 'Content-Type': 'application/json'}
GH_H = {'Authorization': f'token {GH_TOKEN}', 'Accept': 'application/vnd.github.v3+json'}

# ── Hilfsfunktionen ──────────────────────────────────────────────────────────

def get_config(key):
    r = requests.get(
        f'https://api.airtable.com/v0/{BASE_ID}/{CFG_TABLE}',
        headers=AT_H,
        params={'filterByFormula': f'{{Parameter}}="{key}"', 'maxRecords': 1},
        timeout=10
    ).json()
    recs = r.get('records', [])
    return recs[0]['fields'].get('Wert', '') if recs else ''

def at_patch(rec_id, fields):
    return requests.patch(
        f'https://api.airtable.com/v0/{BASE_ID}/{TABLE_ID}/{rec_id}',
        headers=AT_H, json={'fields': fields}, timeout=15
    ).json()

def fail(rec_id, status, msg):
    print(f'FEHLER [{status}]: {msg}')
    at_patch(rec_id, {'Status': status, 'Letzter_Fehler': msg[:500]})
    sys.exit(1)

def gh_upload(upload_base, filename, data, content_type):
    r = requests.post(
        f'{upload_base}?name={filename}',
        headers={'Authorization': f'token {GH_TOKEN}', 'Content-Type': content_type},
        data=data, timeout=180
    )
    if r.status_code not in (200, 201):
        raise Exception(f'{filename} Upload HTTP {r.status_code}: {r.text[:200]}')
    return r.json()['browser_download_url']

# ── Start ─────────────────────────────────────────────────────────────────────

print('=== DS24 Produce Video v9 | Fish Audio + Pexels + JSON2Video ===')

# Record laden
if FORCED_ID:
    r = requests.get(
        f'https://api.airtable.com/v0/{BASE_ID}/{TABLEID}/{FORCED_ID}',
        headers=AT_H, timeout=10
    ).json()
    records = [r] if r.get('id') else []
else:
        resp = requests.get(
        f'https://api.airtable.com/v0/{BASE_ID}/{TABLE_ID}',
        headers=AT_H,
        params={
            'filterByFormula': '{Status}="skript_fertig"',
            'sort[0][field]': 'Profit_Score',
            'sort[0][direction]': 'desc',
            'maxRecords': 1
        },
        timeout=15
    ).json()
    records = resp.get('records', [])

if not records:
    print('Nichts zu tun.'); sys.exit(0)

record   = records[0]
rec_id   = record['id']
fields   = record['fields']
name     = fields.get('Name', 'Produkt')
hook     = fields.get('Script_Hook', '')
volltext = fields.get('Script_Volltext', '')

print(f'Verarbeite: {rec_id} | {name[:60]}')
if not volltext:
    fail(rec_id, 'fehler_voice', 'Script_Volltext ist leer')

at_patch(rec_id, {'Status': 'video_processing'})

# GitHub Release erstellen (für Intermediate File Hosting: Voiceover + Bild)
safe = ''.join(c if c.isalnum() or c == '-' else '' for c in name[:28])
tag  = f'vid-{rec_id[:8]}-{int(time.time())}'
rel  = requests.post(
    f'https://api.github.com/repos/{REPO}/releases',
    headers=GH_H,
    json={'tag_name': tag, 'name': f'Assets: {safe}', 'body': rec_id,
          'draft': False, 'prerelease': False},
    timeout=30
)
if rel.status_code not in (200, 201):
    fail(rec_id, 'fehler_video', f'GitHub Release HTTP {rel.status_code}: {rel.text[:200]}')
upload_base = rel.json()['upload_url'].split('{')[0]

# ── Globaler Exception-Handler ab hier ───────────────────────────────────────
# Jede unhandled Exception landet jetzt als Letzter_Fehler in Airtable
try:

    # ── SCHRITT 1: Fish Audio TTS ─────────────────────────────────────────────
    print('[1/3] Fish Audio TTS...')
    t0 = time.time()

    FISH_KEY = get_config('fish_audio_api_key')
    if not FISH_KEY:
        fail(rec_id, 'fehler_voice', 'fish_audio_api_key fehlt in Airtable Config')

    # WICHTIG: model als HTTP-HEADER, nicht im Body! (Bug #73)
    tts = requests.post(
        'https://api.fish.audio/v1/tts',
        headers={
            'Authorization': f'Bearer {FISH_KEY}',
            'Content-Type': 'application/json',
            'model': 's2.1-pro-free'
        },
        json={'text': volltext[:4096], 'format': 'mp3', 'latency': 'normal'},
        timeout=120
    )
    if tts.status_code != 200:
        fail(rec_id, 'fehler_voice', f'Fish Audio HTTP {tts.status_code}: {tts.text[:300]}')
    audio_data = tts.content
    print(f'Fish Audio OK {time.time()-t0:.1f}s | {len(audio_data)//1024}KB')

    voiceover_url = gh_upload(upload_base, 'voiceover.mp3', audio_data, 'audio/mpeg')
    print(f'Voiceover URL: {voiceover_url[:80]}')

    # ── SCHRITT 2: Pexels Hintergrundbild (portrait 9:16) ─────────────────────
    print('[2/3] Pexels Hintergrundbild...')
    t0 = time.time()

    PEXELS_KEY = get_config('pexels_api_key')
    if not PEXELS_KEY:
        fail(rec_id, 'fehler_video', 'pexels_api_key fehlt in Airtable Config')

    # WICHTIG: KEIN "Bearer"-Prefix bei Pexels! (Bug #3)
    pex_resp = requests.get(
        'https://api.pexels.com/v1/search',
        headers={'Authorization': PEXELS_KEY},
        params={'query': 'success money digital', 'orientation': 'portrait',
                'size': 'large', 'per_page': 3},
        timeout=15
    )
    if pex_resp.status_code != 200:
        fail(rec_id, 'fehler_video', f'Pexels HTTP {pex_resp.status_code}: {pex_resp.text[:200]}')

    photos = pex_resp.json().get('photos', [])
    if not photos:
        fail(rec_id, 'fehler_video', 'Pexels: keine Bilder gefunden')

    photo_url = photos[0].get('src', {}).get('portrait') or photos[0].get('src', {}).get('large2x')
    if not photo_url:
        fail(rec_id, 'fehler_video', 'Pexels: kein portrait-Format verfügbar')

    photo_dl = requests.get(photo_url, timeout=60)
    if photo_dl.status_code != 200:
        fail(rec_id, 'fehler_video', f'Pexels Download HTTP {photo_dl.status_code}')
    bg_bytes = photo_dl.content

    bg_url = gh_upload(upload_base, 'background.jpg', bg_bytes, 'image/jpeg')
    print(f'Pexels OK {time.time()-t0:.1f}s | {len(bg_bytes)//1024}KB')
    print(f'Background URL: {bg_url[:80]}')

    # ── SCHRITT 3: JSON2Video (Ken Burns + Text + Audio) ──────────────────────
    print('[3/3] JSON2Video Render...')
    t0 = time.time()

    J2V_KEY = get_config('json2video_api_key')
    if not J2V_KEY:
        fail(rec_id, 'fehler_video', 'json2video_api_key fehlt in Airtable Config')

    hook_text = hook[:160] if hook else name[:80]

    # REGELN (aus bekannten Bugs):
    # - volume KOMPLETT WEGLASSEN (Bug #1)
    # - Audio PER SCENE, nicht Movie-Ebene (Bug #18) → sonst schwarzer Tail
    # - duration: -1 auf Scene-Ebene (Bug #17/22)
    # - duration: -2 auf Bild-Element (Bug #22)
    # - font-size als String OHNE "px" (Bug #28)
    # - font-weight als numerischer String (Bug #27)
    j2v_payload = {
        "resolution": "9:16",
        "quality": "high",
        "scenes": [
            {
                "duration": -1,
                "elements": [
                    {
                        "type": "image",
                        "src": bg_url,
                        "duration": -2,
                        "zoom": "in",
                        "zoom-start": 1.0,
                        "zoom-end": 1.15
                    },
                    {
                        "type": "text",
                        "text": "Werbung*",
                        "x": "right",
                        "y": "top",
                        "style": {
                            "font-size": "34",
                            "font-weight": "700",
                            "color": "#FFD700",
                            "background": "#000000",
                            "opacity": 0.85,
                            "padding": "8 12"
                        }
                    },
                    {
                        "type": "text",
                        "text": hook_text,
                        "x": "center",
                        "y": "bottom",
                        "style": {
                            "font-size": "58",
                            "font-weight": "700",
                            "color": "#FFFFFF",
                            "background": "#000000",
                            "opacity": 0.75,
                            "padding": "16 20"
                        }
                    },
                    {
                        "type": "audio",
                        "src": voiceover_url
                        # KEIN volume-Feld! (Bug #1)
                    }
                ]
            }
        ]
    }

    j2v_create = requests.post(
        'https://api.json2video.com/v2/movies',
        headers={'x-api-key': J2V_KEY, 'Content-Type': 'application/json'},
        json=j2v_payload,
        timeout=30
    )
    if j2v_create.status_code not in (200, 201):
        fail(rec_id, 'fehler_video', f'JSON2Video Create HTTP {j2v_create.status_code}: {j2v_create.text[:300]}')

    j2v_data   = j2v_create.json()
    project_id = j2v_data.get('project')   # Bug #2: heißt "project", nicht "movie_id"!
    if not project_id:
        fail(rec_id, 'fehler_video', f'JSON2Video: kein project in Response: {j2v_data}')
    print(f'JSON2Video Job: {project_id}')

    # Pollen bis fertig (max 20 Min = 120 × 10s)
    video_url = None
    for attempt in range(120):
        time.sleep(10)
        poll = requests.get(
            f'https://api.json2video.com/v2/movies?project={project_id}',
            headers={'x-api-key': J2V_KEY},
            timeout=15
        ).json()
        movie  = poll.get('movie', {})
        status = movie.get('status', '')
        print(f'  [{attempt+1}/120] JSON2Video Status: {status}')
        if status == 'done':
            video_url = movie.get('url', '')
            break
        elif status in ('error', 'failed'):
            fail(rec_id, 'fehler_video', f'JSON2Video Render-Fehler: {json.dumps(movie)[:300]}')

    if not video_url:
        fail(rec_id, 'fehler_video', 'JSON2Video Timeout nach 20 Minuten')

    print(f'JSON2Video OK {time.time()-t0:.1f}s')
    print(f'Video URL: {video_url[:80]}')

    # ── SCHRITT 4: Airtable finalisieren ─────────────────────────────────────
    at_patch(rec_id, {
        'Status':               'video_fertig',
        'Video_URL':            video_url,
        'Voiceover_File_URL':   voiceover_url,
        'Video_Background_URL': bg_url,
        'Letzter_Fehler':       ''
    })
    print(f'=== FERTIG === RecID={rec_id} | Status=video_fertig')
    print(f'Video: {video_url}')

except SystemExit:
    raise  # fail() benutzt sys.exit() → weiterwerfen, nicht als Fehler behandeln
except Exception as e:
    tb = traceback.format_exc()
    fail(rec_id, 'fehler_video', f'{type(e).__name__}: {str(e)[:300]}\n{tb[-200:]}')
