# Chunk 01: System Architecture Audit Report (Round 5 Revision)

**Project:** College Online Examination System (Gauhati University FYUGP Academic Context)  
**Author:** Antigravity Agent  
**Date:** 2026-11-03 (Round 5 Revision)  
**Assigned Scope:** Chunk 01 — System Architecture  
**Status:** **PASS WITH WARNINGS** (Core architecture is complete, robust, and technically verified; documented non-blocking institutional policies are explicitly flagged for college confirmation).

---

## 1. Scope Assigned vs. Completed

* **Assigned Scope:**
  - Design modular monolith architecture using React, Vite, Tailwind CSS, React Router, Django, DRF, MySQL, ReportLab, and SMTP.
  - Incorporate approved Chunk 00 requirements (Self-registration with approval, hybrid descriptive text + uploads, dual-tier PIN security, configurable roll-number generator, ReportLab PDFs).
  - Define frontend and backend modules, boundaries, and dependencies.
  - Incorporate all Round 5 independent review security corrections:
    1. **Finding A — Removal of PIN-Based Recovery & Secure Server-Assisted Key Lifecycle (High Priority / Blocking Resolved):**
       - Removed the Examination PIN and short credentials from local encryption wrapping; eliminated the offline dictionary-attack vulnerability on locally persisted cache records.
       - Retained AES-256-GCM encryption at rest in IndexedDB via Web Crypto API.
       - Defined authenticated server-assisted key release over TLS: client exports DEK securely over TLS upon attempt start; server wraps DEK with server-managed master/KMS key (`ExamAttempt.encrypted_cache_dek`); upon attempt resumption, backend enforces strict multi-point authorization (`student_id`, active `IN_PROGRESS` attempt, valid session & PIN verification, server time $\le \text{official\_end\_time}$, rate limit $\le 3/\text{min}$, and audited log).
       - Explicitly documented offline limitation: encrypted cached answers are temporarily inaccessible if the browser restarts or tab closes while the workstation is offline until server connectivity is restored. In-memory DEK remains loaded during active tabs during network drops.
       - Documented optional high-entropy recovery secret (128-bit passphrase/token) as an unresolved design decision in Section 18 with operational overhead trade-offs; not implemented by default.
       - Preserved unacknowledged answers without silent deletion; defined `LOCKED_KEY_UNAVAILABLE` and `UNRECOVERABLE_CIPHERTEXT` states.
       - Acknowledged lack of protection against same-origin scripts (XSS) and compromised OS endpoints.
    2. **Finding B — Specification & Authenticity Limitations of Recovery Bundle (`AUDIT_RECOVERY_BUNDLE`):**
       - Detailed exact bundle contents, strictly partitioning client-generated diagnostic evidence (user-agent, screen resolution, local clock, encrypted answer payloads with IVs and tags, client interaction timestamps, network error logs) from authoritative server records (attempt identifiers, server receipt UUIDs, $T_{\text{ingress}}$, server-recorded sequence counters, and server-side HMAC signatures).
       - Defined cryptographic authenticity vs integrity metadata: bundle is accompanied by client-computed SHA-256 integrity checksum to detect transmission corruption; stated that no trusted signing secret exists in frontend JavaScript.
       - Stated clearly that client-generated timestamps inside the bundle do not prove pre-deadline completion.
       - Documented limits of forensic verification on compromised workstations.
       - Defined college examination grievance committee review as a proposed institutional workflow, not an automated grading override; late-rejected answers are never silently treated as valid submissions.
    3. **Finding C — Timestamp Terminology & Production Ingress Failure Semantics:**
       - **Database Transaction Timestamp:** Distinguished application transaction recording time (`transaction_recorded_at = django.utils.timezone.now()`) from the actual database engine transaction commit instant (MySQL InnoDB redo log flush); kept `submitted_at = T_ingress` for accepted manual submissions.
       - **Production Ingress Failure Semantics (Fail-Closed):** Enforced mandatory fail-closed behavior on examination write endpoints (`/api/attempts/*/answers/`, `/api/attempts/*/submit/`) when `HTTP_X_REQUEST_ARRIVAL_TIME` is missing, untrusted (source IP not in `TRUSTED_PROXIES`), malformed, or skewed ($> 500\text{ ms}$ future or impossible lag); backend aborts write, returns HTTP 502 with `INGRESS_TIMESTAMP_INVALID`, and emits critical security audit event `INGRESS_TIMESTAMP_INTEGRITY_FAILURE`.
       - **Strict Distinction:** Timestamp integrity failures are strictly distinguished from examination deadline expiry (`AUTO_CLOSED_DEADLINE` / HTTP 410) and do not alter the student's attempt state.
       - **Restricted WSGI Fallback:** Outermost WSGI middleware fallback ($T_{\text{wsgi\_ingress}}$) is strictly restricted to development/testing environments (`ALLOW_WSGI_TIMESTAMP_FALLBACK = True` / `DEBUG = True`) with documented conservative delay trade-offs.
  - Reconcile Mermaid diagrams, list exact locations, and distinguish manual review from automated validation.
