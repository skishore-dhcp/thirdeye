import colorsys
import io
import re
import zipfile
from datetime import datetime, timezone

import cv2
import numpy as np

import reports

try:
    import pymupdf as fitz
except ImportError:
    import fitz

KIND_LABELS = {
    "must_not_use": "Must not use", "must_include": "Must include", "tone": "Tone / Style",
    "logo": "Logo", "color": "Color",
}


def utcnow():
    return datetime.now(timezone.utc).replace(tzinfo=None)


class ContentError(Exception):
    pass


def open_pdf(data, max_pages):
    if b"%PDF-" not in data[:1024]:
        raise ContentError("This file is not a valid PDF.")
    try:
        doc = fitz.open(stream=data, filetype="pdf")
    except Exception:
        raise ContentError("The PDF could not be read.")
    if doc.needs_pass:
        raise ContentError("Password-protected PDFs are not supported.")
    if doc.page_count == 0:
        raise ContentError("The PDF has no pages.")
    if doc.page_count > max_pages:
        raise ContentError(f"The PDF has too many pages (limit {max_pages}).")
    return doc


def _ocr(doc):
    try:
        import pytesseract
        from PIL import Image
        parts = []
        for page in doc:
            pix = page.get_pixmap(dpi=200, colorspace=fitz.csRGB, alpha=False)
            parts.append(pytesseract.image_to_string(Image.frombytes("RGB", (pix.width, pix.height), pix.samples)))
        return "\n".join(parts), None
    except Exception:
        return "", "OCR is not available on this server, so the scanned PDF could not be read."


def extract_pdf_text(doc):
    text = "\n".join(page.get_text() for page in doc)
    if len(text.strip()) >= 20:
        return text, False, None
    text, err = _ocr(doc)
    if err:
        return "", True, err
    return text, True, "This PDF has no text layer, so OCR was used. Text accuracy may be lower."


IMAGE_FORMATS = {"PNG", "JPEG", "WEBP"}


def open_image(data, max_pixels):
    try:
        from PIL import Image, ImageOps
    except ImportError:
        raise ContentError("Image support is not available on this server.")
    try:
        img = Image.open(io.BytesIO(data))
        fmt, (w, h) = img.format, img.size
    except Exception:
        raise ContentError("This file is not a valid image or could not be read.")
    if fmt not in IMAGE_FORMATS:
        raise ContentError("Only PNG, JPG and WebP images are supported.")
    if w * h > max_pixels:
        raise ContentError(f"The image is too large ({w} x {h} pixels). The limit is {max_pixels / 1_000_000:g} megapixels.")
    try:
        img.load()
        img = ImageOps.exif_transpose(img)
        if img.mode in ("RGBA", "LA") or "transparency" in img.info:
            rgba = img.convert("RGBA")
            flat = Image.new("RGB", rgba.size, (255, 255, 255))
            flat.paste(rgba, mask=rgba.getchannel("A"))
            return flat
        return img.convert("RGB")
    except Exception:
        raise ContentError("The image could not be read. It may be damaged.")


def ocr_image(img, cfg):
    from PIL import Image
    try:
        import pytesseract
        from pytesseract import Output
    except ImportError:
        raise ContentError("OCR is not available on this server, so the image could not be read.")
    longest = max(img.size)
    if longest > cfg["OCR_MAX_SIDE"] or longest < cfg["OCR_MIN_SIDE"]:
        factor = (cfg["OCR_MAX_SIDE"] if longest > cfg["OCR_MAX_SIDE"] else cfg["OCR_MIN_SIDE"]) / longest
        img = img.resize((max(1, round(img.width * factor)), max(1, round(img.height * factor))), Image.LANCZOS)
    try:
        data = pytesseract.image_to_data(img, output_type=Output.DICT, timeout=cfg["OCR_TIMEOUT"])
    except pytesseract.TesseractNotFoundError:
        raise ContentError("OCR is not available on this server, so the image could not be read.")
    except RuntimeError:
        raise ContentError("Reading the image took too long. Try a smaller or clearer image.")
    except Exception:
        raise ContentError("The image could not be read.")
    lines, order, confs = {}, [], []
    for n, word in enumerate(data["text"]):
        word = (word or "").strip()
        if not word:
            continue
        key = (data["block_num"][n], data["par_num"][n], data["line_num"][n])
        if key not in lines:
            lines[key] = []
            order.append(key)
        lines[key].append(word)
        conf = float(data["conf"][n])
        if conf >= 0:
            confs.append(conf)
    out, previous = [], None
    for key in order:
        if previous is not None and key[:2] != previous[:2]:
            out.append("")
        out.append(" ".join(lines[key]))
        previous = key
    return "\n".join(out), (sum(confs) / len(confs) if confs else None)


