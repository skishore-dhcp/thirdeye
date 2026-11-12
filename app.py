import hmac
import io
import json
import math
import os
import re
import secrets
import time
from datetime import timedelta
from functools import wraps

from flask import (Flask, abort, flash, g, get_flashed_messages, jsonify, redirect, render_template,
                   request, send_file, session, url_for)
from jinja2 import TemplateNotFound
from sqlalchemy import func, inspect, text as sql_text
from werkzeug.security import check_password_hash, generate_password_hash

import checks
import insights
import llm
import reports
import stats
from config import Config
from models import (Alert, BrandSettings, DefaultRule, Guideline, Insight, IssueCounter, Organization, ReportEvent, Setting, Submission,
                    User, db, iso, utcnow)

HEX_RE = re.compile(r"^#?[0-9a-fA-F]{6}$")
USERNAME_RE = re.compile(r"^[A-Za-z0-9_.-]{3,30}$")
PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"
CSRF_EXEMPT = {"logout"}


def create_app(overrides=None):
    app = Flask(__name__)
    app.config.from_object(Config)
    if overrides:
        app.config.update(overrides)
    app.config["MAX_CONTENT_LENGTH"] = max(app.config["MAX_PDF_BYTES"], app.config["MAX_IMAGE_BYTES"]) + 1024 * 1024
    db.init_app(app)
    with app.app_context():
        init_db(app)
    register(app)
    if not app.testing:
        if not os.environ.get("SECRET_KEY"):
            app.logger.warning("SECRET_KEY is not set. A random one is used, so everyone is logged out on every restart.")
        if app.config["DEMO_MODE"]:
            app.logger.warning("Demo mode is ON: demo accounts with public passwords exist. Set DEMO_MODE=0 for real use.")
    return app


def demo_account_specs(cfg):
    return [
        {"key": "admin", "label": "Try as Admin", "role": "Admin", "username": cfg["DEMO_ADMIN_USERNAME"],
         "password": cfg["DEMO_ADMIN_PASSWORD"], "about": "Owns the organization. Can do everything a reviewer can."},
        {"key": "reviewer", "label": "Try as Reviewer", "role": "Authorized", "username": cfg["DEMO_USERNAME"],
         "password": cfg["DEMO_PASSWORD"], "about": "Can approve requests and edit the guidelines."},
        {"key": "member", "label": "Try as Member", "role": "Member", "username": cfg["DEMO_MEMBER_USERNAME"],
         "password": cfg["DEMO_MEMBER_PASSWORD"], "about": "Can run checks (they need a reviewer's approval). Cannot edit the guidelines."},
    ]


def brand_for(org_id):
    brand = BrandSettings.query.filter_by(org_id=org_id).first()
    if brand is None:
        brand = BrandSettings(org_id=org_id, colors_json="[]", tolerance="Normal")
        db.session.add(brand)
        db.session.commit()
    return brand


def seed_sample_rules(cfg, org_id):
    existing = {(r.kind, r.text.lower()) for r in Guideline.query.filter_by(org_id=org_id)}
    for entry in cfg["SAMPLE_RULES"]:
        kind, text = entry[0], entry[1]
        replacement = entry[2] if len(entry) > 2 else None
        if (kind, text.lower()) not in existing:
            db.session.add(Guideline(org_id=org_id, kind=kind, text=text, replacement=replacement, created_by="sample"))


def ensure_demo_accounts(cfg):
    demo = cfg["DEMO_MODE"]
    org_id = cfg["DEMO_ORG_ID"]
    for spec in demo_account_specs(cfg):
        user = User.query.filter(User.org_id == org_id, func.lower(User.username) == spec["username"].lower()).first()
        if demo:
            if user is None:
                db.session.add(User(org_id=org_id, username=spec["username"], role=spec["role"],
                                    password_hash=generate_password_hash(spec["password"])))
            else:
                user.role = spec["role"]
                if not check_password_hash(user.password_hash, spec["password"]):
                    user.password_hash = generate_password_hash(spec["password"])
        elif user is not None and check_password_hash(user.password_hash, spec["password"]):
            user.password_hash = generate_password_hash(secrets.token_hex(32))


def column_names(table):
    return {c["name"] for c in inspect(db.engine).get_columns(table)}


