"""
LifeFlow Blood Bank — Service Layer
All business logic lives here, away from routes.
"""

import re
from datetime import datetime, date
from sqlalchemy.exc import SQLAlchemyError

from models import db, Donor, BloodStock, BloodRequest, ActivityLog, COMPATIBILITY, BLOOD_GROUPS


# ─────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────

def _next_code(prefix: str, model, code_col: str) -> str:
    """Generate sequential codes like D001, R001 using the DB."""
    last = (
        db.session.query(model)
        .order_by(db.text(f"{code_col} DESC"))
        .first()
    )
    if last is None:
        return f"{prefix}001"
    num = int(getattr(last, code_col)[len(prefix):])
    return f"{prefix}{num + 1:03d}"


def _log(action: str, user_id=None):
    """Append an activity log entry (does not commit)."""
    entry = ActivityLog(action=action, user_id=user_id, timestamp=datetime.utcnow())
    db.session.add(entry)


def _validate_phone(phone: str) -> bool:
    return bool(re.fullmatch(r"[0-9]{10}", phone.strip()))


def _validate_blood_group(bg: str) -> bool:
    return bg in BLOOD_GROUPS


# ─────────────────────────────────────────────
# Stock helpers
# ─────────────────────────────────────────────

def get_stock_dict() -> dict:
    rows = BloodStock.query.all()
    return {r.blood_group: r.units for r in rows}


def _stock_row(blood_group: str) -> BloodStock:
    """Fetch-or-create a BloodStock row, locking for update."""
    row = BloodStock.query.filter_by(blood_group=blood_group).with_for_update().first()
    if row is None:
        row = BloodStock(blood_group=blood_group, units=0)
        db.session.add(row)
        db.session.flush()
    return row


# ─────────────────────────────────────────────
# Donor Service
# ─────────────────────────────────────────────

class DonorService:

    @staticmethod
    def list_donors(blood_group: str = "", name: str = ""):
        q = Donor.query.filter_by(is_active=True)
        if blood_group:
            q = q.filter_by(blood_group=blood_group)
        if name:
            q = q.filter(Donor.name.ilike(f"%{name}%"))
        return q.order_by(Donor.registered_on.desc()).all()

    @staticmethod
    def get(donor_id: int) -> Donor | None:
        return Donor.query.filter_by(id=donor_id, is_active=True).first()

    @staticmethod
    def add(form: dict, user_id=None) -> tuple[bool, str]:
        """Validate and create a donor. Returns (ok, message)."""
        name  = form.get("name", "").strip()
        phone = form.get("phone", "").strip()
        bg    = form.get("blood_group", "").strip()
        units = int(form.get("units", 1) or 1)

        if not name:
            return False, "Name is required."
        if not _validate_blood_group(bg):
            return False, f"Invalid blood group '{bg}'."
        if not _validate_phone(phone):
            return False, "Phone must be exactly 10 digits."
        try:
            age = int(form.get("age", 0))
            if not (18 <= age <= 65):
                return False, "Age must be between 18 and 65."
        except (ValueError, TypeError):
            return False, "Age must be a number."
        if units < 1:
            return False, "Units must be at least 1."

        last_donation = None
        raw_date = form.get("last_donation", "").strip()
        if raw_date:
            try:
                last_donation = date.fromisoformat(raw_date)
            except ValueError:
                return False, "Invalid last donation date."

        try:
            code = _next_code("D", Donor, "donor_code")
            donor = Donor(
                donor_code    = code,
                name          = name,
                age           = age,
                blood_group   = bg,
                phone         = phone,
                email         = form.get("email", "").strip() or None,
                address       = form.get("address", "").strip() or None,
                last_donation = last_donation,
                units_donated = units,
                registered_on = date.today(),
            )
            db.session.add(donor)

            # Update stock
            stock = _stock_row(bg)
            stock.units += units

            _log(f"New donor registered: {name} ({bg}) — {units} unit(s)", user_id)
            db.session.commit()
            return True, f"Donor {name} ({code}) registered successfully."
        except SQLAlchemyError as e:
            db.session.rollback()
            return False, f"Database error: {e}"

    @staticmethod
    def update(donor_id: int, form: dict, user_id=None) -> tuple[bool, str]:
        donor = Donor.query.filter_by(id=donor_id, is_active=True).first()
        if not donor:
            return False, "Donor not found."

        name  = form.get("name", "").strip()
        phone = form.get("phone", "").strip()
        bg    = form.get("blood_group", "").strip()
        try:
            units = int(form.get("units", 1) or 1)
            age   = int(form.get("age", 0))
        except (ValueError, TypeError):
            return False, "Age and units must be numbers."

        if not name:
            return False, "Name is required."
        if not _validate_blood_group(bg):
            return False, "Invalid blood group."
        if not _validate_phone(phone):
            return False, "Phone must be 10 digits."
        if not (18 <= age <= 65):
            return False, "Age must be 18–65."

        last_donation = None
        raw = form.get("last_donation", "").strip()
        if raw:
            try:
                last_donation = date.fromisoformat(raw)
            except ValueError:
                return False, "Invalid date."

        try:
            # Reverse old stock, apply new
            old_stock = _stock_row(donor.blood_group)
            old_stock.units = max(0, old_stock.units - donor.units_donated)

            donor.name          = name
            donor.age           = age
            donor.blood_group   = bg
            donor.phone         = phone
            donor.email         = form.get("email", "").strip() or None
            donor.address       = form.get("address", "").strip() or None
            donor.last_donation = last_donation
            donor.units_donated = units

            new_stock = _stock_row(bg)
            new_stock.units += units

            _log(f"Donor updated: {name} ({bg})", user_id)
            db.session.commit()
            return True, f"Donor {name} updated."
        except SQLAlchemyError as e:
            db.session.rollback()
            return False, f"Database error: {e}"

    @staticmethod
    def delete(donor_id: int, user_id=None) -> tuple[bool, str]:
        donor = Donor.query.filter_by(id=donor_id, is_active=True).first()
        if not donor:
            return False, "Donor not found."
        try:
            stock = _stock_row(donor.blood_group)
            stock.units = max(0, stock.units - donor.units_donated)
            donor.is_active = False   # soft delete
            _log(f"Donor removed: {donor.name} ({donor.blood_group})", user_id)
            db.session.commit()
            return True, f"Donor {donor.name} deleted."
        except SQLAlchemyError as e:
            db.session.rollback()
            return False, f"Database error: {e}"