def image_page(img, width=1000):
    arr = np.asarray(img.convert("RGB")).copy()
    scale = width / arr.shape[1]
    return cv2.resize(arr, (width, max(1, round(arr.shape[0] * scale))), interpolation=cv2.INTER_AREA if scale < 1 else cv2.INTER_LINEAR)


def phrase_pattern(phrase):
    body = r"\s+".join(re.escape(p) for p in phrase.split())
    return re.compile(r"(?<!\w)" + body + r"(?!\w)", re.IGNORECASE)


_AFTER_BANNED = r"""[.,;:!?)\]}"”…–—]"""


def banned_pattern(phrase):
    body = r"\s+".join(re.escape(p) for p in phrase.split())
    return re.compile(r"(?<!\S)" + body + r"(?=\s|$|" + _AFTER_BANNED + ")", re.IGNORECASE)


def _key(kind, rule):
    return f"{kind}:{' '.join(rule.lower().split())}"


def _excerpt(text, m, pad=40):
    s = " ".join(text[max(0, m.start() - pad): m.end() + pad].split())
    return ("..." if m.start() > pad else "") + s + ("..." if m.end() + pad < len(text) else "")


def _issue(kind, rule, **extra):
    base = {"key": _key(kind, rule) if kind in ("must_not_use", "must_include", "tone") else kind,
            "type": kind, "label": f'{KIND_LABELS[kind]}: "{rule}"' if kind in ("must_not_use", "must_include", "tone")
            else {"logo": "Logo missing", "color": "Off-palette colors"}[kind],
            "rule": rule, "excerpt": "", "problem": "", "suggestion": "", "fix_kind": "none", "find": [], "replace_with": "",
            "manual": False, "gap": None}
    base.update(extra)
    return base


def _match_case(src, repl):
    if repl.startswith("[") or not any(ch.isalpha() for ch in repl):
        return repl
    if len(src) > 1 and src.isupper():
        return repl.upper()
    if src[:1].isupper():
        return repl[:1].upper() + repl[1:]
    return repl


def exact_checks(text, rules, default_replacement="[removed]"):
    issues = []
    for r in rules:
        if r["kind"] == "must_not_use":
            matches = list(banned_pattern(r["text"]).finditer(text))
            if matches:
                found = sorted({m.group(0) for m in matches})
                repl = r.get("replacement") or default_replacement
                manual = not r.get("replacement")
                suggestion = f'Replace "{r["text"]}" with "{repl}".'
                if manual:
                    suggestion += f' Manual editing needed: write new wording where "{repl}" appears.'
                issues.append(_issue(
                    "must_not_use", r["text"], excerpt=_excerpt(text, matches[0]),
                    problem=f'"{r["text"]}" is not allowed and appears {len(matches)} time(s).',
                    suggestion=suggestion, fix_kind="substitute", find=found, replace_with=repl, manual=manual))
        elif r["kind"] == "must_include":
            if not phrase_pattern(r["text"]).search(text):
                issues.append(_issue(
                    "must_include", r["text"], problem=f'The required text "{r["text"]}" is missing.',
                    suggestion=f'Add "{r["text"]}".', fix_kind="append", replace_with=r["text"]))
    return issues


_EMAIL = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")
_PHONE = re.compile(r"(?<!\w)\+?\d[\d ().-]{7,}\d(?!\w)")
_NOT_PHONE = re.compile(r"\d{4}-\d{2}-\d{2}|\d{1,2}\.\d{1,2}\.\d{2,4}")
_CARD = re.compile(r"(?<![\w-])\d(?:[ -]?\d){12,18}(?![\w-])")


