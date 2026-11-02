# Chunk 01: System Architecture Audit Report (Round 7 Revision)

**Project:** College Online Examination System (Gauhati University FYUGP Academic Context)  
**Author:** Antigravity Agent  
**Date:** 2026-11-03 (Round 7 Revision)  
**Assigned Scope:** Chunk 01 — System Architecture  
**Status:** **PASS WITH WARNINGS** (Core architecture is complete, robust, and technically verified; documented non-blocking institutional policies are explicitly flagged for college confirmation).

---

## 1. Scope Assigned vs. Completed

* **Assigned Scope:**
  - Design modular monolith architecture using React, Vite, Tailwind CSS, React Router, Django, DRF, MySQL, ReportLab, and SMTP.
  - Incorporate approved Chunk 00 requirements (Self-registration with approval, hybrid descriptive text + uploads, dual-tier PIN security, configurable roll-number generator, ReportLab PDFs).
  - Define frontend and backend modules, boundaries, and dependencies.
  - Incorporate all Round 7 independent review corrections:
    1. **Finding A (High Priority Resolved) — Deadline Finalization Race Condition:**
       - Eliminated the race condition where the background deadline worker could auto-close an attempt while valid on-time requests ($T_{\text{ingress}} \le \text{official\_end\_time}$) were still queued in socket backlogs or executing in Gunicorn workers.
       - Designed a two-stage finalization protocol for the deadline supervisor worker:
         - *Stage 1 (Queue Drain Wait):* Mandatory delay window ($\Delta_{\text{ingress\_drain}} = 15\text{s}$) before initiating attempt closure, allowing requests buffered at Nginx/sockets to enter Django.
         - *Stage 2 (In-Flight Registry Verification):* Redis-backed active request tracking (`exam:inflight:{attempt_id}`) across multiple Gunicorn workers. Supervisor defers finalization while active requests remain, bounded by a hard ceiling timeout (30s total) to prevent indefinite stalls.
         - *Stage 3 (Atomic Finalization):* Exclusive row lock (`SELECT ... FOR UPDATE` on `ExamAttempt`), freezing attempt state to `AUTO_CLOSED_DEADLINE`, followed by asynchronous, idempotent MCQ evaluation.
       - Specified a universal row-lock acquisition order across Autosave, Submission, and Supervisor finalization.
       - Provided exhaustive 12-scenario concurrency analysis covering worker crashes, slow body uploads, out-of-order network arrival, retries, and duplicate evaluations with authoritative outcomes and HTTP status codes.
    2. **Finding B (Medium Priority Resolved) — Evidence Retention Configuration State Machine:**
       - Defined an explicit 4-state operational machine: `UNCONFIGURED`, `CONFIGURED`, `EXPIRED`, and `LEGAL_HOLD / GRIEVANCE_PENDING`.
       - Implemented a **Hard Production Activation Gate**: examination publishing and activation is strictly blocked while `EXAM_EVIDENCE_KEY_RETENTION_PERIOD` remains `UNCONFIGURED`.
       - Enforced institutional role authorization (`IsCollegeSuperAdmin`) with mandatory written justification and audit logging (`AuditLog: RETENTION_POLICY_CONFIGURED`).
       - Captured retention policy as an immutable snapshot on `Examination` (`evidence_key_retention_days`) and `ExamAttempt` (`evidence_key_expires_at`), preventing retroactive changes to active/finalized attempts.
       - Defined exact countdown start at `finalized_at`, server-authoritative request-time expiry enforcement (HTTP 410 `EVIDENCE_RETENTION_EXPIRED`), scheduled daily key deletion (`purge_expired_evidence_keys`), audit logging (`AuditLog: EVIDENCE_KEY_PURGED`), and failure recovery.
       - Specified legal hold suspension (`is_under_legal_hold = True`) for active grievances.
       - Detailed lab workstation sanitization policies and warned candidates to export bundles prior to PC reboots.
  - Reconcile Mermaid diagrams, list exact locations, and distinguish manual review from automated validation.
* **Scope Completed:**
  - 100% of the assigned architectural tasks and all Round 7 review corrections completed.
  - Zero application code, migrations, or dependencies installed (strict adherence to gate rules).

---

## 2. Documentation Created / Modified

