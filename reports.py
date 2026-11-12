import math
import re
from xml.sax.saxutils import escape

try:
    import pymupdf as fitz
except ImportError:
    import fitz

INK = "#25321f"
MUTED = "#566249"
SAGE = "#718a66"
CLAY = "#b4c8a4"
SOFT = "#f4ede0"
GLOW = "#faf5e8"
BAD = "#d9856f"
LINK = "#2f5430"
GOOD = "#8fbf86"
WHITE = "#ffffff"
FONT = "Helvetica, Arial, sans-serif"

KIND_NAMES = {
    "must_not_use": "Must not use", "must_include": "Must include", "tone": "Tone / Style",
    "logo": "Logo", "color": "Color",
}
STATUS_COLORS = {"Approved": LINK, "Rejected": "#8a2f22", "Clean": SAGE, "Pending": MUTED, "Expired": MUTED}


def _rgb(hex_color):
    h = hex_color.lstrip("#")
    return tuple(int(h[i:i + 2], 16) / 255 for i in (0, 2, 4))


def _plain(text):
    return " ".join("".join(c if (c.isprintable() or c.isspace()) else " " for c in str(text)).split())


def _label(text, limit=None):
    out = "".join(c if ord(c) < 0x250 else "?" for c in _plain(text))
    if limit and len(out) > limit:
        out = out[: limit - 3].rstrip() + "..."
    return escape(out)


def _svg(width, height, body, title):
    return (f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}" '
            f'role="img" aria-label="{_label(title)}"><title>{_label(title)}</title>{body}</svg>')


def _empty(width, height, title, message="No data yet"):
    body = (f'<rect x="0" y="0" width="{width}" height="{height}" rx="18" fill="{SOFT}"/>'
            f'<text x="{width / 2}" y="{height / 2 + 4}" text-anchor="middle" font-family="{FONT}" font-size="13" fill="{MUTED}">'
            f'{escape(message)}</text>')
    return _svg(width, height, body, title)


def svg_pie(slices, width, title):
    total = sum(v for _, v, _ in slices)
    r = max(30.0, min(62.0, width / 2 - 14))
    legend = 22 * len(slices)
    height = int(2 * r + 28 + legend)
    if total <= 0:
        return _empty(width, 130, title)
    cx, cy = width / 2, r + 8
    parts = []
    live = [s for s in slices if s[1] > 0]
    if len(live) == 1:
        parts.append(f'<circle cx="{cx}" cy="{cy}" r="{r}" fill="{live[0][2]}"/>')
    else:
        angle = -math.pi / 2
        for _, value, color in live:
            sweep = 2 * math.pi * value / total
            x1, y1 = cx + r * math.cos(angle), cy + r * math.sin(angle)
            x2, y2 = cx + r * math.cos(angle + sweep), cy + r * math.sin(angle + sweep)
            large = 1 if sweep > math.pi else 0
            parts.append(f'<path d="M{cx:.2f} {cy:.2f} L{x1:.2f} {y1:.2f} A{r} {r} 0 {large} 1 {x2:.2f} {y2:.2f} Z" '
                         f'fill="{color}" stroke="{GLOW}" stroke-width="2"/>')
            angle += sweep
    ly = 2 * r + 34
    left = max(8.0, width / 2 - 78)
    for label, value, color in slices:
        pct = round(100 * value / total)
        parts.append(f'<rect x="{left}" y="{ly - 10:.1f}" width="12" height="12" rx="3" fill="{color}"/>'
                     f'<text x="{left + 20}" y="{ly:.1f}" font-family="{FONT}" font-size="12" fill="{INK}">'
                     f'{_label(label, 18)}: {value} ({pct}%)</text>')
        ly += 22
    return _svg(width, height, "".join(parts), title)


def svg_bars(items, width, title, color=SAGE, empty_message="No data yet"):
    items = [(a, b) for a, b in items if b > 0]
    if not items:
        return _empty(width, 130, title, empty_message)
    row = 30
    height = 14 + row * len(items)
    label_w = min(200, max(110, int(width * 0.42)))
    room = max(40, width - label_w - 56)
    top = max(v for _, v in items)
    parts = []
    for n, (label, value) in enumerate(items):
        y = 8 + n * row
        w = max(18.0, room * value / top)
        parts.append(f'<text x="{label_w - 8}" y="{y + 16}" text-anchor="end" font-family="{FONT}" font-size="11.5" fill="{INK}">'
                     f'{_label(label, int(label_w / 6.2))}</text>'
                     f'<rect x="{label_w}" y="{y + 3}" width="{w:.1f}" height="18" rx="9" fill="{color}"/>'
                     f'<text x="{label_w + w + 8:.1f}" y="{y + 16}" font-family="{FONT}" font-size="11.5" font-weight="bold" fill="{INK}">{value}</text>')
    return _svg(width, height, "".join(parts), title)


