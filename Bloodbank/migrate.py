"""
LifeFlow Blood Bank — JSON → SQL Migration
Run once:  python migrate.py
Re-running is safe — duplicates are skipped by donor_code / request_code.
"""

import json, os, shutil
from datetime import date, datetime

DATA_FILE = os.path.join(os.path.dirname(__file__), "data", "donors.json")
BACKUP    = DATA_FILE + ".bak"


def run_migration(app, db, Donor, BloodRequest, BloodStock, ActivityLog, BLOOD_GROUPS):
    if not os.path.exists(DATA_FILE):
        print("[migrate] No donors.json found — skipping migration.")
        return

    # Backup first
    if not os.path.exists(BACKUP):
        shutil.copy2(DATA_FILE, BACKUP)
        print(f"[migrate] Backup saved → {BACKUP}")

    with open(DATA_FILE) as f:
        raw = json.load(f)

    with app.app_context():
        errors = []

        # ── Donors ──
        donors_imported = 0
        for d in raw.get("donors", []):
            code = d.get("id") or d.get("donor_code", "")
            if not code:
                continue
            if Donor.query.filter_by(donor_code=code).first():
                continue  # skip duplicate

            last_don = None
            raw_ld = d.get("last_donation") or d.get("last_don")
            if raw_ld:
                try:
                    last_don = date.fromisoformat(str(raw_ld))
                except ValueError:
                    errors.append(f"  Donor {code}: bad last_donation '{raw_ld}'")

            reg = date.today()
            raw_reg = d.get("registered_on")
            if raw_reg:
                try:
                    reg = date.fromisoformat(str(raw_reg))
                except ValueError:
                    pass

            try:
                bg = d.get("blood_group", "")
                units = int(d.get("units") or d.get("units_donated") or 1)
                donor = Donor(
                    donor_code    = code,
                    name          = d.get("name", "Unknown"),
                    age           = int(d.get("age", 25)),
                    blood_group   = bg,
                    phone         = d.get("phone", "0000000000"),
                    email         = d.get("email") or None,
                    address       = d.get("address") or None,
                    last_donation = last_don,
                    units_donated = units,
                    registered_on = reg,
                    is_active     = True,
                )
                db.session.add(donor)
                donors_imported += 1
            except Exception as e:
                errors.append(f"  Donor {code}: {e}")

        db.session.flush()

        # ── Requests ──
        reqs_imported = 0
        for r in raw.get("requests", []):
            code = r.get("id") or r.get("request_code", "")
            if not code:
                continue
            if BloodRequest.query.filter_by(request_code=code).first():
                continue

            requested_on = datetime.utcnow()
            raw_dt = r.get("requested_on")
            if raw_dt:
                try:
                    requested_on = datetime.fromisoformat(str(raw_dt))
                except ValueError:
                    pass

            try:
                req = BloodRequest(
                    request_code = code,
                    patient_name = r.get("patient_name", "Unknown"),
                    blood_group  = r.get("blood_group", "O+"),
                    units_needed = int(r.get("units_needed") or r.get("units") or 1),
                    hospital     = r.get("hospital", "Unknown"),
                    contact      = r.get("contact", "0000000000"),
                    priority     = r.get("priority", "normal"),
                    status       = r.get("status", "pending"),
                    requested_on = requested_on,
                )
                db.session.add(req)
                reqs_imported += 1
            except Exception as e:
                errors.append(f"  Request {code}: {e}")

        db.session.flush()

        # ── Stock ──
        stock_data = raw.get("stock", {})
        for bg in BLOOD_GROUPS:
            if not BloodStock.query.filter_by(blood_group=bg).first():
                db.session.add(BloodStock(blood_group=bg, units=int(stock_data.get(bg, 0))))

        db.session.flush()

        # ── Activity logs ──
        logs_imported = 0
        for a in raw.get("activities", []):
            action = a.get("action", "")
            if not action:
                continue
            ts = datetime.utcnow()
            raw_t = a.get("time")
            if raw_t:
                try:
                    ts = datetime.strptime(str(raw_t), "%Y-%m-%d %H:%M")
                except ValueError:
                    pass
            db.session.add(ActivityLog(action=action, timestamp=ts))
            logs_imported += 1

        db.session.commit()

        print(f"[migrate] Done — "
              f"{donors_imported} donors, {reqs_imported} requests, "
              f"{logs_imported} activity logs imported.")
        if errors:
            print("[migrate] Warnings:")
            for e in errors:
                print(e)


if __name__ == "__main__":
    from app import app
    from models import db, Donor, BloodRequest, BloodStock, ActivityLog, BLOOD_GROUPS
    with app.app_context():
        db.create_all()
    run_migration(app, db, Donor, BloodRequest, BloodStock, ActivityLog, BLOOD_GROUPS)
