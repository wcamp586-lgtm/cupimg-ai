"""合成层：AI 只做场景氛围，商品主体像素原样粘贴，绝不重绘。

输出三张（对应 1688 主图第 1 张白底、第 2 张场景、详情分段）：
  main_white.png  白底主体，走 1688 主图硬校验，不加任何文字
  scene.png       程序化/AI 场景 + 原主体，AI 只动背景
  detail.png      场景 + 文案 + 规格表，显式 AI 标识落在这里
另出 editable/ 下文字未转曲的 SVG（CorelDRAW 可直接打开）。
"""
import os
from xml.sax.saxutils import escape

from PIL import Image, ImageDraw, ImageFilter, ImageFont, PngImagePlugin

# 项目自带白名单字体优先，保证本机与服务器用同一套字体度量
FONT_DIRS = [os.path.join(os.path.dirname(__file__), "..", "..", "assets", "fonts"),
             "C:/Windows/Fonts", "/usr/share/fonts",
             os.path.expanduser("~/Library/Fonts")]
WHITELIST_HINT = ("SourceHanSans", "SourceHanSerif", "NotoSansCJK", "NotoSerifCJK",
                  "AlibabaPuHuiTi", "HarmonyOS", "MiSans", "LXGWWenKai", "SmileySans")


def find_font():
    files = []
    for d in FONT_DIRS:
        if os.path.isdir(d):
            for root, _, names in os.walk(d):
                if root.count(os.sep) - d.count(os.sep) > 1:
                    continue
                files += [os.path.join(root, n) for n in names
                          if n.lower().endswith((".ttf", ".otf", ".ttc"))]
    for hint in WHITELIST_HINT:
        for f in files:
            if hint.lower() in os.path.basename(f).lower():
                return f, True
    for f in files:
        if os.path.basename(f).lower() in ("msyh.ttc", "simhei.ttf", "simsun.ttc"):
            return f, False  # 系统字体仅用于链路验证，商用禁止
    return None, False


def _font(path, size):
    try:
        return ImageFont.truetype(path, size) if path else ImageFont.load_default(size=size)
    except Exception:
        return ImageFont.load_default(size=size)


def fit_text(text, font_path, font_size, max_width):
    """按真实字体度量裁断文字（极端长文案的最终兜底，正常排版走 layout_text）。

    PNG 与 SVG 共用同一份裁断结果，避免「网页看着正常、导出后文字溢出」。
    """
    s = str(text or "").replace("\n", " ").strip()
    if not s:
        return ""
    probe = ImageDraw.Draw(Image.new("RGB", (8, 8)))
    font = _font(font_path, font_size)
    if probe.textlength(s, font=font) <= max_width:
        return s
    lo, hi = 0, len(s)
    while lo < hi:
        mid = (lo + hi + 1) // 2
        if probe.textlength(s[:mid] + "…", font=font) <= max_width:
            lo = mid
        else:
            hi = mid - 1
    return s[:lo].rstrip() + "…" if lo else ""


def _wrap_lines(s, font, probe, max_width):
    """按真实字体度量逐字符折行；超宽时优先在最近空格处断，尽量不拆英文单词。"""
    lines, cur = [], ""
    for ch in s:
        trial = cur + ch
        if cur and probe.textlength(trial, font=font) > max_width:
            cut = cur.rfind(" ")
            if cut >= len(cur) // 2:
                lines.append(cur[:cut].rstrip())
                cur = (cur[cut + 1:] + ch).lstrip()
            else:
                lines.append(cur.rstrip())
                cur = "" if ch == " " else ch
        else:
            cur = trial
    if cur.strip():
        lines.append(cur.rstrip())
    return lines or [""]


