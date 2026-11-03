# Chunk 05: FYUGP Academic Management Backend Audit Report

**Project:** College Online Examination System (Gauhati University FYUGP Academic Context)  
**Author:** Antigravity Agent  
**Date:** 2026-11-03  
**Stage:** Chunk 05 — FYUGP Academic Management  
**Status:** **IN REVIEW — PENDING INDEPENDENT AUDIT** (Implementation complete, backed by 36 dedicated academic tests, 232 total passing tests, 10 cleanly skipped live Redis tests, zero failures, clean Django system checks, and strict database schema compliance; Chunk 06 onward remains strictly gated).

---

## 1. Implementation Scope & Assigned Deliverables

In accordance with the project owner authorization for Chunk 05, the backend foundation for FYUGP Academic Structure and Management (Domain B) has been implemented:

1. **Academic Hierarchy Models (`apps.academics.models`):**
   - Implemented all 10 approved Domain B tables:
     - Table 9: `academics_college` (`College`)
     - Table 10: `academics_academic_session` (`AcademicSession`)
     - Table 11: `academics_programme` (`Programme`)
     - Table 12: `academics_department` (`Department`)
     - Table 13: `academics_semester` (`Semester`)
     - Table 14: `academics_subject_category` (`SubjectCategory`)
     - Table 15: `academics_subject` (`Subject`)
     - Table 16: `academics_paper_offering` (`PaperOffering`)
     - Table 17: `academics_paper_programme_mapping` (`PaperProgrammeMapping`)
     - Table 21: `academics_institutional_config` (`InstitutionalConfig`)
   - Strictly deferred Domain B tables outside Chunk 05 scope:
     - Table 18: `enrollments_student_academic_record` (Future student/enrollment stage).
     - Table 19: `enrollments_student_subject_enrollment` (Chunk 07 Subject Registration).
     - Table 20: `academics_faculty_subject_assignment` (Chunk 06 Student & Faculty Management).
2. **Database Migration (`apps.academics.migrations.0001_initial`):**
   - Generated initial migration creating all 10 approved tables, constraints, indexes, and foreign keys.
   - Verified zero unapplied migrations and zero schema drift via `makemigrations --check --dry-run`.
3. **Academic Service Layer (`apps.academics.services`):**
   - `validate_academic_session_dates`: Enforces `start_date < end_date`.
   - `set_current_academic_session`: Transactional atomic session designation with automatic de-duplication of active sessions per college.
   - `validate_paper_offering_relationships`: Cross-college relationship validation, semester bound checks, credit range validation, and non-negative mark constraints.
   - `create_paper_offering`: Relational integrity validation and paper creation.
   - `map_paper_to_programmes`: Transactional common-paper programme mapping, cross-college verification, and programme duration coverage validation.
   - `set_institutional_config`: Typed institutional key-value store with string, integer, boolean, and JSON serialization.
4. **Institutional RBAC Permissions (`apps.academics.permissions`):**
   - `IsAcademicAdminOrReadOnly`: Allows active authenticated users (Admin, Faculty, Student) to browse the academic catalogue; mutations strictly require administrative privileges (`IsAdminUserRole` or `IsCollegeSuperAdmin`).
   - `is_staff=True` privilege escalation defense: accounts with `is_staff=True` but student/faculty roles are strictly denied write access.
   - `IsInstitutionalConfigPermission`: Restricts configuration viewing to administrators, masks sensitive values for standard admins, and requires superadmin privileges to read or modify sensitive configuration keys.
5. **REST API ViewSets & Routing (`apps.academics.views`, `apps.academics.urls`):**
   - CRUD ViewSets for all 10 models with standardized error handling and reference protection (`ProtectedError` / `RestrictedError` -> HTTP 409 Conflict).
   - Custom actions: `POST /sessions/{id}/set-current/` and `POST /paper-offerings/{id}/map-programmes/`.
   - Routing registered under `/api/v1/academics/`.
