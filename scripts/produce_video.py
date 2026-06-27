"""
DS24 Produce Video v10
Pipeline: Fish Audio TTS â Nano Banana REST API â JSON2Video â Airtable
Einzige externe AbhÃ¤ngigkeit: requests
KEIN google-genai, KEIN Pexels, KEIN FFmpeg, KEIN Pillow
"""

import sys, os, time, json, traceback
from datetime import datetime, timezone, timedelta

AT_TOKEN  = os.environ['AIRTABLE_TOKEN']
GH_TOKEN  = os.environ['GH_TOKEN']
FORCED_ID = os.environ.get('FORCED_RECORD_ID', '').strip()

BASE_ID   = 'apppfrE10FwXz9IMY'
TABLE_ID  = 'tblm1szgXQZc0mRle'   # endet auf kleines l, nicht I!
CFG_TABLE = 'tblHq1P7Z7bE7hUEj'
REPO      = 'DigiPartner73/ds24-links'

NB_ENDPOINT  = 'https://nanobananavideo.com/api/v1/text-to-video.php'
CDN_FALLBACK = 'https://videos.pexels.com/video-files/7026684/7026684-sd_540_960_24fps.mp4'

try:
    import requests
except Exception as e:
    print(f'IMPORT FEHLER: {e}'); sys.exit(1)

print('=== DS24 Produce Video v10 | Fish Audio + Nano Banana REST + JSON2Video ===')
print(f'AT_TOKEN: {AT_TOKEN[:8]}... | GH_TOKEN: {GH_TOKEN[:8]}...')

AT_H = {'Authorization': f'Bearer {AT_TOKEN}', 'Content-Type': 'application/json'}
GH_H = {'Authorization': f'token {GH_TOKEN}', 'Accept': 'application/vnd.github.v3+json'}

# ââ Hilfsfunktionen ââââââââââââââââââââââââââââââââââââââââââââââââââââââââââ

def get_config(key):
    try:
        r = requests.get(
            f'https://api.airtable.com/v0/{BASE_ID}/{CFG_TABLE}',
            headers=AT_H,
            params={'filterByFormula': f'{{Parameter}}="{key}"', 'maxRecords': 1},
            timeout=10
        ).json()
        recs = r.get('records', [])
        return recs[0]['fields'].get('Wert', '') if recs else ''
    except Exception as e:
        print(f'Config-Fehler ({key}): {e}')
        return ''

def set_config(key, value):
    try:
        r = requests.get(
            f'https://api.airtable.com/v0/{BASE_ID}/{CFG_TABLE}',
            headers=AT_H,
            params={'filterByFormula': f'{{Parameter}}="{key}"', 'maxRecords': 1},
            timeout=10
        ).json()
        recs = r.get('records', [])
        if recs:
            requests.patch(
                f'https://api.airtable.com/v0/{BASE_ID}/{CFG_TABLE}/{recs[0]["id"]}',
                headers=AT_H, json={'fields': {'Wert': value}}, timeout=10
            )
        else:
            requests.post(
                f'https://api.airtable.com/v0/{BASE_ID}/{CFG_TABLE}',
                headers=AT_H,
                json={'records': [{'fields': {'Parameter': key, 'Wert': value}}]},
                timeout=10
            )
    except Exception as e:
        print(f'Config-Set-Fehler ({key}): {e}')

def at_patch(rec_id, fields):
    try:
        return requests.patch(
            f'https://api.airtable.com/v0/{BASE_ID}/{TABLE_ID}/{rec_id}',
            headers=AT_H, json={'fields': fields}, timeout=15
        ).json()
    except Exception as e:
        print(f'AT patch Fehler: {e}')
        return {}

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

