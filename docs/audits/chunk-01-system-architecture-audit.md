# Chunk 01: System Architecture Audit Report (Final Security & Consistency Revision 2)

**Project:** College Online Examination System (Gauhati University FYUGP Academic Context)  
**Author:** Antigravity Agent  
**Date:** 2026-11-02 (Final Revision 2)  
**Assigned Scope:** Chunk 01 — System Architecture  
**Status:** **PASS** (Architecture fully designed, refined with technically rigorous deadline timestamping, conflict-free offline cache lifecycle, verified security boundaries, and complete requirement traceability).

---

## 1. Scope Assigned vs. Completed

* **Assigned Scope:**
  - Design modular monolith architecture using React, Vite, Tailwind CSS, React Router, Django, DRF, MySQL, ReportLab, and SMTP.
  - Incorporate approved Chunk 00 requirements (Self-registration with approval, hybrid descriptive text + uploads, dual-tier PIN security, configurable roll-number generator, ReportLab PDFs).
  - Define frontend and backend modules, boundaries, and dependencies.
  - Incorporate all independent review corrections:
    1. **Technically Reliable Deadline Timestamping:**
       - Use high-precision Nginx arrival timestamp (`$msec`).
       - Explicitly configure Nginx to overwrite any client-supplied `X-Request-Arrival-Time` header (`proxy_set_header X-Request-Arrival-Time $msec;`).
       - Accept `HTTP_X_REQUEST_ARRIVAL_TIME` **only** from configured trusted reverse proxies (`TRUSTED_PROXIES`); reject/strip arbitrary client-forwarded headers.
       - Correct WSGI fallback description: a WSGI application cannot observe original socket-read time; use strict server-receipt cutoff captured at the earliest reliable server ingress point (outermost WSGI middleware `time.time()`).
       - Explicitly document that the WSGI fallback is conservative and may reject requests delayed by WSGI request buffering.
       - Enforce strict cutoff on request arrival ($T_{\text{arrival}} \le \text{official\_end\_time}$); zero trust in client timestamps or transport buffer answering extensions.
    2. **Conflict-Free Offline Cache Lifecycle:**
       - Resolve contradiction between preserving unsynchronized answers and purge-on-logout/expiry.
       - Unsynchronized answers are **never silently deleted** before explicit server acknowledgement (HTTP 200).
       - Logout does **not** purge unsynchronized answers.
       - Shared-device isolation maintained by partitioning cache keys (`exam_cache_{student_id}_{examination_id}_{attempt_id}`) and restricting access strictly to the currently authenticated student session.
       - Cache expiry marks data as `EXPIRED_STALE` and blocks editing; it does not silently delete unacknowledged answers.
       - Defined secure recovery process: auto-sync if re-authenticated before `end_time`; exportable read-only diagnostic bundle (`AUDIT_RECOVERY_BUNDLE`) if re-authenticated after `end_time`.
       - Answers rejected by the server for late arrival (HTTP 410) are marked `REJECTED_DEADLINE_EXCEEDED` locally for audit/appeal; they are never claimed as synchronized.
       - Synchronized answers are purged only after confirmed submission or auto-close acknowledgement.
       - Documented institutional shared-workstation purge policies.
    3. **Reconciled Examination Entry & PIN Validity Windows:** Reconciled 15-minute early-access buffer (Waiting Room only; question papers locked until `start_time`); strict late-entry cutoff (`entry_cutoff_time`); session resumption permitted only for active `IN_PROGRESS` attempts before `end_time`; permanent attempt locking post-submission/auto-close; PIN validity strictly expires at `end_time`.
    4. **Corrected XSS Security Claims:** Removed all claims of "total" or "complete" XSS immunity for HTTP-only cookies; accurately explained that `HttpOnly` mitigates raw cookie exfiltration but does not stop XSS-driven session riding; established multi-layer defense-in-depth (React JSX context-aware encoding, DOMPurify, strict Content Security Policy, backend input validation, dependency scanning).
    5. **Removal of Unapproved PIN Delivery Default:** Removed `ADMIT_CARD` as automatic default; established delivery method as an explicit mandatory configuration decision (`EXAM_PIN_DELIVERY_METHOD = 'UNCONFIGURED'`); system strictly prevents PIN issuance until approved.
  - Reconcile Mermaid diagrams, list exact locations, and distinguish manual review from automated validation.
* **Scope Completed:**
  - 100% of the assigned architectural tasks and all requested corrections completed.
  - Zero application code, migrations, or dependencies installed (strict adherence to gate rules).