def _is_card(s):
    digits = [int(c) for c in re.sub(r"\D", "", s)]
    if not 13 <= len(digits) <= 19:
        return False
    total = 0
    for n, d in enumerate(reversed(digits)):
        if n % 2:
            d = d * 2 - 9 if d > 4 else d * 2
        total += d
    return total % 10 == 0


def _is_phone(s):
    return 7 <= len(re.sub(r"\D", "", s)) <= 15 and not _NOT_PHONE.fullmatch(s.strip())


def redact(text):
    mapping, counts = {}, {"EMAIL": 0, "CARD": 0, "PHONE_NO": 0}

    def make(label, validator=None):
        def repl(m):
            s = m.group(0)
            if validator and not validator(s):
                return s
            for ph, orig in mapping.items():
                if orig == s and ph.startswith(f"[{label}_"):
                    return ph
            counts[label] += 1
            ph = f"[{label}_{counts[label]}]"
            mapping[ph] = s
            return ph
        return repl

    text = _EMAIL.sub(make("EMAIL"), text)
    text = _CARD.sub(make("CARD", _is_card), text)
    text = _PHONE.sub(make("PHONE_NO", _is_phone), text)
    return text, mapping


def restore(text, mapping):
    for ph, orig in mapping.items():
        text = text.replace(ph, orig)
    return text


def render_pages(doc, max_pages, width=1000):
    pages = []
    for page in list(doc)[:max_pages]:
        zoom = width / page.rect.width
        pix = page.get_pixmap(matrix=fitz.Matrix(zoom, zoom), colorspace=fitz.csRGB, alpha=False)
        pages.append(np.frombuffer(pix.samples, np.uint8).reshape(pix.height, pix.width, 3).copy())
    return pages


def _logo_variants(logo_bytes):
    arr = cv2.imdecode(np.frombuffer(logo_bytes, np.uint8), cv2.IMREAD_UNCHANGED)
    if arr is None:
        return []
    if arr.ndim == 2:
        return [arr]
    if arr.shape[2] == 4:
        a = arr[:, :, 3:4].astype(np.float32) / 255.0
        out = []
        for bg in (255, 0):
            flat = (arr[:, :, :3] * a + bg * (1 - a)).astype(np.uint8)
            out.append(cv2.cvtColor(flat, cv2.COLOR_BGR2GRAY))
        return out
    return [cv2.cvtColor(arr[:, :, :3], cv2.COLOR_BGR2GRAY)]


def _edges(gray):
    return cv2.dilate(cv2.Canny(gray, 50, 150), np.ones((3, 3), np.uint8))


def logo_score(pages_rgb, logo_bytes, scales=48, min_frac=0.07, max_frac=0.6, stop_at=0.9):
    variants = _logo_variants(logo_bytes)
    if not variants:
        return 0.0
    best = 0.0
    for rgb in pages_rgb:
        page_edges = _edges(cv2.cvtColor(rgb, cv2.COLOR_RGB2GRAY))
        ph, pw = page_edges.shape
        for frac in np.geomspace(min_frac, max_frac, scales):
            w = int(pw * frac)
            h = int(round(variants[0].shape[0] * w / variants[0].shape[1]))
            if w < 12 or h < 12 or w >= pw or h >= ph:
                continue
            tpl = None
            for v in variants:
                e = _edges(cv2.resize(v, (w, h), interpolation=cv2.INTER_AREA))
                tpl = e if tpl is None else cv2.bitwise_or(tpl, e)
            if np.count_nonzero(tpl) < 20:
                continue
            best = max(best, float(np.nanmax(cv2.matchTemplate(page_edges, tpl, cv2.TM_CCOEFF_NORMED))))
            if best >= stop_at:
                return best
    return best


def hex_to_rgb(h):
    h = h.lstrip("#")
    return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))


