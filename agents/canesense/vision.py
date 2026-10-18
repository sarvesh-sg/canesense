"""The picture tool: Gemini looks at the latest Sentinel-2 picture of a village (true colour and greenness) and
says what it sees, the way a cane officer would before trusting a number."""
import json
import os

from google import genai
from google.genai import errors, types

from . import data as D

from .models import RETRY_CODES, model_chain

VISION_CHAIN = [os.environ['VISION_MODEL']] if os.environ.get('VISION_MODEL') else model_chain()

_client = None


def client():
    global _client
    if _client is None:
        _client = genai.Client(http_options=types.HttpOptions(timeout=40000, retry_options=types.HttpRetryOptions(
            attempts=1, http_status_codes=sorted(RETRY_CODES))))   # Vertex AI or the AI Studio key, from env; 40 s then the next model
    return _client


def look_at_village_picture(village: str, question: str = '') -> dict:
    """Look at the latest satellite picture of a village and describe it: how much of the land is in standing cane, where fields
    look freshly cut, where orchards or other crops are, cloud or haze. Pass the village name and, optionally, what to look for.
    Returns the description, the picture date, and picture URLs to show the user."""
    v = D.find_village(village)
    if not v:
        return D.not_found(village)
    folder = D.picture_dir(v['id'])
    if not folder:
        return {'error': f"{v['name']} has no stored picture in this prototype."}
    with open(os.path.join(folder, 'meta.json')) as f:
        meta = json.load(f)
    rgb = open(os.path.join(folder, 'rgb.jpg'), 'rb').read()
    ndvi = open(os.path.join(folder, 'ndvi.jpg'), 'rb').read()
    ha = D.cane_ha(v)
    prompt = (
        f"You are a sugarcane field officer reading two Sentinel-2 pictures of the village {v['name']} ({v['district']} district, India), "
        f"taken on {meta.get('when')}. The first is true colour, the second is greenness (vegetation index: bright green = dense green crop, "
        f"brown/grey = bare or harvested). The village's plots are outlined; land outside the outline belongs to neighbours.\n"
        f"The satellite model read {ha:.0f} ha of standing cane here this season.\n"
        "Describe, in plain words for a mill manager, in at most 8 short sentences: (1) roughly what share of the outlined land is dense "
        "green crop, (2) where fields look freshly cut or bare (which side of the village), (3) anything that is clearly not cane: orchards, "
        "water, built-up land, (4) whether the picture is clear enough to trust, (5) whether the picture agrees with the model's cane figure. "
        "Do not invent numbers you cannot see; say 'about' and give ranges."
        + (f"\nThe manager asked specifically: {question}" if question else ''))
    contents = [types.Part.from_bytes(data=rgb, mime_type='image/jpeg'), types.Part.from_bytes(data=ndvi, mime_type='image/jpeg'), prompt]
    resp = None
    for i, name in enumerate(VISION_CHAIN):
        try:
            resp = client().models.generate_content(model=name, contents=contents, config=types.GenerateContentConfig(temperature=0.2))
            break
        except Exception as e:  # noqa: BLE001  (rate limit, overload or a timeout: try the next model)
            if (getattr(e, 'code', None) in RETRY_CODES or not isinstance(e, errors.APIError)) and i + 1 < len(VISION_CHAIN):
                continue
            raise
    return {'village': v['name'], 'picture_date': meta.get('when'), 'clear_day': meta.get('clear'), 'model_cane_ha_2026': round(ha),
            'what_the_picture_shows': resp.text,
            'picture_urls': [f"/pictures/{v['id']}/rgb.jpg", f"/pictures/{v['id']}/ndvi.jpg"],
            'note': 'A description of one picture; the season figure comes from the full-season satellite model, not from this look.'}


# ---- the eyes on one plot: crop the village picture to a survey number and ask whether that is cane ----
def _norm_survey(s):
    return D.norm_survey(s) if hasattr(D, 'norm_survey') else str(s).strip().upper().replace(' ', '')


def plot_geometry(village_id, survey):
    """Outline of a survey number on the land map: exact pin first, else every part of the same base number."""
    path = os.path.join(D.DATA_DIR, 'plots_geo', f'{village_id}.json')
    if not os.path.exists(path):
        return []
    with open(path) as f:
        geo = json.load(f)
    want = _norm_survey(survey)
    exact = [(pin, g) for pin, g in geo.items() if _norm_survey(pin) == want]
    if exact:
        return exact
    base = want.split('/')[0]
    return [(pin, g) for pin, g in geo.items() if _norm_survey(pin).split('/')[0] == base]


