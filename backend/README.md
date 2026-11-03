# College Online Examination System — Backend Foundation (Chunk 03)

**Academic Context:** Gauhati University FYUGP (NEP 2020)  
**Framework:** Django 5.0.x / Django REST Framework 3.15.x  
**Database Target:** MySQL 8.x (InnoDB, `utf8mb4_0900_ai_ci`)  
**Status:** In Review / Round 3 Security Corrections Applied

---

## 1. Architecture Overview

The backend foundation provides the core infrastructure for the College Online Examination System without premature business logic implementation.

### Key Components
- **Settings Hierarchy (`config/settings/`):**
  - `base.py`: Universal configurations, installed apps, middleware, REST framework defaults, signed `BigAutoField`, and logging filter definitions.
  - `development.py`: Local developer environment (`DEBUG=True`, CORS/CSRF enabled for Vite frontend, SQLite fallback if MySQL is not running, and developmental timestamp fallback).
  - `production.py`: Strict security baseline (`DEBUG=False`, fail-closed environment validation, HSTS, Secure Cookies, MySQL engine enforcement, JSON logging, fail-closed reverse proxy trust boundary).
  - `test.py`: Fast in-memory SQLite execution, MD5 password hashing, quiet logging.
- **Modular Domain Apps (`apps/`):**
  - `apps.core`: Utility views (Health Check), exception handling, and sensitive data logging redaction.
  - `apps.accounts`: Identity, user profiles, roles, and credentials (Chunk 04). Domain models deferred.
  - `apps.academics`: FYUGP 4-year curriculum, departments, programs, and courses (Chunk 05). Domain models deferred.
  - `apps.examinations`: Examination sessions, schedules, and papers (Chunk 08). Domain models deferred.
  - `apps.questions`: Question bank, options, and question-paper mappings (Chunk 08). Domain models deferred.
  - `apps.attempts`: Live student attempts, answers, and concurrency locks (Chunk 11). Domain models deferred.
  - `apps.evidence`: Encrypted client cache DEK storage and recovery bundles (Chunk 11). Domain models deferred.
  - `apps.uploads`: Private descriptive answer sheet images/PDFs outside webroot (Chunk 11). Domain models deferred.
  - `apps.evaluations`: Outbox events, evaluations, and grading workers (Chunk 12). Domain models deferred.
  - `apps.operations`: Audit logs and institutional policy state (Chunk 13). Domain models deferred.
- **Security & Error Handling:**
  - Standardized JSON error response envelope (`apps.core.exceptions.custom_exception_handler`).
  - Production exception sanitization: Unhandled 500 exceptions suppress raw exception strings, arguments, and tracebacks from both API responses and production logs. Safe structural metadata (`error_category`, `exception_type`, `view`, `request_id`) is emitted instead.
  - Request-ID normalization (`apps.core.exceptions.normalize_request_id`): Validates incoming `X-Request-ID` against strict pattern `^[A-Za-z0-9_-]{1,64}$`; invalid or missing headers generate a server-side UUIDv4.
  - Sensitive data filter (`apps.core.logging.SensitiveDataFilter`): Defense-in-depth redaction for passwords, PINs, tokens, and authorization headers in server logs.
  - Public health endpoint at `/api/v1/health/` returning liveness status without leaking secrets.

---

## 2. Reverse Proxy Security & Trust Boundary

### 2.1 The Invariant
When deployed in production, TLS termination occurs at the reverse proxy (Nginx). The upstream connection between Nginx and Gunicorn/Django is plain HTTP.
Django uses `SECURE_PROXY_SSL_HEADER = ('HTTP_X_FORWARDED_PROTO', 'https')` to know when an incoming request was originally encrypted with HTTPS.

### 2.2 Security Risks & Fail-Closed Default
If Django enables `SECURE_PROXY_SSL_HEADER` while exposed directly to untrusted networks:
1. An attacker can connect via plain HTTP and inject `X-Forwarded-Proto: https`.
2. Django will mistakenly treat the connection as secure, bypassing `SECURE_SSL_REDIRECT` and weakening CSRF and cookie protections.

### 2.3 Strict Production Requirements
- `TRUST_PROXY_SSL_HEADER` is **disabled (`False`) by default**, setting `SECURE_PROXY_SSL_HEADER = None`.
- `TRUST_PROXY_SSL_HEADER` must only be set to `True` when:
  1. **Nginx Ingress Isolation:** Nginx terminates TLS and unconditionally overwrites the header:
     ```nginx
     proxy_set_header X-Forwarded-Proto $scheme;
     ```
     (Nginx must never forward client-supplied `X-Forwarded-Proto` headers).
  2. **Direct Access Elimination:** Gunicorn/Django must be mechanically unreachable from the public internet. It must bind strictly to a Unix domain socket (e.g. `/run/gunicorn.sock` with file mode `0660` owned by `www-data:www-data`) or a tightly firewalled loopback address.

---

## 3. Request Identifier Normalization & Logging Trust Boundary

### 3.1 Normalization Specification
The backend includes a centralized request-ID normalizer (`normalize_request_id`) in `apps.core.exceptions`:
- **Allowed Format:** `^[A-Za-z0-9_-]{1,64}$` (ASCII letters, numbers, hyphens, and underscores only).
- **Length Ceiling:** Maximum 64 characters.
- **Fail-Closed Fallback:** If the header is missing, empty, exceeds 64 characters, contains whitespace, control characters, Unicode, newlines, or disallowed punctuation, it is rejected **without truncation** and **without logging the rejected input**. A fresh server-side UUIDv4 is generated and used instead.

### 3.2 Trust Boundary Clarification
- **Validated vs. Trusted Identifiers:** Syntactic regex validation ensures an incoming string is structurally safe for structured logging (preventing log injection, CRLF injection, and secret leakage). However, validation does **not** prove the identifier was generated by an authorized party.
- **Ingress Proxy Obligation:** In production, Nginx must be configured to generate or overwrite the request ID unconditionally:
  ```nginx
  proxy_set_header X-Request-ID $request_id;
  ```
- **Security Rule:** If the application cannot verify reverse proxy overwrite, client-provided request IDs must not be used for access control, authentication, or authoritative audit correlation.

---

## 4. Local Development Setup

### 4.1 Prerequisites
- Python 3.12+
- `pip` and `venv`
- MySQL 8.x (optional for development; SQLite fallback is available when MySQL variables are omitted)

### 4.2 Environment Setup
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

### 4.3 Running the Development Server
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

## 5. Running Automated Tests

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
SECRET_KEY="test-production-secret-key-with-sufficient-entropy-over-50-characters-long-12345" \
ALLOWED_HOSTS="exam.college.edu" \
DB_NAME="prod_exam_db" \
DB_USER="prod_user" \
DB_PASSWORD="password" \
DB_HOST="127.0.0.1" \
DB_PORT="3306" \
CORS_ALLOWED_ORIGINS="https://exam.college.edu" \
CSRF_TRUSTED_ORIGINS="https://exam.college.edu" \
python backend/manage.py check --settings=config.settings.production --deploy
```

---

## 6. Scope Boundaries & Deferred Features

In accordance with architectural stage gating:
- **No Domain Models or Migrations:** All 52 relational tables and migrations are deferred to subsequent chunks.
- **No Examination Business Logic:** Student registration, PIN delivery, eligibility rules, and exam workflows are not implemented.
- **No Grading Workers:** Celery pipelines and transactional outbox dispatchers remain strictly gated.
- **Unconfigured Institutional Policies:** Evidence key retention periods and PIN delivery mechanisms remain unconfigured.