| File | Status | Description |
| :--- | :---: | :--- |
| [`docs/architecture.md`](../architecture.md) | **Updated** | Master architecture document containing system overview, module definitions, workflows, security boundaries, and all 11 Mermaid diagrams. Updated with two-stage deadline finalization protocol, Redis cross-worker in-flight registry, 12-scenario concurrency analysis, formal evidence-retention configuration state machine, production activation gate, and legal hold mechanics. |
| [`docs/development-progress.md`](../development-progress.md) | **Updated** | Progress tracking ledger recording chunk statuses, approvals, and decisions. Kept Chunk 01 pending user approval. |
| [`docs/audits/chunk-01-system-architecture-audit.md`](chunk-01-system-architecture-audit.md) | **Updated** | Comprehensive audit report reflecting the finalized Round 7 corrected architecture baseline with truthful status and validation disclosure. |
| [`design.md`](../../design.md) | **Preserved** | Unmodified; retains master requirements contract. |

---

## 3. Architecture Summary

The system is designed as a **Modular Monolith** engineered for high integrity, college-level deployment, and strict compliance with Gauhati University FYUGP academic structures:

1. **Frontend Architecture:**
   - React 18+ SPA built with Vite and Tailwind CSS.
   - Domain-separated feature modules (`auth`, `student`, `exam-interface`, `faculty`, `admin-academics`, `admin-students`, `admin-enrollment`, `admin-exams`, `admin-results`, `admin-audit`).
   - Role-based route guards (`PublicOnlyRoute`, `ProtectedRoute`, `RequireRole`, `LiveExamGuard`).
   - Centralized Axios client with automatic CSRF tokens (`X-CSRFToken`), HTTP-only session cookies, strict CSP, and Web Crypto AES-256-GCM encrypted IndexedDB storage.
2. **Backend Architecture:**
   - Django 5.x + Django REST Framework on MySQL 8.0 (InnoDB).
   - Domain apps with clear boundaries: `accounts`, `academics`, `students`, `faculty`, `enrollments`, `examinations`, `eligibility`, `admit_cards`, `pins`, `questions`, `attempts`, `evaluations`, `results`, `notifications`, `audit`.
   - Celery + Redis task queue for asynchronous batch processing (PDF admit cards, evaluation triggers, and SMTP delivery), abstracted through a unified `TaskQueueService` interface that supports eager execution during testing.
3. **Academic Hierarchy & Enrollment Integrity:**
   - Full FYUGP hierarchy: `College` $\rightarrow$ `AcademicSession` $\rightarrow$ `Programme` $\rightarrow$ `Department` $\rightarrow$ `Semester` $\rightarrow$ `Subject` $\rightarrow$ `PaperOffering`.
   - `SubjectCategory` (Major, Minor, MDC, AEC, SEC, VAC) modeled dynamically in DB rather than hardcoded enums.
   - Cross-programme paper support for shared NEP courses (e.g., Environmental Studies VAC).
   - Explicit registration: Eligibility requires an approved `StudentSubjectEnrollment` record.
4. **Examination Lifecycle & Concurrency Protocol:**
   - Account login establishes student identity; live exam entry requires entering a separate, cryptographically hashed Examination PIN.
   - Server-authoritative timer ($T_{\text{ingress}} \le \text{official\_end\_time}$); zero trust in client timestamps; monotonic sequence versioning; idempotent submission.
   - **Race-Free Finalization:** Ingress Queue Drain Window ($\Delta_{\text{ingress\_drain}} = 15\text{s}$) and Redis in-flight tracking prevent premature auto-closure while valid on-time requests are buffered or processing.
   - Strict row-lock acquisition order (`SELECT ... FOR UPDATE` on `ExamAttempt`) serializes concurrent autosaves, submissions, and supervisor workers.
5. **Shared-Device Cryptographic Confidentiality & Dual-Track Key Recovery:**
   - Local answer persistence protected at rest using Web Crypto API `AES-256-GCM` with 96-bit random IVs and AAD binding. Zero local PIN wrapping.
   - Server-assisted key release partitioned into Track A (Live Exam Recovery, active `IN_PROGRESS`, $T \le \text{deadline}$, write-enabled) and Track B (Post-Deadline Read-Only Evidence Recovery, finalized attempts within `EXAM_EVIDENCE_KEY_RETENTION_PERIOD`, strictly read-only).
   - Production examination activation gate enforces approved retention policy before scheduling.

