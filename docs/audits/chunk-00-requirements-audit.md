# Chunk 00: Requirements Audit Report

**Project:** College Online Examination System (Gauhati University FYUGP Context)  
**Author:** Antigravity Agent  
**Date:** 2026-11-02  
**Assigned Scope:** Chunk 00 — Requirements Audit  
**Status:** **PASS WITH WARNINGS** (Core requirements and scope are sound; non-blocking ambiguities and academic policy confirmations flagged for user review before or during Chunk 01).

---

## 1. Existing Project Inspection

* **Target Directory:** `/home/zero/Documents/college`
* **File System Scan:**
  * `./design.md` — Master design and workflow specification (32,627 bytes, 853 lines). Present and valid.
  * `./temp/` — Empty directory.
  * No existing source code, backend apps, frontend code, migration files, package definitions (`package.json`, `requirements.txt`, `Pipfile`), or configuration files exist.
  * No conflicting `docs/` or previous audit reports exist.
* **Inspection Conclusion:** Clean baseline workspace in the initial **NOT STARTED** state. No conflicting code or artifacts require cleanup.

---

## 2. Requirements Summary

The project is a secure, responsive, college-level online examination system built as a modular monolith with a React (Vite, Tailwind CSS) frontend, a Python Django + Django REST Framework backend, and a MySQL database.

The academic structure is modeled around the Gauhati University Four-Year Undergraduate Programme (FYUGP under NEP 2020), emphasizing:
1. **Configurable Academic Hierarchy:** Academic sessions, programmes, departments, semesters, subjects, paper offerings, and subject categories (Major, Minor, MDC, AEC, SEC, VAC).
2. **Explicit Registration:** Students register explicitly for specific paper offerings; eligibility for exams is strictly derived from verified active registration.
3. **Three Core Roles:** Administrator (system, academics, exams, eligibility, publishing), Faculty/Examiner (assigned subjects, descriptive grading), and Student (profile, admit cards, exams, results).
4. **End-to-End Examination Lifecycle:** Exam setup $\rightarrow$ eligibility computation $\rightarrow$ admin review/confirmation $\rightarrow$ roll number generation $\rightarrow$ PDF admit cards $\rightarrow$ email delivery $\rightarrow$ scheduled live exam with autosave $\rightarrow$ server-enforced deadline $\rightarrow$ MCQ auto-evaluation + faculty descriptive evaluation $\rightarrow$ result aggregation $\rightarrow$ approval $\rightarrow$ publication.
5. **Clear Out-of-Scope Boundaries:** No AI/webcam proctoring, no biometric attendance, no online payment gateways, no native mobile apps, and no direct integration/synchronization with official Gauhati University servers.

---

## 3. Confirmed Requirements (Ready for Architecture)

The following core requirements are unambiguous and established in `design.md`:

1. **Role-Based Access Control (RBAC):** Strict separation of Admin, Faculty, and Student permissions enforced on backend API endpoints.
2. **Explicit Subject/Paper Enrollment:** No implicit eligibility from department or semester alone; eligibility requires an active `StudentSubjectEnrollment` record for the targeted `PaperOffering`.
3. **Eligibility Review & Snapshot:** Automatic candidate identification, administrator review and override capability with audit justification, followed by a confirmed snapshot locked for the exam.
4. **Roll Number & Identifier Separation:** Roll numbers are identifiers allocated per exam/session; visible roll numbers are never treated as secret passwords.
5. **Authoritative Server Clocks:** Exam availability, countdown duration, autosave timestamps, and deadline closures are strictly determined and validated by the backend server, never the client browser.
6. **Autosave & Idempotency:** Answers are saved periodically and on input blur; repeated submissions do not produce duplicate attempts or corrupt evaluation states.
7. **Evaluation Pipeline:** MCQ auto-evaluation using server-side keys (keys never exposed to students); descriptive evaluation restricted to assigned faculty; mark modification audit logging.
8. **Result Lifecycle:** Distinct states (`DRAFT` $\rightarrow$ `REVIEWED` $\rightarrow$ `APPROVED` $\rightarrow$ `PUBLISHED`); unpublished results remain strictly hidden from students.
9. **Security Protections:** Password hashing, rate limiting on authentication, protection against OWASP Top 10 vulnerabilities (SQLi, XSS, CSRF, IDOR), and complete exclusion of secrets/passwords from audit logs.

