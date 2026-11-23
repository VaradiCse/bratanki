#!/usr/bin/env python3
"""v16: képek a kánonhoz a Wikimedia Commonsból.
  python3 -I fetch_img.py            minden hiányzó kép letöltése (img_queries.json alapján)
  python3 -I fetch_img.py slug ...   csak ezek (újrakeresés)
  python3 -I fetch_img.py --pick slug=N   a jelöltlista N. eleme legyen a kép
  python3 -I fetch_img.py --sheet t       kontaktlap egy körről (/tmp/kimg_sheet_t.png)
  python3 -I fetch_img.py --alts slug     a jelöltek kontaktlapja
Csak szabad licenc (PD, CC0, CC BY, CC BY-SA); személyiségi jogi korlátozással jelölt fájl kimarad.
A nyers letöltések a /tmp/kimg_raw mappába kerülnek (megbízhatatlan adat), a kész webp a tools/kanon/img-be."""
import html, io, json, os, re, sys, time, urllib.error, urllib.parse, urllib.request
from PIL import Image, ImageDraw, ImageFont

KD = os.path.dirname(os.path.abspath(__file__))
IMG = os.path.join(KD, 'img')
RAW = '/tmp/kimg_raw'
UA = 'BratankiBot/1.0 (personal language app)'
API = 'https://commons.wikimedia.org/w/api.php'
os.makedirs(IMG, exist_ok=True); os.makedirs(RAW, exist_ok=True)
MP, CP = os.path.join(IMG, 'meta.json'), os.path.join(KD, 'img_cand.json')
meta = json.load(io.open(MP, encoding='utf-8')) if os.path.exists(MP) else {}
cand = json.load(io.open(CP, encoding='utf-8')) if os.path.exists(CP) else {}
Q = json.load(io.open(os.path.join(KD, 'img_queries.json'), encoding='utf-8'))


def save(only=None):
    """only: csak ezt az azonosítót írjuk vissza a lemezen lévő állapotba (egy másik futás közben választhatott)."""
    m0 = json.load(io.open(MP, encoding='utf-8')) if os.path.exists(MP) else {}
    c0 = json.load(io.open(CP, encoding='utf-8')) if os.path.exists(CP) else {}
    keys = [only] if only else list(set(meta) | set(m0))
    for k in keys:
        if k in meta: m0[k] = meta[k]
        else: m0.pop(k, None)
        if k in cand: c0[k] = cand[k]
    meta.clear(); meta.update(m0); cand.clear(); cand.update(c0)
    io.open(MP, 'w', encoding='utf-8').write(json.dumps(meta, ensure_ascii=False, indent=1, sort_keys=True))
    io.open(CP, 'w', encoding='utf-8').write(json.dumps(cand, ensure_ascii=False, indent=1, sort_keys=True))


LAST = [0.0, 0.0]
GAP = float(os.environ.get('KIMG_GAP', '7'))  # a Wikimedia megosztott IP-n szigorúan korlátoz: lassan, egyenként
TGAP = float(os.environ.get('KIMG_TGAP', '4'))


def get(url, tries=8, throttle=True):
    err = None
    for i in range(tries):
        # minden kérést ritkítunk: az API-t jobban (GAP), a bélyegképeket kevésbé (TGAP) — a Wikimedia mindkettőt korlátozza
        g, slot = (GAP, 0) if throttle else (TGAP, 1)
        dt = time.time() - LAST[slot]
        if dt < g: time.sleep(g - dt)
        LAST[slot] = time.time()
        try:
            req = urllib.request.Request(url, headers={'User-Agent': UA})
            with urllib.request.urlopen(req, timeout=40) as r:
                b = r.read()
            if not b: raise ValueError('üres válasz')
            return b
        except urllib.error.HTTPError as e:
            err = e
            if e.code == 429:
                wait = int(e.headers.get('Retry-After') or 0) or 15 * (i + 1)
                wait = min(max(wait, 10), 900) + 3
                print('  429, várok', wait, 's', time.strftime('%H:%M:%S'), flush=True); time.sleep(wait)
            elif e.code in (500, 502, 503, 504):
                time.sleep(5 + 5 * i)
            else:
                raise
        except Exception as e:
            err = e
            time.sleep(3 + 3 * i)
    raise err


