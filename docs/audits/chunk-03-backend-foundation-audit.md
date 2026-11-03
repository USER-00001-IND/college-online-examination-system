# Chunk 03: Backend Foundation Audit Report (Round 3 Security Corrections)

**Project:** College Online Examination System (Gauhati University FYUGP Academic Context)  
**Author:** Antigravity Agent  
**Date:** 2026-11-03 (Round 3 Revision)  
**Assigned Scope:** Chunk 03 — Backend Foundation  
**Audited Commit:** `517a05956c9545960393dce45e3ecc5bc42e2888`  
**Status:** **IN REVIEW — PENDING INDEPENDENT AUDIT** (Backend scaffolding, modular application packages, environment settings hierarchy, health check endpoint, security baselines, structured error handling, JSON/structured logging, strict request-ID normalization, and smoke test suite are complete and verified; models, domain migrations, examination logic, and background workers remain gated).

---

## 1. Scope Assigned vs. Completed

### 1.1 Objectives & Deliverables
In accordance with Chunk 03 instructions and the stage transition authorization from Chunk 02:
1. **Django/DRF Project Scaffolding:** Initialized modular Django backend layout with `backend/manage.py`, `backend/config/`, and modular application packages under `backend/apps/`.
2. **Environment Settings Hierarchy:** Implemented four-tier settings split (`base.py`, `development.py`, `production.py`, `test.py`) driven by `django-environ`.
3. **Modular Domain App Scaffolds:** Created 10 application package skeletons matching the Chunk 02 domain design (`apps.core`, `apps.accounts`, `apps.academics`, `apps.examinations`, `apps.questions`, `apps.attempts`, `apps.evidence`, `apps.uploads`, `apps.evaluations`, `apps.operations`). All domain models and migrations are strictly deferred.
4. **Health Check Endpoint:** Implemented public, credential-safe health endpoint at `/api/v1/health/` returning service liveness, environment, version, and timestamp.
5. **Centralized Error Handling:** Implemented `apps.core.exceptions.custom_exception_handler` normalizing DRF error responses into a standardized JSON envelope (`{"error": {"code": "...", "message": "...", "details": {...}, "timestamp": "..."}}`) and suppressing stack traces in production.
6. **Strict Request-ID Normalization:** Implemented centralized request identifier normalizer `apps.core.exceptions.normalize_request_id` rejecting arbitrary, malformed, or injected client identifiers, falling back to server-generated UUIDv4.
7. **Structured Logging & Redaction:** Implemented `apps.core.logging.SensitiveDataFilter` and `JSONLogFormatter` redacting passwords, PINs, tokens, and authorization headers from console and JSON log records, with complete traceback suppression in production.
8. **Security Baseline & Deployment Check:** Configured strict HTTPS security headers, secure cookie flags, and fail-closed environment validation for production. Django's `check --deploy` passes with 0 issues.
9. **Dependency Manifest & Secrets Template:** Created pinned `backend/requirements.txt` and fully documented `backend/.env.example` containing zero secrets.
10. **Automated Smoke Test Suite:** Created 62 automated unit and integration tests across 7 test modules, achieving 100% pass rate under both Django's test runner and Pytest.

---

### 1.2 Round 2 Audit Findings Summary (Preserved)

1. **Finding A (HIGH — Resolved): Sensitive Information Leakage in Production Logs:**
   - Raw exception strings (`str(exc)`), raw arguments, and `exc_info=True` were eliminated from production logging in `custom_exception_handler`.
   - `SensitiveDataFilter` suppresses `record.exc_info`, `record.exc_text`, and `record.stack_info` when `DEBUG=False`.
   - `Exception` instances in logging arguments are converted to `[ExceptionClass]`.
   - `JSONLogFormatter` excludes traceback fields in production.
2. **Finding B (MEDIUM — Resolved): Trusted Reverse Proxy Boundary:**
   - `SECURE_PROXY_SSL_HEADER = None` by default across all settings (`base.py`, `production.py`).
   - Gated behind `TRUST_PROXY_SSL_HEADER = env.bool('TRUST_PROXY_SSL_HEADER', default=False)`.
   - Rejects invalid non-boolean values via `ImproperlyConfigured`.
   - Documented required Nginx overwrite (`proxy_set_header X-Forwarded-Proto $scheme;`) and Unix socket isolation (`/run/gunicorn.sock` mode `0660`).
3. **Finding C (LOW — Resolved): Institutional Policy Test Typo:**
   - Corrected misspelled setting `INSTULTIONAL_CONFIG_APPROVED` to direct assertion `self.assertFalse(settings.INSTITUTIONAL_CONFIG_APPROVED)`.