def dominant_colors(rgb, k=5):
    scale = 120 / max(rgb.shape[:2])
    small = cv2.resize(rgb, None, fx=scale, fy=scale, interpolation=cv2.INTER_AREA) if scale < 1 else rgb
    data = small.reshape(-1, 3).astype(np.float32)
    k = max(1, min(k, len(np.unique(data, axis=0))))
    cv2.setRNGSeed(42)
    _, labels, centers = cv2.kmeans(
        data, k, None, (cv2.TERM_CRITERIA_EPS + cv2.TERM_CRITERIA_MAX_ITER, 20, 1.0), 3, cv2.KMEANS_PP_CENTERS)
    counts = np.bincount(labels.flatten(), minlength=k)
    return [(tuple(int(v) for v in c), n / len(labels)) for c, n in zip(centers, counts)]


def _chromatic(rgb):
    h, s, v = colorsys.rgb_to_hsv(*(c / 255 for c in rgb))
    return s >= 0.25 and 0.15 <= v


def color_check(pages_rgb, palette, tolerance, min_share):
    pal = [(h, hex_to_rgb(h)) for h in palette]
    offenders = {}
    for rgb in pages_rgb:
        for color, share in dominant_colors(rgb):
            if share < min_share or not _chromatic(color):
                continue
            hex_c, dist = min(((h, float(np.linalg.norm(np.array(color) - np.array(p)))) for h, p in pal),
                              key=lambda t: t[1])
            if dist > tolerance:
                offenders["#%02X%02X%02X" % color] = hex_c
    if not offenders:
        return []
    fixes = "; ".join(f"replace {bad} with {good}" for bad, good in list(offenders.items())[:3])
    return [_issue("color", "Brand color palette", problem="Colors outside the brand palette were found: "
                   + ", ".join(list(offenders)[:3]) + ".", suggestion=fixes[0].upper() + fixes[1:] + ".")]


def _tidy(text):
    text = re.sub(r"[ \t]{2,}", " ", text)
    text = re.sub(r" +([,.;:!?])", r"\1", text)
    text = re.sub(r"(?m)^[ \t]*[,;:]\s*", "", text)
    text = re.sub(r"(?m)^ (?=\S)", "", text)
    return re.sub(r"(?m)[ \t]+$", "", text)


def split_units(text):
    spans = []
    for m in re.finditer(r"[^\n]+", text):
        seg = m.group(0)
        if seg.strip():
            spans.append((m.start(), m.start() + len(seg.rstrip())))
    return spans


def substitute_banned(text, issues):
    out = text
    for i in issues:
        if i["fix_kind"] == "substitute":
            repl = i["replace_with"]
            out = banned_pattern(i["rule"]).sub(lambda m: _match_case(m.group(0), repl), out)
    return out


def _separator(text, spans, gap):
    n = len(spans)
    if n < 2:
        return "\n\n"
    if gap == 0:
        between = text[spans[0][1]:spans[1][0]]
    elif gap >= n:
        between = text[spans[n - 2][1]:spans[n - 1][0]]
    else:
        between = text[spans[gap - 1][1]:spans[gap][0]]
    return "\n\n" if between.count("\n") >= 2 else "\n"


def insert_phrases(text, items):
    spans = split_units(text)
    n = len(spans)
    by_gap = {}
    for gap, phrase in items:
        g = n if gap is None or not 0 <= gap <= n else gap
        by_gap.setdefault(g, []).append(phrase)
    out = text
    for g in sorted(by_gap, reverse=True):
        sep = _separator(text, spans, g)
        if g == 0 or n == 0:
            out = sep.join(by_gap[g]) + sep + out
        else:
            at = text.find("\n", spans[g - 1][1])
            at = len(text) if at == -1 else at
            out = out[:at] + "".join(sep + p for p in by_gap[g]) + out[at:]
    return out


def apply_text_corrections(text, issues):
    return insert_phrases(substitute_banned(text, issues),
                          [(i.get("gap"), i["replace_with"]) for i in issues if i["fix_kind"] == "append"])


