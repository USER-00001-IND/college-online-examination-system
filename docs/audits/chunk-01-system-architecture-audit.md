# Chunk 01: System Architecture Audit Report (Round 6 Revision)

**Project:** College Online Examination System (Gauhati University FYUGP Academic Context)  
**Author:** Antigravity Agent  
**Date:** 2026-11-03 (Round 6 Revision)  
**Assigned Scope:** Chunk 01 — System Architecture  
**Status:** **PASS WITH WARNINGS** (Core architecture is complete, robust, and technically verified; documented non-blocking institutional policies are explicitly flagged for college confirmation).

---

## 1. Scope Assigned vs. Completed

* **Assigned Scope:**
  - Design modular monolith architecture using React, Vite, Tailwind CSS, React Router, Django, DRF, MySQL, ReportLab, and SMTP.
  - Incorporate approved Chunk 00 requirements (Self-registration with approval, hybrid descriptive text + uploads, dual-tier PIN security, configurable roll-number generator, ReportLab PDFs).
  - Define frontend and backend modules, boundaries, and dependencies.
  - Incorporate all Round 6 independent review corrections:
    1. **Blocking Contradiction Resolved — Post-Deadline Encrypted Answer Key Recovery:**
       - Reconciled the conflict where post-deadline preserved answers were inaccessible after browser restart because key release was previously blocked once attempts were finalized or server time passed the deadline.
       - Established a **Dual-Track Key-Management Lifecycle** with separate authorization contracts, endpoints, and security guarantees:
         - **Track A (Live Exam Key Recovery):** `POST /api/attempts/{id}/recover-cache-key/` scoped strictly to active `IN_PROGRESS` attempts before `official_end_time` to resume live answering and synchronized submission.
         - **Track B (Post-Deadline Read-Only Evidence Recovery):** `POST /api/attempts/{id}/recover-evidence-key/` scoped strictly to finalized attempts (`SUBMITTED`, `AUTO_CLOSED_DEADLINE`) within the configurable post-deadline retention window to decrypt local IndexedDB storage, view original drafts in a watermarked read-only viewer, and export `AUDIT_RECOVERY_BUNDLE`.
       - Strictly prohibited live exam reactivation, answer alteration, or automated regrading via Track B.
    2. **Key Retention and Data Lifecycle Specification:**
       - Documented server-wrapped DEK retention window (`EXAM_EVIDENCE_KEY_RETENTION_PERIOD`, pending institutional approval / `UNCONFIGURED`, recommended baseline 14–30 days).
       - Documented local browser storage retention (`LOCAL_EVIDENCE_CACHE_MAX_AGE_DAYS`).
       - Documented permanent ciphertext unrecoverability upon server key deletion (`PERMANENTLY_UNRECOVERABLE_KEY_PURGED`).
       - Documented device switching and browser cache clearing boundaries (local IndexedDB is device-specific).
       - Clearly distinguished synchronized answers (`COMMITTED` in MySQL) from unsynchronized diagnostic evidence (IndexedDB records).
       - Defined evidence export telemetry and signed audit acknowledgement (`AuditLog: EVIDENCE_BUNDLE_EXPORTED`).
       - Defined administrative access controls: administrators cannot silently dump student storage; forensic DEK access requires dual-authorization and audit logging (`AuditLog: ADMIN_EVIDENCE_DEK_ACCESS`).
       - Documented interaction with institutional workstation sanitization: warned that lab PCs with Deep Freeze wipe user profiles on reboot, requiring candidates to export their recovery bundle before logging off or restarting.
    3. **Preserved All Prior Security Baselines:**
       - Maintained Web Crypto API `AES-256-GCM` encryption at rest in IndexedDB with 96-bit random IVs and AAD binding.
       - Maintained complete removal of Examination PINs as local wrapping keys (zero offline dictionary attack vulnerability).
       - Maintained strict fail-closed production ingress timestamp enforcement (HTTP 502 `INGRESS_TIMESTAMP_INVALID` on missing/untrusted/skewed proxy timestamps).
       - Maintained application transaction recording time (`transaction_recorded_at`) distinction from hardware commit instant.
       - Maintained ReportLab pure-Python PDF generation, configurable roll-number engine, and multi-tier role authorization.
  - Reconcile Mermaid diagrams, list exact locations, and distinguish manual review from automated validation.