* **Scope Completed:**
  - 100% of the assigned architectural tasks and all Round 5 review corrections completed.
  - Zero application code, migrations, or dependencies installed (strict adherence to gate rules).

---

## 2. Documentation Created / Modified

| File | Status | Description |
| :--- | :---: | :--- |
| [`docs/architecture.md`](../architecture.md) | **Updated** | Master architecture document containing system overview, module definitions, workflows, security boundaries, and all 11 Mermaid diagrams. Updated with server-assisted AES-256-GCM key management (PIN derivation removed), diagnostic recovery bundle specifications and integrity limits, fail-closed production ingress timestamp enforcement (HTTP 502), dev-only WSGI fallback, and accurate transaction recording semantics. |
| [`docs/development-progress.md`](../development-progress.md) | **Updated** | Progress tracking ledger recording chunk statuses, approvals, and decisions. Kept Chunk 01 pending user approval. |
| [`docs/audits/chunk-01-system-architecture-audit.md`](chunk-01-system-architecture-audit.md) | **Updated** | Comprehensive audit report reflecting the finalized Round 5 corrected architecture baseline with truthful status and validation disclosure. |
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
5. **Shared-Device Cryptographic Confidentiality:**
   - Local answer persistence protected at rest using Web Crypto API `AES-256-GCM` with 96-bit random IVs and AAD binding.
   - In-memory DEK held in volatile RAM; unwrapped strictly via authenticated server-assisted release over TLS. Zero credentials or PINs stored locally as wrapping keys.
   - Unsynchronized answers preserved across logout without leaking plaintext to subsequent lab users.

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
| 10 | Examination Attempt and Submission Sequence | Section 13.5 (Line 935) | `sequenceDiagram` |
| 11 | Evaluation & Results Publication Architecture | Section 14 (Line 986) | `flowchart TD` |

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
| **Encrypted shared-device offline cache** | Concrete Web Crypto API `AES-256-GCM` encryption at rest in IndexedDB with 96-bit random IVs and AAD binding `(student_id, examination_id, attempt_id)`. Zero credential storage; PIN-derived local wrapping removed completely. Authenticated server-assisted key release over TLS with strict multi-point authorization. Exportable diagnostic bundle (`AUDIT_RECOVERY_BUNDLE`) with integrity metadata and linked server receipts for appeal. Late rejected answers marked `REJECTED_DEADLINE_EXCEEDED` and not claimed as synchronized. Synchronized data cleaned up on confirmed submit/auto-close. Institutional kiosk policies documented. | Section 13.3 |
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
4. **Shared-Device Offline Cache Privacy & Cryptographic Isolation:**
   - Threat model explicitly accounts for shared lab PCs, cyber cafes, DevTools (`F12`) storage inspection, and malicious extensions.
   - Local storage in IndexedDB is encrypted at rest using `AES-256-GCM` via Web Crypto API.
   - **Zero Local PIN Derivation:** PIN-derived KEK wrapping is eliminated; no wrapped keys or salts are stored locally in IndexedDB, completely eliminating offline dictionary attacks.
   - In-memory DEK is cleared on tab close/logout. Server-assisted key release over TLS restores the key into volatile memory upon verified re-authentication (`student_id`, active `IN_PROGRESS` state, valid session, before `end_time`, rate-limited).
   - Temporary inaccessibility: if the browser closes while offline, cached answers are temporarily inaccessible until server connectivity is restored.
   - Unsynchronized answers are never silently purged before server acknowledgement.
   - Synchronized answers are purged immediately upon confirmed submission or auto-closure.
   - Residual risks (unmanaged malware, memory dumpers) are mitigated through documented institutional kiosk policies (ephemeral browser sessions, OS Deep Freeze/reboot scripts).
