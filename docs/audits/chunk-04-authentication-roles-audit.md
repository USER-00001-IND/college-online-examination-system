# Chunk 04: Authentication and Roles Audit Report (Round 3 Rate-Limiting & Concurrency Corrections)

**Project:** College Online Examination System (Gauhati University FYUGP Academic Context)  
**Author:** Antigravity Agent  
**Date:** 2026-11-03 (Round 3 Revision)  
**Stage:** Chunk 04 — Authentication and Roles  
**Last Audited Commit:** `784341672bff82651435a5a1f71addf80a3b7ffe`  
**Status:** **IN REVIEW — PENDING INDEPENDENT AUDIT** (All 3 Round 3 findings [1 HIGH, 1 MEDIUM, 1 LOW] and the client IP fallback review have been resolved, verified, and backed by 123 passing automated tests; Chunk 05 onward remains strictly gated).

---

## 1. Scope Assigned vs. Completed

### 1.1 Objectives & Deliverables
In accordance with the approved Chunk 04 implementation scope and project owner authorization:
1. **Domain A Identity Models (`apps.accounts.models`):**
   - Implemented Table 1 (`accounts_user`): Custom user model extending Django `AbstractBaseUser` with signed `BigAutoField`, indexed `username` and `email`, database column `password_hash`, institutional `role` enum (`STUDENT`, `FACULTY`, `ADMIN`, `SUPERADMIN`), `is_active`, `is_staff`, `is_superuser`, and index `idx_user_role_active`.
   - Implemented Table 2 (`accounts_role`): Granular role definitions supporting institutional RBAC (`COLLEGE_SUPERADMIN`, `EXAM_OFFICER`, `HEAD_EXAMINER`).
   - Implemented Table 3 (`accounts_user_role`): Many-to-many role assignments with `assigned_by`, `assigned_at`, and unique constraint `uk_user_role`.
   - Implemented Table 4 (`accounts_email_verification`): Verification token storage with SHA-256 token hashing, expiration cutoffs, and indexed lookups.
   - Implemented Table 5 (`accounts_registration_approval`): Administrative approval workflow tracking with `status` enum (`PENDING`, `APPROVED`, `REJECTED`) and reviewer linkage.
   - Implemented Table 8 (`accounts_auth_event`): Comprehensive audit log of authentication events (`LOGIN_SUCCESS`, `LOGIN_FAILED`, `LOGOUT`, etc.) recording client IP and User-Agent without logging passwords or secrets.
   - Strictly deferred Table 6 (`students_student_profile`) and Table 7 (`faculty_faculty_profile`) to Chunk 06 (Student and Faculty Management) due to foreign key dependencies on Domain B academic entities.
2. **Custom User Manager (`apps.accounts.managers.UserManager`):**
   - Implemented `create_user` with email normalization, role validation, and institutional onboarding defaults (`is_active=False` for students pending verification and approval).
   - Implemented `create_superuser` enforcing `is_staff=True`, `is_superuser=True`, `is_active=True`, and `role='SUPERADMIN'`.
3. **Database Migration Baseline (`apps.accounts.migrations.0001_initial`):**
   - Configured `AUTH_USER_MODEL = 'accounts.User'` in `backend/config/settings/base.py` before migration generation.
   - Generated initial migration creating all 6 approved Domain A tables and constraints.
   - Verified zero unapplied migrations and zero pending schema changes via `makemigrations --check --dry-run`.
4. **Session-Based Authentication APIs (`apps.accounts.views`):**
   - `POST /api/v1/auth/login/`: Validates username or email, performs constant-time dummy hashing for unknown accounts to resist timing attacks, verifies passwords, blocks inactive accounts with `ACCOUNT_INACTIVE`, cycles session keys to prevent fixation, updates `last_login`, records audit events, issues CSRF cookies via `ensure_csrf_cookie`, and returns user profile data.
   - `POST /api/v1/auth/logout/`: Invalidates active session, flushes session state, clears cookies, and logs `LOGOUT` audit event.
   - `GET /api/v1/auth/user/`: Returns authenticated user details and active granular roles; returns RFC 7235-compliant 401 for anonymous access.
5. **Role-Based Access Control (RBAC) Permissions (`apps.accounts.permissions`):**
   - Implemented reusable DRF permission classes: `IsAdminUserRole`, `IsFacultyUserRole`, `IsStudentUserRole`, and `IsCollegeSuperAdmin`.
   - Registered verification endpoints (`/api/v1/auth/test/admin-only/`, `/faculty-only/`, `/student-only/`) to validate server-side authorization boundaries.
6. **Authentication & Session Security Layer (`apps.accounts.authentication.ExamSessionAuthentication`):**
   - Extended DRF `SessionAuthentication` to provide an explicit `authenticate_header` (`Session realm="api"`), ensuring DRF returns 401 Unauthorized (instead of 403 Forbidden) when anonymous clients request protected endpoints.
   - Enforces strict CSRF token validation on all state-changing mutation requests (`POST`, `PUT`, `DELETE`).
7. **Dual-Identifier Authentication Backend (`apps.accounts.backends.EmailOrUsernameModelBackend`):**
   - Supports transparent authentication using either username or normalized email address.
   - Executes constant-time dummy password hashing when accounts do not exist to eliminate timing enumeration side channels.
8. **Automated Test Suite:**
   - Implemented 26 new automated unit and integration tests across `test_auth.py`, `test_permissions.py`, and `test_models.py`.
   - Total test suite now contains 88 passing tests with 0 failures and 0 errors across both `manage.py test` and `pytest`.

---

## 2. Architecture & Database Design Verification

### 2.1 Domain A Relational Schema Conformance
The implemented models strictly mirror the approved Chunk 02 specification:

| Table Name | Model Name | PK Type | DB Table | Key Constraints & Indexes |
| :--- | :--- | :---: | :--- | :--- |
| Table 1 | `User` | `BigAutoField` | `accounts_user` | `UNIQUE(username)`, `UNIQUE(email)`, `INDEX idx_user_role_active (role, is_active)` |
| Table 2 | `Role` | `BigAutoField` | `accounts_role` | `UNIQUE(code)` |
| Table 3 | `UserRole` | `BigAutoField` | `accounts_user_role` | `UniqueConstraint(user, role, name='uk_user_role')` |
| Table 4 | `EmailVerification` | `BigAutoField` | `accounts_email_verification` | `UNIQUE(token_hash)`, `INDEX idx_email_user_lookup (user, is_used)` |
| Table 5 | `RegistrationApproval` | `BigAutoField` | `accounts_registration_approval` | `OneToOneField(user)`, `INDEX idx_reg_approval_status (status, submitted_at)` |
| Table 8 | `AuthEvent` | `BigAutoField` | `accounts_auth_event` | `INDEX idx_auth_event_lookup (user, event_type, created_at)`, `INDEX idx_auth_ip_event (ip_address, event_type, created_at)` |

### 2.2 Boundary Integrity & Gated Tables
- **Domain B Separation:** Tables 6 (`students_student_profile`) and 7 (`faculty_faculty_profile`) require foreign keys to `academics_college`, `academics_programme`, and `academics_department` (Domain B). In strict accordance with the system blueprint, these profile tables are deferred to Chunk 06 and have not been created prematurely.
- **Protected Documentation:** `design.md`, `handover.txt`, `docs/architecture.md`, and `docs/database-architecture.md` remain untouched.
- **Future Chunk Isolation:** Chunk 05 (FYUGP Academic Management) and all subsequent chunks remain locked and unstarted.

---

## 3. Security Implementation & Defensive Controls

### 3.1 Account Enumeration Resistance
- **Generic Failure Response:** The login endpoint returns an identical 401 HTTP response (`AUTHENTICATION_FAILED`: `"Invalid username/email or password."`) whether the username/email does not exist or the provided password is wrong.
- **Timing Attack Mitigation:** When an identifier is not found in the database, `EmailOrUsernameModelBackend` and `LoginView` execute `UserModel().set_password(password)` to compute a dummy PBKDF2 hash calculation, eliminating execution timing discrepancies between existing and non-existing accounts.

### 3.2 Inactive Account Protection
- **Onboarding Gate:** Student accounts created through self-registration default to `is_active=False`.
- **Fail-Closed Verification:** Inactive users attempting to authenticate are rejected with HTTP 401 and machine-readable code `ACCOUNT_INACTIVE`. No session cookie is established, and a `LOGIN_FAILED` audit event is logged.

### 3.3 Session Fixation & Lifecycle Security
- **Session Key Rotation:** On successful authentication, `django.contrib.auth.login` calls `request.session.cycle_key()`, preventing session fixation attacks.
- **Complete Session Flush:** On logout, `django.contrib.auth.logout` invalidates the session record and deletes session cookies. Subsequent requests using former session cookies are rejected with HTTP 401.

### 3.4 CSRF Protection on State Mutations
- **Middleware & Authenticator Enforcement:** State-changing requests (`POST /api/v1/auth/logout/`) require valid CSRF cookies and `HTTP_X_CSRFTOKEN` headers. Requests lacking valid CSRF tokens are rejected with HTTP 403 Forbidden (`CSRF Failed`).
- **Cookie Issuance:** `LoginView` uses `@method_decorator(ensure_csrf_cookie)` to deliver the `csrftoken` cookie to clients upon initial interaction.

### 3.5 Password Storage & Validation Baseline
- **Hashing Algorithms:** Production configuration enforces salted `PBKDF2-SHA256` hashing (Django default). Plaintext passwords are never persisted.
- **Institutional Password Policies:** Configured four standard Django password validators in `base.py`:
  - `UserAttributeSimilarityValidator` (prevents passwords similar to username/email)
  - `MinimumLengthValidator` (`min_length=8`)
  - `CommonPasswordValidator` (rejects common dictionary passwords)
  - `NumericPasswordValidator` (rejects entirely numeric passwords)

### 3.6 Audit Logging & Credential Redaction
- **Audit Trails:** `accounts_auth_event` records `LOGIN_SUCCESS`, `LOGIN_FAILED`, and `LOGOUT` events alongside client IP and User-Agent.
- **Strict Data Minimization:** The `AuthEvent` table has no password or token columns. Passwords, PINs, and credentials are never stored in audit logs or structured server logs, protected by `SensitiveDataFilter`.

---

## 4. Verification and Test Execution Report

### 4.1 Automated Test Execution Summary
The test suite was executed against SQLite in-memory test database with full migrations:

```
$ .venv/bin/python backend/manage.py test tests --settings=config.settings.test
Found 88 test(s).
Creating test database for alias 'default'...
System check identified no issues (0 silenced).
........................................................................................
----------------------------------------------------------------------
Ran 88 tests in 0.259s

OK
Destroying test database for alias 'default'...
```

```
$ .venv/bin/pytest backend/tests --ds=config.settings.test
============================== test session starts ==============================
platform linux -- Python 3.12.3, pytest-8.4.2, pluggy-1.7.0
django: version: 5.0.14, settings: config.settings.test (from option)
rootdir: /home/zero/Documents/college
plugins: django-4.14.0
collected 88 items

backend/tests/test_auth.py ..........                                    [ 11%]
backend/tests/test_exceptions.py ..........................              [ 40%]
backend/tests/test_health.py ....                                        [ 45%]
backend/tests/test_models.py ..........                                  [ 56%]
backend/tests/test_permissions.py ......                                 [ 63%]
backend/tests/test_settings.py ......                                    [ 70%]
backend/tests/test_database_config.py ...                                [ 73%]
backend/tests/test_logging.py .........                                  [ 84%]
backend/tests/test_missing_env.py .......                                [ 92%]
backend/tests/test_security.py .......                                   [100%]

============================== 88 passed in 0.48s ==============================
```