---

### 1.3 Round 3 Audit Finding Resolution: Final Request-ID Security Correction

#### Defect & Root Cause
In `backend/apps/core/exceptions.py:106`, the exception handler previously read `HTTP_X_REQUEST_ID` directly from the request without sanitization:
```python
request_id = str(request.META.get('HTTP_X_REQUEST_ID', 'N/A'))
```
Because `HTTP_X_REQUEST_ID` is a client-controllable HTTP header, an external actor could supply malicious values containing arbitrary text, control characters, CRLF injection sequences (`\r\n`), Unicode characters, excessively long strings, or sensitive data (such as injected passwords or tokens). These unsanitized values were directly interpolated into structured production logs (`logger.error("... request_id=%s", ..., request_id)`).

#### Resolution Implemented
1. **Centralized Request-ID Normalizer (`backend/apps/core/exceptions.py:44-78`):**
   Introduced `normalize_request_id(raw_request_id: Any) -> str`:
   - **Strict Validation Pattern:** Enforces `^[A-Za-z0-9_-]{1,64}$` using full-string matching (`REQUEST_ID_REGEX.fullmatch`).
   - **Allowlist Only:** Permits only ASCII letters (`A-Z`, `a-z`), digits (`0-9`), hyphens (`-`), and underscores (`_`).
   - **Length Ceiling:** Maximum 64 characters.
   - **Strict Rejection:** Rejects empty strings, whitespace, newlines (`\n`), carriage returns (`\r`), tabs (`\t`), Unicode characters, control characters (`\x00`, `\x1b`), and disallowed punctuation.
   - **Non-String Safety:** Handles non-string input types (integers, lists, dictionaries, `None`) safely without exceptions.
   - **No Truncation & No Malformed Logging:** Malformed values are **never** truncated and accepted, and the rejected raw string is **never** logged to prevent log injection or secondary leakage.
   - **Server-Side Fallback:** When missing or invalid, generates a fresh cryptographically random UUIDv4 string via Python's standard `uuid.uuid4()`.
2. **Exception Handler Integration (`backend/apps/core/exceptions.py:149-158`):**
   `custom_exception_handler` now routes the incoming header value through `normalize_request_id`:
   ```python
   raw_request_id = None
   if request and hasattr(request, 'META') and isinstance(request.META, dict):
       raw_request_id = request.META.get('HTTP_X_REQUEST_ID')

   request_id = normalize_request_id(raw_request_id)
   ```
   The normalized identifier is used consistently across logging strings and structured extra fields (`'request_id': request_id`).
3. **Trust-Boundary Clarification:**
   - **Validated vs. Trusted Identifiers:** Syntactic regex validation ensures the identifier is safe for structured logging (preventing log pollution and CRLF injection). However, syntactic validation does **not** authenticate request origin.
   - **Ingress Proxy Obligation:** In production, Nginx must be configured to unconditionally overwrite the incoming request ID header:
     ```nginx
     proxy_set_header X-Request-ID $request_id;
     ```
   - **Security Policy:** Client-provided request IDs are never trusted for authorization, authentication, rate-limiting, or authoritative security correlation.

---

## 2. Inventory of Files Created & Modified

