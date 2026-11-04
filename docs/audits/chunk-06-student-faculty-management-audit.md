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
  - Dedicated Chunk 06 tests (`backend/tests/test_students_faculty.py`): **72 passed, 0 failed**.
  - Full repository test suite (`backend/tests/`): **481 passed, 10 skipped, 0 failed** (491 total discovered).
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
| **A** | **HIGH** | Student email verification delivery failure: `register` endpoint never sent email; token returned in API response; URL prefetchers consumed single-use tokens. | Added `send_student_verification_email` service; registration view dispatches email and fails closed (HTTP 503) on failure with automatic rollback; raw tokens removed from API response; GET without `confirm=true` inspects token safely without consuming; POST and GET with `confirm=true` consume token. |
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

## 9. Governance & Next Steps

Chunk 06 Round 2 corrections are fully implemented, verified, and submitted for independent audit review.

- **Current Status:** `IN REVIEW — PENDING INDEPENDENT AUDIT`.
- **Chunk 07 Onward:** Strictly **GATED — NOT AUTHORIZED**.
- Implementation of Table 19 (`enrollments_student_subject_enrollment`), examination scheduling, or admit cards must strictly await Chunk 06 owner approval and formal Chunk 07 authorization.
- Git commit and git push remain unexecuted pending independent audit signoff.
