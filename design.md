# College Online Examination System --- Master Design

> **Purpose:** This file is the authoritative project instruction and
> design baseline for the AI coding agent.
>
> **Development rule:** Work in small chunks. Complete the current
> chunk, audit it, report the result, and stop. Do not begin the next
> chunk until the user explicitly approves it.

------------------------------------------------------------------------

## 1. Project Overview

Build a secure, responsive online examination system for a college using
the Gauhati University FYUGP academic structure as the intended academic
context.

The system must support:

-   Multiple programmes, departments, semesters, subjects and papers.
-   Subject-wise student registration and examination eligibility.
-   MCQ and descriptive examinations.
-   Admin, faculty/examiner and student roles.
-   General examination creation by an administrator.
-   Unique examination roll numbers and individual admit cards.
-   PDF admit-card generation and email delivery.
-   Online examination delivery, answer saving and submission.
-   MCQ auto-evaluation and faculty evaluation of descriptive answers.
-   Result preparation, approval and publication.

The system is for a college-level deployment. Do not assume it is an
official Gauhati University platform or that it has direct integration
with Gauhati University systems.

## 2. Non-Negotiable Development Rules

1.  **Chunk-by-chunk development:** Work only on the currently assigned
    chunk.
2.  **Audit before progression:** Every chunk must include
    implementation evidence, tests and an audit report.
3.  **Approval gate:** Stop after each chunk. Never start another chunk
    unless the user explicitly approves.
4.  **No silent scope changes:** Do not add major features, remove
    requirements or change architecture without explaining the reason
    and obtaining approval.
5.  **No invented academic rules:** Do not invent official FYUGP/GU
    subject combinations, credit rules, paper codes, eligibility rules
    or examination regulations. Make academic structures configurable
    and flag unknown rules for confirmation.
6.  **Inspect before modifying:** Before editing an existing project,
    inspect its structure and current state. Preserve working code
    unless a change is required and explained.
7.  **Security by design:** Enforce authorization and eligibility on the
    backend. Never rely only on frontend checks.
8.  **Data integrity:** Use database constraints and transactions for
    important operations such as enrollment, eligibility generation,
    credential issuance and exam submission.
9.  **No fake completion:** Do not claim a feature or test works unless
    it has actually been implemented or executed. Clearly identify
    untested items.
10. **Keep documentation current:** Update progress, architecture,
    database and API documentation when relevant to an approved chunk.
11. **Prefer a modular monolith:** Do not introduce microservices unless
    the user approves a justified need.
12. **Ask when blocked:** If an unresolved requirement affects
    correctness, security, academic policy or data structure, document
    it and ask instead of guessing.

## 3. Product Scope

### 3.1 Included in the initial version

-   Responsive web application for desktop, tablet and mobile browsers.
-   Role-based login and access control.
-   Academic session, programme, department, semester, subject and paper
    management.
-   Student and faculty records.
-   Student subject/paper enrollment records.
-   Faculty-to-subject assignments.
-   MCQ and descriptive exam creation.
-   Eligibility calculation based on actual subject/paper registration.
-   Examination roll number allocation.
-   Admit-card PDF generation.
-   Email delivery with delivery status and retry support.
-   Online exam interface.
-   Autosave and server-side submission/deadline enforcement.
-   MCQ automatic marking.
-   Descriptive answer evaluation by assigned faculty.
-   Result calculation, approval and publication.
-   Audit logs for important administrative and examination actions.

### 3.2 Out of scope unless separately approved

-   Advanced AI or webcam-based proctoring.
-   Biometric attendance.
-   Online payments.
-   Native Android/iOS applications.
-   Direct integration with Gauhati University systems.
-   Automated import from external university portals.
-   Complex analytics beyond essential examination reports.
-   Multi-college SaaS tenancy.
-   AI-based descriptive answer grading.

Keep the architecture extensible, but do not implement these features in
the initial version.

## 4. User Roles and Permissions

### 4.1 Administrator

The administrator can:

-   Manage academic sessions and configurable academic structures.
-   Manage programmes, departments, semesters, subjects and papers.
-   Create and manage student and faculty accounts.
-   Manage student academic records and subject registrations.
-   Assign faculty to subjects/papers.
-   Create and configure examinations.
-   Review and confirm eligible-student lists.
-   Generate examination roll numbers and admit cards.
-   Initiate and monitor email delivery.
-   Monitor examination status.
-   Manage result approval and publication.
-   View audit logs and system reports.