### 2.1 Project Infrastructure & Documentation
| File Path | Description / Role |
| :--- | :--- |
| [`.gitignore`](file:///home/zero/Documents/college/.gitignore) | Project-wide Git ignore rules covering Python bytecode, virtual environments (`.venv`), `.env` secrets, SQLite artifacts, uploads, and node caches. |
| [`requirements.txt`](file:///home/zero/Documents/college/requirements.txt) | Root pointer referencing `backend/requirements.txt`. |
| [`backend/requirements.txt`](file:///home/zero/Documents/college/backend/requirements.txt) | Pinned dependency manifest for Django 5.0, DRF 3.15, PyMySQL, django-environ, django-cors-headers, cryptography, and pytest. |
| [`.env.example`](file:///home/zero/Documents/college/.env.example) | Root environment variable template documenting `TRUST_PROXY_SSL_HEADER=False` with zero secrets. |
| [`backend/.env.example`](file:///home/zero/Documents/college/backend/.env.example) | Backend environment variable template documenting database, host, security, and reverse proxy trust boundaries. |
| [`backend/README.md`](file:///home/zero/Documents/college/backend/README.md) | Setup guide, reverse proxy security invariants, Nginx overwrite rules, request-ID normalization policy, and test instructions. |
| [`docs/development-progress.md`](file:///home/zero/Documents/college/docs/development-progress.md) | Progress tracker updated with Decision 21 documenting Round 3 request-ID security corrections. |

### 2.2 Django Core & Configuration
| File Path | Lines Changed | Description / Role |
| :--- | :--- | :--- |
| [`backend/manage.py`](file:///home/zero/Documents/college/backend/manage.py) | Unchanged | Django command-line runner ensuring `backend` is on `sys.path`. |
| [`backend/config/__init__.py`](file:///home/zero/Documents/college/backend/config/__init__.py) | Unchanged | Package initialization registering `pymysql.install_as_MySQLdb()`. |
| [`backend/config/urls.py`](file:///home/zero/Documents/college/backend/config/urls.py) | Unchanged | Root URL routing containing `/api/v1/health/`. |
| [`backend/config/wsgi.py`](file:///home/zero/Documents/college/backend/config/wsgi.py) | Unchanged | WSGI server entry point for synchronous web deployments. |
| [`backend/config/asgi.py`](file:///home/zero/Documents/college/backend/config/asgi.py) | Unchanged | ASGI server entry point for asynchronous deployments. |
| [`backend/config/settings/base.py`](file:///home/zero/Documents/college/backend/config/settings/base.py) | Unchanged | Baseline settings with `SECURE_PROXY_SSL_HEADER = None`. |
| [`backend/config/settings/development.py`](file:///home/zero/Documents/college/backend/config/settings/development.py) | Unchanged | Development settings (`DEBUG = True`, SQLite fallback, browsable API). |
| [`backend/config/settings/production.py`](file:///home/zero/Documents/college/backend/config/settings/production.py) | Unchanged | Production settings (`DEBUG = False`, `TRUST_PROXY_SSL_HEADER` validation, `len(SECRET_KEY) >= 50`). |
| [`backend/config/settings/test.py`](file:///home/zero/Documents/college/backend/config/settings/test.py) | Unchanged | Isolated unit test settings (in-memory SQLite, MD5 hashers, quiet logging). |

### 2.3 Modular Application Packages & Core Services
| File Path | Lines Changed | Description / Role |
| :--- | :--- | :--- |
| [`backend/apps/core/exceptions.py`](file:///home/zero/Documents/college/backend/apps/core/exceptions.py) | Lines 22–78, 149–158 | Implemented `REQUEST_ID_REGEX` (`^[A-Za-z0-9_-]{1,64}$`) and `normalize_request_id()`; sanitized request ID extraction in `custom_exception_handler`; removed absolute protection claims. |
| [`backend/apps/core/logging.py`](file:///home/zero/Documents/college/backend/apps/core/logging.py) | Unchanged | Preserved `SensitiveDataFilter` redaction, traceback suppression when `DEBUG=False`, and `JSONLogFormatter`. |
| 9 Domain App Skeletons | Unchanged | Scaffolds for `accounts`, `academics`, `examinations`, `questions`, `attempts`, `evidence`, `uploads`, `evaluations`, `operations` with domain models deferred. |

### 2.4 Automated Smoke Tests (`backend/tests/`)
| Test File | Tests Implemented |
| :--- | :--- |
| [`backend/tests/test_settings.py`](file:///home/zero/Documents/college/backend/tests/test_settings.py) | Verifies settings, domain apps, policy gates, development/production loading, and proxy SSL header toggles. (6 tests) |
| [`backend/tests/test_health.py`](file:///home/zero/Documents/college/backend/tests/test_health.py) | Verifies GET 200 OK, JSON content type, payload structure, credential leak prevention, unauthenticated access, and disallowed HTTP methods. (4 tests) |
| [`backend/tests/test_security.py`](file:///home/zero/Documents/college/backend/tests/test_security.py) | Verifies production `DEBUG=False`, security headers, secure cookies, proxy trust disabled by default, spoofed `X-Forwarded-Proto` rejection, explicit proxy trust enablement, and reverse-proxy documentation. (7 tests) |
| [`backend/tests/test_database_config.py`](file:///home/zero/Documents/college/backend/tests/test_database_config.py) | Verifies signed `BigAutoField` default auto field, MySQL 8.x InnoDB connection dictionary generation with strict SQL mode and utf8mb4 charset, and production MySQL engine enforcement. (3 tests) |
| [`backend/tests/test_missing_env.py`](file:///home/zero/Documents/college/backend/tests/test_missing_env.py) | Verifies fail-closed `ImproperlyConfigured` exceptions for missing/insecure `SECRET_KEY`, missing/wildcard `ALLOWED_HOSTS`, missing DB credentials, wildcard CORS, and invalid `TRUST_PROXY_SSL_HEADER`. (7 tests) |
| [`backend/tests/test_exceptions.py`](file:///home/zero/Documents/college/backend/tests/test_exceptions.py) | Verifies 400, 403, 404 envelopes; unhandled exception password/PIN/token leak prevention; traceback suppression; 16 comprehensive unit tests for `normalize_request_id` (empty, missing, spaces, newlines, CRLF, tabs, Unicode, punctuation outside allowlist, length > 64, password patterns, bearer tokens, JSON strings, control chars, non-string types); end-to-end integration tests verifying malicious request IDs are discarded and replaced with UUIDs in captured production logs. (26 tests) |
| [`backend/tests/test_logging.py`](file:///home/zero/Documents/college/backend/tests/test_logging.py) | Verifies `SensitiveDataFilter` string pattern redaction, dictionary key redaction, sequence argument redaction, custom record attribute sanitization, `Exception` arg sanitization, `exc_info` suppression, and `JSONLogFormatter` output. (9 tests) |

---

## 3. Dependency Manifest & Versions

All dependencies are installed in `.venv` and verified under Python 3.12.3:

| Package | Version | Purpose |
| :--- | :--- | :--- |
| **Django** | `5.0.14` | Core web framework, ORM baseline, and administrative foundation. |
| **djangorestframework** | `3.15.2` | RESTful API toolkit, serializers, viewsets, and exception handling. |
| **django-environ** | `0.11.2` | Twelve-factor environment variable parsing and configuration management. |
| **django-cors-headers** | `4.3.1` | Cross-Origin Resource Sharing (CORS) HTTP headers management. |
| **cryptography** | `42.0.8` | Cryptographic primitives for tokens, salts, and envelope key wrapping. |
| **PyMySQL** | `1.1.3` | Pure-Python MySQL 8.x database connector registered as `MySQLdb`. |
| **pytest** | `8.4.2` | Modern test runner and test assertion framework. |
| **pytest-django** | `4.14.0` | Pytest integration plugin for Django applications. |

---

## 4. Verification & Test Execution Results

### 4.1 Django Test Runner
Command executed:
```bash
python backend/manage.py test tests --settings=config.settings.test
```
Output:
```
Found 62 test(s).
Creating test database for alias 'default'...
System check identified no issues (0 silenced).
..............................................................
----------------------------------------------------------------------
Ran 62 tests in 0.042s

OK
Destroying test database for alias 'default'...
```

### 4.2 Pytest Execution
Command executed:
```bash
pytest backend/tests --ds=config.settings.test
```
Output:
```
============================= test session starts ==============================
platform linux -- Python 3.12.3, pytest-8.4.2, pluggy-1.7.0
django: version: 5.0.14, settings: config.settings.test (from option)
rootdir: /home/zero/Documents/college
plugins: django-4.14.0
collected 62 items

backend/tests/test_exceptions.py ..........................              [ 41%]
backend/tests/test_health.py ....                                        [ 48%]
backend/tests/test_settings.py ......                                    [ 58%]
backend/tests/test_database_config.py ...                                [ 62%]
backend/tests/test_logging.py .........                                  [ 77%]
backend/tests/test_missing_env.py .......                                [ 88%]
backend/tests/test_security.py .......                                   [100%]

============================== 62 passed in 0.49s ==============================
```

### 4.3 Django Development System Check
Command executed:
```bash
python backend/manage.py check --settings=config.settings.development
```
Output:
```
System check identified no issues (0 silenced).
```

### 4.4 Django Production Deployment Check (`check --deploy`)
Command executed:
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
Output:
```
System check identified no issues (0 silenced).
```

---

## 5. Distinction Between Unit-Tested Configuration & Unverified Deployment Infrastructure

> [!IMPORTANT]
> The automated test suite rigorously tests **Django application configuration settings**, header evaluation logic, exception handling, log redaction, request-ID normalization, and error responses within the Python test harness.
> 
> However, unit tests **cannot** physically verify external deployment infrastructure that has not yet been instantiated:
> 1. **Nginx Reverse Proxy Process & Header Overwrite:** Whether Nginx is running, terminating TLS, and configured to unconditionally overwrite `proxy_set_header X-Forwarded-Proto $scheme;` and `proxy_set_header X-Request-ID $request_id;` is an operational deployment concern to be verified during Chunk 16 (Deployment).
> 2. **Network & Socket Isolation:** Whether Gunicorn binds exclusively to a Unix domain socket (`/run/gunicorn.sock` mode `0660`) or whether external firewall rules block direct access to port 8000 must be verified on the target host environment.
> 3. **Live MySQL Daemon:** Database settings are verified against Django's MySQL dictionary schema, but no live MySQL connection or table generation has been performed in Chunk 03.
> 
> By enforcing `TRUST_PROXY_SSL_HEADER=False` by default and normalizing untrusted request identifiers via `normalize_request_id()`, the application **fails closed** against spoofed forwarded headers and malicious request identifiers even if deployed without an upstream proxy.

---

## 6. Deferred Features & Scope Restrictions

In strict adherence to the Chunk 03 instructions:
- **Application Domain Models & Migrations:** No domain models from the 52-table schema were created. All models and domain migrations are deferred to their respective authorized chunks (Chunk 04–Chunk 13).
- **Authentication & Authorization Workflows:** User login, password hashing verification, JWT/session issuance, and role checks are deferred to Chunk 04.
- **Academic Domain Features:** FYUGP curriculum structures, departments, and course enrollments are deferred to Chunk 05.
- **Examination Business Logic:** General examination scheduling, question banking, paper versions, and student eligibility checks are deferred to Chunk 08 and Chunk 09.
- **Examination Concurrency & Engine:** Attempt lifecycle, monotonic answer saving, row locks, and encrypted IndexedDB recovery are deferred to Chunk 11.
- **Transactional Outbox & Celery Workers:** Outbox dispatchers, grading workers, and Celery tasks are deferred to Chunk 12.
- **Frontend Code:** No React, Vite, or UI components were created.
- **Production Infrastructure:** No live MySQL daemon or production web server was instantiated.

---

## 7. Mandatory Future Acceptance Criteria (Carried Over)

The following criteria carried over from previous audits remain binding requirements for future chunks:
1. **Worker-Event Binding (Target: Chunk 11 / Chunk 12):**
   - The Celery grading task must strictly bind to the locked `attempts_exam_attempt` record before inspecting or updating outbox rows.
   - Task identifiers, attempt IDs, and outbox IDs must be mutually validated against persisted database records before grading evaluation begins.
2. **Outbox Claim Fencing & Terminal Immutability (Target: Chunk 11 / Chunk 12):**
   - Outbox dispatcher transitions must use the `claim_version` fencing token and guarded SQL predicates (`status = 'CLAIMED' AND claimed_by = :dispatcher_id AND claim_version = :claim_version`).
   - If `affected_rows == 0`, dispatcher must verify the current state and treat `status == 'COMPLETED'` as obsolete without overwriting.
   - Celery worker must be able to transition the outbox row to `COMPLETED` from any non-terminal state (`PUBLISHED`, `CLAIMED`, `PROCESSING`, `RETRY_PENDING`, `DEAD_LETTER`).
   - Any manual administrative intervention on `DEAD_LETTER` outbox rows must produce an immutable audit trail in `audit_system_audit_log`.
   - Comprehensive live multi-threaded / multi-process MySQL concurrency tests must be executed when outbox execution is authorized.
3. **Institutional Policy Baseline Confirmation (Target: Chunk 05 / Chunk 08):**
   - Authoritative Gauhati University roll number format template must be configured prior to student roll number generation.
   - Official letter grading scale and 10-point formula mapping must be populated in `academics_institutional_config`.
   - Hard production activation gate must prevent examination activation while `EXAM_PIN_DELIVERY_METHOD` or `EXAM_EVIDENCE_KEY_RETENTION_PERIOD` remains `UNCONFIGURED`.
   - Statutory retention schedules for private descriptive upload files (photos/PDFs) must be confirmed and configured before production deployment.

---

## 8. Final Audit Status & Declaration

* **Status:** **IN REVIEW — PENDING INDEPENDENT AUDIT**
* **Declaration:** Chunk 03 Round 3 security corrections have resolved the untrusted request-ID logging issue. The backend foundation enforces secure production exception log sanitization, strict request-ID normalization (`^[A-Za-z0-9_-]{1,64}$`), server-side UUIDv4 fallback, fail-closed reverse proxy trust boundaries, and verified institutional policy defaults. All 62 automated smoke tests pass.
* **Next Permitted Chunk:** **CHUNK 04 — AUTHENTICATION AND ROLES** (gated; strictly awaiting independent audit review and explicit user approval).
