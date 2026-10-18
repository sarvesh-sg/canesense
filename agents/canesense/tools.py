"""Tools the agents call. Each returns plain dicts built only from the exported data, so every figure
in an answer can be traced to a file. Rupee figures are stated in crore where large (1 crore = 10 million)."""
from . import data as D


def crore(rs):
    return round(rs / 1e7, 2)


def season_summary() -> dict:
    """Headline figures for the mill's 2025-26 season: cane crushed, trips, farmers, money paid, and how much
    cane the satellite saw standing in the supply villages. Use this first for any 'how are we doing' question."""
    s = D.summary()
    standing_t = s['supply_cane_ha_2026'] * D.YIELD_T_PER_HA
    return {
        'season': s['season'], 'cane_crushed_t': s['crushed_t'], 'trips': s['trips'], 'farmers_who_delivered': s['farmers'],
        'paid_to_farmers_rs_crore': crore(s['paid_to_farmers_rs']), 'paid_harvest_and_transport_rs_crore': crore(s['paid_hnt_rs']),
        'supply_villages': s['supply_villages'], 'satellite_cane_in_supply_villages_ha': s['supply_cane_ha_2026'],
        'standing_cane_estimate_t_at_90_t_per_ha': round(standing_t), 'our_share_of_standing_cane_pct': round(100 * s['crushed_t'] / standing_t, 1),
        'mills': s['mills'], 'satellite_model': s['satellite_model'],
        'note': 'Standing cane uses the mill planning yield of 90 t/ha; the satellite gives area, not tonnes.',
    }


def catchment_gap(max_km: float = 30, min_cane_ha: float = 100, max_tonnes_per_ha: float = 20, limit: int = 15) -> dict:
    """Villages near our mills where the satellite sees a lot of cane but little of it reached us. Returns, per village,
    cane hectares, tonnes received, tonnes per cane hectare, distance to our mill and to the nearest competing factory,
    and the tonnes we would gain at half share. Parameters: max_km from our nearest mill, min_cane_ha of satellite cane,
    max_tonnes_per_ha received (below this counts as a gap), limit rows."""
    rows = []
    for v in D.villages():
        ha = D.cane_ha(v)
        mill = v.get('our_mill')
        if not mill or mill['km'] > max_km or ha < min_cane_ha:
            continue
        t = v['deliveries_2025_26']['tonnes']
        tpha = t / ha if ha else 0
        if tpha > max_tonnes_per_ha:
            continue
        gain_t = max(0.0, ha * D.YIELD_T_PER_HA * 0.5 - t)
        other = v.get('nearest_other_factory') or {}
        rows.append({'village': v['name'], 'district': v['district'], 'our_mill': mill['name'], 'km_to_our_mill': mill['km'],
                     'satellite_cane_ha_2026': round(ha), 'tonnes_received': round(t), 'tonnes_per_cane_ha': round(tpha, 1),
                     'farmers_who_delivered': v['deliveries_2025_26']['farmers'],
                     'nearest_other_factory': other.get('name'), 'km_to_other_factory': other.get('km'), 'other_factory_status': other.get('status'),
                     'ratoon_ha_on_plots_that_delivered_to_us': v.get('ratoon_ha_2026_on_our_plots'),
                     'gain_t_at_half_share': round(gain_t), 'has_picture': v.get('has_picture')})
    rows.sort(key=lambda r: -r['gain_t_at_half_share'])
    total_gain = sum(r['gain_t_at_half_share'] for r in rows)
    return {'filters': {'max_km': max_km, 'min_cane_ha': min_cane_ha, 'max_tonnes_per_ha': max_tonnes_per_ha},
            'villages_matching': len(rows), 'total_gain_t_at_half_share': round(total_gain),
            'cane_value_of_gain_rs_crore_at_frp': crore(total_gain * D.FRP_RS_PER_T), 'rows': rows[:limit],
            'note': 'A village the satellite reads high and we receive little from is a reason to look, not a finding: '
                    'cane may be contracted to the nearer factory, or the village boundary may be misread.'}