Sensitive actions must be logged. Use confirmation steps for destructive
or irreversible operations.

### 4.2 Faculty / Examiner

Faculty can:

-   View only assigned subjects/papers and authorized examinations.
-   Manage question content where permitted.
-   Review descriptive answers assigned to them.
-   Enter marks and evaluation remarks where configured.
-   Save evaluation progress.
-   Submit completed evaluations.
-   View relevant examination and evaluation summaries.

Faculty must not access unrelated student records, answer scripts or
examinations.

### 4.3 Student

Students can:

-   Sign in securely.
-   View their profile and academic information.
-   View their registered subjects/papers.
-   View examinations for which they are eligible.
-   Download their own admit cards.
-   Access an examination only during its permitted availability window.
-   Save answers and submit the examination.
-   View submission confirmation and published results.

Students must never be able to view another student's private profile,
admit card, answers or results.

## 5. Academic Structure and FYUGP Configuration

Represent academic data in a configurable hierarchy. A suggested
structure is:

-   College
    -   Academic session
    -   Programme
        -   Department or discipline, where applicable
        -   Semester
            -   Subject or course
                -   Paper or offering
                    -   Subject category
                    -   Credits and other configurable academic
                        attributes

Support configurable subject categories such as:

-   Major
-   Minor
-   MDC
-   AEC
-   SEC
-   VAC

These categories are configuration values, not hardcoded assumptions
about which student must take which combination.

### Academic data rules

-   A student belongs to a programme and academic session and has a
    semester/current academic status.
-   A student may register for multiple subjects or papers in one
    semester.
-   Student-to-subject/paper registration must be represented
    explicitly.
-   A paper offering should identify the relevant academic session,
    semester and subject/category as applicable.
-   Store paper codes and credit values as configurable data.
-   Do not infer enrollment from programme, department or semester
    alone.
-   Preserve historical academic records when a student progresses to
    another semester.
-   Define how repeat/backlog papers are represented only after the
    college confirms the policy.
-   Record the source and date of important enrollment changes where
    practical.

**Critical eligibility rule:** A student is eligible for an examination
only when there is a valid, active registration for the exact
subject/paper offering being examined, subject to any additional
college-approved eligibility rules. Semester or department membership
alone is insufficient.

## 6. Examination Workflow

The intended workflow is:

1.  Administrator creates an examination.
2.  Administrator selects the academic session, programme/semester
    scope, subject category and exact subject/paper offering.
3.  Administrator sets examination type, date, start time, duration,
    marks, instructions and applicable settings.
4.  The eligibility engine identifies students with valid registrations
    for the selected paper offering.
5.  Administrator reviews the eligible-student list and resolves
    exceptions.
6.  After confirmation, the system allocates unique examination roll
    numbers or tokens within the defined scope.
7.  The system generates an individual admit-card PDF for each eligible
    student.
8.  The system emails each admit card to the student's registered email
    address.
9.  Students sign in and access only examinations for which they are
    eligible.
10. Students answer questions; answers are saved according to the
    autosave strategy.
11. Students submit, or the server automatically closes/submits the
    attempt at the deadline according to the approved policy.
12. MCQ answers are evaluated automatically.
13. Descriptive answers are evaluated by authorized faculty.
14. Results are calculated, reviewed, approved and published.
15. Students can view results after publication.

Each transition must have a defined status and permitted actor. Do not
allow a user to skip required workflow states.

## 7. Examination Configuration

An examination should support, as applicable:

-   Examination title/name.
-   Academic session.
-   Programme and semester scope.
-   Subject category.
-   Exact subject/paper offering.
-   Examination type: MCQ, descriptive or mixed, if mixed mode is
    approved.
-   Examination date.
-   Start and end time or duration.
-   Maximum marks and pass criteria, if supplied by the college.
-   Question/section configuration.
-   Instructions.
-   Eligibility snapshot or confirmed eligibility record.
-   Status and publication controls.

Do not assume grading, negative marking, pass marks, grace marks,
moderation or revaluation policies. Make these configurable only after
the relevant policy is confirmed.

Suggested lifecycle statuses:

`DRAFT → CONFIGURED → ELIGIBILITY_REVIEW → READY → ADMIT_CARDS_GENERATED → SCHEDULED → LIVE → SUBMISSION_CLOSED → EVALUATION → RESULT_REVIEW → PUBLISHED`

