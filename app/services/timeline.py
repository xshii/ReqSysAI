"""Generate milestone timeline as PNG image (base64), with caching."""
import base64
import hashlib
import io
from datetime import date

from PIL import Image, ImageDraw, ImageFont

_cache = {}  # in-memory cache: hash → base64 (cleared on app restart)


def _cache_key(milestones, today, width):
    """Generate cache key from milestone data."""
    parts = []
    for m in sorted(milestones, key=lambda x: str(x.get('due_date', ''))):
        parts.append(f"{m.get('name')}|{m.get('due_date')}|{m.get('status')}")
    raw = f"{today}|{width}|{'||'.join(parts)}"
    return hashlib.md5(raw.encode()).hexdigest()  # noqa: S324


# Colors
COLOR_DONE = (25, 135, 84)       # green
COLOR_OVERDUE = (220, 53, 69)    # red
COLOR_ACTIVE = (30, 58, 95)      # dark blue
COLOR_AXIS = (30, 58, 95)
COLOR_TODAY = (220, 53, 69)
COLOR_BG = (255, 255, 255)
COLOR_TEXT = (100, 116, 139)     # gray
COLOR_LABEL = (30, 58, 95)


def _get_font(size):
    """Try system CJK fonts, fallback to default."""
    for name in [
        '/System/Library/Fonts/PingFang.ttc',       # macOS
        '/System/Library/Fonts/STHeiti Light.ttc',
        'C:/Windows/Fonts/msyh.ttc',                # Windows
        'C:/Windows/Fonts/simhei.ttf',
        '/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.ttc',  # Linux
        '/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc',
    ]:
        try:
            return ImageFont.truetype(name, size)
        except (OSError, IOError):
            continue
    return ImageFont.load_default()


def generate_timeline_image(milestones, today=None, width=760):
    """Generate timeline PNG, return base64 string (cached).

    milestones: list of dicts with keys: name, due_date (date), status ('active'/'completed')
    """
    today = today or date.today()
    key = _cache_key(milestones, today, width)
    if key in _cache:
        return _cache[key]
    if not milestones or not any(m.get('due_date') for m in milestones):
        return None

    today = today or date.today()
    scale = 3  # High DPI
    font_name = _get_font(12 * scale)
    font_date = _get_font(10 * scale)
    font_today = _get_font(11 * scale)

    # Layout constants (scaled)
    pad_x = 40 * scale
    pad_top = 30 * scale
    axis_y = pad_top + 20 * scale
    marker_h = 10 * scale
    width = width * scale
    usable_w = width - 2 * pad_x

    # Filter milestones with dates, sort by date
    ms_with_date = sorted([m for m in milestones if m.get('due_date')], key=lambda m: m['due_date'])
    if not ms_with_date:
        return None

    min_date = ms_with_date[0]['due_date']
    max_date = ms_with_date[-1]['due_date']
    date_range = max((max_date - min_date).days, 1)

    # Calculate rows needed (check label overlap)
    positions = []
    for m in ms_with_date:
        x = pad_x + int((m['due_date'] - min_date).days / date_range * usable_w)
        positions.append(x)

    # Stagger labels to avoid overlap: alternate top/bottom
    rows = [0] * len(ms_with_date)  # 0=below axis, 1=above axis
    for i in range(1, len(positions)):
        if positions[i] - positions[i - 1] < 70 * scale:
            rows[i] = 1 - rows[i - 1]

    height = axis_y + 80 * scale  # enough for two rows of labels
    img = Image.new('RGB', (width, height), COLOR_BG)
    draw = ImageDraw.Draw(img)

    # Axis line
    s = scale
    draw.line([(pad_x, axis_y), (width - pad_x, axis_y)], fill=COLOR_AXIS, width=2 * s)

    # Today marker
    today_days = (today - min_date).days
    if 0 <= today_days <= date_range:
        tx = pad_x + int(today_days / date_range * usable_w)
        draw.text((tx - 5 * s, axis_y - 18 * s), '★', fill=COLOR_TODAY, font=font_today)
        draw.text((tx + 8 * s, axis_y - 18 * s), '今天', fill=COLOR_TODAY, font=font_date)
        for dy in range(axis_y - 2 * s, axis_y + 50 * s, 4 * s):
            draw.line([(tx, dy), (tx, dy + 2 * s)], fill=(220, 53, 69, 80), width=s)

    # Milestones
    tri = 5 * s  # triangle half-width
    for i, m in enumerate(ms_with_date):
        x = positions[i]
        color = COLOR_ACTIVE

        if rows[i] == 0:
            draw.polygon([(x, axis_y + 2 * s), (x - tri, axis_y + marker_h + 2 * s), (x + tri, axis_y + marker_h + 2 * s)], fill=color)
            ty = axis_y + marker_h + 6 * s
        else:
            draw.polygon([(x, axis_y - 2 * s), (x - tri, axis_y - marker_h - 2 * s), (x + tri, axis_y - marker_h - 2 * s)], fill=color)
            ty = axis_y - marker_h - 30 * s

        name = m.get('name', '')
        if len(name) > 8:
            name = name[:7] + '…'
        bbox = draw.textbbox((0, 0), name, font=font_name)
        tw = bbox[2] - bbox[0]
        nx = max(2, min(x - tw // 2, width - tw - 2))
        draw.text((nx, ty), name, fill=color, font=font_name)

        if m.get('due_date'):
            ds = m['due_date'].strftime('%m-%d')
            bbox_d = draw.textbbox((0, 0), ds, font=font_date)
            dw = bbox_d[2] - bbox_d[0]
            draw.text((max(2, min(x - dw // 2, width - dw - 2)), ty + 15 * s), ds, fill=COLOR_TEXT, font=font_date)

    # Keep full resolution — browser scales down via CSS width, resulting in crisp display
    buf = io.BytesIO()
    dpi = 72 * scale
    img.save(buf, format='PNG', optimize=True, dpi=(dpi, dpi))
    result = base64.b64encode(buf.getvalue()).decode('ascii')
    _cache[key] = result
    return result