6. **Automated Test Suite (`backend/tests/test_academics.py`):**
   - 36 dedicated unit and integration tests covering model validations, database constraints, referential integrity, services, authorization, API workflows, and sensitive config masking.

---

## 2. Approved Schema & Model Conformance

The implemented models strictly conform to `docs/database-architecture.md`, Domain B:

| Table Name | Model Name | Primary Key | Key Constraints & Indexes | Foreign Key Deletion Behavior |
| :--- | :--- | :---: | :--- | :--- |
| `academics_college` | `College` | `BigAutoField` | `UNIQUE(code)` | — |
| `academics_academic_session` | `AcademicSession` | `BigAutoField` | `UNIQUE(college_id, name)` | `college_id`: `ON DELETE RESTRICT` |
| `academics_programme` | `Programme` | `BigAutoField` | `UNIQUE(college_id, code)` | `college_id`: `ON DELETE RESTRICT` |
| `academics_department` | `Department` | `BigAutoField` | `UNIQUE(college_id, code)` | `college_id`: `ON DELETE RESTRICT` |
| `academics_semester` | `Semester` | `BigAutoField` | `UNIQUE(programme_id, semester_number)` | `programme_id`: `ON DELETE RESTRICT` |
| `academics_subject_category` | `SubjectCategory` | `BigAutoField` | `UNIQUE(college_id, code)` | `college_id`: `ON DELETE RESTRICT` |
| `academics_subject` | `Subject` | `BigAutoField` | `UNIQUE(department_id, code)` | `department_id`: `ON DELETE RESTRICT` |
| `academics_paper_offering` | `PaperOffering` | `BigAutoField` | `UNIQUE(academic_session_id, paper_code)`, `INDEX idx_paper_session_sem`, `INDEX idx_paper_category` | `academic_session_id`, `semester_id`, `subject_id`, `subject_category_id`: `ON DELETE RESTRICT` |
| `academics_paper_programme_mapping` | `PaperProgrammeMapping` | `BigAutoField` | `UNIQUE(paper_offering_id, programme_id)` | `paper_offering_id`: `ON DELETE CASCADE`, `programme_id`: `ON DELETE RESTRICT` |
| `academics_institutional_config` | `InstitutionalConfig` | `BigAutoField` | `UNIQUE(college_id, config_key)` | `college_id`: `ON DELETE RESTRICT`, `updated_by_id`: `ON DELETE SET NULL` |

---

## 3. Configurable FYUGP Architecture

The FYUGP curriculum structure is fully database-driven:
- Subject categories (e.g. `MAJOR`, `MINOR`, `MDC`, `AEC`, `SEC`, `VAC`) are dynamic rows in `academics_subject_category` with configurable `min_credits` and `max_credits` bounds, rather than hardcoded enums.
- Multiple degree programmes within a college (e.g., 8-semester FYUGP Honours, 6-semester Diplomas, PG programmes) are supported with dynamic semester counts.
- Cross-programme paper sharing is modeled through `PaperOffering.is_common_paper` and `PaperProgrammeMapping`, allowing multi-disciplinary courses (such as Environmental Studies VAC) to be mapped to eligible programmes while enforcing college boundaries and duration coverage.
- Student enrollments and exam eligibility remain strictly separate and deferred to future chunks.

---

## 4. Academic Relationship Validation

Both model `clean()` methods and the service layer enforce:
1. **Academic Session Bounds:** `start_date` must strictly precede `end_date`.
2. **Programme Duration Bounds:** `duration_semesters >= 1`.
3. **Semester Bounds:** `1 <= semester_number <= programme.duration_semesters`.
4. **Category Credit Consistency:** `min_credits >= 0.0`, `max_credits >= min_credits`.
5. **Paper Offering Bounds:**
   - Non-negative credits (`credits >= 0.0`).
   - Category credit range: `subject_category.min_credits <= credits <= subject_category.max_credits`.
   - Non-negative marks: `max_marks_internal >= 0.00`, `max_marks_external >= 0.00`.
   - Pass mark bounds: `0.00 <= pass_marks_external <= max_marks_external`.
