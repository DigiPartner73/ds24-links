import requests, os, re, json, html as hlib

TOKEN    = os.environ['AIRTABLE_TOKEN']
BASE_ID  = 'apppfrE10FwXz9IMY'
TABLE_ID = 'tblm1szgXQZc0mRle'
WEBHOOK  = 'https://hook.eu1.make.com/n4g78ewffc2r2wh6lsjv5smxusdrwai8'


def fetch_records():
    records, offset = [], None
    formula = (
        "AND(LEN({Affiliate_Link_Raw})>0,"
        "OR({Status}='veroeffentlicht',{Status}='thumbnail_fertig',"
        "{Status}='video_fertig',{Status}='voiceover_fertig'))"
    )
    while True:
        params = {'filterByFormula': formula}
        if offset:
            params['offset'] = offset
        r = requests.get(
            f'https://api.airtable.com/v0/{BASE_ID}/{TABLE_ID}',
            headers={'Authorization': f'Bearer {TOKEN}'},
            params=params, timeout=30
        )
        data = r.json()
        if 'error' in data:
            print(f'Airtable error: {data}')
            break
        records.extend(data.get('records', []))
        offset = data.get('offset')
        if not offset:
            break
    return records


def make_page(pid, name, hook, volltext, cta_kw, preis, affiliate_url):
    h = lambda s: hlib.escape(str(s)) if s else ''

    headline = h(hook[:200]) if hook else h('Jetzt zugreifen: ' + name)

    body_html = ''
    if volltext:
        short = volltext[:400]
        last = max(short.rfind('.'), short.rfind('!'), short.rfind('?'))
        if last > 80:
            short = short[:last + 1]
        body_html = '<p class="body">' + h(short) + '</p>'

    cta_text   = '&#128073; Jetzt ' + h(cta_kw or 'Zugang') + ' sichern'
    preis_html = ('<div class="price-note">Einmaliger Preis: nur ' + h(preis)
                  + '&thinsp;&euro;</div>') if preis else ''

    pid_js  = json.dumps(pid)
    name_js = json.dumps(name)

    parts = [
        '<!DOCTYPE html>',
        '<html lang="de">',
        '<head>',
        '<meta charset="UTF-8">',
        '<meta name="viewport" content="width=device-width,initial-scale=1">',
        '<meta name="robots" content="noindex,nofollow">',
        '<title>' + h(name) + '</title>',
        '<link rel="icon" type="image/png" href="https://digipartner73.github.io/ds24-links/icon.png">',
        '<style>',
        '*{box-sizing:border-box;margin:0;padding:0}',
        'body{font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,sans-serif;background:#0d0d0d;color:#f0f0f0;min-height:100vh;display:flex;align-items:center;justify-content:center;padding:24px 16px}',
        '.card{max-width:480px;width:100%;background:#1a1a1a;border-radius:20px;padding:36px 24px 28px;box-shadow:0 12px 50px rgba(0,0,0,.7);text-align:center}',
        '.badge{display:inline-block;background:#ff6b00;color:#fff;font-size:11px;font-weight:800;padding:4px 16px;border-radius:20px;letter-spacing:1.5px;margin-bottom:22px;text-transform:uppercase}',
        'h1{font-size:clamp(19px,5vw,25px);font-weight:800;line-height:1.35;margin-bottom:18px;color:#fff}',
        '.body{font-size:14.5px;color:#bbb;line-height:1.7;margin-bottom:20px;text-align:left}',
        '.features{background:#111;border-radius:12px;padding:14px 18px;margin-bottom:24px;text-align:left}',
        '.features li{list-style:none;padding:5px 0;font-size:14px;color:#ddd}',
        '.features li::before{content:"\2713  ";color:#4caf50;font-weight:800}',
        '.price-note{font-size:13px;color:#888;margin-bottom:14px}',
        '.cta{display:block;background:linear-gradient(135deg,#ff6b00 0%,#ffaa00 100%);color:#fff;font-size:17px;font-weight:800;padding:18px 20px;border-radius:14px;text-decoration:none;box-shadow:0 6px 24px rgba(255,107,0,.45);margin-bottom:16px}',
        '.trust{font-size:12px;color:#555;display:flex;justify-content:center;gap:14px;flex-wrap:wrap;margin-bottom:20px}',
        '.legal{font-size:11px;color:#3a3a3a;line-height:1.7}',
        '.legal a{color:#4a4a4a;text-decoration:none}',
        '</style>',
        '</head>',
        '<body>',
        '<div class="card">',
        '  <span class="badge">&#9889; Exklusiv</span>',
        '  <h1>' + headline + '</h1>',
        '  ' + body_html,
        '  <ul class="features">',
        '    <li>Kein Vorwissen notwendig</li>',
        '    <li>Sofortiger Zugang &mdash; 100% digital</li>',
        '    <li>30 Tage Geld-zur&uuml;ck-Garantie</li>',
        '  </ul>',
        '  ' + preis_html,
        '  <a href="' + h(affiliate_url) + '" class="cta" id="cta-btn">' + cta_text + '</a>',
        '  <div class="trust">',
        '    <span>&#128274; Sichere Zahlung</span>',
        '    <span>&#11088; Top-bewertet</span>',
        '    <span>&#128230; Sofort-Zugang</span>',
        '  </div>',
        '  <p class="legal">',
        '    Werbung | Durch Klick auf den Button gelangst du zum Angebot unseres Affiliate-Partners.<br>',
        '    <a href="https://digipartner73.github.io/ds24-links/datenschutz.html">Datenschutz</a>',
        '    &middot;',
        '    <a href="https://digipartner73.github.io/ds24-links/impressum.html">Impressum</a>',
        '  </p>',
        '</div>',
        '<script>',
        'document.getElementById("cta-btn").addEventListener("click", function() {',
        '  try {',
        '    var src = new URLSearchParams(window.location.search).get("src") || "bridge";',
        '    fetch(' + json.dumps(WEBHOOK) + ', {',
        '      method: "POST",',
        '      headers: {"Content-Type": "application/json"},',
        '      body: JSON.stringify({product_id: ' + pid_js + ', source: src + "_cta", produktname: ' + name_js + ', timestamp: new Date().toISOString()}),',
        '      keepalive: true',
        '    });',
        '  } catch(e) {}',
        '});',
        '<\/script>',
        '</body>',
        '</html>',
    ]
    return '\n'.join(parts)


os.makedirs('p', exist_ok=True)
records = fetch_records()
index, count = {}, 0

for rec in records:
    f    = rec['fields']
    link = f.get('Affiliate_Link_UTM') or f.get('Affiliate_Link_Raw', '')
    if not link:
        continue
    m = re.search(r'/redir/(\d+)/', link)
    if not m:
        continue
    pid      = m.group(1)
    name     = f.get('Produktname', 'Kurs')
    hook     = f.get('Optimierter_Hook') or f.get('Script_Hook_A', '') or ''
    volltext = f.get('Script_Volltext_A', '') or ''
    cta      = f.get('CTA_Keyword', '') or ''
    preis    = f.get('Preis', '') or ''

    page = make_page(pid, name, hook, volltext, cta, preis, link)
    with open(f'p/{pid}.html', 'w', encoding='utf-8') as fh:
        fh.write(page)
    index[pid] = {'name': name, 'status': f.get('Status', ''), 'url': f'p/{pid}.html'}
    count += 1
    print(f'  ok  p/{pid}.html  --  {name}')

with open('p/index.json', 'w', encoding='utf-8') as fh:
    json.dump(index, fh, ensure_ascii=False, indent=2)

print(f'\nGenerated {count} bridge pages.')