def _balance_lines(s, font, probe, max_width):
    """两行时尽量均分宽度，避免第一行撑满、第二行只剩两三个字。"""
    target = probe.textlength(s, font=font) / 2
    best, best_score = None, None
    for i in range(1, len(s)):
        # 禁止把连续的英文/数字词从中间劈开（例如 316L 不能断成 316 / L）
        if (s[i - 1].isascii() and s[i - 1].isalnum()
                and s[i].isascii() and s[i].isalnum()):
            continue
        left = probe.textlength(s[:i], font=font)
        if left > max_width:
            break
        if probe.textlength(s[i:], font=font) > max_width:
            continue
        # 优先在空格处断行，避免拆开英文词
        penalty = 0 if (s[i - 1] == " " or s[i] == " ") else 1
        score = abs(left - target) + penalty * 40
        if best_score is None or score < best_score:
            best_score = score
            best = (s[:i].rstrip(), s[i:].lstrip())
    return [best[0], best[1]] if best and all(best) else None


def layout_text(text, font_path, font_size, max_width, max_lines=2,
                min_size=None, step=2):
    """长文案自动降字号 + 折行，完整保留文字，不再截断成省略号。

    返回 (lines, chosen_size, truncated)。PNG 与 SVG 必须共用这份结果，
    否则会出现「预览正常、CDR 打开溢出」。只有极端长文案才回退 fit_text 裁断。
    """
    s = str(text or "").replace("\n", " ").strip()
    if not s:
        return [], font_size, False
    min_size = min_size or max(16, int(font_size * 0.55))
    probe = ImageDraw.Draw(Image.new("RGB", (8, 8)))
    size = font_size
    while size >= min_size:
        font = _font(font_path, size)
        if probe.textlength(s, font=font) <= max_width:
            return [s], size, False
        lines = _wrap_lines(s, font, probe, max_width)
        if (len(lines) <= max_lines
                and all(probe.textlength(x, font=font) <= max_width for x in lines)):
            if len(lines) == 2:
                lines = _balance_lines(s, font, probe, max_width) or lines
            return lines, size, False
        size -= step
    # 兜底：最小字号仍放不下 → 保留前 max_lines 行，末行按字宽硬裁断
    font = _font(font_path, min_size)
    lines = _wrap_lines(s, font, probe, max_width)
    kept = lines[:max_lines]
    if len(lines) > max_lines and kept:
        kept[-1] = fit_text(kept[-1] + " " + " ".join(lines[max_lines:]),
                            font_path, min_size, max_width)
    return kept, min_size, True


def _fit_product(product_rgba, canvas_size, ratio=0.72):
    bbox = product_rgba.getbbox()
    cropped = product_rgba.crop(bbox) if bbox else product_rgba
    w, h = canvas_size
    scale = min(w * ratio / cropped.width, h * ratio / cropped.height)
    nw, nh = max(1, int(cropped.width * scale)), max(1, int(cropped.height * scale))
    return cropped.resize((nw, nh), Image.LANCZOS)


def _paste_center(canvas, product):
    x = (canvas.width - product.width) // 2
    y = (canvas.height - product.height) // 2
    canvas.paste(product, (x, y), product)
    return (x, y, x + product.width, y + product.height)


# 接地阴影参数（只影响背景层，白底主图不加）
SHADOW = {
    "color": (74, 58, 48),       # 暖棕灰，贴合米色场景，不发灰
    "ambient_alpha": 55,         # 宽而淡的环境遮蔽
    "ambient_scale": 1.55,
    "ambient_blur": 18,
    "contact_alpha": 165,        # 窄而深的接触阴影（高斯模糊会摊薄中心 alpha）
    "contact_scale": 0.92,
    "contact_blur": 10,
}


def _soft_ellipse(w, h, color, alpha, blur):
    """生成边缘柔化的椭圆阴影小块（RGBA）。

    四周留出 3×模糊半径的透明边，否则模糊后小块边界会留下矩形硬边。
    """
    w, h = max(2, int(w)), max(2, int(h))
    pad = max(8, int(blur * 3))
    patch = Image.new("RGBA", (w + 2 * pad, h + 2 * pad), (0, 0, 0, 0))
    ImageDraw.Draw(patch).ellipse(
        [pad, pad, pad + w - 1, pad + h - 1], fill=color + (alpha,))
    return patch.filter(ImageFilter.GaussianBlur(blur))