def look_at_plot(village: str, survey_number: str) -> dict:
    """Look at one survey number (plot) in the latest satellite picture of a village and say whether what is visible looks like
    standing cane. Crops the true-colour and greenness pictures to the plot with its outline drawn, shows them, and compares with
    the satellite model's read for that plot. Use when someone asks 'is survey 1252 really cane?' or wants to verify a plot."""
    from PIL import Image, ImageDraw
    v = D.find_village(village)
    if not v:
        return D.not_found(village)
    folder = D.picture_dir(v['id'])
    if not folder:
        return {'error': f"{v['name']} has no stored picture in this prototype."}
    parts = plot_geometry(v['id'], survey_number)
    if not parts:
        return {'error': f"Survey number {survey_number} is not on the land map of {v['name']} in this prototype."}
    with open(os.path.join(folder, 'meta.json')) as f:
        meta = json.load(f)
    w, s, e, n = meta['bounds']
    crops = []
    for kind in ('rgb', 'ndvi'):
        im = Image.open(os.path.join(folder, f'{kind}.jpg')).convert('RGB')
        W, H = im.size
        px = lambda lon, lat: ((lon - w) / (e - w) * W, (n - lat) / (n - s) * H)
        xs = [px(*p)[0] for _, g in parts for p in g['ring']]
        ys = [px(*p)[1] for _, g in parts for p in g['ring']]
        cx, cy = (min(xs) + max(xs)) / 2, (min(ys) + max(ys)) / 2
        half = max(max(xs) - min(xs), max(ys) - min(ys)) / 2 * 1.8 + 12          # the plot and its neighbours for context
        box = (int(cx - half), int(cy - half), int(cx + half), int(cy + half))
        crop = im.crop(box)
        scale = max(1, int(640 / max(1, crop.width)))
        crop = crop.resize((crop.width * scale, crop.height * scale), Image.LANCZOS)
        dr = ImageDraw.Draw(crop)
        for _, g in parts:
            ring = [((px(*p)[0] - box[0]) * scale, (px(*p)[1] - box[1]) * scale) for p in g['ring']]
            dr.line(ring, fill=(255, 230, 0), width=3)
        out_dir = os.path.join(D.DATA_DIR, 'pictures', 'crops')
        os.makedirs(out_dir, exist_ok=True)
        name = f"{v['id']}_{_norm_survey(survey_number).replace('/', '-')}_{kind}.jpg"
        crop.save(os.path.join(out_dir, name), 'JPEG', quality=88)
        crops.append((kind, os.path.join(out_dir, name), f'/pictures/crops/{name}', crop.width // scale))
    # what the model said about this plot
    read = None
    for p in (D.plots(v['id']) or {}).get('plots', []):
        if _norm_survey(p['survey']).split('/')[0] == _norm_survey(survey_number).split('/')[0]:
            s26 = (p.get('seasons') or {}).get('2026') or {}
            read = {'survey': p['survey'], 'part': p.get('part'), 'area_ha': p.get('area_ha'), 'cane_ha_2026': s26.get('cane_ha'),
                    'is_cane_2026': s26.get('is_cane'), 'delivered_2025_26_t': p.get('delivered_2025_26')}
            break
    ha = sum(g.get('ha') or 0 for _, g in parts)
    metres = int(crops[0][3] * 10)
    prompt = (
        f"You are a sugarcane field officer. These are two Sentinel-2 crops ({metres} m across, 10 m per pixel, taken {meta.get('when')}) "
        f"around survey number {survey_number} in {v['name']} ({v['district']} district, India). The plot is outlined in yellow "
        f"({ha:.1f} ha on the land map). First picture true colour, second greenness (bright green = dense green crop; brown/grey = bare, "
        f"cut or dry).\n"
        + (f"The satellite model read this plot as {'cane' if read['is_cane_2026'] else 'not cane'} ({read['cane_ha_2026']} ha of cane). "
           f"Delivered to our factory in 2025-26: {read['delivered_2025_26_t'] or 0} t.\n" if read else "The model has no plot read here.\n")
        + "In at most 5 short sentences: (1) what fills the outlined plot: dense tall green crop, young/sparse crop, bare or cut field, trees, "
          "buildings, water; (2) does it look like standing sugarcane, with how much confidence (high/medium/low) given 10 m pixels; "
          "(3) does that agree with the model's read; (4) one thing a field visit should confirm. Never invent detail you cannot see.")
    contents = [types.Part.from_bytes(data=open(crops[0][1], 'rb').read(), mime_type='image/jpeg'),
                types.Part.from_bytes(data=open(crops[1][1], 'rb').read(), mime_type='image/jpeg'), prompt]
    resp = None
    for i, name in enumerate(VISION_CHAIN):
        try:
            resp = client().models.generate_content(model=name, contents=contents, config=types.GenerateContentConfig(temperature=0.2))
            break
        except Exception as e:  # noqa: BLE001  (rate limit, overload or a timeout: try the next model)
            if (getattr(e, 'code', None) in RETRY_CODES or not isinstance(e, errors.APIError)) and i + 1 < len(VISION_CHAIN):
                continue
            raise
    return {'village': v['name'], 'survey_number': survey_number, 'parts_on_land_map': [pin for pin, _ in parts], 'land_map_ha': round(ha, 2),
            'model_read': read, 'picture_date': meta.get('when'), 'what_the_eye_sees': resp.text.strip() if resp else '',
            'picture_urls': [c[2] for c in crops],
            'note': 'Sentinel-2 is 10 m per pixel: a 1 ha plot is about 10 by 10 pixels. The eye can tell dense crop from bare or built-up land, not cane from every other tall crop.'}
