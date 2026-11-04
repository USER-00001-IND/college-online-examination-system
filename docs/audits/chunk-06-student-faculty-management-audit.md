# Chunk 06: Student and Faculty Management Audit Report

**Project:** College Online Examination System (Gauhati University FYUGP Academic Context)  
**Author:** Antigravity Agent  
**Date:** 2026-11-04  
**Stage:** Chunk 06 — Student and Faculty Management (Round 2 Security, Authorization, Account Onboarding & Academic Integrity Corrections)  
**Status:** **IN REVIEW — PENDING INDEPENDENT AUDIT**  
**Authorized Scope:** Strictly limited to Chunk 06. Chunk 07 onward remains strictly gated.

---

## 1. Executive Summary

In accordance with project owner authorization (Chunk 05 APPROVED WITH WARNINGS on 2026-11-04, Chunk 06 Authorized), the implementation for Chunk 06 (Student and Faculty Management) was initially delivered and subsequently revised under Round 2 to resolve all 7 independent audit findings.

This chunk introduces the four approved relational database tables across four Django applications, establishing academic student profiles, faculty profiles, institutional programme admission ledgers, and teaching/examination paper assignments. It incorporates a multi-step student self-registration workflow with SHA-256 cryptographic email verification and mandatory administrator identity review, alongside role-based access control (RBAC), row-level concurrency locking discipline, and field-level permission scoping.

Round 2 corrections specifically addressed student email dispatch fail-closed semantics, prefetch-safe email verification token handling, secure faculty provisioning with inactive unusable accounts, deletion prohibition across profiles and academic ledgers, faculty academic record and assignment access scoping, complete-state validation on faculty assignment PATCH operations with examiner revocation protection, and bidirectional academic parent update integrity protection for student and faculty dependents.

### Verification Baseline Summary
- **Django System Check (`development`):** 0 issues identified.
- **Django System Check (`production` deploy):** 0 issues identified (0 silenced).
- **Migration Graph & Drift:** Clean acyclic dependency graph; `makemigrations --check --dry-run` reports 0 changes.
- **Automated Test Results:**
  - Dedicated Chunk 06 tests (`backend/tests/test_students_faculty.py`): **93 passed, 0 failed**.
  - Full repository test suite (`backend/tests/`): **502 passed, 10 skipped, 0 failed** (512 total discovered).
  - 10 live Redis integration tests cleanly skipped pending disposable Redis infrastructure.
- **Protected Documentation Integrity:** `design.md`, `handover.txt`, `docs/architecture.md`, and `docs/database-architecture.md` remain 100% byte-identical and untouched.
- **Git Commit Discipline:** 0 git commits or pushes executed.

---

## 2. Implemented Data Architecture & Models

Four approved database tables were implemented in strict conformance with `docs/database-architecture.md`:

| Table # | Table Name | Model Name | App | Purpose |
| :---: | :--- | :--- | :--- | :--- |
| **6** | `students_student_profile` | `StudentProfile` | `apps.students` | Academic student profile linked 1:1 to `accounts_user` with primary role `STUDENT`. |
| **7** | `faculty_faculty_profile` | `FacultyProfile` | `apps.faculty` | Academic faculty profile linked 1:1 to `accounts_user` with primary role `FACULTY`. |
| **18** | `enrollments_student_academic_record` | `StudentAcademicRecord` | `apps.enrollments` | High-level student programme enrollment ledger preserving admission status. |
| **20** | `academics_faculty_subject_assignment` | `FacultySubjectAssignment` | `apps.academics` | Faculty teaching and examination assignments for paper offerings. |

### Strictly Deferred / Excluded Models
- **Table 19 (`enrollments_student_subject_enrollment`):** Deferred strictly to **Chunk 07 (Subject Registration)**.
- Examination scheduling, attempt tracking, PIN generation, roll numbers, admit cards, grading, and dashboards remain strictly deferred and uncreated.

---

## 3. Architecture & Service Layer Implementation