def village_brief(village: str) -> dict:
    """Everything known about one village: satellite cane for 7 seasons, our deliveries by month, farmers, distances to our
    mill and the nearest competitor, ratoon on plots that delivered to us, satellite harvest progress, whether a picture
    and plot-level reads exist. Pass the village name as written by the user."""
    v = D.find_village(village)
    if not v:
        return D.not_found(village)
    seasons = {y: (s or {}).get('cane_ha') for y, s in v['seasons'].items()}
    ha26 = D.cane_ha(v)
    t = v['deliveries_2025_26']['tonnes']
    out = {'village': v['name'], 'village_id': v['id'], 'district': v['district'], 'taluk': v['taluk'], 'group': v['group'],
           'satellite_cane_ha_by_season': seasons, 'other_layers_2026': v['seasons'].get('2026'),
           'our_mill': v.get('our_mill'), 'nearest_other_factory': v.get('nearest_other_factory'),
           'deliveries_2025_26': v['deliveries_2025_26'], 'tonnes_per_cane_ha': v.get('tonnes_per_cane_ha'),
           'standing_cane_estimate_t': round(ha26 * D.YIELD_T_PER_HA), 'our_share_pct': round(100 * t / (ha26 * D.YIELD_T_PER_HA), 1) if ha26 else None,
           'ratoon_ha_2026_on_plots_that_delivered_to_us': v.get('ratoon_ha_2026_on_our_plots'),
           'satellite_cut_share_by_month_end': v.get('satellite_cut_share'),
           'has_picture': v.get('has_picture'), 'has_plot_reads': v.get('has_plots'),
           'picture_urls': [f"/pictures/{v['id']}/rgb.jpg", f"/pictures/{v['id']}/ndvi.jpg"] if v.get('has_picture') else []}
    return out


def district_trend(district: str = '', state: str = '') -> dict:
    """Satellite cane area by season (2020-2026) for one district, or for every district of a state when only the state is given.
    Figures come from the mill's existing satellite read at district level."""
    rows = [r for r in D.districts() if (not district or r['district'].lower() == district.lower()) and (not state or r['state'].lower() == state.lower())]
    if not rows:
        return {'error': f"No district rows for district='{district}' state='{state}'."}
    out = {}
    for r in rows:
        out.setdefault(f"{r['state']} / {r['district']}", {})[str(r['season_year'])] = r['cane_ha']
    return {'cane_ha_by_season': out, 'note': 'Season 2026 means the crop read in Oct 2025 - Oct 2026 for the 2026-27 crushing season.'}


def nearby_cane_not_ours(max_km: float = 50, limit: int = 15) -> dict:
    """Villages that are NOT our supply villages but carry at least 50 ha of satellite cane, within max_km of our mills:
    candidates to sign new farmers. Returns name, district, cane ha, distance to our mill and to the nearest competitor."""
    rows = []
    for v in D.highcane():
        mill = v.get('our_mill')
        if not mill or mill['km'] > max_km:
            continue
        other = v.get('nearest_other_factory') or {}
        rows.append({'village': v['name'], 'district': v['district'], 'satellite_cane_ha_2026': round(D.cane_ha(v)), 'km_to_our_mill': mill['km'],
                     'our_mill': mill['name'], 'nearest_other_factory': other.get('name'), 'km_to_other_factory': other.get('km')})
    rows.sort(key=lambda r: -r['satellite_cane_ha_2026'])
    return {'villages': len(rows), 'cane_ha_total': round(sum(r['satellite_cane_ha_2026'] for r in rows)), 'rows': rows[:limit]}


