# Development Progress Tracker

**Project:** College Online Examination System (Gauhati University FYUGP Academic Context)  
**Last Updated:** 2026-11-03 (Chunk 02 In-Review)  

---

## 1. Overall Status

* **Current Active Chunk:** **CHUNK 02 — DATABASE ARCHITECTURE**
* **Project Phase:** Database Architecture & Specification
* **Implementation Permission:** **NOT GRANTED** (Application initialization, dependencies, models, migrations, and code remain gated)
* **Next Permitted Action:** Independent audit review and user authorization of Chunk 02 Database Architecture Audit

---

## 2. Chunk Execution Progress

| Chunk | Name | Status | Audit Document | Approval Status |
| :---: | :--- | :---: | :--- | :---: |
| **00** | Requirements Audit | **COMPLETED** | [`docs/audits/chunk-00-requirements-audit.md`](chunk-00-requirements-audit.md) | **APPROVED** (2026-11-02) |
| **01** | System Architecture | **COMPLETED** | [`docs/audits/chunk-01-system-architecture-audit.md`](chunk-01-system-architecture-audit.md) | **APPROVED** (2026-11-03) |
| **02** | Database Architecture | **IN REVIEW** | [`docs/audits/chunk-02-database-architecture-audit.md`](chunk-02-database-architecture-audit.md) | **PENDING INDEPENDENT AUDIT** |
| **03** | Project Initialization | NOT STARTED | — | GATED |
| **04** | Authentication and Roles | NOT STARTED | — | GATED |
| **05** | FYUGP Academic Management | NOT STARTED | — | GATED |
| **06** | Student and Faculty Management | NOT STARTED | — | GATED |
| **07** | Subject Registration | NOT STARTED | — | GATED |
| **08** | General Examination Creation | NOT STARTED | — | GATED |
| **09** | Eligibility Engine | NOT STARTED | — | GATED |
| **10** | Admit Cards and Email | NOT STARTED | — | GATED |
| **11** | Examination Engine | NOT STARTED | — | GATED |
| **12** | Evaluation and Results | NOT STARTED | — | GATED |
| **13** | Admin and Faculty Dashboards | NOT STARTED | — | GATED |
| **14** | Student Dashboard | NOT STARTED | — | GATED |
| **15** | Security and Testing Audit | NOT STARTED | — | GATED |
| **16** | Deployment | NOT STARTED | — | GATED |

---

## 3. Approved Key Decisions Log