### 3.1 Student Domain (`apps.students`)
1. **Model (`StudentProfile`):**
   - Enforces primary role `user.role == RoleChoices.STUDENT`.
   - Cross-college relationship validation: `programme.college_id == college_id`.
   - Semester bounds: `1 <= current_semester <= programme.duration_semesters`.
   - Referential integrity: `RESTRICT` on delete for `user`, `college`, and `programme`.
2. **Services (`apps.students.services`):**
   - `register_student`: Transactional atomic registration creating `User(is_active=False, role=STUDENT)`, `StudentProfile`, `RegistrationApproval(status=PENDING)`, and `EmailVerification(token_hash=SHA256, expires_at=+24h)`. Row-level coordination via College lock (`lock_colleges`). Raw tokens are never stored in the database.
   - `send_student_verification_email`: Dispatches email via configured `EMAIL_BACKEND`. Raises `VerificationEmailDeliveryError` on failure.
   - `verify_email_token`: Cryptographically validates raw token against SHA-256 hash under row lock. Enforces single-use (`is_used=True`) and 24-hour expiration window. Leaves `user.is_active=False`.
   - `review_student_registration`: Administrative action (`APPROVE` or `REJECT`). Enforces email verification prerequisite before approval; atomically transitions approval to `APPROVED` and activates user (`is_active=True`). On `REJECT`, requires a mandatory rejection reason and leaves account inactive. Bars administrators from approving their own registration requests.
   - `update_student_profile`: Row-level locked mutation under College lock (`lock_colleges`) and Programme row lock. Restricts students to personal contact fields (`phone_number`, `guardian_name`); administrators may update `current_semester` within programme bounds. Institutional fields (`college`, `programme`, `enrollment_number`, `registration_year`) are immutable.
3. **Permissions & Views:**
   - `IsStudentSelfOrAdmin`: Students are scoped strictly to viewing and updating their own profile (`GET /api/v1/students/profiles/me/`). Administrators have full catalogue access and filtering.
   - `RegistrationApprovalViewSet`: Restricted strictly to institutional administrators (`IsAdminUserRole`).
   - Profile deletion is strictly blocked (`destroy` raises `PermissionDenied` HTTP 403).

### 3.2 Faculty Domain (`apps.faculty`)
1. **Model (`FacultyProfile`):**
   - Enforces primary role `user.role == RoleChoices.FACULTY`.
   - Department relationship boundary: `department.college_id == college_id`.
   - Examiner eligibility flag: `is_examiner` (boolean). Revoking `is_examiner=False` while active examiner assignments exist is rejected in `clean()`.
   - Referential integrity: `RESTRICT` on delete for `user`, `college`, and `department`.
2. **Services (`apps.faculty.services`):**
   - `create_faculty_profile`: Administrative provisioning creating inactive `User(role=FACULTY, is_active=False)` with `user.set_unusable_password()` under College row lock. Passwords cannot be set at creation.
   - `update_faculty_profile`: Under row-level lock. Faculty can only update personal contact details (`phone_number`). Administrators can update `designation`, `is_examiner`, and `department` (verified to belong to the same college). Identity fields (`college`, `user`, `employee_code`) are immutable. Revoking `is_examiner=False` while assigned as `INTERNAL_EXAMINER` or `EXTERNAL_EXAMINER` is rejected with `ValidationError`.
3. **Permissions & Views:**
   - `IsFacultySelfOrAdmin`: Scopes faculty to their own profile (`GET /api/v1/faculty/profiles/me/`) and assigned paper offerings (`GET /api/v1/faculty/profiles/me/assignments/`).
   - Profile deletion is strictly blocked (`destroy` raises `PermissionDenied` HTTP 403).

### 3.3 Enrollments Domain (`apps.enrollments`)
1. **Model (`StudentAcademicRecord`):**
   - Enum `AcademicRecordStatus`: `ACTIVE`, `SUSPENDED`, `ALUMNI`, `DROPOUT`.
   - Unique constraint: `UNIQUE(student, programme, academic_session)`.
   - Cross-college boundary: verifies `student`, `programme`, and `academic_session` all belong to the same college institution.