# ââ Globaler Exception-Handler â umschlieÃt die gesamte Pipeline âââââââââââââ
try:

    # ââ Record laden ââââââââââââââââââââââââââââââââââââââââââââââââââââââââââ
    print('Lade Record...')
    if FORCED_ID:
        print(f'Forced Record: {FORCED_ID}')
        r = requests.get(
            f'https://api.airtable.com/v0/{BASE_ID}/{TABLE_ID}/{FORCED_ID}',
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
    print('Status â video_processing')

    # ââ GitHub Release erstellen ââââââââââââââââââââââââââââââââââââââââââââââ
    print('GitHub Release erstellen...')
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
    print(f'GitHub Release OK: {tag}')

    # ââ SCHRITT 1: Fish Audio TTS âââââââââââââââââââââââââââââââââââââââââââââ
    print('[1/3] Fish Audio TTS...')
    t0 = time.time()
    FISH_KEY = get_config('fish_audio_api_key')
    if not FISH_KEY:
        fail(rec_id, 'fehler_voice', 'fish_audio_api_key fehlt in Airtable Config')

    # KRITISCH: model als HTTP-HEADER, nicht im Body! (Bug #73)
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

    # ââ SCHRITT 2: Nano Banana REST API ââââââââââââââââââââââââââââââââââââââ
    print('[2/3] Nano Banana Video-Clip...')
    t0 = time.time()
    NB_KEY   = get_config('nanobanana_api_key')
    clip_url = CDN_FALLBACK
    nb_ok    = bool(NB_KEY)

    if nb_ok:
        # Rate-Limit vorprÃ¼fen
        rl_reset = get_config('nanobanana_rate_limit_reset')
        if rl_reset and rl_reset.strip():
            try:
                norm = rl_reset.strip().replace(' ', 'T')
                if not ('+' in norm or norm.endswith('Z')): norm += '+00:00'
                reset_dt  = datetime.fromisoformat(norm)
                remaining = (reset_dt - datetime.now(timezone.utc)).total_seconds()
                if remaining > -120:
                    print(f'NB Rate Limit aktiv (~{int(remaining+120)}s). CDN-Fallback.')
                    nb_ok = False
            except Exception as e:
                print(f'Rate-Limit-Parse Fehler: {e}. Fortfahren mit NB-Aufruf.')

    if nb_ok:
        prompt = (
            f"cinematic vertical lifestyle scene for '{name[:40]}', "
            "smooth camera motion, no text, no watermark, no face, "
            "9:16 portrait format, photorealistic, ultra-HD"
        )
        print(f'NB Prompt: {prompt[:80]}...')
        try:
            nb_resp = requests.post(
                NB_ENDPOINT,
                headers={'Authorization': f'Bearer {NB_KEY}', 'Content-Type': 'application/json'},
                json={
                    'prompt': prompt,
                    'video_model': 'seedance2',
                    'resolution': '720p',
                    'duration': 5,
                    'aspect_ratio': '9:16',
                    'motion_intensity': 'medium'
                },
                timeout=180
            )
            elapsed = int(time.time() - t0)
            print(f'NB HTTP {nb_resp.status_code} nach {elapsed}s')

            if nb_resp.status_code == 200:
                data = nb_resp.json()
                video_url_nb = data.get('video_url', '')
                if video_url_nb:
                    clip_url = video_url_nb
                    set_config('nanobanana_rate_limit_reset', '')
                    print(f'NB OK: {clip_url[:80]}')
                else:
                    print(f'NB 200 ohne video_url: {data}. CDN-Fallback.')
            elif nb_resp.status_code == 429:
                try: data = nb_resp.json()
                except: data = {}
                rl = data.get('rate_limit', {})
                reset_at    = rl.get('reset_at', '')
                retry_after = int(nb_resp.headers.get('Retry-After', rl.get('reset_in_seconds', 1800)))
                future      = datetime.now(timezone.utc) + timedelta(seconds=max(retry_after, 1800))
                set_config('nanobanana_rate_limit_reset',
                           reset_at or future.strftime('%Y-%m-%dT%H:%M:%S+00:00'))
                print(f'NB 429 Rate Limit. CDN-Fallback.')
            else:
                print(f'NB HTTP {nb_resp.status_code}: {nb_resp.text[:200]}. CDN-Fallback.')
        except requests.exceptions.Timeout:
            print(f'NB TIMEOUT nach {int(time.time()-t0)}s. CDN-Fallback.')
        except Exception as e:
            print(f'NB Fehler: {e}. CDN-Fallback.')

    print(f'Clip URL: {clip_url[:80]}')

    # ââ SCHRITT 3: JSON2Video Rendering ââââââââââââââââââââââââââââââââââââââ
    print('[3/3] JSON2Video Render...')
    t0 = time.time()
    J2V_KEY   = get_config('json2video_api_key')
    if not J2V_KEY:
        fail(rec_id, 'fehler_video', 'json2video_api_key fehlt in Airtable Config')

    hook_text = hook[:160] if hook else name[:80]

    # JSON2Video Bug-Regeln:
    # Bug #1:  volume KOMPLETT WEGLASSEN
    # Bug #2:  Job-ID heiÃt "project", nicht "movie_id"
    # Bug #17: duration: -1 auf Scene-Ebene (Auto-Dauer)
    # Bug #18: Audio PER SCENE, nicht Movie-Ebene
    # Bug #22: duration: -2 auf Video-Element (Loop)
    # Bug #74: style = Template-Referenz in JSON2Video! NIEMALS für CSS verwenden.
    # Styling-Properties direkt auf das Element (Top-Level): font-size, color, etc.
    j2v_payload = {
        "resolution": "9:16",
        "quality": "high",
        "scenes": [{
            "duration": -1,
            "elements": [
                {
                    "type": "video",
                    "src": clip_url,
                    "duration": -2,
                    "loop": -1
                },
                {
                    "type": "text",
                    "text": "Werbung*",
                    "x": "right",
                    "y": "top",
                    "font-size": "34",
                    "font-weight": "700",
                    "color": "#FFD700",
                    "background-color": "#000000",
                    "opacity": 0.85,
                    "padding": "8 12"
                },
                {
                    "type": "text",
                    "text": hook_text,
                    "x": "center",
                    "y": "bottom",
                    "font-size": "58",
                    "font-weight": "700",
                    "color": "#FFFFFF",
                    "background-color": "#000000",
                    "opacity": 0.75,
                    "padding": "16 20"
                },
                {
                    "type": "audio",
                    "src": voiceover_url
                    # KEIN volume-Feld! (Bug #1)
                }
            ]
        }]
    }

    j2v_create = requests.post(
        'https://api.json2video.com/v2/movies',
        headers={'x-api-key': J2V_KEY, 'Content-Type': 'application/json'},
        json=j2v_payload, timeout=30
    )
    if j2v_create.status_code not in (200, 201):
        fail(rec_id, 'fehler_video',
             f'JSON2Video Create HTTP {j2v_create.status_code}: {j2v_create.text[:300]}')

    j2v_data   = j2v_create.json()
    project_id = j2v_data.get('project')   # Bug #2: "project" nicht "movie_id"!
    if not project_id:
        fail(rec_id, 'fehler_video', f'JSON2Video: kein project in Response: {j2v_data}')
    print(f'JSON2Video Job: {project_id}')

    # Pollen bis fertig (max 20 Min = 120 Ã 10s)
    video_url = None
    for attempt in range(120):
        time.sleep(10)
        poll   = requests.get(
            f'https://api.json2video.com/v2/movies?project={project_id}',
            headers={'x-api-key': J2V_KEY}, timeout=15
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

    # ââ SCHRITT 4: Airtable finalisieren âââââââââââââââââââââââââââââââââââââ
    at_patch(rec_id, {
        'Status':               'video_fertig',
        'Video_URL':            video_url,
        'Voiceover_File_URL':   voiceover_url,
        'Video_Background_URL': clip_url,
        'Letzter_Fehler':       ''
    })
    print(f'=== FERTIG === RecID={rec_id} | Status=video_fertig')
    print(f'Video: {video_url}')

except SystemExit:
    raise
except Exception as e:
    tb = traceback.format_exc()
    msg = f'{type(e).__name__}: {str(e)[:300]}\n{tb[-300:]}'
    print(f'UNHANDLED EXCEPTION:\n{msg}')
    try:
        at_patch(rec_id, {'Status': 'fehler_video', 'Letzter_Fehler': msg[:500]})
    except Exception:
        pass
    sys.exit(1)
