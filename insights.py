from models import Insight, IssueCounter, db, iso, utcnow

TIPS = {
    "must_not_use": "Add this word to your team's avoid-list and search for it before publishing.",
    "must_include": "Add the required line to your content template so it is never left out.",
    "tone": "Review your tone guideline with the team and keep a short checklist beside your drafts.",
    "logo": "Use the approved logo file at its original proportions, and keep it clear of other elements.",
    "color": "Copy the exact hex codes from your guidelines into your design tool's palette.",
}


def record_approved(issues, threshold):
    seen = set()
    for issue in issues:
        key = issue["key"]
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


def get_insights(limit, threshold):
    rows = Insight.query.order_by(Insight.last_triggered.desc()).limit(limit).all()
    return [
        {
            "issue": r.label,
            "type": r.issue_type,
            "occurrences": r.times_triggered * threshold,
            "tips": [TIPS[r.issue_type]],
            "last_triggered": iso(r.last_triggered),
        }
        for r in rows
    ]