def api(params):
    params = dict(params, action='query', format='json', formatversion='2')
    url = API + '?' + urllib.parse.urlencode(params)
    for i in range(3):
        b = get(url)
        try:
            return json.loads(b.decode('utf-8'))
        except ValueError:
            print('  nem JSON válasz, újra', b[:80], flush=True); time.sleep(20)
    raise ValueError('nem JSON')


def strip(s):
    s = re.sub(r'<[^>]+>', ' ', s or '')
    return re.sub(r'\s+', ' ', html.unescape(s)).strip()


def lic_ok(l):
    if not l: return False
    if re.search(r'(?i)(^|[\s-])N[CD]([\s-]|$)', l): return False
    return bool(re.match(r'(?i)(cc0|public domain|pd\b|pd-|cc[ -]by|attribution|copyrighted free use|no restrictions)', l))


II = {'prop': 'imageinfo', 'iiprop': 'url|size|mime|extmetadata', 'iiurlwidth': '960',
      'iiextmetadatafilter': 'LicenseShortName|Artist|Restrictions|ObjectName'}


def search(q):
    if q.startswith('File:'):
        d = api(dict(II, titles=q))
    else:
        d = api(dict(II, generator='search', gsrsearch=q + ' filetype:bitmap', gsrnamespace='6', gsrlimit='15'))
    pages = (d.get('query') or {}).get('pages') or []
    pages.sort(key=lambda p: p.get('index', 0))
    out = []
    for p in pages:
        ii = (p.get('imageinfo') or [{}])[0]
        em = ii.get('extmetadata') or {}
        lic = (em.get('LicenseShortName') or {}).get('value', '')
        res = (em.get('Restrictions') or {}).get('value', '')
        w, h, mime = ii.get('width', 0), ii.get('height', 0), ii.get('mime', '')
        if not ii.get('thumburl') or not lic_ok(lic) or 'personality' in res.lower(): continue
        if mime not in ('image/jpeg', 'image/png', 'image/webp', 'image/svg+xml', 'image/tiff'): continue
        svg = mime == 'image/svg+xml'
        if not svg and (w < 700 or h < 400): continue
        a = w / float(h or 1)
        if not svg and (a < 1.0 or a > 2.6) and not q.startswith('File:'): continue
        sc = len(out) * 1.0 + abs(a - 1.5) * 2 + (0 if w >= 1200 else 1)
        out.append({'title': p['title'], 'thumb': ii['thumburl'], 'page': ii.get('descriptionurl', ''), 'w': w, 'h': h, 'mime': mime,
                    'license': strip(lic), 'artist': strip((em.get('Artist') or {}).get('value', ''))[:120], 'score': round(sc, 2)})
    out.sort(key=lambda c: c['score'])
    return out[:6]


