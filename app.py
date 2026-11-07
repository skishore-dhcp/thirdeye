import hmac
import io
import re
import secrets
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
from config import Config
from models import (BrandSettings, DefaultRule, Guideline, Submission, User, db, iso, utcnow)

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
    return app


def init_db(app):
    db.create_all()
    cols = inspect(db.engine)       
    for table in ("guidelines", "default_rules"):
        if "replacement" not in {c["name"] for c in cols.get_columns(table)}:
            db.session.execute(sql_text(f"ALTER TABLE {table} ADD COLUMN replacement VARCHAR(200)"))
    db.session.commit()
    wanted = {(entry[0], entry[1]) for entry in app.config["DEFAULT_RULES"]}
    for row in DefaultRule.query.all():          
        if (row.kind, row.text) not in wanted:
            db.session.delete(row)
    for entry in app.config["DEFAULT_RULES"]:
        kind, text = entry[0], entry[1]
        repl = entry[2] if len(entry) > 2 else None
        row = DefaultRule.query.filter_by(kind=kind, text=text).first()
        if row is None:
            db.session.add(DefaultRule(kind=kind, text=text, replacement=repl))
        else:
            row.replacement = repl
    if not db.session.get(BrandSettings, 1):
        db.session.add(BrandSettings(id=1, colors_json="[]", tolerance="Normal"))
    demo = app.config["DEMO_USERNAME"]
    if not User.query.filter(func.lower(User.username) == demo.lower()).first():
        db.session.add(User(username=demo, role="Authorized",
                            password_hash=generate_password_hash(app.config["DEMO_PASSWORD"])))
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
        return {"username": u.username, "role": u.role, "is_authorized": u.is_authorized} if u else None

    def page(template, status=200, **ctx):
        ctx["user"] = user_dict(g.user)
        ctx["csrf_token"] = session.get("csrf")
        seen = []
        for c, t in get_flashed_messages(with_categories=True):
            if {"category": c, "text": t} not in seen:
                seen.append({"category": c, "text": t})
        ctx["messages"] = seen[-3:]
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
        return redirect(url_for("dashboard" if g.user else "login"))

    @app.route("/login", methods=["GET", "POST"])
    def login():
        if request.method == "GET":
            return page("login.html")
        name, password = field("username").strip(), field("password")
        user = User.query.filter(func.lower(User.username) == name.lower()).first() if name else None
        if not user or not check_password_hash(user.password_hash, password):
            return fail("Incorrect username or password. Please try again.", 401, "login")
        session.clear()
        session["user_id"] = user.id
        session["csrf"] = secrets.token_hex(16)
        return redirect(url_for("dashboard")) if not wants_json() else jsonify({"ok": True, "redirect": url_for("dashboard")})

    @app.route("/signup", methods=["GET", "POST"])
    def signup():
        if request.method == "GET":
            return page("signup.html")
        name, password = field("username").strip(), field("password")
        if not USERNAME_RE.match(name):
            return fail("Username must be 3 to 30 characters: letters, numbers, dot, dash or underscore.", 400, "signup")
        if len(password) < cfg["MIN_PASSWORD_LENGTH"]:
            return fail(f"Password must be at least {cfg['MIN_PASSWORD_LENGTH']} characters.", 400, "signup")
        if User.query.filter(func.lower(User.username) == name.lower()).first():
            return fail("That username is already taken.", 409, "signup")
        user = User(username=name, role="Member", password_hash=generate_password_hash(password))
        db.session.add(user)
        db.session.commit()
        session.clear()
        session["user_id"] = user.id
        session["csrf"] = secrets.token_hex(16)
        return redirect(url_for("dashboard")) if not wants_json() else jsonify({"ok": True, "redirect": url_for("dashboard")})

    @app.route("/logout", methods=["GET", "POST"])
    def logout():
        session.clear()
        return redirect(url_for("login")) if not wants_json() else jsonify({"ok": True, "redirect": url_for("login")})

    @app.route("/dashboard")
    @login_required
    def dashboard():
        return page("dashboard.html", insights=insights.get_insights(cfg["INSIGHT_LIMIT"], cfg["INSIGHT_THRESHOLD"]))

    def rule_dict(r, editable):
        effective = (r.replacement or cfg["DEFAULT_REPLACEMENT"]) if r.kind == "must_not_use" else None
        return {"id": r.id, "kind": r.kind, "kind_label": cfg["RULE_KINDS"][r.kind], "text": r.text,
                "replacement": r.replacement, "effective_replacement": effective, "editable": editable}

    @app.route("/guidelines")
    @login_required
    def guidelines():
        brand = db.session.get(BrandSettings, 1)
        return page(
            "guidelines.html",
            rule_types=[{"value": k, "label": v} for k, v in cfg["RULE_KINDS"].items()],
            rules=[rule_dict(r, True) for r in Guideline.query.order_by(Guideline.id)],
            default_rules=[rule_dict(r, False) for r in DefaultRule.query.order_by(DefaultRule.id)],
            colors=brand.colors, tolerance=brand.tolerance, tolerance_options=list(cfg["COLOR_TOLERANCES"]),
            default_replacement=cfg["DEFAULT_REPLACEMENT"], max_colors=cfg["MAX_COLORS"], has_logo=bool(brand.logo_blob), logo_name=brand.logo_name,
            logo_url=url_for("logo_image") if brand.logo_blob else None)

    @app.route("/guidelines/rules", methods=["POST"])
    @login_required
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
        same = lambda model: model.query.filter(model.kind == kind, func.lower(model.text) == text.lower()).first()
        if same(DefaultRule):
            return fail("That rule is already a built-in default rule.", 409, "guidelines")
        if same(Guideline):
            return fail("That rule already exists.", 409, "guidelines")
        conflict = checks.rule_conflict(kind, text, replacement, active_rules())
        if conflict:
            return fail(conflict + " Change one of the rules first.", 409, "guidelines")
        db.session.add(Guideline(kind=kind, text=text, replacement=replacement or None, created_by=g.user.username))
        db.session.commit()
        return done("Rule added.", "guidelines")

    @app.route("/guidelines/rules/<int:rule_id>/delete", methods=["POST"])
    @login_required
    def delete_rule(rule_id):
        rule = db.session.get(Guideline, rule_id)
        if rule is None:
            return fail("Rule not found.", 404, "guidelines")
        db.session.delete(rule)
        db.session.commit()
        return done("Rule deleted.", "guidelines")

    @app.route("/guidelines/brand", methods=["POST"])
    @login_required
    def save_brand():
        brand = db.session.get(BrandSettings, 1)
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
        import json
        brand.colors_json = json.dumps(sorted({"#" + c.lstrip("#").upper() for c in colors}))
        brand.tolerance = tolerance
        if logo_bytes:
            brand.logo_blob, brand.logo_name = logo_bytes, logo.filename[:255]
        db.session.commit()
        return done("Guidelines saved.", "guidelines")

    @app.route("/guidelines/logo")
    @login_required
    def logo_image():
        brand = db.session.get(BrandSettings, 1)
        if not brand.logo_blob:
            abort(404)
        return send_file(io.BytesIO(brand.logo_blob), mimetype="image/png")

    def active_rules():
        seen, out = set(), []
        for model in (DefaultRule, Guideline):
            for r in model.query.order_by(model.id):
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

        Submission.query.filter(Submission.status == "Draft",
                                Submission.created_at < utcnow() - timedelta(minutes=cfg["DRAFT_TTL_MINUTES"])).delete()
        brand = db.session.get(BrandSettings, 1)
        try:
            result = checks.run_pipeline(
                input_type=input_type, text=text, pdf_bytes=pdf_bytes, image_bytes=image_bytes, rules=active_rules(),
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
            import json
            sub = Submission(user_id=g.user.id, username=g.user.username, input_type=input_type, status="Draft",
                             issues_json=json.dumps(issues), corrected_text=result["corrected_text"],
                             output_blob=result["output"], output_name=result["output_name"],
                             output_mimetype=result["mimetype"])
            db.session.add(sub)
            db.session.commit()
            out["submission_id"] = sub.id
        else:
            db.session.commit()
        return page("check.html", result=out, **check_ctx())

    def own_draft(sub_id):
        sub = db.session.get(Submission, sub_id)
        if sub is None or sub.user_id != g.user.id or sub.status != "Draft":
            return None, fail("This result is no longer available. Please run the check again.", 404)
        if sub.created_at < utcnow() - timedelta(minutes=cfg["DRAFT_TTL_MINUTES"]):
            db.session.delete(sub)
            db.session.commit()
            return None, fail("This result expired. Please run the check again.", 410)
        return sub, None

    def resolve(sub, status):
        sub.status, sub.resolved_at, sub.resolved_by = status, utcnow(), g.user.username
        if status == "Approved":
            insights.record_approved(sub.issues, cfg["INSIGHT_THRESHOLD"])
        db.session.flush()
        old = Submission.query.filter(Submission.status.in_(("Approved", "Rejected"))) \
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
                "issue_count": len(s.issues), "issues": [checks.public_issue(i) for i in s.issues],
                "manual_edit": any(i.get("manual") for i in s.issues),
                "can_decide": g.user.is_authorized and s.status == "Pending",
                "download_url": url_for("download", sub_id=s.id) if can_dl else None}

    @app.route("/requests")
    @login_required
    def requests_page():
        pending_q = Submission.query.filter_by(status="Pending")
        history_q = Submission.query.filter(Submission.status.in_(("Approved", "Rejected")))
        if not g.user.is_authorized:
            pending_q = pending_q.filter_by(user_id=g.user.id)
            history_q = history_q.filter_by(user_id=g.user.id)
        pending = pending_q.order_by(Submission.created_at.desc()).all()
        history = history_q.order_by(Submission.resolved_at.desc(), Submission.id.desc()).limit(cfg["HISTORY_LIMIT"]).all()
        return page("requests.html", view="authorized" if g.user.is_authorized else "member",
                    pending=[sub_dict(s) for s in pending], history=[sub_dict(s) for s in history])

    def decide(sub_id, status):
        sub = db.session.get(Submission, sub_id)
        if sub is None or sub.status != "Pending":
            return fail("This request is no longer pending.", 404, "requests_page")
        resolve(sub, status)
        return done(f"Request {status.lower()}.", "requests_page", status=status)

    @app.route("/requests/<int:sub_id>/approve", methods=["POST"])
    @authorized_required
    def approve_request(sub_id):
        return decide(sub_id, "Approved")

    @app.route("/requests/<int:sub_id>/reject", methods=["POST"])
    @authorized_required
    def reject_request(sub_id):
        return decide(sub_id, "Rejected")

    @app.route("/download/<int:sub_id>")
    @login_required
    def download(sub_id):
        sub = db.session.get(Submission, sub_id)
        if sub is None or sub.status != "Approved" or not sub.output_blob:
            return fail("Nothing to download.", 404)
        if not g.user.is_authorized and sub.user_id != g.user.id:
            return fail("Not allowed.", 403)
        return send_file(io.BytesIO(sub.output_blob), mimetype=sub.output_mimetype,
                         as_attachment=True, download_name=sub.output_name)


app = create_app()

if __name__ == "__main__":
    app.run(debug=True)