def verify_final(corrected, rules):
    extra = []
    for r in rules:
        if r["kind"] == "must_not_use":
            m = banned_pattern(r["text"]).search(corrected)
            if m:
                extra.append(_issue(
                    "must_not_use", r["text"], excerpt=_excerpt(corrected, m), manual=True,
                    problem=f'"{r["text"]}" is still in the corrected text (a replacement or the required text brought it back).',
                    suggestion=f'Manual editing needed: remove "{r["text"]}" from the corrected text by hand.'))
        elif r["kind"] == "must_include" and not phrase_pattern(r["text"]).search(corrected):
            extra.append(_issue(
                "must_include", r["text"], manual=True,
                problem=f'The required text "{r["text"]}" is not in the corrected text.',
                suggestion=f'Manual editing needed: add "{r["text"]}" by hand.'))
    return extra


def rule_conflict(kind, text, replacement, existing):
    banned = [r for r in existing if r["kind"] == "must_not_use"]
    required = [r for r in existing if r["kind"] == "must_include"]
    if kind == "must_not_use":
        pat = banned_pattern(text)
        for r in required:
            if pat.search(r["text"]):
                return f'"{r["text"]}" is a required phrase and contains "{text}".'
        for b in banned:
            if b.get("replacement") and pat.search(b["replacement"]):
                return f'The replacement for "{b["text"]}" contains "{text}".'
        for b in banned if replacement else []:
            if banned_pattern(b["text"]).search(replacement):
                return f'The replacement contains "{b["text"]}", which is already banned.'
    elif kind == "must_include":
        for b in banned:
            if banned_pattern(b["text"]).search(text):
                return f'This phrase contains "{b["text"]}", which is banned.'
    return None


def _rgb(c):
    return ((c >> 16 & 255) / 255, (c >> 8 & 255) / 255, (c & 255) / 255)


def _rewrite_lines(page, pattern, repl, inserts):
    n = 0
    for block in page.get_text("dict")["blocks"]:
        for line in block.get("lines", []):
            spans = line["spans"]
            text = "".join(s["text"] for s in spans)
            if not spans or not pattern.search(text):
                continue
            new = pattern.sub(lambda m: _match_case(m.group(0), repl), text)
            rect, first = fitz.Rect(line["bbox"]), spans[0]
            size, room = first["size"], page.rect.x1 - 36 - rect.x0
            while size > 6 and fitz.get_text_length(new, fontname="helv", fontsize=size) > room:
                size -= 0.5
            if fitz.get_text_length(new, fontname="helv", fontsize=size) > room:
                continue
            page.add_redact_annot(rect, fill=(1, 1, 1))
            inserts.append((page, first["origin"], new, size, _rgb(first["color"])))
            n += 1
    return n


NOTE_HEADER = "NOTE: THE LIST OF WORDS MUST BE INCLUDED IN THE PDF WHERE SUITABLE."
NOTE_FOOTER = "AFTER ADDING THEM, PLEASE DELETE THIS PAGE."
NOTE_SIGNATURE = "-ThirdEye"


def _wrap(text, font, size, width):
    lines, line = [], ""
    for word in text.split():
        trial = f"{line} {word}".strip()
        if font.text_length(trial, fontsize=size) <= width:
            line = trial
            continue
        if line:
            lines.append(line)
        line = ""
        while font.text_length(word, fontsize=size) > width and len(word) > 1:
            cut = len(word) - 1
            while cut > 1 and font.text_length(word[:cut], fontsize=size) > width:
                cut -= 1
            lines.append(word[:cut])
            word = word[cut:]
        line = word
    if line:
        lines.append(line)
    return lines or [""]


def _font_for(text, fonts):
    wanted = [c for c in text if not c.isspace()]
    best, best_hits = fonts[0], -1
    for f in fonts:
        hits = sum(1 for c in wanted if f.has_glyph(ord(c)))
        if hits == len(wanted):
            return f, text, True
        if hits > best_hits:
            best, best_hits = f, hits
    return best, "".join(c if c.isspace() or best.has_glyph(ord(c)) else "?" for c in text), False