2. **Services (`apps.enrollments.services`):**
   - `create_student_academic_record`: Admin-only. Coordinates Level 1 College row lock, locks student, programme, and session, verifies same-college relationships, and persists.
   - `update_student_academic_record`: Admin-only under row lock. Allows status and admission date updates; foreign key linkages are immutable.
3. **Permissions & Views:**
   - `IsStudentAcademicRecordPermission`: Students have read-only access strictly scoped to their own records. Faculty accounts are explicitly denied (`user.role == RoleChoices.FACULTY` returns `False`).
   - `StudentAcademicRecordViewSet.get_queryset()` returns `qs.none()` for faculty users.
   - Record deletion is strictly blocked (`destroy` raises `PermissionDenied` HTTP 403).

### 3.4 Academics Extension (`FacultySubjectAssignment`)
1. **Model (`FacultySubjectAssignment`):**
   - Enum `FacultyAssignmentRole`: `TEACHER`, `INTERNAL_EXAMINER`, `EXTERNAL_EXAMINER`, `MODERATOR`.
   - Unique constraint: `UNIQUE(faculty, paper_offering, role)`.
   - Cross-college boundary: `faculty.college_id == paper_offering.academic_session.college_id`.
   - Examiner role constraint: `INTERNAL_EXAMINER` and `EXTERNAL_EXAMINER` roles strictly require `faculty.is_examiner == True`.
2. **Services & Endpoints:**
   - `assign_faculty_to_paper`, `update_faculty_assignment`, and `delete_faculty_assignment` with College coordination locking.
   - ViewSet registered under `/api/v1/academics/faculty-assignments/`. Denies students access (HTTP 403); allows faculty read access strictly scoped to their own assignments (`qs.filter(faculty__user=request.user)`); mutations require administrator privileges.
   - `FacultySubjectAssignmentSerializer`: Implements complete-state validation on partial `PATCH` requests by merging existing instance values with validated attributes, verifying examiner eligibility and same-college boundaries before calling `update_faculty_assignment`.

### 3.5 Authentication & Self-Registration Endpoints (`apps.accounts`)
- `POST /api/v1/auth/register/`: Public self-registration endpoint. Never leaks passwords or raw verification tokens in responses. Dispatches email via `send_student_verification_email`; fails closed on delivery failure with HTTP 503 `EMAIL_DELIVERY_UNAVAILABLE` and cleanly deletes the unverified user and profile.
- `GET|POST /api/v1/auth/verify-email/`:
  - `POST {"token": "..."}`: Consumes verification token atomically.
  - `GET ?token=...&confirm=true`: Consumes verification token atomically.
  - `GET ?token=...`: Inspects token validity without consuming credentials (`status="CONFIRM_REQUIRED"`), preventing accidental token consumption by email prefetchers/scanners.

---

## 4. Round 2 Audit Corrections Detail