The exact state transitions should be documented and enforced. Include
cancellation or archival states where needed.

## 8. Eligibility Engine

Eligibility must be computed on the backend.

The engine must:

-   Identify the exact paper offering selected for the examination.
-   Find students with an active registration for that offering.
-   Apply only additional eligibility rules explicitly configured and
    approved by the college.
-   Exclude inactive, withdrawn or invalid registrations according to
    confirmed policy.
-   Avoid duplicate eligible records.
-   Record when eligibility was calculated and by whom.
-   Allow the administrator to review the list before final
    confirmation.
-   Record approved manual additions/removals with a reason and audit
    entry.
-   Preserve a snapshot of the confirmed eligibility list for the
    examination.

Revalidate eligibility and exam status at the point of exam access. Do
not trust a student ID, roll number or client-side flag sent by the
browser.

## 9. Examination Roll Number and Admit Card

### 9.1 Roll number

-   Generate a unique examination roll number for each eligible student
    within the defined examination scope.
-   Define the format only after the college confirms any required
    convention.
-   Prevent duplicate allocation using database constraints.
-   Preserve the mapping between student, examination and allocated roll
    number.
-   Do not expose internal database IDs as examination credentials.

### 9.2 Secure access credential

A visible roll number is an identifier, not a secret. Do not use the
roll number alone as authentication.

Use a separate secure credential, such as a random PIN or one-time
activation credential, according to the approved login design. Store
only a secure hash of reusable credentials. Never include plaintext
passwords or reusable secrets in ordinary logs.

### 9.3 Admit card

Each admit card should contain only the required information, such as:

-   College identity and examination title.
-   Student name and approved student identifier.
-   Examination roll number.
-   Programme, semester and subject/paper details.
-   Examination date, time and duration.
-   Examination instructions.
-   Photo/signature or other fields only if the college requires them.

Generate a separate PDF for each eligible student. Verify that each PDF
is associated with the correct student and examination.

### 9.4 Email delivery

-   Send the PDF to the student's registered email address.
-   Track queued, sent, failed and retry states.
-   Do not treat a queued message as successfully delivered.
-   Support safe retries without generating duplicate or conflicting
    admit-card records.
-   Keep email delivery logs without storing unnecessary sensitive
    content.
-   Allow authorized administrators to inspect failures and retry
    delivery.

Use a background job mechanism for bulk PDF/email tasks when
appropriate.

## 10. Authentication and Authorization

Use a unified sign-in system with role-based routing.

The final login experience must support the college-approved identity
method. The initial recommendation is:

-   Admin/faculty/student: registered username or email plus password.
-   Examination access: the student's account plus the relevant
    examination authorization; if a separate examination PIN is
    required, treat it as an additional credential, not as a substitute
    for backend eligibility checks.

If the college requires roll-number-based login, use roll number plus a
separate secret credential. Never authenticate with a publicly visible
roll number alone.

Security requirements:

-   Hash passwords using a modern password-hashing method supported by
    the backend framework.
-   Use secure session/JWT handling appropriate to the deployment.
-   Enforce role and object-level permissions on every protected API.
-   Rate-limit login and credential verification.
-   Provide secure password reset or administrator-managed recovery.
-   Avoid revealing whether a particular account exists during failed
    login.
-   Use HTTPS in production.
-   Protect against CSRF, XSS, SQL injection and insecure direct object
    references.
-   Keep secrets and environment-specific credentials out of source
    control.
-   Log security-relevant events without recording passwords, PINs or
    tokens.

## 11. Examination Engine Requirements

### 11.1 Question types

Initial supported types:

-   MCQ with one correct option.
-   Descriptive/text answer.

A mixed examination may be supported if approved and properly
represented in the examination configuration.

### 11.2 Attempt handling

-   The server is authoritative for start time, deadline and submission
    status.
-   The frontend timer is informational and must not determine the true
    deadline.
-   Save answers automatically at safe intervals and on relevant
    interactions.
-   Show clear save status to the student.
-   Prevent answers from being modified after submission or deadline
    closure.
-   Handle refresh, temporary network loss and duplicate requests
    safely.
-   Use idempotent submission so repeated submit requests do not create
    multiple submissions.
-   Record attempt start, last activity and final submission timestamps.
-   Provide a clear submission confirmation.

### 11.3 Security

-   Never send correct MCQ answers to the student-facing client before
    the exam is closed and policy permits it.
