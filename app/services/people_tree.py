"""Generate people org-chart as PNG image (base64).

4-level top-down org chart:
  L0: Project code (name prefix before space/dash)
  L1: Topic nodes (name suffix) + PM name below
  L2: Role cards (project_role without parentheses), horizontal branch from topic
  L3: Person names stacked vertically inside role card, note in gray

Small topics stacked vertically sharing a column.
Connectors are fold-lines (折线).
High-DPI: internal scale=3, saved at 216 dpi, CSS width:100% for crisp display.
"""
import base64
import io
import math
import re
from collections import OrderedDict

from PIL import Image, ImageDraw, ImageFont

# ── Colors ──
_PALETTES = [
    # Cold/muted tones, small color diff, light/transparent feel
    # (hdr_bg, hdr_fg, role_hdr_bg, card_text)
    ((100, 140, 190), (255, 255, 255), (180, 205, 230), (60, 85, 120)),   # steel blue
    ((95, 155, 155),  (255, 255, 255), (175, 210, 210), (55, 100, 100)),   # teal
    ((120, 130, 175), (255, 255, 255), (190, 195, 220), (70, 75, 120)),    # lavender
    ((130, 150, 140), (255, 255, 255), (195, 210, 200), (75, 95, 85)),     # sage
    ((140, 135, 165), (255, 255, 255), (200, 198, 218), (85, 80, 115)),    # mauve
    ((110, 150, 170), (255, 255, 255), (185, 210, 220), (65, 100, 120)),   # slate cyan
]
C_BG = (255, 255, 255)
C_ROOT_BG = (70, 100, 145)
C_ROOT_FG = (255, 255, 255)
C_TEXT = (50, 55, 65)
C_MUTED = (158, 168, 184)
C_LINE = (200, 208, 218)
C_CROSS = (80, 125, 180)
C_CARD_BORDER = (210, 215, 225)  # gray frame for role cards


def _get_font(size):
    for name in [
        '/System/Library/Fonts/PingFang.ttc',
        '/System/Library/Fonts/STHeiti Light.ttc',
        'C:/Windows/Fonts/msyh.ttc',
        '/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.ttc',
        '/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc',
    ]:
        try:
            return ImageFont.truetype(name, size)
        except (OSError, IOError):
            continue
    return ImageFont.load_default()


# ── Grid optimizer: minimise bounding-box area ──
def _grid_dims(n, c, widths, heights, gap):
    """Compute (total_w, total_h) for C columns with N items."""
    rows = math.ceil(n / c)
    total_w = gap * max(c - 1, 0)
    for col in range(c):
        col_max = 0
        for r in range(rows):
            idx = r * c + col
            if idx < n:
                col_max = max(col_max, widths[idx])
        total_w += col_max

    total_h = gap * max(rows - 1, 0)
    for r in range(rows):
        row_max = 0
        for col in range(c):
            idx = r * c + col
            if idx < n:
                row_max = max(row_max, heights[idx])
        total_h += row_max
    return total_w, total_h


def _best_cols(widths, heights, gap=0, max_width=0, prefer_wide=True):
    """Find column count C that minimises W(C)×H(C) for N items.

    Improvements over naive ceil(sqrt):
    - Respects max_width constraint (skip layouts exceeding it)
    - prefer_wide: on ties (within 5%), prefer more columns (wider/shorter)
    - Items are pre-sorted by width descending so wide items share columns
      (reduces max-column-width waste)
    """
    n = len(widths)
    if n <= 1:
        return 1

    # Sort indices by width descending → wide items distribute across columns
    order = sorted(range(n), key=lambda i: -widths[i])
    sorted_w = [widths[i] for i in order]
    sorted_h = [heights[i] for i in order]

    best_c, best_score = 1, float('inf')
    for c in range(1, n + 1):
        tw, th = _grid_dims(n, c, sorted_w, sorted_h, gap)

        if max_width and tw > max_width:
            continue

        area = tw * th
        # Score = area × aspect penalty
        ratio = tw / max(th, 1)
        # Ideal ratio derived from average item shape:
        #   items wider than tall → ideal layout wider (ratio ~2-4)
        #   items taller than wide → ideal layout more square (ratio ~1-2)
        avg_w = sum(sorted_w) / n
        avg_h = sum(sorted_h) / n
        item_ratio = avg_w / max(avg_h, 1)
        if prefer_wide:
            ideal = max(1.5, min(item_ratio * 2, 4.0))
        else:
            ideal = max(0.8, min(item_ratio, 2.0))
        log_dev = math.log(max(ratio, 0.01) / ideal)
        ratio_penalty = 1 + log_dev * log_dev
        score = area * ratio_penalty

        if score < best_score:
            best_score = score
            best_c = c

    return best_c


