import sys, os, time, base64, subprocess, textwrap, traceback

AT_TOKEN = os.environ['AIRTABLE_TOKEN']
GH_TOKEN = os.environ['GH_TOKEN']
FORCED_ID = os.environ.get('FORCED_RECORD_ID', '').strip()
BASE_ID  = 'apppfrE10FwXz9IMY'
TABLE_ID = 'tblm1szgXQZc0mRle'
CFG_TABLE = 'tblHq1P7Z7bE7hUEj'
REPO = 'DigiPartner73/ds24-links'

try:
    import requests
    from PIL import Image, ImageDraw, ImageFont
    import google.genai as genai
    import google.genai.types as genai_types
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

print('=== DS24 Produce Video v7 | OpenAI TTS + Nano Banana + FFmpeg ===')

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
sprache = fields.get('Sprache', 'DE')

print(f'Verarbeite: {rec_id} | {name[:60]} | {sprache}')
if not volltext:
    fail(rec_id, 'fehler_voice', 'Script_Volltext ist leer')

at_patch(rec_id, {'Status': 'video_processing'})

# SCHRITT 1: OpenAI TTS
print('[1/4] OpenAI TTS...')
t0 = time.time()
OPENAI_KEY = get_config('openai_api_key')
TTS_VOICE  = get_config('openai_tts_voice') or 'shimmer'
TTS_MODEL  = get_config('openai_tts_model') or 'tts-1'
if not OPENAI_KEY:
    fail(rec_id, 'fehler_voice', 'openai_api_key fehlt in Config')

tts = requests.post(
    'https://api.openai.com/v1/audio/speech',
    headers={'Authorization': f'Bearer {OPENAI_KEY}', 'Content-Type': 'application/json'},
    json={'model': TTS_MODEL, 'input': volltext[:4096], 'voice': TTS_VOICE},
    timeout=120
)
if tts.status_code != 200:
    fail(rec_id, 'fehler_voice', f'OpenAI TTS HTTP {tts.status_code}: {tts.text[:300]}')
with open('voiceover.mp3', 'wb') as f: f.write(tts.content)
print(f'TTS OK {time.time()-t0:.1f}s | {len(tts.content)//1024}KB')

# SCHRITT 2: Nano Banana Hintergrundbild
print('[2/4] Nano Banana Hintergrundbild...')
t0 = time.time()
NB_KEY = get_config('nanobanana_api_key')
if not NB_KEY:
    fail(rec_id, 'fehler_video', 'nanobanana_api_key fehlt')

try:
    nb_client = genai.Client(api_key=NB_KEY)
    img_prompt = (
        f"Professional dark luxury background for digital product '{name}'. "
        "Cinematic lighting, subtle golden accent, abstract premium feel. "
        "No text, no logos, no people, no faces. Vertical 9:16 format, photorealistic."
    )
    nb_resp = nb_client.models.generate_content(
        model='gemini-3.1-flash-image-preview',
        contents=img_prompt,
        config=genai_types.GenerateContentConfig(
            response_modalities=['image'],
            image_generation_config=genai_types.ImageGenerationConfig(
                aspect_ratio='9:16', number_of_images=1
            )
        )
    )
    img_bytes = None
    for part in nb_resp.candidates[0].content.parts:
        if part.inline_data:
            img_bytes = base64.b64decode(part.inline_data.data)
            break
    if not img_bytes:
        fail(rec_id, 'fehler_video', 'Nano Banana: keine Bild-Daten')
    with open('background.jpg', 'wb') as f: f.write(img_bytes)
    print(f'Nano Banana OK {time.time()-t0:.1f}s | {len(img_bytes)//1024}KB')
except Exception as e:
    fail(rec_id, 'fehler_video', f'Nano Banana: {traceback.format_exc()[-400:]}')

# SCHRITT 3: Pillow Text-Overlay
print('[3/4] Text-Overlay + FFmpeg...')
img = Image.open('background.jpg').convert('RGB').resize((1080, 1920), Image.LANCZOS)
W, H = 1080, 1920
draw = ImageDraw.Draw(img)
FONT = '/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf'
try:
    f_lbl = ImageFont.truetype(FONT, 38)
    f_hk  = ImageFont.truetype(FONT, 62)
except Exception:
    f_lbl = f_hk = ImageFont.load_default()

draw.rectangle([W-215, 22, W-12, 70], fill=(0,0,0))
draw.text((W-208, 28), 'Werbung*', font=f_lbl, fill='#FFD700')

if hook:
    lines = textwrap.wrap(hook[:160], width=22)
    lh = 78
    bh = len(lines)*lh+20
    sy = H-bh-70
    strip = Image.new('RGBA', (W, bh+16), (0,0,0,170))
    img_r = img.convert('RGBA')
    img_r.paste(strip, (0, sy-8), strip)
    img = img_r.convert('RGB')
    draw = ImageDraw.Draw(img)
    for i, ln in enumerate(lines):
        bb = draw.textbbox((0,0), ln, font=f_hk)
        tw = bb[2]-bb[0]
        x = (W-tw)//2
        y = sy+i*lh
        for dx,dy in [(-3,-3),(3,-3),(-3,3),(3,3)]:
            draw.text((x+dx,y+dy), ln, font=f_hk, fill='black')
        draw.text((x,y), ln, font=f_hk, fill='white')

img.save('background_overlay.jpg', quality=95)
print('Overlay OK')

r = subprocess.run([
    'ffmpeg', '-y', '-loop', '1', '-i', 'background_overlay.jpg', '-i', 'voiceover.mp3',
    '-vf', (
        'scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920,'
        "zoompan=z='if(eq(on,1),1.15,max(1.001,zoom-0.0008))'"
        ":x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':d=1:s=1080x1920:fps=25"
    ),
    '-c:v', 'libx264', '-preset', 'fast', '-crf', '22',
    '-c:a', 'aac', '-b:a', '128k', '-movflags', '+faststart', '-shortest', 'output.mp4'
], capture_output=True, text=True)
if r.returncode != 0:
    fail(rec_id, 'fehler_video', f'FFmpeg: {r.stderr[-400:]}')
print(f'FFmpeg OK | {os.path.getsize("output.mp4")/1024/1024:.1f}MB')

# SCHRITT 4: GitHub Release
print('[4/4] GitHub Release...')
safe = ''.join(c if c.isalnum() or c=='-' else '' for c in name[:28])
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
    bu = upload('background_overlay.jpg', 'image/jpeg', 'background.jpg')
except Exception as e:
    fail(rec_id, 'fehler_video', f'Upload: {e}')

at_patch(rec_id, {
    'Status': 'video_fertig', 'Video_URL': vu,
    'Voiceover_File_URL': au, 'Video_Background_URL': bu, 'Letzter_Fehler': ''
})
print(f'FERTIG! RecID={rec_id} Status=video_fertig')
print(f'Video: {vu}')
