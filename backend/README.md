# College Online Examination System — Backend Foundation (Chunk 03)

**Academic Context:** Gauhati University FYUGP (NEP 2020)  
**Framework:** Django 5.0.x / Django REST Framework 3.15.x  
**Database Target:** MySQL 8.x (InnoDB, `utf8mb4_0900_ai_ci`)  
**Status:** In Progress / Pending Independent Audit Review

---

## 1. Architecture Overview

The backend foundation provides the core infrastructure for the College Online Examination System without premature business logic implementation.

### Key Components
- **Settings Hierarchy (`config/settings/`):**
  - `base.py`: Universal configurations, installed apps, middleware, REST framework defaults, and sensitive logging filters.
  - `development.py`: Local developer environment (`DEBUG=True`, CORS/CSRF enabled for Vite frontend, SQLite fallback if MySQL is not running).
  - `production.py`: Strict security baseline (`DEBUG=False`, fail-closed environment validation, HSTS, Secure Cookies, MySQL engine enforcement, JSON logging).
  - `test.py`: Fast in-memory SQLite execution, MD5 password hashing, quiet logging.
- **Modular Domain Apps (`apps/`):**
  - `apps.core`: Utility views (Health Check), exception handling, and sensitive data logging redaction.
  - `apps.accounts`: Identity, user profiles, roles, and faculty/student credentials (Chunk 04).
  - `apps.academics`: FYUGP 4-year curriculum, departments, programs, and courses (Chunk 05).
  - `apps.examinations`: Examination sessions, schedules, and papers (Chunk 08).
  - `apps.questions`: Question bank, options, and question-paper mappings (Chunk 08).
  - `apps.attempts`: Live student attempts, answers, and concurrency locks (Chunk 11).
  - `apps.evidence`: Encrypted client cache DEK storage and recovery bundles (Chunk 11).
  - `apps.uploads`: Private descriptive answer sheet images/PDFs outside webroot (Chunk 11).
  - `apps.evaluations`: Outbox events, evaluations, and grading workers (Chunk 12).
  - `apps.operations`: Audit logs and institutional policy state (Chunk 13).
- **Security & Error Handling:**
  - Standardized JSON error response envelope (`apps.core.exceptions.custom_exception_handler`).
  - Sensitive data filter (`apps.core.logging.SensitiveDataFilter`) redacting passwords, PINs, tokens, and authorization headers in server logs.
  - Public health endpoint at `/api/v1/health/` returning liveness status without leaking secrets.

---

## 2. Local Development Setup

### 2.1 Prerequisites
- Python 3.12+
- `pip` and `venv`
- MySQL 8.x (optional for development; SQLite fallback is available when MySQL variables are omitted)

### 2.2 Environment Setup
1. Create and activate a Python virtual environment:
   ```bash
   python3 -m venv .venv
   source .venv/bin/activate
   ```

2. Install dependencies:
   ```bash
   pip install -r backend/requirements.txt
   ```

3. Configure environment variables:
   ```bash
   cp backend/.env.example backend/.env
   # Or copy to root:
   cp .env.example .env
   ```

### 2.3 Running the Development Server
```bash
cd backend
python manage.py runserver
```
The server will start at `http://127.0.0.1:8000/`.

Access the health check endpoint:
```bash
curl http://127.0.0.1:8000/api/v1/health/
```
Expected response:
```json
{
  "status": "healthy",
  "version": "1.0.0",
  "environment": "development",
  "timestamp": "2026-11-03T03:30:00.000000+00:00"
}
```

---

## 3. Running Automated Tests

Run the full smoke test suite using Django's test runner:
```bash
python backend/manage.py test tests --settings=config.settings.test
```

Or using `pytest`:
```bash
pytest backend/tests --ds=config.settings.test
```

Run Django production deployment verification checks:
```bash
SECRET_KEY="test-production-secret-key-entropy-12345" \
ALLOWED_HOSTS="exam.college.edu" \
DB_NAME="college_exam_db" \
DB_USER="college_app" \
DB_PASSWORD="password" \
DB_HOST="127.0.0.1" \
python backend/manage.py check --settings=config.settings.production --deploy
```

---

## 4. Scope Boundaries & Deferred Features

In accordance with architectural stage gating:
- **No Domain Models or Migrations:** All 52 relational tables and migrations are deferred to subsequent chunks.
- **No Examination Business Logic:** Student registration, PIN delivery, eligibility rules, and exam workflows are not implemented.
- **No Grading Workers:** Celery pipelines and transactional outbox dispatchers remain strictly gated.
- **Unconfigured Institutional Policies:** Evidence key retention periods and PIN delivery mechanisms remain unconfigured.
