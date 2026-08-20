import os
import urllib.request
from PIL import Image, ImageDraw, ImageFont

LOCAL_FONT = "DejaVuSans.ttf"
FONT_URL = "https://github.com/dejavu-fonts/dejavu-fonts/raw/master/ttf/DejaVuSans.ttf"
FONT_CANDIDATES = [
    LOCAL_FONT,
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
    "/usr/share/fonts/truetype/freefont/FreeSans.ttf",
    "C:/Windows/Fonts/arial.ttf",
    "C:/Windows/Fonts/arialbd.ttf",
    "/System/Library/Fonts/Supplemental/Arial.ttf",
]


def get_font(size):
    for path in FONT_CANDIDATES:
        if os.path.exists(path):
            try:
                return ImageFont.truetype(path, size)
            except Exception:
                continue
    try:
        urllib.request.urlretrieve(FONT_URL, LOCAL_FONT)
        return ImageFont.truetype(LOCAL_FONT, size)
    except Exception:
        return ImageFont.load_default()


def build_standings_text(standings):
    if not standings:
        return "Данных для таблицы нет."
    lines = ["ТУРНИРНАЯ ТАБЛИЦА", ""]
    lines.append(f"{'№':<3}{'Команда':<18}{'И':>3}{'В':>3}{'Н':>3}{'П':>3}{'ГЗ':>4}{'ГП':>4}{'О':>4}")
    for i, s in enumerate(standings, 1):
        lines.append(
            f"{i:<3}{s['name'][:17]:<18}{s['played']:>3}{s['wins']:>3}{s['draws']:>3}"
            f"{s['losses']:>3}{s['gf']:>4}{s['ga']:>4}{s['points']:>4}"
        )
    return "\n".join(lines)


def render_standings_image(standings, title="Турнирная таблица"):
    font = get_font(15)
    bold = get_font(16)
    title_font = get_font(24)

    headers = ["№", "Команда", "И", "В", "Н", "П", "ГЗ", "ГП", "О"]
    col_w = [40, 250, 40, 40, 40, 40, 50, 50, 50]
    pad = 20
    width = sum(col_w) + pad * 2
    title_h, header_h, row_h = 60, 40, 36
    height = title_h + header_h + row_h * len(standings) + pad

    img = Image.new("RGB", (width, height), "#ffffff")
    d = ImageDraw.Draw(img)
    d.text((pad, 18), title, font=title_font, fill="#111111")

    y = title_h
    d.rectangle([pad, y, width - pad, y + header_h], fill="#2e7d32")
    x = pad
    for i, h in enumerate(headers):
        if i == 1:
            d.text((x + 8, y + header_h / 2 - 8), h, font=bold, fill="white")
        else:
            tw = d.textlength(h, font=bold)
            d.text((x + col_w[i] / 2 - tw / 2, y + header_h / 2 - 8), h, font=bold, fill="white")
        x += col_w[i]
    y += header_h

    for idx, s in enumerate(standings):
        bg = "#c8e6c9" if idx == 0 else ("#f1f8e9" if idx % 2 == 0 else "#ffffff")
        d.rectangle([pad, y, width - pad, y + row_h], fill=bg)
        x = pad
        vals = [str(idx + 1), s["name"], str(s["played"]), str(s["wins"]), str(s["draws"]),
                str(s["losses"]), str(s["gf"]), str(s["ga"]), str(s["points"])]
        for i, v in enumerate(vals):
            if i == 1:
                name = v
                while d.textlength(name, font=font) > col_w[1] - 16 and len(name) > 1:
                    name = name[:-1]
                if name != v:
                    name += "…"
                d.text((x + 8, y + row_h / 2 - 8), name, font=font, fill="#111111")
            else:
                tw = d.textlength(v, font=font)
                d.text((x + col_w[i] / 2 - tw / 2, y + row_h / 2 - 8), v,
                       font=bold if i == 8 else font, fill="#111111")
            x += col_w[i]
        y += row_h

    x = pad
    for w in col_w[:-1]:
        x += w
        d.line([x, title_h, x, y], fill="#cfd8dc", width=1)
    d.rectangle([pad, title_h, width - pad, y], outline="#90a4ae", width=2)
    return img