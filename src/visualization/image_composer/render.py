"""Compose and save the NOTAM card: text column on the left, map on the right."""

from __future__ import annotations

from src.core.logging import logger
from src.visualization.fonts import load_font
from src.visualization.image_composer.card_data import notam_from_db_row
from src.visualization.image_composer.fallback_map import draw_fallback_map
from src.visualization.image_composer.layout import (
    BG_COLOR,
    CANVAS_H,
    CANVAS_W,
    GRAY_AAA,
    LEFT_MAX_W,
    PADDING,
    RED_CF,
    WHITE,
)
from src.visualization.map_renderer import MAP_H, MAP_W, render_map


def render_notam_image(notam_dict: dict, output_path: str = "notam_sample.png") -> str:
    """Compose the final NOTAM image (canvas + text + map) and save it.

    Coordinates present in ``notam_dict['coords']`` are used directly. If they
    are missing/unparseable the map renderer falls back to a default global
    map extent.

    Returns the ``output_path`` the image was saved to.
    """
    from PIL import Image, ImageDraw

    notam = notam_dict
    logger.info("Rendering NOTAM image for %s", notam.get("number"))
    img = Image.new("RGBA", (CANVAS_W, CANVAS_H), BG_COLOR)
    draw = ImageDraw.Draw(img)

    # Layout: right map box positioned with PADDING from right and top
    map_x = CANVAS_W - PADDING - MAP_W
    map_y = PADDING

    # Left column area
    left_x = PADDING
    left_y = PADDING
    left_w = min(LEFT_MAX_W, map_x - PADDING - left_x)

    # Load fonts
    title_font = load_font("JetBrainsMono-Bold.ttf", 48)
    number_font = load_font("JetBrainsMono-Bold.ttf", 48)
    details_font = load_font("JetBrainsMono-Regular.ttf", 28)
    small_font = load_font("JetBrainsMono-Regular.ttf", 16)
    caption_font = load_font("JetBrainsMono-Regular.ttf", 14)

    # Draw texts with specified styles
    # Title: ОПОВЕЩЕНИЕ NOTAM
    draw.text((left_x, left_y), "ОПОВЕЩЕНИЕ NOTAM", font=title_font, fill=WHITE)
    left_y += 48 + 4

    # Meta line (ДЛЯ ВОЗДУШНОГО ТРАНСПОРТА)
    draw.text((left_x, left_y), notam.get("meta", "(ДЛЯ ВОЗДУШНОГО ТРАНСПОРТА)"), font=small_font, fill=WHITE)
    left_y += 16 + 4

    # Author
    draw.text((left_x, left_y), notam.get("author", "@sanitaravel"), font=caption_font, fill=GRAY_AAA)
    left_y += 14 + 16

    # NOTAM number
    draw.text((left_x, left_y), notam.get("number", ""), font=number_font, fill=RED_CF)
    left_y += 48 + 20

    # Details (wrap to LEFT_MAX_W)
    details = notam.get("details", "")
    # Simple wrapping
    lines = []
    words = details.split()
    cur = ""
    for w in words:
        test = (cur + " " + w).strip()
        w_box = draw.textbbox((0, 0), test, font=details_font)
        if w_box[2] - w_box[0] > left_w:
            if cur:
                lines.append(cur)
            cur = w
        else:
            cur = test
    if cur:
        lines.append(cur)

    for ln in lines:
        draw.text((left_x, left_y), ln, font=details_font, fill=WHITE)
        left_y += 28 + 4

    left_y += 12

    # Active windows (from the D schedule field). Render a "Действует:" header
    # followed by one line per active window. When no windows were parsed
    # (D field empty/unparseable) fall back to the classic Начало/Завершение
    # start/end display so those NOTAMs still show timing information.
    time_label_font = load_font("JetBrainsMono-Bold.ttf", 24)
    time_value_font = load_font("JetBrainsMono-Regular.ttf", 24)
    time_label_color = WHITE
    time_value_color = (255, 128, 20)  # #FF8014
    time_gap = 8

    windows = notam.get('windows') or []

    if windows:
        left_y += 4
        draw.text((left_x, left_y), "Действует (UTC):", font=time_label_font, fill=time_label_color)
        left_y += 24 + 6
        for win in windows:
            draw.text((left_x, left_y), win, font=time_value_font, fill=time_value_color)
            left_y += 24 + 2
    else:
        # Fallback: right-align the start/end values against the column right
        # edge; if space is insufficient, left-align them after the widest label.
        start_str = notam.get('start')
        end_str = notam.get('end')

        rows = []
        if start_str:
            lb_box = draw.textbbox((0, 0), "Начало:", font=time_label_font)
            vb_box = draw.textbbox((0, 0), start_str, font=time_value_font)
            rows.append(("Начало:", start_str, lb_box[2] - lb_box[0], vb_box[2] - vb_box[0]))
        if end_str:
            lb_box = draw.textbbox((0, 0), "Завершение:", font=time_label_font)
            vb_box = draw.textbbox((0, 0), end_str, font=time_value_font)
            rows.append(("Завершение:", end_str, lb_box[2] - lb_box[0], vb_box[2] - vb_box[0]))

        if rows:
            left_y += 6
            max_lb_w = max(r[2] for r in rows)
            max_vb_w = max(r[3] for r in rows)
            # space after widest label
            min_value_left = left_x + max_lb_w + time_gap
            # candidate left for a right-aligned column that fits the largest value
            candidate_value_left = left_x + left_w - max_vb_w

            if candidate_value_left >= min_value_left:
                # We can right-align values to the column right edge (left_x + left_w)
                for label, value, lb_w, vb_w in rows:
                    draw.text((left_x, left_y), label, font=time_label_font, fill=time_label_color)
                    # right-align each value so their right edges match left_x + left_w
                    value_x = left_x + left_w - vb_w
                    draw.text((value_x, left_y), value, font=time_value_font, fill=time_value_color)
                    left_y += 24 + 6
            else:
                # Not enough space — put values in a consistent column after widest label
                value_left = min_value_left
                for label, value, lb_w, vb_w in rows:
                    draw.text((left_x, left_y), label, font=time_label_font, fill=time_label_color)
                    draw.text((value_left, left_y), value, font=time_value_font, fill=time_value_color)
                    left_y += 24 + 6

    left_y += 12

    # Zone and top height display (under the time block)
    zone = notam.get('zone')
    top = notam.get('top')
    if zone or top:
        # Determine height text, treating 999 as unlimited
        height_text = None
        if top is not None:
            try:
                top_int = int(str(top).lstrip('0') or '0')
            except Exception:
                top_int = None
            if top_int == 999:
                height_text = 'Неограниченно'
            else:
                height_text = str(top)

        parts = []
        if zone:
            parts.append(f"Зона: {zone}")
        if height_text:
            parts.append(f"Высота: {height_text}")
        if parts:
            zone_line = ", ".join(parts)
            left_y += 6
            # Use JetBrains Mono regular at 24px (time_value_font) and white color
            draw.text((left_x, left_y), zone_line, font=time_value_font, fill=WHITE)
            left_y += 24 + 6

    # Draw right map placeholder (rounded rectangle)
    map_box = (map_x, map_y, map_x + MAP_W, map_y + MAP_H)
    # Background for map — match canvas background to avoid visible seams
    draw.rectangle(map_box, fill=BG_COLOR)
    # Coordinates and radius for map rendering
    coords = notam.get("coords")
    radius_nm = notam.get("radius_nm")

    # Try rendering a proper Earth map with the polygon/point using Cartopy
    try:
        map_img = render_map(coords, (MAP_W, MAP_H), radius_nm=radius_nm)
        img.paste(map_img, (map_x, map_y), map_img)
    except Exception:
        logger.exception("Cartopy map rendering failed, falling back to PIL rendering")
        img = draw_fallback_map(img, map_x, map_y, coords, radius_nm)

    # Draw a uniform 2px frame around the map. The cartopy axes spine renders
    # unevenly (the right/top edges get clipped at the figure boundary), so we
    # draw our own border here to guarantee all four sides match. Re-create the
    # drawing context because the fallback path may have replaced ``img`` via
    # alpha compositing.
    draw = ImageDraw.Draw(img)
    draw.rectangle(map_box, outline=(58, 58, 58), width=2)

    img.save(output_path)
    logger.info("Saved NOTAM image to %s", output_path)
    return output_path


def plot_single_notam(name: str, parsed: dict, out_path: str) -> str:
    """Blocking helper used by external callers to generate a NOTAM image.

    This function is suitable for running in a thread (e.g. via
    ``asyncio.to_thread``) and simply wraps existing helpers to produce
    the file at ``out_path`` and return that path.

    Coordinates are always derived from ``parsed`` by
    :func:`notam_from_db_row`, which keeps AND-separated areas as separate
    polygon groups.
    """
    try:
        return render_notam_image(notam_from_db_row(name, parsed), output_path=out_path)
    except Exception:
        logger.exception("plot_single_notam failed for %s", name)
        raise