### 4.2 Test Coverage by Requirement

| Requirement | Test Method | Test Module | Result |
| :--- | :--- | :--- | :---: |
| Successful login with username | `test_login_success_with_username` | `test_auth.py` | **PASS** |
| Successful login with email | `test_login_success_with_email` | `test_auth.py` | **PASS** |
| Incorrect password rejection | `test_incorrect_password_rejection` | `test_auth.py` | **PASS** |
| Unknown account rejection (enumeration resistant) | `test_unknown_account_rejection_enumeration_resistant` | `test_auth.py` | **PASS** |
| Inactive account rejection (`is_active=False`) | `test_inactive_account_rejection` | `test_auth.py` | **PASS** |
| Anonymous access to protected endpoints denied (401) | `test_anonymous_access_denied` | `test_auth.py` | **PASS** |
| Administrator permissions allow admin, deny student/faculty | `test_admin_permissions_allow_admin_deny_others` | `test_permissions.py` | **PASS** |
| Faculty permissions allow faculty/admin, deny student | `test_faculty_permissions_allow_faculty_and_admin_deny_student` | `test_permissions.py` | **PASS** |
| Student permissions allow student, deny faculty/admin | `test_student_permissions_allow_student_deny_faculty_and_admin` | `test_permissions.py` | **PASS** |
| Cross-role access matrix rejection | `test_cross_role_access_matrix` | `test_permissions.py` | **PASS** |
| Granular role assignment & escalation prevention | `test_granular_role_assignment_grants_access` | `test_permissions.py` | **PASS** |
| Superadmin permission isolation | `test_is_college_super_admin_permission` | `test_permissions.py` | **PASS** |
| Session logout flushes session & invalidates cookies | `test_logout_flushes_session` | `test_auth.py` | **PASS** |
| CSRF enforcement on state-changing requests | `test_csrf_enforcement_on_mutations` | `test_auth.py` | **PASS** |
| Password validation and PBKDF2 hashing | `test_password_validation_and_hashing` | `test_auth.py` | **PASS** |
| No credentials or passwords logged in AuthEvent | `test_no_passwords_stored_in_auth_events` | `test_auth.py` | **PASS** |
| User creation & default inactive flag for students | `test_create_standard_student` | `test_models.py` | **PASS** |
| Superuser creation & permission flags | `test_create_superuser` | `test_models.py` | **PASS** |
| Input validation on user creation | `test_create_user_empty_username_or_email_raises_error` | `test_models.py` | **PASS** |
| Role enum validation | `test_create_user_invalid_role_raises_error` | `test_models.py` | **PASS** |
| Database uniqueness constraint on username | `test_duplicate_username_constraint` | `test_models.py` | **PASS** |
| Database uniqueness constraint on email | `test_duplicate_email_constraint` | `test_models.py` | **PASS** |
| UserRole unique constraint `uk_user_role` | `test_user_role_assignment_and_uniqueness` | `test_models.py` | **PASS** |
| Email verification model & token hash | `test_email_verification_model` | `test_models.py` | **PASS** |
| Registration approval model & status | `test_registration_approval_model` | `test_models.py` | **PASS** |
| AuthEvent structure and sensitive field exclusion | `test_auth_event_model_never_stores_passwords` | `test_models.py` | **PASS** |
| Chunk 03 regression test suite (62 tests) | 7 test modules | `test_exceptions.py`, `test_health.py`, etc. | **PASS** |

### 4.3 Static and Deployment Checks
1. **Django Development Check:**
   `python backend/manage.py check --settings=config.settings.development`  
   **Result:** `System check identified no issues (0 silenced).`
2. **Django Migration Check:**
   `python backend/manage.py makemigrations --check --dry-run --settings=config.settings.development`  
   **Result:** `No changes detected.`
3. **Django Production Security Deployment Check:**
   `python backend/manage.py check --settings=config.settings.production --deploy` (with required production env vars)  
   **Result:** `System check identified no issues (0 silenced).`

---

## 5. File Inventory of Changes

### 5.1 Modified Files
- `backend/config/settings/base.py`: Registered `AUTH_USER_MODEL = 'accounts.User'`, `AUTH_PASSWORD_VALIDATORS`, `AUTHENTICATION_BACKENDS`, and `ExamSessionAuthentication`.
- `backend/config/settings/test.py`: Registered `PBKDF2PasswordHasher` alongside `MD5PasswordHasher`.
- `backend/config/urls.py`: Included `apps.accounts.urls` under `/api/v1/auth/`.
- `backend/apps/accounts/models.py`: Implemented 6 Domain A models (`User`, `Role`, `UserRole`, `EmailVerification`, `RegistrationApproval`, `AuthEvent`).
- `docs/development-progress.md`: Updated active chunk status to `IN REVIEW (Pending Independent Audit)`.

### 5.2 Created Files
- `backend/apps/accounts/managers.py`: Custom `UserManager` with `create_user` and `create_superuser`.
- `backend/apps/accounts/authentication.py`: `ExamSessionAuthentication` with RFC 7235 401 header.
- `backend/apps/accounts/backends.py`: `EmailOrUsernameModelBackend` supporting dual-identifier login and timing mitigation.
- `backend/apps/accounts/permissions.py`: Reusable RBAC permissions (`IsAdminUserRole`, `IsFacultyUserRole`, `IsStudentUserRole`, `IsCollegeSuperAdmin`).
- `backend/apps/accounts/serializers.py`: `LoginSerializer`, `UserSerializer`, `RoleSerializer`, `UserRoleAssignmentSerializer`.
- `backend/apps/accounts/urls.py`: URL wiring for auth endpoints and RBAC test views.
- `backend/apps/accounts/views.py`: `LoginView`, `LogoutView`, `CurrentUserView`, and RBAC test views.
- `backend/apps/accounts/migrations/0001_initial.py`: Initial migration for Domain A tables.
- `backend/tests/test_auth.py`: Authentication, session, enumeration, and CSRF test suite.
- `backend/tests/test_models.py`: Database models, managers, and constraints test suite.
- `backend/tests/test_permissions.py`: RBAC permissions and cross-role isolation test suite.
- `docs/audits/chunk-04-authentication-roles-audit.md`: This comprehensive audit report.