def add_instruction_pages(doc, words):
    regular, bold = fitz.Font("helv"), fitz.Font("hebo")
    fallback = [regular, fitz.Font("cjk")]
    w, h = doc[-1].rect.width, doc[-1].rect.height
    if min(w, h) < 400:
        w, h = 595.0, 842.0
    margin = max(36.0, min(w, h) * 0.09)
    width = w - 2 * margin
    head_size, body_size, gap = 14.0, 13.0, 8.0
    head_lh, body_lh = head_size * 1.35, body_size * 1.4
    header = _wrap(NOTE_HEADER, bold, head_size, width)
    footer = _wrap(NOTE_FOOTER, bold, head_size, width)
    footer_height = len(footer) * head_lh + gap + body_lh
    top_after_header = margin + len(header) * head_lh + 2 * gap
    limit = h - margin - footer_height - 2 * gap

    entries, unreadable = [], []
    for word in words:
        font, drawn, ok = _font_for(word, fallback)
        if not ok:
            unreadable.append(word)
        entries.append((font, _wrap(drawn, font, body_size, width), ok))

    pages_added, page, writer, y = 0, None, None, 0.0

    def begin():
        nonlocal page, writer, y, pages_added
        page = doc.new_page(-1, width=w, height=h)
        writer = fitz.TextWriter(page.rect)
        y = margin
        for line in header:
            y += head_lh
            writer.append((margin, y - head_size * 0.3), line, font=bold, fontsize=head_size)
        y = top_after_header
        pages_added += 1

    def finish():
        fy = y + gap
        for line in footer:
            fy += head_lh
            writer.append((margin, fy - head_size * 0.3), line, font=bold, fontsize=head_size)
        fy += gap + body_lh
        writer.append((margin, fy - body_size * 0.3), NOTE_SIGNATURE, font=regular, fontsize=body_size)
        writer.write_text(page, color=(0, 0, 0))

    begin()
    for font, lines, _ in entries:
        for n, line in enumerate(lines):
            if y + body_lh > limit:
                finish()
                begin()
            y += body_lh
            writer.append((margin, y - body_size * 0.3), line, font=font, fontsize=body_size)
        y += gap
    finish()
    return pages_added, unreadable


def edit_pdf(data, issues, scanned=False):
    notes, inserts = [], []
    doc = fitz.open(stream=data, filetype="pdf")
    changed = False
    substitutes = [i for i in issues if i["fix_kind"] == "substitute"]
    if scanned:
        if substitutes:
            notes.append("Scanned PDFs have no editable text, so banned-word fixes are only in the corrected text file.")
    else:
        for i in substitutes:
            pattern = banned_pattern(i["rule"])
            hits = sum(_rewrite_lines(page, pattern, i["replace_with"], inserts) for page in doc)
            if hits:
                changed = True
            else:
                notes.append(f'Could not edit "{i["rule"]}" inside the PDF layout. See the corrected text file.')
        for page in doc:
            page.apply_redactions(images=fitz.PDF_REDACT_IMAGE_NONE)
        for page, origin, text, size, color in inserts:
            page.insert_text(origin, text, fontsize=size, fontname="helv", color=color)
    words = [i["replace_with"] for i in issues if i["fix_kind"] == "append"]
    if words:
        pages, unreadable = add_instruction_pages(doc, words)
        changed = True
        which = "The last page of the corrected PDF lists" if pages == 1 else f"The last {pages} pages of the corrected PDF list"
        notes.append(f"{which} the required words that are missing. Add them where suitable, then delete "
                     f"{'that page' if pages == 1 else 'those pages'}.")
        if unreadable:
            notes.append("These required words contain characters that cannot be shown on that page (shown as ?): "
                         + ", ".join(f'"{u}"' for u in unreadable) + ". See the corrected text file for the exact text.")
    return (doc.tobytes(garbage=3, deflate=True) if changed else None), notes


def public_issue(i):
    out = {k: i[k] for k in ("key", "type", "label", "rule", "excerpt", "problem", "suggestion")}
    out["manual"] = bool(i.get("manual"))
    return out


