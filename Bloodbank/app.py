"""
LifeFlow Blood Bank Management System
Flask + SQLAlchemy backend
Preserves all existing routes, templates, and frontend behavior.
"""

import os
from flask import (Flask, render_template, request, redirect,
                   url_for, flash, session, jsonify)
from werkzeug.security import generate_password_hash, check_password_hash
from functools import wraps
from dotenv import load_dotenv

load_dotenv()   # reads .env if present

app = Flask(__name__)

# ─── Configuration ───
app.secret_key  = os.environ.get("SECRET_KEY", "dev-change-me-in-production")
DATABASE_URL    = os.environ.get("DATABASE_URL", "sqlite:///bloodbank.db")
app.config["SQLALCHEMY_DATABASE_URI"]        = DATABASE_URL
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
app.config["SQLALCHEMY_ENGINE_OPTIONS"]      = {
    "pool_recycle": 280,
    "connect_args": {"check_same_thread": False} if DATABASE_URL.startswith("sqlite") else {},
}

# ─── Models & Services ───
from models import db, User, Donor, BloodRequest, BloodStock, ActivityLog, BLOOD_GROUPS, COMPATIBILITY
from services import (DonorService, RequestService, StockService,
                      get_dashboard_stats, get_stock_dict)

db.init_app(app)


# ─── Startup: create tables + seed admin + migrate JSON ───
def _init_db():
    db.create_all()

    # Seed admin user (idempotent)
    if not User.query.filter_by(username="admin").first():
        admin_pw = os.environ.get("ADMIN_PASSWORD", "admin123")
        db.session.add(User(
            username      = "admin",
            password_hash = generate_password_hash(admin_pw),
            role          = "admin",
        ))
        db.session.commit()
        app.logger.info("Admin user created (username: admin).")

    # Seed blood stock rows (idempotent)
    for bg in BLOOD_GROUPS:
        if not BloodStock.query.filter_by(blood_group=bg).first():
            db.session.add(BloodStock(blood_group=bg, units=0))
    db.session.commit()

    # One-time JSON migration
    data_file = os.path.join(app.root_path, "data", "donors.json")
    if os.path.exists(data_file):
        from migrate import run_migration
        run_migration(app, db, Donor, BloodRequest, BloodStock, ActivityLog, BLOOD_GROUPS)


with app.app_context():
    _init_db()


# ─────────────────────────────────────────────
# Auth helpers
# ─────────────────────────────────────────────

def login_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if not session.get("logged_in"):
            flash("Please log in to access this page.", "warning")
            return redirect(url_for("login"))
        return f(*args, **kwargs)
    return decorated


def _current_user_id():
    return session.get("user_id")


# ─────────────────────────────────────────────
# Auth Routes
# ─────────────────────────────────────────────

@app.route("/login", methods=["GET", "POST"])
def login():
    if session.get("logged_in"):
        return redirect(url_for("dashboard"))
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "").strip()
        user = User.query.filter_by(username=username, is_active=True).first()
        if user and check_password_hash(user.password_hash, password):
            session["logged_in"]  = True
            session["username"]   = user.username
            session["user_id"]    = user.id
            session["user_role"]  = user.role
            flash(f"Welcome back, {user.username}!", "success")
            return redirect(url_for("dashboard"))
        flash("Invalid username or password.", "danger")
    return render_template("login.html")


@app.route("/logout")
def logout():
    session.clear()
    flash("You have been logged out.", "info")
    return redirect(url_for("login"))


# ─────────────────────────────────────────────
# Public Home
# ─────────────────────────────────────────────

@app.route("/")
def index():
    stats = {
        "total_donors":      Donor.query.filter_by(is_active=True).count(),
        "total_units":       db.session.query(db.func.sum(BloodStock.units)).scalar() or 0,
        "total_requests":    BloodRequest.query.count(),
        "emergency_requests": BloodRequest.query.filter_by(priority="emergency", status="pending").count(),
    }
    return render_template("index.html", stats=stats)


# ─────────────────────────────────────────────
# Dashboard
# ─────────────────────────────────────────────

@app.route("/dashboard")
@login_required
def dashboard():
    stats      = get_dashboard_stats()
    stock      = get_stock_dict()
    activities = ActivityLog.query.order_by(ActivityLog.timestamp.desc()).limit(10).all()
    return render_template(
        "dashboard.html",
        stats=stats, stock=stock, activities=activities,
        blood_groups=BLOOD_GROUPS
    )


# ─────────────────────────────────────────────
# Donor Routes
# ─────────────────────────────────────────────

