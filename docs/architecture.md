# College Online Examination System — System Architecture Specification

**Project Context:** College Online Examination System (Gauhati University FYUGP Academic Context)  
**Document Status:** Architecture Baseline (Chunk 01)  
**Last Updated:** 2026-11-02  

---

## 1. Executive Summary & Architecture Principles

The College Online Examination System is designed as a secure, responsive, and robust **Modular Monolith**. It supports the Gauhati University Four-Year Undergraduate Programme (FYUGP under NEP 2020) academic hierarchy and examination lifecycle.

### Key Architectural Principles

1. **Modular Monolith over Microservices:** Single deployable codebase with strictly decoupled domain applications. Avoids the network latency, distributed transaction failures, and operational overhead of microservices while maintaining clean boundaries.
2. **Backend-Authoritative Integrity:** All business rules, eligibility calculations, countdown timers, autosave versioning, mark computations, and role permissions are strictly enforced on the server. The client is strictly an interactive view.
3. **Explicit Academic State:** No student is eligible for an examination based on programme, department, or semester alone. Eligibility strictly requires an active, approved enrollment in the exact paper offering being examined.
4. **Defense in Depth for Security & Privacy:**
   - Multi-tier authentication: Account credentials establish identity; separate, hashed Examination PINs authorize live exam sessions.
   - Private storage for all exam assets (admit cards, answer uploads); zero public URL access.
   - Monotonic versioning on autosave to prevent race conditions over unstable mobile connections.
   - Immutable audit logging for all administrative, eligibility, evaluation, and publishing events.

---

## 2. Technology Stack & Responsibilities

| Tier / Component | Technology | Role & Architectural Responsibilities |
| :--- | :--- | :--- |
| **Frontend SPA** | React 18+ / Vite | Single Page Application; responsive layouts for desktop/tablet/mobile; state management and client-side form validation. |
| **Styling & UI** | Tailwind CSS | Utility-first CSS framework; accessible, mobile-first design; dark/light examination contrast mode. |
| **Routing** | React Router v6+ | Client-side routing with role-based route guards (`AdminRoute`, `FacultyRoute`, `StudentRoute`, `ExamGuard`). |
| **Backend Framework**| Python 3.11+ / Django 5.x | Core monolith framework; ORM, migrations, user session management, signal dispatching, and security middleware. |
| **API Framework** | Django REST Framework (DRF) | RESTful API endpoints; serializers; object-level permissions; rate-limiting throttles; JSON API responses. |
| **Database** | MySQL 8.0 (InnoDB) | Relational persistence; ACID compliance; foreign key constraints; row-level locking (`SELECT ... FOR UPDATE`); transaction isolation. |
| **PDF Generation** | ReportLab (Pure Python) | Pixel-perfect admit-card generation; zero external OS library dependencies (no cairo/pango required); fast programmatic PDF rendering. |
| **Email Dispatch** | Django Mail + SMTP | Transactional email delivery with HTML templates and PDF attachments. |
| **Task Queue / Worker**| Celery + Redis (or DB Queue) | Asynchronous execution of bulk PDF admit-card generation, batch email dispatch, and background deadline supervisor. |
| **Web / App Server** | Nginx + Gunicorn | Reverse proxy handling SSL termination, static asset compression, and WSGI application serving. |

### Evaluation of Redis and Celery

* **Role:** Bulk operations in examination workflows—such as compiling 1,000 admit-card PDFs, sending 1,000 emails, or evaluating heavy batches—cannot run inside a synchronous HTTP request cycle without causing gateway timeouts (HTTP 504).
* **Architecture Decision:**
  * Celery with Redis broker is the designated background processing engine for batch jobs, cache-based rate limiting (PIN attempts), and exam session heartbeat tracking.
  * To maintain operational simplicity during initial development and CI/CD testing, task execution is abstracted through a unified interface (`TaskQueueService`), enabling synchronous eager execution (`CELERY_TASK_ALWAYS_EAGER = True`) in local test environments without requiring an active Redis server.

---

## 3. System Architecture Diagrams

### 3.1 High-Level System Architecture

```mermaid
flowchart TD
    subgraph ClientLayer ["Client Layer (Desktop / Tablet / Mobile)"]
        BrowserStudent["Student Browser (SPA)"]
        BrowserFaculty["Faculty Browser (SPA)"]
        BrowserAdmin["Administrator Browser (SPA)"]
    end

    subgraph GatewayLayer ["Gateway & Static Serving"]
        Nginx["Nginx Reverse Proxy & SSL"]
        StaticFiles["Static UI Assets (Vite Dist)"]
    end

    subgraph AppLayer ["Modular Monolith Application Layer (Django / DRF)"]
        APIAuth["Auth & Accounts Module"]
        APIAcademics["Academics & Enrollments"]
        APIExams["Examination & Eligibility Engine"]
        APIAttempts["Attempts & Autosave Engine"]
        APIEval["Evaluation & Results Engine"]
        APIPDF["ReportLab PDF Generator"]
    end

    subgraph AsyncLayer ["Background & Cache Tier"]
        RedisBroker["Redis (Cache & Message Broker)"]
        CeleryWorker["Celery Worker (Admit Cards / Emails / Auto-close)"]
    end

    subgraph DataLayer ["Data & Storage Layer"]
        MySQL[("MySQL 8.0 Database (InnoDB)")]
        PrivateMedia[("Private File Storage (Protected PDFs & Answer Uploads)")]
    end

    subgraph ExternalLayer ["External Services"]
        SMTPServer["College / Institutional SMTP Server"]
    end

    BrowserStudent -->|HTTPS / REST| Nginx
    BrowserFaculty -->|HTTPS / REST| Nginx
    BrowserAdmin -->|HTTPS / REST| Nginx

    Nginx -->|Static Requests| StaticFiles
    Nginx -->|API Requests /api/*| AppLayer

    AppLayer -->|Read / Write| MySQL
    AppLayer -->|Store / Retrieve Private Files| PrivateMedia
    AppLayer -->|Enqueue Background Tasks| RedisBroker
    AppLayer -->|Cache & Rate Limit| RedisBroker

    RedisBroker -->|Consume Tasks| CeleryWorker
    CeleryWorker -->|Read / Update| MySQL
    CeleryWorker -->|Write PDFs| PrivateMedia
    CeleryWorker -->|Dispatch Emails| SMTPServer
```

---

## 4. Frontend Architecture

### 4.1 Module Structure & Responsibilities

The React application is structured into domain-aligned modules:

```
frontend/src/
├── app/                  # Application bootstrap, routing configuration, global providers
├── assets/               # Logos, brand icons, styling variables
├── components/           # Shared UI primitives (Button, Modal, Input, Table, Alert, Badge)
├── hooks/                # Custom React hooks (useAuth, useExamTimer, useAutosave, useNetwork)
├── services/             # Axios API client, interceptors, and typed endpoint contracts
└── modules/
    ├── auth/             # Public self-registration, login, email verification, password reset
    ├── student/          # Student portal: profile, enrollment view, admit cards, results
    ├── exam-interface/   # Distraction-free live exam UI, question palette, answer inputs, timer
    ├── faculty/          # Faculty portal: assigned papers, descriptive script grading queue
    ├── admin-academics/  # Sessions, programmes, departments, semesters, subjects, paper offerings
    ├── admin-students/   # Student registration approvals, profile management
    ├── admin-enrollment/ # Student subject enrollment approvals & backlog records
    ├── admin-exams/      # Exam setup, eligibility computation, roll allocation, PIN management
    ├── admin-results/    # Result compilation, moderation review, and publishing controls
    └── admin-audit/      # System audit log viewer and security monitoring
```

### 4.2 Role-Based Route Guards

Client-side routes are guarded by high-order route wrappers:
* `PublicOnlyRoute`: Accessible only to unauthenticated users (`/login`, `/register`, `/forgot-password`).
* `ProtectedRoute`: Requires active authentication and verified account status.
* `RequireRole(['admin'])`: Enforces administrator role.
* `RequireRole(['faculty'])`: Enforces faculty role.
* `RequireRole(['student'])`: Enforces student role with `status == ACTIVE`.
* `LiveExamGuard`: Enforces active examination state; blocks navigation away without confirmation; disables distracting global layout navigation bars.

### 4.3 API Communication Layer & Security

* **Centralized API Client:** Axios instance configured with `withCredentials: true` to pass HTTP-only session cookies and CSRF tokens (`X-CSRFToken`).
* **Error Interceptor:** Automatically captures 401 (redirects to login with return path), 403 (insufficient permissions alert), and 429 (rate-limit warnings).
* **Network Resilience:** The exam interface tracks browser online/offline status (`navigator.onLine`). When offline, autosave actions queue in IndexedDB/localStorage and auto-flush immediately upon reconnection.

---

## 5. Backend Architecture & Domain Modules

### 5.1 Django Application Modules

```
backend/
├── manage.py
├── core/                 # Django settings, WSGI/ASGI, base models, global middleware
└── apps/
    ├── accounts/         # Custom User, authentication, session tokens, permissions
    ├── academics/        # Sessions, Programmes, Departments, Semesters, Subjects, PaperOfferings
    ├── students/         # StudentProfile, registration approvals, academic status
    ├── faculty/          # FacultyProfile, PaperAssignments
    ├── enrollments/      # StudentSubjectEnrollment, backlog management, approval workflow
    ├── examinations/     # Examination model, lifecycle states, scheduling, configurations
    ├── eligibility/      # Eligibility computation engine, overrides, snapshot tables
    ├── admit_cards/      # ReportLab PDF generation, roll-number allocation, download endpoints
    ├── pins/             # ExaminationPIN model, cryptographic generation, rate-limited validation
    ├── questions/        # Question banks, MCQ options, descriptive question rules
    ├── attempts/         # ExamAttempt, StudentAnswer (versioned), DescriptiveUpload
    ├── evaluations/      # Faculty script assignments, marks entry, remarks, locks
    ├── results/          # Result calculation, grade mapping hooks, approval & publication
    ├── notifications/    # Email queue, templates, SMTP dispatcher, retry engine
    └── audit/            # AuditLog model, signals, diff recording, change tracking
```

### 5.2 Frontend and Backend Module Communication

```mermaid
flowchart LR
    subgraph FrontendModules ["Frontend React Modules"]
        AuthUI["auth (Login / Register)"]
        StudentUI["student (Profile / Admit Cards / Scorecards)"]
        ExamLiveUI["exam-interface (Live Attempt & Autosave)"]
        FacultyUI["faculty (Grading Queue & Marking)"]
        AdminUI["admin-* (Academics / Exams / Users / Results)"]
    end

    subgraph BackendModules ["Backend Django REST Apps"]
        API_Accounts["accounts & students"]
        API_Academics["academics & enrollments"]
        API_Exams["examinations & eligibility"]
        API_Admit["admit_cards & pins"]
        API_Attempts["attempts & questions"]
        API_Eval["evaluations & results"]
        API_Audit["audit"]
    end

    AuthUI -->|/api/accounts/*| API_Accounts
    StudentUI -->|/api/students/*, /api/admit-cards/*| API_Accounts
    StudentUI -->|/api/results/my-results/| API_Eval
    ExamLiveUI -->|/api/pins/verify/, /api/attempts/*| API_Attempts
    FacultyUI -->|/api/evaluations/*| API_Eval
    AdminUI -->|/api/academics/*| API_Academics
    AdminUI -->|/api/examinations/*| API_Exams
    AdminUI -->|/api/admit-cards/*| API_Admit
    AdminUI -->|/api/audit/*| API_Audit
```

### 5.3 Backend Module Dependency Graph

```mermaid
flowchart TD
    accounts["accounts (Custom User & RBAC)"]
    academics["academics (Sessions, Programmes, Papers)"]
    students["students (Student Profiles)"]
    faculty["faculty (Faculty Profiles)"]
    enrollments["enrollments (Subject Registrations)"]
    examinations["examinations (Exam Configuration & Lifecycle)"]
    eligibility["eligibility (Eligibility Engine & Snapshot)"]
    pins["pins (Hashed Exam PINs)"]
    admit_cards["admit_cards (Roll Numbers & ReportLab PDFs)"]
    questions["questions (MCQs & Descriptive Items)"]
    attempts["attempts (Attempts, Autosave & Uploads)"]
    evaluations["evaluations (Marking & Remarks)"]
    results["results (Score Compilation & Publishing)"]
    notifications["notifications (Email Dispatcher)"]
    audit["audit (Audit Logging)"]

    students --> accounts
    faculty --> accounts
    students --> academics
    faculty --> academics
    accounts -.->|administrative membership (Proposed Table 53)| academics

    enrollments --> students
    enrollments --> academics

    examinations --> academics
    eligibility --> examinations
    eligibility --> enrollments

    admit_cards --> eligibility
    pins --> eligibility

    questions --> examinations
    attempts --> examinations
    attempts --> questions
    attempts --> students
    attempts --> pins

    evaluations --> attempts
    evaluations --> faculty
    results --> evaluations
    results --> examinations

    admit_cards --> notifications
    audit -.-> accounts
    audit -.-> examinations
    audit -.-> enrollments
    audit -.-> results
```

---

## 6. Authentication & Authorization Architecture

### 6.1 Account Authentication vs. Examination Authorization

A strict conceptual and technical boundary exists between **Identity Authentication** and **Examination Authorization**:

1. **Account Authentication (Who you are):**
   - Establishes identity via email/username and salted password hash.
   - Enforces user status: `PENDING_VERIFICATION`, `PENDING_APPROVAL`, `ACTIVE`, `INACTIVE`.
   - Issues secure HTTP-only session cookie.
2. **Examination Authorization (What you are allowed to enter):**
   - Having an active student account **does not** permit opening an examination.
   - Access requires fulfilling all five authorization gates:
     1. Account authenticated as Student with `status == ACTIVE`.
     2. Student exists in the locked `ExaminationEligibility` snapshot for this specific exam.
     3. Examination status is currently `LIVE` (or `SCHEDULED` during the configured early-access waiting room buffer).
     4. Entry Window Rules:
        - *New Attempt Initialization:* Permitted **only** when server time is within the configured entry window `[start_time, entry_cutoff_time]`. (During the early-access buffer `[start_time - early_access_buffer, start_time]`, PIN verification grants access strictly to the "Waiting Room / Instructions Hall"; question papers and attempt timers remain locked until `start_time`).
        - *Active Attempt Resumption:* Permitted **only** for attempts with `status == IN_PROGRESS` when server time is $\le \text{end\_time}$.
        - *Post-Deadline / Finalized Attempts:* Strictly prohibited. Attempts marked `SUBMITTED` or `AUTO_CLOSED_DEADLINE` are permanently locked.
     5. Correct, unrevoked, unexpired **Examination PIN** is supplied and verified against its salted hash.