def anomaly_cases(kind: str = 'contractor_advances', limit: int = 10) -> dict:
    """Money checks from the mill's records, identities removed. kind is one of:
    'contractor_advances' (H&T advance against what the contractor earned this season),
    'trips_billed_to_another_village' (transport paid at another village's distance),
    'deliveries_from_plots_with_no_cane_seen' (survey numbers that sent cane while the satellite saw none on them).
    Every row is a reason to check, never a finding."""
    a = D.anomalies()
    if kind not in a or kind == 'notes':
        return {'error': f"kind must be one of {[k for k in a if k != 'notes']}"}
    rows = a[kind]
    out = {'kind': kind, 'what_it_means': a['notes'][kind], 'total_rows': len(rows), 'rows': rows[:limit]}
    if kind == 'contractor_advances':
        exposed = [r for r in rows if r['exposed_rs'] > 0]
        out['summary'] = {'contractors_with_advance': len(rows), 'advance_total_rs_crore': crore(sum(r['advance_rs'] for r in rows)),
                          'contractors_whose_advance_exceeds_earnings': len(exposed), 'exposed_rs_crore': crore(sum(r['exposed_rs'] for r in exposed)),
                          'took_advance_and_harvested_nothing': sum(1 for r in rows if r['harvested_t'] == 0)}
    elif kind == 'trips_billed_to_another_village':
        extra = sum((r['billed_km'] or 0) - (r['farmer_village_km'] or 0) for r in rows if r['billed_km'] and r['farmer_village_km']) / max(1, len(rows))
        out['summary'] = {'village_pairs': len(rows), 'tonnes': round(sum(r['tonnes'] for r in rows)), 'average_extra_km_billed': round(extra, 1),
                          'approx_extra_transport_rs_crore': crore(sum(max(0, (r['billed_km'] or 0) - (r['farmer_village_km'] or 0)) * r['tonnes'] * D.HNT_RS_PER_KM_T for r in rows))}
    else:
        out['summary'] = {'villages': len(rows), 'plots': sum(r['plots'] for r in rows), 'tonnes': round(sum(r['tonnes'] for r in rows))}
    return out


def case_detail(kind: str, key: str) -> dict:
    """One case in full for review. kind as in anomaly_cases; key is the contractor code (e.g. 'C-0007') or the billed village name
    or the village name, depending on kind. Adds the village brief where a village is involved."""
    a = D.anomalies()
    if kind == 'contractor_advances':
        row = next((r for r in a[kind] if r['code'].lower() == key.lower()), None)
        return row or {'error': f'no contractor {key}'}
    if kind == 'trips_billed_to_another_village':
        rows = [r for r in a[kind] if key.lower() in (r['billed_village'].lower(), r['farmer_village'].lower())]
        return {'rows': rows, 'billed_village_brief': village_brief(key)} if rows else {'error': f'no mis-booked trips for {key}'}
    if kind == 'deliveries_from_plots_with_no_cane_seen':
        row = next((r for r in a[kind] if r['village'].lower() == key.lower()), None)
        return {'row': row, 'village_brief': village_brief(key)} if row else {'error': f'no such village {key} in this list'}
    return {'error': 'unknown kind'}


def plot_lookup(village: str, survey_number: str = '', only_cane: bool = False, limit: int = 20) -> dict:
    """Plot-level satellite reads (2025 and 2026) for a village that has field-by-field detail. Give a survey number to see one
    plot (all its parts), or leave it empty for the village's largest cane plots. Each plot shows area, cane hectares, whether it
    is read as cane, and the tonnes it sent us in 2025-26 if any."""
    v = D.find_village(village)
    if not v:
        return D.not_found(village)
    p = D.plots(v['id'])
    if not p:
        return {'error': f"{v['name']} has no plot-level reads in this prototype (only villages with a satellite picture were exported)."}
    rows = p['plots']
    if survey_number:
        want = survey_number.strip().upper()
        rows = [r for r in rows if r['survey'].upper() == want or r['survey'].upper().startswith(want + '/')]
        if not rows:
            return {'error': f"survey number {survey_number} is not on the land map of {v['name']}."}
    else:
        rows = sorted(rows, key=lambda r: -((r['seasons'].get('2026') or {}).get('cane_ha') or 0))
    if only_cane:
        rows = [r for r in rows if (r['seasons'].get('2026') or {}).get('is_cane')]
    cane_plots = [r for r in p['plots'] if (r['seasons'].get('2026') or {}).get('is_cane')]
    delivered = [r for r in p['plots'] if r.get('delivered_2025_26')]
    return {'village': v['name'], 'plots_on_land_map': len(p['plots']), 'plots_read_as_cane_2026': len(cane_plots),
            'cane_plots_that_delivered_to_us': sum(1 for r in cane_plots if r.get('delivered_2025_26')),
            'plots_that_delivered_but_show_no_cane': sum(1 for r in delivered if not (r['seasons'].get('2026') or {}).get('is_cane')),
            'rows': rows[:limit], 'picture_urls': [f"/pictures/{v['id']}/rgb.jpg", f"/pictures/{v['id']}/ndvi.jpg"] if v.get('has_picture') else []}


