import re
from datetime import datetime

from models import Insight, IssueCounter, db, iso, utcnow

TIPS = {
    "must_not_use": "Add this word to your team's avoid-list and search for it before publishing.",
    "must_include": "Add the required line to your content template so it is never left out.",
    "tone": "Review your tone guideline with the team and keep a short checklist beside your drafts.",
    "logo": "Use the approved logo file at its original proportions, and keep it clear of other elements.",
    "color": "Copy the exact hex codes from your guidelines into your design tool's palette.",
}


def normalize_key(key):
    kind, sep, rest = key.partition(":")
    return f"{kind}:{' '.join(rest.lower().split())}" if sep else key


def rule_from_label(label):
    m = re.search(r'"(.*)"', label or "")
    return m.group(1) if m else None


def tip_for(issue_type, label):
    rule = rule_from_label(label)
    if rule:
        if issue_type == "must_not_use":
            return f'Add "{rule}" to your team\'s avoid-list and search for it before publishing.'
        if issue_type == "must_include":
            return f'Add "{rule}" to your content template so it is never left out.'
        if issue_type == "tone":
            return f'Review the "{rule}" tone guideline with the team and keep a short checklist beside your drafts.'
    return TIPS[issue_type]


def record_approved(issues, threshold):
    seen = set()
    for issue in issues:
        key = normalize_key(issue["key"])
        if key in seen:
            continue
        seen.add(key)
        counter = db.session.get(IssueCounter, key)
        if counter is None:
            counter = IssueCounter(issue_key=key, label=issue["label"], issue_type=issue["type"], count=0)
            db.session.add(counter)
        counter.count += 1
        if counter.count >= threshold:
            counter.count = 0
            insight = db.session.get(Insight, key)
            if insight is None:
                insight = Insight(issue_key=key, label=issue["label"], issue_type=issue["type"], times_triggered=0)
                db.session.add(insight)
            insight.times_triggered += 1
            insight.last_triggered = utcnow()


def merge_duplicates():
    for model, fields in ((IssueCounter, ("count",)), (Insight, ("times_triggered",))):
        groups = {}
        for row in model.query.all():
            groups.setdefault(normalize_key(row.issue_key), []).append(row)
        for key, rows in groups.items():
            if len(rows) == 1 and rows[0].issue_key == key:
                continue
            newest = max(rows, key=lambda r: getattr(r, "last_triggered", None) or datetime.min)
            merged = dict(issue_key=key, label=newest.label, issue_type=newest.issue_type)
            for f in fields:
                merged[f] = sum(getattr(r, f) or 0 for r in rows)
            if model is Insight:
                merged["last_triggered"] = max((r.last_triggered for r in rows if r.last_triggered), default=utcnow())
            for r in rows:
                db.session.delete(r)
            db.session.flush()
            db.session.add(model(**merged))


def get_insights(limit, threshold):
    grouped = {}
    for r in Insight.query.order_by(Insight.last_triggered.desc()).all():
        key = normalize_key(r.issue_key)
        if key in grouped:
            grouped[key]["times"] += r.times_triggered
        else:
            grouped[key] = {"row": r, "times": r.times_triggered}
    items = []
    for entry in list(grouped.values())[:limit]:
        r = entry["row"]
        items.append({
            "issue": r.label,
            "type": r.issue_type,
            "occurrences": entry["times"] * threshold,
            "tips": [tip_for(r.issue_type, r.label)],
            "last_triggered": iso(r.last_triggered),
        })
    return items