| Finding # | Severity | Defect Description | Resolution / Implementation Detail |
| :---: | :---: | :--- | :--- |
| **A** | **HIGH** | Student email verification delivery failure: `register` endpoint never sent email; token returned in API response; URL prefetchers consumed single-use tokens. | Added `send_student_verification_email` service; registration view dispatches email and fails closed (HTTP 503) on failure with atomic database cleanup service (`cleanup_unverified_registration`); raw tokens removed from API response; GET strictly inspects token safely without consuming credentials; POST authoritatively consumes token. |
| **B** | **HIGH** | Insecure faculty account activation: provisioning accepted admin passwords and activated accounts immediately (`is_active=True`). | Removed `password` argument from `create_faculty_profile` service and `FacultyProvisioningSerializer`; sets `user.set_unusable_password()`, `is_active=False`, `is_staff=False`, `is_superuser=False`; newly provisioned faculty cannot log in until activated. |
| **C** | **HIGH** | Unsafe profile and ledger deletion permissions: default DRF `destroy()` permitted hard deletion of profiles and academic ledgers. | Overrode `destroy()` in `StudentProfileViewSet`, `FacultyProfileViewSet`, and `StudentAcademicRecordViewSet` to raise `PermissionDenied` (HTTP 403), enforcing immutability of academic identity ledgers. |
| **D** | **HIGH** | Faculty and administrative data access scoping: faculty could access arbitrary student academic records and peer paper assignments. | `IsStudentAcademicRecordPermission` and `StudentAcademicRecordViewSet.get_queryset()` explicitly deny faculty access to student records; `IsFacultyOrAdminAssignmentPermission` and `FacultySubjectAssignmentViewSet.get_queryset()` scope faculty exclusively to their own assignments (`faculty__user=request.user`). |
| **E** | **HIGH** | Faculty assignment PATCH bypasses complete-state validation: missing serializer `update()` allowed examiner role changes without revalidating eligibility; revoking examiner flag allowed with active assignments. | Added `update_faculty_assignment` service under row locks; `FacultySubjectAssignmentSerializer` merges instance state with partial updates to validate examiner eligibility and delegates `update()` to service; revoking `is_examiner=False` while active examiner assignments exist is rejected in service and model `clean()`. |
| **F** | **HIGH** | Academic parent updates invalidate Chunk 06 records: parent updates (`Programme`, `Department`, `AcademicSession`, `PaperOffering`) did not check dependent student/faculty records. | Added dependent record integrity checks in `update_programme` (max student semester, student/record college change), `update_department` (faculty profile college change), `update_academic_session` (academic record college change), and `update_paper_offering` (faculty assignment cross-college session change), mirrored in model `clean()` methods. Added College and Programme locking in `update_student_profile`. |
| **G** | **MEDIUM** | Development progress tracker did not reflect Chunk 05 approval on 2026-11-04. | Updated `docs/development-progress.md` reflecting Chunk 05 `APPROVED WITH WARNINGS` (2026-11-04), Chunk 06 `IN REVIEW — ROUND 2 CORRECTIONS, OWNER APPROVAL PENDING`, and Chunk 07 onward strictly `GATED — NOT AUTHORIZED`. |

---

## 5. Concurrency, Locking & Isolation Architecture

1. **Lock Hierarchy Integration:**
   - Conforms to the unified Five-Level Academic Lock Hierarchy established in Chunk 05:
     - **Level 1:** Owning College coordination row lock (`lock_colleges` in deterministic ascending PK order).
     - **Level 2:** Parent academic entities (`Programme`, `Department`, `AcademicSession`).
     - **Level 3:** Child profile/ledger entities (`StudentProfile`, `FacultyProfile`, `StudentAcademicRecord`, `FacultySubjectAssignment`).
     - **Level 4:** Authoritative validation under lock.
     - **Level 5:** Atomic persistence.
2. **Single-Table Lock Discipline:**
   - All `select_for_update()` queries target single tables without joined-table row locking (`select_related()`), preventing table-lock escalation and deadlocks under MySQL InnoDB.
3. **Audit Status on Concurrency Verification:**
   - `MYSQL INNODB CONCURRENCY INTEGRATION: NOT EXECUTED`.
     - *All row-locking mechanisms are implemented using Django ORM transaction and locking primitives targeting MySQL 8 InnoDB. Tests executed under SQLite validate application logic but do not execute live multi-connection MySQL concurrency verification.*
   - `LIVE REDIS INTEGRATION: DEFERRED (10 Tests Cleanly Skipped)`.
     - *Throttling and cache operations are architected for Redis, with disposable live-redis integration tests deferred until disposable Redis test infrastructure is provisioned.*
   - `PRODUCTION NGINX / TLS REVERSE-PROXY: PENDING`.

---

## 6. Security & RBAC Privilege Escalation Defenses

1. **Separation of `is_staff` from Institutional RBAC:**
   - `is_staff=True` alone NEVER confers administrator authority.
   - Dedicated regression tests (`test_is_staff_privilege_escalation_defense`) prove that a user with `role=STUDENT` or `role=FACULTY` and `is_staff=True` is strictly rejected from:
     - Accessing registration approvals (HTTP 403).
     - Provisioning faculty accounts (HTTP 403).
     - Creating academic admission records (HTTP 403).
     - Creating or modifying faculty paper assignments (HTTP 403).