* **Scope Completed:**
  - 100% of the assigned architectural tasks and all Round 6 review corrections completed.
  - Zero application code, migrations, or dependencies installed (strict adherence to gate rules).

---

## 2. Documentation Created / Modified

| File | Status | Description |
| :--- | :---: | :--- |
| [`docs/architecture.md`](../architecture.md) | **Updated** | Master architecture document containing system overview, module definitions, workflows, security boundaries, and all 11 Mermaid diagrams. Updated with the Dual-Track Key-Management Lifecycle (Live Exam Recovery vs. Post-Deadline Read-Only Evidence Recovery), comprehensive evidence retention and workstation sanitization policies, recovery bundle specifications, fail-closed ingress verification, and accurate transaction recording semantics. |
| [`docs/development-progress.md`](../development-progress.md) | **Updated** | Progress tracking ledger recording chunk statuses, approvals, and decisions. Kept Chunk 01 pending user approval. |
| [`docs/audits/chunk-01-system-architecture-audit.md`](chunk-01-system-architecture-audit.md) | **Updated** | Comprehensive audit report reflecting the finalized Round 6 corrected architecture baseline with truthful status and validation disclosure. |
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
4. **Examination Lifecycle & Dual-Tier Access:**
   - Account login establishes student identity; live exam entry requires entering a separate, cryptographically hashed Examination PIN.
   - Early access allows entering the Waiting Room only; new attempts are permitted only within `[start_time, entry_cutoff_time]`; active attempts may resume until `end_time`; attempts are permanently locked after submit or auto-close.
   - Server-authoritative timer; conservative ingress timestamping ($T_{\text{ingress}} \le \text{official\_end\_time}$); zero trust in client timestamps; monotonic sequence versioning; idempotent submission; ReportLab PDF generation; private storage for admit cards and student descriptive uploads.
5. **Shared-Device Cryptographic Confidentiality & Dual-Track Key Recovery:**
   - Local answer persistence protected at rest using Web Crypto API `AES-256-GCM` with 96-bit random IVs and AAD binding.
   - Zero credentials or PINs stored locally as wrapping keys.
   - Server-assisted key release partitioned into:
     - **Track A (Live Exam Key Recovery):** Unwraps DEK into volatile RAM for active attempts before `end_time` to resume answering.
     - **Track B (Post-Deadline Read-Only Evidence Recovery):** Unwraps DEK into volatile RAM for finalized attempts within `EXAM_EVIDENCE_KEY_RETENTION_PERIOD` to export `AUDIT_RECOVERY_BUNDLE` and view original local answers in a read-only viewer. Write APIs strictly disabled.

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
| 10 | Examination Attempt and Submission Sequence | Section 13.5 (Line 1010) | `sequenceDiagram` |
| 11 | Evaluation & Results Publication Architecture | Section 14 (Line 1061) | `flowchart TD` |

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
| **Encrypted offline cache & dual-track recovery** | Concrete Web Crypto API `AES-256-GCM` encryption at rest in IndexedDB with 96-bit random IVs and AAD binding. Zero local PIN wrapping. Partitioned dual-track key recovery: Track A for active attempts before deadline; Track B for post-deadline read-only evidence recovery and diagnostic export within `EXAM_EVIDENCE_KEY_RETENTION_PERIOD`. Preserved unacknowledged answers; recovery bundles (`AUDIT_RECOVERY_BUNDLE`) with SHA-256 integrity metadata and server HMACs; institutional kiosk and deep freeze warning documented. | Section 13.3 |
| **Reconciled submission lifecycle** | Explicit distinction between $T_{\text{ingress}}$ (`submitted_at`), $T_{\text{process}}$, and application transaction recording time `transaction_recorded_at` (persisted in `committed_at`). Exhaustive documentation of all 6 submission scenarios with exact HTTP response codes (200, 409, 410, 502) and transactional row-locking semantics (`SELECT ... FOR UPDATE`). | Section 13.4 & 13.5 |
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
   - Distinct audit events for key recovery: `AuditLog: LIVE_CACHE_KEY_RELEASED`, `AuditLog: EVIDENCE_KEY_RELEASED`, and `AuditLog: EVIDENCE_BUNDLE_EXPORTED`.
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
   - Offline answers entered after `end_time` cannot be synchronized upon reconnection; marked `REJECTED_DEADLINE_EXCEEDED` locally for diagnostic appeal, while attempt is finalized using only pre-deadline saved state.