def init_db(app):
    cfg = app.config
    demo_org = cfg["DEMO_ORG_ID"]
    postgres = db.engine.dialect.name == "postgresql"

    def ddl(statement, **params):
        db.session.execute(sql_text(statement), params)
        db.session.commit()

    for table in ("issue_counters", "insights"):
        if inspect(db.engine).has_table(table) and "org_id" not in column_names(table):
            ddl(f"DROP TABLE {table}")
    db.create_all()
    flag_false = "FALSE" if postgres else "0"
    for table in ("guidelines", "default_rules"):
        if "replacement" not in column_names(table):
            ddl(f"ALTER TABLE {table} ADD COLUMN replacement VARCHAR(200)")
    if "alerts_seen_at" not in column_names("users"):
        ddl("ALTER TABLE users ADD COLUMN alerts_seen_at TIMESTAMP")
    if "tour_seen" not in column_names("users"):
        ddl(f"ALTER TABLE users ADD COLUMN tour_seen BOOLEAN NOT NULL DEFAULT {flag_false}")
    if "remark" not in column_names("submissions"):
        ddl("ALTER TABLE submissions ADD COLUMN remark VARCHAR(300)")
    if "event_id" not in column_names("submissions"):
        ddl("ALTER TABLE submissions ADD COLUMN event_id INTEGER")
    added = [t for t in ("users", "guidelines", "brand_settings", "submissions") if "org_id" not in column_names(t)]
    for table in added:
        ddl(f"ALTER TABLE {table} ADD COLUMN org_id INTEGER REFERENCES organizations (id)")
    if db.session.get(Organization, demo_org) is None:
        db.session.add(Organization(id=demo_org, name=cfg["DEMO_ORG_NAME"], created_by="system"))
        db.session.commit()
    for table in ("users", "guidelines", "brand_settings", "submissions"):
        ddl(f"UPDATE {table} SET org_id = :org WHERE org_id IS NULL", org=demo_org)
    stats.backfill()
    if postgres:
        for table in ("organizations", "users", "guidelines", "default_rules", "brand_settings", "submissions", "alerts", "report_events"):
            seq = db.session.execute(sql_text("SELECT pg_get_serial_sequence(:t, 'id')"), {"t": table}).scalar()
            if seq:
                top = db.session.execute(sql_text(f"SELECT COALESCE(MAX(id), 0) FROM {table}")).scalar()
                last, called = db.session.execute(sql_text(f"SELECT last_value, is_called FROM {seq}")).one()
                if top >= (last + 1 if called else last):
                    db.session.execute(sql_text("SELECT setval(:seq, :top)"), {"seq": seq, "top": top})
                db.session.commit()
        for table in added:
            ddl(f"ALTER TABLE {table} ALTER COLUMN org_id SET NOT NULL")
        for uc in inspect(db.engine).get_unique_constraints("users"):
            if uc["column_names"] == ["username"]:
                ddl(f'ALTER TABLE users DROP CONSTRAINT "{uc["name"]}"')
        for ix in inspect(db.engine).get_indexes("users"):
            if ix.get("unique") and ix["column_names"] == ["username"]:
                ddl(f'DROP INDEX IF EXISTS "{ix["name"]}"')
    ddl("CREATE UNIQUE INDEX IF NOT EXISTS ix_users_org_username ON users (org_id, lower(username))")
    if "brand_settings" in added:
        ddl("CREATE UNIQUE INDEX IF NOT EXISTS brand_settings_org_id_key ON brand_settings (org_id)")
    for table in added:
        if table != "brand_settings":
            ddl(f"CREATE INDEX IF NOT EXISTS ix_{table}_org_id ON {table} (org_id)")
    wanted = {(entry[0], entry[1]) for entry in cfg["DEFAULT_RULES"]}
    for row in DefaultRule.query.all():
        if (row.kind, row.text) not in wanted:
            db.session.delete(row)
    for entry in cfg["DEFAULT_RULES"]:
        kind, text = entry[0], entry[1]
        repl = entry[2] if len(entry) > 2 else None
        row = DefaultRule.query.filter_by(kind=kind, text=text).first()
        if row is None:
            db.session.add(DefaultRule(kind=kind, text=text, replacement=repl))
        else:
            row.replacement = repl
    marker = f"sample_rules_seeded:{demo_org}"
    legacy_marker = db.session.get(Setting, "sample_rules_seeded")
    if legacy_marker is not None:
        if db.session.get(Setting, marker) is None:
            db.session.add(Setting(key=marker, value=legacy_marker.value))
        db.session.delete(legacy_marker)
    demo = cfg["DEMO_MODE"]
    db.session.flush()
    brand = BrandSettings.query.filter_by(org_id=demo_org).first()
    if brand is None:
        brand = BrandSettings(org_id=demo_org, colors_json="[]", tolerance="Normal")
        db.session.add(brand)
    if demo and not brand.colors:
        brand.colors_json = json.dumps(sorted(cfg["SAMPLE_BRAND_COLORS"]))
        brand.tolerance = cfg["SAMPLE_BRAND_TOLERANCE"]
    ensure_demo_accounts(cfg)
    if demo and db.session.get(Setting, marker) is None:
        seed_sample_rules(cfg, demo_org)
        db.session.add(Setting(key=marker, value="1"))
    insights.merge_duplicates()
    db.session.commit()