---

## 4. Proposed Technical Decisions

The following architectural decisions are proposed based on `design.md` and standard best practices. These can be accepted as-is or modified during Chunk 01:

| Area | Proposed Decision | Rationale |
| :--- | :--- | :--- |
| **Monolith Architecture** | Modular Monolith (Django apps: `accounts`, `academics`, `students`, `faculty`, `enrollments`, `examinations`, `admit_cards`, `questions`, `attempts`, `evaluations`, `results`, `audit`) | Avoids unnecessary distributed systems complexity while keeping domain logic decoupled and maintainable. |
| **Authentication** | Session-based authentication via HTTP-only secure cookies (Django default with CSRF protection) for web SPA; token-ready for background/mobile API. | Eliminates XSS token exfiltration risks inherent to `localStorage` JWT storage. |
| **PDF Generation Engine** | `ReportLab` or `WeasyPrint` | `WeasyPrint` allows clean HTML/CSS templating for admit cards, while `ReportLab` is pure Python without OS-level pango/cairo dependencies. Recommendation: Start with `WeasyPrint` if system packages are supported, or `ReportLab` for zero-dependency portability. |
| **Background Processing** | Database-backed task queue (e.g., `django-q2` or `celery` with Redis) | Bulk PDF generation and email dispatch for hundreds of students will timeout a synchronous HTTP request. An asynchronous worker is essential for admit-card issuance. |
| **Audit Logging** | Centralized `AuditLog` table using Django signals or service-layer hooks recording `(user, action, target_model, target_id, changes_json, ip_address, timestamp)` | Ensures auditable paper trails for critical actions (enrollment edits, eligibility overrides, mark changes, result publishing). |

---

## 5. Missing Requirements

The following operational and technical requirements are not currently specified in `design.md` and should be addressed during system design:

1. **Student Account Provisioning:** How do students obtain accounts? Are they imported in bulk by administrators via CSV/Excel, or is there self-registration with an admin approval gate? (Recommendation: Admin bulk import to prevent unverified registrations).
2. **Descriptive Answer Format:** Can students only type text into the browser, or is handwritten paper photo/scan upload supported? (Note: Typing long answers, mathematical notations, or regional Indian language scripts like Assamese/Bengali can be challenging on mobile/laptop keyboards without LaTeX or image upload support).
3. **Grace Period for Network Latency:** When an exam timer expires, is there a server-side grace period (e.g., 60 seconds) to accept in-flight autosave requests delayed by transient network jitter?
4. **Student Photo & Signature on Admit Cards:** Does the college require a student photo and signature to be printed on the admit card? If yes, profile photo uploads must be supported in student records.
5. **Repeat / Backlog Enrollment Workflow:** How does a student in Semester 3 register for a backlog paper from Semester 1? Does the backlog paper map to the active session's Semester 1 offering, or a dedicated backlog offering?

---

## 6. Ambiguities Requiring User / College Confirmation

The following items involve academic policies or institutional rules that must not be invented by the AI agent:

1. **FYUGP Shared Offerings:** In FYUGP, can an AEC (e.g., Environmental Studies, English Communication) or VAC paper offering be shared across multiple programmes (e.g., both B.A. and B.Sc.), or must every programme have separate paper offerings?
2. **Examination Roll Number Structure:** Does the college follow a specific numbering format (e.g., `GU/2026/UG/<PROG>/<ROLL>` or an internal college convention), or should a configurable sequence generator with prefix/suffix formatting be provided?
3. **Exam Access Secret / PIN:** Does the student log in using only their regular account password, or is a unique one-time exam PIN printed on the admit card / emailed prior to the exam start required to open the paper?
4. **Grading & Pass Criteria:** Does the initial system require letter grades (O, A+, A, B+, B, C, P, F) and SGPA/CGPA calculation, or strictly raw marks (Component Marks + Total Marks) until the college formalizes its grade conversion table?
5. **Negative Marking & Sectional Cutoffs:** Are MCQs strictly positive marks, or must the system support configurable negative marking per question/exam?