5. **Audit Trail & Secret Hygiene:**
   - Centralized `AuditLog` records actor, IP address, action, target entity, and before/after state diffs.
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
| **Shared-Device Offline Inaccessibility** | If a browser is closed while offline, encrypted IndexedDB answers cannot be decrypted until server connection is re-established. | In-memory DEK remains loaded during active tabs during network drops; answers remain safely encrypted without silent deletion; server-assisted key release restores DEK immediately upon re-connection. |
| **Diagnostic Bundle Verification Limits** | Client-generated timestamps inside `AUDIT_RECOVERY_BUNDLE` are self-reported and cannot cryptographically prove pre-deadline completion. | Documented limitation; bundle accompanied by SHA-256 integrity metadata; server-issued receipts authenticated via server HMAC; evaluation governed by administrative committee review rather than automatic override. |
| **PIN Delivery Method** | Advance PIN printing on admit cards risks early disclosure; just-in-time delivery risks network/SMS bottlenecks on exam day. | System enforces mandatory configuration (`EXAM_PIN_DELIVERY_METHOD`); PIN generation blocked until college confirms choice. |
| **Network Loss Across Deadline** | A student disconnected before deadline cannot upload offline answers after `end_time`. | Documented as strict server-authoritative integrity rule; attempt is auto-closed using last synchronized answers; unacknowledged answers preserved in `AUDIT_RECOVERY_BUNDLE` for grievance appeal. |
| **Descriptive Upload Bandwidth** | Students on poor 4G uplinks uploading multiple photos may experience timeouts. | Client-side Canvas downscaling in React UI; provisional 5 MB default is configurable; multipart streaming; background retry. |
| **Redis / Celery Infrastructure** | Requiring Redis and Celery daemon management could burden small single-server deployments. | Abstracted `TaskQueueService` allows running synchronous or DB-backed tasks in development/testing without requiring an active Redis server. |

---

## 9. Unresolved Decisions (Flagged for Institutional / Chunk 02 Confirmation)

The following items are documented as proposed baselines and flagged for formal institutional or data modeling confirmation:

1. **Shared-Device Lab Sanitization & Diagnostic Appeal Policy:** Institutional confirmation of administrative workstation sanitization schedules (e.g. nightly deep-freeze/reboot scripts in shared college computer labs), local diagnostic bundle retention periods, and formal college protocols for evaluating `AUDIT_RECOVERY_BUNDLE` appeal submissions.
2. **Examination PIN Delivery Policy:** Mandatory college decision selecting between PIN printing on admit cards or just-in-time delivery via SMS/portal/invigilators. PIN issuance blocked until configured.
3. **Late-Entry Cutoff Duration:** Institutional confirmation of the permitted entry window (`entry_cutoff_time`, e.g., 15 or 30 minutes past `start_time`), after which new attempts cannot be initialized.
4. **Official Gauhati University Roll-Number Pattern:** Populating the configurable `RollNumberScheme` template once the official university convention is provided.
5. **Descriptive Upload Quotas:** Confirming provisional defaults (max 3 files, 5 MB/file, PDF/JPEG/PNG) or adopting custom institutional thresholds.
6. **Answer Script Retention Schedule:** Confirming statutory retention period (recommended: 6 to 12 months) before automated archival or purging.
7. **Grading & GPA Scale:** Confirming official Gauhati University 10-point letter grade conversion tables and SGPA/CGPA formulas.
8. **Optional High-Entropy Offline Encryption Recovery Secret (Unresolved Design Decision):** Confirmation whether the college desires a separate high-entropy recovery secret (128-bit passphrase or base58 token) printed or distributed by proctors to allow offline DEK unwrapping during total server outages. Due to substantial operational overhead, server-assisted key release remains the standard baseline.

---

## 10. Final Audit Status

* **Status:** **PASS WITH WARNINGS**
* **Gate Sign-off:** All Chunk 01 requirements and Round 5 review corrections are fully addressed. All 11 Mermaid diagrams are documented, manually verified, and reconciled. Architectural boundaries, security protocols, technically defensible deadline enforcement ($T_{\text{ingress}}$), fail-closed production ingress verification, Web Crypto AES-256-GCM server-assisted key lifecycle, diagnostic recovery bundle limits, and reconciled submission semantics are finalized in [`docs/architecture.md`](../architecture.md). Documented non-blocking institutional policies are explicitly flagged for college confirmation.
* **Next Permitted Chunk:** **CHUNK 02 — DATABASE ARCHITECTURE** (pending explicit user approval).

> **STOP:** All work for Chunk 01 is complete. No application code, packages, or database schemas have been generated. Awaiting explicit user approval before proceeding to Chunk 02.
