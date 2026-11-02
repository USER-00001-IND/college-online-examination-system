# Development Progress Tracker

**Project:** College Online Examination System (Gauhati University FYUGP Academic Context)  
**Last Updated:** 2026-11-02  

---

## 1. Overall Status

* **Current Active Chunk:** **CHUNK 01 — SYSTEM ARCHITECTURE**
* **Project Phase:** Architecture & Specification
* **Implementation Permission:** **NOT GRANTED** (Application initialization, dependencies, and code remain gated)
* **Next Permitted Action:** User review and authorization of Chunk 01 Architecture Audit

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
7. **Deadline Enforcement:** Server-authoritative cutoff using high-precision Nginx `$msec` arrival timestamping (`X-Request-Arrival-Time`) overwritten by reverse proxy; accepted strictly from configured trusted proxy IPs; outermost WSGI middleware ingress fallback with documented conservative delay trade-off; zero trust in client timestamps.
8. **Offline Cache Lifecycle:** Scoped storage keys (`exam_cache_*`); zero credential storage; unsynchronized answers never silently deleted before server acknowledgement; logout preserves unsynced data with shared-device isolation; recovery bundles (`AUDIT_RECOVERY_BUNDLE`) for appeal; rejected late answers marked `REJECTED_DEADLINE_EXCEEDED`; synchronized answers purged on confirmed submission.
9. **XSS Defense-in-Depth:** Acknowledged `HttpOnly` scope (prevents raw cookie theft, but requires defense-in-depth via React JSX escaping, DOMPurify, strict CSP, and backend input validation).
10. **Background Worker:** `Celery` + `Redis` for production batch operations (PDFs, emails, dead-letter supervision), with an abstracted service layer for test execution.