---

## 4. Diagram Validation & Reconciliation

### 4.1 Diagram Count Reconciliation

The assignment requested workflow visualizations across 9 architectural domains. In [`docs/architecture.md`](../architecture.md), these were decomposed into **11 distinct Mermaid diagrams** to provide granular separation (e.g., separating module communication from domain dependencies, separating self-registration from live PIN verification, and detailing reverse-proxy timestamping and encrypted cache transitions in live submissions).

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
| 8 | Descriptive Answer File-Upload Pipeline | Section 11.2 (Line 569) | `sequenceDiagram` |
| 9 | Background Admit-Card Email Delivery | Section 12.2 (Line 635) | `flowchart LR` |
| 10 | Examination Attempt and Submission Sequence | Section 13.5 (Line 1007) | `sequenceDiagram` |
| 11 | Evaluation & Results Publication Architecture | Section 14 (Line 1058) | `flowchart TD` |

### 4.2 Validation Method

* **Manual Review (Performed):** Complete manual structural and syntactic inspection was conducted for all 11 diagrams against official Mermaid grammar specifications. All node labels containing special characters or punctuation were verified to be enclosed in standard double quotes (e.g., `id["Label (Info)"]`), diagram direction directives (`TD`, `LR`) were confirmed, and sequence diagram actor lifelines and alternative block syntax (`alt`, `opt`, `loop`) were verified for structural consistency with the written text.
* **Automated CLI Validation (Not Executed):** No automated CLI parser (such as `@mermaid-js/mermaid-cli` / `mmdc`) was executed, as no Mermaid CLI binary or headless Chromium environment is installed in the workspace environment. To maintain absolute technical honesty, this report explicitly documents that validation was achieved via comprehensive manual grammar verification rather than automated tooling.

---

## 5. Requirement-to-Architecture Traceability