---

## 2. Documentation Created / Modified

| File | Status | Description |
| :--- | :---: | :--- |
| [`docs/architecture.md`](../architecture.md) | **Updated** | Master architecture document containing system overview, module definitions, workflows, security boundaries, and all 11 Mermaid diagrams. Updated with high-precision Nginx `$msec` arrival timestamping, trusted proxy validation, corrected WSGI fallback, conflict-free offline cache lifecycle, recovery bundles, and institutional lab purge policy. |
| [`docs/development-progress.md`](../development-progress.md) | **Updated** | Progress tracking ledger recording chunk statuses, approvals, and decisions. Kept Chunk 01 pending user approval. |
| [`docs/audits/chunk-01-system-architecture-audit.md`](chunk-01-system-architecture-audit.md) | **Updated** | Comprehensive audit report reflecting the finalized, corrected architecture baseline. |
| [`design.md`](../../design.md) | **Preserved** | Unmodified; retains master requirements contract. |

---

## 3. Architecture Summary

The system is designed as a **Modular Monolith** engineered for high integrity, college-level deployment, and strict compliance with Gauhati University FYUGP academic structures:

1. **Frontend Architecture:**
   - React 18+ SPA built with Vite and Tailwind CSS.
   - Domain-separated feature modules (`auth`, `student`, `exam-interface`, `faculty`, `admin-academics`, `admin-students`, `admin-enrollment`, `admin-exams`, `admin-results`, `admin-audit`).
   - Role-based route guards (`PublicOnlyRoute`, `ProtectedRoute`, `RequireRole`, `LiveExamGuard`).
   - Centralized Axios client with automatic CSRF tokens (`X-CSRFToken`), HTTP-only session cookies, strict CSP, and scoped offline network resilience.
2. **Backend Architecture:**
   - Django 5.x + Django REST Framework on MySQL 8.0 (InnoDB).
   - Domain apps with clear boundaries: `accounts`, `academics`, `students`, `faculty`, `enrollments`, `examinations`, `eligibility`, `admit_cards`, `pins`, `questions`, `attempts`, `evaluations`, `results`, `notifications`, `audit`.
   - Celery + Redis task queue for asynchronous batch processing (PDF admit cards and SMTP delivery), abstracted through a unified `TaskQueueService` interface that supports eager execution during testing.
3. **Academic Hierarchy & Enrollment Integrity:**
   - Full FYUGP hierarchy: `College` $\rightarrow$ `AcademicSession` $\rightarrow$ `Programme` $\rightarrow$ `Department` $\rightarrow$ `Semester` $\rightarrow$ `Subject` $\rightarrow$ `PaperOffering`.
   - `SubjectCategory` (Major, Minor, MDC, AEC, SEC, VAC) modeled dynamically in DB rather than hardcoded enums.
   - Cross-programme paper support for shared NEP courses (e.g., Environmental Studies VAC).
   - Explicit registration: Eligibility requires an approved `StudentSubjectEnrollment` record.
4. **Examination Lifecycle & Dual-Tier Access:**
   - Account login establishes student identity; live exam entry requires entering a separate, cryptographically hashed Examination PIN.
   - Early access allows entering the Waiting Room only; new attempts are permitted only within `[start_time, entry_cutoff_time]`; active attempts may resume until `end_time`; attempts are permanently locked after submit or auto-close.
   - Server-authoritative timer; high-precision trusted reverse-proxy arrival timestamping ($T_{\text{arrival}} \le \text{official\_end\_time}$); zero trust in client timestamps; monotonic sequence versioning; idempotent submission; ReportLab PDF generation; private storage for admit cards and student descriptive uploads.

---

## 4. Diagram Validation & Reconciliation

### 4.1 Diagram Count Reconciliation

The assignment requested workflow visualizations across 9 architectural domains. In [`docs/architecture.md`](../architecture.md), these were decomposed into **11 distinct Mermaid diagrams** to provide granular separation (e.g., separating module communication from domain dependencies, separating self-registration from live PIN verification, and detailing reverse-proxy timestamping in live submissions).

The table below enumerates all 11 Mermaid diagrams present in [`docs/architecture.md`](../architecture.md):