-   Students may access only their own attempt and answers.
-   Validate question IDs and answer ownership on the backend.
-   Do not rely on disabled buttons or hidden UI elements for security.
-   Record important examination events in an audit log.

### 11.4 Deadline behavior

Define and test the exact policy for:

-   A student opening the exam near the deadline.
-   A student losing connectivity.
-   A student submitting at the deadline.
-   Automatic closure when time expires.
-   A request arriving after the deadline.
-   An administrator cancelling or rescheduling an exam.

The backend must enforce the approved policy consistently.

## 12. Evaluation and Results

### MCQ evaluation

-   Evaluate using server-side answer keys.
-   Support configurable marks per question if required.
-   Support negative marking only if explicitly approved.
-   Ensure repeated evaluation does not duplicate marks.

### Descriptive evaluation

-   Assign scripts to authorized faculty/examiners.
-   Allow marks and remarks according to the approved marking scheme.
-   Track draft and submitted evaluation states.
-   Prevent unauthorized changes after finalization, except through an
    approved correction workflow.
-   Keep an audit trail of mark changes.

### Results

-   Calculate totals and other grade fields only from approved rules.
-   Keep draft/reviewed/approved/published states distinct.
-   Students must not see unpublished results.
-   Record who approved and published results and when.
-   Provide a controlled correction process after publication.
-   Do not invent grade bands, SGPA/CGPA formulas, pass criteria or
    rounding rules. Confirm the applicable college/university policy
    first.

## 13. Suggested Technology Stack

Use this stack unless the Chunk 00 audit identifies a concrete
compatibility or operational reason to propose a change:

  Layer                   Preferred technology
  ----------------------- --------------------------------------------------
  Frontend                React
  Build tooling           Vite
  Styling                 Tailwind CSS
  Routing                 React Router
  Backend                 Python Django
  API                     Django REST Framework
  Database                MySQL
  Background jobs         Celery, if required
  Broker/cache            Redis, if required
  PDF generation          WeasyPrint or ReportLab
  Email                   SMTP or an approved transactional email provider
  Production web server   Nginx
  Application server      Gunicorn or an appropriate ASGI server

Use supported, stable versions and record the chosen versions in project
documentation. Do not add Redis, Celery or Channels until the use case
and deployment requirements justify them.

## 14. Architecture Principles

-   Build a modular monolith with clearly separated application modules.
-   Keep business rules in backend services/domain logic, not only in
    React components.
-   Use REST APIs with consistent validation and error responses.
-   Keep database migrations version-controlled.
-   Use database transactions for multi-step critical operations.
-   Add indexes for common academic, enrollment, eligibility and
    examination lookups.
-   Use pagination and filtering for large student/exam lists.
-   Keep file storage configurable; do not assume local disk is suitable
    for production.
-   Separate development, testing and production configuration.
-   Provide backups and a tested restore procedure before production
    use.

Suggested backend modules (names may be adjusted during architecture
design):

-   `accounts`
-   `academics`
-   `students`
-   `faculty`
-   `enrollments`
-   `examinations`
-   `admit_cards`
-   `notifications`
-   `questions`
-   `attempts`
-   `evaluations`
-   `results`
-   `audit`

## 15. Suggested Data Model

This is a conceptual starting point, not a final schema. The database
design chunk must validate relationships, constraints, indexes and
naming.

Potential entities:

-   `College`
-   `AcademicSession`
-   `Programme`
-   `Department`
-   `Semester`
-   `Subject`
-   `PaperOffering`
-   `SubjectCategory`
-   `User`
-   `StudentProfile`
-   `FacultyProfile`
-   `StudentAcademicRecord`
-   `StudentSubjectEnrollment`
-   `FacultySubjectAssignment`
-   `Examination`
-   `ExaminationEligibility`
-   `ExaminationRollNumber`
-   `AdmitCard`
-   `ExaminationCredential`
-   `EmailDeliveryLog`
-   `Question`
-   `QuestionOption`
-   `ExamAttempt`
-   `StudentAnswer`
-   `Evaluation`
-   `Result`
-   `ResultPublication`
-   `AuditLog`

Important relationship expectations:

-   Students can have multiple subject/paper enrollments.
-   Each enrollment must point to a specific student and paper offering.
-   Faculty assignments must identify the subject/paper and applicable
    academic scope.
-   An examination must target a specific paper offering or a clearly
    defined set of offerings.