def svg_line(points, width, title):
    height = 190
    if not points or max(v for _, v in points) <= 0:
        return _empty(width, height, title, "No activity in this period")
    left, right, top, bottom = 38, 14, 14, 30
    inner_w, inner_h = width - left - right, height - top - bottom
    peak = max(v for _, v in points)
    step = max(1, math.ceil(peak / 4))
    ceiling = step * 4
    parts = []
    for k in range(5):
        value = step * k
        y = top + inner_h - inner_h * value / ceiling
        parts.append(f'<line x1="{left}" y1="{y:.1f}" x2="{width - right}" y2="{y:.1f}" stroke="{CLAY}" stroke-width="1" stroke-dasharray="3 4"/>'
                     f'<text x="{left - 8}" y="{y + 4:.1f}" text-anchor="end" font-family="{FONT}" font-size="10.5" fill="{MUTED}">{value}</text>')
    count = len(points)
    xs = [left + (inner_w * n / (count - 1) if count > 1 else inner_w / 2) for n in range(count)]
    ys = [top + inner_h - inner_h * v / ceiling for _, v in points]
    line = " ".join(f"{x:.1f},{y:.1f}" for x, y in zip(xs, ys))
    area = f"{xs[0]:.1f},{top + inner_h:.1f} {line} {xs[-1]:.1f},{top + inner_h:.1f}"
    parts.append(f'<polygon points="{area}" fill="{CLAY}" fill-opacity="0.45"/>')
    parts.append(f'<polyline points="{line}" fill="none" stroke="{LINK}" stroke-width="2.5" stroke-linejoin="round" stroke-linecap="round"/>')
    for x, y, (_, v) in zip(xs, ys, points):
        if v > 0:
            parts.append(f'<circle cx="{x:.1f}" cy="{y:.1f}" r="3.2" fill="{LINK}"/>')
    marks = sorted({0, count // 2, count - 1})
    for n in marks:
        anchor = "start" if n == 0 and count > 1 else "end" if n == count - 1 and count > 1 else "middle"
        parts.append(f'<text x="{xs[n]:.1f}" y="{height - 10}" text-anchor="{anchor}" font-family="{FONT}" font-size="10.5" fill="{MUTED}">'
                     f'{_label(points[n][0])}</text>')
    return _svg(width, height, "".join(parts), title)


class Report:
    W, H, M = 595.0, 842.0, 42.0

    def __init__(self, title, subtitle):
        self.title = title
        self.doc = fitz.open()
        self.regular, self.bold = fitz.Font("helv"), fitz.Font("hebo")
        self.cjk = fitz.Font("cjk")
        self.page = None
        self.y = 0.0
        self.writers = {}
        self.lengths = {}
        self.new_page(first=True, subtitle=subtitle)

    @property
    def width(self):
        return self.W - 2 * self.M

    def flush(self):
        for color, writer in self.writers.items():
            writer.write_text(self.page, color=color)
        self.writers = {}

    def new_page(self, first=False, subtitle=""):
        if self.page is not None:
            self.flush()
        self.page = self.doc.new_page(-1, width=self.W, height=self.H)
        if first:
            self.page.draw_rect(fitz.Rect(0, 0, self.W, 96), color=None, fill=_rgb(SAGE))
            self.page.draw_rect(fitz.Rect(0, 90, self.W, 96), color=None, fill=_rgb(CLAY))
            self.text(self.M, 46, "ThirdEye", bold=True, size=11, color=WHITE)
            self.text(self.M, 72, self.title, bold=True, size=22, color=WHITE)
            self.y = 118.0
            if subtitle:
                for line in self.lines(subtitle, False, 9.5, self.width):
                    self.text(self.M, self.y, line, size=9.5, color=MUTED)
                    self.y += 13
                self.y += 8
        else:
            self.text(self.M, 30, f"ThirdEye  |  {self.title}", size=8.5, color=MUTED)
            self.page.draw_line((self.M, 38), (self.W - self.M, 38), color=_rgb(CLAY), width=1)
            self.y = 58.0

    def ensure(self, height):
        if self.y + height > self.H - self.M - 18:
            self.new_page()

    def prepare(self, text, bold=False):
        text = _plain(text)
        primary = self.bold if bold else self.regular
        if text.isascii():
            return primary, text
        wanted = [c for c in text if not c.isspace()]
        for font in (primary, self.cjk):
            if all(font.has_glyph(ord(c)) for c in wanted):
                return font, text
        best = max((primary, self.cjk), key=lambda f: sum(1 for c in wanted if f.has_glyph(ord(c))))
        return best, "".join(c if c.isspace() or best.has_glyph(ord(c)) else "?" for c in text)

    def measure(self, font, text, size):
        key = (id(font), text, size)
        if key not in self.lengths:
            if len(self.lengths) > 50000:
                self.lengths.clear()
            self.lengths[key] = font.text_length(text, fontsize=size)
        return self.lengths[key]

    def lines(self, text, bold, size, width):
        font, text = self.prepare(text, bold)
        if self.measure(font, text, size) <= width:
            return [text]
        out, line = [], ""
        for word in text.split():
            trial = f"{line} {word}".strip()
            if font.text_length(trial, fontsize=size) <= width:
                line = trial
                continue
            if line:
                out.append(line)
            line = ""
            while font.text_length(word, fontsize=size) > width and len(word) > 1:
                cut = len(word) - 1
                while cut > 1 and font.text_length(word[:cut], fontsize=size) > width:
                    cut -= 1
                out.append(word[:cut])
                word = word[cut:]
            line = word
        if line:
            out.append(line)
        return out or [""]

    def text(self, x, y, text, bold=False, size=10.0, color=INK, anchor="left", width=0):
        font, drawn = self.prepare(text, bold)
        if not drawn:
            return
        if anchor == "center":
            x += (width - self.measure(font, drawn, size)) / 2
        elif anchor == "right":
            x += width - self.measure(font, drawn, size)
        key = _rgb(color)
        if key not in self.writers:
            self.writers[key] = fitz.TextWriter(self.page.rect)
        self.writers[key].append((x, y), drawn, font=font, fontsize=size)

    def box(self, rect, fill=SOFT, radius=0.12):
        self.page.draw_rect(rect, color=None, fill=_rgb(fill), radius=radius or None)

    def heading(self, text, need=40):
        self.ensure(40 + need)
        self.y += 10
        self.text(self.M, self.y + 10, text, bold=True, size=13, color=LINK)
        self.page.draw_line((self.M, self.y + 17), (self.W - self.M, self.y + 17), color=_rgb(CLAY), width=1.5)
        self.y += 30

    def paragraph(self, text, size=9.5, color=MUTED):
        for line in self.lines(text, False, size, self.width):
            self.ensure(size * 1.5)
            self.text(self.M, self.y + size, line, size=size, color=color)
            self.y += size * 1.45
        self.y += 6

    def metrics(self, items, per_row=4):
        gap, box_h = 10.0, 58.0
        for start in range(0, len(items), per_row):
            row = items[start:start + per_row]
            self.ensure(box_h + gap)
            box_w = (self.width - gap * (per_row - 1)) / per_row
            for n, (label, value) in enumerate(row):
                x = self.M + n * (box_w + gap)
                self.box(fitz.Rect(x, self.y, x + box_w, self.y + box_h), SOFT, 0.18)
                self.text(x + 12, self.y + 28, str(value), bold=True, size=19, color=LINK)
                for k, line in enumerate(self.lines(label.upper(), False, 7.2, box_w - 20)[:2]):
                    self.text(x + 12, self.y + 42 + k * 9, line, size=7.2, color=MUTED)
            self.y += box_h + gap

    def chart(self, svg, caption=None, x=None, width=None, advance=True):
        source = fitz.open("svg", svg.encode("utf-8"))
        pdf = fitz.open("pdf", source.convert_to_pdf())
        rect = source[0].rect
        w = width or min(rect.width, self.width)
        h = rect.height * w / rect.width
        x = self.M if x is None else x
        if advance:
            self.ensure(h + 26)
        top = self.y + (14 if caption else 0)
        if caption:
            self.text(x, self.y + 9, caption, bold=True, size=9.5, color=INK)
        self.page.show_pdf_page(fitz.Rect(x, top, x + w, top + h), pdf, 0)
        if advance:
            self.y = top + h + 12
        return top + h

    def chart_row(self, left_svg, left_caption, right_svg, right_caption):
        gap = 16.0
        half = (self.width - gap) / 2
        sizes = []
        for svg in (left_svg, right_svg):
            rect = fitz.open("svg", svg.encode("utf-8"))[0].rect
            sizes.append(rect.height * half / rect.width)
        self.ensure(max(sizes) + 30)
        end_left = self.chart(left_svg, left_caption, x=self.M, width=half, advance=False)
        end_right = self.chart(right_svg, right_caption, x=self.M + half + gap, width=half, advance=False)
        self.y = max(end_left, end_right) + 12

    def table(self, columns, rows, size=8.0):
        total = sum(w for _, w in columns)
        widths = [self.width * w / total for _, w in columns]
        pad, lead = 5.0, size * 1.35

        def header():
            self.ensure(24)
            self.box(fitz.Rect(self.M, self.y, self.W - self.M, self.y + 18), CLAY, 0.3)
            x = self.M
            for (title, _), w in zip(columns, widths):
                self.text(x + pad, self.y + 12.5, title, bold=True, size=size, color=INK)
                x += w
            self.y += 22

        header()
        for n, row in enumerate(rows):
            cells = []
            for value, w in zip(row, widths):
                color = INK
                if isinstance(value, tuple):
                    value, color = value
                cells.append((self.lines(value, False, size, w - 2 * pad), color))
            height = max(len(c[0]) for c in cells) * lead + 6
            if self.y + height > self.H - self.M - 18:
                self.new_page()
                header()
            if n % 2 == 0:
                self.box(fitz.Rect(self.M, self.y - 2, self.W - self.M, self.y + height - 2), GLOW, 0)
            x = self.M
            for (lines, color), w in zip(cells, widths):
                for k, line in enumerate(lines):
                    self.text(x + pad, self.y + size + 1 + k * lead, line, size=size, color=color)
                x += w
            self.y += height
        self.y += 8

    def issue_card(self, number, issue):
        pad = 12.0
        inner = self.width - 2 * pad
        head = f"{number}.  {KIND_NAMES.get(issue['type'], issue['type'])}"
        blocks = [(self.lines(issue["problem"] or "-", True, 9.5, inner), True, INK)]
        if issue.get("excerpt"):
            blocks.append((self.lines(f"Text: {issue['excerpt']}", False, 9, inner), False, MUTED))
        blocks.append((self.lines(f"Fix: {issue['suggestion'] or '-'}", False, 9, inner), False, MUTED))
        height = pad * 2 + 16 + sum(len(lines) * 12.5 + 3 for lines, _, _ in blocks)
        self.ensure(height + 10)
        self.box(fitz.Rect(self.M, self.y, self.W - self.M, self.y + height), SOFT, 0.06)
        if issue.get("manual"):
            self.page.draw_rect(fitz.Rect(self.M, self.y + 10, self.M + 4, self.y + height - 10), color=None, fill=_rgb(BAD))
        cy = self.y + pad + 9
        self.text(self.M + pad, cy, head, bold=True, size=10, color=LINK)
        if issue.get("manual"):
            self.text(self.M + pad, cy, "MANUAL EDIT", bold=True, size=8, color="#8a2f22", anchor="right", width=inner)
        cy += 7
        for lines, bold, color in blocks:
            for line in lines:
                cy += 12.5
                self.text(self.M + pad, cy, line, bold=bold, size=9.5 if bold else 9, color=color)
            cy += 3
        self.y += height + 10

    def finish(self):
        self.flush()
        count = self.doc.page_count
        for n, page in enumerate(self.doc, 1):
            self.page = page
            self.text(self.M, self.H - 24, "Generated by ThirdEye", size=8, color=MUTED)
            self.text(self.M, self.H - 24, f"Page {n} of {count}", size=8, color=MUTED, anchor="right", width=self.width)
            self.flush()
        data = self.doc.tobytes(garbage=3, deflate=True)
        self.doc.close()
        return data


def svg_height(svg):
    m = re.search(r'height="(\d+)"', svg)
    return int(m.group(1)) + 26 if m else 120


def stamp(moment):
    return moment.strftime("%Y-%m-%d %H:%M UTC") if moment else "-"


def upload_report(input_type, issues, notes, moment):
    label = {"pdf": "PDF", "image": "Image"}.get(input_type, "Text")
    manual = sum(1 for i in issues if i.get("manual"))
    auto = sum(1 for i in issues if i.get("fix_kind", "none") != "none" and not i.get("manual"))
    rep = Report("Content check report", f"Generated {stamp(moment)}")
    rep.metrics([("Content type", label), ("Issues found", len(issues)), ("Fixed automatically", auto), ("Manual editing needed", manual)])
    if manual:
        rep.paragraph("MANUAL EDITING NEEDED: items marked MANUAL EDIT cannot be fixed automatically.", 9.5, "#8a2f22")
    counts = {}
    for i in issues:
        name = KIND_NAMES.get(i["type"], i["type"])
        counts[name] = counts.get(name, 0) + 1
    rep.chart(svg_bars(sorted(counts.items(), key=lambda kv: -kv[1]), int(rep.width), "Issues by type", SAGE),
              caption="Issues by type")
    rep.heading("Issues", 120)
    for n, issue in enumerate(issues, 1):
        rep.issue_card(n, issue)
    if notes:
        rep.heading("Notes")
        for note in notes:
            rep.paragraph("- " + note, 9.5, INK)
    return rep.finish()


def org_charts(summary, full, half):
    return {
        "pie": svg_pie([("Approved", summary["approved"], GOOD), ("Rejected", summary["rejected"], BAD)], half,
                       "Approvals versus rejections"),
        "usage": svg_bars(summary["usage"], half, "Most used content types", SAGE),
        "issues": svg_bars(summary["top_issues"], full, "Most common issues", LINK, "No issues recorded yet"),
        "revised": svg_bars(summary["revised"], half, "Most revised content types", CLAY, "No approved corrections yet"),
        "activity": svg_line(summary["activity"], full, "Checks per day"),
    }


def org_metrics(summary):
    roles = summary["roles"]
    return [("Admins", roles.get("Admin", 0)), ("Reviewers", roles.get("Authorized", 0)), ("Members", roles.get("Member", 0)),
            ("Total checks", summary["total"]), ("Approvals", summary["approved"]), ("Rejections", summary["rejected"]),
            ("Pending", summary["pending"]), ("Issues found", summary["issues_found"])]


def org_report(org_name, org_id, summary, moment, days):
    rep = Report("Organization report", f"{_plain(org_name)} (ID {org_id})  |  Generated {stamp(moment)}")
    rep.metrics(org_metrics(summary))
    charts = org_charts(summary, int(rep.width), int(rep.width / 2 - 8))
    rep.heading("Approvals and content", 220)
    rep.chart_row(charts["pie"], "Approvals versus rejections", charts["usage"], "Most used content types")
    rep.heading("Issues", svg_height(charts["issues"]))
    rep.chart(charts["issues"], caption="Most common issues")
    rep.heading("Revisions", svg_height(charts["revised"]))
    rep.chart(charts["revised"], caption="Most revised content types (corrections applied in approved requests)")
    rep.heading("Activity", svg_height(charts["activity"]))
    rep.chart(charts["activity"], caption=f"Checks per day, last {days} days")
    return rep.finish()


def history_report(org_name, org_id, username, role, rows, show_user, moment, total=None):
    scope = "All members" if show_user else f"Only your own entries ({_plain(username)})"
    total = len(rows) if total is None else total
    count = f"{len(rows)} entries" if total <= len(rows) else f"newest {len(rows)} of {total} entries"
    rep = Report("Full history", f"{_plain(org_name)} (ID {org_id})  |  {scope}  |  Generated {stamp(moment)}  |  {count}")
    columns = [("Date and Time", 17), ("Content Type", 11), ("Issues Found", 12), ("Status", 10), ("Remark", 28)]
    if show_user:
        columns.insert(0, ("Username", 13))
    table = []
    for r in rows:
        line = [stamp(r["when"]), r["content_type"], str(r["issue_count"]), (r["status"], STATUS_COLORS.get(r["status"], INK)),
                r["remark"] or "-"]
        if show_user:
            line.insert(0, r["username"])
        table.append(line)
    if table:
        rep.table(columns, table)
    else:
        rep.paragraph("There are no entries yet.")
    return rep.finish()
