import sys, os, time, subprocess, textwrap, traceback
from datetime import datetime, timezone, timedelta

AT_TOKEN = os.environ['AIRTABLE_TOKEN']
GH_TOKEN = os.environ['GH_TOKEN']
FORCED_ID = os.environ.get('FORCED_RECORD_ID', '').strip()
BASE_ID  = 'apppfrE10FwXz9IMY'
TABLE_ID = 'tblm1szgXQZc0mRle'
CFG_TABLE = 'tblHq1P7Z7bE7hUEj'
REPO = 'DigiPartner73/ds24-links'
NB_ENDPOINT = 'https://nanobananavideo.com/api/v1/text-to-video.php'
FALLBACK_CLIP = 'https://videos.pexels.com/video-files/7026684/7026684-sd_540_960_24fps.mp4'

try:
    import requests
    from PIL import Image, ImageDraw, ImageFont
except Exception as e:
    print(f'IMPORT FEHLER: {e}'); sys.exit(1)

AT_H = {'Authorization': f'Bearer {AT_TOKEN}', 'Content-Type': 'application/json'}
GH_H = {'Authorization': f'token {GH_TOKEN}', 'Accept': 'application/vnd.github.v3+json'}

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

print('=== DS24 Produce Video v7 | Fish Audio TTS + Nano Banana Video + FFmpeg ===')

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

record  = records[0]
rec_id  = record['id']
fields  = record['fields']
name    = fields.get('Name', 'Produkt')
hook    = fields.get('Script_Hook', '')
volltext = fields.get('Script_Volltext', '')

print(f'Verarbeite: {rec_id} | {name[:60]}')
if not volltext:
    fail(rec_id, 'fehler_voice', 'Script_Volltext ist leer')

at_patch(rec_id, {'Status': 'video_processing'})

# SCHRITT 1: Fish Audio TTS
print('[1/4] Fish Audio TTS...')
t0 = time.time()
FISH_KEY = get_config('fish_audio_api_key')
if not FISH_KEY:
    fail(rec_id, 'fehler_voice', 'fish_audio_api_key fehlt in Config')

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
    fail(rec_id, 'fehler_voice', f'Fish Audio TTS HTTP {tts.status_code}: {tts.text[:300]}')
with open('voiceover.mp3', 'wb') as f: f.write(tts.content)
print(f'TTS OK {time.time()-t0:.1f}s | {len(tts.content)//1024}KB')

# SCHRITT 2: Nano Banana Video-Hintergrund (oder Pexels-Fallback)
print('[2/4] Nano Banana Video-Hintergrund...')
t0 = time.time()
NB_KEY = get_config('nanobanana_api_key')
clip_url = FALLBACK_CLIP
nb_ok = bool(NB_KEY)

if nb_ok:
    # Rate-Limit vorprüfen
    rl_reset = get_config('nanobanana_rate_limit_reset')
    if rl_reset and rl_reset.strip():
        try:
            norm = rl_reset.strip().replace(' ', 'T')
            if not ('+' in norm or norm.endswith('Z')): norm += '+00:00'
            reset_dt = datetime.fromisoformat(norm)
            remaining = (reset_dt - datetime.now(timezone.utc)).total_seconds()
            if remaining > -120:
                print(f'NB Rate Limit aktiv (~{int(remaining+120)}s). Pexels-Fallback.')
                nb_ok = False
        except Exception as e:
            print(f'Rate-Limit-Parse Fehler: {e}. Pexels-Fallback.')
            nb_ok = False

if nb_ok:
    prompt = (
        f"cinematic vertical lifestyle scene for '{name[:40]}', "
        "smooth camera motion, no text, no watermark, no face, "
        "9:16 portrait format, photorealistic, ultra-HD"
    )
    print(f'NB Request: {prompt[:100]}...')
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

        if nb_resp.status_code == 429:
            try: data = nb_resp.json()
            except: data = {}
            rl = data.get('rate_limit', {})
            reset_at = rl.get('reset_at', '')
            retry_hdr = int(nb_resp.headers.get('Retry-After', rl.get('reset_in_seconds', 1800)))
            future = datetime.now(timezone.utc) + timedelta(seconds=max(retry_hdr, 1800))
            set_config('nanobanana_rate_limit_reset', reset_at or future.strftime('%Y-%m-%dT%H:%M:%S+00:00'))
            print('NB 429 Rate Limit → Pexels-Fallback.')
        elif nb_resp.status_code == 200:
            try: data = nb_resp.json()
            except: data = {}
            video_url = data.get('video_url', '')
            if video_url:
                clip_url = video_url
                set_config('nanobanana_rate_limit_reset', '')
                print(f'NB OK {elapsed}s: {clip_url[:80]}')
            else:
                print(f'NB 200 ohne video_url: {data}. Pexels-Fallback.')
        else:
            print(f'NB HTTP {nb_resp.status_code}: {nb_resp.text[:200]}. Pexels-Fallback.')
    except requests.exceptions.Timeout:
        print(f'NB TIMEOUT nach {int(time.time()-t0)}s. Pexels-Fallback.')
    except Exception as e:
        print(f'NB Fehler: {e}. Pexels-Fallback.')

