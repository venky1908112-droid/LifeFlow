"""
LifeFlow Blood Bank — Integration Test Suite
Run:  python test_app.py
"""

import os, sys, json
os.environ["DATABASE_URL"]  = "sqlite:///test_bloodbank.db"
os.environ["SECRET_KEY"]    = "test-secret"
os.environ["ADMIN_PASSWORD"] = "testpass"

from app import app, db
from models import User, Donor, BloodRequest, BloodStock, ActivityLog, BLOOD_GROUPS
from services import DonorService, RequestService, StockService, get_dashboard_stats
from werkzeug.security import check_password_hash

PASS = 0; FAIL = 0

def check(label, cond, detail=""):
    global PASS, FAIL
    if cond:
        print(f"  ✅  {label}")
        PASS += 1
    else:
        print(f"  ❌  {label}" + (f" — {detail}" if detail else ""))
        FAIL += 1

def section(title):
    print(f"\n{'─'*55}")
    print(f"  {title}")
    print(f"{'─'*55}")


with app.app_context():

    # ── 1. DB tables ──────────────────────────────────────
    section("1. Database Table Creation")
    db.drop_all()
    db.create_all()
    from sqlalchemy import inspect
    tables = inspect(db.engine).get_table_names()
    for t in ["users","donors","blood_stock","blood_requests","activity_logs"]:
        check(f"Table '{t}' exists", t in tables)

    # ── 2. Admin seeding ──────────────────────────────────
    section("2. Admin User Seeding")
    from app import _init_db
    _init_db()
    admin = User.query.filter_by(username="admin").first()
    check("Admin user created",  admin is not None)
    check("Password is hashed",  admin and admin.password_hash != "testpass")
    check("Password verifies",   admin and check_password_hash(admin.password_hash, "testpass"))
    check("Role is admin",       admin and admin.role == "admin")

    # ── 3. Stock seeding ──────────────────────────────────
    section("3. Blood Stock Seeding")
    rows = BloodStock.query.all()
    check("All 8 blood groups seeded", len(rows) == 8)
    for bg in BLOOD_GROUPS:
        r = BloodStock.query.filter_by(blood_group=bg).first()
        check(f"  {bg} row present", r is not None)

    # ── 4. Donor CRUD ────────────────────────────────────
    section("4. Donor Management")

    ok, msg = DonorService.add({
        "name":"Test Donor","age":"28","blood_group":"O+",
        "phone":"9800000001","email":"t@t.com","address":"Hyderabad",
        "last_donation":"2020-01-01","units":"2"
    })
    check("Add donor — valid data", ok, msg)
    donor = Donor.query.filter_by(name="Test Donor").first()
    check("Donor persisted in DB", donor is not None)
    check("Donor code assigned",   donor and donor.donor_code.startswith("D"))
    check("Stock incremented +2",  BloodStock.query.filter_by(blood_group="O+").first().units == 2)
    check("Donor eligible (2020)", donor and donor.eligible is True)

    ok, msg = DonorService.add({
        "name":"","age":"25","blood_group":"A+","phone":"9800000002","units":"1"
    })
    check("Add donor — empty name rejected", not ok)

    ok, msg = DonorService.add({
        "name":"Bad Phone","age":"25","blood_group":"A+","phone":"123","units":"1"
    })
    check("Add donor — bad phone rejected", not ok)

    ok, msg = DonorService.add({
        "name":"Too Young","age":"15","blood_group":"A+","phone":"9800000003","units":"1"
    })
    check("Add donor — age<18 rejected", not ok)

    # Update
    did = donor.id
    ok, msg = DonorService.update(did, {
        "name":"Test Donor Updated","age":"29","blood_group":"O+",
        "phone":"9800000001","units":"3","last_donation":"2020-01-01"
    })
    check("Update donor", ok, msg)
    donor = Donor.query.get(did)
    check("Name updated in DB", donor.name == "Test Donor Updated")
    check("Stock reflects new units", BloodStock.query.filter_by(blood_group="O+").first().units == 3)

    # Eligibility — recent donation
    from datetime import date, timedelta
    recent = (date.today() - timedelta(days=30)).isoformat()
    ok, msg = DonorService.add({
        "name":"Recent Donor","age":"25","blood_group":"A+",
        "phone":"9800000004","units":"1","last_donation": recent
    })
    recent_donor = Donor.query.filter_by(name="Recent Donor").first()
    check("Ineligible donor created", recent_donor and not recent_donor.eligible)

    # Search
    results = DonorService.list_donors(blood_group="O+")
    check("Search by blood group works", len(results) >= 1)
    results = DonorService.list_donors(name="Updated")
    check("Search by name works", len(results) >= 1)

    # Delete
    ok, msg = DonorService.delete(did)
    check("Delete donor (soft)", ok, msg)
    donor = Donor.query.get(did)
    check("Soft-deleted donor not visible", donor and not donor.is_active)
    check("Stock reduced after delete", BloodStock.query.filter_by(blood_group="O+").first().units == 0)

    # ── 5. Stock Updates ─────────────────────────────────
    section("5. Blood Stock Management")
    a_plus_before = BloodStock.query.filter_by(blood_group="A+").first().units
    ok, msg = StockService.update_stock("A+", 10, "add")
    check("Add 10 units to A+", ok, msg)
    a_plus_after_add = BloodStock.query.filter_by(blood_group="A+").first().units
    check("A+ increased by 10", a_plus_after_add == a_plus_before + 10, f"expected {a_plus_before+10}, got {a_plus_after_add}")

    ok, msg = StockService.update_stock("A+", 3, "remove")
    check("Remove 3 units from A+", ok, msg)
    a_plus_after_rem = BloodStock.query.filter_by(blood_group="A+").first().units
    check("A+ decreased by 3", a_plus_after_rem == a_plus_after_add - 3, f"expected {a_plus_after_add-3}, got {a_plus_after_rem}")

    ok, msg = StockService.update_stock("A+", 99999, "remove")
    check("Insufficient stock rejected", not ok)
    a_plus_unchanged = BloodStock.query.filter_by(blood_group="A+").first().units
    check("A+ unchanged after failed remove", a_plus_unchanged == a_plus_after_rem, f"expected {a_plus_after_rem}, got {a_plus_unchanged}")

    ok, msg = StockService.update_stock("XX", 5, "add")
    check("Invalid blood group rejected", not ok)

    # ── 6. Blood Requests ────────────────────────────────
    section("6. Blood Request Management")

    # Load enough O+ stock for tests
    op_row = BloodStock.query.filter_by(blood_group="O+").first()
    op_row.units = 20
    db.session.commit()

    ok, msg = RequestService.add({
        "patient_name":"Test Patient","blood_group":"O+",
        "units_needed":"3","hospital":"Test Hospital",
        "contact":"9900000001","priority":"normal"
    })
    check("Add request — valid", ok, msg)
    req = BloodRequest.query.filter_by(patient_name="Test Patient").first()
    check("Request persisted in DB", req is not None)
    check("Request code assigned",   req and req.request_code.startswith("R"))
    check("Status is pending",       req and req.status == "pending")

    ok, msg = RequestService.add({
        "patient_name":"","blood_group":"O+","units_needed":"1",
        "hospital":"H","contact":"9900000002","priority":"normal"
    })
    check("Add request — empty name rejected", not ok)

    ok, msg = RequestService.add({
        "patient_name":"P","blood_group":"O+","units_needed":"1",
        "hospital":"H","contact":"123","priority":"normal"
    })
    check("Add request — bad contact rejected", not ok)

    # Process — should succeed (20 units O+ available)
    rid = req.id
    ok, msg = RequestService.process(rid)
    check("Process request — sufficient stock", ok, msg)
    req = BloodRequest.query.get(rid)
    check("Status updated to fulfilled",  req.status == "fulfilled")
    check("Fulfilled_from recorded",      req.fulfilled_from is not None)
    check("Stock deducted by 3",          BloodStock.query.filter_by(blood_group="O+").first().units == 17)

    # Double-fulfillment prevention
    ok, msg = RequestService.process(rid)
    check("Double fulfillment prevented", not ok)
    check("Stock unchanged after double", BloodStock.query.filter_by(blood_group="O+").first().units == 17)

    # Process with insufficient stock
    ok, msg = RequestService.add({
        "patient_name":"No Stock Patient","blood_group":"AB-",
        "units_needed":"100","hospital":"H",
        "contact":"9900000003","priority":"emergency"
    })
    big_req = BloodRequest.query.filter_by(patient_name="No Stock Patient").first()
    ok, msg = RequestService.process(big_req.id)
    check("Insufficient stock blocks fulfillment", not ok)
    check("Status stays pending after fail", BloodRequest.query.get(big_req.id).status == "pending")

    # Cancel
    ok, msg = RequestService.add({
        "patient_name":"Cancel Patient","blood_group":"B+",
        "units_needed":"1","hospital":"H","contact":"9900000004","priority":"normal"
    })
    cancel_req = BloodRequest.query.filter_by(patient_name="Cancel Patient").first()
    ok, msg = RequestService.cancel(cancel_req.id)
    check("Cancel pending request", ok, msg)
    check("Status is cancelled", BloodRequest.query.get(cancel_req.id).status == "cancelled")

    ok, msg = RequestService.cancel(rid)  # try to cancel fulfilled
    check("Cannot cancel fulfilled request", not ok)

    # Filtering
    RequestService.add({"patient_name":"Em Patient","blood_group":"A+","units_needed":"1","hospital":"H","contact":"9900000005","priority":"emergency"})
    em_list = RequestService.list_requests(priority="emergency")
    check("Filter by emergency works", any(r.priority=="emergency" for r in em_list))
    pend_list = RequestService.list_requests(status="pending")
    check("Filter by status works", all(r.status=="pending" for r in pend_list))

    # ── 7. Dashboard Stats ───────────────────────────────
    section("7. Dashboard Statistics")
    stats = get_dashboard_stats()
    check("total_donors >= 0",        stats["total_donors"] >= 0)
    check("total_units >= 0",         stats["total_units"] >= 0)
    check("total_requests >= 1",      stats["total_requests"] >= 1)
    check("fulfilled_requests >= 1",  stats["fulfilled_requests"] >= 1)

    # ── 8. HTTP Route Tests ──────────────────────────────
    section("8. HTTP Routes")
    client = app.test_client()

    r = client.get("/")
    check("GET / → 200", r.status_code == 200)

    r = client.get("/login")
    check("GET /login → 200", r.status_code == 200)

    r = client.get("/dashboard")
    check("GET /dashboard (unauth) → redirect", r.status_code == 302)

    # Login
    r = client.post("/login", data={"username":"admin","password":"testpass"}, follow_redirects=True)
    check("POST /login → 200", r.status_code == 200)

    r = client.get("/dashboard")
    check("GET /dashboard (authed) → 200", r.status_code == 200)
    r = client.get("/donors")
    check("GET /donors → 200", r.status_code == 200)
    r = client.get("/donors/add")
    check("GET /donors/add → 200", r.status_code == 200)
    r = client.get("/requests")
    check("GET /requests → 200", r.status_code == 200)
    r = client.get("/requests/add")
    check("GET /requests/add → 200", r.status_code == 200)
    r = client.get("/stock")
    check("GET /stock → 200", r.status_code == 200)

    r = client.get("/api/stock")
    data = json.loads(r.data)
    check("GET /api/stock → JSON dict", isinstance(data, dict) and "O+" in data)

    r = client.get("/api/compatibility/AB%2B")
    data = json.loads(r.data)
    check("GET /api/compatibility/AB+ → 8 donors", len(data["donors"]) == 8)

    r = client.get("/api/compatibility/O-")
    data = json.loads(r.data)
    check("GET /api/compatibility/O- → 1 donor (O-)", data["donors"] == ["O-"])

    # POST add donor via HTTP
    r = client.post("/donors/add", data={
        "name":"HTTP Test Donor","age":"30","blood_group":"B+",
        "phone":"9700000001","units":"1"
    }, follow_redirects=True)
    check("POST /donors/add → 200", r.status_code == 200)
    check("Donor in DB after HTTP POST", Donor.query.filter_by(name="HTTP Test Donor").first() is not None)

    # POST add request via HTTP
    r = client.post("/requests/add", data={
        "patient_name":"HTTP Test Patient","blood_group":"B+",
        "units_needed":"1","hospital":"Test H",
        "contact":"9700000002","priority":"normal"
    }, follow_redirects=True)
    check("POST /requests/add → 200", r.status_code == 200)

    # POST update stock
    b_plus_before = BloodStock.query.filter_by(blood_group="B+").first().units
    r = client.post("/stock/update", data={
        "blood_group":"B+","units":"5","action":"add"
    }, follow_redirects=True)
    check("POST /stock/update → 200", r.status_code == 200)
    b_plus_after = BloodStock.query.filter_by(blood_group="B+").first().units
    check("Stock incremented via HTTP POST", b_plus_after == b_plus_before + 5)

    r = client.get("/logout", follow_redirects=True)
    check("GET /logout → 200", r.status_code == 200)

    # ── 9. Activity Log ──────────────────────────────────
    section("9. Activity Logging")
    logs = ActivityLog.query.order_by(ActivityLog.timestamp.desc()).all()
    check("Activity logs exist", len(logs) > 0)
    check("Logs have timestamps", all(l.timestamp is not None for l in logs))

    # ── 10. Persistence (restart simulation) ─────────────
    section("10. Data Persistence After Restart")
    # Close and re-open
    db.session.remove()
    from app import app as app2
    with app2.app_context():
        donor_count = Donor.query.count()
        req_count   = BloodRequest.query.count()
        stock_rows  = BloodStock.query.count()
        check("Donors persist after session close", donor_count > 0)
        check("Requests persist after session close", req_count > 0)
        check("Stock rows persist after session close", stock_rows == 8)

    # ── Summary ──────────────────────────────────────────
    print(f"\n{'═'*55}")
    print(f"  RESULTS: {PASS} passed, {FAIL} failed")
    print(f"{'═'*55}\n")

# Cleanup test DB
if os.path.exists("test_bloodbank.db"):
    os.remove("test_bloodbank.db")

sys.exit(0 if FAIL == 0 else 1)