---

## 7. ROUND 2 — INDEPENDENT SECURITY AUDIT CORRECTIONS

During the independent security audit of Chunk 04 (audited commit `ee4cf67669095b1e74090debc882fe689c396050`), four security findings were identified (2 HIGH, 2 MEDIUM). All four findings, along with identified regression vectors, have been completely resolved and verified.

---

### 7.1 Finding A (HIGH): Login CSRF Vulnerability

#### 1. Severity & Classification
- **Severity:** HIGH
- **Vulnerability Category:** Cross-Site Request Forgery (CSRF) / Session Fixation Ingress
- **Affected Endpoints:** `POST /api/v1/auth/login/`

#### 2. Root Cause
`LoginView` is an unauthenticated entry point (`authentication_classes = []`, `permission_classes = [AllowAny]`). In Django REST Framework, `APIView.as_view()` unconditionally wraps view callables in `@csrf_exempt`. Because `LoginView` had no authentication classes, DRF's `SessionAuthentication.enforce_csrf()` was never executed. Although `@ensure_csrf_cookie` was attached to `LoginView`, that decorator only ensures the `csrftoken` cookie is returned in the response—it does NOT validate incoming request tokens. Consequently, incoming login requests were completely exempt from CSRF token verification.

#### 3. Exact Affected Code
- `backend/apps/accounts/views.py`: `LoginView` lines 71–84.
- `backend/apps/accounts/urls.py`: Missing explicit CSRF bootstrap route.
- `backend/config/settings/base.py`: Unconfigured `CSRF_FAILURE_VIEW`.

#### 4. Implementation Correction
1. **DRF APIView Un-Exemption (`views.py:LoginView.as_view`):**
   Overrode `as_view()` on `LoginView` to explicitly set `view.csrf_exempt = False`. This restores standard Django `CsrfViewMiddleware` execution for incoming POST requests.
2. **View-Level Defense-in-Depth (`views.py:LoginView.initial` & `enforce_csrf`):**
   Added an explicit call to `self.enforce_csrf(request)` inside `LoginView.initial()` using DRF's `CSRFCheck(dummy_get_response)`. This guarantees CSRF verification even if requests are processed through test harnesses or direct callable invocations that bypass outer WSGI middleware.
3. **Safe CSRF Bootstrap Flow (`views.py:CsrfBootstrapView` & `urls.py`):**
   Added an explicitly designated safe endpoint `GET /api/v1/auth/csrf/` decorated with `@ensure_csrf_cookie` returning `{"message": "CSRF cookie set.", "csrf_token": get_token(request)}`. Single-page applications and clients invoke this endpoint to securely obtain an initial CSRF token prior to authentication mutations.
4. **Standardized CSRF Failure Handler (`apps.core.views.csrf_failure_view` & `base.py:CSRF_FAILURE_VIEW`):**
   Implemented `csrf_failure_view` returning a standardized JSON error envelope with HTTP 403 Forbidden (`PERMISSION_DENIED: "CSRF validation failed. Token missing or invalid."`), completely suppressing internal tracebacks and server paths.

#### 5. Associated Tests
- `tests.test_auth.AuthenticationAPITests.test_csrf_bootstrap_and_login_enforcement`:
  Uses Django's `Client(enforce_csrf_checks=True)` to prove:
  - `GET /api/v1/auth/csrf/` delivers `csrftoken` cookie and token.
  - `POST /api/v1/auth/login/` without CSRF token is rejected with HTTP 403 `PERMISSION_DENIED`.
  - `POST /api/v1/auth/login/` with an invalid token is rejected with HTTP 403 `PERMISSION_DENIED`.
  - `POST /api/v1/auth/login/` with a valid CSRF token succeeds with HTTP 200, creates session, and rotates session key.
  - Authenticated session access functions properly.
  - `POST /api/v1/auth/logout/` without CSRF token is rejected with HTTP 403.
  - `POST /api/v1/auth/logout/` with valid CSRF token succeeds with HTTP 200 and invalidates the session.

---

### 7.2 Finding B (HIGH): Role Authorization Bypass via `is_staff=True`

#### 1. Severity & Classification
- **Severity:** HIGH
- **Vulnerability Category:** Broken Object Level Authorization / Privilege Escalation
- **Affected Components:** `backend/apps/accounts/permissions.py`

#### 2. Root Cause
`IsAdminUserRole` and `IsFacultyUserRole` previously contained fallback logic:
```python
if user.is_superuser or user.is_staff:
    return True
```
Django's `is_staff` flag designates administrative site access and is not equivalent to institutional administrator or faculty authority. If an active user with primary role `STUDENT` or `FACULTY` had `is_staff=True`, they were granted unrestricted access to privileged administrative and examination endpoints.

#### 3. Exact Affected Code
- `backend/apps/accounts/permissions.py`: Lines 22–24 in `IsAdminUserRole`, Lines 43–45 in `IsFacultyUserRole`, and related checks in `IsCollegeSuperAdmin`.

#### 4. Implementation Correction
1. **Separation of Django Staff Flags from Institutional RBAC:**
   `is_staff=True` alone NEVER grants institutional administrator or faculty privileges.