# Pexels-Fallback
if clip_url == FALLBACK_CLIP:
    PEXELS_KEY = get_config('pexels_api_key')
    if PEXELS_KEY:
        try:
            r = requests.get('https://api.pexels.com/videos/search',
                headers={'Authorization': PEXELS_KEY},
                params={'query': 'cinematic lifestyle', 'orientation': 'portrait', 'size': 'large', 'per_page': 3},
                timeout=15)
            if r.status_code == 200:
                videos = r.json().get('videos', [])
                if videos:
                    files = sorted(videos[0].get('video_files', []), key=lambda f: f.get('height', 0), reverse=True)
                    if files:
                        clip_url = files[0]['link']
                        print(f'Pexels OK: {clip_url[:60]}')
        except Exception as e:
            print(f'Pexels Fehler: {e}')
    if clip_url == FALLBACK_CLIP:
        print('CDN Fallback Clip.')

print(f'Clip: {clip_url[:80]}')

# SCHRITT 3: Clip herunterladen + Overlay-Bild erstellen
print('[3/4] Clip-Download + Pillow Overlay...')
clip_data = requests.get(clip_url, timeout=60).content
with open('background.mp4', 'wb') as f: f.write(clip_data)
print(f'Clip: {len(clip_data)//1024}KB')

# Pillow: transparentes Overlay (1080x1920)
FONT = '/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf'
overlay = Image.new('RGBA', (1080, 1920), (0, 0, 0, 0))
draw = ImageDraw.Draw(overlay)
try:
    f_lbl = ImageFont.truetype(FONT, 38)
    f_hk  = ImageFont.truetype(FONT, 56)
except Exception:
    f_lbl = f_hk = ImageFont.load_default()

# "Werbung*" Badge oben rechts
draw.rectangle([855, 18, 1065, 70], fill=(0, 0, 0, 210))
draw.text((863, 24), 'Werbung*', font=f_lbl, fill='#FFD700')

# Hook-Text unten
if hook:
    lines = textwrap.wrap(hook[:180], width=24)[:4]
    lh = 70
    bh = len(lines) * lh + 30
    sy = 1920 - bh - 90
    draw.rectangle([10, sy - 15, 1070, 1920 - 55], fill=(0, 0, 0, 175))
    for i, ln in enumerate(lines):
        bb = draw.textbbox((0, 0), ln, font=f_hk)
        tw = bb[2] - bb[0]
        x = (1080 - tw) // 2
        y = sy + i * lh
        for dx, dy in [(-3, -3), (3, -3), (-3, 3), (3, 3)]:
            draw.text((x + dx, y + dy), ln, font=f_hk, fill='black')
        draw.text((x, y), ln, font=f_hk, fill='white')

overlay.save('overlay.png')

# SCHRITT 4: FFmpeg — Video + Audio + Overlay
print('[4/4] FFmpeg render...')
r = subprocess.run([
    'ffmpeg', '-y',
    '-stream_loop', '-1', '-i', 'background.mp4',
    '-i', 'voiceover.mp3',
    '-i', 'overlay.png',
    '-filter_complex',
    '[0:v]scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920[v];'
    '[v][2:v]overlay=0:0[out]',
    '-map', '[out]', '-map', '1:a',
    '-c:v', 'libx264', '-preset', 'fast', '-crf', '22',
    '-c:a', 'aac', '-b:a', '128k',
    '-movflags', '+faststart', '-shortest',
    'output.mp4'
], capture_output=True, text=True)
if r.returncode != 0:
    fail(rec_id, 'fehler_video', f'FFmpeg: {r.stderr[-500:]}')
print(f'FFmpeg OK | {os.path.getsize("output.mp4")/1024/1024:.1f}MB')

# GitHub Release
print('GitHub Release...')
safe = ''.join(c if c.isalnum() or c == '-' else '' for c in name[:28])
tag  = f'vid-{rec_id[:8]}-{int(time.time())}'
rel  = requests.post(
    f'https://api.github.com/repos/{REPO}/releases',
    headers=GH_H,
    json={'tag_name': tag, 'name': f'Video: {safe}', 'body': rec_id,
          'draft': False, 'prerelease': False},
    timeout=30
)
if rel.status_code not in (200, 201):
    fail(rec_id, 'fehler_video', f'Release HTTP {rel.status_code}: {rel.text[:200]}')
ub = rel.json()['upload_url'].split('{')[0]

def upload(path, ctype, aname):
    with open(path, 'rb') as f: data = f.read()
    r = requests.post(f'{ub}?name={aname}',
        headers={'Authorization': f'token {GH_TOKEN}', 'Content-Type': ctype},
        data=data, timeout=180)
    if r.status_code not in (200, 201):
        raise Exception(f'{aname} HTTP {r.status_code}')
    return r.json()['browser_download_url']

try:
    vu = upload('output.mp4', 'video/mp4', 'video.mp4')
    au = upload('voiceover.mp3', 'audio/mpeg', 'voiceover.mp3')
    bu = upload('overlay.png', 'image/png', 'overlay.png')
except Exception as e:
    fail(rec_id, 'fehler_video', f'Upload: {e}')

at_patch(rec_id, {
    'Status': 'video_fertig', 'Video_URL': vu,
    'Voiceover_File_URL': au, 'Video_Background_URL': bu, 'Letzter_Fehler': ''
})
print(f'FERTIG! RecID={rec_id} Status=video_fertig')
print(f'Video: {vu}')