2. **Information Disclosure Prevention:**
   - Plaintext passwords and cryptographic tokens are never returned in HTTP responses or stored in plaintext.
   - `EmailVerification` persists only a one-way `SHA-256` token hash.
   - Error envelopes sanitize exceptions and avoid leaking database table names or internal SQL syntax.

---

## 7. Test Suite & Quality Assurance

72 comprehensive automated tests were authored in `backend/tests/test_students_faculty.py` and executed alongside all existing foundation tests:

```
Ran 491 tests in 6.809s
OK (skipped=10)
```

Breakdown of tests in `backend/tests/test_students_faculty.py`:
- **`StudentProfileModelAndServiceTests` (7 tests):** Model validation, role enforcement, cross-college programme rejection, semester bounds, student self-service contact update permissions, and admin semester updates.
- **`FacultyProfileModelAndServiceTests` (8 tests):** Model validation, role enforcement, cross-college department rejection, admin provisioning (inactive accounts with unusable passwords), duplicate employee code rejection, faculty self-update restrictions, and admin department reassignment.
- **`StudentAcademicRecordModelAndServiceTests` (7 tests):** Admission ledger creation, non-admin rejection, cross-college programme/session rejection, unique constraint enforcement, lifecycle status updates, and immutable field protection.
- **`FacultySubjectAssignmentModelAndServiceTests` (7 tests):** Teaching and examination assignments, non-admin rejection, cross-college rejection, examiner flag eligibility enforcement, teacher role allowance for non-examiners, uniqueness enforcement, and admin deletion.
- **`StudentRegistrationAndApprovalWorkflowTests` (11 tests):** Public self-registration, inactive account creation, token and password disclosure defense, cross-college registration rejection, duplicate username rejection, single-use email token verification, 24-hour token expiry rejection, unverified approval rejection, verified approval activation, rejection with mandatory reason, and unauthorized review rejection.
- **`StudentFacultyApiEndpointsAndRBACTests` (13 tests):** Student profile list scoping, `/me/` endpoint GET and PATCH, admin filtering, faculty profile list scoping, `/me/` and `/me/assignments/` endpoints, faculty provisioning endpoint, academic record scoping and CRUD, faculty assignment access controls, and `is_staff=True` privilege escalation defense.
- **`Chunk06Round2CorrectionsTests` (19 tests):**
  - Registration email delivery to outbox and failure rollback (HTTP 503).
  - Email token inspect safe against prefetch; GET confirm and POST token consumption.
  - Faculty provisioning inactive account with unusable password; login rejection.
  - Deletion prohibition (HTTP 403) on StudentProfile, FacultyProfile, and StudentAcademicRecord.
  - Faculty data access scoping (academic record denial; own assignments scoping).
  - Faculty assignment PATCH complete-state validation for examiner eligibility.
  - Protection against revoking examiner flag with active examiner assignments.
  - Dependent record integrity protection on parent updates (Programme duration reduction, Programme college change, Department college change, AcademicSession college change, PaperOffering cross-college session change).

---

## 8. Migration Verification

Migration sequence:
1. `backend/apps/faculty/migrations/0001_initial.py` (depends on `accounts.0001_initial`, `academics.0001_initial`).
2. `backend/apps/academics/migrations/0002_faculty_subject_assignment.py` (depends on `academics.0001_initial`, `faculty.0001_initial`).
3. `backend/apps/students/migrations/0001_initial.py` (depends on `accounts.0001_initial`, `academics.0001_initial`).
4. `backend/apps/enrollments/migrations/0001_initial.py` (depends on `students.0001_initial`, `academics.0001_initial`).

Migration plan execution order verified via `manage.py migrate --plan`. Clean execution with zero circular dependencies. `makemigrations --check --dry-run` reports 0 changes.

---

