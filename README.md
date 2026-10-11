# 🩸 LifeFlow — Blood Bank Management System
### Flask + SQLAlchemy | Dark Healthcare UI

---

## Quick Start (3 commands)

```bash
cd Bloodbank
pip install -r requirements.txt
python app.py
```

Open **http://localhost:5000** — Login: `admin` / `admin123`

That's it. The database initializes automatically on first run and any existing `data/donors.json` is migrated in.

---

## Configuration

Copy `.env.example` to `.env` and edit as needed:

```bash
cp .env.example .env
```

| Variable | Default | Description |
|---|---|---|
| `SECRET_KEY` | `dev-change-me-in-production` | Flask session key — **change in production** |
| `DATABASE_URL` | `sqlite:///bloodbank.db` | SQLite (default) or PostgreSQL URL |
| `ADMIN_PASSWORD` | `admin123` | Password for the initial admin account |
| `FLASK_DEBUG` | `0` | Set to `1` for debug mode (dev only) |

---

## Project Structure

```
Bloodbank/
├── app.py              # Flask app, routes, startup logic
├── models.py           # SQLAlchemy models (User, Donor, BloodRequest, BloodStock, ActivityLog)
├── services.py         # Business logic layer (DonorService, RequestService, StockService)
├── migrate.py          # One-time JSON → SQL migration (runs automatically on startup)
├── test_app.py         # Integration test suite (89 tests)
├── requirements.txt
├── .env.example
│
├── data/
│   └── donors.json          # Original JSON data (migrated automatically, backup kept as .bak)
│
├── static/
│   ├── css/style.css        # Dark healthcare theme
│   └── js/script.js         # Sidebar, counter animations, form guard
│
└── templates/
    ├── layout.html           # Base layout with sidebar
    ├── index.html            # Public home page
    ├── login.html            # Admin login
    ├── dashboard.html        # KPIs, stock chart, activity feed
    ├── donors.html           # Donor table with search/filter
    ├── add_donor.html        # Register donor form
    ├── update_donor.html     # Edit donor form
    ├── requests.html         # Request queue with filter
    ├── add_request.html      # New request form
    ├── stock.html            # Stock cards + update form
    └── error.html            # 404/500 error page
```

---

## Database Schema

```
users
  id (PK), username (unique), password_hash, role, is_active, created_at

donors
  id (PK), donor_code (unique, e.g. D001), name, age, blood_group (indexed),
  phone, email, address, last_donation (date), units_donated,
  registered_on, is_active (soft-delete)

blood_stock
  id (PK), blood_group (unique, indexed), units, updated_at

blood_requests
  id (PK), request_code (unique, e.g. R001), patient_name, blood_group (indexed),
  units_needed, hospital, contact, priority (emergency|normal),
  status (pending|fulfilled|cancelled, indexed),
  fulfilled_from (blood group actually used), requested_on, processed_at

activity_logs
  id (PK), action, timestamp (indexed), user_id (FK → users.id)
```

---

## Frontend → Backend Mapping

| Page / Action | Route | DB Operation |
|---|---|---|
| Home stats | `GET /` | `COUNT` on donors, stock SUM, requests |
| Login | `POST /login` | `SELECT users WHERE username=?` + bcrypt verify |
| Dashboard | `GET /dashboard` | Aggregates across all 5 tables |
| Donor list | `GET /donors` | `SELECT donors WHERE active + filters` |
| Add donor | `POST /donors/add` | `INSERT donor` + `UPDATE stock +units` |
| Edit donor | `POST /donors/update/<id>` | `UPDATE donor` + stock delta |
| Delete donor | `GET /donors/delete/<id>` | Soft-delete + `UPDATE stock -units` |
| Request list | `GET /requests` | `SELECT requests WHERE filters ORDER BY priority` |
| Add request | `POST /requests/add` | `INSERT blood_requests` |
| Fulfill request | `GET /requests/process/<id>` | `SELECT FOR UPDATE` stock → `UPDATE` stock and request (atomic) |
| Cancel request | `GET /requests/delete/<id>` | `UPDATE status=cancelled` |
| Stock page | `GET /stock` | `SELECT blood_stock` |
| Update stock | `POST /stock/update` | `UPDATE blood_stock units +/-` (with non-negative guard) |
| API — stock | `GET /api/stock` | `SELECT blood_stock` → JSON |
| API — compat | `GET /api/compatibility/<bg>` | In-memory lookup → JSON |

---

## Running Tests

```bash
python test_app.py
```

Uses an isolated `test_bloodbank.db` (deleted after). 89 tests covering:
- Table creation, admin seeding, stock seeding
- Full donor CRUD with validation
- Stock add/remove with non-negative guard
- Request create, fulfill, double-fulfillment prevention, cancel
- Insufficient-stock blocking
- Dashboard stats
- All HTTP routes (GET + POST)
- API endpoints
- Activity logging
- Data persistence

---

## Blood Compatibility Logic

ABO/Rh basic compatibility for packed-RBC transfusion (AABB Technical Manual reference):

| Recipient | Can receive from |
|---|---|
| A+ | A+, A-, O+, O- |
| A- | A-, O- |
| B+ | B+, B-, O+, O- |
| B- | B-, O- |
| AB+ | All groups (Universal Recipient) |
| AB- | A-, B-, AB-, O- |
| O+ | O+, O- |
| O- | O- only (Universal Donor) |

> ⚠️ Real clinical transfusion requires additional crossmatching, antibody screening, and physician oversight beyond ABO/Rh matching alone.

---

## Security Notes

- Passwords hashed with `werkzeug` PBKDF2-SHA256 — never stored plaintext
- SQLAlchemy parameterized queries — SQL injection not possible
- Session-based auth with `@login_required` decorator on all admin routes
- `SECRET_KEY` via environment variable — never hardcoded
- Debug mode off by default (`FLASK_DEBUG=0`)
- Soft deletes preserve data integrity (donors set `is_active=False`)

---

## Upgrading to PostgreSQL

1. Install: `pip install psycopg2-binary`
2. Set in `.env`:
   ```
   DATABASE_URL=postgresql://user:password@localhost:5432/bloodbank
   ```
3. Run the app — tables create automatically

---

*LifeFlow 2025 — Flask 3.0 + SQLAlchemy 2.0*
