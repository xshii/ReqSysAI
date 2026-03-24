"""Generate milestone timeline as PNG image (base64)."""
import base64
import io
from datetime import date

from PIL import Image, ImageDraw, ImageFont


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
    """Generate timeline PNG, return base64 string.

    milestones: list of dicts with keys: name, due_date (date), status ('active'/'completed')
    """
    if not milestones or not any(m.get('due_date') for m in milestones):
        return None

    today = today or date.today()
    font_name = _get_font(12)
    font_date = _get_font(10)
    font_today = _get_font(11)

    # Layout constants
    pad_x = 40
    pad_top = 30
    axis_y = pad_top + 20
    marker_h = 10
    label_y = axis_y + marker_h + 4
    date_y = label_y + 16
    row_height = 70
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
        if positions[i] - positions[i - 1] < 70:
            rows[i] = 1 - rows[i - 1]

    height = axis_y + 80  # enough for two rows of labels
    img = Image.new('RGB', (width, height), COLOR_BG)
    draw = ImageDraw.Draw(img)

    # Axis line
    draw.line([(pad_x, axis_y), (width - pad_x, axis_y)], fill=COLOR_AXIS, width=2)

    # Today marker
    today_days = (today - min_date).days
    if 0 <= today_days <= date_range:
        tx = pad_x + int(today_days / date_range * usable_w)
        # Star above axis
        draw.text((tx - 5, axis_y - 18), '★', fill=COLOR_TODAY, font=font_today)
        draw.text((tx + 8, axis_y - 18), '今天', fill=COLOR_TODAY, font=font_date)
        # Dashed vertical line
        for dy in range(axis_y - 2, axis_y + 50, 4):
            draw.line([(tx, dy), (tx, dy + 2)], fill=(220, 53, 69, 80), width=1)

    # Milestones
    for i, m in enumerate(ms_with_date):
        x = positions[i]
        done = m.get('status') == 'completed'
        overdue = not done and m['due_date'] < today
        color = COLOR_DONE if done else (COLOR_OVERDUE if overdue else COLOR_ACTIVE)

        # Triangle marker
        if rows[i] == 0:
            # Below axis
            draw.polygon([(x, axis_y + 2), (x - 5, axis_y + marker_h + 2), (x + 5, axis_y + marker_h + 2)], fill=color)
            ty = axis_y + marker_h + 6
        else:
            # Above axis
            draw.polygon([(x, axis_y - 2), (x - 5, axis_y - marker_h - 2), (x + 5, axis_y - marker_h - 2)], fill=color)
            ty = axis_y - marker_h - 30

        # Name (truncate)
        name = m.get('name', '')
        if len(name) > 8:
            name = name[:7] + '…'
        bbox = draw.textbbox((0, 0), name, font=font_name)
        tw = bbox[2] - bbox[0]
        nx = max(2, min(x - tw // 2, width - tw - 2))
        draw.text((nx, ty), name, fill=color, font=font_name)

        # Date
        if m.get('due_date'):
            ds = m['due_date'].strftime('%m-%d')
            bbox_d = draw.textbbox((0, 0), ds, font=font_date)
            dw = bbox_d[2] - bbox_d[0]
            draw.text((max(2, min(x - dw // 2, width - dw - 2)), ty + 15), ds, fill=COLOR_TEXT, font=font_date)

    # Export as base64 PNG
    buf = io.BytesIO()
    img.save(buf, format='PNG', optimize=True)
    return base64.b64encode(buf.getvalue()).decode('ascii')