def pay_at_the_gate(village: str, limit: int = 10) -> dict:
    """The 'pay at the gate' pipeline for one village: the cane a lender can see coming, so the mill can pay farmers on the day of
    delivery instead of weeks later. Returns (a) the returning plots: read as cane now, cane last season, delivered to us last season,
    with their expected tonnes and the cash needed at the gate at FRP, month by month from last season's pattern; (b) the prize: plots
    read as cane that sent us nothing, which a mill that pays at the gate can win. Only for villages with plot reads."""
    v = D.find_village(village)
    if not v:
        return D.not_found(village)
    p = D.plots(v['id'])
    if not p:
        return {'error': f"{v['name']} has no plot-level reads in this prototype."}
    def t(x):
        d = x.get('delivered_2025_26'); return (d.get('tonnes') if isinstance(d, dict) else d) or 0
    def ha(x, season): return ((x.get('seasons') or {}).get(season) or {}).get('cane_ha') or 0.0
    cane_now = [x for x in p['plots'] if ((x.get('seasons') or {}).get('2026') or {}).get('is_cane')]
    returning = [x for x in cane_now if ((x.get('seasons') or {}).get('2025') or {}).get('is_cane') and t(x) > 0]
    prize = [x for x in cane_now if t(x) == 0]
    def expected(x): return min(ha(x, '2026') * D.YIELD_T_PER_HA, t(x) * 1.1)   # never more than the plot actually sent, plus a tenth
    def row(x):
        return {'survey': x['survey'], 'cane_ha_now': round(ha(x, '2026'), 2), 'standing_t_at_90': round(ha(x, '2026') * D.YIELD_T_PER_HA),
                'delivered_last_season_t': round(t(x)), 'expected_t': round(expected(x)), 'cash_at_gate_rs': round(expected(x) * D.FRP_RS_PER_T)}
    exp_t = sum(expected(x) for x in returning)
    by_month = (v.get('deliveries_2025_26') or {}).get('by_month') or {}
    tot = sum(by_month.values()) or 1
    cash_by_month = {m: crore(exp_t * share / tot * D.FRP_RS_PER_T) for m, share in by_month.items()}
    prize_t = sum(ha(x, '2026') for x in prize) * D.YIELD_T_PER_HA
    return {
        'village': v['name'], 'our_mill_km': (v.get('our_mill') or {}).get('km'), 'nearest_other_factory': v.get('nearest_other_factory'),
        'frp_rs_per_t': D.FRP_RS_PER_T,
        'returning_plots': {'plots': len(returning), 'cane_ha_now': round(sum(ha(x, '2026') for x in returning), 1),
                            'expected_t': round(exp_t), 'cash_at_gate_rs_crore': crore(exp_t * D.FRP_RS_PER_T),
                            'cash_by_month_rs_crore': cash_by_month, 'rows': sorted((row(x) for x in returning), key=lambda r: -r['expected_t'])[:limit]},
        'cane_to_win': {'plots': len(prize), 'cane_ha_now': round(sum(ha(x, '2026') for x in prize)),
                        'standing_t_at_90': round(prize_t), 'value_rs_crore_at_frp': crore(prize_t * D.FRP_RS_PER_T),
                        'rows': sorted((row(x) for x in prize), key=lambda r: -r['standing_t_at_90'])[:limit]},
        'how_it_works': 'Farmers go to the mill that pays on time; the law says 14 days, most mills take 60 to 90. Paying at the gate, on the day '
                        'of delivery, needs working capital a lender will only give against receipts it can see. This pipeline is what the lender '
                        'sees: plots read as cane now that delivered last season, their expected tonnes, and the cash needed month by month. '
                        'Expected tonnes are capped by what each plot actually sent last season; standing tonnes rest on 90 t/ha.',
        'picture_urls': [f"/pictures/{v['id']}/rgb.jpg", f"/pictures/{v['id']}/ndvi.jpg"] if v.get('has_picture') else []}