def convert(slug, c):
    raw = get(c['thumb'], throttle=False)
    rp = os.path.join(RAW, slug + '.bin'); io.open(rp, 'wb').write(raw)
    im = Image.open(rp)
    if c['mime'] == 'image/svg+xml' or im.mode in ('RGBA', 'LA', 'P'):
        im = im.convert('RGBA'); bg = Image.new('RGBA', im.size, (244, 246, 241, 255)); bg.alpha_composite(im); im = bg
    im = im.convert('RGB')
    w, h = im.size
    if h > w * 0.75:  # legfeljebb 4:3 álló arány: középre (kicsit felülre) vágva
        nh = int(w * 0.75); top = int((h - nh) * 0.35); im = im.crop((0, top, w, top + nh))
    if c['mime'] == 'image/svg+xml' and im.size[0] / float(im.size[1]) < 1.45:  # címer: 3:2 vászonra
        W = int(im.size[1] * 1.5); bg = Image.new('RGB', (W, im.size[1]), (244, 246, 241)); bg.paste(im, ((W - im.size[0]) // 2, 0)); im = bg
    if im.size[0] > 800:
        im = im.resize((800, int(im.size[1] * 800.0 / im.size[0])), Image.LANCZOS)
    op = os.path.join(IMG, slug + '.webp')
    im.save(op, 'WEBP', quality=62, method=6)
    meta[slug] = {'title': c['title'], 'page': c['page'], 'license': c['license'], 'artist': c['artist'] or 'ismeretlen',
                  'w': im.size[0], 'h': im.size[1], 'q': Q[slug]['img']}
    return os.path.getsize(op)


def fetch(slugs, force=False):
    for s in slugs:
        q = Q[s]['img']
        if not q or q == '-':
            meta.pop(s, None); continue
        if s in meta and meta[s].get('q') == q and os.path.exists(os.path.join(IMG, s + '.webp')) and not force:
            continue
        try:
            cs = search(q)
        except Exception as e:
            print('HIBA keresés', s, e); continue
        cand[s] = cs
        if not cs:
            print('NINCS', s, '|', q); meta.pop(s, None); save(s); continue
        try:
            n = convert(s, cs[0])
            print('ok', s, n // 1024, 'KiB', cs[0]['title'][:70], '|', cs[0]['license'])
        except Exception as e:
            print('HIBA letöltés', s, e)
        save(s)


def wiki(path):
    """--wiki térkép.txt: „azonosító | lengyel Wikipédia-szócikk" (vagy File:…). A szócikkek vezető képét kéri le 50-esével
    (pageimages, csak szabad képek), aztán a Commons-adatokat is 50-esével: így 60 tételhez is csak néhány API-hívás kell."""
    pairs = []
    for raw in io.open(path, encoding='utf-8').read().split('\n'):
        if raw.strip() and not raw.startswith('#'):
            k, _, v = raw.partition('|'); k = k.strip()
            if k in meta and meta[k].get('via') == 'plwiki' and os.path.exists(os.path.join(IMG, k + '.webp')): continue
            pairs.append((k, v.strip()))
    print('wiki:', len(pairs), 'tétel', flush=True)
    files = {}
    arts = [(k, t) for k, t in pairs if not t.startswith('File:')]
    for i in range(0, len(arts), 50):
        ch = arts[i:i + 50]
        b = get('https://pl.wikipedia.org/w/api.php?' + urllib.parse.urlencode({'action': 'query', 'format': 'json', 'formatversion': '2',
                'prop': 'pageimages', 'piprop': 'name', 'pilicense': 'free', 'redirects': '1', 'titles': '|'.join(t for _, t in ch)}))
        d = json.loads(b.decode('utf-8'))['query']
        norm = {x['from']: x['to'] for x in d.get('normalized', [])}; red = {x['from']: x['to'] for x in d.get('redirects', [])}
        pages = {p['title']: p for p in d.get('pages', [])}
        for k, t in ch:
            t1 = norm.get(t, t); t1 = red.get(t1, t1); p = pages.get(t1) or {}
            if p.get('pageimage'): files[k] = 'File:' + p['pageimage'].replace('_', ' ')
            else: print('NINCS KÉP a szócikkben', k, '|', t, '(hiányzik)' if p.get('missing') else '')
    for k, t in pairs:
        if t.startswith('File:'): files[k] = t
    info = {}
    tl = sorted(set(files.values()))
    for i in range(0, len(tl), 50):
        d = api(dict(II, titles='|'.join(tl[i:i + 50])))
        norm = {x['from']: x['to'] for x in (d.get('query') or {}).get('normalized', [])}
        got = {p['title']: p for p in (d.get('query') or {}).get('pages', [])}
        for t in tl[i:i + 50]: info[t] = got.get(norm.get(t, t))
    for k, f in files.items():
        p = info.get(f)
        if not p or not p.get('imageinfo'): print('NINCS fájladat', k, f); continue
        ii = p['imageinfo'][0]; em = ii.get('extmetadata') or {}
        lic = (em.get('LicenseShortName') or {}).get('value', ''); res = (em.get('Restrictions') or {}).get('value', '')
        if not ii.get('thumburl') or not lic_ok(lic) or 'personality' in res.lower(): print('ROSSZ licenc/kép', k, f, lic); continue
        c = {'title': p['title'], 'thumb': ii['thumburl'], 'page': ii.get('descriptionurl', ''), 'w': ii.get('width', 0), 'h': ii.get('height', 0),
             'mime': ii.get('mime', ''), 'license': strip(lic), 'artist': strip((em.get('Artist') or {}).get('value', ''))[:120], 'score': 0}
        try:
            n = convert(k, c); meta[k]['q'] = Q[k]['img']; meta[k]['via'] = 'plwiki'
            cand.setdefault(k, []); cand[k] = [c] + [x for x in cand[k] if x['title'] != c['title']]
            save(k); print('ok', k, n // 1024, 'KiB', c['title'][:70], '|', c['license'], flush=True)
        except Exception as e:
            print('HIBA', k, e)


def font(sz):
    for f in ('/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf', '/usr/share/fonts/dejavu/DejaVuSans.ttf'):
        if os.path.exists(f): return ImageFont.truetype(f, sz)
    return ImageFont.load_default()


def sheet(items, outp, cols=6, tw=260, th=170):
    rows = (len(items) + cols - 1) // cols
    sh = Image.new('RGB', (cols * tw, rows * (th + 22)), (255, 255, 255)); dr = ImageDraw.Draw(sh); f = font(13)
    for i, (label, path) in enumerate(items):
        x, y = (i % cols) * tw, (i // cols) * (th + 22)
        try:
            im = Image.open(path).convert('RGB'); im.thumbnail((tw - 6, th - 4)); sh.paste(im, (x + 3, y + 2))
        except Exception:
            dr.rectangle((x + 3, y + 2, x + tw - 3, y + th - 2), outline=(200, 0, 0))
        dr.text((x + 4, y + th + 2), label[:34], fill=(0, 0, 0), font=f)
    sh.save(outp); print(outp, len(items))


if __name__ == '__main__':
    a = sys.argv[1:]
    if a and a[0] == '--pick':
        for kv in a[1:]:
            s, n = kv.split('='); c = cand[s][int(n)]
            print('ok', s, convert(s, c) // 1024, 'KiB', c['title'][:70], '|', c['license'])
            save(s)
    elif a and a[0] == '--wiki':
        wiki(a[1])
    elif a and a[0] == '--sheet':
        cats = a[1:] or ['t']
        items = [(s, os.path.join(IMG, s + '.webp')) for s in sorted(Q, key=lambda k: list(Q).index(k)) if Q[s]['cat'] in cats and s in meta]
        for i in range(0, len(items), 36):
            sheet(items[i:i + 36], '/tmp/kimg_sheet_%s_%d.png' % ('_'.join(cats), i // 36))
    elif a and a[0] == '--alts':
        for s in a[1:]:
            items = []
            for i, c in enumerate(cand.get(s, [])):
                p = os.path.join(RAW, '%s_alt%d.bin' % (s, i))
                if not os.path.exists(p):
                    try: io.open(p, 'wb').write(get(c['thumb'].replace('/960px-', '/330px-'), throttle=False))
                    except Exception: pass
                items.append(('%d %s' % (i, c['title'][5:40]), p))
            sheet(items, '/tmp/kimg_alts_%s.png' % s, cols=3, tw=330, th=220)
    elif a:
        fetch(a, force=True)
    else:
        fetch(list(Q))