# ─────────────────────────────────────────────
# Request Service
# ─────────────────────────────────────────────

class RequestService:

    @staticmethod
    def list_requests(priority: str = "", status: str = ""):
        q = BloodRequest.query
        if priority:
            q = q.filter_by(priority=priority)
        if status:
            q = q.filter_by(status=status)
        # Emergency first, then by date
        return q.order_by(
            db.case({"emergency": 0}, value=BloodRequest.priority, else_=1),
            BloodRequest.requested_on
        ).all()

    @staticmethod
    def add(form: dict, user_id=None) -> tuple[bool, str]:
        patient = form.get("patient_name", "").strip()
        bg      = form.get("blood_group", "").strip()
        hospital = form.get("hospital", "").strip()
        contact  = form.get("contact", "").strip()
        priority = form.get("priority", "normal")

        if not patient:
            return False, "Patient name is required."
        if not _validate_blood_group(bg):
            return False, "Invalid blood group."
        if not hospital:
            return False, "Hospital is required."
        if not _validate_phone(contact):
            return False, "Contact must be 10 digits."
        if priority not in ("emergency", "normal"):
            priority = "normal"
        try:
            units = int(form.get("units_needed", 1))
            if units < 1:
                return False, "Units must be at least 1."
        except (ValueError, TypeError):
            return False, "Units must be a number."

        try:
            code = _next_code("R", BloodRequest, "request_code")
            req = BloodRequest(
                request_code = code,
                patient_name = patient,
                blood_group  = bg,
                units_needed = units,
                hospital     = hospital,
                contact      = contact,
                priority     = priority,
                status       = "pending",
                requested_on = datetime.utcnow(),
            )
            db.session.add(req)
            label = "🚨 EMERGENCY" if priority == "emergency" else "Normal"
            _log(f"{label} request: {patient} needs {bg} ({units} units) — {hospital}", user_id)
            db.session.commit()
            return True, f"Request {code} created for {patient}."
        except SQLAlchemyError as e:
            db.session.rollback()
            return False, f"Database error: {e}"

    @staticmethod
    def process(request_id: int, user_id=None) -> tuple[bool, str]:
        """
        Fulfill a request atomically:
        1. Lock the request row.
        2. Check it's still pending (prevent double fulfillment).
        3. Lock compatible stock rows and find first with sufficient units.
        4. Deduct units and mark fulfilled — all in one transaction.
        """
        try:
            req = (
                BloodRequest.query
                .filter_by(id=request_id)
                .with_for_update()
                .first()
            )
            if not req:
                return False, "Request not found."
            if req.status != "pending":
                return False, f"Request is already {req.status}."

            compatible_groups = COMPATIBILITY.get(req.blood_group, [req.blood_group])

            # Lock all relevant stock rows in a deterministic order to avoid deadlock
            stock_rows = (
                BloodStock.query
                .filter(BloodStock.blood_group.in_(compatible_groups))
                .order_by(BloodStock.blood_group)
                .with_for_update()
                .all()
            )
            stock_map = {r.blood_group: r for r in stock_rows}

            fulfilled_from = None
            for cg in compatible_groups:
                row = stock_map.get(cg)
                if row and row.units >= req.units_needed:
                    row.units -= req.units_needed
                    fulfilled_from = cg
                    break

            if fulfilled_from is None:
                total_available = sum(r.units for r in stock_rows)
                db.session.rollback()
                return False, (
                    f"Insufficient compatible blood for {req.patient_name} "
                    f"({req.blood_group}). Need {req.units_needed} unit(s), "
                    f"{total_available} total available across compatible groups."
                )

            req.status         = "fulfilled"
            req.fulfilled_from = fulfilled_from
            req.processed_at   = datetime.utcnow()

            _log(
                f"Request fulfilled: {req.patient_name} ({req.blood_group}) "
                f"using {fulfilled_from} — {req.units_needed} unit(s)",
                user_id
            )
            db.session.commit()
            return True, f"Request for {req.patient_name} fulfilled using {fulfilled_from} blood."
        except SQLAlchemyError as e:
            db.session.rollback()
            return False, f"Database error: {e}"

    @staticmethod
    def cancel(request_id: int, user_id=None) -> tuple[bool, str]:
        req = BloodRequest.query.filter_by(id=request_id).first()
        if not req:
            return False, "Request not found."
        if req.status == "fulfilled":
            return False, "Cannot cancel a fulfilled request."
        try:
            req.status = "cancelled"
            req.processed_at = datetime.utcnow()
            _log(f"Request cancelled: {req.patient_name} ({req.blood_group})", user_id)
            db.session.commit()
            return True, "Request cancelled."
        except SQLAlchemyError as e:
            db.session.rollback()
            return False, f"Database error: {e}"