# ── Measuring helper ──
_measure_img = None
_measure_draw = None


def _get_measure():
    global _measure_img, _measure_draw
    if _measure_draw is None:
        _measure_img = Image.new('RGB', (1, 1))
        _measure_draw = ImageDraw.Draw(_measure_img)
    return _measure_draw


def _tw(text, font):
    """Text width."""
    if not text:
        return 0
    d = _get_measure()
    bbox = d.textbbox((0, 0), text, font=font)
    return bbox[2] - bbox[0]


# ── Main entry ──
def generate_people_tree_image(tree, project_name='', width=None):
    """Generate org-chart PNG, return base64 string."""
    if not tree:
        return None

    S = 3  # scale factor for high-DPI

    # ── Fonts (all sizes × S) ──
    F_ROOT = _get_font(11 * S)
    F_TOPIC = _get_font(8 * S)
    F_PM = _get_font(8 * S)
    F_ROLE = _get_font(8 * S)
    F_PERSON = _get_font(8 * S)
    F_NOTE = _get_font(6 * S)

    # ── Layout constants (all × S) ──
    PAD = 6 * S           # image edge padding
    NPX = 4 * S           # node inner horizontal padding
    NPY = 2 * S           # node inner vertical padding
    GAP = 4 * S            # gap between sibling nodes
    LVL_GAP = 12 * S      # vertical gap between levels
    PERSON_H = 11 * S     # height per person line
    ROLE_HDR_H = 11 * S   # role card header height
    ROOT_H = 22 * S       # root node height

    # ── Parse root code ──
    root_name = project_name or '项目'
    m = re.match(r'^(\S+?)[\s\-](.+)$', root_name)
    root_code = m.group(1) if m else root_name

    # ── Cross-project detection ──
    person_projs = {}
    for pn, roles in tree.items():
        for persons in roles.values():
            for p in persons:
                person_projs.setdefault(p['name'], set()).add(pn)
    cross_people = {n for n, ps in person_projs.items() if len(ps) > 1}

    # ════════════════════════════════════════════════════════════════
    # PASS 1: Build topic data + measure widths bottom-up
    # ════════════════════════════════════════════════════════════════
    topics = []
    for pi, (proj_name, roles) in enumerate(tree.items()):
        m2 = re.match(r'^(\S+?)[\s\-](.+)$', proj_name)
        tname = m2.group(2) if m2 else proj_name

        # Separate PM from other roles
        pm_name = ''
        non_pm_roles = OrderedDict()
        for rname, persons in roles.items():
            if rname.upper() == 'PM':
                if persons:
                    pm_name = persons[0]['name']
            else:
                non_pm_roles[rname] = persons

        # Measure each role card (grid layout via _best_cols)
        role_cards = []
        for rname, persons in non_pm_roles.items():
            n = len(persons)

            role_label_w = _tw(rname, F_ROLE)

            # Measure each person's text width
            p_widths = []
            for p in persons:
                pw = _tw(p['name'], F_PERSON)
                if p.get('note'):
                    pw += _tw(f' ({p["note"]})', F_NOTE) + 2 * S
                p_widths.append(pw + NPX)

            p_heights = [PERSON_H] * n
            col_gap = 4 * S
            cols = _best_cols(p_widths, p_heights, col_gap)
            rows = math.ceil(n / cols)

            # Calculate actual card width from grid
            grid_w = col_gap * (cols - 1)
            for col in range(cols):
                col_max = 0
                for r in range(rows):
                    idx = r * cols + col
                    if idx < n:
                        col_max = max(col_max, p_widths[idx])
                grid_w += col_max

            card_w = max(role_label_w + NPX * 2, grid_w + NPX * 2)
            card_h = ROLE_HDR_H + rows * PERSON_H + 1 * S

            role_cards.append({
                'name': rname, 'persons': persons,
                'w': card_w, 'h': card_h,
                'cols': cols, 'rows': rows,
                'p_widths': p_widths, 'col_gap': col_gap,
            })

        # Topic header size
        topic_name_w = _tw(tname, F_TOPIC)
        pm_text_w = _tw(pm_name, F_PM) if pm_name else 0
        topic_hdr_w = max(topic_name_w, pm_text_w) + NPX * 2
        topic_hdr_h = NPY + 10 * S + (10 * S if pm_name else 0) + NPY

        # Apply _best_cols to role cards within this topic
        if role_cards:
            rc_widths = [rc['w'] for rc in role_cards]
            rc_heights = [rc['h'] for rc in role_cards]
            card_grid_cols = _best_cols(rc_widths, rc_heights, GAP)
        else:
            card_grid_cols = 1
        card_grid_rows = math.ceil(len(role_cards) / card_grid_cols) if role_cards else 0

        # Compute topic body size from card grid
        cards_grid_w = GAP * max(card_grid_cols - 1, 0)
        for col in range(card_grid_cols):
            col_max = 0
            for r in range(card_grid_rows):
                idx = r * card_grid_cols + col
                if idx < len(role_cards):
                    col_max = max(col_max, role_cards[idx]['w'])
            cards_grid_w += col_max

        cards_grid_h = GAP * max(card_grid_rows - 1, 0)
        for r in range(card_grid_rows):
            row_max = 0
            for col in range(card_grid_cols):
                idx = r * card_grid_cols + col
                if idx < len(role_cards):
                    row_max = max(row_max, role_cards[idx]['h'])
            cards_grid_h += row_max

        topic_total_w = max(topic_hdr_w, cards_grid_w)

        count = sum(len(ps) for ps in roles.values())

        topics.append({
            'name': tname, 'pm': pm_name,
            'cards': role_cards, 'count': count, 'pi': pi,
            'w': topic_total_w, 'hdr_w': topic_hdr_w, 'hdr_h': topic_hdr_h,
            'cards_grid_cols': card_grid_cols, 'cards_grid_rows': card_grid_rows,
            'cards_grid_w': cards_grid_w, 'cards_grid_h': cards_grid_h,
        })

    # ════════════════════════════════════════════════════════════════
    # PASS 2: Sort, apply _best_cols to topics, build columns
    # ════════════════════════════════════════════════════════════════
    topics.sort(key=lambda t: -t['count'])

    # Total topic sizes (header + card grid)
    for t in topics:
        t['total_h'] = t['hdr_h'] + LVL_GAP + t['cards_grid_h']

    MAX_W = (width or 1200) * S  # cap image width
    topic_widths = [t['w'] for t in topics]
    topic_heights = [t['total_h'] for t in topics]
    topic_grid_cols = _best_cols(topic_widths, topic_heights, GAP, max_width=MAX_W)

    # Greedy column packing: assign each topic to best column
    # When heights are similar (within 15%), prefer column with more topics (reinforce stacking)
    col_data = [{'topics': [], 'h': 0} for _ in range(topic_grid_cols)]
    for t in topics:
        # Find column with min height
        min_h = min(c['h'] for c in col_data)
        threshold = max(min_h * 0.15, LVL_GAP * 2)  # 15% or at least 2 gaps
        candidates = [i for i, c in enumerate(col_data) if c['h'] <= min_h + threshold]
        # Among candidates, prefer the one with most topics (reinforce stacking)
        best = max(candidates, key=lambda i: len(col_data[i]['topics']))
        col_data[best]['topics'].append(t)
        col_data[best]['h'] += t['total_h'] + LVL_GAP

    columns = []
    for cd in col_data:
        if cd['topics']:
            col_w = max(t['w'] for t in cd['topics'])
            columns.append({
                'topics': cd['topics'],
                'w': col_w,
            })

    if not columns:
        return None

    # ════════════════════════════════════════════════════════════════
    # PASS 3: Calculate image size
    # ════════════════════════════════════════════════════════════════
    total_cols_w = sum(c['w'] for c in columns) + GAP * (len(columns) - 1)
    W = max(total_cols_w + PAD * 2, 400 * S)
    if width:
        W = max(W, width * S)

    y_root = PAD
    y_topic = y_root + ROOT_H + LVL_GAP

    # Column height = sum of stacked topic total_h + gaps
    max_col_h = 0
    for col in columns:
        col_h = sum(t['total_h'] for t in col['topics']) + LVL_GAP * max(len(col['topics']) - 1, 0)
        max_col_h = max(max_col_h, col_h)

    H = y_topic + max_col_h + PAD

    # ════════════════════════════════════════════════════════════════
    # PASS 4: Position columns horizontally
    # ════════════════════════════════════════════════════════════════
    extra = W - PAD * 2 - total_cols_w
    col_gap = max(extra // max(len(columns) + 1, 1), GAP)

    x_cursor = PAD + col_gap
    for col in columns:
        col['x'] = x_cursor
        col['cx'] = x_cursor + col['w'] // 2
        x_cursor += col['w'] + col_gap

    # ════════════════════════════════════════════════════════════════
    # DRAW
    # ════════════════════════════════════════════════════════════════
    img = Image.new('RGB', (W, H), C_BG)
    draw = ImageDraw.Draw(img)

    def _fold_line(px, py_bot, child_cxs, cy_top, thick=2):
        """Draw fold-line connector from parent to children."""
        mid = (py_bot + cy_top) // 2
        draw.line([(px, py_bot), (px, mid)], fill=C_LINE, width=thick * S)
        if child_cxs:
            draw.line([(min(child_cxs), mid), (max(child_cxs), mid)],
                      fill=C_LINE, width=thick * S)
            for cx in child_cxs:
                draw.line([(cx, mid), (cx, cy_top)], fill=C_LINE, width=thick * S)

    # ── L0: Root ──
    root_cx = W // 2
    root_text = root_code
    rtw = _tw(root_text, F_ROOT)
    rw = rtw + NPX * 2
    rx = root_cx - rw // 2
    draw.rounded_rectangle([(rx, y_root), (rx + rw, y_root + ROOT_H)], radius=2*S, fill=C_ROOT_BG)
    draw.text((root_cx - rtw // 2, y_root + 6 * S), root_text,
              fill=C_ROOT_FG, font=F_ROOT)

    # Root → columns connector
    _fold_line(root_cx, y_root + ROOT_H, [c['cx'] for c in columns], y_topic)

    # ── L1–L2–L3: Topics ──
    for col in columns:
        for si, topic in enumerate(col['topics']):
            pal = _PALETTES[topic['pi'] % len(_PALETTES)]
            hdr_bg, hdr_fg, role_hdr_bg, card_text = pal

            # Stacking offset: sum of previous topics' heights
            ty = y_topic
            for prev_i in range(si):
                ty += col['topics'][prev_i]['total_h'] + LVL_GAP
            topic_cx = col['cx']

            # Stacking connector (from previous topic's bottom)
            if si > 0:
                prev_bot = ty - LVL_GAP
                draw.line([(topic_cx, prev_bot), (topic_cx, ty)],
                          fill=C_LINE, width=S)

            # ── Topic header node ──
            thw = col['w']
            thh = topic['hdr_h']
            tx = topic_cx - thw // 2

            draw.rounded_rectangle([(tx, ty), (tx + thw, ty + thh)], radius=2*S, fill=hdr_bg)

            # Topic name (centered)
            tnw = _tw(topic['name'], F_TOPIC)
            draw.text((topic_cx - tnw // 2, ty + NPY),
                      topic['name'], fill=hdr_fg, font=F_TOPIC)

            # PM name (centered, below topic name)
            if topic['pm']:
                pmw = _tw(topic['pm'], F_PM)
                draw.text((topic_cx - pmw // 2, ty + NPY + 10 * S),
                          topic['pm'], fill=hdr_fg, font=F_PM)

            # ── Role cards (grid layout) ──
            cards = topic['cards']
            if not cards:
                continue

            cy_base = ty + thh + LVL_GAP  # cards area top y
            gc = topic['cards_grid_cols']
            gr = topic['cards_grid_rows']

            # Compute column widths and row heights for card grid
            g_col_widths = []
            for col_i in range(gc):
                cw = 0
                for r_i in range(gr):
                    idx = r_i * gc + col_i
                    if idx < len(cards):
                        cw = max(cw, cards[idx]['w'])
                g_col_widths.append(cw)

            g_row_heights = []
            for r_i in range(gr):
                rh = 0
                for col_i in range(gc):
                    idx = r_i * gc + col_i
                    if idx < len(cards):
                        rh = max(rh, cards[idx]['h'])
                g_row_heights.append(rh)

            total_cards_w = sum(g_col_widths) + GAP * max(gc - 1, 0)
            cx_grid_start = topic_cx - total_cards_w // 2

            # Position and draw each card
            card_positions = []  # (x, y, cx_mid) for each card
            x_offsets = []
            cur_x = cx_grid_start
            for col_i in range(gc):
                x_offsets.append(cur_x)
                cur_x += g_col_widths[col_i] + GAP

            y_offsets = []
            cur_y = cy_base
            for r_i in range(gr):
                y_offsets.append(cur_y)
                cur_y += g_row_heights[r_i] + GAP

            for ci, rc in enumerate(cards):
                gc_i = ci % gc
                gr_i = ci // gc
                cx_card = x_offsets[gc_i]
                cy_card = y_offsets[gr_i]
                cx_mid = cx_card + rc['w'] // 2
                card_positions.append((cx_card, cy_card, cx_mid))

            # Topic → cards connector
            # Collect all card center-x positions and draw fold line
            all_cxs = [cp[2] for cp in card_positions]
            _fold_line(topic_cx, ty + thh, all_cxs, cy_base, thick=1)
            # For multi-row grids, add vertical drops from the horizontal bar to each card
            if gr > 1:
                mid_y = (ty + thh + cy_base) // 2  # horizontal bar y from _fold_line
                for ci, (_cx_card_pos, cy_card_pos, cx_mid_pos) in enumerate(card_positions):
                    # _fold_line already drew drop to first-row cards (cy_base)
                    gr_i = ci // gc
                    if gr_i > 0:
                        # Cards in later rows need vertical line from horizontal bar
                        draw.line([(cx_mid_pos, mid_y), (cx_mid_pos, cy_card_pos)],
                                  fill=C_LINE, width=S)

            # Draw each card
            for ci, rc in enumerate(cards):
                cx_card, cy_card, cx_mid = card_positions[ci]

                # Card: gray border, white body
                draw.rounded_rectangle(
                    [(cx_card, cy_card), (cx_card + rc['w'], cy_card + rc['h'])],
                    radius=2*S, fill=C_BG, outline=C_CARD_BORDER, width=S)

                # Role header: same color family as topic
                draw.rounded_rectangle(
                    [(cx_card, cy_card), (cx_card + rc['w'], cy_card + ROLE_HDR_H)],
                    radius=2*S, fill=role_hdr_bg)
                # Fill bottom corners of header (overlap with card body)
                draw.rectangle(
                    [(cx_card, cy_card + ROLE_HDR_H - 2*S),
                     (cx_card + rc['w'], cy_card + ROLE_HDR_H)],
                    fill=role_hdr_bg)

                # Role label (centered in header)
                rlw = _tw(rc['name'], F_ROLE)
                draw.text((cx_mid - rlw // 2, cy_card + 1 * S),
                          rc['name'], fill=card_text, font=F_ROLE)

                # Person names (grid layout in card body)
                p_cols = rc.get('cols', 1)
                p_col_gap = rc.get('col_gap', 4 * S)
                p_widths = rc.get('p_widths', [])

                # Compute person column x-offsets and widths
                p_col_xs = []
                p_col_widths = []
                p_rows = math.ceil(len(rc['persons']) / p_cols) if p_cols else 0
                pcx = cx_card + NPX
                for pc in range(p_cols):
                    p_col_xs.append(pcx)
                    col_max_w = 0
                    for pr in range(p_rows):
                        pidx = pr * p_cols + pc
                        if pidx < len(p_widths):
                            col_max_w = max(col_max_w, p_widths[pidx])
                    p_col_widths.append(col_max_w)
                    pcx += col_max_w + p_col_gap

                for idx, p in enumerate(rc['persons']):
                    pc_i = idx % p_cols
                    pr_i = idx // p_cols
                    col_x = p_col_xs[pc_i] if pc_i < len(p_col_xs) else cx_card + NPX
                    col_w = p_col_widths[pc_i] if pc_i < len(p_col_widths) else rc['w']
                    py = cy_card + ROLE_HDR_H + 1 * S + pr_i * PERSON_H

                    name = p['name']
                    is_cross = name in cross_people
                    nc = C_CROSS if is_cross else C_TEXT

                    # Calculate total text width for centering
                    name_w = _tw(name, F_PERSON)
                    note_text = f'({p["note"]})' if p.get('note') else ''
                    note_w = (_tw(note_text, F_NOTE) + 2 * S) if note_text else 0
                    total_text_w = name_w + note_w
                    px = col_x + (col_w - total_text_w) // 2

                    draw.text((px, py), name, fill=nc, font=F_PERSON)

                    if note_text:
                        draw.text((px + name_w + 2 * S, py + 2 * S),
                                  note_text, fill=C_MUTED, font=F_NOTE)

    # ── Crop & export ──
    img = img.crop((0, 0, W, H))

    buf = io.BytesIO()
    dpi = 72 * S  # 216 dpi
    img.save(buf, format='PNG', optimize=True, dpi=(dpi, dpi))
    return base64.b64encode(buf.getvalue()).decode('ascii')
