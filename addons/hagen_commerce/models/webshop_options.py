"""Turn a WooCommerce order line or variation into an Odoo build.

blurbybike.com sells variable products (Size, Colour, Carbon package, Luggage
rack, Pedals). hagenbikes.com sells bikes through a configurator whose options
arrive as "01 Colors: Yellow", "02 Type: Frame set", ... in the line meta. Both
end up here, so order import, manufacturing orders and the stock push all use
the same rules.

A build is a plain dict, so it can be stored as JSON on the sales order line:
    code      Odoo internal reference of the bike or frameset, or None
    replace   [[old_part, new_part], ...]   applied only where the recipe has old_part
    remove    [part, ...]
    add       [[part, qty_per_unit, label], ...]   MO components for bikes, extra
                                                   order lines for kits
    notes     build sheet lines (printed on the MO and the invoice line)
    warnings  things the workshop has to check
"""

import html
import re

HAGEN_MODELS = (('flagship', 'FLAGSHIP'), ('hagen xl', 'XL'))
HAGEN_BIKES = {
    ('FLAGSHIP', False): 'M-005',
    ('FLAGSHIP', True): 'M-006',
    ('XL', False): 'M-007',
    ('XL', True): 'M-008',
}
HAGEN_FRAMESETS = {'FLAGSHIP': 'FS-HAGEN-FLAGSHIP', 'XL': 'FS-HAGEN-XL'}
FRAMESET_WORDS = ('frame set', 'frameset', 'frame-set', 'rahmenset', 'rahmen-set', 'rahmen set')
NON_ELECTRIC_WORDS = ('non-electric', 'non electric', 'nicht-elektrisch', 'nicht elektrisch', 'ohne motor')
ELECTRIC_WORDS = ('brose', 'mid-motor', 'mittelmotor', 'electric', 'elektrisch', ' nm')

# Longest name first: "blurby w" must not swallow "blurby w..." of another model.
BLURBY_MODELS = (
    (re.compile(r'\bblurby\s+trekking\b'), 'M-001'),
    (re.compile(r'\bblurby\s+max\b'), 'M-002'),
    (re.compile(r'\bblurby\s+gravel\b'), 'M-003'),
    (re.compile(r'\bblurby\s+w\b'), 'M-004'),
    (re.compile(r'\bblurby\s+bike\b'), 'M-004'),
)
BLURBY_STEP_THROUGH_MODEL = re.compile(r'\bblurby\s+w\b')

# Base recipes are built for size L, aluminium package, Deore 10s, riser bar,
# black panels. Options swap parts away from that base.
BLURBY_BASE_FRAME, BLURBY_BASE_REAR_GUARD = 'A50', 'A41'
BLURBY_SIZES = {
    'L': ('A50', 'A41', 'L frame'),
    'M': ('A51', 'A40', 'M frame'),
    'W': ('A52', 'A39', 'Women / step-through frame'),
}
BLURBY_CARBON = (('A55', 'A57'), ('A29', 'A30'))
HAGEN_DRIVETRAINS = {
    'deore': ('Shimano Deore 10-speed derailleur (base)', [], []),
    'nexus': ('Shimano Nexus 5-speed hub', [['A154', 'A157'], ['A156', 'A158']], ['A8']),
    'alfine': ('Shimano Alfine 8-speed hub', [['A154', 'A159'], ['A156', 'A160']], ['A8']),
}
HAGEN_HANDLEBARS = {
    'riser': ('Riser (A98, base)', []),
    'flat': ('Flat (A99)', [['A98', 'A99']]),
    'cruiser': ('Cruiser (A28)', [['A98', 'A28']]),
}
HAGEN_GREY_PANELS = [['A110', 'A112'], ['A111', 'A113'], ['A102', 'A103'], ['A104', 'A105']]
HAGEN_FLOOR_PLATE = {('FLAGSHIP', False): 'A102', ('FLAGSHIP', True): 'A103', ('XL', False): 'A104', ('XL', True): 'A105'}
HAGEN_SIDE_PANELS = {False: ('A110', 'A111'), True: ('A112', 'A113')}