---

## 7. Conflicts and Risks Analysis

| Conflict / Risk | Severity | Mitigation Strategy |
| :--- | :--- | :--- |
| **Synchronous Admit Card / Email Timeouts** | High | Generating 500+ PDFs and sending emails synchronously in an HTTP request will cause gateway timeouts. Must decouple via a background task worker. |
| **Autosave Race Conditions** | Medium | Rapid network reconnects could submit stale autosave payloads overwriting newer client state. Mitigate using monotonic revision/sequence numbers on answer payloads. |
| **Mobile Screen Constraints for Exams** | Medium | Students taking exams on mobile devices may face poor readability with complex layouts. Frontend design must be strictly mobile-responsive. |
| **Premature Hardcoding of Academic Rules** | High | Hardcoding Gauhati University subject combinations or credit structures will break if regulations shift. Keep all subject categories, credits, and offerings configurable in the database. |
| **Unauthenticated Admit Card Leakage** | High | If admit-card PDF URLs are predictable static files, students could view peers' cards. Mitigate using authenticated download endpoints checking user ownership and role. |

---

## 8. Recommended Decisions for Chunk 01

1. **Architecture Blueprint:** Proceed with a Django + DRF modular monolith backend and a React + Vite + Tailwind CSS SPA frontend.
2. **Database Engine:** MySQL 8.0 with InnoDB engine, enforcing strict foreign keys, unique constraints on `(student, paper_offering)` and `(student, examination)`, and explicit indexes on academic lookups.
3. **Session Authentication:** Use Django session cookies with HTTP-only, SameSite, and CSRF protection to defend against XSS-based token theft.
4. **Configurable Lookups:** Implement `SubjectCategory` (Major, Minor, MDC, AEC, SEC, VAC) as a database model rather than hardcoded Python enums.
5. **Raw Marks Baseline:** Implement raw component scoring (MCQ auto-marks + descriptive marks) for v1 results, while providing extension hooks for grade-point conversions once the college confirms the exact GU formula.

---

## 9. Questions Requiring User Approval

Before or during the Chunk 01 System Architecture phase, please provide guidance on the following:

1. **Student Provisioning:** Should student profiles and paper registrations be created via **Administrator CSV/Excel bulk upload**, or should student self-registration be allowed? *(Recommended: Admin bulk upload)*.
2. **Descriptive Answers:** Should descriptive questions support **strictly browser-typed text**, or should **handwritten answer photo/file uploads** be planned? *(Recommended: Typed text for initial MVP, with architecture accommodating file uploads)*.
3. **Exam Access PIN:** Should an exam require a **separate PIN** (printed on the admit card or released by the admin) in addition to logging in, or is standard student login sufficient to access eligible exams?
4. **Roll Number Convention:** Is there a preferred college roll number pattern, or should we implement a configurable pattern template (e.g., `PREFIX-YEAR-SEQUENCE`)?
5. **PDF Engine:** Do you approve using `WeasyPrint` (requires system cairo/pango) or pure-Python `ReportLab` for admit-card PDF generation?

---

## 10. Audit Status & Gate Sign-Off

* **Assigned Chunk:** Chunk 00 — Requirements Audit
* **Deliverable Created:** [`docs/audits/chunk-00-requirements-audit.md`](file:///home/zero/Documents/college/docs/audits/chunk-00-requirements-audit.md)
* **Design File Modified:** None (`design.md` preserved intact)
* **Code / Migrations Generated:** None
* **Final Chunk Status:** **PASS WITH WARNINGS**
  * *Pass:* The requirements, domain model, role permissions, and lifecycle states in `design.md` provide a solid, coherent foundation.
  * *Warnings:* Identified non-blocking academic policy questions (roll number format, student onboarding method, grading formulas, and descriptive upload preferences) must be confirmed during architecture and data design.

> **STOP:** Chunk 00 is complete. Per project rules, no work on Chunk 01 (System Architecture) will begin until explicit user approval is granted.