| # | Diagram Name | Location in `architecture.md` | Diagram Type |
| :-: | :--- | :--- | :--- |
| 1 | High-Level System Architecture | Section 3.1 (Line 54) | `flowchart TD` |
| 2 | Frontend and Backend Module Communication | Section 5.2 (Line 182) | `flowchart LR` |
| 3 | Backend Module Dependency Graph | Section 5.3 (Line 215) | `flowchart TD` |
| 4 | Student Self-Registration & Approval Workflow | Section 6.2 (Line 292) | `sequenceDiagram` |
| 5 | Authentication and Examination PIN Verification Flow | Section 6.3 (Line 322) | `sequenceDiagram` |
| 6 | Student Subject Enrollment & Historical Preservation | Section 7.2 (Line 379) | `flowchart TD` |
| 7 | Complete Examination Lifecycle | Section 8.1 (Line 402) | `flowchart TD` |
| 8 | Descriptive Answer File-Upload Pipeline | Section 11.2 (Line 570) | `sequenceDiagram` |
| 9 | Background Admit-Card Email Delivery | Section 12.2 (Line 636) | `flowchart LR` |
| 10 | Examination Attempt and Submission Sequence | Section 13.5 (Line 749) | `sequenceDiagram` |
| 11 | Evaluation & Results Publication Architecture | Section 14 (Line 796) | `flowchart TD` |

### 4.2 Validation Method

* **Manual Review (Performed):** Complete manual structural and syntactic inspection was conducted for all 11 diagrams against official Mermaid grammar specifications. All node labels containing special characters or punctuation were verified to be enclosed in standard double quotes (e.g., `id["Label (Info)"]`), diagram direction directives (`TD`, `LR`) were confirmed, and sequence diagram actor lifelines and alternative block syntax (`alt`, `opt`, `loop`) were verified for structural consistency with the written text.
* **Automated CLI Validation (Not Executed):** No automated CLI parser (such as `@mermaid-js/mermaid-cli` / `mmdc`) was executed, as no Mermaid CLI package is installed in the local environment and package installation is prohibited in Chunk 01.

---

## 5. Requirement-to-Architecture Traceability

| Approved Requirement | Architectural Solution | Section in `architecture.md` |
| :--- | :--- | :--- |
| **Student self-registration with approval** | User created with `PENDING_VERIFICATION`; email token verification transitions to `PENDING_APPROVAL`; Admin inspects college credentials and activates account. | Section 6.2 |
| **Hybrid descriptive answers (text + files)** | Dual inputs in exam UI: Rich text editor + multi-file upload. Provisional defaults (max 3 files, 5 MB/file, PDF/JPEG/PNG) kept fully configurable. Server validates MIME/magic bytes, scans for malware, generates UUID filenames, and saves to private storage. | Section 11 |
| **Dual-tier examination access (PIN)** | Standard login sets HTTP-only session. Live exam requires 6-character CSPRNG PIN; backend verifies against PBKDF2/Argon2 salted hash. Early access allows Waiting Room entry; new attempts permitted only up to `entry_cutoff_time`; active attempts resume until `end_time`. Lockout proposed subject to review; secure admin reissue; zero disclosure in logs/APIs. | Section 6.3 & 9 |
| **PIN delivery configuration gate** | Delivery method is explicitly `UNCONFIGURED` by default. System strictly prevents PIN generation until college administrator selects and approves delivery policy (`ADMIT_CARD` vs. `JUST_IN_TIME`). | Section 9.6 |
| **Configurable roll-number format** | `RollNumberScheme` model with customizable template pattern. Documented format is strictly illustrative; supports atomic `SELECT ... FOR UPDATE` allocation, admin correction workflows, and historical locking. | Section 10 |
| **ReportLab PDF admit cards** | Pure-Python `reportlab.platypus` document builder generating pixel-perfect PDFs with candidate info, schedule table, instructions, and barcode/QR without OS cairo/pango dependencies. | Section 12 |
| **Technically reliable deadline enforcement** | High-precision Nginx `$msec` timestamping via unconditionally overwritten `X-Request-Arrival-Time` header. Accepted strictly from configured `TRUSTED_PROXIES`. WSGI fallback captured at earliest middleware ingress (`time.time()`); conservative nature documented. Writes accepted only when $T_{\text{arrival}} \le \text{end\_time}$; requests arriving after `end_time` strictly rejected for write. | Section 13.1 |
| **Conflict-free offline cache lifecycle** | Scoped storage keys (`exam_cache_*`). Zero credential caching. Unsynchronized answers are never silently deleted before server acknowledgement. Logout does not purge unsynchronized data; shared-device isolation prevents access by subsequent users. Expiry marks cache stale without deletion. Recovery bundle (`AUDIT_RECOVERY_BUNDLE`) for appeal. Late rejected answers marked `REJECTED_DEADLINE_EXCEEDED` and not claimed as synchronized. Synchronized data cleaned up on confirmed submit/auto-close. | Section 13.3 |
| **XSS defense-in-depth** | Accurate acknowledgement of `HttpOnly` scope (stops raw cookie theft, but does not stop XSS session riding). Defense-in-depth enforced via React JSX default escaping, DOMPurify, strict Content Security Policy (`script-src 'self'`), backend input sanitization, and dependency scanning. | Section 15.2 & 17 |
| **Explicit FYUGP eligibility** | Eligibility service filters active approved `StudentSubjectEnrollment` for targeted `PaperOffering`. Admin reviews, applies audited overrides, and locks immutable snapshot. | Section 7 & 8 |
| **Role-based access & private files** | Django permission classes (`IsAdminRole`, `IsFacultyRole`, `IsApprovedStudent`). Private storage outside webroot with authenticated streaming downloads. | Section 4.2 & 11.4 |