1. **Student Provisioning:** Student self-registration with multi-step email verification and administrator identity approval.
2. **Descriptive Answers:** Hybrid approach supporting both browser-typed text and handwritten sheet image/PDF uploads. Provisional defaults (max 3 files, 5 MB/file) kept fully configurable.
3. **Examination Access:** Multi-tier authorization requiring standard student account login PLUS a separate, cryptographically hashed Examination PIN. PIN validity reconciled with entry cutoff and attempt resumption.
4. **PIN Delivery Gate:** Explicit institutional configuration (`EXAM_PIN_DELIVERY_METHOD`), initialized as unconfigured; PIN issuance strictly gated until approved.
5. **Roll Number Architecture:** Configurable pattern-based generator supporting college/GU conventions once finalized (template illustrative only).
6. **PDF Engine:** Pure-Python `ReportLab` for zero-OS-dependency portable admit card generation.
7. **Deadline Enforcement, Ingress Timestamping ($T_{\text{ingress}}$) & Bounded-Processing Consistency Model:** Unified $T_{\text{ingress}}$ terminology across all sections and diagrams; server-authoritative cutoff using high-precision Nginx `$msec` arrival timestamping (`X-Request-Arrival-Time`) unconditionally overwritten by reverse proxy; accepted strictly from configured `TRUSTED_PROXIES`; direct backend access prevented via Unix socket/firewall; mandatory fail-closed behavior on missing/invalid timestamps in production (HTTP 502 `INGRESS_TIMESTAMP_INVALID`); outermost WSGI middleware ingress fallback ($T_{\text{wsgi\_ingress}}$) restricted strictly to development/testing environments (`ALLOW_WSGI_TIMESTAMP_FALLBACK = True`). Option B: Bounded-Processing Consistency Model distinguishing the six lifecycle stages (Physical Arrival $\rightarrow$ Perimeter Ingress Timestamp $\rightarrow$ Complete HTTP Receipt $\rightarrow$ Application Admission $\rightarrow$ Database Transaction Execution $\rightarrow$ Durable Commit). Application Admission Window $W_{\text{admission}} = [\text{start\_time}, \text{official\_end\_time} + \Delta_{\text{drain}}]$ ($\Delta_{\text{drain}} = 15\text{s}$) accommodating socket queues. Coordination strictly through MySQL InnoDB ACID row locks (`SELECT ... FOR UPDATE` on `ExamAttempt`), eliminating distributed TOCTOU race conditions and Redis dependencies. Late write requests arriving after deadline are rejected with HTTP 410 without altering attempt status, preventing premature auto-closure while queued on-time requests traverse socket buffers; auto-closure is deferred strictly to the deadline supervisor worker after the 15-second drain window. Full 16-scenario concurrency analysis documented.
8. **Encrypted Shared-Device Offline Cache & Dual-Track Key Recovery:** Web Crypto API `AES-256-GCM` encryption at rest in IndexedDB with 96-bit random IVs and AAD binding `(student_id, examination_id, attempt_id)`; ephemeral in-memory DEK; zero credentials or PINs stored locally as wrapping keys; Dual-Track key recovery separating Track A (Live Exam Recovery, active `IN_PROGRESS`, $T \le \text{deadline}$, write-enabled) from Track B (Post-Deadline Read-Only Evidence Recovery, finalized attempts within configurable `EXAM_EVIDENCE_KEY_RETENTION_PERIOD`, strictly read-only); diagnostic recovery bundles (`AUDIT_RECOVERY_BUNDLE`) with SHA-256 integrity metadata and server HMACs; institutional kiosk and lab Deep Freeze reboot export rules documented.
9. **Evidence Retention State Machine & Hard Production Gate:** Formal 4-state operational machine (`UNCONFIGURED` -> `CONFIGURED` -> `EXPIRED` / `LEGAL_HOLD`); Hard production activation gate strictly blocking examination scheduling and activation while `EXAM_EVIDENCE_KEY_RETENTION_PERIOD` remains `UNCONFIGURED`; institutional approval requirement (`IsCollegeSuperAdmin`); immutable snapshots captured on `Examination` and `ExamAttempt`; scheduled daily deletion (`purge_expired_evidence_keys`) with security audit logging; legal hold suspension mechanics for active grievance appeals.
10. **Submission Lifecycle, Sequence Model & 16-Scenario Concurrency Model:** Explicit distinction between perimeter arrival $T_{\text{ingress}}$ (`submitted_at`), application admission $T_{\text{admit}}$, and application transaction recording time `transaction_recorded_at` (persisted in `committed_at`). Comprehensive handling of all 16 submission scenarios with exact HTTP response codes (200, 408, 409, 410, 502); transactional row locking (`SELECT ... FOR UPDATE` on `ExamAttempt`) to serialize concurrent autosaves, manual submissions, and deadline supervisor finalization; late manual submissions do not transition attempts to `AUTO_CLOSED_DEADLINE` or trigger grading; Section 13.5 sequence diagram models all branches including on-time autosaves under lock, bounded delay rejections, idempotent submission retries, late submissions without auto-closure, and post-commit asynchronous grading.
11. **XSS Defense-in-Depth:** Acknowledged `HttpOnly` scope (prevents raw cookie theft, but requires defense-in-depth via React JSX escaping, DOMPurify, strict CSP, and backend input validation).
12. **Background Worker:** `Celery` + `Redis` for production batch operations (PDFs, emails, dead-letter supervision), with an abstracted service layer for test execution.
13. **Relational Schema & MySQL InnoDB 8.x Baseline:** 51 normalized tables targeting MySQL 8.x with InnoDB exclusively; character set `utf8mb4` with `utf8mb4_0900_ai_ci`; Django ORM-compatible conventions (`id BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY`, snake_case table and column names); strict SQL mode; 3NF compliance across all entities with 4 formally justified denormalizations for historical immutability.
14. **Centralized Concurrency & Locking Serialization on `ExamAttempt`:** Implementation of Option B Bounded-Processing Consistency Model directly in the relational schema; `attempts_exam_attempt` serves as the centralized row-lock coordination point (`SELECT ... FOR UPDATE`); monotonic answer saving via `attempts_answer.version_sequence`; idempotent manual submissions with client UUID4 matching; deadline supervisor finalization respects the 15-second drain window; late submissions rejected with HTTP 410 without altering attempt status.
15. **Dual-Tier Cryptographic Credential & Key Storage:** Salted PBKDF2-SHA256 password hashes; separately salted PBKDF2 examination PIN hashes with independent 32-byte cryptographic salts (`pin_salt`); Data Encryption Keys (DEKs) envelope-wrapped under Master KEK via AES-KeyWrap; zero plaintext secrets or PINs stored in MySQL; evidence retention state machine with immutable expiry timestamps and daily automated purging.
16. **Private Descriptive Upload Storage Architecture:** Physical handwritten answer sheet photos and PDFs stored outside HTTP webroot in private disk storage; files renamed to random UUID4 identifiers (`uploads_descriptive_upload.file_uuid`) to eliminate path traversal and direct enumeration; ClamAV malware scanning status tracking; streaming access restricted strictly to authenticated Django controller views with role checks.\n