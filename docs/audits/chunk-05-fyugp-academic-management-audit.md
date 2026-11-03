# Chunk 05: FYUGP Academic Management Backend Audit Report (Round 3 Revisions)

**Project:** College Online Examination System (Gauhati University FYUGP Academic Context)  
**Author:** Antigravity Agent  
**Date:** 2026-11-03 (Round 3 Revisions Completed)  
**Stage:** Chunk 05 — FYUGP Academic Management  
**Status:** **IN REVIEW — PENDING INDEPENDENT AUDIT** (Round 3 corrections complete, backed by 108 dedicated academic tests, 314 total discovered tests [304 passing, 10 cleanly skipped live Redis tests], zero failures, clean Django system checks, zero schema drift, and strict database schema compliance; Chunk 06 onward remains strictly gated).

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
Found 288 test(s).
Creating test database for alias 'default'...
System check identified no issues (0 silenced).
......................................................................
......................................................................
......................................................................
......................................................................
...........................ssssssssss.................................
----------------------------------------------------------------------
Ran 288 tests in 4.169s

OK (skipped=10)
Destroying test database for alias 'default'...
```

### Pytest Runner (`pytest`)
```bash
$ .venv/bin/pytest backend/tests --ds=config.settings.test
======================= 278 passed, 10 skipped in 4.72s =======================
```

- **Total Tests Discovered:** 288 tests.
- **Passing Tests:** 278 passed (196 Chunk 04 authentication/foundation tests + 82 Chunk 05 academic tests).
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
- **Chunk 05 Status:** **IN REVIEW (Round 3 Revisions Completed — Awaiting Independent Audit)**
- **Chunk 06 onward:** **GATED — NOT AUTHORIZED**
- **Implementation State:** All Round 3 corrections on Chunk 05 are complete. No Chunk 06 code has been written.
- **Git State:** Changes remain uncommitted in the working directory for project owner and independent audit review.

---

## 12. ROUND 2 — ACADEMIC DATA INTEGRITY AND AUTHORIZATION CORRECTIONS

### 12.1 Independent Audit Findings Summary

| Finding | Severity | Description | Resolution Status |
| :--- | :---: | :--- | :--- |
| **High Finding A** | **HIGH** | Truthiness-based fallback (`attrs.get(x) or getattr(inst, x)`) caused zero-valued inputs (`0`, `0.0`) during PATCH to evaluate to falsy, silently ignoring submitted zero values and bypassing model bounds and relation constraints. | **RESOLVED** — Replaced truthiness fallbacks across all academic serializers with explicit membership checks (`attrs[x] if x in attrs else getattr(...)`). Enforced complete model state validation invoking `validate_paper_offering_relationships` and service validators before database mutation. |
| **High Finding B** | **HIGH** | Object-level permission checks did not run on `POST /institutional-configs/`, allowing ordinary administrators to create sensitive configurations (`is_sensitive: true`) and mutate sensitivity flags without superadministrator authority. | **RESOLVED** — Enforced sensitivity authorization across the entire object lifecycle in `IsInstitutionalConfigPermission` (both `has_permission` and `has_object_permission`), `InstitutionalConfigSerializer`, and `set_institutional_config` service. Ordinary admins cannot create sensitive configs, edit sensitive configs, change nonsensitive to sensitive, or downgrade sensitive to nonsensitive (HTTP 403). `is_staff=True` alone strictly denied. |
| **Medium Finding C** | **MEDIUM** | `is_current` was writable in `AcademicSessionSerializer`, allowing multiple sessions per college to be marked current through ordinary CRUD endpoints, bypassing the dedicated switching service. | **RESOLVED** — Made `is_current` strictly read-only on `AcademicSessionSerializer` and rejected any attempt to submit `is_current` in POST, PUT, or PATCH with HTTP 400. `set_current_academic_session` service enforces row locking on `College` (`select_for_update()`) to coordinate concurrent session switches and atomically deactivates previous sessions for that college. |
| **Medium Finding D** | **MEDIUM** | Direct CRUD on `PaperProgrammeMappingViewSet` did not enforce programme-duration coverage or `is_common_paper` consistency, producing behavioral divergence from the bulk mapping service. | **RESOLVED** — Centralized all paper-programme mapping invariants in `validate_paper_programme_mapping` (services.py). Unified validation across `PaperProgrammeMappingSerializer.validate()`, `clean()`, and `map_paper_to_programmes()`. Ensured `is_common_paper = True` is automatically maintained on creation/update. |
| **Medium Finding E** | **MEDIUM** | `replace = bool(request.data.get("replace", False))` in `map-programmes` action performed unsafe boolean coercion (e.g. `bool("false") is True`), and broad exception handling leaked raw exception messages. | **RESOLVED** — Implemented `MapProgrammesPayloadSerializer` with explicit `type(raw_replace) is bool` validation, rejecting strings (`"false"`, `"true"`) and integers (`0`, `1`) with HTTP 400. Enforced non-empty distinct `programme_ids`. Pre-validated all programmes inside `@transaction.atomic` before deleting existing mappings. Sanitized error handling returning standardized envelopes without raw exception/SQL traces. |

---

### 12.2 Exact Code Locations & Structural Changes

1. **`backend/apps/academics/serializers.py`:**
   - Lines 59–85: `AcademicSessionSerializer.validate()` rejects `is_current` submissions with HTTP 400; uses explicit membership check `if "start_date" in attrs` / `if "end_date" in attrs`.
   - Lines 124–150: `SemesterSerializer.validate()` uses explicit membership checks `if "semester_number" in attrs`; rejects 0 and out-of-bounds semester numbers.
   - Lines 170–190: `SubjectCategorySerializer.validate()` uses explicit membership checks `if "min_credits" in attrs` / `if "max_credits" in attrs`; accepts 0.0 for min_credits and rejects max_credits < min_credits.
   - Lines 230–285: `PaperOfferingSerializer.validate()` uses explicit membership checks for all numeric and relational attributes; invokes `validate_paper_offering_relationships` on complete resolved state, converting `ValidationError` to DRF validation errors.
   - Lines 300–345: `PaperProgrammeMappingSerializer.validate()` calls centralized `validate_paper_programme_mapping(paper, prog)`; `create()` and `update()` ensure `is_common_paper = True`.
   - Lines 370–425: `InstitutionalConfigSerializer.validate()` enforces superadministrator check whenever existing or requested `is_sensitive` is True, raising `PermissionDenied` (HTTP 403) for non-superadmins.
   - Lines 445–475: Added `MapProgrammesPayloadSerializer` enforcing `type(raw_replace) is bool` and duplicate-free positive integer list for `programme_ids`.
2. **`backend/apps/academics/services.py`:**
   - Lines 35–48: `set_current_academic_session` acquires exclusive `select_for_update()` row lock on `College`.
   - Lines 160–185: Added centralized `validate_paper_programme_mapping(paper_offering, programme)`.
   - Lines 188–225: `map_paper_to_programmes` pre-validates all programmes before modifying or deleting any mappings, within `transaction.atomic()`.
   - Lines 230–280: `set_institutional_config` checks superadmin permissions when `is_sensitive` is True.
3. **`backend/apps/academics/permissions.py`:**
   - Lines 40–90: `IsInstitutionalConfigPermission` enforces superadmin check in `has_permission` on POST when `is_sensitive: true` is requested, and in `has_object_permission` on PUT/PATCH/DELETE when existing or requested `is_sensitive` is True.
4. **`backend/apps/academics/views.py`:**
   - Lines 76–90: `AcademicSessionViewSet.set_current` catches `ValidationError` and returns standardized HTTP 400.
   - Lines 145–215: `PaperOfferingViewSet.map_programmes` validates payload using `MapProgrammesPayloadSerializer`, catches `ValidationError`, logs sanitized unexpected errors, and returns clean envelopes.
5. **`backend/apps/academics/models.py`:**
   - Lines 445–465: `PaperProgrammeMapping.clean()` verifies programme duration covers offering semester number.
6. **`backend/tests/test_academics.py`:**
   - Added 5 dedicated regression test suites (46 new tests), bringing total academic tests to 82.

---

### 12.3 Regression Test Coverage Summary

| Test Class | Tests Added | Scope Verified |
| :--- | :---: | :--- |
| `ZeroValuedPatchValidationRegressionTests` | 11 | Zero-valued PATCH updates on `max_marks_external`, `max_marks_internal`, `pass_marks_external`, `credits`, `min_credits`, `max_credits`; rejection of `max_marks_external=0` when `pass_marks_external>0`; acceptance of `0` when valid; omitted fields preservation; cross-college patch rejections. |
| `SensitiveInstitutionalConfigAuthorizationRegressionTests` | 13 | Ordinary admin cannot create sensitive configs (HTTP 403); superadmin can create sensitive configs (HTTP 201); admin cannot change nonsensitive to sensitive (HTTP 403); admin cannot downgrade sensitive to nonsensitive (HTTP 403); admin cannot edit or delete sensitive configs (HTTP 403); superadmin can edit sensitive configs (HTTP 200); student/faculty with `is_staff=True` denied (HTTP 403); sensitive values remain unexposed. |
| `AcademicSessionCurrentStateIntegrityRegressionTests` | 8 | Ordinary POST with `is_current=True` rejected (HTTP 400); ordinary PATCH with `is_current=True`/`False` rejected (HTTP 400); new sessions default to `is_current=False`; dedicated `set-current` action atomically switches sessions under row lock; only 1 session current per college; other colleges unaffected. |
| `PaperProgrammeMappingIntegrityRegressionTests` | 4 | Direct POST enforces same-college rule and duration coverage; short programmes (< semester) rejected (HTTP 400); direct PATCH enforces same rules; direct mapping creation sets `is_common_paper = True`. |
| `MapProgrammesReplaceBooleanAndExceptionSafetyRegressionTests` | 10 | `replace: false` retains existing mappings; `replace: true` replaces mappings; `"replace": "false"`, `"replace": "true"`, `0`, `1` rejected (HTTP 400) without deleting mappings; empty/duplicate/unknown/cross-college programme IDs rejected; transaction failure preserves existing mappings; sanitized error responses. |

- **Total New Regression Tests Added in Round 2:** 46 tests.
- **Total Academic Tests in Round 2:** 82 tests.
- **Total Test Suite in Round 2:** 288 tests discovered, 278 passed, 10 cleanly skipped (`SafeLiveRedisIntegrationTests`), zero failures.

---

## 13. ROUND 3 — SERVICE AUTHORIZATION, COMMON-PAPER CONSISTENCY AND EXCEPTION SANITIZATION

### 13.1 Independent Audit Findings Summary

| Finding | Severity | Description | Resolution Status |
| :--- | :---: | :--- | :--- |
| **High Finding A** | **HIGH** | `set_institutional_config()` accepted an omitted user or `enforce_authorization=False`, allowing programmatic callers to bypass RBAC and modify sensitive configurations without authorization checks. | **RESOLVED** — Made `user` a mandatory keyword-only argument (`user`). Completely removed `enforce_authorization`. Required authenticated, active administrator user for all configuration mutations. Enforced Superadministrator role whenever existing or proposed configuration is sensitive (`is_sensitive=True`). Blocked ordinary admin sensitivity promotions and demotions. Maintained database audit attribution (`updated_by = user`). |
| **Medium Finding B** | **MEDIUM** | Common-paper flags could become inconsistent with programme mappings: `is_common_paper` could be set to `False` while mappings existed, and concurrent direct mapping mutations lacked row locking discipline. | **RESOLVED** — Formalized and enforced invariant: *If a paper offering has one or more programme mappings, its `is_common_paper` value must be `True`.* Blocked setting `is_common_paper=False` when mappings exist across `PaperOffering.clean()`, `PaperOfferingSerializer.validate()`, and `PaperOfferingViewSet.perform_update()`. In `PaperProgrammeMappingSerializer.create()`, `update()`, and `map_paper_to_programmes()`, acquired exclusive row lock on `PaperOffering` (`select_for_update()`) and maintained `is_common_paper = True` atomically. |
| **Medium Finding C** | **MEDIUM** | Reference-protected deletion error envelopes in `BaseAcademicViewSet.destroy()` leaked internal table names and SQL details (`"details": str(exc)`), and broad exception handlers converted arbitrary exceptions into `str(exc)`. | **RESOLVED** — Completely removed `"details": str(exc)` from `BaseAcademicViewSet.destroy()` and replaced with sanitized warning log. Targeted exception catching specifically to `(DjangoValidationError, DRFValidationError)`. In action endpoints (`map_programmes`), structured logging (`logger.error("... [category=..., type=%s]", type(exc).__name__)`) logs diagnostic metadata while returning standardized generic envelopes without exposing database names, table names, or Python traces. Replaced raw JSON parsing exceptions in `InstitutionalConfig` model and serializer with clean validation messages (`"Value must be valid JSON."`). |

---

### 13.2 Exact Code Locations & Structural Changes

1. **`backend/apps/academics/services.py`:**
   - Lines 195–230: In `map_paper_to_programmes`, acquired exclusive `select_for_update()` lock on `PaperOffering` first to establish strict lock-order discipline before mutating or deleting mappings. Enforced `is_common_paper = True` under atomic transaction.
   - Lines 235–295: In `set_institutional_config`, transformed `user` into a mandatory keyword-only argument (`user`), eliminating default `None` and removing `enforce_authorization`. Added mandatory authorization checks rejecting unauthenticated, inactive, student, and faculty users (including those with `is_staff=True`). Required Superadministrator role whenever existing or proposed config is sensitive. Persisted `config.updated_by = user`.
2. **`backend/apps/academics/models.py`:**
   - Lines 410–420: In `PaperOffering.clean()`, added invariant validation: `if self.pk and not self.is_common_paper and self.programme_mappings.exists(): raise ValidationError({"is_common_paper": "Cannot set is_common_paper to False while programme mappings exist. Remove all programme mappings first."})`.
   - Lines 539–543: In `InstitutionalConfig.clean()`, replaced broad `except Exception as e:` with `except (json.JSONDecodeError, ValueError): raise ValidationError({"config_value": "Value must be valid JSON."})`.
3. **`backend/apps/academics/serializers.py`:**
   - Lines 320–332: In `PaperOfferingSerializer.validate()`, enforced invariant: rejected `is_common_paper=False` when `self.instance.programme_mappings.exists()`.
   - Lines 334–345: In `PaperOfferingSerializer.validate()`, replaced broad exception catch with `except DjangoValidationError as exc:`.
   - Lines 380–395: In `PaperProgrammeMappingSerializer.validate()`, replaced broad exception catch with `except DjangoValidationError as exc:`.
   - Lines 397–420: In `PaperProgrammeMappingSerializer.create()` and `update()`, wrapped mutations in `@transaction.atomic`, acquired exclusive `select_for_update()` row locks on `PaperOffering`, and guaranteed `is_common_paper = True`.
   - Lines 510–515: In `InstitutionalConfigSerializer.validate()`, replaced broad exception catch with `except (json.JSONDecodeError, ValueError):` returning sanitized `"Value must be valid JSON."`.
4. **`backend/apps/academics/views.py`:**
   - Lines 58–73: In `BaseAcademicViewSet.destroy()`, removed `"details": str(exc)`, returning clean HTTP 409 envelope `{"error": {"code": "RESOURCE_CONFLICT", "message": "Cannot delete record because it is referenced by existing academic data."}}` and logging structured warning without leaking table/constraint names to client.
   - Lines 88–102: In `AcademicSessionViewSet.set_current()`, caught `(DjangoValidationError, DRFValidationError)` specifically.
   - Lines 166–180: In `PaperOfferingViewSet`, implemented `perform_update()` wrapped in `@transaction.atomic`, acquiring row lock via `select_for_update()` on `PaperOffering` and rejecting `is_common_paper=False` when mappings exist.
   - Lines 200–228: In `PaperOfferingViewSet.map_programmes()`, caught `(DjangoValidationError, DRFValidationError)` specifically for HTTP 400; caught unexpected exceptions with structured error logging (`logger.error("... [offering_id=%s, error_type=%s]", offering.pk, type(exc).__name__)`) and returned generic HTTP 500 error envelope.
5. **`backend/tests/test_academics.py`:**
   - Added 3 dedicated regression test suites (26 new tests), expanding academic test coverage from 82 to 108 tests.

---

### 13.3 Round 3 Regression Test Coverage Summary

| Test Class | Tests Added | Scope Verified |
| :--- | :---: | :--- |
| `MandatoryInstitutionalConfigServiceAuthorizationRegressionTests` | 14 | Admin allowed to create/update non-sensitive config; admin denied sensitive config creation (PermissionDenied); superadmin allowed sensitive config creation; admin denied editing existing sensitive config; admin denied promoting non-sensitive to sensitive; admin denied demoting sensitive to non-sensitive; student denied; faculty denied; student with `is_staff=True` denied; faculty with `is_staff=True` denied; anonymous / `None` user denied; inactive user denied; omitted `user` raises `TypeError`; passing `enforce_authorization` raises `TypeError`; database audit user recorded. |
| `CommonPaperInvariantAndRowLockingRegressionTests` | 9 | Unmapped paper can have `is_common_paper=False`; service mapping automatically sets `is_common_paper=True`; direct mapping POST sets `is_common_paper=True`; direct mapping PATCH maintains `is_common_paper=True`; mapped paper cannot be set to `is_common_paper=False` via API PATCH (HTTP 400); mapped paper cannot be set to `is_common_paper=False` via model `clean()`; rejected update leaves database state intact; deleting all mappings allows setting `is_common_paper=False`; bulk mapping transactional rollback on failure preserves original state. |
| `SanitizedExceptionHandlingRegressionTests` | 3 | Restricted deletion returns HTTP 409 without `"details"`, table names, or SQL fragments; unexpected error during `map_programmes` logs structured metadata and returns generic HTTP 500 without leaking exception strings or tracebacks; invalid JSON configuration returns clean `"Value must be valid JSON."` without Python json module error traces. |

- **Total New Regression Tests Added in Round 3:** 26 tests.
- **Total Academic Tests:** 108 tests (all passed).
- **Total Full Test Suite:** 314 tests discovered, 304 passed, 10 cleanly skipped (`SafeLiveRedisIntegrationTests`), zero failures.
- **Clean System Checks:** Zero issues identified across development and production checks (`check --deploy`).
- **Protected Files Integrity:** All 4 protected architectural documents verified 100% byte-identical and unmodified.