---

## 6. Security & Privacy Review

1. **Authentication & XSS Defense-in-Depth:**
   - Cookies configured with `HttpOnly`, `SameSite=Lax` (or `Strict`), and `Secure=True`.
   - **Accurate Scope:** The architecture clearly documents that `HttpOnly` mitigates raw cookie theft but does not prevent XSS from issuing authenticated requests on behalf of the user.
   - Comprehensive multi-layer protection: React JSX output escaping, strict CSP blocking inline scripts and unauthorized hosts, backend input validation, dependency security auditing, and CSRF tokens on all state-changing endpoints.
2. **Examination PIN Security & Lifecycle:**
   - Generated using cryptographically secure random entropy (`secrets.choice` / `/dev/urandom`).
   - Salted hashing (PBKDF2-SHA256 / Argon2) ensures zero-knowledge database security.
   - Verification creates an ephemeral signed session token rather than consuming/destroying the PIN, ensuring resilience against mid-exam disconnects or browser crashes while preventing post-submission reuse.
   - Reconciled entry windows prevent new attempt creation after `entry_cutoff_time` and prevent PIN use after `end_time`.
   - Rate limiting (5 failed attempts before 15-minute lockout) is documented as a proposed policy subject to college sign-off.
   - Administrative reissue is fully auditable with mandatory justification.
   - Plaintext PIN is strictly excluded from `AuditLog`, application logs, and API responses.
   - Delivery method is unconfigured by default, requiring explicit administrator approval before PIN issuance.
3. **File Upload Security & Malware Defense:**
   - Multi-layer defense: Configurable extension whitelist, MIME-type validation, and binary magic-byte inspection (detecting disguised PHP, shell scripts, or executable binaries).
   - Pluggable malware scanning interface (ClamAV) to scan incoming streams before committing to disk.
   - Filename sanitization: Client filenames are completely replaced with random UUIDs (`uuid4()`).
   - Private media storage: Placed completely outside the public web root; accessed strictly via authenticated controller endpoints with role and ownership checks.
4. **Offline Cache Privacy & Shared-Device Safety:**
   - Cache keys strictly scoped to `(student_id, examination_id, attempt_id)`.
   - Credentials (passwords, PINs, tokens) strictly prohibited from browser caches.
   - Conflict-free preservation: unsynchronized answers are never silently purged before server acknowledgement.
   - Shared-device safety: client state restrictions prevent subsequent candidates logging into the same computer from accessing or viewing another student's cache.
   - Confirmed synchronized answers are purged immediately upon submission/auto-close.
5. **Audit Trail & Secret Hygiene:**
   - Centralized `AuditLog` records actor, IP address, action, target entity, and before/after state diffs.
   - Passwords, plain PINs, and auth tokens are explicitly scrubbed from audit payloads and application logs.

---

## 7. Reliability, Scalability & Concurrency Review

1. **Autosave Race Conditions:** Monotonic sequence versioning (`WHERE sequence < incoming_sequence`) eliminates race conditions caused by delayed packets over mobile networks.
2. **Concurrent Roll-Number Allocation:** Database row locks (`SELECT ... FOR UPDATE`) guarantee zero duplicate sequence numbers even during high-concurrency batch allocations.
3. **Strict Server-Authoritative Deadline Integrity:**
   - Zero trust in client timestamps.
   - Nginx high-precision `$msec` arrival timestamping unconditionally injected.
   - Requests arriving before `end_time` at the trusted reverse proxy are accepted even if internal processing finishes slightly after `end_time`.
   - Requests first received after `end_time` are rejected immediately with HTTP 410, and attempt is transitioned to `AUTO_CLOSED_DEADLINE`.
   - Offline answers entered after `end_time` cannot be synchronized upon reconnection; marked `REJECTED_DEADLINE_EXCEEDED` locally for diagnostic appeal, while attempt is finalized using only pre-deadline saved state.
