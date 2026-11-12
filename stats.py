import json
from collections import Counter
from datetime import timedelta, timezone

from models import ReportEvent, Submission, User, db, utcnow

CONTENT_TYPES = ("Text", "PDF", "Image")
RESOLVED = ("Approved", "Rejected")


def content_label(input_type):
    return {"pdf": "PDF", "image": "Image"}.get(input_type, "Text")


def describe(issues):
    types = Counter(i["type"] for i in issues)
    labels = [i["label"][:200] for i in issues][:40]
    fixes = sum(1 for i in issues if i.get("fix_kind", "none") != "none")
    manual = any(i.get("manual") for i in issues)
    return dict(issue_count=len(issues), fix_count=fixes, manual_edit=manual,
                issue_types_json=json.dumps(dict(types)), issue_labels_json=json.dumps(labels))


def record_check(user, input_type, issues, sub=None):
    clean = not issues
    now = utcnow()
    event = ReportEvent(org_id=user.org_id, user_id=user.id, username=user.username, content_type=content_label(input_type),
                        status="Clean" if clean else "Pending", created_at=now, resolved_at=now if clean else None,
                        **describe(issues))
    db.session.add(event)
    db.session.flush()
    if sub is not None:
        sub.event_id = event.id
    return event


def event_for(sub):
    event = db.session.get(ReportEvent, sub.event_id) if sub.event_id else None
    if event is None:
        event = ReportEvent(org_id=sub.org_id, user_id=sub.user_id, username=sub.username,
                            content_type=content_label(sub.input_type), status="Pending", created_at=sub.created_at,
                            **describe(sub.issues))
        db.session.add(event)
        db.session.flush()
        sub.event_id = event.id
    return event


def record_decision(sub, status, by, remark=None):
    event = event_for(sub)
    event.status = status
    event.resolved_at = sub.resolved_at or utcnow()
    event.resolved_by = by
    event.remark = remark or None
    sub.remark = remark or None


def mark_expired(sub, ttl_minutes):
    event = event_for(sub)
    if event.status == "Pending":
        event.status = "Expired"
        event.resolved_at = (sub.created_at or utcnow()) + timedelta(minutes=ttl_minutes)


def expire_drafts(ttl_minutes, org_id=None):
    query = Submission.query.filter(Submission.status == "Draft", Submission.created_at < utcnow() - timedelta(minutes=ttl_minutes))
    if org_id is not None:
        query = query.filter(Submission.org_id == org_id)
    stale = query.all()
    for sub in stale:
        mark_expired(sub, ttl_minutes)
        db.session.delete(sub)
    if stale:
        db.session.commit()
    return len(stale)


def retire_user_submissions(user_id, ttl_minutes):
    for sub in Submission.query.filter(Submission.user_id == user_id, Submission.status.in_(("Draft", "Pending"))).all():
        mark_expired(sub, ttl_minutes)


def backfill():
    count = 0
    for sub in Submission.query.order_by(Submission.id).all():
        if sub.event_id:
            continue
        status = sub.status if sub.status in RESOLVED else "Pending"
        event = ReportEvent(org_id=sub.org_id, user_id=sub.user_id, username=sub.username, content_type=content_label(sub.input_type),
                            status=status, created_at=sub.created_at, resolved_at=sub.resolved_at, resolved_by=sub.resolved_by,
                            remark=sub.remark, **describe(sub.issues))
        db.session.add(event)
        db.session.flush()
        sub.event_id = event.id
        count += 1
    db.session.commit()
    return count


def user_counts(user):
    rows = db.session.query(ReportEvent.status, db.func.count(ReportEvent.id)) \
        .filter(ReportEvent.org_id == user.org_id, ReportEvent.user_id == user.id).group_by(ReportEvent.status).all()
    by = dict(rows)
    return {"uploads": sum(by.values()), "approved": by.get("Approved", 0), "rejected": by.get("Rejected", 0),
            "pending": by.get("Pending", 0)}


def org_summary(org_id, days=30, zone=None):
    zone = zone or timezone.utc
    roles = dict(db.session.query(User.role, db.func.count(User.id)).filter(User.org_id == org_id).group_by(User.role).all())
    rows = db.session.query(ReportEvent.status, ReportEvent.content_type, ReportEvent.issue_count, ReportEvent.fix_count,
                            ReportEvent.issue_types_json, ReportEvent.issue_labels_json, ReportEvent.created_at) \
        .filter(ReportEvent.org_id == org_id).all()
    status, usage, revised, labels, kinds, per_day = Counter(), Counter(), Counter(), Counter(), Counter(), Counter()
    issues_found = 0
    for st, ctype, count, fixes, types_json, labels_json, created in rows:
        status[st] += 1
        usage[ctype] += 1
        issues_found += count or 0
        if st == "Approved":
            revised[ctype] += fixes or 0
        if count:
            labels.update(json.loads(labels_json or "[]"))
            kinds.update(json.loads(types_json or "{}"))
        if created:
            per_day[created.replace(tzinfo=timezone.utc).astimezone(zone).date()] += 1
    today = utcnow().replace(tzinfo=timezone.utc).astimezone(zone).date()
    activity = [((today - timedelta(days=d)).strftime("%b %d"), per_day.get(today - timedelta(days=d), 0))
                for d in range(days - 1, -1, -1)]
    kind_names = {"must_not_use": "Must not use", "must_include": "Must include", "tone": "Tone / Style", "logo": "Logo", "color": "Color"}
    return {
        "roles": roles, "total": len(rows), "clean": status["Clean"], "approved": status["Approved"], "rejected": status["Rejected"],
        "pending": status["Pending"], "expired": status["Expired"], "issues_found": issues_found,
        "usage": sorted(((t, usage[t]) for t in CONTENT_TYPES), key=lambda kv: (-kv[1], CONTENT_TYPES.index(kv[0]))),
        "revised": sorted(((t, revised[t]) for t in CONTENT_TYPES), key=lambda kv: (-kv[1], CONTENT_TYPES.index(kv[0]))),
        "top_issues": labels.most_common(8),
        "issue_types": [(kind_names.get(k, k), n) for k, n in kinds.most_common()],
        "activity": activity, "days": days,
    }


def history_rows(org_id, user_id=None, limit=None):
    query = ReportEvent.query.filter_by(org_id=org_id)
    if user_id is not None:
        query = query.filter_by(user_id=user_id)
    total = query.count()
    query = query.order_by(ReportEvent.created_at.desc(), ReportEvent.id.desc())
    if limit:
        query = query.limit(limit)
    out = []
    for e in query.yield_per(500):
        out.append({"when": e.resolved_at or e.created_at, "username": e.username, "content_type": e.content_type,
                    "issue_count": e.issue_count, "status": e.status, "remark": e.remark})
    return out, total
