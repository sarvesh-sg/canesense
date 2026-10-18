"""Read-only access to the exported mill data (see export/export_data.py). Everything the agents say
about cane comes from these files; the satellite figures were produced by the mill's own existing satellite read, outside this repository.
model and are not recomputed here."""
import difflib
import json
import os
from functools import lru_cache

DATA_DIR = os.environ.get('DATA_DIR', os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), 'data'))
YIELD_T_PER_HA = 90          # the mill's planning yield
FRP_RS_PER_T = 3230          # average cane price paid to farmers in 2025-26 (from the export)
HNT_RS_PER_KM_T = 20         # approximate transport slab, rupees per km per tonne


def _load(name):
    with open(os.path.join(DATA_DIR, name)) as f:
        return json.load(f)


@lru_cache(maxsize=None)
def summary():
    return _load('summary.json')


@lru_cache(maxsize=None)
def villages():
    return _load('villages.json')


@lru_cache(maxsize=None)
def highcane():
    return _load('highcane.json')


@lru_cache(maxsize=None)
def districts():
    return _load('districts.json')


@lru_cache(maxsize=None)
def anomalies():
    return _load('anomalies.json')


@lru_cache(maxsize=None)
def plots(village_id):
    path = os.path.join(DATA_DIR, 'plots', f'{village_id}.json')
    if not os.path.exists(path):
        return None
    with open(path) as f:
        return json.load(f)


def picture_dir(village_id):
    d = os.path.join(DATA_DIR, 'pictures', str(village_id))
    return d if os.path.isdir(d) else None


_DEV = {'अ':'a','आ':'a','इ':'i','ई':'i','उ':'u','ऊ':'u','ए':'e','ऐ':'ai','ओ':'o','औ':'au','ऋ':'ri',
        'क':'k','ख':'kh','ग':'g','घ':'gh','ङ':'n','च':'ch','छ':'chh','ज':'j','झ':'jh','ञ':'n','ट':'t','ठ':'th','ड':'d','ढ':'dh',
        'ण':'n','त':'t','थ':'th','द':'d','ध':'dh','न':'n','प':'p','फ':'ph','ब':'b','भ':'bh','म':'m','य':'y','र':'r','ल':'l',
        'व':'v','श':'sh','ष':'sh','स':'s','ह':'h','ळ':'l','ा':'a','ि':'i','ी':'i','ु':'u','ू':'u','े':'e','ै':'ai','ो':'o','ौ':'au',
        'ृ':'ri','ं':'n','ँ':'n','ः':'','्':'','़':''}
# Kannada letters, so a Kannada-speaking officer's village names (ಆಷ್ಟಾ, ಬೇಡಗ) match too
_KAN = {'ಅ':'a','ಆ':'a','ಇ':'i','ಈ':'i','ಉ':'u','ಊ':'u','ಎ':'e','ಏ':'e','ಐ':'ai','ಒ':'o','ಓ':'o','ಔ':'au','ಋ':'ri',
        'ಕ':'k','ಖ':'kh','ಗ':'g','ಘ':'gh','ಙ':'n','ಚ':'ch','ಛ':'chh','ಜ':'j','ಝ':'jh','ಞ':'n','ಟ':'t','ಠ':'th','ಡ':'d','ಢ':'dh',
        'ಣ':'n','ತ':'t','ಥ':'th','ದ':'d','ಧ':'dh','ನ':'n','ಪ':'p','ಫ':'ph','ಬ':'b','ಭ':'bh','ಮ':'m','ಯ':'y','ರ':'r','ಲ':'l',
        'ವ':'v','ಶ':'sh','ಷ':'sh','ಸ':'s','ಹ':'h','ಳ':'l','ಾ':'a','ಿ':'i','ೀ':'i','ು':'u','ೂ':'u','ೆ':'e','ೇ':'e','ೈ':'ai','ೊ':'o','ೋ':'o','ೌ':'au',
        'ೃ':'ri','ಂ':'n','ಃ':'','್':''}