4. **Peak Examination Traffic:**
   - Read-heavy live exam questions and configuration can be cached in Redis.
   - Static assets served directly by Nginx.
   - Autosave requests are lightweight (`PATCH` with minimal payload), minimizing database I/O.
5. **Idempotent Exam Submission:** Atomic database locking on submission prevents double-submission or duplicate evaluation triggers if students double-click the submit button.

---

## 8. Risks, Assumptions and Limitations

| Area | Risk / Limitation | Mitigation |
| :--- | :--- | :--- |
| **PIN Delivery Method** | Advance PIN printing on admit cards risks early disclosure; just-in-time delivery risks network/SMS bottlenecks on exam day. | System enforces mandatory configuration (`EXAM_PIN_DELIVERY_METHOD`); PIN generation blocked until college confirms choice. |
| **Network Loss Across Deadline** | A student disconnected before deadline cannot upload offline answers after `end_time`. | Documented as strict server-authoritative integrity rule; attempt is auto-closed using last synchronized answers; unacknowledged answers preserved in `AUDIT_RECOVERY_BUNDLE` for grievance appeal. |
| **Shared Lab Computer Privacy** | Students sharing computers in college labs or cyber cafes could expose answers if browser cache persists. | Scoped cache keys per student/attempt; zero credential storage; client-side state access controls; synchronized data purged on confirmed submission; institutional workstation wipe policies documented. |
| **WSGI Fallback Latency** | Direct WSGI execution without Nginx uses conservative middleware ingress timestamping that may reject requests delayed by WSGI request buffering. | Documented that Nginx reverse proxy with `$msec` is mandatory for production deployments; WSGI fallback is strictly for local dev/testing. |
| **Descriptive Upload Bandwidth** | Students on poor 4G uplinks uploading multiple photos may experience timeouts. | Client-side Canvas downscaling in React UI; provisional 5 MB default is configurable; multipart streaming; background retry. |

---

## 9. Unresolved Decisions (Flagged for Institutional / Chunk 02 Confirmation)

The following items are documented as proposed baselines and flagged for formal institutional or data modeling confirmation:

1. **Examination PIN Delivery Policy:** Mandatory college decision selecting between PIN printing on admit cards or just-in-time delivery via SMS/portal/invigilators. PIN issuance blocked until configured.
2. **Late-Entry Cutoff Duration:** Institutional confirmation of the permitted entry window (`entry_cutoff_time`, e.g., 15 or 30 minutes past `start_time`), after which new attempts cannot be initialized.
3. **Shared Lab Workstation Cache Purge Policy:** Institutional confirmation of administrative workstation sanitization schedules (e.g. nightly deep-freeze/reboot scripts wiping persistent browser local storage in shared college computer labs).
4. **Official Gauhati University Roll-Number Pattern:** Populating the configurable `RollNumberScheme` template once the official university convention is provided.
5. **Descriptive Upload Quotas:** Confirming provisional defaults (max 3 files, 5 MB/file, PDF/JPEG/PNG) or adopting custom institutional thresholds.
6. **Answer Script Retention Schedule:** Confirming statutory retention period (recommended: 6 to 12 months) before automated archival or purging.
7. **Grading & GPA Scale:** Confirming official Gauhati University 10-point letter grade conversion tables and SGPA/CGPA formulas.

---

## 10. Final Audit Status

* **Status:** **PASS**
* **Gate Sign-off:** All Chunk 01 requirements and independent review corrections are fully addressed. All 11 Mermaid diagrams are documented, manually verified, and reconciled. Architectural boundaries, security protocols, technically reliable deadline enforcement, and conflict-free offline cache lifecycle rules are finalized in [`docs/architecture.md`](../architecture.md).
* **Next Permitted Chunk:** **CHUNK 02 — DATABASE ARCHITECTURE** (pending explicit user approval).

> **STOP:** All work for Chunk 01 is complete. No application code, packages, or database schemas have been generated. Awaiting explicit user approval before proceeding to Chunk 02.