6. **Cross-College Relational Isolation:**
   - `PaperOffering`: `academic_session.college == semester.programme.college == subject.department.college == subject_category.college`.
   - `PaperProgrammeMapping`: `programme.college == paper_offering.academic_session.college`. Cross-college mapping is strictly blocked.
7. **Referential Integrity on Deletion:**
   - Attempting to delete a referenced entity (e.g., deleting a College with active Programmes, or deleting a Department with active Subjects) triggers `models.RestrictedError` / `models.ProtectedError`, which the API converts to HTTP 409 Conflict (`RESOURCE_CONFLICT`).

---

## 5. Institutional Configuration & Gatekeeping

The `InstitutionalConfig` model (Table 21) serves as the persistent configuration store for institutional activation gates and regulatory parameters:
- **Data Types:** Validates format and serializes values for `STRING`, `INTEGER`, `BOOLEAN`, and `JSON`.
- **Sensitive Value Masking:** When `is_sensitive=True`, read endpoints mask the value as `********` for general administrators; raw values are exposed only to institutional Superadministrators.
- **Unresolved Institutional Policies:** Parameters such as the official Gauhati University grading formula, examination PIN delivery method (`EXAM_PIN_DELIVERY_METHOD`), and evidence key retention period (`EXAM_EVIDENCE_KEY_RETENTION_PERIOD`) remain unconfigured in the baseline settings and require institutional administrative provisioning.

---

## 6. API Endpoints & RBAC Permissions Matrix

All endpoints are registered under `/api/v1/academics/`:

| Endpoint | Methods | Anonymous | Student | Faculty | Admin | SuperAdmin |
| :--- | :--- | :---: | :---: | :---: | :---: | :---: |
| `/api/v1/academics/colleges/` | `GET` | 401 | 200 | 200 | 200 | 200 |
| `/api/v1/academics/colleges/` | `POST` | 401 | 403 | 403 | 201 | 201 |
| `/api/v1/academics/sessions/` | `GET` | 401 | 200 | 200 | 200 | 200 |
| `/api/v1/academics/sessions/` | `POST` | 401 | 403 | 403 | 201 | 201 |
| `/api/v1/academics/sessions/{id}/set-current/` | `POST` | 401 | 403 | 403 | 200 | 200 |
| `/api/v1/academics/programmes/` | `GET` / `POST` | 401 / 401 | 200 / 403 | 200 / 403 | 200 / 201 | 200 / 201 |
| `/api/v1/academics/departments/` | `GET` / `POST` | 401 / 401 | 200 / 403 | 200 / 403 | 200 / 201 | 200 / 201 |
| `/api/v1/academics/semesters/` | `GET` / `POST` | 401 / 401 | 200 / 403 | 200 / 403 | 200 / 201 | 200 / 201 |
| `/api/v1/academics/subject-categories/` | `GET` / `POST` | 401 / 401 | 200 / 403 | 200 / 403 | 200 / 201 | 200 / 201 |
| `/api/v1/academics/subjects/` | `GET` / `POST` | 401 / 401 | 200 / 403 | 200 / 403 | 200 / 201 | 200 / 201 |
| `/api/v1/academics/paper-offerings/` | `GET` / `POST` | 401 / 401 | 200 / 403 | 200 / 403 | 200 / 201 | 200 / 201 |
| `/api/v1/academics/paper-offerings/{id}/map-programmes/` | `POST` | 401 | 403 | 403 | 200 | 200 |
| `/api/v1/academics/paper-mappings/` | `GET` / `POST` | 401 / 401 | 200 / 403 | 200 / 403 | 200 / 201 | 200 / 201 |
| `/api/v1/academics/institutional-configs/` | `GET` | 401 | 403 | 403 | 200 (Masked) | 200 (Raw) |
| `/api/v1/academics/institutional-configs/` | `POST` / `PATCH` | 401 | 403 | 403 | 201 / 403 (Sensitive) | 201 / 200 |