@app.route("/donors")
@login_required
def donors():
    bg   = request.args.get("blood_group", "").strip()
    name = request.args.get("name", "").strip()
    donor_list = DonorService.list_donors(blood_group=bg, name=name)
    return render_template(
        "donors.html",
        donors=donor_list, blood_groups=BLOOD_GROUPS,
        search_bg=bg, search_name=name
    )


@app.route("/donors/add", methods=["GET", "POST"])
@login_required
def add_donor():
    if request.method == "POST":
        ok, msg = DonorService.add(request.form.to_dict(), user_id=_current_user_id())
        flash(msg, "success" if ok else "danger")
        if ok:
            return redirect(url_for("donors"))
    return render_template("add_donor.html", blood_groups=BLOOD_GROUPS)


@app.route("/donors/update/<int:donor_id>", methods=["GET", "POST"])
@login_required
def update_donor(donor_id):
    donor = DonorService.get(donor_id)
    if not donor:
        flash("Donor not found.", "danger")
        return redirect(url_for("donors"))
    if request.method == "POST":
        ok, msg = DonorService.update(donor_id, request.form.to_dict(), user_id=_current_user_id())
        flash(msg, "success" if ok else "danger")
        if ok:
            return redirect(url_for("donors"))
    return render_template("update_donor.html", donor=donor, blood_groups=BLOOD_GROUPS)


@app.route("/donors/delete/<int:donor_id>")
@login_required
def delete_donor(donor_id):
    ok, msg = DonorService.delete(donor_id, user_id=_current_user_id())
    flash(msg, "success" if ok else "danger")
    return redirect(url_for("donors"))


# ─────────────────────────────────────────────
# Request Routes
# ─────────────────────────────────────────────

@app.route("/requests")
@login_required
def requests_page():
    priority_filter = request.args.get("priority", "")
    status_filter   = request.args.get("status", "")
    req_list = RequestService.list_requests(priority=priority_filter, status=status_filter)
    return render_template(
        "requests.html",
        requests=req_list, blood_groups=BLOOD_GROUPS,
        priority_filter=priority_filter, status_filter=status_filter,
        compatibility=COMPATIBILITY
    )


@app.route("/requests/add", methods=["GET", "POST"])
@login_required
def add_request():
    if request.method == "POST":
        ok, msg = RequestService.add(request.form.to_dict(), user_id=_current_user_id())
        flash(msg, "success" if ok else "danger")
        if ok:
            return redirect(url_for("requests_page"))
    return render_template("add_request.html", blood_groups=BLOOD_GROUPS)


@app.route("/requests/process/<int:req_id>")
@login_required
def process_request(req_id):
    ok, msg = RequestService.process(req_id, user_id=_current_user_id())
    flash(msg, "success" if ok else "danger")
    return redirect(url_for("requests_page"))


@app.route("/requests/delete/<int:req_id>")
@login_required
def delete_request(req_id):
    ok, msg = RequestService.cancel(req_id, user_id=_current_user_id())
    flash(msg, "success" if ok else "danger")
    return redirect(url_for("requests_page"))


# ─────────────────────────────────────────────
# Stock Routes
# ─────────────────────────────────────────────

@app.route("/stock")
@login_required
def stock():
    stock_data = get_stock_dict()
    total = sum(stock_data.values())
    return render_template(
        "stock.html",
        stock=stock_data, total=total,
        blood_groups=BLOOD_GROUPS, compatibility=COMPATIBILITY
    )


@app.route("/stock/update", methods=["POST"])
@login_required
def update_stock():
    bg     = request.form.get("blood_group", "")
    action = request.form.get("action", "add")
    try:
        units = int(request.form.get("units", 0))
    except (ValueError, TypeError):
        flash("Units must be a number.", "danger")
        return redirect(url_for("stock"))
    ok, msg = StockService.update_stock(bg, units, action, user_id=_current_user_id())
    flash(msg, "success" if ok else "danger")
    return redirect(url_for("stock"))


# ─────────────────────────────────────────────
# API Endpoints (consumed by frontend JS)
# ─────────────────────────────────────────────

@app.route("/api/stock")
def api_stock():
    return jsonify(get_stock_dict())


@app.route("/api/compatibility/<blood_group>")
def api_compatibility(blood_group):
    return jsonify({"donors": COMPATIBILITY.get(blood_group, [])})


# ─────────────────────────────────────────────
# Error Handlers
# ─────────────────────────────────────────────

@app.errorhandler(404)
def not_found(e):
    return render_template("error.html", code=404, msg="Page not found."), 404


@app.errorhandler(500)
def server_error(e):
    app.logger.error(f"500: {e}")
    return render_template("error.html", code=500, msg="Internal server error."), 500


if __name__ == "__main__":
    debug = os.environ.get("FLASK_DEBUG", "0") == "1"
    app.run(debug=debug, port=5000)