## 10. ROUND 3 — ADMINISTRATIVE AUTHORIZATION, LOCK HIERARCHY AND REGISTRATION RECOVERY

Round 3 addresses the remaining 5 independent audit findings (2 HIGH, 3 MEDIUM) alongside verification endpoint hardening.

### 10.1 Finding R3-A (HIGH) — Administrator Cross-College Authorization Scoping
1. **Root Cause:** In the approved 52-table schema ([docs/database-architecture.md](file:///home/zero/Documents/college/docs/database-architecture.md)), `accounts_user` and `accounts_user_role` contain no `college_id` column. ViewSets allowed users with generic `ADMIN` roles to query and mutate records across institutions, and query parameters (`?college=2`) allowed arbitrary filtering.
2. **Severity:** HIGH.
3. **Files Modified:**
   - `backend/apps/accounts/authorization.py` (new centralized authorization service)
   - `backend/apps/students/views.py`
   - `backend/apps/students/services.py`
   - `backend/apps/faculty/views.py`
   - `backend/apps/faculty/services.py`
   - `backend/apps/enrollments/views.py`
   - `backend/apps/enrollments/services.py`
   - `backend/apps/academics/views.py`
   - `backend/apps/academics/services.py`
4. **Exact Correction:**
   - Introduced `get_actor_authorized_college_ids(actor)` and `check_college_operation_authority(actor, college_id, operation)`.
   - Superadministrators (`SUPERADMIN` or `is_superuser`) retain system-wide access.
   - Ordinary administrators (`ADMIN` or granular roles `COLLEGE_SUPERADMIN`, `EXAM_OFFICER`) resolve scope from explicit college linkage (runtime property `college` / `college_id` or linked `FacultyProfile`).
   - If an ordinary administrator's institutional scope cannot be established, the system fails closed (raises `PermissionDenied`, returns empty querysets).
   - ViewSet `get_queryset()` methods apply college scoping before pagination or filtering; query parameters like `?college=2` can never widen access beyond authorized scope.
   - Direct service functions enforce `check_college_operation_authority` before acquiring locks or executing mutations.
5. **Authorization Behavior:** Explicit institutional administrative authority is required per target college; cross-college actions by ordinary administrators raise HTTP 403 `PermissionDenied`.
6. **Transaction Strategy:** Scoping evaluated before entering transaction; service-level checks re-verified under lock.
7. **Lock Order:** N/A (Authorization precedes Level 1 row locking).
8. **Regression Evidence:** Covered by 11 targeted tests in `Chunk06Round3CorrectionsTests` (`test_ordinary_admin_cannot_*`, `test_query_parameters_cannot_widen_admin_access`, `test_admin_with_ambiguous_scope_fails_closed`, `test_superadmin_has_multi_college_access`).
9. **Actual Test Results:** All 11 tests passed cleanly.
10. **Remaining Risks / Schema Limitation:** In the approved relational schema, `accounts_user` does not include a `college_id` foreign key. Ordinary administrators without a runtime college binding fail closed. Permanent resolution requires an architectural decision by the project owner (e.g. adding `college_id` to `accounts_user` or an approved institutional administrative mapping table).

### 10.2 Finding R3-B (HIGH) — Faculty Department Change Lock Hierarchy
1. **Root Cause:** `update_faculty_profile()` previously locked `FacultyProfile` before resolving and locking academic parent records, risking deadlocks and race conditions during concurrent department college reassignments.
2. **Severity:** HIGH.
3. **Files Modified:** `backend/apps/faculty/services.py`.
4. **Exact Correction:** Refactored `update_faculty_profile()` to adhere strictly to the Five-Level Academic Lock Hierarchy:
   - Step 1: Read minimum candidate identifiers (`college_id`, `department_id`, proposed `department`) without holding child row locks.
   - Step 2: Acquire Level 1 College coordination locks (`lock_colleges`) in deterministic ascending PK order.
   - Step 3: Acquire Level 2 Department row locks (`select_for_update`) in ascending PK order.
   - Step 4: Reload and lock `FacultyProfile` (Level 3 child entity).
   - Step 5: Revalidate that acquired College locks cover authoritative profile ownership.
   - Step 6: Verify administrative authorization for target college.
   - Step 7: Resolve complete proposed department relationship and validate same-college compatibility.
   - Step 8: Validate examiner assignment dependencies (blocking revocation of `is_examiner` with active assignments).
   - Step 9: Persist atomically.
5. **Authorization Behavior:** Enforces administrative authority or self-service restrictions under lock.
6. **Transaction Strategy:** Single atomic transaction (`@transaction.atomic`).
7. **Lock Order:** Level 1 College Coordination Lock $\rightarrow$ Level 2 Department $\rightarrow$ Level 3 FacultyProfile $\rightarrow$ Validation $\rightarrow$ Persistence.
8. **Regression Evidence:** Tested in `test_faculty_department_change_same_college_succeeds`, `test_faculty_department_change_cross_college_fails`, and `test_faculty_cannot_change_own_department`.
9. **Actual Test Results:** All passed with zero errors.
10. **Remaining Risks:** Multi-connection MySQL concurrency integration testing remains pending.

### 10.3 Finding R3-C (MEDIUM) — Faculty Assignment Update Lock-Order Inversion
1. **Root Cause:** `update_faculty_assignment()` locked `FacultySubjectAssignment` before acquiring the Level 1 College coordination lock and parent entity locks, inverting the established academic lock protocol.
2. **Severity:** MEDIUM.
3. **Files Modified:** `backend/apps/academics/services.py`.
4. **Exact Correction:** Refactored `update_faculty_assignment()`:
   - Step 1: Read candidate identifiers (`faculty_id`, `paper_offering_id`) without locking child rows.
   - Step 2: Resolve current and proposed candidate college owners from `FacultyProfile` and `PaperOffering`.
   - Step 3: Acquire Level 1 College coordination locks in ascending PK order (`lock_colleges`).
   - Step 4: Reload and lock `FacultySubjectAssignment` row.
   - Step 5: Lock relevant parent entities in consistent order: Level 2 `PaperOffering` (ordered by PK), Level 3 `FacultyProfile` (ordered by PK).
   - Step 6: Verify that acquired College locks cover authoritative owners.
   - Step 7: Resolve complete proposed state, recheck institutional administrative authority, validate same-college boundary, examiner eligibility, and uniqueness.
   - Step 8: Persist atomically.
5. **Authorization Behavior:** Validates administrator authority over target offering college.
6. **Transaction Strategy:** `@transaction.atomic`.
7. **Lock Order:** Level 1 College Coordination Lock $\rightarrow$ Level 2 PaperOffering $\rightarrow$ Level 3 FacultyProfile $\rightarrow$ Level 3 FacultySubjectAssignment $\rightarrow$ Validation $\rightarrow$ Persistence.
8. **Regression Evidence:** Tested in `test_faculty_assignment_update_college_first_locking_and_reassignment` and `test_faculty_assignment_update_cross_college_faculty_rejected`.
9. **Actual Test Results:** All passed cleanly.
10. **Remaining Risks:** Multi-connection live MySQL InnoDB concurrency verification remains pending.

### 10.4 Finding R3-D (MEDIUM) — Broken Administrator Student-Profile Creation Endpoint
1. **Root Cause:** `StudentProfileViewSet` inherited `ModelViewSet` exposing POST `/api/v1/students/profiles/`, but `StudentProfileSerializer` marked required fields (`user`, `college`, `programme`, `enrollment_number`) read-only, causing database integrity errors or unhandled 500 exceptions on direct POST.
2. **Severity:** MEDIUM.
3. **Files Modified:** `backend/apps/students/views.py`.
4. **Exact Correction:** Overrode `create()` and `perform_create()` in `StudentProfileViewSet` to raise `PermissionDenied` (HTTP 403) with an explicit, controlled error message. Direct POST creation is disabled. The exclusive authorized path for student onboarding is student self-registration (`POST /api/v1/auth/register/`) followed by administrative review and approval (`POST /api/v1/students/registrations/{id}/approve/`).
5. **Authorization Behavior:** All callers (anonymous, student, faculty, ordinary admin, superadmin) receive HTTP 403 on direct StudentProfile POST.
6. **Transaction Strategy:** N/A (Rejected at controller level).
7. **Lock Order:** N/A.
8. **Regression Evidence:** Tested in `test_direct_student_profile_post_disabled_with_403` and `test_unauthenticated_direct_student_profile_post_rejected`.
9. **Actual Test Results:** All passed with controlled HTTP 403 responses.
10. **Remaining Risks:** None.

### 10.5 Finding R3-E (MEDIUM) — Registration Email-Failure Cleanup Atomicity & Recovery
1. **Root Cause:** On verification email dispatch failure, `StudentRegisterView` executed sequential, uncoordinated `delete()` calls across multiple tables after the registration transaction had committed. If any delete failed, orphaned unverified records remained. Additionally, previous audit text inaccurately described this as an "automatic rollback".
2. **Severity:** MEDIUM.
3. **Files Modified:** `backend/apps/students/services.py`, `backend/apps/accounts/views.py`.
4. **Exact Correction:**
   - Introduced dedicated atomic cleanup service `cleanup_unverified_registration(user_id)`.
   - Executes inside `@transaction.atomic` under row lock on `User`.
   - Precondition checks under lock: verifies `user.is_active is False`, `EmailVerification.is_used is False`, and `RegistrationApproval.status == PENDING`. If any check fails (e.g. concurrent verification or approval), cleanup safely refuses deletion and aborts.
   - If preconditions are met, atomically deletes `StudentProfile`, `EmailVerification`, `RegistrationApproval`, and `User`.
   - Corrected documentation: SMTP handoff is external to database transactions; atomic cleanup is executed upon SMTP failure.
5. **Authorization Behavior:** System-internal transactional service.
6. **Transaction Strategy:** `@transaction.atomic` with row-level locks on `User`, `EmailVerification`, and `RegistrationApproval`.
7. **Lock Order:** User lock $\rightarrow$ Verification & Approval lock $\rightarrow$ State verification $\rightarrow$ Atomic deletion.
8. **Regression Evidence:** Tested in `test_registration_email_delivery_failure_atomic_cleanup_and_recovery` and `test_cleanup_unverified_registration_refuses_to_delete_verified_or_approved_user`.
9. **Actual Test Results:** Passed cleanly; repeated registration with same credentials succeeds after cleanup.
10. **Remaining Risks:** External email delivery limitations (SMTP acceptance is not inbox receipt confirmation).

### 10.6 Hardening — Email Verification Token Consumption Exclusively via POST
1. **Root Cause:** `GET /api/v1/auth/verify-email/?token=...&confirm=true` previously consumed single-use verification tokens. State-changing token consumption via GET is unsafe against email security crawlers, prefetchers, and query-string browser caching.
2. **Exact Correction:**
   - Removed `confirm=true` token consumption from `VerifyEmailView.get()`.
   - `GET` exclusively executes non-consuming token validity inspection (`_inspect_token`), returning HTTP 200 `CONFIRM_REQUIRED` if valid without modifying database state.
   - `POST {"token": "..."}` is the exclusive, authoritative token consumption endpoint.
3. **Regression Evidence:** Tested in `test_email_verification_get_never_consumes_token` and `test_student_email_verification_get_does_not_consume_token_even_with_confirm_flag`.
4. **Actual Test Results:** Passed cleanly.

---

## 11. Governance & Next Steps

Chunk 06 Round 3 corrections are fully implemented, verified, and submitted for independent audit review.

- **Current Status:** `IN REVIEW — PENDING INDEPENDENT AUDIT`.
- **Chunk 07 Onward:** Strictly **GATED — NOT AUTHORIZED**.
- Implementation of Table 19 (`enrollments_student_subject_enrollment`), examination scheduling, or admit cards must strictly await Chunk 06 owner approval and formal Chunk 07 authorization.
- Git commit and git push remain unexecuted pending independent audit signoff.