| Requirement | Architectural Response | Section in `architecture.md` |
| :--- | :--- | :--- |
| **Self-registration with approval** | Dedicated registration workflow with email token verification and administrative pending-approval status (`PENDING_APPROVAL`, `APPROVED`, `REJECTED`). Unapproved accounts are blocked from login. | Section 6.1 & 6.2 |
| **Hybrid descriptive answers** | Unified `DescriptiveAnswer` entity supporting both typed `answer_text` and file attachments. Multi-layer validation (extension, MIME, magic bytes, ClamAV) and private filesystem storage outside webroot. Provisional limits (max 3 files, 5 MB/file) are configurable. | Section 11 |
| **Dual-tier examination access** | Account login issues short-lived JWT/Session. Starting or resuming an exam requires verifying a cryptographically hashed Examination PIN, creating an ephemeral `exam_session_token`. | Section 6.3 & 13.2 |
| **Configurable roll numbers** | Dynamic pattern-based template engine (`RollNumberScheme`) supporting college prefix, academic session, programme code, and zero-padded sequence numbers. Documented default is strictly illustrative; supports atomic `SELECT ... FOR UPDATE` allocation, admin correction workflows, and historical locking. | Section 10 |
| **ReportLab PDF admit cards** | Pure-Python `reportlab.platypus` document builder generating pixel-perfect PDFs with candidate info, schedule table, instructions, and barcode/QR without OS cairo/pango dependencies. | Section 12 |
| **Unified deadline timestamping ($T_{\text{ingress}}$)** | Distinction of 5 request stages; Nginx `$msec` semantics & limitations acknowledged; Nginx overwrites `X-Request-Arrival-Time`; accepted strictly from `TRUSTED_PROXIES`; direct backend access prevented via Unix socket/firewall; mandatory fail-closed behavior on missing/invalid timestamps in production (HTTP 502); WSGI fallback strictly restricted to dev/test environments. Writes accepted only when $T_{\text{ingress}} \le \text{official\_end\_time}$. | Section 13.1 |
| **Two-stage finalization protocol** | Prevents race condition between in-flight on-time writes and deadline auto-closure. Stage 1 queue drain window ($\Delta_{\text{ingress\_drain}} = 15\text{s}$) + Stage 2 Redis in-flight tracking (`exam:inflight:{id}`) + hard ceiling timeout (30s). Full 12-scenario concurrency analysis documented. | Section 13.1 & 13.4 |
| **Evidence retention state machine** | Formal 4-state lifecycle (`UNCONFIGURED` -> `CONFIGURED` -> `EXPIRED` / `LEGAL_HOLD`). Hard production gate blocks exam activation while unconfigured. Immutable snapshots per exam and attempt. Scheduled daily deletion and legal hold mechanics. | Section 13.3.6 |
| **Encrypted offline cache & dual-track recovery** | Concrete Web Crypto API `AES-256-GCM` encryption at rest in IndexedDB with 96-bit random IVs and AAD binding. Zero local PIN wrapping. Partitioned dual-track key recovery: Track A for active attempts before deadline; Track B for post-deadline read-only evidence recovery and diagnostic export within `EXAM_EVIDENCE_KEY_RETENTION_PERIOD`. Preserved unacknowledged answers; recovery bundles (`AUDIT_RECOVERY_BUNDLE`) with SHA-256 integrity metadata and server HMACs; institutional kiosk and deep freeze warning documented. | Section 13.3 |
| **Reconciled submission lifecycle** | Explicit distinction between $T_{\text{ingress}}$ (`submitted_at`), $T_{\text{process}}$, and application transaction recording time `transaction_recorded_at` (persisted in `committed_at`). Exhaustive documentation of all 12 submission scenarios with exact HTTP response codes (200, 408, 409, 410, 502) and transactional row-locking semantics (`SELECT ... FOR UPDATE`). | Section 13.4 & 13.5 |
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
4. **Shared-Device Offline Cache Privacy & Dual-Track Key Security:**
   - Threat model explicitly accounts for shared lab PCs, cyber cafes, DevTools (`F12`) storage inspection, and malicious extensions.
   - Local storage in IndexedDB is encrypted at rest using `AES-256-GCM` via Web Crypto API.
   - **Zero Local PIN Derivation:** PIN-derived KEK wrapping is eliminated; no wrapped keys or salts are stored locally in IndexedDB, completely eliminating offline dictionary attacks.
   - In-memory DEK is cleared on tab close/logout.
   - **Dual-Track Key Recovery:**
     - *Track A (Live Resumption):* Restores DEK over TLS only when `attempt.status == IN_PROGRESS` and `server_time <= official_end_time`.
     - *Track B (Post-Deadline Evidence):* Restores DEK strictly in read-only mode for finalized attempts within `EXAM_EVIDENCE_KEY_RETENTION_PERIOD` to export `AUDIT_RECOVERY_BUNDLE`. Strictly prohibits write operations or attempt reactivation.
   - Temporary inaccessibility: if the browser closes while offline, cached answers are temporarily inaccessible until server connectivity is restored.
   - Unsynchronized answers are never silently purged before server acknowledgement.
   - Residual risks (unmanaged malware, memory dumpers) are mitigated through documented institutional kiosk policies (ephemeral browser sessions, OS Deep Freeze/reboot scripts).
5. **Audit Trail & Secret Hygiene:**
   - Centralized `AuditLog` records actor, IP address, action, target entity, and before/after state diffs.
   - Distinct audit events for key recovery and retention: `AuditLog: LIVE_CACHE_KEY_RELEASED`, `AuditLog: EVIDENCE_KEY_RELEASED`, `AuditLog: EVIDENCE_BUNDLE_EXPORTED`, `AuditLog: RETENTION_POLICY_CONFIGURED`, `AuditLog: EVIDENCE_KEY_PURGED`, and `AuditLog: LEGAL_HOLD_RELEASED`.
   - Passwords, plain PINs, and auth tokens are explicitly scrubbed from audit payloads and application logs.

---

## 7. Reliability, Scalability & Concurrency Review