_DEV.update(_KAN)
_NOISE = ('village', 'gaon', 'gav', 'gaav', 'गाव', 'गावात', 'गावाची', 'गावची', 'गांव', 'ಗ್ರಾಮದಿಂದ', 'ಗ್ರಾಮದ', 'ಗ್ರಾಮ', 'ಹಳ್ಳಿ')


def phonetic(name):
    """Spoken-name key: Devanagari to Latin, aspirates and doublings collapsed, so Ashtha, Asta, आष्टा and Ashta agree."""
    s = name.strip().lower()
    for w in sorted(_NOISE, key=len, reverse=True):
        s = s.replace(w, ' ')
    s = ''.join(_DEV.get(ch, ch) for ch in s)
    s = ''.join(ch for ch in s if ch.isalpha())
    for a, b in (('sh', 's'), ('chh', 'ch'), ('th', 't'), ('dh', 'd'), ('bh', 'b'), ('kh', 'k'), ('gh', 'g'), ('ph', 'p'), ('jh', 'j'),
                 ('w', 'v'), ('ee', 'i'), ('oo', 'u'), ('aa', 'a'), ('z', 'j'), ('q', 'k')):
        s = s.replace(a, b)
    out = []
    for ch in s:
        if not out or out[-1] != ch:
            out.append(ch)
    s = ''.join(out)
    return s[:-1] if len(s) > 3 and s.endswith('a') else s


def skeleton(name):
    """Consonants only: Devanagari leaves the inherent 'a' unwritten, so कसबे (ksb) and Kasbe (ksb) agree here."""
    return ''.join(ch for ch in phonetic(name) if ch not in 'aeiou')


def _words(name):
    return [w for w in (name or '').replace('(', ' ').replace(')', ' ').split()]


def find_village(name):
    """Best matching village by name (supply villages first, then high-cane villages). None if no fair match.
    Accepts typed English, spoken transliterations (Asta, Ashta) and Devanagari (आष्टा)."""
    if not name:
        return None
    key = name.strip().lower()
    pool = villages() + highcane()
    exact = [v for v in pool if v['name'].lower() == key]
    if exact:
        return exact[0]
    starts = [v for v in pool if v['name'].lower().startswith(key)]
    if len(starts) == 1:
        return starts[0]
    names = [v['name'].lower() for v in pool]
    close = difflib.get_close_matches(key, names, n=1, cutoff=0.75)
    if close:
        return pool[names.index(close[0])]
    pk = phonetic(key)
    if pk:
        keys = [phonetic(v['name']) for v in pool]
        if pk in keys:
            return pool[keys.index(pk)]
        close = difflib.get_close_matches(pk, keys, n=1, cutoff=0.8)
        if close:
            return pool[keys.index(close[0])]
        sk = skeleton(key)
        if len(sk) >= 3:
            skels = [skeleton(v['name']) for v in pool]
            if skels.count(sk) == 1:
                return pool[skels.index(sk)]
        # a village said by one of its words only ("Digraj" for Kasbe Digraj), when that word names a single village
        hits = [v for v in pool if any(phonetic(w) == pk or (len(sk) >= 3 and skeleton(w) == sk) for w in _words(v['name']))]
        if len(hits) == 1:
            return hits[0]
    return None


def not_found(name):
    """Error payload for an unknown village, with the villages that share a word of the name so the agent can ask back."""
    pool = villages() + highcane()
    keys = {skeleton(w) for w in _words(name) if len(skeleton(w)) >= 3} | ({skeleton(name)} if len(skeleton(name)) >= 3 else set())
    hits = [v['name'] for v in pool if keys & ({skeleton(w) for w in _words(v['name'])} | {skeleton(v['name'])})]
    hits = sorted(set(hits))[:5]
    out = {'error': f"No village named '{name}' among the mill's supply or high-cane villages."}
    if hits:
        out['did_you_mean'] = hits
        out['error'] += ' Ask the user which one they mean: ' + ', '.join(hits) + '.'
    return out


def cane_ha(v, season='2026'):
    s = v['seasons'].get(season) or {}
    return s.get('cane_ha') or 0.0