---

## 7. Automated Test Suite Execution & Verification

### Django Test Runner (`backend/manage.py test`)
```bash
$ .venv/bin/python backend/manage.py test tests --settings=config.settings.test
Found 242 test(s).
Creating test database for alias 'default'...
System check identified no issues (0 silenced).
......................................................................
......................................................................
......................................................................
...........................ssssssssss.................................
----------------------------------------------------------------------
Ran 242 tests in 3.907s

OK (skipped=10)
Destroying test database for alias 'default'...
```

### Pytest Runner (`pytest`)
```bash
$ .venv/bin/pytest backend/tests --ds=config.settings.test
======================= 232 passed, 10 skipped in 4.44s =======================
```

- **Total Tests Discovered:** 242 tests.
- **Passing Tests:** 232 passed (196 Chunk 04 authentication/foundation tests + 36 Chunk 05 academic tests).
- **Skipped Tests:** 10 cleanly skipped (`SafeLiveRedisIntegrationTests` awaiting operator-provided disposable Redis service).
- **Failures / Errors:** 0.

### Django Configuration & System Checks
- **Development System Check:** `python backend/manage.py check --settings=config.settings.development` -> `System check identified no issues (0 silenced).`
- **Migration Sync Check:** `python backend/manage.py makemigrations --check --dry-run --settings=config.settings.development` -> `No changes detected.`
- **Production Deployment Check:** `python backend/manage.py check --deploy --settings=config.settings.production` -> `System check identified no issues (0 silenced).`

---

## 8. Preserved Deferred Verification Requirements

In accordance with Chunk 04 owner approval, the following three requirements remain deferred and retained for future integration/deployment chunks:
1. **Live Redis Integration Testing (Target: Chunk 15 / Chunk 16):** Execution of the 10 live Redis integration tests against an operator-provided disposable Redis instance (`RUN_REDIS_INTEGRATION_TESTS=1`).
2. **Production MySQL Integration Verification (Target: Chunk 15 / Chunk 16):** Verification against a live MySQL 8.x InnoDB instance under concurrent transactional load.
3. **Production Reverse Proxy, Ingress Trust & TLS Verification (Target: Chunk 16):** Verification of production Nginx TLS termination, unconditional overwrite of `X-Forwarded-Proto`, and `X-Request-ID`.

---

## 9. Protected Architecture Document Integrity

All 4 architectural specification documents remain strictly unmodified (`git diff --exit-code`: 0):
- `design.md`
- `handover.txt`
- `docs/architecture.md`
- `docs/database-architecture.md`

---

## 10. File Inventory for Chunk 05

### Created Files:
1. `backend/apps/academics/migrations/0001_initial.py`
2. `backend/apps/academics/services.py`
3. `backend/apps/academics/permissions.py`
4. `backend/apps/academics/serializers.py`
5. `backend/apps/academics/views.py`
6. `backend/apps/academics/urls.py`
7. `backend/tests/test_academics.py`
8. `docs/audits/chunk-05-fyugp-academic-management-audit.md`

### Modified Files:
1. `backend/apps/academics/models.py`
2. `backend/config/urls.py`
3. `docs/audits/chunk-04-authentication-roles-audit.md`
4. `docs/development-progress.md`

---

## 11. Gate Status & Conclusion

- **Chunk 04 Status:** **APPROVED WITH WARNINGS — 2026-11-03**
- **Chunk 05 Status:** **IN REVIEW (Implementation Completed — Awaiting Independent Audit)**
- **Chunk 06 onward:** **GATED — NOT AUTHORIZED**
- **Implementation State:** All work on Chunk 05 is complete. No Chunk 06 code has been written.
- **Git State:** Changes remain uncommitted in the working directory for project owner and independent audit review.