-   Eligibility records must link a student to an examination.
-   Roll number allocation must be unique within its defined scope.
-   Attempts and answers must be linked to the correct student and
    examination.
-   Results must be linked to the relevant examination/student and
    publication state.

The final schema must define uniqueness, foreign keys, deletion behavior
and historical-record preservation.

## 16. Privacy, Security and Auditability

-   Collect only information needed for college and examination
    operations.
-   Restrict access to student personal data and examination records.
-   Apply least-privilege access for all roles.
-   Keep an audit trail for academic enrollment changes, eligibility
    overrides, roll-number allocation, admit-card generation, exam
    cancellation, evaluation changes and result publication.
-   Record actor, action, target, timestamp and relevant change context.
-   Do not log passwords, PINs, access tokens or full authentication
    secrets.
-   Protect uploaded files and generated PDFs from public access.
-   Use secure, expiring download links or authenticated downloads where
    appropriate.
-   Define backup retention and access policy with the college before
    production.
-   Follow applicable institutional and legal data-protection
    requirements.

## 17. Testing Requirements

Every relevant chunk must add or update tests.

Minimum test categories:

-   Unit tests for academic and examination business rules.
-   API tests for authentication, authorization and validation.
-   Eligibility tests proving that only registered students qualify.
-   Tests for duplicate prevention and transaction rollback.
-   Admit-card mapping tests to detect wrong-student PDFs.
-   Email job retry and status tests.
-   Exam timing and deadline tests.
-   Autosave and idempotent submission tests.
-   MCQ evaluation tests.
-   Descriptive evaluation permission tests.
-   Result visibility and publication tests.
-   Responsive UI checks for key student and admin flows.

Include negative tests: unauthorized users, wrong paper, inactive
enrollment, duplicate requests, expired exam, submitted attempt and
unpublished result.

Never report tests as passed unless they were actually run. Include the
command and result in the audit report.

## 18. Development Chunks

Complete these chunks in order. The user may approve changes to the
order, but the agent must not change it independently.

  -----------------------------------------------------------------------
  Chunk                   Name                    Main outcome
  ----------------------- ----------------------- -----------------------
  00                      Requirements audit      Resolve ambiguities,
                                                  confirm scope and
                                                  record decisions

  01                      System architecture     Architecture, modules,
                                                  API boundaries and key
                                                  workflows

  02                      Database architecture   ERD, schema,
                                                  constraints, indexes
                                                  and migration plan

  03                      Project initialization  Frontend/backend setup,
                                                  configuration and
                                                  health checks

  04                      Authentication and      Login, role permissions
                          roles                   and account security

  05                      FYUGP academic          Configurable sessions,
                          management              programmes, semesters,
                                                  subjects and papers

  06                      Student and faculty     Profiles, records and
                          management              faculty assignments

  07                      Subject registration    Enrollment management
                                                  and history

  08                      General examination     Examination setup and
                          creation                lifecycle

  09                      Eligibility engine      Exact
                                                  paper-registration
                                                  eligibility and review

  10                      Admit cards and email   Roll numbers, PDF
                                                  generation and delivery
                                                  tracking

  11                      Examination engine      Questions, attempts,
                                                  autosave, timing and
                                                  submission

  12                      Evaluation and results  MCQ marking,
                                                  descriptive evaluation
                                                  and result publication

  13                      Admin and faculty       Role-specific
                          dashboards              administrative
                                                  workflows

  14                      Student dashboard       Profile, subjects,
                                                  admit cards, exams and
                                                  results

  15                      Security and testing    Cross-system security,
                          audit                   reliability and
                                                  regression testing

  16                      Deployment              Production
                                                  configuration, backup,
                                                  monitoring and release
                                                  checklist
  -----------------------------------------------------------------------

### Chunk execution rule

For each chunk:

1.  Read this `design.md` and all relevant existing documentation.
2.  Read the previous chunk's audit report and decisions.
3.  Inspect the current codebase before changing files.
4.  State the exact scope and files/modules expected to change.
5.  Identify dependencies and risks.
6.  Implement only the approved chunk.
7.  Run relevant tests, linting, type checks and build checks.
8.  Review security, data integrity and edge cases relevant to the
    chunk.
9.  Update relevant documentation.
10. Create an audit report in `docs/audits/`.
11. Summarize changed files, commands run, results, known issues and
    unresolved questions.
12. Stop and wait for explicit user approval.

## 19. Mandatory Audit and Approval Gate