def register(app):
    cfg = app.config

    def wants_json():
        return request.is_json or request.args.get("format") == "json" or request.accept_mimetypes.best == "application/json"

    def body():
        if request.is_json:
            data = request.get_json(silent=True)
            return data if isinstance(data, dict) else {}
        return request.form

    def field(name, default=""):
        value = body().get(name, default)
        return value if isinstance(value, str) else default

    def field_list(name):
        data = body()
        if hasattr(data, "getlist"):
            return data.getlist(name)
        value = data.get(name, [])
        return [v for v in value if isinstance(v, str)] if isinstance(value, list) else []

    def user_dict(u):
        if not u:
            return None
        return {"username": u.username, "role": u.role, "is_authorized": u.is_authorized, "is_admin": u.is_admin,
                "org_id": u.org_id, "org_name": u.org.name}

    def page(template, status=200, **ctx):
        ctx["user"] = user_dict(g.user)
        ctx["csrf_token"] = session.get("csrf")
        ctx["demo_mode"] = cfg["DEMO_MODE"]
        ctx["demo_org_id"] = cfg["DEMO_ORG_ID"]
        ctx["docs_url"] = cfg["DOCS_URL"]
        ctx["messages"] = [{"category": c, "text": t} for c, t in get_flashed_messages(with_categories=True)]
        if g.user:
            seen = g.user.alerts_seen_at
            rows = Alert.query.filter_by(user_id=g.user.id).order_by(Alert.id.desc()).limit(cfg["ALERTS_SHOWN"]).all()
            ctx["alerts"] = [{"message": a.message, "kind": a.kind, "created_at": iso(a.created_at), "unseen": seen is None or a.created_at > seen}
                             for a in rows]
            ctx["unseen_alerts"] = sum(1 for a in ctx["alerts"] if a["unseen"])
        if wants_json():
            return jsonify(ctx), status
        try:
            return render_template(template, **ctx), status
        except TemplateNotFound:
            ctx["_note"] = f"template {template} not found, showing data only"
            return jsonify(ctx), status

    def done(message, endpoint, **extra):
        if wants_json():
            return jsonify({"ok": True, "message": message, **extra})
        flash(message, "success")
        return redirect(url_for(endpoint))

    def fail(message, status, endpoint=None):
        if wants_json() or endpoint is None:
            return jsonify({"ok": False, "error": message}), status
        flash(message, "error")
        return redirect(url_for(endpoint))

    def login_required(fn):
        @wraps(fn)
        def wrapper(*a, **kw):
            if g.user is None:
                return fail("Please log in.", 401, "login")
            return fn(*a, **kw)
        return wrapper

    def authorized_required(fn):
        @wraps(fn)
        @login_required
        def wrapper(*a, **kw):
            if not g.user.is_authorized:
                return fail("Only Authorized users can do this.", 403)
            return fn(*a, **kw)
        return wrapper

    def admin_required(fn):
        @wraps(fn)
        @login_required
        def wrapper(*a, **kw):
            if not g.user.is_admin:
                return fail("Only the organization's Admin can do this.", 403, "dashboard")
            return fn(*a, **kw)
        return wrapper

    def guidelines_editor(fn):
        @wraps(fn)
        @login_required
        def wrapper(*a, **kw):
            if not g.user.is_authorized:
                return fail("Only Authorized users can edit guidelines.", 403, "guidelines")
            return fn(*a, **kw)
        return wrapper

    @app.before_request
    def load_user_and_csrf():
        g.user = db.session.get(User, session["user_id"]) if "user_id" in session else None
        if "user_id" in session and g.user is None:
            session.pop("user_id")
        if "csrf" not in session:
            session["csrf"] = secrets.token_hex(16)
        if cfg["CSRF_ENABLED"] and request.method in ("POST", "PUT", "PATCH", "DELETE") \
                and request.endpoint not in CSRF_EXEMPT:
            sent = request.headers.get("X-CSRF-Token") or field("csrf_token")
            if not sent or not hmac.compare_digest(sent, session["csrf"]):
                return fail("Your session expired or the form is invalid. Reload the page and try again.", 400)

    @app.errorhandler(413)
    def too_large(_):
        return fail("The upload is too large.", 413)

    @app.errorhandler(404)
    def not_found(_):
        return fail("Not found.", 404)

    @app.errorhandler(500)
    def server_error(_):
        db.session.rollback()
        return fail("Something went wrong on our side. Please try again.", 500)

    @app.route("/")
    def index():
        if g.user:
            return redirect(url_for("dashboard"))
        if cfg["DEMO_MODE"]:
            return page("demo.html", demo_accounts=demo_account_specs(cfg))
        return page("login.html", demo_available=False)

    @app.route("/demo")
    def demo_page():
        if g.user:
            return redirect(url_for("dashboard"))
        if not cfg["DEMO_MODE"]:
            return redirect(url_for("login"))
        return page("demo.html", demo_accounts=demo_account_specs(cfg))

    failed_logins = {}

    def login_lock_seconds(key):
        org_id, name = key
        if cfg["DEMO_MODE"] and org_id == cfg["DEMO_ORG_ID"] and name in {s["username"].lower() for s in demo_account_specs(cfg)}:
            return 0
        now = time.time()
        recent = [t for t in failed_logins.get(key, []) if now - t < cfg["LOGIN_LOCK_SECONDS"]]
        if recent:
            failed_logins[key] = recent
        else:
            failed_logins.pop(key, None)
        if len(recent) >= cfg["LOGIN_MAX_FAILURES"]:
            return max(1, math.ceil(cfg["LOGIN_LOCK_SECONDS"] - (now - recent[0])))
        return 0

    def start_session(user, message=None, **extra):
        session.clear()
        session["user_id"] = user.id
        session["csrf"] = secrets.token_hex(16)
        if protected_account(user):
            session["tour"] = True
        if message:
            flash(message, "success")
        if wants_json():
            return jsonify({"ok": True, "redirect": url_for("dashboard"), **({"message": message} if message else {}), **extra})
        return redirect(url_for("dashboard"))

    @app.route("/login", methods=["GET", "POST"])
    def login():
        if request.method == "GET":
            if g.user:
                return redirect(url_for("dashboard"))
            return page("login.html", demo_available=cfg["DEMO_MODE"])
        raw_org, name, password = field("org_id").strip(), field("username").strip(), field("password")
        org_id = int(raw_org) if raw_org.isdigit() and len(raw_org) <= 9 else None
        key = (org_id, name.lower())
        wait = login_lock_seconds(key) if name and org_id else 0
        if wait:
            minutes = math.ceil(wait / 60)
            return fail(f"Too many wrong passwords for this username. Please wait {minutes} minute(s) and try again.", 429, "login")
        user = None
        if name and org_id:
            user = User.query.filter(User.org_id == org_id, func.lower(User.username) == name.lower()).first()
        if not user or not check_password_hash(user.password_hash, password):
            if name and org_id:
                if len(failed_logins) > 1000:
                    failed_logins.clear()
                failed_logins.setdefault(key, []).append(time.time())
            return fail("Incorrect organization ID, username or password. Please try again.", 401, "login")
        failed_logins.pop(key, None)
        return start_session(user)

    @app.route("/demo-login/<key>", methods=["POST"])
    def demo_login(key):
        spec = next((s for s in demo_account_specs(cfg) if s["key"] == key), None) if cfg["DEMO_MODE"] else None
        user = None
        if spec:
            user = User.query.filter(User.org_id == cfg["DEMO_ORG_ID"], func.lower(User.username) == spec["username"].lower()).first()
        if user is None:
            return fail("Demo mode is not available.", 404, "login")
        return start_session(user)

    @app.route("/organizations/new", methods=["GET", "POST"])
    def org_new():
        if g.user:
            return redirect(url_for("dashboard"))
        if request.method == "GET":
            return page("org_new.html")
        name = " ".join(field("org_name").split())
        username, password, confirm = field("username").strip(), field("password"), field("confirm_password")
        if not cfg["MIN_ORG_NAME_CHARS"] <= len(name) <= cfg["MAX_ORG_NAME_CHARS"]:
            return fail(f"The organization name must be {cfg['MIN_ORG_NAME_CHARS']} to {cfg['MAX_ORG_NAME_CHARS']} characters.", 400, "org_new")
        if not USERNAME_RE.match(username):
            return fail("Username must be 3 to 30 characters: letters, numbers, dot, dash or underscore.", 400, "org_new")
        if len(password) < cfg["MIN_PASSWORD_LENGTH"]:
            return fail(f"Password must be at least {cfg['MIN_PASSWORD_LENGTH']} characters.", 400, "org_new")
        if password != confirm:
            return fail("The two passwords do not match.", 400, "org_new")
        org = Organization(name=name, created_by=username)
        db.session.add(org)
        db.session.flush()
        user = User(org_id=org.id, username=username, role="Admin", password_hash=generate_password_hash(password))
        db.session.add(user)
        db.session.add(BrandSettings(org_id=org.id, colors_json="[]", tolerance="Normal"))
        db.session.flush()
        notify(user, "welcome", "Welcome to ThirdEye! We hope you and your organization enjoy your experience with us. "
                                "To utilize ThirdEye to its fullest, click here to view our documentation:")
        seed_sample_rules(cfg, org.id)
        db.session.commit()
        return start_session(
            user, f"Organization created. Your organization ID is {org.id}. You need it, with your username, to log in.",
            organization_id=org.id)

    def notify(user, kind, message):
        db.session.add(Alert(org_id=user.org_id, user_id=user.id, kind=kind, message=message[:400]))
        db.session.flush()
        for stale in Alert.query.filter_by(user_id=user.id).order_by(Alert.id.desc()).offset(cfg["ALERTS_KEPT"]).all():
            db.session.delete(stale)

    @app.route("/alerts/seen", methods=["POST"])
    @login_required
    def alerts_seen():
        g.user.alerts_seen_at = utcnow()
        db.session.commit()
        return jsonify({"ok": True})

    def protected_account(u):
        return (cfg["DEMO_MODE"] and u.org_id == cfg["DEMO_ORG_ID"]
                and u.username.lower() in {s["username"].lower() for s in demo_account_specs(cfg)})

    def managed_member(user_id):
        target = User.query.filter_by(id=user_id, org_id=g.user.org_id).first()
        if target is None:
            return None, fail("Member not found.", 404, "members_page")
        if target.role == "Admin" or target.id == g.user.id:
            return None, fail("The Admin account cannot be changed or removed.", 400, "members_page")
        if protected_account(target):
            return None, fail("This is a built-in demo account and cannot be changed or removed.", 400, "members_page")
        return target, None

    @app.route("/members")
    @admin_required
    def members_page():
        users = User.query.filter_by(org_id=g.user.org_id).all()
        order = {"Admin": 0, "Authorized": 1, "Member": 2}
        users.sort(key=lambda u: (order.get(u.role, 3), u.username.lower()))
        return page(
            "members.html", org={"id": g.user.org_id, "name": g.user.org.name}, max_message_chars=cfg["MAX_MESSAGE_CHARS"],
            members=[{"id": u.id, "username": u.username, "role": u.role, "created_at": iso(u.created_at),
                      "is_self": u.id == g.user.id, "protected": protected_account(u),
                      "can_manage": u.role != "Admin" and u.id != g.user.id and not protected_account(u)} for u in users])

    @app.route("/members/add", methods=["POST"])
    @admin_required
    def member_add():
        username, password = field("username").strip(), field("password")
        if not USERNAME_RE.match(username):
            return fail("Username must be 3 to 30 characters: letters, numbers, dot, dash or underscore.", 400, "members_page")
        if len(password) < cfg["MIN_PASSWORD_LENGTH"]:
            return fail(f"Password must be at least {cfg['MIN_PASSWORD_LENGTH']} characters.", 400, "members_page")
        if User.query.filter(User.org_id == g.user.org_id, func.lower(User.username) == username.lower()).first():
            return fail("That username is already taken in this organization.", 409, "members_page")
        db.session.add(User(org_id=g.user.org_id, username=username, role="Member", password_hash=generate_password_hash(password)))
        db.session.commit()
        return done(f"Member added. They log in with organization ID {g.user.org_id}, the username and the password you set.", "members_page")

    @app.route("/members/<int:user_id>/role", methods=["POST"])
    @admin_required
    def member_role(user_id):
        target, err = managed_member(user_id)
        if err:
            return err
        role = field("role")
        if role not in ("Authorized", "Member"):
            return fail("Choose Authorized or Member.", 400, "members_page")
        if target.role == role:
            return done(f"{target.username} is already {role}.", "members_page")
        target.role = role
        notify(target, "role", f"Your role was changed to {role} by {g.user.username}.")
        db.session.commit()
        return done(f"{target.username} is now {role}.", "members_page")

    @app.route("/members/<int:user_id>/remove", methods=["POST"])
    @admin_required
    def member_remove(user_id):
        target, err = managed_member(user_id)
        if err:
            return err
        name = target.username
        Alert.query.filter_by(user_id=target.id).delete()
        stats.retire_user_submissions(target.id, cfg["DRAFT_TTL_MINUTES"])
        Submission.query.filter_by(user_id=target.id).delete()
        db.session.delete(target)
        db.session.commit()
        return done(f"{name} was removed. Their requests were removed with the account.", "members_page")

    @app.route("/members/message", methods=["POST"])
    @admin_required
    def member_message():
        text = " ".join(field("message").split())
        if not text:
            return fail("Write a message first.", 400, "members_page")
        if len(text) > cfg["MAX_MESSAGE_CHARS"]:
            return fail(f"Messages are limited to {cfg['MAX_MESSAGE_CHARS']} characters.", 400, "members_page")
        recipients = User.query.filter(User.org_id == g.user.org_id, User.id != g.user.id).all()
        if not recipients:
            return fail("There is nobody else in this organization yet.", 400, "members_page")
        for u in recipients:
            notify(u, "message", f"Message from {g.user.username}: {text}")
        db.session.commit()
        return done(f"Message sent to {len(recipients)} member(s).", "members_page")

    @app.route("/logout", methods=["GET", "POST"])
    def logout():
        session.clear()
        return redirect(url_for("login")) if not wants_json() else jsonify({"ok": True, "redirect": url_for("login")})

    @app.route("/dashboard")
    @login_required
    def dashboard():
        flagged = bool(session.pop("tour", False))
        auto_tour = flagged or request.args.get("tour") == "1" or (not g.user.tour_seen and not protected_account(g.user))
        return page("dashboard.html", auto_tour=auto_tour, tour_seen_url=url_for("tour_seen"),
                    insights=insights.get_insights(g.user.org_id, cfg["INSIGHT_LIMIT"], cfg["INSIGHT_THRESHOLD"]))

    @app.route("/tour/seen", methods=["POST"])
    @login_required
    def tour_seen():
        if not g.user.tour_seen:
            g.user.tour_seen = True
            db.session.commit()
        return jsonify({"ok": True})

    @app.route("/demo/reset", methods=["POST"])
    @authorized_required
    def demo_reset():
        org_id = cfg["DEMO_ORG_ID"]
        if not cfg["DEMO_MODE"] or g.user.org_id != org_id:
            return fail("Demo mode is not on.", 404, "dashboard")
        for model in (Alert, Submission, ReportEvent, Guideline, IssueCounter, Insight):
            model.query.filter_by(org_id=org_id).delete()
        keep = {s["username"].lower() for s in demo_account_specs(cfg)} | {g.user.username.lower()}
        for u in User.query.filter_by(org_id=org_id).all():
            if u.username.lower() not in keep:
                db.session.delete(u)
        db.session.flush()
        ensure_demo_accounts(cfg)
        seed_sample_rules(cfg, org_id)
        brand = brand_for(org_id)
        brand.colors_json = json.dumps(sorted(cfg["SAMPLE_BRAND_COLORS"]))
        brand.tolerance = cfg["SAMPLE_BRAND_TOLERANCE"]
        brand.logo_blob, brand.logo_name = None, None
        db.session.commit()
        return done("Demo data reset. The sample rules, colors and demo accounts are back.", "dashboard")

    def rule_dict(r, editable):
        effective = (r.replacement or cfg["DEFAULT_REPLACEMENT"]) if r.kind == "must_not_use" else None
        return {"id": r.id, "kind": r.kind, "kind_label": cfg["RULE_KINDS"][r.kind], "text": r.text,
                "replacement": r.replacement, "effective_replacement": effective, "editable": editable}

    @app.route("/guidelines")
    @login_required
    def guidelines():
        brand = brand_for(g.user.org_id)
        return page(
            "guidelines.html", can_edit=g.user.is_authorized,
            rule_types=[{"value": k, "label": v} for k, v in cfg["RULE_KINDS"].items()],
            rules=[rule_dict(r, True) for r in Guideline.query.filter_by(org_id=g.user.org_id).order_by(Guideline.id)],
            default_rules=[rule_dict(r, False) for r in DefaultRule.query.order_by(DefaultRule.id)],
            colors=brand.colors, tolerance=brand.tolerance, tolerance_options=list(cfg["COLOR_TOLERANCES"]),
            default_replacement=cfg["DEFAULT_REPLACEMENT"], max_colors=cfg["MAX_COLORS"], has_logo=bool(brand.logo_blob), logo_name=brand.logo_name,
            logo_url=url_for("logo_image") if brand.logo_blob else None)

    @app.route("/guidelines/rules", methods=["POST"])
    @guidelines_editor
    def add_rule():
        kind, text = field("kind"), " ".join(field("text").split())
        replacement = " ".join(field("replacement").split()) if kind == "must_not_use" else ""
        if kind not in cfg["RULE_KINDS"]:
            return fail("Choose a rule type.", 400, "guidelines")
        if not text:
            return fail("Rule text cannot be empty.", 400, "guidelines")
        if len(text) > cfg["MAX_RULE_CHARS"]:
            return fail(f"Rule text is limited to {cfg['MAX_RULE_CHARS']} characters.", 400, "guidelines")
        if len(replacement) > cfg["MAX_RULE_CHARS"]:
            return fail(f"The replacement is limited to {cfg['MAX_RULE_CHARS']} characters.", 400, "guidelines")
        if replacement and checks.phrase_pattern(text).search(replacement):
            return fail("The replacement cannot contain the banned word itself.", 400, "guidelines")
        if DefaultRule.query.filter(DefaultRule.kind == kind, func.lower(DefaultRule.text) == text.lower()).first():
            return fail("That rule is already a built-in default rule.", 409, "guidelines")
        if Guideline.query.filter(Guideline.org_id == g.user.org_id, Guideline.kind == kind,
                                  func.lower(Guideline.text) == text.lower()).first():
            return fail("That rule already exists.", 409, "guidelines")
        conflict = checks.rule_conflict(kind, text, replacement, active_rules(g.user.org_id))
        if conflict:
            return fail(conflict + " Change one of the rules first.", 409, "guidelines")
        db.session.add(Guideline(org_id=g.user.org_id, kind=kind, text=text, replacement=replacement or None, created_by=g.user.username))
        db.session.commit()
        return done("Rule added.", "guidelines")

    @app.route("/guidelines/rules/<int:rule_id>/delete", methods=["POST"])
    @guidelines_editor
    def delete_rule(rule_id):
        rule = Guideline.query.filter_by(id=rule_id, org_id=g.user.org_id).first()
        if rule is None:
            return fail("Rule not found.", 404, "guidelines")
        db.session.delete(rule)
        db.session.commit()
        return done("Rule deleted.", "guidelines")

    @app.route("/guidelines/brand", methods=["POST"])
    @guidelines_editor
    def save_brand():
        brand = brand_for(g.user.org_id)
        colors = [c.strip() for c in field_list("colors") if c.strip()]
        if not 1 <= len(colors) <= cfg["MAX_COLORS"]:
            return fail(f"Enter 1 to {cfg['MAX_COLORS']} brand colors.", 400, "guidelines")
        if any(not HEX_RE.match(c) for c in colors):
            return fail("Colors must be hex codes like #0033A0.", 400, "guidelines")
        tolerance = field("tolerance", "Normal") or "Normal"
        if tolerance not in cfg["COLOR_TOLERANCES"]:
            return fail("Choose Strict, Normal or Loose.", 400, "guidelines")
        logo = request.files.get("logo")
        logo_bytes = None
        if logo and logo.filename:
            logo_bytes = logo.read(cfg["MAX_LOGO_BYTES"] + 1)
            if len(logo_bytes) > cfg["MAX_LOGO_BYTES"]:
                return fail("The logo file is too large.", 400, "guidelines")
            if not logo_bytes.startswith(PNG_SIGNATURE) or not checks._logo_variants(logo_bytes):
                return fail("The logo must be a valid PNG file.", 400, "guidelines")
        brand.colors_json = json.dumps(sorted({"#" + c.lstrip("#").upper() for c in colors}))
        brand.tolerance = tolerance
        if logo_bytes:
            brand.logo_blob, brand.logo_name = logo_bytes, logo.filename[:255]
        db.session.commit()
        return done("Guidelines saved.", "guidelines")

    @app.route("/guidelines/logo")
    @login_required
    def logo_image():
        brand = brand_for(g.user.org_id)
        if not brand.logo_blob:
            abort(404)
        return send_file(io.BytesIO(brand.logo_blob), mimetype="image/png")

    def active_rules(org_id):
        seen, out = set(), []
        for model, scope in ((DefaultRule, None), (Guideline, org_id)):
            query = model.query if scope is None else model.query.filter_by(org_id=scope)
            for r in query.order_by(model.id):
                k = (r.kind, r.text.lower())
                if k not in seen:
                    seen.add(k)
                    out.append({"kind": r.kind, "text": r.text, "replacement": r.replacement})
        return out

    def default_judge(units, tone_rules, phrases):
        return llm.analyze(units, tone_rules, phrases, api_key=cfg["GEMINI_API_KEY"], model=cfg["GEMINI_MODEL"],
                           max_tokens=cfg["LLM_MAX_OUTPUT_TOKENS"], thinking_budget=cfg["GEMINI_THINKING_BUDGET"],
                           reason_words=cfg["LLM_REASON_WORDS"], cache_size=cfg["LLM_CACHE_SIZE"])

    def check_ctx(**extra):
        return dict(max_text_chars=cfg["MAX_TEXT_CHARS"], max_pdf_mb=cfg["MAX_PDF_BYTES"] // (1024 * 1024),
                    max_image_mb=cfg["MAX_IMAGE_BYTES"] // (1024 * 1024), **extra)

    @app.route("/check", methods=["GET", "POST"])
    @login_required
    def check():
        if request.method == "GET":
            return page("check.html", **check_ctx())
        text = field("text").replace("\r\n", "\n").replace("\r", "\n").replace("\x00", "")
        pdf_upload, image_upload = request.files.get("pdf"), request.files.get("image")
        has_pdf = bool(pdf_upload and pdf_upload.filename)
        has_image = bool(image_upload and image_upload.filename)
        input_type = field("input_type") or ("pdf" if has_pdf else "image" if has_image else "text")
        if input_type not in ("text", "pdf", "image"):
            return page("check.html", 400, error="Unknown input type.", **check_ctx())
        if not field("input_type") and (has_pdf + has_image + bool(text.strip())) > 1:
            return page("check.html", 400, error="Provide only one of: text, a PDF, or an image.", text=text, **check_ctx())

        def reject(msg):
            return page("check.html", 400, error=msg, text=text if input_type == "text" else "", **check_ctx())

        pdf_bytes = image_bytes = None
        if input_type == "text":
            if not text.strip():
                return reject("Please enter some text to check.")
            if len(text) > cfg["MAX_TEXT_CHARS"]:
                return reject(f"Text is limited to {cfg['MAX_TEXT_CHARS']} characters.")
        elif input_type == "pdf":
            if not has_pdf:
                return reject("Please choose a PDF file.")
            if not pdf_upload.filename.lower().endswith(".pdf"):
                return reject("Please upload a PDF file (.pdf).")
            pdf_bytes = pdf_upload.read(cfg["MAX_PDF_BYTES"] + 1)
            if len(pdf_bytes) > cfg["MAX_PDF_BYTES"]:
                return reject(f"The PDF is larger than {cfg['MAX_PDF_BYTES'] // (1024 * 1024)} MB.")
        else:
            if not has_image:
                return reject("Please choose an image file.")
            if not image_upload.filename.lower().endswith((".png", ".jpg", ".jpeg", ".webp")):
                return reject("Please upload a PNG, JPG or WebP image.")
            image_bytes = image_upload.read(cfg["MAX_IMAGE_BYTES"] + 1)
            if len(image_bytes) > cfg["MAX_IMAGE_BYTES"]:
                return reject(f"The image is larger than {cfg['MAX_IMAGE_BYTES'] // (1024 * 1024)} MB.")

        stats.expire_drafts(cfg["DRAFT_TTL_MINUTES"])
        brand = brand_for(g.user.org_id)
        try:
            result = checks.run_pipeline(
                input_type=input_type, text=text, pdf_bytes=pdf_bytes, image_bytes=image_bytes, rules=active_rules(g.user.org_id),
                brand={"colors": brand.colors, "tolerance": brand.tolerance, "logo": brand.logo_blob},
                judge=cfg.get("LLM_JUDGE") or default_judge, cfg=cfg)
        except checks.ContentError as exc:
            return reject(str(exc))

        issues = result["issues"]
        out = {"status": "clean" if not issues else "issues", "input_type": input_type, "notes": result["notes"],
               "needs_review": result["needs_review"], "manual_edit": result["manual_edit"],
               "issues": [checks.public_issue(i) for i in issues],
               "can_apply_immediately": g.user.is_authorized, "submission_id": None}
        if issues:
            sub = Submission(org_id=g.user.org_id, user_id=g.user.id, username=g.user.username, input_type=input_type, status="Draft",
                             issues_json=json.dumps(issues), corrected_text=result["corrected_text"],
                             output_blob=result["output"], output_name=result["output_name"],
                             output_mimetype=result["mimetype"])
            db.session.add(sub)
            db.session.flush()
            stats.record_check(g.user, input_type, issues, sub)
            db.session.commit()
            out["submission_id"] = sub.id
        else:
            stats.record_check(g.user, input_type, issues)
            db.session.commit()
        return page("check.html", result=out, **check_ctx())

    def own_draft(sub_id):
        sub = db.session.get(Submission, sub_id)
        if sub is None or sub.user_id != g.user.id or sub.status != "Draft":
            return None, fail("This result is no longer available. Please run the check again.", 404)
        if sub.created_at < utcnow() - timedelta(minutes=cfg["DRAFT_TTL_MINUTES"]):
            stats.mark_expired(sub, cfg["DRAFT_TTL_MINUTES"])
            db.session.delete(sub)
            db.session.commit()
            return None, fail("This result expired. Please run the check again.", 410)
        return sub, None

    def resolve(sub, status, remark=None):
        sub.status, sub.resolved_at, sub.resolved_by = status, utcnow(), g.user.username
        stats.record_decision(sub, status, g.user.username, remark)
        if status == "Approved":
            insights.record_approved(sub.org_id, sub.issues, cfg["INSIGHT_THRESHOLD"])
        db.session.flush()
        old = Submission.query.filter(Submission.org_id == sub.org_id, Submission.status.in_(("Approved", "Rejected"))) \
            .order_by(Submission.resolved_at.desc(), Submission.id.desc()).offset(cfg["HISTORY_LIMIT"]).all()
        for o in old:
            db.session.delete(o)
        db.session.commit()

    @app.route("/check/<int:sub_id>/approve", methods=["POST"])
    @login_required
    def approve_check(sub_id):
        sub, err = own_draft(sub_id)
        if err:
            return err
        if g.user.is_authorized:
            resolve(sub, "Approved")
            return page("check.html", **check_ctx(), approved={
                "message": "Corrections applied.", "input_type": sub.input_type, "corrected_text": sub.corrected_text,
                "manual_edit": any(i.get("manual") for i in sub.issues),
                "download_url": url_for("download", sub_id=sub.id)})
        sub.status = "Pending"
        db.session.commit()
        return page("check.html", **check_ctx(), forwarded={"message": "Request sent for approval."})

    @app.route("/check/<int:sub_id>/reject", methods=["POST"])
    @login_required
    def reject_check(sub_id):
        sub, err = own_draft(sub_id)
        if err:
            return err
        sub.output_blob, sub.corrected_text = None, None
        resolve(sub, "Rejected")
        return page("check.html", **check_ctx(), rejected={"message": "No changes were made. Saved to history as Rejected."})

    def sub_dict(s):
        can_dl = s.status == "Approved" and (g.user.is_authorized or s.user_id == g.user.id)
        return {"id": s.id, "username": s.username, "input_type": s.input_type,
                "content_type": {"pdf": "PDF", "image": "Image"}.get(s.input_type, "Text"), "status": s.status,
                "created_at": iso(s.created_at), "resolved_at": iso(s.resolved_at), "resolved_by": s.resolved_by,
                "issue_count": len(s.issues), "remark": s.remark, "issues": [checks.public_issue(i) for i in s.issues],
                "manual_edit": any(i.get("manual") for i in s.issues),
                "can_decide": g.user.is_authorized and s.status == "Pending",
                "download_url": url_for("download", sub_id=s.id) if can_dl else None}

    @app.route("/requests")
    @login_required
    def requests_page():
        pending_q = Submission.query.filter_by(status="Pending", org_id=g.user.org_id)
        history_q = Submission.query.filter(Submission.org_id == g.user.org_id, Submission.status.in_(("Approved", "Rejected")))
        if not g.user.is_authorized:
            pending_q = pending_q.filter_by(user_id=g.user.id)
            history_q = history_q.filter_by(user_id=g.user.id)
        pending = pending_q.order_by(Submission.created_at.desc()).all()
        history = history_q.order_by(Submission.resolved_at.desc(), Submission.id.desc()).limit(cfg["HISTORY_LIMIT"]).all()
        return page("requests.html", view="authorized" if g.user.is_authorized else "member",
                    pending=[sub_dict(s) for s in pending], history=[sub_dict(s) for s in history])

    def decide(sub_id, status):
        sub = Submission.query.filter_by(id=sub_id, org_id=g.user.org_id).first()
        if sub is None or sub.status != "Pending":
            return fail("This request is no longer pending.", 404, "requests_page")
        remark = " ".join(field("remark").split())
        if status == "Rejected" and not remark:
            return fail("Write a remark explaining the rejection.", 400, "requests_page")
        if len(remark) > cfg["MAX_REMARK_CHARS"]:
            return fail(f"Remarks are limited to {cfg['MAX_REMARK_CHARS']} characters.", 400, "requests_page")
        uploader = db.session.get(User, sub.user_id)
        label = {"pdf": "PDF", "image": "Image"}.get(sub.input_type, "Text")
        resolve(sub, status, remark)
        if uploader is not None and uploader.id != g.user.id:
            notify(uploader, "request", f"Your {label} request was {status.lower()} by {g.user.username}."
                   + (f" Remark: {remark}" if remark else ""))
            db.session.commit()
        return done(f"Request {status.lower()}.", "requests_page", status=status)

    @app.route("/requests/<int:sub_id>/approve", methods=["POST"])
    @authorized_required
    def approve_request(sub_id):
        return decide(sub_id, "Approved")

    @app.route("/requests/<int:sub_id>/reject", methods=["POST"])
    @authorized_required
    def reject_request(sub_id):
        return decide(sub_id, "Rejected")

    @app.route("/reports")
    @login_required
    def reports_page():
        stats.expire_drafts(cfg["DRAFT_TTL_MINUTES"], g.user.org_id)
        summary = stats.org_summary(g.user.org_id, cfg["REPORT_DAYS"])
        return page("reports.html", org={"id": g.user.org_id, "name": g.user.org.name}, summary=summary,
                    metrics=[{"label": label, "value": value} for label, value in reports.org_metrics(summary)],
                    charts=reports.org_charts(summary, 720, 350), download_url=url_for("report_download"))

    def pdf_response(data, name):
        return send_file(io.BytesIO(data), mimetype="application/pdf", as_attachment=True, download_name=name)

    @app.route("/reports/download")
    @login_required
    def report_download():
        stats.expire_drafts(cfg["DRAFT_TTL_MINUTES"], g.user.org_id)
        summary = stats.org_summary(g.user.org_id, cfg["REPORT_DAYS"])
        data = reports.org_report(g.user.org.name, g.user.org_id, summary, utcnow(), cfg["REPORT_DAYS"])
        return pdf_response(data, "thirdeye_organization_report.pdf")

    @app.route("/history/download")
    @login_required
    def history_download():
        stats.expire_drafts(cfg["DRAFT_TTL_MINUTES"], g.user.org_id)
        rows, total = stats.history_rows(g.user.org_id, None if g.user.is_authorized else g.user.id, cfg["HISTORY_PDF_MAX_ROWS"])
        data = reports.history_report(g.user.org.name, g.user.org_id, g.user.username, g.user.role, rows, g.user.is_authorized, utcnow(), total)
        return pdf_response(data, "thirdeye_full_history.pdf")

    @app.route("/profile")
    @login_required
    def profile():
        stats.expire_drafts(cfg["DRAFT_TTL_MINUTES"], g.user.org_id)
        return page("profile.html", me={"username": g.user.username, "role": g.user.role, "org_id": g.user.org_id,
                                        "org_name": g.user.org.name},
                    counts=stats.user_counts(g.user), can_change_password=not protected_account(g.user),
                    min_password=cfg["MIN_PASSWORD_LENGTH"])

    @app.route("/profile/password", methods=["POST"])
    @login_required
    def change_password():
        if protected_account(g.user):
            return fail("This is a shared demo account, so its password cannot be changed.", 400, "profile")
        key = (g.user.org_id, g.user.username.lower())
        wait = login_lock_seconds(key)
        if wait:
            return fail(f"Too many wrong passwords. Please wait {math.ceil(wait / 60)} minute(s) and try again.", 429, "profile")
        current, new, confirm = field("current_password"), field("new_password"), field("confirm_password")
        if not check_password_hash(g.user.password_hash, current):
            if len(failed_logins) > 1000:
                failed_logins.clear()
            failed_logins.setdefault(key, []).append(time.time())
            return fail("The current password is incorrect.", 401, "profile")
        if len(new) < cfg["MIN_PASSWORD_LENGTH"]:
            return fail(f"The new password must be at least {cfg['MIN_PASSWORD_LENGTH']} characters.", 400, "profile")
        if new != confirm:
            return fail("The two new passwords do not match.", 400, "profile")
        if new == current:
            return fail("The new password must be different from the current one.", 400, "profile")
        failed_logins.pop(key, None)
        g.user.password_hash = generate_password_hash(new)
        db.session.commit()
        return done("Password changed.", "profile")

    @app.route("/download/<int:sub_id>")
    @login_required
    def download(sub_id):
        sub = Submission.query.filter_by(id=sub_id, org_id=g.user.org_id).first()
        if sub is None or sub.status != "Approved" or not sub.output_blob:
            return fail("Nothing to download.", 404)
        if not g.user.is_authorized and sub.user_id != g.user.id:
            return fail("Not allowed.", 403)
        return send_file(io.BytesIO(sub.output_blob), mimetype=sub.output_mimetype,
                         as_attachment=True, download_name=sub.output_name)


app = create_app()

if __name__ == "__main__":
    app.run(debug=True)
