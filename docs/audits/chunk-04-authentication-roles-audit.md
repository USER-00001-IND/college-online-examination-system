# Chunk 04: Authentication and Roles Audit Report

**Project:** College Online Examination System (Gauhati University FYUGP Academic Context)  
**Author:** Antigravity Agent  
**Date:** 2026-11-03  
**Stage:** Chunk 04 — Authentication and Roles  
**Status:** **IN REVIEW — PENDING INDEPENDENT AUDIT** (Identity models, custom User model, migrations, session authentication APIs, RBAC permission classes, password security baseline, and comprehensive test suite are complete; Chunk 05 onward remains strictly gated).

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

## 6. Audit Verdict & Recommendation

**Audit Verdict:** **READY FOR INDEPENDENT REVIEW — RECOMMENDED FOR AUDIT PASS.**

All Chunk 04 deliverables have been completely implemented, verified, and documented in strict adherence to the project specification and database architecture.

**Gating Notice:** Chunk 05 (FYUGP Academic Management) and all subsequent chunks remain strictly gated pending explicit independent audit sign-off and project owner approval.