def _alpha_paste(base, patch, x, y):
    """把带 alpha 的小块合成到 base，自动裁剪出界部分。"""
    x, y = int(round(x)), int(round(y))
    px0, py0 = max(0, -x), max(0, -y)
    px1 = min(patch.width, base.width - x)
    py1 = min(patch.height, base.height - y)
    if px1 <= px0 or py1 <= py0:
        return
    base.alpha_composite(patch.crop((px0, py0, px1, py1)), (x + px0, y + py0))


def _center_paste(base, patch, cx, cy):
    """按中心点贴阴影小块（_soft_ellipse 带 padding，不能用左上角定位）。"""
    _alpha_paste(base, patch, cx - patch.width / 2, cy - patch.height / 2)


def _contact_shadow(canvas, product, box, strength=1.0):
    """在主体接地处叠「宽淡环境遮蔽 + 窄深接触阴影」两层。

    只改背景像素；调用方随后把商品主体原样 paste 覆盖，主体一个像素都不动。
    阴影宽度取主体底部若干行的 alpha 跨度，自动适配细长杯 / 锥形杯 / 带挂绳杯型。
    """
    x0, y0, x1, y1 = box
    alpha = product.getchannel("A")
    w, h = product.size
    rows = max(3, int(h * 0.09))
    bb = alpha.crop((0, h - rows, w, h)).getbbox()
    foot_w = (bb[2] - bb[0]) if bb else w
    foot_cx = x0 + ((bb[0] + bb[2]) / 2 if bb else w / 2)
    foot_y = y1 - max(2, int(h * 0.012))

    base = canvas.convert("RGBA")
    c = SHADOW["color"]
    aw = int(foot_w * SHADOW["ambient_scale"])
    ah = max(28, int(h * 0.10))
    _center_paste(base,
                  _soft_ellipse(aw, ah, c,
                                int(SHADOW["ambient_alpha"] * strength),
                                SHADOW["ambient_blur"]),
                  foot_cx, foot_y)
    cw = int(foot_w * SHADOW["contact_scale"])
    ch = max(18, int(h * 0.060))
    _center_paste(base,
                  _soft_ellipse(cw, ch, c,
                                int(SHADOW["contact_alpha"] * strength),
                                SHADOW["contact_blur"]),
                  foot_cx, foot_y)
    return base.convert("RGB")


def make_main_white(product_rgba, size=800):
    """第 1 张主图（抠图版）：纯白底 + 抠出的主体，零文字零水印。"""
    canvas = Image.new("RGB", (size, size), (255, 255, 255))
    box = _paste_center(canvas, _fit_product(product_rgba, (size, size), 0.86))
    return canvas, box


def make_main_white_from_original(src_img, size=800, ratio=0.86):
    """第 1 张主图（原图直通）：直接用美工定稿图，不经过抠图模型。

    - 有透明通道：alpha 合成到纯白底，保住半透明盖件与抠图易丢失的边缘
    - 正方形定稿图：等比缩放到 size×size，沿用原有构图与留白
    - 非正方形：按 ratio 缩放后居中留白成正方形
    全程只做等比缩放与画布合成，不重绘、不抠图、不动任何商品像素。
    """
    im = src_img.convert("RGBA")
    if im.getchannel("A").getextrema()[0] < 255:
        bg = Image.new("RGBA", im.size, (255, 255, 255, 255))
        bg.alpha_composite(im)
        im = bg
    im = im.convert("RGB")
    w, h = im.size
    if w == h:
        if (w, h) != (size, size):
            im = im.resize((size, size), Image.LANCZOS)
        return im, (0, 0, size, size)
    scale = min(size * ratio / w, size * ratio / h)
    nw, nh = max(1, int(w * scale)), max(1, int(h * scale))
    im = im.resize((nw, nh), Image.LANCZOS)
    canvas = Image.new("RGB", (size, size), (255, 255, 255))
    x, y = (size - nw) // 2, (size - nh) // 2
    canvas.paste(im, (x, y))
    return canvas, (x, y, x + nw, y + nh)