2. **Hard Compartmentalization for Student Accounts:**
   Explicitly checks `if user.role == RoleChoices.STUDENT: return False` as the initial gate in `IsAdminUserRole`, `IsFacultyUserRole`, and `IsCollegeSuperAdmin`. Students cannot escalate privileges through staff flags or misconfigured role links.
3. **Faculty / Admin Boundary:**
   `FACULTY` accounts with `is_staff=True` are strictly barred from `IsAdminUserRole`.
4. **Legitimate Superadmin Authority Preserved:**
   `user.role == RoleChoices.SUPERADMIN` (or `user.is_superuser` when combined with administrative primary roles) retains institutional governance authority.
5. **Approved Granular Roles Only:**
   Granular privileges via `UserRole` are restricted to approved role codes:
   - Administrative: `COLLEGE_SUPERADMIN`, `EXAM_OFFICER`
   - Faculty/Examiner: `FACULTY`, `HEAD_EXAMINER`, `EXAMINER`
   - Unrelated granular roles (e.g. `INVIGILATOR`, `LAB_ASSISTANT`) are strictly rejected from granting excessive privileges.

#### 5. Updated Permission Evaluation Matrix
| Primary Role | `is_staff` | Granular Role | Admin Endpoint | Faculty Endpoint | Student Endpoint |
|---|:---:|:---:|:---:|:---:|:---:|
| `STUDENT` | `False` | None | **DENIED (403)** | **DENIED (403)** | **PERMITTED (200)** |
| `STUDENT` | `True` | None | **DENIED (403)** | **DENIED (403)** | **PERMITTED (200)** |
| `STUDENT` | `True` | `EXAM_OFFICER` | **DENIED (403)** | **DENIED (403)** | **PERMITTED (200)** |
| `FACULTY` | `False` | None | **DENIED (403)** | **PERMITTED (200)** | **DENIED (403)** |
| `FACULTY` | `True` | None | **DENIED (403)** | **PERMITTED (200)** | **DENIED (403)** |
| `FACULTY` | `False` | `EXAM_OFFICER` | **PERMITTED (200)** | **PERMITTED (200)** | **DENIED (403)** |
| `FACULTY` | `False` | `INVIGILATOR` | **DENIED (403)** | **PERMITTED (200)** | **DENIED (403)** |
| `ADMIN` | `False` | None | **PERMITTED (200)** | **PERMITTED (200)** | **DENIED (403)** |
| `ADMIN` | `True` | None | **PERMITTED (200)** | **PERMITTED (200)** | **DENIED (403)** |
| `SUPERADMIN` | `True` | `COLLEGE_SUPERADMIN` | **PERMITTED (200)** | **PERMITTED (200)** | **DENIED (403)** |

#### 6. Associated Tests
- `tests.test_permissions.RoleBasedAccessControlTests`:
  - `test_is_staff_flag_alone_does_not_grant_admin_or_faculty_access`
  - `test_unrelated_granular_role_does_not_grant_privileged_access`
  - `test_student_cannot_be_escalated_via_granular_role`
  - `test_inactive_and_anonymous_users_strictly_denied`

---

### 7.3 Finding C (MEDIUM): Login Rate Limiting & Brute-Force Throttling

#### 1. Severity & Classification
- **Severity:** MEDIUM
- **Vulnerability Category:** Lack of Authentication Rate Limiting / Automated Password Guessing
- **Affected Endpoints:** `POST /api/v1/auth/login/`

#### 2. Root Cause
The public authentication endpoint did not enforce application-level rate limiting, allowing unrestricted automated password guessing and credential-stuffing attacks.

#### 3. Exact Affected Code
- `backend/apps/accounts/views.py`: `LoginView.post` lines 82–120.
- `backend/config/settings/base.py`: Missing throttling configuration parameters and cache definitions.
- `backend/config/settings/production.py`: Missing cache backend validation gate.

#### 4. Implementation Correction
1. **Dedicated Throttling Engine (`apps.accounts.throttling.AuthenticationThrottle`):**
   Implemented a server-side rate limiter using Django's atomic cache primitives (`cache.add()`, `cache.incr()`, `cache.get()`, `cache.delete()`).
2. **Dual-Dimension Protection:**
   - **IP-Level Throttle:** Maximum 15 attempts per 5-minute sliding window (`AUTH_THROTTLE_IP_LIMIT = 15`, `AUTH_THROTTLE_IP_WINDOW = 300`). Prevents distributed credential stuffing across multiple accounts from a single host.
   - **Target Compound Throttle (IP + Normalized Identifier):** Maximum 5 attempts per 5-minute sliding window (`AUTH_THROTTLE_TARGET_LIMIT = 5`, `AUTH_THROTTLE_TARGET_WINDOW = 300`). Prevents targeted brute-forcing against individual accounts while preventing attackers from causing widespread account lockout of legitimate users from other IPs.
3. **Execution Before Password Verification:**
   The throttle check runs immediately upon request receipt, before expensive database lookups and PBKDF2 hash calculations, protecting server CPU resources.
4. **Standardized HTTP 429 Response:**
   Exceeded limits return HTTP 429 Too Many Requests with standardized envelope `RATE_LIMIT_EXCEEDED` and a compliant `Retry-After: <seconds>` HTTP response header.
5. **Identifier Normalization & Credential Safety:**
   Identifiers are normalized (stripped of control characters and lowercased). Cache keys store SHA-256 digests (`auth_throttle:ip:<sha256>`, `auth_throttle:target:<sha256>`). Raw identifiers, passwords, and tokens are NEVER stored in cache keys.
6. **Account Enumeration Resistance:**
   Existing and non-existing accounts follow the identical throttling curve and return the identical 429 response structure.
7. **Reset on Success:**
   Successful logins reset the compound target counter, preventing false-positive lockouts for legitimate users who mistype their password once or twice.