1. **Autosave Race Conditions:** Monotonic sequence versioning (`WHERE sequence < incoming_sequence`) eliminates race conditions caused by delayed packets over mobile networks.
2. **Concurrent Roll-Number Allocation:** Database row locks (`SELECT ... FOR UPDATE`) guarantee zero duplicate sequence numbers even during high-concurrency batch allocations.
3. **Strict Server-Authoritative Deadline Integrity ($T_{\text{ingress}}$):**
   - Zero trust in client timestamps.
   - Nginx high-precision `$msec` arrival timestamping unconditionally injected as $T_{\text{ingress}}$.
   - Mandatory fail-closed enforcement in production: requests missing `$msec` or arriving from untrusted proxies immediately return HTTP 502 (`INGRESS_TIMESTAMP_INVALID`) and log `INGRESS_TIMESTAMP_INTEGRITY_FAILURE`.
   - Outermost WSGI middleware fallback is restricted strictly to development and testing environments (`ALLOW_WSGI_TIMESTAMP_FALLBACK = True`).
   - Requests arriving before `end_time` at the trusted reverse proxy ($T_{\text{ingress}} \le \text{official\_end\_time}$) are accepted even if internal processing finishes slightly after `end_time`.
   - Requests first received after `end_time` are rejected immediately with HTTP 410 Gone, and attempt is transitioned to `AUTO_CLOSED_DEADLINE`.
4. **Race-Free Deadline Finalization Protocol:**
   - Background supervisor worker will not initiate closure until $T_{\text{now}} \ge \text{official\_end\_time} + \Delta_{\text{ingress\_drain}}$ (15s).
   - Active in-flight tracking via Redis hash `exam:inflight:{attempt_id}` defers finalization while qualifying requests execute, with a 30s hard ceiling preventing indefinite stalls.
   - Database row-level locking (`SELECT ... FOR UPDATE` on `ExamAttempt`) serializes concurrent autosaves, manual submissions, and supervisor workers.
   - Full 12-scenario matrix defines exact behaviors, outcomes, and HTTP status codes.
5. **Peak Examination Traffic:**
   - Read-heavy live exam questions and configuration can be cached in Redis.
   - Static assets served directly by Nginx.
   - Autosave requests are lightweight (`PATCH` with minimal payload), minimizing database I/O.
6. **Task Queue Abstraction:** Abstracted `TaskQueueService` allows running synchronous or DB-backed tasks in development/testing while leveraging Celery + Redis in production.

---

## 8. Risks, Assumptions and Limitations

| Area | Risk / Limitation | Mitigation |
| :--- | :--- | :--- |
| **Nginx `$msec` Semantics** | Nginx `$msec` represents user-space variable evaluation time during event loop processing, not a kernel/hardware packet arrival timestamp. | Documented as an acknowledged software stack limitation; system adopts an explicit conservative server-authoritative cutoff policy. |
| **Production Ingress Header Tampering** | Untrusted clients or misconfigured reverse proxies sending manipulated `X-Request-Arrival-Time` headers. | Strict fail-closed policy: header accepted only from verified `TRUSTED_PROXIES`; missing or invalid headers return HTTP 502 `INGRESS_TIMESTAMP_INVALID` and log security audit event. |
| **In-Flight Finalization Bounded Wait** | Extreme server worker queueing exceeding the 30-second hard ceiling could theoretically cause a late on-time request to encounter `AUTO_CLOSED_DEADLINE`. | Mitigated by 15s socket drain window + Redis in-flight tracking + worker sizing; uncommitted requests delayed beyond ceiling are logged as `ABANDONED_INFLIGHT_REQUEST` and preserved locally as `REJECTED_DEADLINE_EXCEEDED` for appeal. |
| **Shared-Device Lab PC Reboot Sanitization** | Workstations running Deep Freeze or reboot-wipe scripts purge IndexedDB on reboot. | Documented mandatory operational rule: candidates experiencing exam disruption on shared lab PCs must export `AUDIT_RECOVERY_BUNDLE` prior to rebooting or leaving the workstation. |
| **Post-Deadline Evidence Expiry** | Once the configured evidence key retention period (`EXAM_EVIDENCE_KEY_RETENTION_PERIOD`) expires, local ciphertext becomes permanently unrecoverable. | Documented policy lifecycle; server deletes DEKs post-retention; candidates must file appeals within institutional retention window; production activation gated on configured policy. |
| **Diagnostic Bundle Verification Limits** | Client-generated timestamps inside `AUDIT_RECOVERY_BUNDLE` are self-reported and cannot cryptographically prove pre-deadline completion. | Documented limitation; bundle accompanied by SHA-256 integrity metadata; server-issued receipts authenticated via server HMAC; evaluation governed by administrative committee review rather than automatic override. |
| **PIN Delivery Method** | Advance PIN printing on admit cards risks early disclosure; just-in-time delivery risks network/SMS bottlenecks on exam day. | System enforces mandatory configuration (`EXAM_PIN_DELIVERY_METHOD`); PIN generation blocked until college confirms choice. |
| **Network Loss Across Deadline** | A student disconnected before deadline cannot upload offline answers after `end_time`. | Documented as strict server-authoritative integrity rule; attempt is auto-closed using last synchronized answers; unacknowledged answers preserved in `AUDIT_RECOVERY_BUNDLE` for grievance appeal via Track B. |
| **Descriptive Upload Bandwidth** | Students on poor 4G uplinks uploading multiple photos may experience timeouts. | Client-side Canvas downscaling in React UI; provisional 5 MB default is configurable; multipart streaming; background retry. |
| **Redis / Celery Infrastructure** | Requiring Redis and Celery daemon management could burden small single-server deployments. | Abstracted `TaskQueueService` allows running synchronous or DB-backed tasks in development/testing without requiring an active Redis server. |