def _merge_issue(first, other):
    first["manual"] = bool(first.get("manual") or other.get("manual"))
    if other["problem"] and other["problem"] not in first["problem"]:
        first["problem"] = f'{first["problem"]} {other["problem"]}'.strip()
    if other.get("manual") and other["suggestion"] and other["suggestion"] not in first["suggestion"]:
        first["suggestion"] = f'{first["suggestion"]} {other["suggestion"]}'.strip()


def unique_issues(issues):
    out, by_key = [], {}
    for i in issues:
        if i["key"] in by_key:
            _merge_issue(by_key[i["key"]], i)
        else:
            by_key[i["key"]] = i
            out.append(i)
    return out


def _gap_from(pos, n_units):
    if not isinstance(pos, dict):
        return None
    unit, where = pos.get("unit"), pos.get("where")
    if isinstance(unit, bool) or not isinstance(unit, int) or not 0 <= unit < n_units or where not in ("before", "after"):
        return None
    return unit if where == "before" else unit + 1


def _unit_texts(masked, spans, limit):
    out = []
    for s, e in spans:
        t = masked[s:e].strip()
        if limit and len(t) > limit:
            t = t[:limit].rstrip() + "\u2026"
        out.append(t)
    return out


def _short(text, n=80):
    text = " ".join(text.split())
    return text if len(text) <= n else text[:n].rstrip() + "..."


