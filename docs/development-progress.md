# Development Progress Tracker

**Project:** College Online Examination System (Gauhati University FYUGP Academic Context)  
**Last Updated:** 2026-11-03 (Round 6 Revision)  

---

## 1. Overall Status

* **Current Active Chunk:** **CHUNK 01 — SYSTEM ARCHITECTURE**
* **Project Phase:** Architecture & Specification
* **Implementation Permission:** **NOT GRANTED** (Application initialization, dependencies, and code remain gated)
* **Next Permitted Action:** User review and authorization of Chunk 01 Architecture Audit (Round 6 Revision)

---

## 2. Chunk Execution Progress

| Chunk | Name | Status | Audit Document | Approval Status |
| :---: | :--- | :---: | :--- | :---: |
| **00** | Requirements Audit | **COMPLETED** | [`docs/audits/chunk-00-requirements-audit.md`](chunk-00-requirements-audit.md) | **APPROVED** (2026-11-02) |
| **01** | System Architecture | **IN REVIEW** | [`docs/audits/chunk-01-system-architecture-audit.md`](chunk-01-system-architecture-audit.md) | **PENDING USER APPROVAL** |
| **02** | Database Architecture | NOT STARTED | — | GATED |
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
7. **Deadline Enforcement & Ingress Timestamping ($T_{\text{ingress}}$):** Unified $T_{\text{ingress}}$ terminology across all sections and diagrams; server-authoritative cutoff using high-precision Nginx `$msec` arrival timestamping (`X-Request-Arrival-Time`) unconditionally overwritten by reverse proxy; accepted strictly from configured `TRUSTED_PROXIES`; direct backend access prevented via Unix socket/firewall; mandatory fail-closed behavior on missing/invalid timestamps in production (HTTP 502 `INGRESS_TIMESTAMP_INVALID`); outermost WSGI middleware ingress fallback ($T_{\text{wsgi\_ingress}}$) restricted strictly to development/testing environments (`ALLOW_WSGI_TIMESTAMP_FALLBACK = True`); zero trust in client timestamps.
8. **Encrypted Shared-Device Offline Cache & Dual-Track Key Recovery:** Web Crypto API `AES-256-GCM` encryption at rest in IndexedDB with 96-bit random IVs and AAD binding `(student_id, examination_id, attempt_id)`; ephemeral in-memory DEK; zero credentials or PINs stored locally as wrapping keys; Dual-Track key recovery separating Track A (Live Exam Recovery, active `IN_PROGRESS`, $T \le \text{deadline}$, write-enabled) from Track B (Post-Deadline Read-Only Evidence Recovery, finalized attempts within configurable `EXAM_EVIDENCE_KEY_RETENTION_PERIOD`, strictly read-only); diagnostic recovery bundles (`AUDIT_RECOVERY_BUNDLE`) with SHA-256 integrity metadata and server HMACs; institutional kiosk and lab Deep Freeze reboot export rules documented.
9. **Submission Lifecycle Reconciliation:** Explicit distinction between $T_{\text{ingress}}$ (`submitted_at`), $T_{\text{process}}$, and application transaction recording time `transaction_recorded_at` (persisted in `committed_at`); comprehensive handling of all 6 submission scenarios with exact HTTP response codes (200, 409, 410, 502); transactional row locking (`SELECT ... FOR UPDATE` on `ExamAttempt`) to serialize concurrent autosaves and final submissions; idempotent duplicate submission processing.
10. **XSS Defense-in-Depth:** Acknowledged `HttpOnly` scope (prevents raw cookie theft, but requires defense-in-depth via React JSX escaping, DOMPurify, strict CSP, and backend input validation).
11. **Background Worker:** `Celery` + `Redis` for production batch operations (PDFs, emails, dead-letter supervision), with an abstracted service layer for test execution.