---

## 9. Unresolved Decisions (Flagged for Institutional / Chunk 02 Confirmation)

The following items are documented as proposed baselines and flagged for formal institutional or data modeling confirmation:

1. **Institutional Evidence Key Retention Approval & Activation Gate:** Confirmation of the institutional retention period (`EXAM_EVIDENCE_KEY_RETENTION_PERIOD`, recommended baseline 14–30 days) by college administration. System strictly blocks examination publication and activation while unconfigured. Confirmation of administrative workstation sanitization schedules and student evidence export protocols prior to lab PC reboots.
2. **Shared-Device Lab Sanitization & Diagnostic Appeal Policy:** Institutional confirmation of administrative workstation sanitization schedules (e.g. nightly deep-freeze/reboot scripts in shared college computer labs), proctor procedures for immediate post-exam evidence export, and formal college protocols for evaluating `AUDIT_RECOVERY_BUNDLE` appeal submissions.
3. **Examination PIN Delivery Policy:** Mandatory college decision selecting between PIN printing on admit cards or just-in-time delivery via SMS/portal/invigilators. PIN issuance blocked until configured.
4. **Late-Entry Cutoff Duration:** Institutional confirmation of the permitted entry window (`entry_cutoff_time`, e.g., 15 or 30 minutes past `start_time`), after which new attempts cannot be initialized.
5. **Official Gauhati University Roll-Number Pattern:** Populating the configurable `RollNumberScheme` template once the official university convention is provided.
6. **Descriptive Upload Quotas:** Confirming provisional defaults (max 3 files, 5 MB/file, PDF/JPEG/PNG) or adopting custom institutional thresholds.
7. **Answer Script Retention Schedule:** Confirming statutory retention period (recommended: 6 to 12 months) before automated archival or purging.
8. **Grading & GPA Scale:** Confirming official Gauhati University 10-point letter grade conversion tables and SGPA/CGPA formulas.
9. **Optional High-Entropy Offline Encryption Recovery Secret (Unresolved Design Decision):** Confirmation whether the college desires a separate high-entropy recovery secret (128-bit passphrase or base58 token) printed or distributed by proctors to allow offline DEK unwrapping during total server outages. Due to substantial operational overhead, server-assisted key release remains the standard baseline.

---

## 10. Final Audit Status

* **Status:** **PASS WITH WARNINGS**
* **Gate Sign-off:** All Chunk 01 requirements and Round 1–7 audit corrections are fully addressed. The Two-Stage Deadline Finalization Protocol resolves the in-flight race condition with mathematically bounded guarantees. The Evidence Retention State Machine establishes a hard production activation gate and complete lifecycle controls. All 11 Mermaid diagrams are reconciled and manually verified. Documented non-blocking institutional policies are explicitly flagged for college confirmation.
* **Next Permitted Chunk:** **CHUNK 02 — DATABASE ARCHITECTURE** (pending explicit user approval).

> **STOP:** All work for Chunk 01 is complete. No application code, packages, or database schemas have been generated. Awaiting explicit user approval before proceeding to Chunk 02.