# (words in the option, parts, label). Checked in order; the first match wins.
HAGEN_ACCESSORIES = (
    (('wide box', 'widebox'), [('A115', 1.0)], 'Widebox'),
    (('front child seat', 'child seat front', 'kindersitz vorne'), [('A125', 1.0)], 'Child seat, front'),
    (('child seat', 'kindersitz'), [('A124', 1.0)], 'Child seat, rear'),
    (('canopy', 'verdeck', 'regenverdeck'), [('A151', 2.0)], 'Canopy holder clamps'),
    (('rack adapter', 'gepäckträgeradapter', 'gepacktrageradapter'), [('A130', 1.0)], 'Rack adapter'),
    (('ergotec', 'up and down'), [('A118', 1.0)], 'Ergotec up-and-down adapter'),
)

# Standalone accessory products on hagenbikes.com carry their own SKUs.
SKU_ALIASES = {'E00302': 'A115', 'E00303': 'A124'}
SKU_EXTRAS = {'E00312': [['A151', 2.0, 'Canopy holder clamps']]}

# Paints tab of the inventory workbook. Values marked "?" there are kept, the
# report lists them as unconfirmed.
RAL = {
    'shiny black': '9005', 'black': '9005', 'schwarz': '9005',
    'white': '9003', 'weiß': '9003', 'weiss': '9003',
    'yellow': '1023', 'gelb': '1023',
    'dark blue': '5026', 'navy blue': '5026',
    'metallic green': '6036', 'green': '6036',
    'cherry red': '3032', 'red': '3032',
    'moon grey': '9022', 'light grey': '9022', 'grey': '9022',
    'metallic copper': '8029',
}
NO_RAL = ('matte black', 'matt black', 'anthracite', 'light blue', 'custom', 'individuell')
RAL_IN_TEXT = re.compile(r'\bRAL\s*[:#]?\s*((?=[0-9A-Za-z-]*\d)[0-9A-Za-z][0-9A-Za-z-]{1,14})', re.I)
PRICE_SUFFIX = re.compile(r'\s*\(\+[^)]*\)')
OPTION_IN_TEXT = re.compile(r'(?:^|\n)\s*(?:\d{1,2}\s+)?([^\n:]{2,40}):\s*([^\n]+)')


def _clean(text):
    text = html.unescape(str(text or ''))
    text = re.sub(r'<\s*br\s*/?>|</p>|</li>|</div>', '\n', text, flags=re.I)
    text = re.sub(r'<[^>]+>', ' ', text)
    return text.replace('\u00a0', ' ').replace('\r', '')


def option_pairs(item):
    """(label, value) pairs from a Woo order line or variation, in shop order."""
    pairs = []
    for meta in item.get('meta_data') or []:
        if not isinstance(meta, dict):
            continue
        key = str(meta.get('key') or '')
        if key.startswith('_'):
            continue
        label = _clean(meta.get('display_key') or key).strip()
        value = _clean(meta.get('display_value') if meta.get('display_value') not in (None, '') else meta.get('value'))
        nested = OPTION_IN_TEXT.findall('\n' + value)
        if nested and ('\n' in value.strip() or label.lower() in ('configuration', 'konfiguration', '')):
            pairs += [(left.strip(), right.strip()) for left, right in nested]
        elif label or value.strip():
            pairs.append((label, value.strip()))
    for attribute in item.get('attributes') or []:
        if isinstance(attribute, dict):
            pairs.append((str(attribute.get('name') or ''), str(attribute.get('option') or attribute.get('value') or '')))
    return pairs


def _kind(label):
    label = re.sub(r'^\s*\d{1,2}\s+', '', label.lower()).replace('pa_', '')
    for kind, words in (
        ('size', ('size', 'größe', 'grosse', 'bike-frame', 'rahmengröße')),
        ('colour', ('colour', 'color', 'farbe', 'farben')),
        ('material', ('carbon', 'package', 'paket')),
        ('rack', ('luggage', 'gepäckträger', 'rack')),
        ('pedals', ('pedal',)),
        ('type', ('type', 'typ', 'antriebsart')),
        ('gearing', ('gearing', 'drivetrain', 'gears', 'schaltung', 'antrieb')),
        ('handlebar', ('handlebar', 'lenker')),
        ('panels', ('panel', 'floor plate', 'bodenplatte')),
        ('accessory', ('accessor', 'zubehör', 'zubehor', 'extra', 'option')),
    ):
        if any(word in label for word in words):
            return kind
    return 'other'