8. **Production Cache Gate (`production.py`):**
   Enforces that `DummyCache` is strictly forbidden in production, raising `ImproperlyConfigured`. Multi-worker production deployment requires configuring a distributed shared cache (`REDIS_URL` or `DatabaseCache`).

#### 5. Associated Tests
- `tests.test_throttling.AuthenticationThrottlingTests`:
  - `test_requests_below_threshold_permitted`
  - `test_exceeding_target_threshold_returns_429`
  - `test_case_and_whitespace_variations_do_not_bypass_throttling`
  - `test_throttling_does_not_reveal_account_existence`
  - `test_single_user_attack_does_not_block_different_user`
  - `test_successful_login_resets_target_attempts`
  - `test_spoofed_ip_header_does_not_bypass_ip_throttle`
  - `test_production_cache_gate_rejects_dummy_cache`

---

### 7.4 Finding D (MEDIUM): Authentication Audit Metadata Validation & Integrity

#### 1. Severity & Classification
- **Severity:** MEDIUM
- **Vulnerability Category:** Untrusted Ingress Metadata / Log & Database Injection / Audit Bypasses
- **Affected Components:** `backend/apps/accounts/views.py:_get_client_ip`, `_log_auth_event`

#### 2. Root Cause
- `_get_client_ip()` previously trusted `X-Forwarded-For` based on `TRUST_PROXY_SSL_HEADER`. Deciding whether to trust HTTPS scheme termination from a reverse proxy is completely separate from determining whether forwarded client IP headers are authentic.
- The helper performed zero syntactic validation on IP strings, merely truncating raw strings to 45 characters. Injected script tags, CRLF characters, or SQL fragments could enter audit logs.
- Login identifiers and User-Agent strings were unvalidated, allowing CRLF injection (`\r\n`) and multiline log poisoning.
- `_log_auth_event()` caught and suppressed all exceptions during `AuthEvent.objects.create()`, allowing login sessions to be established without a durable audit record.

#### 3. Exact Affected Code
- `backend/apps/accounts/views.py`: `_get_client_ip`, `_get_user_agent`, `_log_auth_event`.
- `backend/config/settings/base.py`: Missing `TRUST_PROXY_CLIENT_IP`.
- `backend/config/settings/production.py`: Missing `TRUST_PROXY_CLIENT_IP` validation.

#### 4. Implementation Correction
1. **Dedicated Audit Services Module (`apps.accounts.audit`):**
   Centralized metadata validation in `backend/apps/accounts/audit.py`.
2. **Independent IP Trust Boundary (`TRUST_PROXY_CLIENT_IP`):**
   Created `TRUST_PROXY_CLIENT_IP = env.bool('TRUST_PROXY_CLIENT_IP', default=False)` in `base.py` and validated in `production.py`. Completely decoupled from `TRUST_PROXY_SSL_HEADER`.
3. **Strict IP Address Validation via Python `ipaddress`:**
   `get_validated_client_ip()` parses candidate IP strings through `ipaddress.ip_address()`. Any non-IP, spoofed, or malformed value is rejected and falls back safely to validated `REMOTE_ADDR` (or default `'127.0.0.1'`). Supports IPv4 and IPv6.
4. **Metadata Sanitization & Control-Character Stripping:**
   `sanitize_identifier()` and `sanitize_user_agent()` strip all ASCII control characters (`[\x00-\x1f\x7f]`), eliminating CRLF injection, null-byte poisoning, and multiline log forging. Enforces column length limits (254 chars for identifier, 255 chars for User-Agent).
5. **Fail-Closed Audit Persistence Policy (`record_auth_event`):**
   - For `LOGIN_SUCCESS`: Enforces `raise_on_failure=True`. If persisting the `AuthEvent` fails (e.g. database failure), an `AuditPersistenceError` is raised, session creation is aborted, and a standardized 500 error is returned. No user can obtain an active authenticated session without a durable audit record.
   - For `LOGIN_FAILED`: Enforces `raise_on_failure=False`. Emits a critical alert in server logs without leaking database exceptions to clients or blocking error reporting.
6. **Credential Redaction Guarantee:**
   `AuthEvent` has no password or token fields. Password strings, secrets, and bearer tokens are never persisted in audit tables or server logs.

#### 5. Associated Tests
- `tests.test_audit.AuditMetadataValidationTests`:
  - `test_direct_remote_addr_used_when_proxy_trust_disabled`
  - `test_forwarded_ip_accepted_when_proxy_trust_enabled`
  - `test_ipv6_address_validated_correctly`
  - `test_invalid_ip_header_rejected_and_falls_back`
  - `test_missing_client_metadata_defaults_safely`
  - `test_crlf_and_control_characters_stripped_from_identifier`
  - `test_oversized_identifier_truncated_safely`
  - `test_crlf_and_control_characters_stripped_from_user_agent`
  - `test_oversized_user_agent_truncated_safely`
  - `test_login_success_fails_closed_when_audit_persistence_fails`
  - `test_login_failed_logs_error_without_crashing_when_audit_persistence_fails`
  - `test_audit_event_never_stores_credentials`

---

### 7.5 Additional Security Improvements
- **Password Validator Enforcement in Custom Manager:**
  Updated `backend/apps/accounts/managers.py:create_user()` to explicitly invoke `django.contrib.auth.password_validation.validate_password(password, user=user)`. Tested via `test_create_user_enforces_password_validation` in `test_models.py`.

---

## 8. Verification and Test Results Summary (Round 2 Baseline)

- **Round 2 Test Suite:** 113 passing tests.
- **Round 2 Audit Verdict:** Revision required (1 HIGH, 1 MEDIUM, 1 LOW).

---

## 9. Round 3 — Production Throttling, Concurrency, and Privilege Escalation Corrections