def make_scene(scene_img, product_rgba, size=800):
    """第 2 张：AI 背景 + 接地阴影 + 原主体像素粘贴（图实一致）。

    阴影先画在背景层，主体随后覆盖，保证杯底「站得住」且商品不被改动。
    """
    canvas = scene_img.convert("RGB").resize((size, size), Image.LANCZOS)
    product = _fit_product(product_rgba, (size, size), 0.70)
    x, y = (size - product.width) // 2, (size - product.height) // 2
    box = (x, y, x + product.width, y + product.height)
    canvas = _contact_shadow(canvas, product, box)
    canvas.paste(product, (x, y), product)
    return canvas, box


def _scene_accent_color(img):
    """从场景图上部取饱和度最高像素的色相，压暗成「贴纸字」主题色。

    白描边 + 投影下需要足够深的填充色才醒目：色相保留、S=0.85、V=0.42。
    取不到（纯灰场景）时回退深绿。
    """
    import colorsys
    top = img.crop((0, 0, img.width, max(1, int(img.height * 0.38)))).resize((64, 24))
    best, best_s = (44, 110, 66), -1.0
    for r, g, b in top.getdata():
        mx, mn = max(r, g, b), min(r, g, b)
        s = 0 if mx == 0 else (mx - mn) / mx
        if s > best_s:
            best_s, best = s, (r, g, b)
    h, _, _ = colorsys.rgb_to_hsv(best[0] / 255, best[1] / 255, best[2] / 255)
    r, g, b = colorsys.hsv_to_rgb(h, 0.85, 0.42)
    return (int(r * 255), int(g * 255), int(b * 255))