Every chunk must produce an audit report at:

`docs/audits/chunk-XX-<short-name>-audit.md`

The report must include:

1.  Chunk number and name.
2.  Scope assigned.
3.  Scope completed.
4.  Files created, modified or deleted.
5.  Design decisions made and their rationale.
6.  Tests and validation commands executed.
7.  Actual test/build/lint results.
8.  Security review.
9.  Data integrity and migration review, where relevant.
10. Known defects and limitations.
11. Unresolved questions and assumptions.
12. Documentation updated.
13. Final audit status.

Use one of these statuses:

-   **PASS** --- Requirements for this chunk are met and relevant checks
    pass.
-   **PASS WITH WARNINGS** --- Core requirements are met, but documented
    non-blocking issues remain.
-   **FAIL** --- Requirements or required checks are not met.
-   **BLOCKED** --- Work cannot safely continue because a decision,
    dependency or external input is missing.

A chunk is not approved merely because the agent says it is complete.
The user reviews the audit report and explicitly authorizes the next
chunk.

If the audit is FAIL or BLOCKED, do not proceed. Fix the current chunk
or ask the user for the missing decision.

## 20. Required Project Documentation

Maintain these documents as the project develops:

-   `design.md` --- This master specification and workflow contract.
-   `docs/architecture.md` --- System architecture and module
    boundaries.
-   `docs/database.md` --- ERD, tables, relationships, constraints and
    indexes.
-   `docs/api.md` --- API endpoints, request/response contracts and
    permissions.
-   `docs/development-progress.md` --- Current chunk, status, completed
    work and next approved action.
-   `docs/decisions/` --- Important decisions and their rationale.
-   `docs/audits/` --- Per-chunk audit reports.

Do not overwrite earlier audit reports. Keep a traceable history of
decisions and progress.

## 21. Initial Project State

At the time this file is first created:

-   Project status: **NOT STARTED**
-   Current chunk: **CHUNK 00 --- REQUIREMENTS AUDIT**
-   Completed chunks: **NONE**
-   Next permitted action: Inspect the project and perform the Chunk 00
    requirements audit.
-   Implementation permission: **NOT GRANTED**
-   Chunk 01 permission: **NOT GRANTED**

If an existing project is present, inspect it read-only during Chunk 00.
Do not initialize, restructure or modify application code during the
requirements audit.

## 22. Antigravity Instruction --- Chunk 00

When starting the project, use the following task instruction:

> Read `design.md` completely. Work only on **CHUNK 00 --- REQUIREMENTS
> AUDIT**.
>
> First inspect the existing project directory in read-only mode. Do not
> create, delete, rename or modify application files. If the directory
> is empty, report that fact.
>
> Audit the requirements in `design.md`. Specifically examine:
>
> -   Project scope and user roles.
> -   Configurable Gauhati University FYUGP academic hierarchy.
> -   Student subject/paper enrollment and historical records.
> -   Faculty subject assignments.
> -   General examination creation.
> -   Exact subject/paper eligibility rules.
> -   Examination roll number and separate secure credential design.
> -   Admit-card PDF generation and email delivery.
> -   MCQ and descriptive examination workflows.
> -   Server-side timing, autosave and submission.
> -   Evaluation, result approval and publication.
> -   Security, privacy, auditability, backups and deployment
>     assumptions.
> -   Technology stack feasibility and project risks.
>
> Separate findings into:
>
> 1.  Requirements clearly confirmed by the specification.
> 2.  Proposed technical decisions that can be accepted or changed.
> 3.  Missing requirements.
> 4.  Ambiguities requiring user/college confirmation.
> 5.  Conflicts, risks and recommendations.
>
> Do not invent official Gauhati University academic or examination
> rules. Clearly flag every policy that requires confirmation.
>
> Create only `docs/audits/chunk-00-requirements-audit.md` if the
> documentation directory does not already contain conflicting work. If
> creating that file would require modifying or overwriting existing
> work, stop and report the conflict instead.
>
> The audit report must include the project inspection, requirements
> summary, ambiguity list, risk review, recommended decisions, concise
> questions for the user, and a final status of PASS, PASS WITH
> WARNINGS, FAIL or BLOCKED.
>
> Do not modify this `design.md`. Do not implement the application. Do
> not begin Chunk 01. At the end, summarize the audit and **stop for
> explicit user approval**.

------------------------------------------------------------------------

**End of master design specification.**