### 9.1 Summary of Addressed Findings

| Finding ID | Severity | Description | Status |
| :--- | :---: | :--- | :---: |
| **Finding 1** | **HIGH** | Unsafe production authentication cache defaults to local memory (`LocMemCache`) | **RESOLVED** |
| **Finding 2** | **MEDIUM** | Non-atomic rate-limit admission allows concurrent brute-force race conditions | **RESOLVED** |
| **Finding 3** | **LOW** | Privilege-escalation regression test uses arbitrary role code instead of institutional `EXAM_OFFICER` | **RESOLVED** |
| **Review Item**| **DEFENSE**| Client IP fallback returns `'127.0.0.1'` when `REMOTE_ADDR` is missing or invalid | **RESOLVED** |

---

### 9.2 Finding 1 (HIGH) — Mandatory Production Shared Cache Enforcement

#### 1. Root Cause
In Round 2, `backend/config/settings/production.py` used `env.cache('REDIS_URL', default=None)`. If operators did not provide `REDIS_URL` or `CACHE_URL`, Django defaulted to local-memory caching (`LocMemCache`). In a multi-worker production environment (e.g., Gunicorn with 4–8 workers), each worker maintained an independent in-memory cache, fragmenting brute-force rate-limit counters and allowing attackers to multiply allowable login attempts by the number of active workers.

#### 2. Resolution & Production Gate
- Updated `backend/config/settings/production.py`:
  - Strictly requires `REDIS_URL` or `CACHE_URL` environment variable.
  - Validates cache URL scheme strictly against approved shared cache protocols (`redis://`, `rediss://`, `unix://`).
  - Configures `CACHES['default']` with `django.core.cache.backends.redis.RedisCache`.
  - Rejects `LocMemCache`, `DummyCache`, `FileBasedCache`, `DatabaseCache`, or missing cache variables with a blocking `django.core.exceptions.ImproperlyConfigured`.
  - Documented production Redis requirements and cluster topologies in `backend/.env.example` and `.env.example`.
  - Installed `redis>=5.0.0,<6.0.0` (version 5.3.1) in `backend/requirements.txt`.

#### 3. Verification
- `tests.test_throttling.ProductionCacheSettingsGateTests`:
  - `test_production_rejects_missing_cache_url`: Confirms `ImproperlyConfigured` is raised when neither `REDIS_URL` nor `CACHE_URL` is set.
  - `test_production_rejects_unsupported_cache_scheme`: Confirms `ImproperlyConfigured` is raised when unsupported schemes (e.g. `locmem://`, `file://`) are provided.
  - `test_production_configures_redis_cache_when_valid`: Confirms `RedisCache` is configured and bound when valid `redis://` URL is provided.

---

### 9.3 Finding 2 (MEDIUM) — Atomic Check-and-Reserve Rate-Limit Admission

#### 1. Root Cause & Concurrency Vulnerability
In Round 2, rate limiting followed a check-then-increment pattern: `LoginView` checked if attempts were within limits using `cache.get()`, proceeded with password verification, and only incremented the counter via `record_attempt()` post-authentication. Under concurrent bursts, multiple parallel requests could evaluate `is_admitted() == True` before any failed attempt was committed, allowing attackers to perform high-volume credential stuffing within a single concurrency window.

#### 2. Resolution: Check-and-Reserve Admission Semantics
- Redesigned `backend/apps/accounts/throttling.py` around `acquire_admission(ip, identifier) -> (admitted, retry_after, reason)`:
  - **Check-and-Reserve Pattern:** Every login request atomically checks the threshold and reserves an attempt counter slot *before* password verification or hashing is executed.
  - **Redis Lua Script Atomicity (`REDIS_CHECK_AND_RESERVE_LUA`):**
    ```lua
    local ip_key = KEYS[1]
    local target_key = KEYS[2]
    local ip_limit = tonumber(ARGV[1])
    local ip_window = tonumber(ARGV[2])
    local target_limit = tonumber(ARGV[3])
    local target_window = tonumber(ARGV[4])

    local ip_count = tonumber(redis.call('get', ip_key) or '0')
    if ip_count >= ip_limit then
        local ttl = redis.call('ttl', ip_key)
        return {0, ttl, 'IP_LIMIT'}
    end

    local target_count = tonumber(redis.call('get', target_key) or '0')
    if target_count >= target_limit then
        local ttl = redis.call('ttl', target_key)
        return {0, ttl, 'TARGET_LIMIT'}
    end

    local new_ip = redis.call('incr', ip_key)
    if new_ip == 1 then
        redis.call('expire', ip_key, ip_window)
    end

    local new_target = redis.call('incr', target_key)
    if new_target == 1 then
        redis.call('expire', target_key, target_window)
    end

    return {1, 0, 'OK'}
    ```
  - **Local/Test Thread-Locked Atomic Cache:** For non-Redis caches in development and testing, an identical check-and-reserve transaction is executed under `_local_throttle_lock = threading.RLock()`.
  - **Standardized HTTP 429:** Denied requests immediately return HTTP 429 Too Many Requests (`RATE_LIMIT_EXCEEDED`) with a RFC-compliant `Retry-After: <seconds>` HTTP header.
  - **Fail-Closed on Infrastructure Outage:** If the cache backend is unavailable or throws an exception, `acquire_admission()` raises `ThrottleBackendError`. `LoginView` catches this and returns HTTP 503 Service Unavailable (`SERVICE_UNAVAILABLE`). Crucially, zero password verification, dummy hashing, or PBKDF2 operations are executed, preserving backend resources during cache failures.
  - **Target Attempt Reset:** On successful authentication, target identifier attempts are cleared via `reset_target(ip, identifier)` to restore access for legitimate users. The IP-level attempt counter is deliberately retained to prevent password spraying across multiple student accounts from a single IP.