### 6.2 Student Self-Registration & Approval Workflow

```mermaid
sequenceDiagram
    autonumber
    actor Student
    participant Frontend as React SPA
    participant Backend as Django /accounts
    participant DB as MySQL Database
    actor Admin as College Administrator

    Student->>Frontend: Fill Registration Form (Name, Email, Mobile, Reg No, Programme)
    Frontend->>Backend: POST /api/accounts/register/
    Backend->>DB: Create User (status=PENDING_VERIFICATION) & StudentProfile
    Backend-->>Student: Send Email Verification Link (Secure Token)

    Student->>Frontend: Clicks Verification Link in Email
    Frontend->>Backend: GET /api/accounts/verify-email/?token=...
    Backend->>DB: Update User (status=PENDING_APPROVAL)
    Backend-->>Frontend: Email Verified; Awaiting Admin Approval

    Admin->>Frontend: View Pending Student Registrations
    Frontend->>Backend: GET /api/admin/students/pending/
    Admin->>Frontend: Verify College Identity & Click "Approve"
    Frontend->>Backend: POST /api/admin/students/{id}/approve/
    Backend->>DB: Update User (status=ACTIVE, approved_by, approved_at)
    Backend-->>Student: Send "Account Approved" Welcome Email
    Student->>Frontend: Login with Email & Password -> Access Student Portal
```

### 6.3 Authentication and Examination PIN Verification Flow

```mermaid
sequenceDiagram
    autonumber
    actor Student
    participant SPA as React Student Portal
    participant AuthAPI as Django /accounts
    participant ExamAPI as Django /examinations & /pins
    participant DB as MySQL Database

    Student->>SPA: Enters Email & Password
    SPA->>AuthAPI: POST /api/accounts/login/
    AuthAPI->>DB: Verify Credentials & Active Status
    AuthAPI-->>SPA: HTTP 200 (Sets Secure Session Cookie)

    Student->>SPA: Selects Scheduled Examination
    SPA->>ExamAPI: GET /api/examinations/{id}/entry-check/
    ExamAPI->>DB: Check Eligibility Snapshot, Exam LIVE Status & Entry Cutoff Window
    ExamAPI-->>SPA: Status = READY_FOR_PIN (Prompts for PIN)

    Student->>SPA: Submits 6-character Examination PIN
    SPA->>ExamAPI: POST /api/examinations/{id}/verify-pin/ (PIN)
    ExamAPI->>DB: Check Lockout Counter (< 5 attempts) & Entry Window
    alt Hash Matches Stored Hash & Within Permitted Window
        ExamAPI->>DB: Reset Lockout Counter; Log Success
        ExamAPI-->>SPA: HTTP 200 (Issues Ephemeral Exam Session Token)
        SPA->>Student: Redirect to /student/exams/{id}/live (or Waiting Room if before start_time)
    else Invalid PIN (Failed Attempt)
        ExamAPI->>DB: Increment Lockout Counter (Lock if == 5)
        ExamAPI-->>SPA: HTTP 400 (Invalid PIN, Remaining Attempts: N)
        SPA->>Student: Display Error Alert with Remaining Attempts
    end
```

### 6.4 Institutional Administrator Membership & Multi-Tenancy Architecture (Option B — Proposed Architecture)

*Architecture Proposal: Option B (Dedicated Administrative Membership Mapping Table). Reconciled under Gate A for Project-Owner Review; Implementation Strictly Gated.*

