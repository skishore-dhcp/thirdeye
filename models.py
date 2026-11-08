import json
from datetime import datetime, timezone

from flask_sqlalchemy import SQLAlchemy

db = SQLAlchemy()


def utcnow():
    return datetime.now(timezone.utc).replace(tzinfo=None)


def iso(dt):
    return dt.isoformat() + "Z" if dt else None


class User(db.Model):
    __tablename__ = "users"
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(40), unique=True, nullable=False)
    password_hash = db.Column(db.String(255), nullable=False)
    role = db.Column(db.String(20), nullable=False, default="Member")
    created_at = db.Column(db.DateTime, default=utcnow)

    @property
    def is_authorized(self):
        return self.role == "Authorized"


class Guideline(db.Model):
    __tablename__ = "guidelines"
    id = db.Column(db.Integer, primary_key=True)
    kind = db.Column(db.String(20), nullable=False)
    text = db.Column(db.String(200), nullable=False)
    replacement = db.Column(db.String(200))
    created_by = db.Column(db.String(40))
    created_at = db.Column(db.DateTime, default=utcnow)


class Setting(db.Model):
    __tablename__ = "settings"
    key = db.Column(db.String(80), primary_key=True)
    value = db.Column(db.String(255), nullable=False, default="")


class DefaultRule(db.Model):
    __tablename__ = "default_rules"
    id = db.Column(db.Integer, primary_key=True)
    kind = db.Column(db.String(20), nullable=False)
    text = db.Column(db.String(200), nullable=False)
    replacement = db.Column(db.String(200))
    __table_args__ = (db.UniqueConstraint("kind", "text"),)


class BrandSettings(db.Model):
    __tablename__ = "brand_settings"
    id = db.Column(db.Integer, primary_key=True)
    colors_json = db.Column(db.Text, default="[]")
    tolerance = db.Column(db.String(10), default="Normal")
    logo_blob = db.Column(db.LargeBinary)
    logo_name = db.Column(db.String(255))

    @property
    def colors(self):
        return json.loads(self.colors_json or "[]")


class Submission(db.Model):
    __tablename__ = "submissions"
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    username = db.Column(db.String(40), nullable=False)
    input_type = db.Column(db.String(10), nullable=False)
    status = db.Column(db.String(10), nullable=False, default="Draft")
    issues_json = db.Column(db.Text, default="[]")
    corrected_text = db.Column(db.Text)
    output_blob = db.Column(db.LargeBinary)
    output_name = db.Column(db.String(255))
    output_mimetype = db.Column(db.String(100))
    created_at = db.Column(db.DateTime, default=utcnow)
    resolved_at = db.Column(db.DateTime)
    resolved_by = db.Column(db.String(40))

    @property
    def issues(self):
        return json.loads(self.issues_json or "[]")


class IssueCounter(db.Model):
    __tablename__ = "issue_counters"
    issue_key = db.Column(db.String(300), primary_key=True)
    label = db.Column(db.String(300), nullable=False)
    issue_type = db.Column(db.String(20), nullable=False)
    count = db.Column(db.Integer, default=0, nullable=False)


class Insight(db.Model):
    __tablename__ = "insights"
    issue_key = db.Column(db.String(300), primary_key=True)
    label = db.Column(db.String(300), nullable=False)
    issue_type = db.Column(db.String(20), nullable=False)
    times_triggered = db.Column(db.Integer, default=0, nullable=False)
    last_triggered = db.Column(db.DateTime, default=utcnow)