def ral_for(colour, note=''):
    """'RAL 1023', 'RAL 570-M (customer note)' or '' when the Paints tab has none."""
    value = colour.lower()
    value = PRICE_SUFFIX.sub('', value).strip()
    if any(word in value for word in ('custom', 'individuell')):
        found = RAL_IN_TEXT.search(note or '') or RAL_IN_TEXT.search(colour)
        return f'RAL {found.group(1).strip()} (customer note)' if found else 'RAL: see customer note'
    found = RAL_IN_TEXT.search(colour)
    if found:
        return f'RAL {found.group(1).strip()}'
    if any(word in value for word in NO_RAL):
        return ''
    for name in sorted(RAL, key=len, reverse=True):
        if name in value.replace('-', ' '):
            return f'RAL {RAL[name]}'
    return ''


def _new_build(code):
    return {'code': code, 'replace': [], 'remove': [], 'add': [], 'notes': [], 'warnings': []}


def resolve(name, pairs, note='', sku=''):
    """Build for one product name + option pairs. code is None when nothing matches."""
    title = _clean(name).lower()
    sku = (sku or '').strip()
    if sku in SKU_ALIASES:
        build = _new_build(SKU_ALIASES[sku])
        build['notes'].append(f'{name} (webshop SKU {sku})')
        return build
    if sku in SKU_EXTRAS:
        build = _new_build(None)
        build['add'] = [list(row) for row in SKU_EXTRAS[sku]]
        return build
    if any(pattern.search(title) for pattern, _code in BLURBY_MODELS):
        return _resolve_blurby(name, title, pairs, note)
    model = next((code for word, code in HAGEN_MODELS if word in title), None)
    if model:
        return _resolve_hagen(name, model, pairs, note)
    return _new_build(None)


def _option_note(pairs):
    return [f'{label}: {value}' for label, value in pairs if label or value]


def _resolve_blurby(name, title, pairs, note):
    code = next(code for pattern, code in BLURBY_MODELS if pattern.search(title))
    build = _new_build(code)
    size = 'W' if BLURBY_STEP_THROUGH_MODEL.search(title) else None
    colour = ''
    for label, value in pairs:
        kind, text = _kind(label), value.lower()
        if kind == 'size' and size != 'W':
            if 'step' in text or re.match(r'\s*(st|s|w)\b|\s*(s|w)-frame', text):
                size = 'W'
            elif re.match(r'\s*m\b|\s*m-frame', text):
                size = 'M'
            elif re.match(r'\s*l\b|\s*l-frame', text):
                size = 'L'
        elif kind == 'colour':
            colour = value
        elif kind == 'material' and 'carbon' in text and not text.startswith(('alu', 'aluminium')):
            build['replace'] += [list(pair) for pair in BLURBY_CARBON]
            build['notes'].append('Carbon package: carbon fork A57, carbon handlebar A30, carbon seatpost')
            build['warnings'].append('Carbon seatpost has no part code yet: take it from the shelf by hand.')
        elif kind == 'rack' and text.startswith(('with', 'mit', 'yes')) and 'without' not in text:
            build['notes'].append('Luggage rack: fit a Blurby rear rack')
            build['warnings'].append('Blurby luggage rack has no part code yet (A152/A153 are VanMoof racks).')
        elif kind == 'pedals' and text:
            build['notes'].append(f'Pedals: {value}')
            build['warnings'].append('Pedals have no part code yet: pack the chosen pedals by hand.')
    size = size or 'L'
    frame, guard, label = BLURBY_SIZES[size]
    if size != 'L':
        build['replace'] += [[BLURBY_BASE_FRAME, frame], [BLURBY_BASE_REAR_GUARD, guard]]
    build['notes'].insert(0, f'Size: {label} ({frame}, rear mudguard {guard} if fitted)')
    if colour:
        ral = ral_for(colour, note)
        build['notes'].insert(1, f'Frame colour: {colour}' + (f' — {ral}' if ral else ' — RAL not on the Paints tab'))
    build['notes'] += ['Website options: ' + '; '.join(_option_note(pairs))] if pairs else []
    return build