To enforce multi-institutional isolation without coupling administrator identity to single colleges, the system proposes **Option B: Dedicated Administrative Membership Mapping Table** ([`Table 53 (Proposed): accounts_administrative_membership`](database-architecture.md#table-53-proposed-accounts_administrative_membership)) to expand the committed 52-table schema to 53 tables.

```mermaid
erDiagram
    accounts_user ||--o{ accounts_administrative_membership : "holds"
    academics_college ||--o{ accounts_administrative_membership : "governs"
    accounts_role ||--o{ accounts_administrative_membership : "authorizes"
```

#### 6.4.1 Cardinality & Mandatory Institutional Roles
1. **Multi-Tenancy Cardinality (M:N):** Administrators with primary role `ADMIN` in `accounts_user` may hold distinct administrative appointments across multiple colleges (e.g. cluster coordinators or nodal principals).
2. **Mandatory Institutional Role:** Each membership record requires an explicit `role_id BIGINT NOT NULL` referencing [`accounts_role(id)`](../backend/apps/accounts/models.py#L110-L130) (`COLLEGE_SUPERADMIN`, `EXAM_OFFICER`, `HEAD_EXAMINER`).
3. **Single Mutable Current-State Record:** A unique constraint on `(user_id, college_id)` enforces a single current-state record with status choices `ACTIVE`, `SUSPENDED`, or `REVOKED`. Historical assignment tenure and revocation reasons are retained on the row and permanently logged to Table 51 (`audit_system_audit_log`) under proposed Policy A.

#### 6.4.2 Two-Dimensional RBAC & Operation Registry
Authorization is evaluated across two orthogonal dimensions: Institutional Scope (`college_id`) and Operational Capability (`operation`).

```
+----------------------------------------------------------------------------------------------------+
| DOMAIN                             | OPERATIONAL CAPABILITY IDENTIFIER                             |
+------------------------------------+---------------------------------------------------------------+
| Student Management                 | student.registration.view, student.registration.review        |
|                                    | student.profile.view, student.profile.manage                  |
| Faculty Management                 | faculty.profile.view, faculty.account.provision               |
|                                    | faculty.profile.manage                                        |
| Academic Structure                 | academic.programme.view, academic.programme.manage            |
|                                    | academic.department.view, academic.department.manage          |
|                                    | academic.subject.view, academic.subject.manage                |
|                                    | academic.session.view, academic.session.manage                |
| Offerings & Assignments            | academic.offering.view, academic.offering.manage              |
|                                    | academic.faculty_assignment.view                              |
|                                    | academic.faculty_assignment.manage                            |
| Enrollment Records                 | enrollment.record.view, enrollment.record.manage              |
| Institutional Configuration        | academic.config.read, academic.config.manage                  |
| Administrative Membership          | admin.membership.view, admin.membership.manage                |
+----------------------------------------------------------------------------------------------------+
```

* **Unbypassable Evaluation Pipeline:** The centralized authorization service (`authorize_institutional_operation`) is designed to verify: (1) operation code type; (2) membership in the approved 25-operation registry; (3) actor authentication; (4) actor active status; (5) rejection of student/faculty accounts; (6) college existence and active status; (7) Superadmin scope for valid operations; (8) active membership matching `(actor, college_id)`; (9) assigned role resolution; (10) role permission check.
* **Fail-Closed Principle:** Unregistered or unknown operation codes raise `PermissionDenied` (HTTP 403) across all roles, including Superadmin.
* **Superadmin Scope:** `SUPERADMIN` accounts possess system-wide operational authority across all colleges for registered operations, but never bypass authentication, active account checks, or relational integrity constraints.
* **Operational Capability Restriction (Proposed Option B Policy):** Under the proposed Option B least-privilege policy, write capability for paper offerings (`academic.offering.manage`) is recommended to be restricted strictly to `SUPERADMIN` and `COLLEGE_SUPERADMIN`, while denying it to `EXAM_OFFICER` pending separate review of narrower coordination permissions. This operation-level restriction is part of the proposed Option B architecture and is not yet approved or enforced in application code; current academic CRUD services do not enforce operation-level checks, and institutional write authorization remains incomplete per Codex Finding F01.

#### 6.4.3 Strategy C Concurrency Architecture (Proposed Protocol)
Under the proposed **Strategy C: Outer Coordination Protocol with Preserved Internal Academic Lock Families**, administrative mutations are designed to adhere to a two-tier locking hierarchy:
1. **Level 1 (College Coordination Lock):** Acquired via `lock_colleges(*sorted_ids)` in deterministic ascending numeric primary-key order. Serializes mutations within the target college.
2. **Level 2 (User Row Locks):** All participating `accounts_user` rows are locked in ascending primary-key order (`SELECT ... FOR UPDATE`).
3. **Level 3 (Membership Row Locks):** Target `accounts_administrative_membership` rows are locked under the Level 1 coordination lock.
4. **Level 4 (Internal Domain Lock Families):** Dependent domain records (e.g. `PaperOffering`, `FacultyProfile`, `StudentProfile`) are locked following established domain hierarchy.
5. **Level 5 (Atomic Audit Log):** Membership mutations and Table 51 audit records commit within the same atomic transaction.

* **Revocation Race Serialization:** When a Superadmin revokes an administrator's membership concurrently with that administrator executing a mutation in the same college, the proposed protocol requires both transactions to compete for the Level 1 College Coordination Lock. If revocation commits first, the unblocked administrator's mutation revalidates membership status under lock, discovers `status == 'REVOKED'`, and fails closed with HTTP 403 Forbidden. Concurrency guarantees are conditional upon consistent implementation across all services and live MySQL verification. Deadlock freedom is not unconditionally guaranteed; deadlocks may occur under concurrent execution due to gap locks and index contention, requiring application-level retry handling.
* **Connection Isolation Level:** Django's MySQL connection ordinarily operates under `READ COMMITTED` or the database server default. The effective live MySQL connection isolation level remains unverified. Concurrency guarantees and transaction isolation behavior are subject to live MySQL 8 integration and deadlock testing. Mandatory deadlock retry recovery (MySQL error 1213) is designed for write paths.

#### 6.4.4 Academic Catalogue Read-Visibility Baseline
* **Catalogue Browsing Preservation:** Active authenticated students, faculty, and administrators have global read access to browse all paper offerings across colleges (`PaperOfferingViewSet` enforcing `IsAcademicAdminOrReadOnly` with `queryset.all()`). This enables university-wide course discovery, minor elective selection, and multidisciplinary planning under FYUGP. Read-only catalogue browsing visibility remains unchanged.
* **Mutation Scoping & Security Boundary:**
  - **Intended Institutional Requirement:** The intended institutional security architecture requires that write mutations (create, update, delete) on college-bound academic records, including paper offerings, be strictly restricted to administrators authorized for the record's host college.
  - **Proposed Option B Policy:** Under the proposed Option B architecture, this requirement is modeled via the `academic.offering.manage` operational capability within the 25-operation registry, restricted to `SUPERADMIN` and `COLLEGE_SUPERADMIN`. This operational policy is proposed and pending formal owner approval; it is not yet approved or implemented.
  - **Current Runtime Status (Codex Finding F01):** Implemented academic CRUD APIs (`BaseAcademicViewSet`, `PaperOfferingViewSet`) do not consistently enforce college-scoped write checks; ordinary administrators can mutate academic records across colleges via HTTP. Codex F01 remains **P1 HIGH — CONFIRMED — UNRESOLVED** in application code.
  - **Gate B Remediation Pending:** Gate B implementation remediation has not been executed or authorized. Institutional write authorization remains an open security defect until Gate B is formally authorized and implemented.

#### 6.4.5 Durable Administrative Audit Prerequisite (Policy A — RECOMMENDED — OWNER SELECTION PENDING)
* Under proposed Policy A, Table 51 ([`audit_system_audit_log`](database-architecture.md#table-51-audit_system_audit_log), planned in Domain I / Chunk 14) is designed as a mandatory transactional audit sink for production administrative membership lifecycle mutations. Both Table 51 and Table 53 remain explicitly unimplemented in application models and database migrations.
* Application-level membership state transitions and Table 51 audit records are designed to commit atomically in the same database transaction; failure to record the audit entry aborts the mutation. Relational audit logging provides database-tier auditability and tamper resistance against application-tier compromise; database-level DBA modifications remain bounded by database engine controls, and relational audit logging does not by itself constitute cryptographic non-repudiation.

#### 6.4.6 Institutional Authorization Defect & Interim Security Boundary (Codex Finding F01)
* **Status:** P1 HIGH — CONFIRMED — UNRESOLVED (Application code).
* **Defect Description:** In Chunk 05, academic ViewSets (`BaseAcademicViewSet`, `ProgrammeViewSet`, `InstitutionalConfigViewSet`) enforce only global role checks (`IsAcademicAdminOrReadOnly`) without verifying college ownership. While `accounts.authorization.get_actor_authorized_college_ids` fails closed (`set()`) for ordinary administrators, the academic APIs do not consistently invoke or enforce it, allowing ordinary administrators to modify academic records across institutions via direct API calls.
* **Governance & Remediation:** Institutional write security remains incomplete in the current codebase. Implementation code remains untouched under Gate A. A targeted, fail-closed write check must be authorized and implemented under Gate B prior to production deployment.

---

## 7. Academic Workflow Architecture

### 7.1 Configurable Academic Hierarchy (FYUGP NEP 2020)

The academic structure is purely data-driven, avoiding hardcoded assumptions:

* `College`: Top-level institution.
* `AcademicSession`: e.g., `2024-2025`, `2025-2026`, `2026-2027` (with active flags).
* `Programme`: e.g., `B.A. (FYUGP)`, `B.Sc. (FYUGP)`, `B.Com. (FYUGP)`, `B.C.A.`.
* `Department`: e.g., `Department of Political Science`, `Department of Chemistry`.
* `Semester`: Configurable semesters (1 through 8).
* `SubjectCategory`: Configurable database model (e.g., `Major`, `Minor`, `MDC`, `AEC`, `SEC`, `VAC`).
* `Subject`: Broad academic discipline (e.g., `Political Science`, `Mathematics`).
* `PaperOffering`: Exact academic unit offered in a given session and semester:
  - `paper_code`: e.g., `POL1014`, `VAC1012`.
  - `title`: e.g., `Foundations of Political Theory`, `Environmental Studies`.
  - `category`: Linked to `SubjectCategory`.
  - `credits`: Configurable integer/float.
  - `is_common_paper`: Boolean flag allowing papers like AEC/VAC to enroll students from multiple programmes.

### 7.2 Student Subject Enrollment & Historical Preservation

```mermaid
flowchart TD
    Student["Student (Active Profile)"]
    Admin["Admin / Faculty Advisor"]
    Session["Academic Session (e.g. 2026-2027)"]
    Paper["Paper Offerings for Semester"]

    Student -->|Selects Papers in Portal| DraftEnrollment["Draft Subject Enrollment"]
    DraftEnrollment -->|Submits Selection| SubmittedEnrollment["Submitted Enrollment"]
    Admin -->|Verifies Eligibility & Rules| ApprovalAction{"Admin Review"}
    ApprovalAction -->|Approved| ApprovedEnrollment["Approved Enrollment (Active Record)"]
    ApprovalAction -->|Rejected| RejectedEnrollment["Rejected (Returned to Student with Remarks)"]

    ApprovedEnrollment --> HistoricalLog[("Historical Academic Ledger (Immutable Snapshots)")]
    HistoricalLog -.->|Future Backlog Reference| BacklogLink["Backlog / Repeat Registration Tracking"]
```

---

## 8. Examination Workflow Architecture

### 8.1 Complete End-to-End Examination Lifecycle

```mermaid
flowchart TD
    Step1["1. Admin Creates Examination (Title, Type, Date, Duration, Marks)"]
    Step2["2. Admin Links Exact Paper Offering"]
    Step3["3. Eligibility Engine Computes Registered Students"]
    Step4["4. Admin Reviews & Locks Confirmed Eligibility Snapshot"]
    Step5["5. Roll Number Service Allocates College-Format Numbers"]
    Step6["6. Admit Card Service Generates ReportLab PDFs"]
    Step7["7. Notification Service Dispatches Admit Cards via Email"]
    Step8["8. Student Logs into Student Portal"]
    Step9["9. Student Provides Separate Examination PIN"]
    Step10["10. Backend Verifies PIN, Eligibility, Exam Status & Time Window"]
    Step11["11. Student Starts Exam Attempt (Server Authoritative Clock)"]
    Step12["12. Answers Autosaved with Monotonic Version Sequences"]
    Step13["13. Descriptive Files Uploaded to Private Storage"]
    Step14["14. Student Submits or Server Auto-Closes at Deadline"]
    Step15["15. MCQ Auto-Evaluation & Faculty Descriptive Evaluation"]
    Step16["16. Admin Reviews, Approves & Publishes Results"]

    Step1 --> Step2 --> Step3 --> Step4 --> Step5 --> Step6 --> Step7
    Step7 -.-> Step8 --> Step9 --> Step10 --> Step11 --> Step12 --> Step13 --> Step14 --> Step15 --> Step16
```

### 8.2 Failure & Recovery Paths

1. **Network Drop During Examination:**
   - Client stores unsaved keystrokes in a local encrypted IndexedDB cache (`exam_cache_{student_id}_{examination_id}_{attempt_id}`), protected via AES-256-GCM.
   - Client-supplied timestamps are **never trusted** by the server as proof of pre-deadline completion.
   - Autosave worker retries every 10 seconds with exponential backoff while connection is down.
   - UI displays clear persistent status banner: `⚠️ Offline - Changes cached locally (Encrypted)`.
   - **Conflict-Free Lifecycle & Shared-Device Isolation:** Unsynchronized answers are **never silently deleted** prior to explicit server acknowledgement; user logout does **not** purge unsynchronized data. Cryptographic isolation (AES-256-GCM using keys inaccessible across sessions) ensures subsequent users on the same workstation cannot inspect, decrypt, or tamper with another candidate's cached answers.
   - On reconnect prior to the official deadline (`end_time`), pending changes flush to the server with sequence numbers; write acceptance is determined strictly by the server's authoritative ingress timestamp ($T_{\\text{ingress}} \le \text{official\_end\_time}$). UI displays `✅ All answers saved`.
   - If network reconnects *after* the official deadline, any answers cached offline cannot be accepted for write. The server rejects them with HTTP 410 (`EXAMINATION_CLOSED`), and the client marks them locally as `REJECTED_DEADLINE_EXCEEDED` (preserved in a diagnostic recovery bundle for administrative appeal, but never treated as synchronized). The attempt is closed based strictly on the valid answers received by the server on or before `end_time`.
2. **Accidental Tab Close / System Restart:**
   - Student navigates back to exam URL.
   - **During Active Exam Window (Server Time $\le \text{end\_time}$):** Backend recognizes active `ExamAttempt` (`status == IN_PROGRESS`). In-memory Data Encryption Key (DEK) is securely restored via **Live Examination Key Recovery** over TLS after verifying student identity, active attempt ownership, session token validity, and deadline compliance. Countdown timer reflects remaining server time; previously saved answers load immediately into the UI.
   - **After Examination Deadline (Server Time $> \text{end\_time}$ or Finalized):** Attempt cannot be resumed for answering. The student can access the **Post-Deadline Read-Only Evidence Recovery** workflow to restore the DEK strictly in read-only mode, decrypt locally preserved unsynchronized answers, and export an `AUDIT_RECOVERY_BUNDLE` for formal grievance appeal.
   - *(Note: Encrypted cached answers are temporarily inaccessible while the workstation remains completely offline until server re-authentication succeeds; no examination credentials or short PINs are stored locally as wrapping secrets).*
3. **Deadline Reached & Bounded-Processing Consistency Enforcement:**
   - The official examination deadline (`end_time`) is strictly server-authoritative and marks the absolute cutoff for answering questions.
   - Write requests (autosave updates and manual submissions) are accepted **only** when their authoritative ingress timestamp ($T_{\text{ingress}}$ evaluated via Nginx `$msec`, or fallback WSGI ingress in dev/test only) is $\le \text{official\_end\_time}$.
   - Requests first received after `end_time` are rejected for write, regardless of any client-side claims or offline timestamps.
   - **Zero Premature Finalization by Late Requests:** A rejected late request (autosave or manual submission arriving with $T_{\text{ingress}} > \text{official\_end\_time}$) **never** transitions an attempt to `AUTO_CLOSED_DEADLINE` and **never** triggers MCQ evaluation. The attempt status remains unchanged (`IN_PROGRESS`), preserving processing eligibility for any earlier on-time requests still queued in socket backlogs.
   - **Authoritative Deadline Auto-Closure Protocol:** Deadline finalization is performed strictly by the background deadline supervisor worker (`evaluate_examination_deadline_closure`) after the bounded processing drain window has elapsed ($\text{server\_time} \ge \text{official\_end\_time} + \Delta_{\text{drain}}$, where $\Delta_{\text{drain}} = 15\text{s}$). A valid on-time manual submission may independently transition the attempt to `SUBMITTED` under its own row-lock transaction.
   - All write operations and deadline finalization serialize strictly on the database row lock (`SELECT ... FOR UPDATE` on `ExamAttempt`). Requests admitted before finalization commit cleanly (HTTP 200). If extreme queueing delays admission past finalization, the request is rejected with HTTP 410 (`WRITE_REJECTED_FINALIZATION_COMPLETED`), and the payload is preserved in the client's local recovery bundle (`AUDIT_RECOVERY_BUNDLE`) for grievance appeal.
   - Once finalized, attempt status transitions to `AUTO_CLOSED_DEADLINE` (or `SUBMITTED`), with `submitted_at = T_ingress` for on-time submissions and `closed_at = official_end_time` for deadline auto-closures, while recording `transaction_recorded_at` during the database transaction. All subsequent write APIs strictly reject modifications (HTTP 410).
4. **Email Delivery Failure:**
   - Failed email attempts are captured in `AdmitCardEmailQueue` with error message.
   - Admin monitor displays failed records; provides single-click "Retry Failed Emails" batch action.
   - Students can always directly download their admit card from their authenticated student portal.
---

## 9. Examination PIN Design & Security

### 9.1 PIN Architecture & Generation

* **Scope & Uniqueness:** A unique, cryptographically random Examination PIN is generated per student per examination (`(examination_id, student_id)` unique constraint).
* **Generation Strategy (CSPRNG):** Generated using Python's `secrets` module (`secrets.choice` utilizing system OS entropy `/dev/urandom`), producing a 6-character alphanumeric string. Ambiguous glyphs (e.g., `0`, `O`, `1`, `I`, `l`) are explicitly excluded from the character alphabet to prevent transcription errors.
* **Storage & Hashing:** Plaintext PINs are **never stored** in the database. PINs are hashed immediately upon generation using Django's standard password-hashing framework (`PBKDF2PasswordHasher` with SHA-256 and unique per-record salt, or Argon2). Plaintext is held in memory only during immediate admit card rendering or email dispatch, and discarded immediately.
* **Separation from Roll Number:** The Roll Number is an institutional public identifier displayed on admit cards, attendance rosters, and answer script metadata. The Examination PIN is a confidential authentication secret required solely to unlock the live exam interface.

### 9.2 Verification, Session Creation, and Resumption

* **Session Creation vs. Non-Consumption:**
  - Successful PIN verification **does not consume or destroy** the PIN during an active examination.
  - Consuming the PIN on first entry would prevent students from recovering from common real-world disruptions (accidental browser tab closure, browser crashes, system reboots, or network disconnects).
  - Upon successful PIN verification, the backend issues an authorized, time-bound, cryptographically signed **Examination Session Token** (or secure HTTP-only cookie) scoped specifically to `(student_id, examination_id, attempt_id)`.
  - The PIN remains valid for session re-entry and attempt resumption throughout the examination's active window (`start_time` to `end_time`).
  - Once the attempt is transitioned to `SUBMITTED` (manual submission) or `AUTO_CLOSED_DEADLINE` (deadline expiration), the attempt is locked permanently; subsequent PIN entries are rejected.
* **Reconciled Validity Windows:**
  - *New Attempt Initialization Window:* The PIN is valid to initialize a new examination attempt **only** from `start_time` up to the examination's configured `entry_cutoff_time` (e.g., `start_time + 15m` or `start_time + 30m`, which can never exceed `end_time`). After `entry_cutoff_time`, new attempt initialization is rejected (HTTP 403 `ENTRY_WINDOW_CLOSED`).
  - *Early-Access Buffer (`start_time - early_access_buffer` to `start_time`):* Students may verify their PIN early (default: 15 minutes before start) to authenticate and enter the virtual "Waiting Room / Instructions Hall". However, question payloads are withheld and attempts cannot be started until server time reaches `start_time`.
  - *Attempt Resumption Window:* For students with an already-started `IN_PROGRESS` attempt, PIN verification permits session resumption until `end_time`.
  - *Strict Expiration at Deadline:* PIN validity for all attempts **strictly expires at `end_time`**. Under **no circumstances** does the PIN authorize a new attempt or grant write access after the official examination deadline.

### 9.3 Rate Limiting, Failed Attempts, and Lockout Policy

* **Proposed Lockout Policy (Subject to Institutional Security Review):**
  - Verification requests are rate-limited per student per examination attempt.
  - **Threshold:** Maximum of 5 consecutive failed PIN attempts.
  - **Lockout Action:** On the 5th failed attempt, the PIN is locked for 15 minutes, and an alert entry is written to `AuditLog`.
  - **Progressive Backoff:** Subsequent failures after the initial lockout period trigger progressive exponential lockouts (e.g., 30 minutes).
  - *Institutional Review Note:* This policy is proposed as a security baseline; the college administration may review and adjust the attempt threshold or lockout duration during final operational sign-off.

### 9.4 Administrator Reissue & Revocation Workflow

* **Revocation & Emergency Reissue:**
  - If a student is locked out due to repeated failures, suspects PIN compromise, or loses access, a college administrator can reissue the PIN from the Admin Examination Dashboard.
  - The re-issue operation:
    1. Marks the existing `ExaminationPIN` record as revoked (`is_revoked = True`).
    2. Generates a fresh cryptographically random PIN and stores its salted hash.
    3. Records an immutable entry in `AuditLog` capturing `administrator_id`, `student_id`, `examination_id`, timestamp, and administrative justification.
    4. Provides the new PIN to the administrator for direct delivery or triggers a secure notification to the student.

### 9.5 Protection Against Disclosure in Logs & APIs

* **Zero Plaintext Logging:** Plaintext PINs are strictly excluded from Django application logs, web server access logs (via `POST` body submission, never URL parameters), and `AuditLog` change payloads.
* **API Protection:** No API endpoint ever exposes stored PIN hashes or plaintext PINs. Verification endpoints return only boolean verification status and ephemeral session tokens.

### 9.6 PIN Delivery Channels & Security Implications

The delivery mechanism for Examination PINs presents operational and security trade-offs that require explicit institutional configuration:

| Delivery Option | Operational Mechanism | Security Implications & Trade-offs |
| :--- | :--- | :--- |
| **Option A: Printed on Admit Card** | PIN is rendered on the downloadable/emailed admit card PDF alongside candidate details. | **Advantage:** Guarantees offline availability in the exam hall; zero reliance on network or SMS infrastructure on exam day.<br>**Implication:** Admit cards are distributed days in advance. Anyone with access to the student's email, printed paper, or shared cyber-cafe computer gains knowledge of the PIN. While backend rules strictly block exam entry before `start_time`, advance PIN exposure removes just-in-time confidentiality.<br>**Mitigation:** Admit cards must be served exclusively via authenticated, private download endpoints. |
| **Option B: Just-In-Time Separate Delivery** | PIN is distributed 15 minutes before exam start via SMS blast, portal notification, or verbal announcement by invigilators in the hall. | **Advantage:** Maximizes live confidentiality; eliminates risk of advance credential leakage.<br>**Implication:** High dependency on real-time telecommunications and student connectivity on exam morning; potential operational bottlenecks if SMS deliveries fail. |

* **Mandatory Institutional Configuration Gate:**
  - The delivery method is **NOT defaulted** to `ADMIT_CARD` or any other option.
  - It is an **explicit institutional configuration decision** (`EXAM_PIN_DELIVERY_METHOD`), initialized as `UNCONFIGURED`.
  - The system **strictly prevents PIN generation and examination scheduling** until the college administrator explicitly selects, configures, and approves the delivery method for the institution or examination.

---

## 10. Roll-Number Architecture

### 10.1 Configurable Format Generator (Illustrative Only)

> [!IMPORTANT]
> The pattern below is **strictly illustrative** to demonstrate the generator's template architecture. It is **not** an approved college format or an authoritative system default. The actual roll-number format must be configured by college administrators once the official Gauhati University or institutional convention is supplied.

The roll-number engine is completely configurable and avoids any hardcoded numbering conventions:

```python
# Conceptual Roll Number Template Engine
class RollNumberScheme(models.Model):
    name = models.CharField(max_length=100) # e.g. "College FYUGP Examination Format"
    # Illustrative pattern only; fully configurable with parameters:
    # {COLLEGE_CODE}, {YEAR}, {SESSION}, {PROG_CODE}, {DEPT_CODE}, {SEMESTER}, {SEQUENCE:04d}
    pattern = models.CharField(
        max_length=255, 
        help_text="Customizable pattern template using dynamic parameters"
    )
    sequence_start = models.PositiveIntegerField(default=1)
    current_sequence = models.PositiveIntegerField(default=1)
    scope = models.CharField(max_length=50, choices=[
        ('PER_EXAM', 'Per Examination Instance'),
        ('PER_SESSION_PROGRAMME', 'Per Academic Session and Programme'),
        ('PER_COLLEGE_ANNUAL', 'College-Wide Annual Sequence')
    ])
```

### 10.2 Concurrency, Uniqueness & Administration

* **Transaction-Safe Atomic Sequence Allocation:** Roll numbers are allocated in bulk during the transition from `ELIGIBILITY_REVIEW` to `READY`. Allocation runs inside an atomic database transaction using row-level locking (`SELECT ... FOR UPDATE` on the `RollNumberScheme` sequence counter) to guarantee sequential ordering without duplicate sequence gaps or collisions.
* **Database Integrity Constraints:** Database-level composite unique constraint enforces uniqueness:
  - Scoped to `(examination_id, roll_number)` or `(academic_session_id, roll_number)` depending on the configured scheme scope.
* **Administrator-Controlled Corrections & Re-issues:**
  - If a student is added late (manual eligibility addition) or an allocation error occurs, administrators can re-allocate or manually assign a corrected roll number.
  - Manual overrides require an administrative justification note and generate an immutable record in `AuditLog` preserving the previous number, the new number, and the authorizing administrator.
* **Historical Immutability:** Once admit cards are compiled and published, the roll-number mapping is locked permanently for that examination attempt to preserve historical examination records.

---

## 11. Descriptive Answer Upload Architecture

### 11.1 Configurable Upload Policies (Provisional Defaults)

> [!NOTE]
> The thresholds below represent **provisional system defaults** designed for general mobile network feasibility. All parameters are stored as configurable database settings and may be customized per examination or institutional policy.

* **File Count Limit:** Provisional default of maximum 3 files per descriptive question (configurable).
* **File Size Limit:** Provisional default of maximum 5 MB per individual file (configurable).
* **Total Upload Quota:** Configurable per attempt (provisional default: 50 MB total across all questions).
* **Allowed File Types:** Configurable extension whitelist (provisional default: `.pdf`, `.jpg`, `.jpeg`, `.png`).

### 11.2 Security & Storage Pipeline

```mermaid
sequenceDiagram
    autonumber
    actor Student
    participant SPA as React Exam Interface
    participant API as Django /attempts/upload/
    participant AV as Malware Scanner (ClamAV Hook)
    participant Disk as Private Media Storage
    participant DB as MySQL Database

    Student->>SPA: Selects Image / PDF of Handwritten Sheet
    SPA->>SPA: Client Check: Extension & Provisional Size (< 5MB)
    SPA->>API: POST /api/attempts/{id}/questions/{qId}/upload/ (Multipart)
    API->>API: Verify Exam is LIVE, Attempt is IN_PROGRESS, Time < Deadline
    API->>API: Server Check: File Extension, MIME-Type & Magic Byte Signatures
    opt Malware Scanning Enabled
        API->>AV: Stream File Stream to ClamAV Daemon
        AV-->>API: Scan Result (Clean / Infected)
    end
    API->>API: Sanitize & Generate Random UUID Filename (e.g. 7c9e6679-7425-40de.pdf)
    API->>Disk: Write File to private/descriptive_uploads/{exam_id}/{attempt_id}/
    API->>DB: Create DescriptiveUpload (student_id, attempt_id, question_id, file_path)
    API-->>SPA: Return Upload Success & Secure Thumbnail Link
```

### 11.3 Multi-Tier Validation & Malware Protection

1. **Client-Side Preliminary Validation:** React exam interface validates file extension and size prior to network transmission, providing immediate student feedback without wasting uplink bandwidth.
2. **Server-Side Whitelist Enforcement:** File extension is checked against the active examination configuration whitelist.
3. **MIME-Type & Magic-Byte Signature Inspection:** Using binary signature inspection (`python-magic` or header byte analysis), the server verifies the actual binary content matches legitimate PDF, JPEG, or PNG formats, rejecting renamed executable binaries, PHP scripts, or shell payloads.
4. **Pluggable Malware Scanning Interface:** The architecture provides a pluggable antivirus hook (supporting ClamAV daemon via TCP/Unix socket). When enabled in production, files are streamed to the scanner before committing to disk; infected files are discarded immediately and logged in `AuditLog`.

### 11.4 Private Storage & Controlled Access

* **Private Storage Outside Webroot:** Stored in `MEDIA_ROOT/private/descriptive_uploads/{exam_id}/{attempt_id}/`. Web server configurations explicitly block direct URL alias access to this path.
* **Randomized UUID Filenames:** Original client filenames (which may contain path traversal characters or malicious naming) are stripped; files are saved exclusively as `uuid4()` identifiers.
* **Authenticated Download Endpoint:**
  - `GET /api/attempts/{attempt_id}/uploads/{upload_id}/download/`
  - Access is granted **only** if:
    1. Caller is the authenticated student who owns the attempt, OR
    2. Caller is the faculty examiner assigned to evaluate this paper offering, OR
    3. Caller is an authorized college administrator.
  - In production, files are delivered efficiently via Nginx `X-Accel-Redirect` (or Django `FileResponse` in development), eliminating Python memory overhead.

### 11.5 Retention & Archival Policy Considerations

* **Active Retention:** Uploads must be retained in active high-performance storage throughout the live examination, evaluation, result compilation, and re-evaluation appeal windows (typically 6 months post-publication).
* **Archival vs. Purging:** Following the expiration of the appeal period, the system supports an automated archival job to bundle scripts into compressed cold storage or permanently purge files per college statutory document retention regulations. Specific retention schedules require institutional policy confirmation.

---

## 12. PDF & Email Architecture (ReportLab)

### 12.1 Admit-Card Generation with ReportLab

* **Engine:** Pure Python `reportlab.platypus` (Canvas, SimpleDocTemplate, Table, Paragraph, Image).
* **Zero System Dependencies:** Does not require OS-level `libpango`, `libcairo`, or fontconfig packages.
* **Layout Structure:**
  - Header: College Emblem, College Name, Examination Title, Academic Session.
  - Candidate Details: Student Name, Examination Roll Number, University Reg/Enrollment No, Programme & Semester.
  - Paper Schedule Table: Paper Code, Paper Title, Category, Exam Date, Timing, Reporting Time.
  - Instructions: Candidate instructions, permitted materials, examination PIN and access guidelines.
  - Verification Box: Barcode/QR code of roll number, signature of Controller of Examinations.

### 12.2 Background Email Delivery

```mermaid
flowchart LR
    Admin["Admin Triggers 'Email Admit Cards'"] --> Celery["Celery Task Enqueued"]
    Celery --> DBQueue["AdmitCardEmailQueue (Status: PENDING)"]
    DBQueue --> Worker["Worker Processes Batch"]
    Worker --> ReportLab["Generate / Load PDF"]
    Worker --> SMTP["Dispatch via SMTP"]
    SMTP -->|Success| Sent["Status: SENT (Timestamp Logged)"]
    SMTP -->|Failure| Fail["Status: FAILED (Error Logged, Retry Incremented)"]
```

---

## 13. Examination Reliability & Integrity Architecture

### 13.1 Server-Authoritative Timer & Conservative Ingress Deadline Policy

* **Zero Trust in Client Timestamps:**
  - Client/browser timestamps are **never trusted** by the server as proof that an answer was entered or submitted before the deadline. A compromised client, manipulated system clock, or modified script could trivially forge pre-deadline timestamps.
  - The server's clock and trusted network gateway timestamps strictly govern all deadlines.
* **Request Ingress Pipeline & The Six Lifecycle Stages:**
  To ensure absolute technical rigor and eliminate false concurrency assumptions, the architecture distinguishes the **six distinct stages** of the request and data lifecycle:
  1. *Physical Network Arrival:* The client's TCP packets arrive at the physical host network interface card (NIC) and are buffered in the Linux operating system kernel socket queue.
  2. *Perimeter Timestamp Evaluation ($T_{\text{ingress}}$):* The Nginx worker event loop (`epoll`) wakes up, reads the HTTP request line and headers from the socket, and evaluates `$msec` as the trusted perimeter ingress timestamp.
  3. *Complete HTTP Request Receipt:* Nginx fully ingests and buffers the complete HTTP request body from the client (governed by `client_body_timeout 10s`). A request is not forwarded upstream until headers and body are fully received.
  4. *Application Admission ($T_{\text{admit}}$):* The Gunicorn worker process accepts the connection from the upstream Unix socket backlog, parses the WSGI environment, and dispatches the request into the Django application middleware.
  5. *Database Transaction Execution:* Django view logic executes, begins an atomic database transaction, and acquires an exclusive row lock on the `ExamAttempt` record (`SELECT ... FOR UPDATE`).
  6. *Successful Durable Commit:* The MySQL InnoDB transaction commits, flushing the write-ahead log (WAL / redo log) to persistent storage, establishing durable persistence.

* **Critical Architectural Clarification on Ingress Timestamps:**
  - A timestamp evaluated at Stage 2 ($T_{\text{ingress}}$) represents perimeter receipt time; it **does NOT** guarantee application admission (Stage 4) or durable commit (Stage 6).
  - If a worker crashes, the connection drops, or upstream socket backlogs exceed the processing window, an on-time timestamp alone cannot force a database write.
  - The architecture therefore adopts **Option B: Bounded-Processing Consistency**.

* **Semantics and Technical Limitations of Nginx `$msec`:**
  - In Nginx, `$msec` evaluates to the current time in seconds with millisecond resolution (`time_t sec + msec`) obtained from Nginx's internal cached time structure, which is updated on each event loop iteration via `ngx_time_update()` (derived from `gettimeofday()`).
  - **Limitations:**
    - It is **not** an operating system kernel-level network packet arrival timestamp (unlike Linux socket options `SO_TIMESTAMPING` / `SO_TIMESTAMPNS`, which require dedicated C-level socket modules not provided in standard Nginx distributions).
    - Under heavy load, worker event loop latency, or TLS handshake queueing, `$msec` represents the time when Nginx evaluated the variable during request header processing, which can lag slightly behind physical packet arrival on the wire.
    - **Architecture Stance:** The system explicitly acknowledges this limitation. It does **not** claim `$msec` is an absolute physical packet arrival guarantee. Instead, it defines $T_{\\text{ingress}}$ as the earliest practical software-evaluated ingress timestamp achievable in a standard Linux/Nginx web stack.
* **Technically Defensible Production Cutoff Mechanism ($T_{\\text{ingress}}$):**
  - **Unified Timestamp Definition:** The authoritative ingress timestamp ($T_{\\text{ingress}}$) is defined as:
    $$T_{\\text{ingress}} = \\begin{cases} T_{\\text{proxy\_eval}} \\ (\\text{Nginx } \$msec) & \\text{when request arrives via validated trusted proxy} \\\\ T_{\\text{wsgi\_ingress}} \\ (\\text{Middleware } \\text{time.time()}) & \\text{in direct/fallback environments} \\end{cases}$$
  - **Ingress Header Overwrite:** Nginx is explicitly configured as the sole external ingress point and unconditionally overwrites any incoming client-supplied header:
    ```nginx
    # Unconditionally overwrite any client-supplied header with high-precision proxy evaluation time
    proxy_set_header X-Request-Arrival-Time $msec;
    ```
  - **Trusted Proxy Verification:** The backend application (Django custom middleware) accepts `HTTP_X_REQUEST_ARRIVAL_TIME` **strictly** when `request.META['REMOTE_ADDR']` originates from a pre-configured trusted proxy IP or CIDR block (e.g., `TRUSTED_PROXIES = ['127.0.0.1', '10.0.0.0/8']`). Forwarded arrival headers from untrusted clients or unverified proxies are strictly ignored and stripped.
  - **Direct Backend Access Restrictions:** Gunicorn is strictly bound to a local Unix domain socket (`/run/gunicorn.sock` with file mode `0660` owned by `www-data:www-data`), or bound exclusively to `127.0.0.1` with host firewall rules (`ufw` / `iptables`) dropping external traffic to port 8000. Direct access bypassing Nginx is architecturally prohibited.
  - **Clock Synchronization & Skew Considerations:**
    - Host system clocks are synchronized via `chrony` or `systemd-timesyncd` with local/regional NTP stratum-1/2 servers, maintaining target clock drift $\\pm 10\\text{ to }50\\text{ ms}$.
    - Because Nginx and Gunicorn reside on the same server (or within a tightly synchronized local container network), inter-service clock skew between proxy and backend is eliminated or negligible.
  - **Mandatory Production Security Control & Fail-Closed Behavior:**
    In production deployments, trusted ingress timestamping is a mandatory security control. If an incoming write request (`/api/attempts/*/answers/`, `/api/attempts/*/submit/`) at the backend:
    1. Lacks the `HTTP_X_REQUEST_ARRIVAL_TIME` header,
    2. Originates from an IP address not explicitly listed in `TRUSTED_PROXIES`,
    3. Contains a malformed, non-numeric, or unparseable timestamp value, OR
    4. Carries an implausible timestamp that diverges from the backend system clock by more than the configured maximum tolerance $\delta_{\text{max}}$ (e.g., future timestamp $> 500\text{ ms}$, or lagging behind by an impossible duration indicating proxy clock failure):
    $\rightarrow$ **The backend fails closed immediately.**
    - The write operation is aborted before touching or modifying attempt state.
    - An explicit error response is returned: **HTTP 502 (Bad Gateway / Ingress Timestamp Error)** with structured error payload:
      ```json
      {
        "error": "INGRESS_TIMESTAMP_INVALID",
        "message": "Trusted perimeter ingress timestamp is missing, untrusted, or skewed."
      }
      ```
    - A critical security audit event is logged: `AuditLog: INGRESS_TIMESTAMP_INTEGRITY_FAILURE` recording the client IP, proxy headers, local clock reading, and failure reason.
    - **Strict Distinction:** This failure mode represents an infrastructure/perimeter fault and is **strictly distinguished** from normal examination deadline expiry (`AUTO_CLOSED_DEADLINE` / HTTP 410). It does not auto-close or alter the student's examination attempt state.
* **WSGI Fallback Strictly Restricted to Development / Testing:**
  - Fallback to outermost WSGI middleware ingress timestamping ($T_{\text{wsgi\_ingress}} = \text{time.time()}$) is **permitted strictly in development, staging, or automated testing environments** where explicitly enabled via settings flag:
    `ALLOW_WSGI_TIMESTAMP_FALLBACK = True` (or `DEBUG = True`).
  - In production (`DEBUG = False`, `ALLOW_WSGI_TIMESTAMP_FALLBACK = False`), missing or untrusted proxy arrival headers **always fail closed** as described above.
  - When active in dev/test, WSGI fallback captures the earliest Python entry point (`time.time()` on the first line of the outermost WSGI middleware).
  - **Conservative Nature of Fallback:** This fallback is conservative. Under worker thread contention or WSGI request buffering, a request that physically arrived at the host before the deadline might be delayed by WSGI request parsing and only timestamped at the middleware entry point after `end_time`, causing it to be rejected. Deploying behind a properly configured trusted reverse proxy (Nginx with `$msec`) with strict fail-closed enforcement is therefore the required production architecture.
* **Strict Cutoff on Request Arrival (No Late Writes):**
  - A write request (autosave update or submission) is accepted **only** when its authoritative ingress timestamp is at or before the official scheduled deadline:
    $$T_{\\text{ingress}} \le \text{official\_end\_time}$$
  - Any request whose ingress time is $> \text{official\_end\_time}$ **must be rejected** for answer writes. No client-side explanation, transport buffer, or offline timestamp permits accepting answers that arrive after the deadline.
* **Distinction Between Request Arrival and Processing Completion:**
  - If a request arrives at the trusted reverse proxy before the deadline ($T_{\\text{ingress}} \le \text{official\_end\_time}$), but backend worker thread scheduling or database lock contention causes processing to complete slightly after ($T_{\\text{complete}} > \text{official\_end\_time}$), the write is **accepted and committed** because the request was verified to have arrived on time.
  - The internal latency buffer accommodates server processing queues, but **never extends answering time or permits late-arriving requests**.
* **Bounded-Processing Consistency Model & Database-Coordinated Finalization:**
  To eliminate distributed state mismatch and non-atomic coordination gaps, the system coordinates admission and finalization **strictly through the database row lock on `ExamAttempt`**.

  1. **Dual Conditions for Write Acceptance:**
     A write request (autosave or submission) is accepted for durable persistence if and only if **both** of the following conditions are met:
     - **Condition 1 (On-Time Ingress):** Its trusted perimeter ingress timestamp was on or before the deadline: $T_{\text{ingress}} \le \text{official\_end\_time}$.
     - **Condition 2 (Admitted Prior to Finalization):** The request achieves application admission and acquires the `ExamAttempt` row lock while `status == IN_PROGRESS`.
  2. **Application Admission Window ($W_{\text{admission}}$):**
     To accommodate legitimate transport and queueing latency for on-time requests, the system provides a bounded processing window:
     $$W_{\text{admission}} = [\text{start\_time}, \text{official\_end\_time} + \Delta_{\text{drain}}] \quad (\Delta_{\text{drain}} = 15\text{ seconds})$$
  3. **Deadline Supervisor Finalization Protocol:**
     The background supervisor worker (`evaluate_examination_deadline_closure`) will **never** initiate attempt closure until the processing drain window has elapsed:
     $$\text{server\_time} \ge \text{official\_end\_time} + \Delta_{\text{drain}}$$
     At that instant, the supervisor acquires the row lock: `SELECT * FROM ExamAttempt WHERE id = :id FOR UPDATE`.
     - If `status == IN_PROGRESS`: transitions `status = AUTO_CLOSED_DEADLINE`, sets `closed_at = official_end_time`, `committed_at = transaction_recorded_at`, commits, and triggers MCQ evaluation.
     - If already `SUBMITTED` or `AUTO_CLOSED_DEADLINE`: releases lock and exits idempotently.
  4. **Bounded Exception & Grievance Fallback:**
     If extreme server queueing, worker contention, or network stall delays an on-time request past $\text{official\_end\_time} + \Delta_{\text{drain}}$ such that the supervisor has already committed `AUTO_CLOSED_DEADLINE`, the request is rejected with HTTP 410 (`WRITE_REJECTED_FINALIZATION_COMPLETED`). The answer payload is preserved in the candidate's local encrypted IndexedDB storage as `REJECTED_DEADLINE_EXCEEDED` inside the `AUDIT_RECOVERY_BUNDLE` for formal grievance appeal via Track B.
  5. **Late Ingress Rejection & Zero Premature Finalization:**
     Any request whose perimeter ingress timestamp is $> \text{official\_end\_time}$ is **strictly rejected** immediately with HTTP 410 (`EXAMINATION_CLOSED` for autosaves, `MANUAL_SUBMISSION_REJECTED_DEADLINE_EXCEEDED` for manual submissions), regardless of server load or drain windows. The drain window **never** extends answering time for late requests.
     - **Authoritative Finalization Isolation:** A rejected late request **never** transitions an attempt to `AUTO_CLOSED_DEADLINE` and **never** triggers MCQ evaluation.
     - The attempt status remains unchanged (`IN_PROGRESS`), preserving processing eligibility for any earlier on-time requests still traversing socket backlogs.
     - Only the background deadline supervisor worker, following the 15-second drain interval ($\text{server\_time} \ge \text{official\_end\_time} + \Delta_{\text{drain}}$), performs authoritative deadline auto-closure.

### 13.2 Autosave Strategy & Monotonic Sequence Versioning

* **Heartbeat & Trigger Events:** Answers autosave periodically (default: every 30 seconds) and immediately upon field blur or question palette navigation.
* **Monotonic Sequence Versioning:**
  - Every answer update includes a client incremented sequence counter: `{ question_id: 101, answer: "...", sequence: 14 }`.
  - The server verifies: `IF payload.sequence > existing_answer.version_sequence THEN UPDATE`.
  - Stale payloads arriving out of order due to network jitter or packet retransmission are safely discarded without overwriting newer state.

### 13.3 Encrypted Offline Cache Architecture & Shared-Device Security

#### 13.3.1 Shared-Device Threat Model
In college deployments, students frequently access online examinations from unmanaged or shared endpoints (e.g., college computer labs, multi-user library terminals, and commercial cyber cafes). A realistic threat model must address:
1. **Subsequent Students on Same OS Profile:** Subsequent candidates using the identical workstation and browser profile without OS user account separation.
2. **Developer Tools Access:** Any local user opening DevTools (`F12`), inspecting `IndexedDB` or `localStorage`, or dumping JavaScript heap memory.
3. **Persistent Local Profiles:** Unmanaged browsers retaining cached data across browser restarts.
4. **Malicious Extensions & Scripts:** Third-party extensions or bookmarklets running within the same browser origin.
5. **Endpoint Malware / Compromise:** Keystroke logging or physical RAM inspection on compromised public PCs.

#### 13.3.2 Application-Level Isolation vs. Cryptographic Confidentiality
- **Application-Level Isolation:** Routing checks and React component state checks (e.g. verifying `currentUser.id === student_id`) govern what the user interface renders. They provide **zero confidentiality** against anyone who inspects local browser storage directly via DevTools or disk inspection.
- **Cryptographic Confidentiality:** True confidentiality requires encrypting all offline persisted answers and draft text at rest before writing to browser storage, using cryptographic keys that are inaccessible to subsequent users.

#### 13.3.3 Encrypted Cache Specification (Web Crypto API & AES-GCM)
* **Storage Engine:** IndexedDB (providing structured key-value storage capable of storing binary `ArrayBuffer` payloads for answer text and image/PDF attachments).
* **Cryptographic Algorithm:** AES-256-GCM (Authenticated Encryption with Associated Data - AEAD) via `window.crypto.subtle`.
* **Record Structure:**
  ```typescript
  interface EncryptedCacheRecord {
    id: string;                     // e.g. "ans_q101"
    iv: Uint8Array;                 // 12-byte random Initialization Vector (CSPRNG)
    ciphertext: ArrayBuffer;        // AES-256-GCM ciphertext of answer payload
    tagLength: 128;                 // 128-bit authentication tag
    associatedData: {               // Authenticated Additional Data (AAD) bound to cipher
      student_id: number;
      examination_id: number;
      attempt_id: number;
      question_id: number;
      version_sequence: number;
    };
    sync_status: 'SYNC_PENDING' | 'REJECTED_DEADLINE_EXCEEDED';
    created_at: string;
  }
  ```
* **Binding via AAD:** Authenticated Additional Data binds candidate and attempt metadata to the ciphertext, preventing ciphertext-swapping attacks between questions or attempts.

#### 13.3.4 Dual-Track Key-Management Lifecycle (Live Examination vs. Post-Deadline Evidence Recovery)

To resolve the tension between strict examination deadline enforcement and post-deadline grievance appeal rights, the architecture establishes a **Dual-Track Key-Management Lifecycle**. Key recovery is strictly partitioned into two distinct operations with separate authorization contracts, endpoints, and security guarantees.

1. **Removal of Examination PIN as Local Encryption Secret:**
   - **NO Examination PIN, student password, or short credential is ever used to derive local encryption wrapping keys, nor is any wrapped DEK stored in IndexedDB.**
   - Short credentials (such as 6-character PINs) possess insufficient entropy against offline brute-force attacks if stored locally on a shared computer. Eliminating local PIN wrapping eliminates the offline dictionary-attack vector completely.

2. **Data Encryption Key (DEK) Generation & In-Memory Lifetime:**
   - Upon entering the live exam interface, the client generates an attempt-specific 256-bit AES-GCM key via Web Crypto API:
     ```javascript
     const dek = await window.crypto.subtle.generateKey(
       { name: "AES-GCM", length: 256 },
       true,
       ["encrypt", "decrypt"]
     );
     ```
   - The DEK is held **strictly in volatile JavaScript memory** (within a private closure / React ref). It is **never** stored in plaintext in `localStorage`, `sessionStorage`, or `IndexedDB`.
   - While the browser tab remains open during an active examination, the in-memory DEK is continuously used to encrypt unsynchronized keystrokes into IndexedDB, providing uninterrupted local caching even during prolonged network outages.

3. **Server-Assisted Key Wrapping & Protection over TLS:**
   - During attempt initialization or re-entry over TLS (`POST /api/attempts/{examId}/start/` or `/init-cache-key/`), the client exports the DEK securely over TLS to the backend.
   - The backend encrypts/wraps the DEK using a server-managed Key Encryption Key (e.g., dedicated server envelope key `AES-256-GCM` or Django application secret).
   - The server stores the wrapped DEK in the `ExamAttempt.encrypted_cache_dek` database field.
   - At rest in the database, the DEK is cryptographically protected by the server key; in transit, it is protected by TLS 1.3.

4. **Track A: Live Examination Key Recovery (Resumption & Synchronization):**
   - **Purpose:** Resume an active, in-progress examination and synchronize valid pending answers before the deadline.
   - **Endpoint:** `POST /api/attempts/{attemptId}/recover-cache-key/`
   - **Permission Class:** `LiveExamKeyRecoveryPermission`
   - **Authorization Conditions (All Mandatory):**
     1. *Student Identity:* Authenticated student account must match `attempt.student_id`.
     2. *Attempt Status:* Attempt must be in active `IN_PROGRESS` status. If already `SUBMITTED` or `AUTO_CLOSED_DEADLINE`, live key release is rejected (HTTP 403 `EXAM_ATTEMPT_FINALIZED`).
     3. *Session Authorization:* Valid, active `exam_session_token` and verified Examination PIN.
     4. *Deadline Boundary:* Server-authoritative time must be $\le \text{official\_end\_time}$. If server time has passed the deadline, live key release is rejected (HTTP 410 `EXAMINATION_CLOSED`).
     5. *Throttling & Audit:* Rate-limited to max 3 requests per minute; emits `AuditLog: LIVE_CACHE_KEY_RELEASED`.
   - **Permitted Operations:**
     - Unwraps and transmits DEK over TLS to client volatile memory.
     - Client decrypts locally cached answers in IndexedDB.
     - Resumes active live examination interface with countdown timer.
     - Allows write operations (`PATCH /answers/`, `POST /submit/`) subject strictly to $T_{\text{ingress}} \le \text{official\_end\_time}$.

5. **Track B: Post-Deadline Read-Only Evidence Recovery (Grievance & Audit):**
   - **Purpose:** Allow a candidate (or grievance committee) to inspect and export preserved, unacknowledged local answers for a formal academic appeal after an examination has concluded.
   - **Endpoint:** `POST /api/attempts/{attemptId}/recover-evidence-key/`
   - **Permission Class:** `PostDeadlineEvidenceRecoveryPermission`
   - **Authorization Conditions (All Mandatory):**
     1. *Student Identity:* Authenticated student account must match original `attempt.student_id`.
     2. *Finalized State:* Attempt status is finalized as `SUBMITTED` or `AUTO_CLOSED_DEADLINE`, OR server time has exceeded `official_end_time`.
     3. *Re-authentication:* Re-authentication via student login credentials + Examination PIN verification (or institutional SSO/MFA).
     4. *Retention Window Compliance:* Request must arrive within the authorized evidence retention window (`server_time <= finalized_at + EXAM_EVIDENCE_KEY_RETENTION_PERIOD`). If retention has expired, request is rejected (HTTP 410 `EVIDENCE_RETENTION_EXPIRED`).
     5. *Throttling & Audit:* Strictly rate-limited to max 3 requests per 10 minutes; emits mandatory security audit event `AuditLog: EVIDENCE_KEY_RELEASED` logging candidate ID, attempt ID, client IP, and user-agent.
     6. *Strict Non-Reactivation:* Authorization grants read-only evidence access **only**. It does NOT reactivate examination permissions.
   - **Permitted Operations:**
     - Transmits DEK over TLS to client volatile memory scoped strictly to the `ReadOnlyEvidenceView` component.
     - Decrypts candidate's locally preserved IndexedDB records (`REJECTED_DEADLINE_EXCEEDED` and unacknowledged `SYNC_PENDING`).
     - Generates and exports structured `AUDIT_RECOVERY_BUNDLE` (`audit_recovery_bundle_{attemptId}.json`).
     - Displays original local answers in a read-only viewer with a persistent, non-dismissible banner: `⚠️ READ-ONLY EVIDENCE RECOVERY — EXAM CLOSED — NOT SUBMITTED`.
   - **Strictly Prohibited Operations (Enforced at Backend API & DB Level):**
     - Reopening the examination (`status` can NEVER transition back to `IN_PROGRESS`).
     - Modifying submitted answers (all write endpoints `/answers/` reject with HTTP 403 `EXAM_ATTEMPT_FINALIZED`).
     - Synchronizing rejected late answers as accepted responses.
     - Altering the official scheduled deadline.
     - Triggering automated regrading or altering published evaluation scores.
     - Bypassing the formal college grievance review process.

6. **Summary Comparison: Key Recovery Operations:**

| Dimension | Track A: Live Exam Key Recovery | Track B: Post-Deadline Evidence Recovery |
| :--- | :--- | :--- |
| **Endpoint** | `POST /api/attempts/{id}/recover-cache-key/` | `POST /api/attempts/{id}/recover-evidence-key/` |
| **Attempt Status Required** | `status == IN_PROGRESS` | `status IN [SUBMITTED, AUTO_CLOSED_DEADLINE]` or $T > \text{end}$ |
| **Time Boundary** | Server time $\le \text{official\_end\_time}$ | Within `EXAM_EVIDENCE_KEY_RETENTION_PERIOD` post-exam |
| **Write APIs Enabled?** | Yes (subject to $T_{\text{ingress}} \le \text{official\_end\_time}$) | **No. Strictly Read-Only (HTTP 403 / 410 on writes)** |
| **UI Mode** | Active Live Exam Palette & Timer | Watermarked Read-Only Evidence Viewer |
| **Primary Output** | Synchronized exam answers | Exported `AUDIT_RECOVERY_BUNDLE` diagnostic archive |
| **Audit Event** | `AuditLog: LIVE_CACHE_KEY_RELEASED` | `AuditLog: EVIDENCE_KEY_RELEASED` |

7. **Lifecycle Behavior Across Session Boundaries:**
   - *Logout / Tab Close:* In-memory DEK is immediately zeroed and discarded. Encrypted records remain safely encrypted in IndexedDB.
   - *Browser Restart:* In-memory DEK is absent. The client cannot decrypt local storage until re-authenticating with the server under Track A (if on-time) or Track B (if finalized).
   - *Session Expiry:* Expired session tokens cannot fetch the DEK under either track.
   - *Temporary Inaccessibility During Offline Disconnection:* **If a browser restart or tab closure occurs while the device is offline, encrypted cached answers are temporarily inaccessible until server connectivity is restored.** The client cannot decrypt the IndexedDB ciphertext without contacting the server for DEK release.

8. **Limits Against Same-Origin Scripts & Compromised Endpoints:**
   - Marking a Web Crypto key `extractable: false` prevents raw key export, but **does not protect against arbitrary scripts executing within the same origin**. An attacker executing script via XSS or a malicious extension can invoke `crypto.subtle.decrypt()` using the key handle. Robust XSS defenses (CSP, JSX escaping) remain essential.
   - Browser cryptography cannot protect against an operating system compromised by root-level malware, memory dumpers, or hardware keyloggers.

#### 13.3.5 Diagnostic Recovery Bundle (`AUDIT_RECOVERY_BUNDLE`) & Authenticity Limitations

When offline answers are transmitted after `official_end_time`, the server responds with HTTP 410 (`EXAMINATION_CLOSED`). The client **does not** claim these answers were synchronized, and updates their local status to `REJECTED_DEADLINE_EXCEEDED` alongside the server's rejection timestamp.

The candidate or proctor can export a structured diagnostic bundle (`AUDIT_RECOVERY_BUNDLE`) using Track B Post-Deadline Evidence Recovery for administrative appeal.

1. **Exact Bundle Specification:**
   An `AUDIT_RECOVERY_BUNDLE` is a structured JSON diagnostic archive containing two clearly separated sections:
   - **Client-Generated Diagnostic Evidence (Self-Reported / Untrusted):**
     - Client environment: Browser user-agent, OS platform, screen resolution, local system clock time at export.
     - Local cache records: Question IDs, encrypted answer payloads (base64 ciphertext), decrypted plaintext drafts (for human committee review), random IVs, 128-bit AES-GCM authentication tags, client version sequence numbers, and client-recorded interaction timestamps (`client_recorded_at`).
     - Local network diagnostic log: Timestamps of failed autosave fetch attempts, connection errors, HTTP status codes (e.g. timeouts, HTTP 410), and client online/offline event transitions.
   - **Server-Generated Records & Linked Receipts (Authoritative / Trusted):**
     - Examination attempt metadata: `attempt_id`, `student_id`, `examination_id`, scheduled `start_time`, and `official_end_time`.
     - Server receipts: `submission_receipt_uuid`, HTTP 410 rejection receipt containing $T_{\text{ingress}}$, server-recorded sequence counter (`last_synchronized_sequence`), and server digital signature / HMAC digest (`receipt_signature`) generated by the backend using server-managed secret keys.

2. **Cryptographic Authentication vs. Integrity Metadata:**
   - The bundle is **accompanied by integrity metadata** (a client-computed SHA-256 hash of the canonical JSON export) to detect file corruption during transmission.
   - **No Trusted Signing Secret in Frontend JavaScript:** The frontend JavaScript does NOT and CANNOT hold a private signing key, because any secret placed in client-side code can be extracted or forged by the user.
   - **Client Timestamps Do Not Prove Pre-Deadline Entry:** Client-generated timestamps inside the bundle are self-reported and **do not prove answers were entered before the official deadline**.
   - Server-issued receipts linked in the bundle are authenticated using server-side signatures (HMAC-SHA256 with server `SECRET_KEY`).

3. **Forensic Verification Limits:**
   - Forensic scrutiny cannot prove timeline authenticity if the client endpoint was compromised or if client JavaScript was manipulated.

4. **College Examination Committee Grievance Review Process:**
   - Defined as a **proposed institutional workflow**, NOT an automated grading override.
   - The candidate exports `audit_recovery_bundle_{attemptId}.json` and submits it through the college examination grievance portal.
   - The committee compares server-side audit logs, network gateway logs, and pre-deadline synchronized sequence numbers against the bundle.
   - **Late-rejected answers are never silently or automatically treated as valid examination submissions.** Any acceptance or special evaluation requires a formal, recorded administrative committee resolution.

#### 13.3.6 Evidence Retention Policy & Operational State Machine

The retention and disposal of server-wrapped Data Encryption Keys (`ExamAttempt.encrypted_cache_dek`) is governed by an explicit institutional configuration state machine. The system strictly enforces that no production examination can be activated without an approved, valid evidence retention policy.

1. **Configuration State Machine:**
   The evidence retention policy operates under four formal states:
   - **`UNCONFIGURED` (Initial / Default State):** The institutional retention duration has not been formally approved or entered by college administration. In this state, the system enforces a **Hard Production Activation Gate**: any attempt to publish, schedule, or activate an examination is **strictly blocked** by Django system checks and administrative validation.
   - **`CONFIGURED` (Active Operational State):** An authorized institutional administrator (`IsCollegeSuperAdmin`) has configured a valid integer retention period (in days, e.g., 14, 30, or 60 days) and signed the policy configuration action. Emits `AuditLog: RETENTION_POLICY_CONFIGURED`. Scheduled examinations can now be published and activated.
   - **`EXPIRED` (Purged State):** The retention period for a finalized examination attempt has elapsed. The scheduled key-deletion worker zeroes and deletes the wrapped DEK from the database. The client UI transitions to `KEY_PURGED_UNRECOVERABLE`.
   - **`LEGAL_HOLD / GRIEVANCE_PENDING` (Suspended State):** An administrative override applied to specific examination attempts subject to formal grievance appeals, legal scrutiny, or disciplinary review. While active, scheduled key deletion is strictly suspended, and keys remain preserved until the dispute is formally resolved.

2. **Production Examination Activation Gate (Hard Blocker):**
   - **Mandatory Pre-Condition:** Setting an examination to `SCHEDULED` or `ACTIVE` requires a valid, institution-approved retention policy (`EXAM_EVIDENCE_KEY_RETENTION_PERIOD != 'UNCONFIGURED'`).
   - Attempting to schedule or activate an examination while unconfigured raises a validation error: `ValidationError('EXAM_ACTIVATION_BLOCKED: Institutional evidence key retention period is UNCONFIGURED.')`.
   - Safe operational baseline: College administrators must explicitly configure an approved integer retention period prior to examination scheduling.

3. **Institutional Approval & Role Authorization:**
   - Modifying the institutional retention policy is strictly restricted to the college super-administrator role (`IsCollegeSuperAdmin`).
   - Individual faculty, department heads, or exam coordinators cannot alter or bypass this policy.
   - Every policy update requires mandatory written justification and generates a high-severity audit record: `AuditLog: RETENTION_POLICY_CONFIGURED` recording the administrator ID, old value, new value, client IP, and approval timestamp.

4. **Immutable Snapshot per Examination and Attempt:**
   - When an examination is scheduled/published, the active institutional retention policy is captured as an **immutable snapshot** on the `Examination` record:
     `Examination.evidence_key_retention_days = Config.EXAM_EVIDENCE_KEY_RETENTION_PERIOD`
   - When an attempt is finalized (`SUBMITTED` or `AUTO_CLOSED_DEADLINE`), the exact expiry instant is computed and stored immutably on `ExamAttempt`:
     `ExamAttempt.evidence_key_expires_at = attempt.finalized_at + timedelta(days=examination.evidence_key_retention_days)`
   - **Non-Retroactivity:** Subsequent modifications to the institutional retention setting apply only to future examinations. They **never** retroactively alter the expiry date or retention rights of active or already-finalized examination attempts.

5. **Retention Countdown & Expiry Determination:**
   - The retention countdown begins at the exact instant the attempt transitions to a finalized state: `finalized_at` (`submitted_at` for manual submissions, `closed_at` for deadline auto-closures).
   - Expiry is determined server-authoritatively: `server_time > attempt.evidence_key_expires_at`.
   - At request time, if `server_time > attempt.evidence_key_expires_at`, any call to `POST /api/attempts/{attemptId}/recover-evidence-key/` is immediately rejected with HTTP 410 (`EVIDENCE_RETENTION_EXPIRED`), regardless of whether the physical database record has been purged by the scheduled batch worker.

6. **Scheduled Key-Deletion Job Behavior:**
   - Scheduled Celery beat task `purge_expired_evidence_keys` executes daily during off-peak hours (e.g., 02:00 AM).
   - Queries attempts where `evidence_key_expires_at < timezone.now()`, `encrypted_cache_dek IS NOT NULL`, and `is_under_legal_hold == False`.
   - Cryptographically zeroes the `encrypted_cache_dek` field, updates it to `NULL`, and sets `evidence_key_purged_at = timezone.now()`.

7. **Audit Trail for Key Deletion:**
   - Each purged key emits a security audit record: `AuditLog: EVIDENCE_KEY_PURGED` capturing `attempt_id`, `student_id`, `examination_id`, and `purged_at`.

8. **Handling Key-Deletion Job Failures:**
   - If the database write fails or a worker crashes during key purging, the transaction rolls back.
   - The failure is logged as `AuditLog: EVIDENCE_KEY_PURGE_FAILED` and alerts systems administrators.
   - Because the recovery API strictly checks `now() > evidence_key_expires_at` on every request, an unpurged expired key **will never be released to a client**, preserving confidentiality even if the deletion task encounters a transient database error.

9. **Legal Holds & Formal Grievance Appeals:**
   - If a candidate files a formal academic grievance or appeal before `evidence_key_expires_at`, an authorized examination committee member flags the attempt: `ExamAttempt.is_under_legal_hold = True` with mandatory `legal_hold_reason = "Formal Grievance #GR-2026-XXX"`.
   - While `is_under_legal_hold == True`, scheduled deletion jobs strictly skip this record.
   - Evidence key recovery remains accessible to authorized committee members and the candidate throughout the formal grievance review process.
   - Once the committee issues a final resolution, the legal hold is released with audited resolution metadata (`AuditLog: LEGAL_HOLD_RELEASED`), and normal retention expiry resumes.

10. **Interaction with Local Browser Cache & Lab Workstation Sanitization:**
    - Local browser storage (IndexedDB) is device-specific and decoupled from the server database.
    - Workstations in shared college computer labs frequently run Deep Freeze or reboot-restore scripts that purge temporary profiles and browser storage upon reboot.
    - **Mandatory Procedural Rule:** If a student experiences an examination disruption on a shared college lab machine, the candidate **must perform Track B Post-Deadline Evidence Recovery and export the `AUDIT_RECOVERY_BUNDLE` prior to rebooting or leaving the workstation**.
    - If the computer reboots before export, local IndexedDB is wiped by OS sanitization scripts, rendering unacknowledged local evidence permanently unrecoverable. Proctors and lab administrators must be trained on this requirement.

#### 13.3.7 Residual Risks & Required Institutional Policies
- **Residual Risks on Unmanaged Devices:** Hardware keyloggers, screen recording malware, or root-level compromise on commercial cyber cafe machines cannot be fully mitigated by browser-level cryptography.
- **Required Institutional Policies:**
  - High-stakes examinations should be conducted on college-controlled workstations configured in **Kiosk Mode** (locked down full-screen browser, disabled DevTools via Group Policy, extension installation blocked).
  - Regular automated workstation sanitization: nightly deep-freeze or reboot scripts wiping temporary profiles and browser storage.

### 13.4 Idempotent Submissions, Locking Order & 16-Scenario Concurrency Analysis

#### 13.4.1 Accurate Timestamp Definitions for Submissions
To maintain technical precision, the architecture defines three distinct timestamps:
* **$T_{\text{ingress}}$ (Perimeter Ingress Timestamp):** High-precision Nginx `$msec` captured at header read. Recorded immutably as `submitted_at` for on-time submissions.
* **$T_{\text{admit}}$ (Application Admission Timestamp):** The instant a Gunicorn worker accepts the request and enters Django middleware.
* **`transaction_recorded_at` (Model field `committed_at`):** Application server timestamp captured during the database transaction block (`django.utils.timezone.now()`).
  - **Technical Precision Note:** The architecture explicitly distinguishes between application transaction recording time and the actual database engine transaction commit instant. The hardware/engine commit completion instant is an internal MySQL InnoDB event (write-ahead log / redo log flush) that cannot be directly observed by the Python application layer without specialized database binary log hooks. The field `committed_at` therefore accurately records the application-evaluated transaction execution timestamp.

#### 13.4.2 Database-Coordinated Row-Locking Order & Transaction Boundaries
Admission and finalization are coordinated **strictly through MySQL InnoDB ACID row locks** (`SELECT ... FOR UPDATE` on `ExamAttempt`), eliminating distributed race conditions and TOCTOU gaps:
1. **Acquire Exclusive Row Lock:** Execute `SELECT * FROM ExamAttempt WHERE id = :attempt_id FOR UPDATE`.
2. **Evaluate Ingress Timestamp & Attempt Status:**
   - **Autosave Request:**
     - If `status == IN_PROGRESS` and $T_{\text{ingress}} \le \text{official\_end\_time}$: execute `UPDATE Answer SET ... WHERE question_id = :qid AND version_sequence < :seq`, commit transaction, release lock. Return **HTTP 200 (OK)**.
     - If `status == SUBMITTED`: reject with **HTTP 409 (Conflict)** `{ error: "ATTEMPT_ALREADY_FINALIZED" }`.
     - If `status == AUTO_CLOSED_DEADLINE`: reject with **HTTP 410 (Gone)** `{ error: "WRITE_REJECTED_FINALIZATION_COMPLETED" }`.
   - **Manual Submission Request:**
     - **On-Time Submission ($T_{\text{ingress}} \le \text{official\_end\_time}$):**
       - If `status == IN_PROGRESS`: transition `status = SUBMITTED`, `submitted_at = T_ingress`, `committed_at = transaction_recorded_at`, commit transaction, release lock. Post-commit: trigger asynchronous, idempotent MCQ evaluation (`evaluate_mcq_attempt.delay()`). Return **HTTP 200 (OK)** with signed submission receipt.
       - If `status == SUBMITTED` and `submission_uuid == attempt.submission_uuid`: return cached submission receipt (**HTTP 200 OK**, idempotent retry with original `submitted_at`).
       - If `status == SUBMITTED` and `submission_uuid != attempt.submission_uuid`: reject with **HTTP 409 (Conflict)** `{ error: "ATTEMPT_ALREADY_FINALIZED" }`.
       - If `status == AUTO_CLOSED_DEADLINE`: reject with **HTTP 410 (Gone)** `{ error: "WRITE_REJECTED_FINALIZATION_COMPLETED" }` (bounded-processing exception: on-time ingress delayed in socket backlog until supervisor finalized). Local payload preserved in `AUDIT_RECOVERY_BUNDLE`.
     - **Late Submission ($T_{\text{ingress}} > \text{official\_end\_time}$):**
       - Evaluated against current attempt status without altering lifecycle state:
         - **Case A (Attempt remains `IN_PROGRESS`):** Reject write payload immediately with **HTTP 410 (Gone)** `{ error: "MANUAL_SUBMISSION_REJECTED_DEADLINE_EXCEEDED" }`. **Crucial Rule:** The late submission **does NOT** transition the attempt to `AUTO_CLOSED_DEADLINE` and **does NOT** trigger MCQ grading. Attempt status remains unchanged (`IN_PROGRESS`); earlier on-time autosaves or submissions in socket backlogs remain eligible for processing. Finalization is deferred strictly to the background deadline supervisor after the drain interval ($\text{official\_end\_time} + \Delta_{\text{drain}}$).
         - **Case B (Attempt already `AUTO_CLOSED_DEADLINE`):** Reject with **HTTP 410 (Gone)** `{ error: "MANUAL_SUBMISSION_REJECTED_DEADLINE_EXCEEDED", finalized_at: closed_at }`. Zero state alteration or duplicate grading.
         - **Case C (Attempt already `SUBMITTED`):** If `submission_uuid == attempt.submission_uuid`, return cached original submission receipt (**HTTP 200 OK**, idempotent retry of earlier on-time submission). If `submission_uuid != attempt.submission_uuid`, reject with **HTTP 409 (Conflict)** `{ error: "ATTEMPT_ALREADY_FINALIZED" }`. The existing submission timestamp and receipt remain untouched.
         - **Case D (Concurrent earlier on-time request queued):** The late submission is rejected immediately. Any earlier on-time autosave or submission queued in upstream buffers proceeds according to standard bounded-processing consistency without premature closure.
   - **Deadline Supervisor Worker:**
     - Waits until $\text{server\_time} \ge \text{official\_end\_time} + \Delta_{\text{drain}}$ (15s).
     - Acquires row lock: if `status == IN_PROGRESS`, transitions `status = AUTO_CLOSED_DEADLINE`, `closed_at = official_end_time`, `committed_at = transaction_recorded_at`, commits transaction, releases lock. Post-commit: triggers asynchronous, idempotent MCQ evaluation (`evaluate_mcq_attempt.delay()`).
     - If already `SUBMITTED` or `AUTO_CLOSED_DEADLINE`, releases lock and exits idempotently.
3. **MCQ Grading Execution:** Evaluates strictly after the final transactional state has committed to MySQL, ensuring grading runs on the frozen answer snapshot. Duplicate grading task dispatches are handled idempotently via row locks on `EvaluationResult` or transactional `is_evaluated` flag checks.

#### 13.4.3 Scenario-by-Scenario Concurrency Analysis (16 Scenarios)

| # | Scenario Description | Ingress Timestamp & Conditions | Lock Serialization & Path | Authoritative Outcome & HTTP Code |
| :-: | :--- | :--- | :--- | :--- |
| **1** | **On-time autosave admitted before deadline** | $T_{\text{ingress}} \le \text{end}$; admitted at $T_{\text{admit}} \le \text{end}$. | Acquires row lock on `IN_PROGRESS` attempt; updates `Answer` row (`WHERE version_sequence < incoming_seq`); commits transaction. | **HTTP 200 (OK)**<br>`{ status: "SAVED", seq: N, timestamp: T_server }` |
| **2** | **On-time autosave admitted after deadline within processing window** | $T_{\text{ingress}} \le \text{end}$; buffered in socket queue; admitted at $T_{\text{admit}} \le \text{end} + \Delta_{\text{drain}}$. | Supervisor delayed in drain window ($\Delta_{\text{drain}} = 15\text{s}$); request acquires row lock on `IN_PROGRESS` attempt; verifies $T_{\text{ingress}} \le \text{end}$; commits answer. | **HTTP 200 (OK)**<br>Answer accepted because ingress arrival was verified on-time and admitted before closure. |
| **3** | **On-time request still queued after processing window** | $T_{\text{ingress}} \le \text{end}$; extreme queueing delays admission past $\text{end} + \Delta_{\text{drain}}$. | Supervisor has already acquired lock, transitioned attempt to `AUTO_CLOSED_DEADLINE`, and committed. Request acquires lock next, sees `AUTO_CLOSED_DEADLINE`. | **HTTP 410 (Gone)**<br>`{ error: "WRITE_REJECTED_FINALIZATION_COMPLETED" }`<br>Preserved locally in `AUDIT_RECOVERY_BUNDLE` for grievance appeal. |
| **4** | **Late autosave** | $T_{\text{ingress}} > \text{end}$. | Evaluated immediately at ingress middleware; rejected before touching attempt state. | **HTTP 410 (Gone)**<br>`{ error: "EXAMINATION_CLOSED" }`<br>Zero late data committed. |
| **5** | **On-time manual submission** | $T_{\text{ingress}} \le \text{end}$; admitted within processing window while `status == IN_PROGRESS`. | Acquires row lock, marks `status = SUBMITTED`, `submitted_at = T_ingress`, `committed_at = transaction_recorded_at`, commits, enqueues MCQ grading. | **HTTP 200 (OK)**<br>Signed submission receipt returned with immutable $T_{\text{ingress}}$. |
| **6** | **Late manual submission** | $T_{\text{ingress}} > \text{end}$. | Evaluated against attempt status without altering lifecycle state. The late request does NOT transition the attempt to `AUTO_CLOSED_DEADLINE` and does NOT trigger MCQ grading.<br>• *Case A (`IN_PROGRESS`):* Status left unchanged; auto-closure deferred strictly to deadline supervisor at $\text{end} + \Delta_{\text{drain}}$; queued on-time autosaves remain eligible.<br>• *Case B (`AUTO_CLOSED_DEADLINE`):* Returns finalized status.<br>• *Case C (`SUBMITTED`):* Idempotent retry returns original receipt if matching UUID; rejects new UUID.<br>• *Case D (Queued on-time write):* Earlier write processed under lock; late write rejected. | **HTTP 410 (Gone)**<br>`{ error: "MANUAL_SUBMISSION_REJECTED_DEADLINE_EXCEEDED" }`<br>Zero late data committed; attempt auto-closure deferred strictly to deadline supervisor; local evidence preserved in `AUDIT_RECOVERY_BUNDLE` for Track B appeal. |
| **7** | **Concurrent autosave and manual submission** | Both arrive at $T_{\text{ingress}} \le \text{end}$; compete for row lock. | Case A (Autosave first): Autosave updates answer, commits. Submission acquires lock next, marks `SUBMITTED`, commits.<br>Case B (Submission first): Submission marks `SUBMITTED`, commits. Autosave acquires lock next, sees `SUBMITTED`. | **Case A: Both HTTP 200 (OK)**<br>**Case B: Submission HTTP 200 (OK); Autosave HTTP 409 (Conflict / Finalized)** |
| **8** | **Request admission racing with finalization** | On-time request and deadline worker compete for row lock at $T \approx \text{end} + \Delta_{\text{drain}}$. | MySQL InnoDB row lock serializes execution atomically.<br>If request wins lock: commits write; supervisor acquires lock next and finalizes attempt.<br>If supervisor wins lock: commits `AUTO_CLOSED_DEADLINE`; request acquires lock next and sees finalized state. | **If request wins: HTTP 200 (OK)**<br>**If supervisor wins: HTTP 410 (Gone / Finalized)**<br>Zero TOCTOU gap; atomic database coordination. |
| **9** | **Worker crash after admission** | Worker accepts connection, acquires row lock, but crashes (OOM / `SIGSEGV`) before commit. | MySQL detects connection termination and rolls back uncommitted transaction automatically. Row lock released. Client detects network drop / HTTP 502. | **HTTP 502 (Bad Gateway)** to client.<br>Client retries with same sequence / submission UUID; state remains clean. |
| **10** | **Worker crash before admission** | Worker crashes while request is buffered in socket backlog or during HTTP header read. | Nginx detects upstream socket closure and returns HTTP 502 to client. Zero application or database state touched. | **HTTP 502 (Bad Gateway)** to client.<br>Client retries with same sequence / submission UUID. |
| **11** | **Duplicate submission UUID** | Client double-clicks or retries submit after network timeout with identical `submission_uuid`. | Acquires row lock, matches `submission_uuid` on already `SUBMITTED` attempt, reads existing state. | **HTTP 200 (OK)**<br>Cached submission receipt returned (`idempotency: "ALREADY_SUBMITTED"`). Zero re-grading. |
| **12** | **Duplicate deadline workers** | Multiple Celery worker processes execute finalization task simultaneously. | Both execute `SELECT ... FOR UPDATE`. Worker 1 acquires lock, marks `AUTO_CLOSED_DEADLINE`, commits. Worker 2 acquires lock next, sees `AUTO_CLOSED_DEADLINE`. | **Worker 1: Commits Finalization**<br>**Worker 2: Idempotent No-Op Exit**<br>Zero duplicate auto-closures or conflicting states. |
| **13** | **Redis unavailable** | Redis cache / broker is down or unreachable. | Core admission and finalization protocol coordinates strictly through MySQL row locks and continues to function without Redis. Tasks fall back to synchronous execution via `TaskQueueService`. | **Writes and Finalization Succeed (HTTP 200 / 410)**.<br>Zero data loss; admission correctness independent of Redis. |
| **14** | **MySQL temporarily unavailable** | Transient database deadlock, timeout, or connection drop. | Django transaction rolls back, returns HTTP 503 or HTTP 500. Client catches error, keeps answer cached in IndexedDB (`SYNC_PENDING`), and retries with backoff. | **HTTP 503 (Service Unavailable)**<br>Local client cache safely preserves answers until database recovers. |
| **15** | **Request body incomplete at deadline** | Header read before deadline ($T_{\text{ingress}} \le \text{end}$); body upload slow. | Nginx buffers body under `client_body_timeout 10s`. If completed within timeout, request forwards to Gunicorn. If stalled past timeout, Nginx aborts connection. | **HTTP 408 (Request Timeout)** or **HTTP 200 (if completed within timeout)**.<br>Zero partial or corrupted request bodies committed. |
| **16** | **MCQ grading triggered more than once** | Duplicate worker message or concurrent submit/auto-close triggers `evaluate_mcq_attempt`. | Grading task acquires row lock on `EvaluationResult` or checks `is_evaluated` flag under transaction. Task 1 computes scores and commits result. Task 2 acquires lock, sees `is_evaluated == True`, and skips computation. | **Exactly One Evaluation Record**<br>Zero score alteration or duplicate result entries. |

### 13.5 Examination Attempt and Submission Sequence

```mermaid
sequenceDiagram
    autonumber
    actor Student
    participant UI as React Live Exam Interface
    participant IDB as Encrypted IndexedDB Cache
    participant Proxy as Nginx Trusted Reverse Proxy
    participant API as Django /attempts/ API
    participant DB as MySQL Database
    participant Supervisor as Deadline Supervisor (Celery)

    Student->>UI: Enters Live Examination View
    UI->>Proxy: POST /api/attempts/{examId}/start/
    Proxy->>API: Overwrite & Forward X-Request-Arrival-Time ($msec as T_ingress)
    API->>DB: Check or Create ExamAttempt (status=IN_PROGRESS)
    API-->>UI: Questions Payload, Attempt ID, Remaining Seconds, Wrapped DEK
    UI->>UI: Import DEK into Volatile Memory (Zeroed on Tab Close / Logout)

    loop Every 30s or on Question Blur (Autosave Cycle)
        Student->>UI: Selects Option / Types Text
        UI->>IDB: Encrypt Payload (AES-256-GCM) & Store (SYNC_PENDING)
        UI->>Proxy: PATCH /api/attempts/{attemptId}/answers/ (qid, answer, seq=N)
        Proxy->>API: Overwrite & Forward X-Request-Arrival-Time ($msec as T_ingress)
        alt On-Time Ingress (T_ingress <= official_end_time)
            API->>DB: SELECT * FROM ExamAttempt WHERE id = attempt_id FOR UPDATE
            alt Attempt IN_PROGRESS (Standard Acceptance)
                API->>DB: UPDATE Answer WHERE question_id = qid AND seq < N
                API->>DB: Commit Transaction & Release Row Lock
                API-->>UI: HTTP 200 (Saved, Server Timestamp, Ack Seq=N)
                UI->>IDB: Delete Local Cache Record for Acknowledged Seq
            else Bounded-Processing Delay (Finalized Before Lock Acquired)
                API->>DB: Rollback / Release Row Lock
                API-->>UI: HTTP 410 (WRITE_REJECTED_FINALIZATION_COMPLETED)
                UI->>IDB: Mark Record as REJECTED_DEADLINE_EXCEEDED (Retain for Appeal)
            end
        else Late Ingress (T_ingress > official_end_time)
            API-->>UI: HTTP 410 (EXAMINATION_CLOSED)
            UI->>IDB: Mark Record as REJECTED_DEADLINE_EXCEEDED (Retain for Appeal)
        end
    end

    alt Manual Submission on Time (T_ingress <= official_end_time)
        Student->>UI: Clicks "Submit Examination"
        UI->>Proxy: POST /api/attempts/{attemptId}/submit/ (submission_uuid)
        Proxy->>API: Overwrite & Forward X-Request-Arrival-Time ($msec as T_ingress)
        API->>DB: SELECT * FROM ExamAttempt WHERE id = attempt_id FOR UPDATE
        alt Attempt IN_PROGRESS (First-Time Finalization)
            API->>DB: UPDATE ExamAttempt SET status=SUBMITTED, submitted_at=T_ingress, committed_at=now()
            API->>DB: Commit Transaction & Release Row Lock
            API->>Supervisor: Enqueue Asynchronous MCQ Grading (Post-Commit)
            API-->>UI: HTTP 200 (Signed Submission Receipt)
            UI->>IDB: Purge Synchronized Attempt Cache & Zero DEK in Memory
        else Attempt Already SUBMITTED (Idempotent Retry)
            API->>DB: Read Existing Submission Details & Release Lock
            alt submission_uuid Matches Existing Attempt
                API-->>UI: HTTP 200 (Cached Submission Receipt, Idempotent)
            else submission_uuid Mismatch
                API-->>UI: HTTP 409 (ATTEMPT_ALREADY_FINALIZED)
            end
        else Bounded-Processing Delay (Already AUTO_CLOSED_DEADLINE)
            API->>DB: Rollback / Release Row Lock
            API-->>UI: HTTP 410 (WRITE_REJECTED_FINALIZATION_COMPLETED)
            UI->>IDB: Transition Cache to EXPIRED_STALE (Preserve for Track B Appeal)
        end
    else Late Manual Submission (T_ingress > official_end_time)
        Student->>UI: Clicks "Submit Examination" (Arriving Late)
        Proxy->>API: Overwrite & Forward X-Request-Arrival-Time (T_ingress > end_time)
        API->>DB: Read ExamAttempt Status (Read-Only Check; NO Finalization Lock)
        Note over API,DB: Status left unchanged (IN_PROGRESS); NO auto-closure; NO grading triggered
        API-->>UI: HTTP 410 (MANUAL_SUBMISSION_REJECTED_DEADLINE_EXCEEDED)
        UI->>IDB: Transition Cache to EXPIRED_STALE (Preserve Diagnostics for Track B Appeal)
    end

    opt Background Deadline Supervisor Finalization (After Drain Window)
        Note over Supervisor,DB: Initiates strictly at server_time >= official_end_time + Δ_drain (15s)
        Supervisor->>DB: SELECT * FROM ExamAttempt WHERE id = attempt_id FOR UPDATE
        alt Attempt Still IN_PROGRESS
            Supervisor->>DB: UPDATE ExamAttempt SET status=AUTO_CLOSED_DEADLINE, closed_at=end_time, committed_at=now()
            Supervisor->>DB: Commit Transaction & Release Row Lock
            Supervisor->>Supervisor: Enqueue Asynchronous MCQ Grading (Post-Commit)
        else Attempt Already Finalized (SUBMITTED or AUTO_CLOSED_DEADLINE)
            Supervisor->>DB: Rollback / Release Row Lock (Idempotent No-Op Exit)
        end
    end
```
---

## 14. Evaluation & Results Publication Architecture

```mermaid
flowchart TD
    AttemptSubmitted["Attempt Submitted / Auto-Closed"] --> MCQEngine["MCQ Auto-Scoring Engine"]
    MCQEngine --> MCQScore["MCQ Marks Calculated & Stored"]

    AttemptSubmitted --> FacultyQueue["Faculty Grading Queue"]
    FacultyQueue --> AssignedFaculty["Assigned Faculty Evaluator"]
    AssignedFaculty --> GradingUI["Side-by-Side Evaluation Interface"]
    GradingUI --> SaveMarks["Enter Question Marks & Remarks"]
    SaveMarks --> SubmitGrading["Submit Evaluation (Locked)"]

    MCQScore --> ResultsCollation["Results Collation Service"]
    SubmitGrading --> ResultsCollation

    ResultsCollation --> DraftResult["Draft Result Record"]
    DraftResult --> CommitteeReview["Admin / Exam Committee Review"]
    CommitteeReview -->|Approved| ApprovedResult["Approved Result"]
    ApprovedResult -->|Publish Action| PublishedResult["Published Result (Live to Students)"]

    PublishedResult --> StudentDashboard["Student Views Verified Marksheet"]
```

---

## 15. Auditability, Security & Privacy

### 15.1 Centralized Audit Trail

1. **Comprehensive Event Logging:** Every critical state transition (Enrollment approval, Eligibility override, Roll generation, PIN reissue, Mark change, Result publication) records:
   - `actor_id` (User who performed the action).
   - `action_type` (e.g., `ELIGIBILITY_OVERRIDE`, `MARK_MODIFIED`, `PIN_REISSUED`).
   - `target_model` & `target_id`.
   - `previous_state` & `new_state` (JSON diff).
   - `ip_address` & `user_agent`.
   - `timestamp` (UTC).
2. **Secret Hygiene:** Audit payloads strictly scrub passwords, plain PINs, and session tokens.
3. **Data Protection:** Student personal data, admit cards, and answer sheets are accessible strictly by authorized personnel via authenticated endpoints.

### 15.2 Cross-Site Scripting (XSS) Defenses & Session Hardening

> [!SECURITY]
> **Accurate Security Boundary Statement:** The system does **not** claim that HTTP-only cookies provide "complete" or "total" protection against XSS. While the `HttpOnly` flag successfully prevents client-side JavaScript from directly reading `document.cookie` (stopping direct credential exfiltration), it **does not** prevent an attacker who successfully executes arbitrary script from issuing authenticated same-origin requests ("session riding") on behalf of the candidate. Comprehensive defense-in-depth is therefore required and enforced.

To defend against XSS and protect session integrity, the architecture enforces multiple defense layers:

1. **Context-Aware Output Encoding & Safe Templating:**
   - React JSX inherently escapes values before rendering, neutralizing standard HTML and script injection vectors.
   - Raw HTML injection points (e.g., `dangerouslySetInnerHTML`) are strictly prohibited in user-facing views; any rich-text rendering is sanitized using `DOMPurify`.
2. **Strict Content Security Policy (CSP):**
   - Nginx and Django `django-csp` headers enforce a strict policy:
     ```http
     Content-Security-Policy: default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data: blob:; object-src 'none'; frame-ancestors 'none'; base-uri 'self';
     ```
   - Restricts script execution strictly to same-origin application bundles; completely disallows inline scripts (`unsafe-inline` in `script-src`) and script evaluation (`unsafe-eval`).
3. **Input Validation & Sanitization:**
   - All incoming textual payloads (student registration inputs, descriptive answers, remarks) are validated and sanitized on the backend using Django serializer validators.
4. **Dependency Security Auditing:**
   - Automated CI vulnerability scanning via `npm audit` for frontend libraries and `pip audit` / `safety` for Python packages to guard against supply-chain vulnerabilities.
5. **Session Hardening & CSRF Protection:**
   - Session cookies are configured with `HttpOnly=True`, `SameSite='Lax'` (or `'Strict'`), and `Secure=True` (HTTPS).
   - Combined with Django's double-submit CSRF tokens (`X-CSRFToken`) on all non-GET requests to prevent cross-site forged transactions.

---

## 16. Deployment & Infrastructure Overview

```
                      +-----------------------------+
                      |   Cloud / College Server    |
                      |  (Linux Ubuntu 22.04 LTS)   |
                      +-----------------------------+
                                     |
           +-------------------------+-------------------------+
           |                                                   |
+---------------------+                             +---------------------+
|    Nginx (Port 443) |                             | MySQL 8.0 (Port 3306|
| - SSL / TLS         |                             | - InnoDB Engine     |
| - Reverse Proxy     |                             | - UTF8MB4 Collation |
| - Static Vite Dist  |                             +---------------------+
+---------------------+                                        |
           | (Unix Socket)                                     |
+---------------------+                             +---------------------+
| Gunicorn (Django WSGI)                            | Redis (Port 6379)   |
| - 4 Worker Processes|-----------------------------| - Celery Broker     |
| - Python 3.11+ Venv |                             | - Rate Limit Cache  |
+---------------------+                             +---------------------+
           |                                                   |
+---------------------+                                        |
| Celery Worker Daemon|----------------------------------------+
| - ReportLab PDFs    |
| - Email Dispatch    |
+---------------------+
```

---

## 17. Architecture Decisions & Trade-Offs

| Decision | Alternative Considered | Selected Rationale |
| :--- | :--- | :--- |
| **ReportLab for PDF** | WeasyPrint | ReportLab is pure Python with zero OS package dependencies. WeasyPrint requires complex system libraries (cairo, pango, gdk-pixbuf) that complicate deployment. |
| **Session Cookies for Web** | LocalStorage JWT | `HttpOnly` SameSite cookies prevent client-side JavaScript from directly reading the cookie, mitigating raw token exfiltration. Defense-in-depth (CSP, context-aware encoding, safe rendering) protects against XSS-driven session riding. |
| **Monolith vs Microservices**| Microservices | Microservices introduce distributed transaction risks and operational overhead inappropriate for a single college deployment. |
| **Hashed Exam PINs** | Plaintext PINs in DB | If the database is compromised, plaintext PINs would allow unauthorized exam access. Hashing ensures zero-knowledge security. |
| **Private File Storage** | Public S3 / Media root | Descriptive answer scripts and admit cards contain private student academic data; public URLs present severe privacy violations. |
| **Encrypted Offline Cache & Dual-Track Key Recovery** | Plaintext IndexedDB / localStorage | Plaintext browser storage fails the shared-device threat model. AES-256-GCM at rest protects answers against extraction via browser DevTools on shared workstations. In-memory DEK is zeroed on tab close/logout. Dual-track key recovery separates active live exam resumption (Track A, server time $\le$ deadline, write-enabled) from post-deadline read-only evidence recovery (Track B, within configurable retention period, read-only). Zero credentials or PINs are stored locally as wrapping secrets. |
| **Bounded-Processing Consistency Protocol (Option B)** | Unrealistic absolute admission guarantees or non-atomic distributed locks | Web applications cannot prevent operating system socket backlogs or worker queueing under extreme load. Option B defines an explicit Application Admission Window ($\Delta_{\text{drain}} = 15\text{s}$) and coordinates admission and finalization strictly through MySQL InnoDB ACID row locks (`SELECT ... FOR UPDATE` on `ExamAttempt`). Eliminates TOCTOU gaps and Redis dependencies. Requests delayed past the drain window are rejected with HTTP 410 and preserved in local diagnostic recovery bundles for appeal. Late requests arriving after the deadline are rejected immediately without altering attempt status, preventing premature auto-closure while earlier on-time requests remain in socket queues. |
| **Evidence Retention State Machine & Activation Gate** | Unrestricted / unconfigured default retention | Unconfigured retention periods leave key lifecycle undefined. The four-state configuration machine (`UNCONFIGURED` -> `CONFIGURED` -> `EXPIRED` / `LEGAL_HOLD`) enforces a hard production activation gate: no examination can be published or scheduled until college administration explicitly approves and signs an integer retention policy. |

## 18. Open Questions & Future Confirmation

The following policy and configuration items are flagged for institutional/college confirmation during data modeling (Chunk 02) and configuration setup:
1. **Official Gauhati University Roll-Number Pattern:** The generator is built to be configurable with parameterized templates; the exact pattern template will be populated once supplied by the college.
2. **Examination PIN Delivery Policy:** Mandatory institutional decision whether to configure PIN printing on admit cards or just-in-time delivery via SMS/portal/invigilators. System strictly prevents PIN generation while `EXAM_PIN_DELIVERY_METHOD` remains `UNCONFIGURED`.
3. **Late-Entry Cutoff Duration:** Institutional confirmation of the permitted entry window (`entry_cutoff_time`, e.g. 15 or 30 minutes past `start_time`), after which new attempts cannot be initialized.
4. **Descriptive Answer Upload Quotas:** Confirmation of provisional defaults (maximum 3 files, 5 MB per file, PDF/JPEG/PNG) or college-specific size/count limits.
5. **Answer Script Data Retention Schedule:** Confirmation of the duration scripts are retained in active storage post-result publication before archival or purging (recommended: 6 to 12 months).
6. **Grading & GPA Scale:** Raw component scores are implemented as the baseline; 10-point letter grade conversions (O, A+, A, etc.) and SGPA/CGPA formulas will be added upon confirmation of official GU tables.
7. **Institutional Evidence Key Retention Approval & Activation Gate:** Confirmation of the institutional retention period (`EXAM_EVIDENCE_KEY_RETENTION_PERIOD`, recommended baseline 14–30 days) by college administration. System strictly blocks examination publication and activation while unconfigured. Confirmation of administrative workstation sanitization schedules and student evidence export protocols prior to lab PC reboots.
8. **Optional High-Entropy Offline Encryption Recovery Secret (Unresolved Design Decision):** Documenting the trade-off of generating an optional, separate high-entropy recovery secret (e.g., 128-bit random alphanumeric passphrase or base58 recovery token) printed or physically distributed by proctors to allow offline DEK unwrapping during total server outages. Due to substantial operational overhead in generating, securely distributing, proctor tracking, and managing lost secrets across thousands of candidates, this is NOT implemented by default; server-assisted key release remains the standard baseline.