# ─────────────────────────────────────────────
# Stock Service
# ─────────────────────────────────────────────

class StockService:

    @staticmethod
    def update_stock(blood_group: str, units: int, action: str, user_id=None) -> tuple[bool, str]:
        if not _validate_blood_group(blood_group):
            return False, "Invalid blood group."
        if units < 1:
            return False, "Units must be positive."
        try:
            row = _stock_row(blood_group)
            if action == "add":
                row.units += units
                msg = f"Stock updated: {blood_group} +{units} unit(s) (now {row.units})"
            else:
                if row.units < units:
                    db.session.rollback()
                    return False, f"Cannot remove {units} units — only {row.units} available."
                row.units -= units
                msg = f"Stock updated: {blood_group} -{units} unit(s) (now {row.units})"
            _log(msg, user_id)
            db.session.commit()
            return True, msg
        except SQLAlchemyError as e:
            db.session.rollback()
            return False, f"Database error: {e}"


# ─────────────────────────────────────────────
# Dashboard Stats
# ─────────────────────────────────────────────

def get_dashboard_stats() -> dict:
    total_donors    = Donor.query.filter_by(is_active=True).count()
    total_units     = db.session.query(db.func.sum(BloodStock.units)).scalar() or 0
    total_requests  = BloodRequest.query.count()
    emergency_pend  = BloodRequest.query.filter_by(priority="emergency", status="pending").count()
    pending         = BloodRequest.query.filter_by(status="pending").count()
    fulfilled       = BloodRequest.query.filter_by(status="fulfilled").count()
    eligible        = sum(1 for d in Donor.query.filter_by(is_active=True).all() if d.eligible)
    return {
        "total_donors": total_donors,
        "total_units": total_units,
        "total_requests": total_requests,
        "emergency_requests": emergency_pend,
        "pending_requests": pending,
        "fulfilled_requests": fulfilled,
        "eligible_donors": eligible,
    }