def _resolve_hagen(name, model, pairs, note):
    text = ' '.join(f'{label} {value}' for label, value in pairs).lower() + ' ' + _clean(name).lower()
    types = [value.lower() for label, value in pairs if _kind(label) == 'type']
    type_text = ' '.join(types) or text
    frameset = any(word in type_text for word in FRAMESET_WORDS)
    non_electric = any(word in type_text for word in NON_ELECTRIC_WORDS)
    electric = not non_electric and any(word in type_text for word in ELECTRIC_WORDS)
    if frameset:
        code = HAGEN_FRAMESETS[model]
    elif non_electric or electric:
        code = HAGEN_BIKES[(model, electric)]
    else:
        return _new_build(None)
    build = _new_build(code)
    grey = any(
        ('grey' in value.lower() or 'gray' in value.lower() or 'grau' in value.lower())
        and (_kind(label) in ('panels', 'accessory') or 'panel' in value.lower())
        for label, value in pairs
    )
    for label, value in pairs:
        kind, text_value = _kind(label), value.lower()
        if kind == 'colour':
            ral = ral_for(value, note)
            build['notes'].append(f'Frame colour: {PRICE_SUFFIX.sub("", value)}' + (f' — {ral}' if ral else ''))
        elif kind == 'gearing' and not frameset:
            key = next((key for key in ('nexus', 'alfine', 'deore') if key in text_value), None)
            if key is None and ('10' in text_value or 'e10' in text_value):
                key = 'deore'
            if key:
                label_text, replace, remove = HAGEN_DRIVETRAINS[key]
                build['replace'] += [list(pair) for pair in replace]
                build['remove'] += remove
                build['notes'].append(f'Drivetrain: {label_text}')
                if key == 'alfine' and electric:
                    build['warnings'].append('Alfine 8-speed is offered for non-electric bikes only: confirm with the office.')
                if key == 'alfine' and 'belt' in text_value:
                    build['warnings'].append('Alfine is ordered as a belt drive: belt and sprockets are not in the recipe.')
            else:
                build['warnings'].append(f'Unknown drivetrain "{value}": build the base 10-speed and check with the office.')
        elif kind == 'handlebar' and not frameset:
            key = next((key for key in HAGEN_HANDLEBARS if key in text_value), None)
            if key:
                label_text, replace = HAGEN_HANDLEBARS[key]
                build['replace'] += [list(pair) for pair in replace]
                build['notes'].append(f'Handlebar: {label_text}')
            else:
                build['warnings'].append(f'Unknown handlebar "{value}".')
        elif kind == 'accessory':
            _hagen_accessory(build, model, value, frameset, grey)
    if grey:
        build['notes'].append('Panels: grey')
        if not frameset:
            build['replace'] += [list(pair) for pair in HAGEN_GREY_PANELS]
    if not frameset and electric:
        build['notes'].insert(0, 'Type: 90 Nm Brose mid-motor')
    elif not frameset:
        build['notes'].insert(0, 'Type: non-electric')
    else:
        build['notes'].insert(0, 'Type: frame set (non-electric frame)')
    build['notes'].append('Website options: ' + '; '.join(_option_note(pairs)))
    if 'custom' in text and note:
        build['notes'].append(f'Customer note: {note.strip()}')
    return build


def _hagen_accessory(build, model, value, frameset, grey):
    text = PRICE_SUFFIX.sub('', value).strip()
    lower = text.lower()
    if 'side panel' in lower or 'seitenteil' in lower:
        if model == 'FLAGSHIP':
            if frameset:
                right, left = HAGEN_SIDE_PANELS[grey]
                build['add'] += [[right, 1.0, 'Side panel right'], [left, 1.0, 'Side panel left']]
            build['notes'].append('Accessory: side panels' + (' (grey)' if grey else ' (black)'))
        else:
            build['notes'].append('Accessory: side panels')
            build['warnings'].append('XL side panels have no part code yet: nothing is deducted for them.')
        return
    if 'floor plate' in lower or 'bodenplatte' in lower:
        if frameset:
            build['add'].append([HAGEN_FLOOR_PLATE[(model, grey)], 1.0, 'Floor plate'])
        build['notes'].append('Accessory: floor plate' + (' (grey)' if grey else ''))
        return
    for words, parts, label in HAGEN_ACCESSORIES:
        if any(word in lower for word in words):
            build['add'] += [[part, qty, label] for part, qty in parts]
            build['notes'].append(f'Accessory: {text} ({", ".join(f"{part}×{qty:g}" for part, qty in parts)})')
            return
    if text:
        build['notes'].append(f'Accessory: {text}')
        build['warnings'].append(f'No part code for accessory "{text}": nothing is deducted for it.')


def resolve_line(item, customer_note=''):
    return resolve(item.get('name') or '', option_pairs(item), customer_note, item.get('sku') or '')


def resolve_variation(parent_name, variation):
    """Build for one variation of a variable product (Woo REST v3 shape)."""
    return resolve(parent_name, option_pairs(variation), '', variation.get('sku') or '')


def has_changes(build):
    return bool(build and (build.get('replace') or build.get('remove') or build.get('add')))