4. **Reconciled Submission Concurrency & Locking:**
   - Concurrent autosaves and final submissions serialize on `ExamAttempt` row lock (`SELECT ... FOR UPDATE`).
   - An autosave arriving after submission finalization fails gracefully with HTTP 409 Conflict (`ATTEMPT_ALREADY_FINALIZED`).
   - Network retries and duplicate submission clicks return idempotent HTTP 200 responses without triggering duplicate evaluations.
   - `submitted_at` records $T_{\text{ingress}}$, while `committed_at` records application transaction time `transaction_recorded_at`.
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
| **WSGI Fallback Latency** | Standalone WSGI execution without Nginx uses conservative middleware ingress timestamping ($T_{\text{wsgi\_ingress}}$) that may reject requests delayed by WSGI request buffering. | Documented that WSGI fallback is strictly permitted in dev/test; Nginx reverse proxy with `$msec` and fail-closed enforcement is mandatory for production deployments. |
| **Shared-Device Lab PC Reboot Sanitization** | Workstations running Deep Freeze or reboot-wipe scripts purge IndexedDB on reboot. | Documented mandatory operational rule: candidates experiencing exam disruption on shared lab PCs must export `AUDIT_RECOVERY_BUNDLE` prior to rebooting or leaving the workstation. |
| **Post-Deadline Evidence Expiry** | Once the configured evidence key retention period (`EXAM_EVIDENCE_KEY_RETENTION_PERIOD`) expires, local ciphertext becomes permanently unrecoverable. | Documented policy lifecycle; server deletes DEKs post-retention; candidates must file appeals within institutional retention window. |
| **Diagnostic Bundle Verification Limits** | Client-generated timestamps inside `AUDIT_RECOVERY_BUNDLE` are self-reported and cannot cryptographically prove pre-deadline completion. | Documented limitation; bundle accompanied by SHA-256 integrity metadata; server-issued receipts authenticated via server HMAC; evaluation governed by administrative committee review rather than automatic override. |
| **PIN Delivery Method** | Advance PIN printing on admit cards risks early disclosure; just-in-time delivery risks network/SMS bottlenecks on exam day. | System enforces mandatory configuration (`EXAM_PIN_DELIVERY_METHOD`); PIN generation blocked until college confirms choice. |
| **Network Loss Across Deadline** | A student disconnected before deadline cannot upload offline answers after `end_time`. | Documented as strict server-authoritative integrity rule; attempt is auto-closed using last synchronized answers; unacknowledged answers preserved in `AUDIT_RECOVERY_BUNDLE` for grievance appeal via Track B. |
| **Descriptive Upload Bandwidth** | Students on poor 4G uplinks uploading multiple photos may experience timeouts. | Client-side Canvas downscaling in React UI; provisional 5 MB default is configurable; multipart streaming; background retry. |
| **Redis / Celery Infrastructure** | Requiring Redis and Celery daemon management could burden small single-server deployments. | Abstracted `TaskQueueService` allows running synchronous or DB-backed tasks in development/testing without requiring an active Redis server. |

---

## 9. Unresolved Decisions (Flagged for Institutional / Chunk 02 Confirmation)

The following items are documented as proposed baselines and flagged for formal institutional or data modeling confirmation:

1. **Post-Deadline Evidence Key Retention Window (`EXAM_EVIDENCE_KEY_RETENTION_PERIOD`):** Institutional confirmation of the duration server-wrapped DEKs are retained for grievance review post-finalization (recommended baseline: 14 to 30 days). Initialized as `UNCONFIGURED`.
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
* **Gate Sign-off:** All Chunk 01 requirements and Round 6 review corrections are fully addressed. All 11 Mermaid diagrams are documented, manually verified, and reconciled. Architectural boundaries, security protocols, technically defensible deadline enforcement ($T_{\text{ingress}}$), fail-closed production ingress verification, Web Crypto AES-256-GCM Dual-Track key lifecycle (Live Resumption vs. Post-Deadline Read-Only Evidence Recovery), diagnostic recovery bundle limits, and reconciled submission semantics are finalized in [`docs/architecture.md`](../architecture.md). Documented non-blocking institutional policies are explicitly flagged for college confirmation.
* **Next Permitted Chunk:** **CHUNK 02 — DATABASE ARCHITECTURE** (pending explicit user approval).

> **STOP:** All work for Chunk 01 is complete. No application code, packages, or database schemas have been generated. Awaiting explicit user approval before proceeding to Chunk 02.