def run_pipeline(*, input_type, text, pdf_bytes=None, rules, brand, judge, cfg, image_bytes=None):
    notes, scanned, doc, image, low_ocr = [], False, None, None, False
    if input_type == "pdf":
        doc = open_pdf(pdf_bytes, cfg["MAX_PDF_PAGES"])
        text, scanned, note = extract_pdf_text(doc)
        if note:
            notes.append(note)
        if not text.strip():
            raise ContentError(note or "No readable text was found in the PDF.")
    elif input_type == "image":
        image = open_image(image_bytes, cfg["MAX_IMAGE_PIXELS"])
        text, confidence = ocr_image(image, cfg)
        if not text.strip():
            raise ContentError("No readable text was found in the image.")
        if confidence is None or confidence < cfg["OCR_LOW_CONFIDENCE"]:
            low_ocr = True
            notes.append("The text in this image was hard to read (low OCR confidence). Misread words can hide problems or "
                         "create false ones, so please review the result carefully.")
        else:
            notes.append(f"The text was read from the image with OCR (confidence {confidence:.0f}%). Some words may be misread.")

    issues = exact_checks(text, [r for r in rules if r["kind"] != "tone"], cfg["DEFAULT_REPLACEMENT"])
    working = substitute_banned(text, issues)

    tone_rules = [r for r in rules if r["kind"] == "tone"]
    missing = [i for i in issues if i["type"] == "must_include"]
    needs_review, answers, err, mapping = low_ocr, None, None, {}
    limit = cfg["MAX_LLM_CHARS"]
    part = working[:limit]
    truncated = len(working) > len(part)
    ask_place = bool(missing) and not truncated
    if truncated and tone_rules:
        notes.append(f"Tone / Style rules were checked on the first {limit} characters only.")
    if tone_rules or ask_place:
        masked, mapping = redact(part)
        spans, masked_spans = split_units(part), split_units(masked)
        if len(spans) != len(masked_spans):
            err = "the text could not be split into lines"
        else:
            texts = _unit_texts(masked, masked_spans, None if tone_rules else cfg["PLACEMENT_UNIT_CHARS"])
            answers, err = judge(texts, tone_rules, [i["rule"] for i in missing] if ask_place else [])

    if tone_rules:
        unchecked = []
        for idx, r in enumerate(tone_rules):
            ans = ((answers or {}).get("tone") or {}).get(idx)
            if not isinstance(ans, dict) or not isinstance(ans.get("match"), bool):
                unchecked.append(r["text"])
            elif not ans["match"]:
                why = " ".join(restore(str(ans.get("why") or ""), mapping).split()[: cfg["LLM_REASON_WORDS"]])
                issues.append(_issue(
                    "tone", r["text"], manual=True,
                    problem=f"The text does not match this tone guideline: {why}" if why else "The text does not match this tone guideline.",
                    suggestion=f'Manual editing needed: revise the text to match "{r["text"]}".'))
        if answers is None:
            needs_review = True
            notes.append(f"Tone / Style rules could not be checked ({err}). Please review them manually.")
        elif unchecked:
            needs_review = True
            notes.append("These Tone / Style rules could not be checked: " + ", ".join(f'"{t}"' for t in unchecked)
                         + ". Please review them manually.")

    if missing:
        spans = split_units(working)
        fallback = []
        for n, issue in enumerate(missing):
            gap = _gap_from(((answers or {}).get("place") or {}).get(n), len(spans)) if ask_place else None
            phrase = issue["replace_with"]
            issue["gap"] = gap
            if gap is None:
                fallback.append(phrase)
                issue["manual"] = True
                if spans:
                    issue["excerpt"] = _short(working[spans[-1][0]:spans[-1][1]])
                issue["suggestion"] = f'Added "{phrase}" at the end because a better spot could not be determined. Manual check needed: confirm the position.'
            else:
                where = "at the start, before this line" if gap == 0 else (
                    "at the end, after this line" if gap == len(spans) else "after this line")
                ref = spans[0] if gap == 0 else spans[gap - 1]
                issue["excerpt"] = _short(working[ref[0]:ref[1]])
                issue["suggestion"] = f'Add "{phrase}" {where}.'
        if fallback:
            if truncated:
                notes.append(f"The text is longer than the {limit}-character analysis limit, so required text was added at the end.")
            else:
                notes.append("Could not find a confident spot for " + ", ".join(f'"{p}"' for p in fallback)
                             + ", so it was added at the end. Please check the position.")

    corrected = insert_phrases(working, [(i["gap"], i["replace_with"]) for i in issues if i["fix_kind"] == "append"])
    issues += verify_final(corrected, [r for r in rules if r["kind"] != "tone"])

    if input_type in ("pdf", "image"):
        has_logo, has_colors = bool(brand.get("logo")), bool(brand.get("colors"))
        if has_logo or has_colors:
            pages = render_pages(doc, cfg["VISUAL_MAX_PAGES"]) if input_type == "pdf" else [image_page(image)]
        if has_logo:
            if logo_score(pages, brand["logo"]) < cfg["LOGO_MATCH_THRESHOLD"]:
                where = f"in the first {len(pages)} page(s)" if input_type == "pdf" else "in the image"
                issues.append(_issue(
                    "logo", "Brand logo", problem=f"The brand logo was not found {where}.",
                    suggestion="Add the approved logo at its original proportions."))
        else:
            notes.append("No brand logo has been uploaded, so the logo check was skipped. A logo can be added on the Guidelines page.")
        if has_colors:
            issues += color_check(pages, brand["colors"], cfg["COLOR_TOLERANCES"][brand["tolerance"]], cfg["COLOR_MIN_SHARE"])
        else:
            notes.append("No brand colors have been set, so the color check was skipped. Colors can be added on the Guidelines page.")
    elif brand.get("logo") or brand.get("colors"):
        notes.append("Logo and color checks apply to PDFs and images only, so they were skipped for plain text.")
    issues[:] = unique_issues(issues)

    result = {"issues": issues, "notes": notes, "needs_review": needs_review, "corrected_text": corrected,
              "manual_edit": any(i.get("manual") for i in issues)}
    if not issues:
        return result

    if input_type == "text":
        result.update(output=corrected.encode("utf-8"), output_name="corrected_text.txt", mimetype="text/plain")
        return result
    files = {}
    if input_type == "pdf":
        edited, edit_notes = edit_pdf(pdf_bytes, issues, scanned=scanned)
        if edit_notes:
            result["notes"] += edit_notes
        if edited:
            files["corrected.pdf"] = edited
    files["corrected_text.txt"] = corrected
    files["report.pdf"] = reports.upload_report(input_type, issues, result["notes"], utcnow())
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for name, content in files.items():
            z.writestr(name, content)
    result.update(output=buf.getvalue(), output_name="thirdeye_corrected.zip", mimetype="application/zip")
    return result