#### 3. Concurrency Test Evidence
- `tests.test_throttling.ConcurrentRateLimitingTests`:
  - **Test A (`test_concurrency_same_ip_burst`):** 30 concurrent threads submit admission requests for the same IP (limit = 15). Exactly 15 are admitted, and 15 are denied with `IP_LIMIT`. Zero race condition leakage.
  - **Test B (`test_concurrency_same_identifier_burst`):** 20 concurrent threads submit admission requests for the same identifier (limit = 5). Exactly 5 are admitted, and 15 are denied with `TARGET_LIMIT` and positive `Retry-After`.
  - **Test C (`test_shared_worker_state`):** Independent throttle instances sharing the underlying cache observe identical counters and enforce thresholds uniformly.
  - **Test D (`test_backend_failure_fails_closed_without_password_check`):** Simulating a cache backend failure returns HTTP 503 `SERVICE_UNAVAILABLE` and asserts `mock_check_password.assert_not_called()`.
  - **Test E (`test_sliding_window_expiration`):** Exhausts a 1-second window, waits for expiration, and confirms subsequent attempts are successfully admitted.
  - **Test F (`test_boundary_single_slot_remaining`):** With 1 slot remaining, 10 concurrent threads attempt admission; exactly 1 succeeds and 9 are rejected.

---

### 9.4 Finding 3 (LOW) — Institutional Role Privilege-Escalation Regression Test

#### 1. Root Cause
In Round 2, `test_student_cannot_be_escalated_via_granular_role` used a synthetic role code `EXAM_OFFICER_STUDENT_TEST`. While it verified basic role non-escalation, it did not exercise the actual institutional role `EXAM_OFFICER` (`RoleChoices.EXAM_OFFICER`) against the real permission classes.

#### 2. Resolution & Verification
- Updated `backend/tests/test_permissions.py:test_student_cannot_be_escalated_via_granular_role`:
  - Creates the authentic institutional role `Role.objects.create(code=RoleChoices.EXAM_OFFICER, name='Examination Officer')`.
  - Assigns this role to an active student user via `UserRole`.
  - Asserts `student.has_role(RoleChoices.EXAM_OFFICER)` is `True`.
  - Requests `/api/v1/auth/test/admin-only/` with authenticated student session -> returns HTTP 403 Forbidden.
  - Requests `/api/v1/auth/test/faculty-only/` with authenticated student session -> returns HTTP 403 Forbidden.
  - Evaluates `IsCollegeSuperAdmin().has_permission(request, None)` -> returns `False`.
  - Requests `/api/v1/auth/test/student-only/` with authenticated student session -> returns HTTP 200 OK.

---

### 9.5 Client IP Fallback Review — Fail-Closed Ingress Resolution

#### 1. Root Cause & Review
In Round 2, `get_validated_client_ip()` defaulted candidate IP strings to `'127.0.0.1'` when `REMOTE_ADDR` was missing or syntactically invalid. In production or behind improperly configured proxies, this could cause distinct external clients with missing headers to share the loopback rate-limit bucket or bypass IP tracking.

#### 2. Resolution
- Updated `backend/apps/accounts/audit.py:get_validated_client_ip()`:
  - If `REMOTE_ADDR` is missing or syntactically invalid, returns `None` (never fabricates `'127.0.0.1'`).
- Updated `backend/apps/accounts/views.py:LoginView`:
  - If `ip_address is None`, immediately rejects the request with HTTP 400 Bad Request (`VALIDATION_ERROR: "Unable to determine client IP address."`).
  - Completely stops authentication processing and bypasses password verification.
- Verified in `tests.test_audit.AuditMetadataValidationTests`:
  - `test_missing_remote_addr_returns_none`
  - `test_malformed_remote_addr_returns_none`
  - `test_login_fails_closed_when_client_ip_cannot_be_determined`

---

### 9.6 Unverified Infrastructure Assumptions

> [!IMPORTANT]
> **REDIS CONCURRENCY VERIFICATION: NOT EXECUTED**
> All automated concurrency tests (`ConcurrentRateLimitingTests`) were executed in the test environment using Python's `concurrent.futures.ThreadPoolExecutor` against the thread-locked atomic cache implementation (`_local_throttle_lock`).
> Testing against a live, running Redis cluster daemon with real network socket latency was **NOT executed** in this environment because no live Redis service is running locally.
> The atomic Redis Lua script (`REDIS_CHECK_AND_RESERVE_LUA`) was statically analyzed and validated, but full live multi-node Redis cluster validation remains an operational deployment verification requirement (carried over to Chunk 16 Deployment).

---

## 10. Verification and Test Results Summary

```bash
$ .venv/bin/python backend/manage.py test tests --settings=config.settings.test
Found 123 test(s).
Creating test database for alias 'default'...
System check identified no issues (0 silenced).
...........................................................................................................................
----------------------------------------------------------------------
Ran 123 tests in 1.537s

OK
Destroying test database for alias 'default'...
```

```bash
$ .venv/bin/pytest backend/tests --ds=config.settings.test
============================= 123 passed in 1.79s ==============================
```

- **Django Development Check:** `System check identified no issues (0 silenced).`
- **Django Migration Dry-Run:** `No changes detected.`
- **Django Production Deploy Check:** `System check identified no issues (0 silenced).`
- **Protected Files Integrity:** [`design.md`](file:///home/zero/Documents/college/design.md), [`handover.txt`](file:///home/zero/Documents/college/handover.txt), [`docs/architecture.md`](file:///home/zero/Documents/college/docs/architecture.md), and [`docs/database-architecture.md`](file:///home/zero/Documents/college/docs/database-architecture.md) remain strictly unmodified.
- **Stage Gating:** Chunk 04 is complete and submitted for independent audit. Chunk 05 onward remains strictly gated.


