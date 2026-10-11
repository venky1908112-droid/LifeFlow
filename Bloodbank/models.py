"""
LifeFlow Blood Bank — SQLAlchemy Models
Relational schema: User, Donor, BloodRequest, BloodStock, ActivityLog
"""

from datetime import datetime
from flask_sqlalchemy import SQLAlchemy

db = SQLAlchemy()

# ─── Blood compatibility matrix (medically validated ABO/Rh for packed-RBC transfusion) ───
# Source: AABB Technical Manual. Note: real clinical decisions require additional
# antibody screening; this logic covers basic ABO/Rh compatibility only.
BLOOD_GROUPS = ["A+", "A-", "B+", "B-", "AB+", "AB-", "O+", "O-"]

COMPATIBILITY = {
    "A+":  ["A+", "A-", "O+", "O-"],
    "A-":  ["A-", "O-"],
    "B+":  ["B+", "B-", "O+", "O-"],
    "B-":  ["B-", "O-"],
    "AB+": ["A+", "A-", "B+", "B-", "AB+", "AB-", "O+", "O-"],
    "AB-": ["A-", "B-", "AB-", "O-"],
    "O+":  ["O+", "O-"],
    "O-":  ["O-"],
}


# ─── User ───
class User(db.Model):
    __tablename__ = "users"

    id       = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(64), unique=True, nullable=False, index=True)
    password_hash = db.Column(db.String(256), nullable=False)
    role     = db.Column(db.String(16), nullable=False, default="admin")  # admin | staff
    is_active = db.Column(db.Boolean, default=True, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    def __repr__(self):
        return f"<User {self.username}>"


# ─── Donor ───
class Donor(db.Model):
    __tablename__ = "donors"

    id            = db.Column(db.Integer, primary_key=True)
    donor_code    = db.Column(db.String(10), unique=True, nullable=False, index=True)  # e.g. D001
    name          = db.Column(db.String(120), nullable=False)
    age           = db.Column(db.Integer, nullable=False)
    blood_group   = db.Column(db.String(4), nullable=False, index=True)
    phone         = db.Column(db.String(15), nullable=False)
    email         = db.Column(db.String(120), nullable=True)
    address       = db.Column(db.String(200), nullable=True)
    last_donation = db.Column(db.Date, nullable=True)
    units_donated = db.Column(db.Integer, default=1, nullable=False)
    registered_on = db.Column(db.Date, default=datetime.utcnow, nullable=False)
    is_active     = db.Column(db.Boolean, default=True, nullable=False)

    @property
    def eligible(self):
        """True if 90+ days since last donation, or never donated."""
        if self.last_donation is None:
            return True
        delta = (datetime.utcnow().date() - self.last_donation).days
        return delta >= 90

    @property
    def days_since_donation(self):
        if self.last_donation is None:
            return None
        return (datetime.utcnow().date() - self.last_donation).days

    def to_dict(self):
        return {
            "id": self.id,
            "donor_code": self.donor_code,
            "name": self.name,
            "age": self.age,
            "blood_group": self.blood_group,
            "phone": self.phone,
            "email": self.email,
            "address": self.address,
            "last_donation": self.last_donation.isoformat() if self.last_donation else None,
            "units_donated": self.units_donated,
            "eligible": self.eligible,
            "registered_on": self.registered_on.isoformat(),
        }

    def __repr__(self):
        return f"<Donor {self.donor_code} {self.name}>"


# ─── Blood Stock ───
class BloodStock(db.Model):
    __tablename__ = "blood_stock"

    id          = db.Column(db.Integer, primary_key=True)
    blood_group = db.Column(db.String(4), unique=True, nullable=False, index=True)
    units       = db.Column(db.Integer, default=0, nullable=False)
    updated_at  = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    def __repr__(self):
        return f"<BloodStock {self.blood_group}: {self.units}>"


# ─── Blood Request ───
class BloodRequest(db.Model):
    __tablename__ = "blood_requests"

    id           = db.Column(db.Integer, primary_key=True)
    request_code = db.Column(db.String(10), unique=True, nullable=False, index=True)  # e.g. R001
    patient_name = db.Column(db.String(120), nullable=False)
    blood_group  = db.Column(db.String(4), nullable=False, index=True)
    units_needed = db.Column(db.Integer, nullable=False)
    hospital     = db.Column(db.String(200), nullable=False)
    contact      = db.Column(db.String(15), nullable=False)
    priority     = db.Column(db.String(16), nullable=False, default="normal")  # emergency | normal
    status       = db.Column(db.String(16), nullable=False, default="pending", index=True)  # pending | fulfilled | cancelled
    fulfilled_from = db.Column(db.String(4), nullable=True)   # blood group actually used
    requested_on = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    processed_at = db.Column(db.DateTime, nullable=True)

    def to_dict(self):
        return {
            "id": self.id,
            "request_code": self.request_code,
            "patient_name": self.patient_name,
            "blood_group": self.blood_group,
            "units_needed": self.units_needed,
            "hospital": self.hospital,
            "contact": self.contact,
            "priority": self.priority,
            "status": self.status,
            "requested_on": self.requested_on.strftime("%Y-%m-%d"),
        }

    def __repr__(self):
        return f"<BloodRequest {self.request_code} {self.patient_name}>"


# ─── Activity Log ───
class ActivityLog(db.Model):
    __tablename__ = "activity_logs"

    id          = db.Column(db.Integer, primary_key=True)
    action      = db.Column(db.String(500), nullable=False)
    timestamp   = db.Column(db.DateTime, default=datetime.utcnow, nullable=False, index=True)
    user_id     = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=True)

    user = db.relationship("User", backref="activities")

    def __repr__(self):
        return f"<ActivityLog {self.timestamp}: {self.action[:40]}>"