def draw_scene_copy(scene_img, copy_text, font_path, size=800):
    """场景图促销文案层（2026-11-24 风格化新增，参考电商样张「贴纸字」风格）。

    大标题 = 场景取色主题色填充 + 白色粗描边 + 投影，置顶居中；
    副标题 = 白底圆角胶囊 + 同主题色文字。文字全部来自已过广告法校验的
    copy_text（title/subtitle），本函数不新增任何文案内容。
    """
    im = scene_img.convert("RGB").resize((size, size), Image.LANCZOS)
    # 大标题优先用短口号（slogan，≤10 字），没有再退回商品名 title；
    # 商品名+参数太长会被截断成省略号，参考样张的大字层都是短口号。
    title = str(copy_text.get("slogan") or copy_text.get("title") or "").strip()
    subtitle = str(copy_text.get("subtitle") or "").strip()
    if not title and not subtitle:
        return im
    d = ImageDraw.Draw(im)
    accent = _scene_accent_color(im)
    y = 46
    if title:
        fsize = 104
        while fsize > 44:
            if d.textlength(title, font=_font(font_path, fsize)) <= size * 0.88:
                break
            fsize -= 6
        t = fit_text(title, font_path, fsize, size * 0.88)
        font = _font(font_path, fsize)
        sw = max(4, fsize // 11)
        x = (size - d.textlength(t, font=font)) // 2
        d.text((x + 6, y + 8), t, font=font, fill=(72, 72, 72),
               stroke_width=sw, stroke_fill=(72, 72, 72))       # 投影层
        d.text((x, y), t, font=font, fill=accent,
               stroke_width=sw, stroke_fill=(255, 255, 255))    # 白描边贴纸字
        y += int(fsize * 1.18) + 22
    if subtitle:
        f2size = 30
        s = fit_text(subtitle, font_path, f2size, size * 0.72)
        f2 = _font(font_path, f2size)
        tw = d.textlength(s, font=f2)
        bw, bh = tw + 52, f2size + 24
        bx = (size - bw) // 2
        d.rounded_rectangle([bx, y, bx + bw, y + bh], radius=bh // 2,
                            fill=(255, 255, 255), outline=accent, width=3)
        d.text((bx + 26, y + 10), s, font=f2, fill=accent)
    return im


def make_detail(scene_img, product_rgba, facts, copy_text, font_path,
                label, size=800):
    """详情图：信息条按文字实际行数自适应，主体按剩余高度缩放，不被上下条遮挡。"""
    canvas = scene_img.convert("RGB").resize((size, size), Image.LANCZOS)
    max_w = size - 80
    title, title_size, _ = layout_text(copy_text.get("title", ""), font_path,
                                       44, max_w, max_lines=2)
    subtitle, sub_size, _ = layout_text(copy_text.get("subtitle", ""), font_path,
                                        24, max_w, max_lines=2)
    title_lh = int(title_size * 1.22)
    sub_lh = int(sub_size * 1.35)
    title_y = 20
    sub_y = title_y + len(title) * title_lh + 10
    top_bar = min(230, max(168, sub_y + len(subtitle) * sub_lh + 20))
    bullets = list(copy_text.get("bullets", []))[:4]
    by = size - 40 - len(bullets) * 34 - 34
    bottom_bar = size - by + 24          # 底部白条上方留 8px，不压杯底
    usable = size - top_bar - bottom_bar

    small = _fit_product(product_rgba, (size, usable), 0.92)
    x = (size - small.width) // 2
    y = top_bar + max(0, (usable - small.height) // 2)
    # 详情图接地阴影弱一档，避免被底部信息条截断显得突兀
    canvas = _contact_shadow(canvas, small,
                             (x, y, x + small.width, y + small.height),
                             strength=0.75)
    canvas.paste(small, (x, y), small)

    d = ImageDraw.Draw(canvas)
    d.rectangle([0, 0, size, top_bar], fill=(255, 255, 255))
    f_title, f_sub = _font(font_path, title_size), _font(font_path, sub_size)
    for i, line in enumerate(title):
        d.text((40, title_y + i * title_lh), line, font=f_title, fill=(28, 32, 38))
    for i, line in enumerate(subtitle):
        d.text((40, sub_y + i * sub_lh), line, font=f_sub, fill=(92, 100, 110))

    d.rectangle([0, by - 16, size, size], fill=(255, 255, 255))
    for b in bullets:
        lines, b_size, _ = layout_text(b, font_path, 24, max_w - 24, max_lines=1)
        d.text((40, by), f"· {lines[0] if lines else ''}",
               font=_font(font_path, b_size), fill=(40, 46, 54))
        by += 34
    d.text((40, size - 30), label["explicit"],
           font=_font(font_path, 18), fill=(110, 118, 128))
    return canvas


def make_detail_from_composed(composed_img, product_box, copy_text, font_path,
                              label, size=800, margin=0.14):
    """详情图（i2i 直出版）：场景与主体已由模型融合渲染，不能重复贴主体。

    取法：以门禁给出的主体 bbox 为中心，向外扩 margin 裁出带背景的局部画面，
    等比缩放进上下信息条之间的窗口，再画文案条与显式 AI 标识。
    主体观感大小与贴图版（_fit_product 至 usable 高度）基本一致。
    """
    canvas = Image.new("RGB", (size, size), (255, 255, 255))
    max_w = size - 80
    title, title_size, _ = layout_text(copy_text.get("title", ""), font_path,
                                       44, max_w, max_lines=2)
    subtitle, sub_size, _ = layout_text(copy_text.get("subtitle", ""), font_path,
                                        24, max_w, max_lines=2)
    title_lh = int(title_size * 1.22)
    sub_lh = int(sub_size * 1.35)
    title_y = 20
    sub_y = title_y + len(title) * title_lh + 10
    top_bar = min(230, max(168, sub_y + len(subtitle) * sub_lh + 20))
    bullets = list(copy_text.get("bullets", []))[:4]
    by = size - 40 - len(bullets) * 34 - 34
    usable = (by - 16) - top_bar   # 顶部条底边到卖点条顶边之间的画面高度

    x0, y0, x1, y1 = product_box
    bw, bh = x1 - x0, y1 - y0
    cx0 = max(0, int(x0 - bw * margin)); cy0 = max(0, int(y0 - bh * margin))
    cx1 = min(composed_img.width, int(x1 + bw * margin))
    cy1 = min(composed_img.height, int(y1 + bh * margin))
    crop = composed_img.convert("RGB").crop((cx0, cy0, cx1, cy1))
    scale = min(max_w * 0.92 / crop.width, usable * 0.98 / crop.height)
    nw, nh = max(1, int(crop.width * scale)), max(1, int(crop.height * scale))
    crop = crop.resize((nw, nh), Image.LANCZOS)
    px = (size - nw) // 2
    py = top_bar + max(0, (usable - nh) // 2)
    canvas.paste(crop, (px, py))

    d = ImageDraw.Draw(canvas)
    d.rectangle([0, 0, size, top_bar], fill=(255, 255, 255))
    f_title, f_sub = _font(font_path, title_size), _font(font_path, sub_size)
    for i, line in enumerate(title):
        d.text((40, title_y + i * title_lh), line, font=f_title, fill=(28, 32, 38))
    for i, line in enumerate(subtitle):
        d.text((40, sub_y + i * sub_lh), line, font=f_sub, fill=(92, 100, 110))

    d.rectangle([0, by - 16, size, size], fill=(255, 255, 255))
    for b in bullets:
        lines, b_size, _ = layout_text(b, font_path, 24, max_w - 24, max_lines=1)
        d.text((40, by), f"· {lines[0] if lines else ''}",
               font=_font(font_path, b_size), fill=(40, 46, 54))
        by += 34
    d.text((40, size - 30), label["explicit"],
           font=_font(font_path, 18), fill=(110, 118, 128))
    return canvas


def save_png(img, path, ai_meta=None):
    if ai_meta:
        meta = PngImagePlugin.PngInfo()
        for k, v in ai_meta.items():
            meta.add_text(k, str(v))
        img.save(path, pnginfo=meta, optimize=True)
    else:
        img.save(path, optimize=True)


def export_svg(path, facts, copy_text, label, size=800):
    """文字保持 <text> 不转曲，CorelDRAW 可直接打开精修；多行用 tspan。"""
    font_path, _ = find_font()
    max_w = size - 80
    title, title_size, _ = layout_text(copy_text.get("title", ""), font_path,
                                       44, max_w, max_lines=2)
    subtitle, sub_size, _ = layout_text(copy_text.get("subtitle", ""), font_path,
                                        24, max_w, max_lines=2)

    def block(lines, x, y, fsize, lh, fill):
        if not lines:
            return ""
        spans = "".join(f'<tspan x="{x}" y="{y + i * lh}">{escape(line)}</tspan>'
                        for i, line in enumerate(lines))
        return (f'<text x="{x}" y="{y}" font-size="{fsize}" '
                f'fill="{fill}">{spans}</text>')

    title_lh = int(title_size * 1.22)
    sub_lh = int(sub_size * 1.35)
    title_xml = block(title, 40, 60, title_size, title_lh, "#1C2026")
    subtitle_xml = block(subtitle, 40, 60 + len(title) * title_lh + 10,
                         sub_size, sub_lh, "#5C646E")
    bullet_xml = []
    for i, b in enumerate(copy_text.get("bullets", [])[:4]):
        lines, b_size, _ = layout_text(b, font_path, 24, max_w - 24, max_lines=1)
        bullet_xml.append(
            f'<text x="40" y="{560 + i * 36}" font-size="{b_size}" '
            f'fill="#282E36">· {escape(lines[0] if lines else "")}</text>')

    svg = f'''<?xml version="1.0" encoding="UTF-8"?>
<svg xmlns="http://www.w3.org/2000/svg" width="{size}" height="{size}" viewBox="0 0 {size} {size}">
  <rect width="{size}" height="{size}" fill="#FFFFFF"/>
  {title_xml}
  {subtitle_xml}
  {"".join(bullet_xml)}
  <text x="40" y="{size - 30}" font-size="18" fill="#6E7680">{escape(label["explicit"])}</text>
  <!-- 商品主体图层由 final/main_white.png 提供；CDR 中请沿用输入的定稿商品图，勿重绘 -->
</svg>'''
    with open(path, "w", encoding="utf-8") as f:
        f.write(svg)
