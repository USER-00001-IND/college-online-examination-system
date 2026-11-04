# Architectural Decision Proposal: Administrator-to-College Membership Architecture
## Final Design Addendum — Authorization, Concurrency and Audit Retention

**Project:** College Online Examination System  
**Academic Context:** Gauhati University FYUGP Context (College Level)  
**Target Domain:** Domain A: Identity, Authentication & Role-Based Access Control  
**Document ID:** `PROP-CHUNK-06-ADMIN-MEMBERSHIP-FINAL-ADDENDUM`  
**Status:** **FINAL DESIGN ADDENDUM — PENDING INDEPENDENT AUDIT AND PROJECT-OWNER APPROVAL**  
**Author:** Antigravity Engineering Team  
**Date:** 2026-11-04  
**Last Independently Audited Commit:** `f3655b7763c8c5b75d989005fe027f55b1bc5128`  
**Impacted Stage:** Chunk 06 (Student and Faculty Management) / Chunk 04 RBAC Integration  

---

## 1. Executive Summary & Design Revision History

### 1.1 Context and Problem Statement
In the approved 52-table relational database architecture ([`docs/database-architecture.md`](file:///home/zero/Documents/college/docs/database-architecture.md)), institutional scoping exists exclusively for student and faculty accounts via dedicated profile entities:
- Table 6: [`StudentProfile`](file:///home/zero/Documents/college/backend/apps/students/models.py) has a foreign key to `academics_college` (`college_id`).
- Table 7: [`FacultyProfile`](file:///home/zero/Documents/college/backend/apps/faculty/models.py) has a foreign key to `academics_college` (`college_id`).
- Table 1: [`User`](file:///home/zero/Documents/college/backend/apps/accounts/models.py#L44-L107) defines primary role `role = 'ADMIN'`, but contains **no college foreign key**.
- Table 3: [`UserRole`](file:///home/zero/Documents/college/backend/apps/accounts/models.py#L129-L167) assigns granular roles globally across the deployment, with **no college foreign key**.

During the Chunk 06 technical audits, ephemeral caller-injected Python attributes (`actor.college_id`, `actor.college`) were eliminated as security vulnerabilities. A strict **fail-closed** boundary was established in [`backend/apps/accounts/authorization.py`](file:///home/zero/Documents/college/backend/apps/accounts/authorization.py): ordinary administrators fail closed (`return set()`), blocking all college-scoped mutations and queries. Superadministrators (`role == 'SUPERADMIN'` or `is_superuser == True`) retain verified system-wide authority.

### 1.2 Independent Audit Revision History

| Proposal Iteration | Verdict | Findings / Scope |
|---|---|---|
| **Round 1 (`PROP-...-001`)** | REVISION REQUIRED | 5 Findings: Incomplete college scoping, lock-order contradictions, audit deletion risk, SQL/Django constraint mismatches, overstated deployment claims. |
| **Round 2 (`PROP-...-002`)** | CONDITIONAL PASS | Preferred Option B retained; identified 3 remaining specification gaps: Read-operation scoping, in-flight transaction synchronization, durable audit retention. |
| **Final Addendum (Current)** | **PENDING REVIEW** | Resolves Findings P3-A, P3-B, and P3-C; delivers complete 2D read/write RBAC, service locking matrix, and audit retention policy decision. |

### 1.3 Resolution Summary of Final Addendum Findings

| Finding | Severity | Defect Analysis & Root Cause | Final Addendum Resolution & Document Section |
| :---: | :---: | :--- | :--- |
| **P3-A** | **HIGH** | Round 2 specified operation permissions only for mutations; read access (list, detail, search, filter) was unspecified. EXAM_OFFICER was mislabeled as read-only. | Defined 25 explicit read and write operation identifiers; established complete 7-role authorization matrix; modeled multi-college role divergence; designed collection helper `get_authorized_college_ids_for_operation`; mapped indirect college ownership paths. *(Section 8, Section 9)* |
| **P3-B** | **HIGH** | Lock hierarchy did not distinguish actor vs. target users (e.g. registration review locking student user before college); lack of in-flight revocation locking protocol. | Established unified lock hierarchy: Level 1 College $\rightarrow$ Level 2 Actor User $\rightarrow$ Level 3 Membership $\rightarrow$ Level 4 Target Record $\rightarrow$ Level 5 Target Children; specified MySQL 8 InnoDB locking reads; created comprehensive 14-service locking table; designed 10 multi-connection concurrency tests. *(Section 12, Section 13)* |
| **P3-C** | **MEDIUM** | Single mutable membership row overwrites earlier appointment metadata on reappointment; Table 8 only logs auth events; Table 51 is deferred to Chunk 15. | Formulated Policy A (Audit Prerequisite bringing forward Table 51) vs. Policy B (Interim Application Logging); detailed audit event payload schema; recommended Policy A for production; structured explicit owner decision gate. *(Section 10, Section 11)* |

> [!IMPORTANT]
> **Governance Boundary:** This document is an **architecture proposal addendum only**. Implementation authorization is **NOT GRANTED**. No Django models, migrations, serializers, or services have been modified. Protected architecture documents ([`design.md`](file:///home/zero/Documents/college/design.md), [`handover.txt`](file:///home/zero/Documents/college/handover.txt), [`docs/architecture.md`](file:///home/zero/Documents/college/docs/architecture.md), [`docs/database-architecture.md`](file:///home/zero/Documents/college/docs/database-architecture.md)) remain 100% untouched.

---

## 2. Problem Statement: Existing Schema Limitation

### 2.1 The Asymmetry in Institutional Scoping
In the approved 52-table schema ([`docs/database-architecture.md`](file:///home/zero/Documents/college/docs/database-architecture.md)), institutional scoping is defined across Domain A (Identity) and Domain B (Academics):

```
+--------------------------------------------------------------------------------------------------+
| Table                              | User Linkage           | College Linkage   | Institutional  |
+------------------------------------+------------------------+-------------------+----------------+
| Table 1: accounts_user             | Primary Entity (id)    | NONE              | Global role    |
| Table 2: accounts_role             | N/A                    | NONE              | Global code    |
| Table 3: accounts_user_role        | FK -> accounts_user    | NONE              | Global role    |
| Table 6: students_student_profile  | OneToOne accounts_user | FK -> College     | STUDENT only   |
| Table 7: faculty_faculty_profile   | OneToOne accounts_user | FK -> College     | FACULTY only   |
| Table 9: academics_college         | Primary Entity (id)    | Self              | Institution    |
+--------------------------------------------------------------------------------------------------+
```

### 2.2 Operational Deadlock Analysis
1. **Absence of Institutional FK:** Table 1 (`accounts_user`) defines `role = 'ADMIN'`, but does not store an associated college. Table 3 (`accounts_user_role`) allows assigning roles such as `COLLEGE_SUPERADMIN` or `EXAM_OFFICER`, but does so globally without institutional scoping.
2. **Elimination of Runtime Injections:** Finding R4-A demonstrated that caller-injected runtime Python attributes (`admin.college_id = 1`) are non-persistent, forgeable, and violate database referential integrity.
3. **Current Fail-Closed State:** In [`backend/apps/accounts/authorization.py`](file:///home/zero/Documents/college/backend/apps/accounts/authorization.py), `get_actor_authorized_college_ids()` returns an empty set (`set()`) for all ordinary administrators. Consequently, ordinary administrators are currently prevented from executing any college-scoped administrative operations (e.g., student registration review, faculty provisioning, subject assignment).

---

## 3. Architectural Options Evaluation

### 3.1 Option A: User-to-College Direct Relationship (`accounts_user.college_id`)
* **Concept:** Add a nullable foreign key `college_id BIGINT NULL REFERENCES academics_college(id) ON DELETE RESTRICT` to Table 1 (`accounts_user`).
* **Evaluation:**
  - *Advantages:* Zero-join resolution (`request.user.college_id`); minimal query latency.
  - *Deficiencies:*
    1. *Rigid 1:1 Cardinality:* Gauhati University affiliated colleges frequently share administrative personnel (e.g., regional university examination observers, roving nodal officers, cluster college administrators). Option A mechanically prohibits multi-college administration without creating duplicate user accounts (two separate emails and logins), violating single-identity principles.
    2. *Schema Redundancy & Data Inconsistency:* Both `StudentProfile` (Table 6) and `FacultyProfile` (Table 7) already maintain authoritative `college_id` foreign keys. If `accounts_user.college_id` is added, it creates duplicate sources of truth. If a student's `accounts_user.college_id` differs from `student_profile.college_id`, an irreconcilable data conflict arises. If left `NULL` for students and faculty, Table 1 permanently stores a sparse, role-polluted column.
    3. *High Migration & Table Lock Risk:* Table 1 (`accounts_user`) is the central, highest-traffic table in the system, referenced by 14 foreign keys across 9 domains. Executing an `ALTER TABLE` on production MySQL requires metadata locks and risks table locking.
    4. *Lack of Lifecycle & Audit Metadata:* Cannot track appointment dates, granting superadministrators, or revocation justifications.
    5. *Ambiguity with Superadministrator:* Superadministrators have system-wide access across all colleges. On Table 1, a Superadmin would have `college_id = NULL`. An unassigned ordinary admin would also have `college_id = NULL`, requiring brittle conditional logic.

### 3.2 Option B (Recommended): Dedicated Administrative Membership Mapping Table
* **Concept:** Introduce Table 53 (`accounts_administrative_membership`) as an explicit relational junction entity between `accounts_user` and `academics_college`, augmented with mandatory institutional role assignment, tenure tracking, and audit metadata.
* **Evaluation:**
  - *Advantages:*
    1. *Flexible M:N Institutional Support:* Full support for institutional administrators managing a single college, multi-campus institutions, regional university clusters, or roving examination observers.
    2. *Clean Separation of Concerns:* `accounts_user` remains the pure authentication identity; `accounts_administrative_membership` encapsulates institutional appointment and governance.
    3. *Immediate Activation & Revocation Lifecycle:* Administrative access can be granted, suspended, or revoked (`status = 'REVOKED'`, `is_active = FALSE`) without deactivating the underlying user account or deleting records.
    4. *Granular Per-College Role Specialization:* An administrator can hold distinct responsibilities per institution (e.g., `COLLEGE_SUPERADMIN` at College A, and operational examination administrator `EXAM_OFFICER` at College B) via `role_id`.
    5. *Zero Schema Disruption to Existing Tables:* Requires zero modifications to Table 1 (`accounts_user`), Table 2, Table 3, or Table 9. No existing table locks or migrations on production authentication tables.
    6. *Engine-Level Foreign Key Protection:* `ON DELETE RESTRICT` on both `college_id` and `user_id` referentially prevents accidental deletion while active administrative appointments exist.
  - *Disclosed Trade-offs & Mitigations:*
    1. *Schema Expansion (52 to 53 Tables):* Increases the relational table count from 52 to 53. Justified by domain architecture requirements, mirroring Table 17 (`PaperProgrammeMapping`) and Table 20 (`FacultySubjectAssignment`).
    2. *Single Additional Query:* Resolving college scope requires one indexed lookup. Mitigated by indexed covering scans and request-lifecycle caching.

### 3.3 Option C: Reuse Existing Institutional Relationships (REJECTED)
* **Concept:** Force administrators to hold a `FacultyProfile` (Table 7) linked to their college, or store administrator user IDs inside `academics_institutional_config` (Table 21).
* **Rejection Rationale:**
  - *Conflation of Distinct Operational Domains:* Non-teaching administrative staff (Registrars, Academic Deans, Examination Cell In-Charges, Office Superintendents) would require fabricating dummy academic departments, artificial faculty designations, and fictitious employee codes.
  - *Privilege Escalation & Academic Governance Risk:* A college administrator possessing a dummy `FacultyProfile` would become eligible for paper evaluation and grading under Table 20 (`academics_faculty_subject_assignment`), creating severe conflict-of-interest and academic integrity violations.
  - *JSON Anti-Pattern:* Storing user IDs in `academics_institutional_config` lacks foreign keys, row locks, indexing, and invites race conditions.
  - *Verdict:* Strictly **REJECTED**.

---

## 4. Recommended Architecture Overview (Option B)

The proposed architecture adopts **Option B** enhanced with a **Two-Dimensional Institutional Authorization System** (resolving Finding P2-A and P3-A).

Administrative authority requires satisfying two distinct dimensions simultaneously:
$$\text{Authorized Operation} \iff \text{Dimension 1 (Institution Scope)} \land \text{Dimension 2 (Role Permission)}$$

1. **Dimension 1 (Institution Scope):** The acting user must hold an authoritative, active `AdministrativeMembership` record for the target `academics_college` (`is_active = TRUE`, `status = 'ACTIVE'`).
2. **Dimension 2 (Role Permission):** The specific granular role assigned to the user within that institution (`membership.role`) must possess the explicit capability to execute the requested administrative operation (read or write).

---

## 5. Corrected Table 53 SQL Schema Definition

```sql
-- Table 53: Administrative College Membership Mapping (Domain A)
CREATE TABLE accounts_administrative_membership (
    id BIGINT NOT NULL AUTO_INCREMENT,
    user_id BIGINT NOT NULL,
    college_id BIGINT NOT NULL,
    role_id BIGINT NOT NULL,
    status VARCHAR(20) NOT NULL DEFAULT 'ACTIVE',
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    assigned_by_id BIGINT NOT NULL,
    assigned_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
    revoked_by_id BIGINT NULL DEFAULT NULL,
    revoked_at DATETIME(6) NULL DEFAULT NULL,
    revocation_reason TEXT NULL DEFAULT NULL,
    notes VARCHAR(255) NULL DEFAULT NULL,
    
    PRIMARY KEY (id),
    CONSTRAINT uk_admin_mem_user_college UNIQUE (user_id, college_id),
    CONSTRAINT fk_admin_mem_user FOREIGN KEY (user_id) 
        REFERENCES accounts_user(id) ON DELETE RESTRICT,
    CONSTRAINT fk_admin_mem_college FOREIGN KEY (college_id) 
        REFERENCES academics_college(id) ON DELETE RESTRICT,
    CONSTRAINT fk_admin_mem_role FOREIGN KEY (role_id) 
        REFERENCES accounts_role(id) ON DELETE RESTRICT,
    CONSTRAINT fk_admin_mem_assigned_by FOREIGN KEY (assigned_by_id) 
        REFERENCES accounts_user(id) ON DELETE RESTRICT,
    CONSTRAINT fk_admin_mem_revoked_by FOREIGN KEY (revoked_by_id) 
        REFERENCES accounts_user(id) ON DELETE SET NULL,
    CONSTRAINT chk_admin_mem_status CHECK (
        status IN ('ACTIVE', 'SUSPENDED', 'REVOKED')
    ),
    CONSTRAINT chk_admin_mem_active_status CHECK (
        (is_active = TRUE AND status = 'ACTIVE') OR 
        (is_active = FALSE AND status IN ('SUSPENDED', 'REVOKED'))
    )
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

-- Optimized performance indexes
CREATE INDEX idx_admin_mem_lookup ON accounts_administrative_membership (user_id, is_active, college_id, role_id);
CREATE INDEX idx_admin_mem_college_status ON accounts_administrative_membership (college_id, status);
CREATE INDEX idx_admin_mem_role ON accounts_administrative_membership (role_id);
```

---

## 6. Matching Django ORM Model Specification

```python
# Proposed: backend/apps/accounts/models.py (Illustrative Specification — Unimplemented)

from django.db import models
from django.db.models import Q
from django.core.exceptions import ValidationError
from django.utils import timezone


class AdministrativeMembershipStatus(models.TextChoices):
    ACTIVE = 'ACTIVE', 'Active'
    SUSPENDED = 'SUSPENDED', 'Suspended'
    REVOKED = 'REVOKED', 'Revoked'


class AdministrativeMembership(models.Model):
    """
    Administrative College Membership Mapping (Table 53: accounts_administrative_membership).
    Assigns institutional administrative authority to an accounts_user for an academics_college
    with an explicit, mandatory institutional role (Finding P2-A).
    """
    id = models.BigAutoField(primary_key=True)
    user = models.ForeignKey(
        'accounts.User',
        on_delete=models.RESTRICT,
        related_name='administrative_memberships',
        db_column='user_id',
    )
    college = models.ForeignKey(
        'academics.College',
        on_delete=models.RESTRICT,
        related_name='administrative_memberships',
        db_column='college_id',
    )
    role = models.ForeignKey(
        'accounts.Role',
        on_delete=models.RESTRICT,
        related_name='college_administrative_memberships',
        db_column='role_id',
        help_text="Mandatory granular institutional role within this college (Finding P2-A).",
    )
    status = models.CharField(
        max_length=20,
        choices=AdministrativeMembershipStatus.choices,
        default=AdministrativeMembershipStatus.ACTIVE,
    )
    is_active = models.BooleanField(
        default=True,
        db_index=True,
        help_text="Denormalized flag for fast covering-index authorization queries.",
    )
    assigned_by = models.ForeignKey(
        'accounts.User',
        on_delete=models.RESTRICT,
        related_name='granted_administrative_memberships',
        db_column='assigned_by_id',
    )
    assigned_at = models.DateTimeField(default=timezone.now)
    revoked_by = models.ForeignKey(
        'accounts.User',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='revoked_administrative_memberships',
        db_column='revoked_by_id',
    )
    revoked_at = models.DateTimeField(null=True, blank=True)
    revocation_reason = models.TextField(null=True, blank=True)
    notes = models.CharField(max_length=255, null=True, blank=True)

    class Meta:
        db_table = 'accounts_administrative_membership'
        verbose_name = 'Administrative Membership'
        verbose_name_plural = 'Administrative Memberships'
        constraints = [
            models.UniqueConstraint(
                fields=['user', 'college'],
                name='uk_admin_mem_user_college',
            ),
            models.CheckConstraint(
                check=Q(status__in=['ACTIVE', 'SUSPENDED', 'REVOKED']),
                name='chk_admin_mem_status',
            ),
            models.CheckConstraint(
                check=(
                    Q(is_active=True, status='ACTIVE') |
                    Q(is_active=False, status__in=['SUSPENDED', 'REVOKED'])
                ),
                name='chk_admin_mem_active_status',
            ),
        ]
        indexes = [
            models.Index(
                fields=['user', 'is_active', 'college', 'role'],
                name='idx_admin_mem_lookup',
            ),
            models.Index(
                fields=['college', 'status'],
                name='idx_admin_mem_college_status',
            ),
            models.Index(
                fields=['role'],
                name='idx_admin_mem_role',
            ),
        ]

    def clean(self):
        super().clean()
        errors = {}

        # 1. Primary role enforcement: only primary ADMIN users may hold memberships
        if self.user_id:
            from apps.accounts.models import RoleChoices
            if self.user.role != RoleChoices.ADMIN:
                errors['user'] = (
                    f"Administrative membership can only be granted to users with primary role "
                    f"'{RoleChoices.ADMIN}'. User primary role is '{self.user.role}'."
                )

        # 2. Prevent self-grant and self-revocation
        if self.assigned_by_id and self.assigned_by_id == self.user_id:
            errors['assigned_by'] = "Administrators cannot grant administrative memberships to themselves."
        if self.revoked_by_id and self.revoked_by_id == self.user_id:
            errors['revoked_by'] = "Administrators cannot revoke their own administrative memberships."

        # 3. Status and is_active coherence
        if self.status == AdministrativeMembershipStatus.ACTIVE and not self.is_active:
            errors['is_active'] = "Active status requires is_active=True."
        if self.status != AdministrativeMembershipStatus.ACTIVE and self.is_active:
            errors['is_active'] = f"Status '{self.status}' requires is_active=False."

        # 4. Revocation timestamp coherence
        if self.status == AdministrativeMembershipStatus.REVOKED and not self.revoked_at:
            self.revoked_at = timezone.now()

        if errors:
            raise ValidationError(errors)
```

---

## 7. Constraint Classification & Redundant Field Justification

### 7.1 Multi-Tier Constraint Enforcement Architecture

| Invariant | Enforcement Tier | Mechanism | Failure Mode |
| :--- | :--- | :--- | :--- |
| **Referential Integrity** | Database Foreign Key | `fk_admin_mem_user`, `fk_admin_mem_college`, `fk_admin_mem_role` | `IntegrityError` (`ON DELETE RESTRICT`) |
| **Single Active Membership** | Database Unique Constraint | `uk_admin_mem_user_college (user_id, college_id)` | `IntegrityError` (Duplicate Key) |
| **Allowed Status Values** | Database Check Constraint | `chk_admin_mem_status (status IN (...))` | `IntegrityError` (Check Violation) |
| **Status / Active Coherence** | Database Check Constraint | `chk_admin_mem_active_status ((is_active=T AND status='ACTIVE') OR ...)` | `IntegrityError` (Check Violation) |
| **Primary Role Eligibility** | Transactional Service Validation & Model `clean()` | Service rechecks `user.role == RoleChoices.ADMIN` under User lock | `ValidationError` (HTTP 400) |
| **No Self-Grant / Self-Revoke** | Transactional Service Validation & Model `clean()` | Service verifies `actor.pk != target_user.pk` | `PermissionDenied` (HTTP 403) |
| **Mandatory Role Assignment** | Database `NOT NULL` Column | `role_id BIGINT NOT NULL` | `IntegrityError` (Column cannot be null) |
| **Operation-Level Authority** | Centralized Authorization Service | `authorize_institutional_operation(actor, college_id, operation)` | `PermissionDenied` (HTTP 403) |

### 7.2 Justification for Retaining Denormalized `is_active`
The boolean column `is_active` denormalizes `status == 'ACTIVE'`. This field is intentionally retained for:
1. **Covering Index Optimization:** In MySQL InnoDB, a composite index `(user_id, is_active, college_id, role_id)` allows high-frequency authorization queries to execute as pure index-covering scans, filtering on a 1-byte integer boolean rather than performing multi-byte string comparisons on `status`.
2. **Database-Level Coherence:** Constraint `chk_admin_mem_active_status` enforces strict mathematical equivalence at the database engine level, eliminating any risk of status drift between `is_active` and `status`.

---

# Final Authorization and Concurrency Addendum

---

## 8. Complete Two-Dimensional Read & Write Authorization (Finding P3-A)

### 8.1 Explicit Operation Identifiers (Read & Write)
To comprehensively secure both data retrieval (collection listing, detail retrieval, search, filter) and state mutations, administrative operations are partitioned into 25 discrete, non-redundant operation identifiers across Domain A and Domain B:

```
+----------------------------------------------------------------------------------------------------+
| DOMAIN               | READ OPERATIONS                      | WRITE / MUTATION OPERATIONS          |
+----------------------+--------------------------------------+--------------------------------------+
| Student Registration | student.registration.list            | student.registration.review          |
|                      | student.registration.read            |                                      |
+----------------------+--------------------------------------+--------------------------------------+
| Student Profile      | student.profile.list                 | student.profile.manage               |
|                      | student.profile.read                 |                                      |
+----------------------+--------------------------------------+--------------------------------------+
| Faculty Profile      | faculty.profile.list                 | faculty.account.provision            |
|                      | faculty.profile.read                 | faculty.profile.manage               |
+----------------------+--------------------------------------+--------------------------------------+
| Enrollment Record    | enrollment.record.list               | enrollment.record.manage             |
|                      | enrollment.record.read               |                                      |
+----------------------+--------------------------------------+--------------------------------------+
| Faculty Assignment   | academic.faculty_assignment.list     | academic.faculty_assignment.manage   |
|                      | academic.faculty_assignment.read     |                                      |
+----------------------+--------------------------------------+--------------------------------------+
| Academic Structure   | academic.structure.list              | academic.structure.manage            |
|                      | academic.structure.read              | academic.programme.manage            |
|                      |                                      | academic.session.manage              |
+----------------------+--------------------------------------+--------------------------------------+
| Institutional Config | academic.config.read                 | academic.config.manage               |
+----------------------+--------------------------------------+--------------------------------------+
| Admin Membership     | admin.membership.read                | admin.membership.manage              |
+----------------------+--------------------------------------+--------------------------------------+
```

### 8.2 Comprehensive Institutional Role-to-Operation Matrix (7 Roles)
The matrix defines exact capabilities across all 7 user classifications. Default-deny is enforced for any unlisted operation.

*Role Key:*
- **SUPERADMIN:** System-wide superadministrator (`role == 'SUPERADMIN'` or `is_superuser == True`).
- **COLLEGE_SUPERADMIN:** Administrator with active `AdministrativeMembership` holding role `COLLEGE_SUPERADMIN` at target college.
- **EXAM_OFFICER:** Operational examination administrator with active `AdministrativeMembership` holding role `EXAM_OFFICER` at target college (authorized for examination coordination and assignment writes; barred from institutional governance).
- **UNMAPPED_ADMIN:** User with primary role `ADMIN` but lacking an active membership for the target college (or membership revoked/suspended).
- **FACULTY:** Active user with primary role `FACULTY` and `FacultyProfile`.
- **STUDENT:** Active user with primary role `STUDENT` and `StudentProfile`.
- **ANONYMOUS:** Unauthenticated client.

| Operation Identifier | Operation Type | System `SUPERADMIN` | Assigned `COLLEGE_SUPERADMIN` | Assigned `EXAM_OFFICER` | Unmapped / Cross-College `ADMIN` | `FACULTY` | `STUDENT` | `ANONYMOUS` |
| :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: |
| `student.registration.list` | Read | **ALLOW** | **ALLOW** | **DENY** | **DENY** | **DENY** | **DENY** | **DENY** |
| `student.registration.read` | Read | **ALLOW** | **ALLOW** | **DENY** | **DENY** | **DENY** | **DENY** | **DENY** |
| `student.registration.review` | Mutation | **ALLOW** | **ALLOW** | **DENY** | **DENY** | **DENY** | **DENY** | **DENY** |
| `student.profile.list` | Read | **ALLOW** | **ALLOW** | **ALLOW** | **DENY** | **DENY** | **DENY** | **DENY** |
| `student.profile.read` | Read | **ALLOW** | **ALLOW** | **ALLOW** | **DENY** | **DENY** | Self Only | **DENY** |
| `student.profile.manage` | Mutation | **ALLOW** | **ALLOW** | **DENY** | **DENY** | **DENY** | Contact Only | **DENY** |
| `faculty.profile.list` | Read | **ALLOW** | **ALLOW** | **ALLOW** | **DENY** | **DENY** | **DENY** | **DENY** |
| `faculty.profile.read` | Read | **ALLOW** | **ALLOW** | **ALLOW** | **DENY** | Self Only | **DENY** | **DENY** |
| `faculty.account.provision` | Mutation | **ALLOW** | **ALLOW** | **DENY** | **DENY** | **DENY** | **DENY** | **DENY** |
| `faculty.profile.manage` | Mutation | **ALLOW** | **ALLOW** | **DENY** | **DENY** | Contact Only | **DENY** | **DENY** |
| `enrollment.record.list` | Read | **ALLOW** | **ALLOW** | **ALLOW** | **DENY** | **DENY** | **DENY** | **DENY** |
| `enrollment.record.read` | Read | **ALLOW** | **ALLOW** | **ALLOW** | **DENY** | **DENY** | Self Only | **DENY** |
| `enrollment.record.manage` | Mutation | **ALLOW** | **ALLOW** | **ALLOW** | **DENY** | **DENY** | **DENY** | **DENY** |
| `academic.faculty_assignment.list` | Read | **ALLOW** | **ALLOW** | **ALLOW** | **DENY** | Assigned Only | **DENY** | **DENY** |
| `academic.faculty_assignment.read` | Read | **ALLOW** | **ALLOW** | **ALLOW** | **DENY** | Assigned Only | **DENY** | **DENY** |
| `academic.faculty_assignment.manage`| Mutation | **ALLOW** | **ALLOW** | **ALLOW** | **DENY** | **DENY** | **DENY** | **DENY** |
| `academic.structure.list` | Read | **ALLOW** | **ALLOW** | **ALLOW** | **DENY** | **ALLOW** | **ALLOW** | **DENY** |
| `academic.structure.read` | Read | **ALLOW** | **ALLOW** | **ALLOW** | **DENY** | **ALLOW** | **ALLOW** | **DENY** |
| `academic.structure.manage` | Mutation | **ALLOW** | **ALLOW** | **DENY** | **DENY** | **DENY** | **DENY** | **DENY** |
| `academic.programme.manage` | Mutation | **ALLOW** | **ALLOW** | **DENY** | **DENY** | **DENY** | **DENY** | **DENY** |
| `academic.session.manage` | Mutation | **ALLOW** | **ALLOW** | **DENY** | **DENY** | **DENY** | **DENY** | **DENY** |
| `academic.config.read` | Read | **ALLOW** | **ALLOW** | **DENY** | **DENY** | **DENY** | **DENY** | **DENY** |
| `academic.config.manage` | Sensitive | **ALLOW** | **ALLOW** | **DENY** | **DENY** | **DENY** | **DENY** | **DENY** |
| `admin.membership.read` | Read | **ALLOW** | **ALLOW** | **DENY** | **DENY** | **DENY** | **DENY** | **DENY** |
| `admin.membership.manage` | Governance| **ALLOW** | **DENY** | **DENY** | **DENY** | **DENY** | **DENY** | **DENY** |

### 8.3 Multi-College Administrator Role Differences Scenario Analysis
Consider an administrator user ($U_1$) holding active memberships across two institutions:
- **College A (Cotton University, ID: 1):** Assigned Role = `COLLEGE_SUPERADMIN`
- **College B (B. Borooah College, ID: 2):** Assigned Role = `EXAM_OFFICER`

The effective access across endpoints differs strictly between the two institutions:

```
+-----------------------------------------------------------------------------------------------------+
| ENDPOINT / OPERATION                     | EFFECTIVE ACCESS AT COLLEGE A   | EFFECTIVE ACCESS AT COLLEGE B  |
+------------------------------------------+---------------------------------+--------------------------------+
| GET /api/v1/students/registrations/      | ALLOW (Returns College A rows)  | DENY (Filtered out / 0 rows)   |
| POST /api/v1/students/registrations/appr | ALLOW (Can review College A)    | DENY (HTTP 403 Forbidden)      |
| GET /api/v1/students/profiles/           | ALLOW (Returns College A rows)  | ALLOW (Returns College B rows) |
| PATCH /api/v1/students/profiles/{id}/    | ALLOW (Can update College A)    | DENY (HTTP 403 Forbidden)      |
| POST /api/v1/faculty/profiles/provision/ | ALLOW (Can provision at A)      | DENY (HTTP 403 Forbidden)      |
| GET /api/v1/enrollments/records/         | ALLOW (Returns College A rows)  | ALLOW (Returns College B rows) |
| POST /api/v1/enrollments/records/        | ALLOW (Can create ledger at A)  | ALLOW (Can create ledger at B) |
| POST /api/v1/academics/assignments/      | ALLOW (Can assign faculty at A) | ALLOW (Can assign faculty at B)|
| POST /api/v1/academics/sessions/set-curr | ALLOW (Can switch session at A) | DENY (HTTP 403 Forbidden)      |
| GET /api/v1/academics/configs/           | ALLOW (Returns College A keys)  | DENY (HTTP 403 Forbidden)      |
| POST /api/v1/admin/memberships/          | DENY (Reserved to Superadmin)   | DENY (Reserved to Superadmin)  |
+-----------------------------------------------------------------------------------------------------+
```

### 8.4 Collection Queryset Scoping Helper Contract
Collection querysets in ViewSets must enforce operation-specific scoping before applying filters, search, or pagination:

```python
# Proposed: backend/apps/accounts/authorization.py

def get_authorized_college_ids_for_operation(
    actor,
    operation: str,
) -> Optional[Set[int]]:
    """
    Authoritative resolution of college IDs permitted for a specific operation (Finding P3-A).
    
    Returns:
    - None: Unrestricted system-wide authority (Superadministrator / is_superuser)
    - Set[int]: Explicit authorized college IDs where actor holds an active membership
                whose assigned institutional role permits the specified operation.
    - Set(): Empty set -> actor has no authority for this operation; ViewSets call qs.none().
    
    Invariants Enforced:
    1. Actor must be authenticated and active.
    2. Primary role must be ADMIN or SUPERADMIN (STUDENT/FACULTY return set()).
    3. Excludes memberships where is_active=False or status != 'ACTIVE'.
    4. Excludes colleges where is_active=False.
    5. Operation must exist in INSTITUTIONAL_ROLE_PERMISSIONS; unknown operations fail closed.
    6. Ignores caller-injected runtime Python attributes.
    7. Query parameters can never expand returned scope.
    """
    if not actor or not getattr(actor, 'is_authenticated', False) or not getattr(actor, 'is_active', False):
        return set()

    if actor.role in (RoleChoices.STUDENT, RoleChoices.FACULTY):
        return set()

    if actor.role == RoleChoices.SUPERADMIN or getattr(actor, 'is_superuser', False):
        return None

    if actor.role != RoleChoices.ADMIN:
        return set()

    if operation not in VALID_INSTITUTIONAL_OPERATIONS:
        logger.warning("Unrecognized institutional operation requested: %s", operation)
        return set()

    from apps.accounts.models import AdministrativeMembership, AdministrativeMembershipStatus
    
    memberships = (
        AdministrativeMembership.objects.filter(
            user=actor,
            is_active=True,
            status=AdministrativeMembershipStatus.ACTIVE,
            college__is_active=True,
        )
        .select_related('role')
        .values_list('college_id', 'role__code')
    )

    authorized_college_ids: Set[int] = set()
    for college_id, role_code in memberships:
        permitted_ops = INSTITUTIONAL_ROLE_PERMISSIONS.get(role_code, set())
        if operation in permitted_ops:
            authorized_college_ids.add(college_id)

    return authorized_college_ids
```

### 8.5 Object-Level Indirect Ownership Path Mapping
When retrieving detail records or performing mutations, authorization verifies the authoritative `college_id` by traversing unambiguous foreign-key relationship paths:

```
+------------------------------------+---------------------------------------------------------------+
| Target Entity                      | Authoritative College Relationship Traversal Path             |
+------------------------------------+---------------------------------------------------------------+
| StudentProfile                     | instance.college_id                                           |
| RegistrationApproval               | instance.user.student_profile.college_id                      |
| FacultyProfile                     | instance.college_id                                           |
| StudentAcademicRecord              | instance.student.college_id                                   |
| AcademicSession                    | instance.college_id                                           |
| Programme                          | instance.college_id                                           |
| Department                         | instance.college_id                                           |
| Semester                           | instance.programme.college_id                                 |
| SubjectCategory                    | instance.college_id                                           |
| Subject                            | instance.department.college_id                                |
| PaperOffering                      | instance.academic_session.college_id                          |
| PaperProgrammeMapping              | instance.paper_offering.academic_session.college_id           |
| FacultySubjectAssignment           | instance.paper_offering.academic_session.college_id           |
| InstitutionalConfig                | instance.college_id                                           |
| AdministrativeMembership           | instance.college_id                                           |
+------------------------------------+---------------------------------------------------------------+
```

### 8.6 Service-Layer Transition & Integration Plan
Existing generic checks in service functions (`check_institutional_admin_authority()` and `check_college_operation_authority()`) will transition to operation-specific enforcement:
- `review_student_registration()` calls `authorize_institutional_operation(reviewer, student_college_id, "student.registration.review")`.
- `update_faculty_assignment()` calls `authorize_institutional_operation(acting_user, offering_college_id, "academic.faculty_assignment.manage")`.
- `set_institutional_config()` calls `authorize_institutional_operation(acting_user, college_id, "academic.config.manage")`.
- All checks execute inside `@transaction.atomic` blocks under row locks.

---

## 9. Comprehensive Service Transaction Lock Hierarchy (Finding P3-B)

### 9.1 Standard Administrative Mutation Order
To ensure deadlock-free synchronization across all concurrent operations, administrative mutations adhere to a strict standard locking sequence:

1. **Step 1: Unlocked Candidate Read:** Read candidate identifiers (`college_id`, parent IDs) without acquiring child row locks.
2. **Step 2: Candidate College Resolution:** Determine all source and destination colleges involved in the operation.
3. **Step 3: Level 1 College Coordination Lock:** Acquire exclusive row locks on owning colleges in strictly ascending primary-key order (`lock_colleges(*sorted_college_ids)`).
4. **Step 4: Level 2 Actor User Lock:** Reload and verify the acting administrator's active account state (`User.objects.select_for_update().get(pk=actor_id)`).
5. **Step 5: Level 3 Membership Lock & Verification:** Execute a locking read on the acting administrator's `AdministrativeMembership` row, verifying `status == 'ACTIVE'` and confirming operation capability.
6. **Step 6: Level 4 Target Entity Locks:** Acquire row locks on target entities (e.g., target User, PaperOffering, FacultyProfile) in consistent ascending primary-key order.
7. **Step 7: Level 5 Target Child Record Locks:** Acquire child row locks (e.g., RegistrationApproval, FacultySubjectAssignment).
8. **Step 8: Authoritative Invariant Revalidation:** Under full locks, revalidate relationship consistency, examiner eligibility, and institutional boundaries.
9. **Step 9: Apply Mutation & Persist:** Save changes atomically.
10. **Step 10: Atomic Commit:** Release all acquired row locks simultaneously at transaction commit.

### 9.2 Actor vs. Target Identity Separation
Finding P3-B noted that previous registration workflows locked the target Student User before checking college authorization. The corrected protocol strictly separates Actor and Target identities:

$$\text{Level 1: College} \longrightarrow \text{Level 2: Actor User} \longrightarrow \text{Level 3: Membership} \longrightarrow \text{Level 4: Target Student User} \longrightarrow \text{Level 5: Child Records}$$

Because Level 1 College Coordination Lock is acquired *first*, concurrent operations within that college are fully serialized at the database engine level, mathematically eliminating lock-order inversion between Actor and Target user rows.

### 9.3 Authoritative Membership Revalidation & MySQL 8 InnoDB Guarantees
- **Locking Read on Membership:** In sensitive mutations, the service acquires an explicit row lock on the membership:
  ```sql
  SELECT id, role_id, status, is_active FROM accounts_administrative_membership 
  WHERE user_id = :actor_id AND college_id = :college_id FOR UPDATE;
  ```
- **Guaranteed Concurrency Semantics:**
  1. *Revocation Before Authorization:* If Superadmin revokes membership and commits, the administrator's subsequent transaction observes `status == 'REVOKED'` and is immediately rejected with HTTP 403 `PermissionDenied`.
  2. *Concurrent Revocation Race:* If Superadmin attempts revocation while an administrator is executing a mutation, both transactions contend for the Level 1 College lock and Level 3 Membership lock. If revocation acquires the lock first, the mutation is serialized behind it, rechecks membership under lock, discovers revocation, and aborts without persisting.
  3. *In-Flight Completion:* If the administrator's transaction commits before revocation begins, the write is durably committed under ACID rules. Revocation immediately takes effect for all subsequent transactions.

---

## 10. Service-Level Locking Matrix (14 Administrative Services) (Finding P3-B)

| Service Function | Operation Code | Candidate Read | Level 1: College Lock | Level 2: Actor Lock | Level 3: Membership Lock | Level 4: Target Lock | Level 5: Child Lock | Recheck & Outcome |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| `review_student_registration` | `student.registration.review` | Target user & college from approval | `lock_colleges(college_id)` | Actor User `FOR UPDATE` | Membership `FOR UPDATE` | Target User `FOR UPDATE` | `RegistrationApproval`, `StudentProfile` `FOR UPDATE` | Recheck pending, verified email; approve/reject |
| `update_student_profile` | `student.profile.manage` | Profile PK, college | `lock_colleges(college_id)` | Actor User `FOR UPDATE` | Membership `FOR UPDATE` | Student User `FOR UPDATE` | `StudentProfile` `FOR UPDATE` | Recheck semester bounds, save |
| `provision_faculty` | `faculty.account.provision` | Target college, department | `lock_colleges(college_id)` | Actor User `FOR UPDATE` | Membership `FOR UPDATE` | Target User (New row) | `FacultyProfile` (New row) | Verify department same-college; create user & profile |
| `update_faculty_profile` | `faculty.profile.manage` | Profile PK, college, depts | `lock_colleges(college_id)` | Actor User `FOR UPDATE` | Membership `FOR UPDATE` | Target User `FOR UPDATE` | `FacultyProfile`, `Department` `FOR UPDATE` | Verify dept same-college, recheck examiner flag |
| `create_student_academic_record`| `enrollment.record.manage` | Student PK, college | `lock_colleges(college_id)` | Actor User `FOR UPDATE` | Membership `FOR UPDATE` | Student User `FOR UPDATE` | `StudentProfile`, `StudentAcademicRecord` | Verify same-college programme, save record |
| `update_student_academic_record`| `enrollment.record.manage` | Record PK, college | `lock_colleges(college_id)` | Actor User `FOR UPDATE` | Membership `FOR UPDATE` | Student User `FOR UPDATE` | `StudentAcademicRecord` `FOR UPDATE` | Revalidate status transition, save |
| `assign_faculty_to_paper` | `academic.faculty_assignment.manage` | Offering PK, Faculty PK | `lock_colleges(college_id)` | Actor User `FOR UPDATE` | Membership `FOR UPDATE` | `PaperOffering`, `FacultyProfile` `FOR UPDATE`| `FacultySubjectAssignment` (New) | Verify same-college, examiner flag; create |
| `update_faculty_assignment` | `academic.faculty_assignment.manage` | Assignment PK, offerings, fac | `lock_colleges(*sorted_colleges)`| Actor User `FOR UPDATE` | Membership `FOR UPDATE` | `PaperOffering`, `FacultyProfile` `FOR UPDATE`| `FacultySubjectAssignment` `FOR UPDATE`| Reconcile stale snapshot, verify examiner; save |
| `delete_faculty_assignment` | `academic.faculty_assignment.manage` | Assignment PK, offering | `lock_colleges(college_id)` | Actor User `FOR UPDATE` | Membership `FOR UPDATE` | `PaperOffering` `FOR UPDATE` | `FacultySubjectAssignment` `FOR UPDATE`| Reconcile stale snapshot, delete assignment |
| `update_programme` | `academic.programme.manage` | Programme PK, college | `lock_colleges(college_id)` | Actor User `FOR UPDATE` | Membership `FOR UPDATE` | `Programme` `FOR UPDATE` | Child `Semester` count query | Revalidate duration covers semesters; save |
| `set_current_academic_session` | `academic.session.manage` | Session PK, college | `lock_colleges(college_id)` | Actor User `FOR UPDATE` | Membership `FOR UPDATE` | `AcademicSession` (All for college) `FOR UPDATE`| None | Deactivate other sessions, activate target |
| `set_institutional_config` | `academic.config.manage` | College PK, config key | `lock_colleges(college_id)` | Actor User `FOR UPDATE` | Membership `FOR UPDATE` | `InstitutionalConfig` `FOR UPDATE` | None | Verify value format, save config |
| `grant_administrative_membership`| `admin.membership.manage` | College PK, User PK | `lock_colleges(college_id)` | Superadmin `FOR UPDATE` | Target User `FOR UPDATE` | Membership (New row) | None | Verify Superadmin, check target role; create |
| `revoke_administrative_membership`| `admin.membership.manage` | Membership PK, college | `lock_colleges(college_id)` | Superadmin `FOR UPDATE` | Target User `FOR UPDATE` | `AdministrativeMembership` `FOR UPDATE`| None | Set `is_active=F`, `status='REVOKED'`; save |

---

## 11. Multi-Connection MySQL Concurrency Test Design (Finding P3-B)

The following 10 real multi-connection integration tests are specified for post-approval implementation, using `django.test.TransactionTestCase` with multiple independent database connections (`connections['default']`, `connections['second']`):

```
+----------------------------------------------------------------------------------------------------+
| Test Scenario Identifier             | Concurrency Race Condition Tested                           |
+--------------------------------------+-------------------------------------------------------------+
| test_concurrent_revocation_vs_approv | Superadmin revokes membership while admin approves student. |
| test_concurrent_revocation_vs_provis | Superadmin revokes membership while admin provisions faculty|
| test_concurrent_revocation_vs_record | Superadmin revokes membership while admin updates ledger.   |
| test_concurrent_revocation_vs_assign | Superadmin revokes membership while admin updates assignment|
| test_concurrent_suspension_vs_write  | Superadmin suspends membership while admin writes structure.|
| test_concurrent_demote_vs_write      | Superadmin demotes user role while admin mutates offering.  |
| test_concurrent_grant_vs_revoke_race | Concurrent grant and revocation for same user-college pair. |
| test_concurrent_multi_college_update | Concurrent mutations across two colleges held by one admin. |
| test_concurrent_college_deactivation | Superadmin deactivates college while admin executes writes. |
| test_deadlock_detection_and_recovery | Intentional cross-operation lock contention verifies retry. |
+----------------------------------------------------------------------------------------------------+
```

---

## 12. Durable Administrative Audit Retention Analysis (Finding P3-C)

### 12.1 Policy Evaluation: Policy A vs. Policy B

#### Policy A: Audit Prerequisite (Recommended for Production)
* **Concept:** Administrative membership mutations remain gated until a durable, authorized security-audit mechanism is available. This brings forward a narrowly scoped portion of the approved audit architecture (Table 51: `audit_system_audit_log` from Domain I) through a separate owner authorization.
* **Trade-Offs:**
  - *Pros:* Uncompromising enterprise auditability, tamper-evident non-repudiation, permanent historical tracking of appointments/revocations across reappointments.
  - *Cons:* Requires implementing Table 51 earlier than originally scheduled in Chunk 15.

#### Policy B: Explicit Interim Limitation (Development / Staging Only)
* **Concept:** The project owner accepts temporary structured application logging (`logger = logging.getLogger('college.accounts.audit')`) for membership lifecycle events until Chunk 15 implements Table 51.
* **Limitations Disclosed:** Application logs can be rotated, deleted, or truncated; they lack database relational queryability and foreign-key integrity; reappointment overwrites previous row metadata on Table 53.
* **Trade-Offs:**
  - *Pros:* Zero schema expansion beyond Table 53 in Chunk 06.
  - *Cons:* Does not provide guaranteed durable, queryable, non-repudiable audit storage.

### 12.2 Recommendation and Project-Owner Decision Requirement
The engineering team **strongly recommends Policy A** for production readiness. Policy B may be considered strictly for isolated development environments. In accordance with governance instructions, **the choice between Policy A and Policy B is submitted to the project owner for formal decision and is not selected on the owner's behalf.**

### 12.3 Administrative Audit Event Specification & Payload Schema
When administrative membership events occur, the system generates structured audit records conforming to the following payload schema:

```json
{
  "event_id": "c4b8e2a1-5f3d-4e9b-8a21-9d7e3f1c5b8a",
  "event_type": "ADMIN_MEMBERSHIP_REVOKED",
  "timestamp": "2026-11-04T23:30:00.000000Z",
  "actor_id": 1,
  "actor_role": "SUPERADMIN",
  "target_user_id": 15,
  "college_id": 2,
  "membership_id": 4,
  "previous_role_code": "EXAM_OFFICER",
  "new_role_code": null,
  "previous_status": "ACTIVE",
  "new_status": "REVOKED",
  "revocation_reason": "Tenure expired; transferred to examination coordination headquarters.",
  "ip_address": "192.168.1.100",
  "request_id": "REQ-20261104-ABC12345"
}
```

*Audit Event Types Defined:*
1. `ADMIN_MEMBERSHIP_GRANTED`: Initial membership assignment.
2. `ADMIN_MEMBERSHIP_SUSPENDED`: Temporary access suspension.
3. `ADMIN_MEMBERSHIP_REINSTATED`: Reinstatement of suspended membership.
4. `ADMIN_MEMBERSHIP_REVOKED`: Permanent access termination.
5. `ADMIN_MEMBERSHIP_REAPPOINTED`: Reappointment of previously revoked administrator.
6. `ADMIN_MEMBERSHIP_ROLE_CHANGED`: Modification of assigned institutional role.
7. `ADMIN_MEMBERSHIP_UNAUTHORIZED_ATTEMPT`: Unauthorized mutation attempt rejected by security gates.

---

## 13. Phased Deployment & Rollback Strategy

### 13.1 Staged Rollout Strategy
1. **Stage 1 — Schema Introduction:** Apply migration `accounts.0002_administrative_membership` during an off-peak maintenance window.
2. **Stage 2 — Dual-Compatible Code Deployment:** Deploy backend services supporting `AdministrativeMembership`. Institutional authorization remains fail-closed for administrators without assigned memberships.
3. **Stage 3 — Administrative Membership Provisioning:** Superadministrators grant explicit institutional memberships and roles through an audited bootstrap procedure.
4. **Stage 4 — Authorization Gate Activation:** Switch `authorize_institutional_operation` to actively permit ordinary administrators based on verified active memberships.
5. **Stage 5 — Staging & Production Verification:** Verify institutional boundaries, operation-level permissions, and revocation semantics.

### 13.2 Real-World Rollback Plan
- **Level 1 (Operational Rollback):** Disable membership-based administrative access by toggling an application flag, immediately reverting ordinary administrators to fail-closed status without schema modifications.
- **Level 2 (Data Preservation Rollback):** Export all `accounts_administrative_membership` records to a secure SQL/JSON dump before attempting schema reversal.
- **Level 3 (Schema Reversal):** Execute `python manage.py migrate accounts 0001_initial`. Drops Table 53 after Level 2 data preservation.

---

## 14. Outstanding Project-Owner Approval Checklist

Before any code implementation begins, the project owner must review and explicitly decide:

- [ ] **1. Architecture Selection:** Formally approve **Option B (Dedicated Administrative Membership Mapping Table)** with **Two-Dimensional Institutional Authorization**.
- [ ] **2. Schema Baseline Expansion:** Formally approve expanding the relational database architecture from **52 tables to 53 tables** to accommodate Table 53 (`accounts_administrative_membership`).
- [ ] **3. Mandatory Institutional Role:** Approve making `role_id` mandatory (`NOT NULL`) on Table 53.
- [ ] **4. Audit Retention Policy Selection:**
  - [ ] **Approve Policy A (Audit Prerequisite):** Bring forward Table 51 (`audit_system_audit_log`) for durable administrative auditing prior to production deployment.
  - [ ] **Approve Policy B (Interim Application Logging):** Authorize temporary structured application logging for development environments with documented limitations.
- [ ] **5. Authorization Matrix:** Approve the 25-operation institutional authorization matrix defined in Section 8.
- [ ] **6. Chunk 06 Round 6 Implementation:** Authorize the engineering team to implement Table 53, generate migration `0002_administrative_membership`, and wire `authorize_institutional_operation`.

---

## 15. Stop Condition & Governance Attestation

In accordance with explicit governance instructions:
- **Zero code changes** have been made to Django models, services, or views.
- **Zero migrations** have been created.
- Protected files ([`design.md`](file:///home/zero/Documents/college/design.md), [`handover.txt`](file:///home/zero/Documents/college/handover.txt), [`docs/architecture.md`](file:///home/zero/Documents/college/docs/architecture.md), [`docs/database-architecture.md`](file:///home/zero/Documents/college/docs/database-architecture.md), [`docs/development-progress.md`](file:///home/zero/Documents/college/docs/development-progress.md)) remain untouched.
- Git commit and push remain unexecuted.
- Chunk 07 onward remains strictly gated.
- Android application development remains paused.

```
===================================================================================================
STOP CONDITION MET: FINAL DESIGN ADDENDUM COMPLETED.
AWAITING INDEPENDENT ARCHITECTURE AUDIT AND FORMAL PROJECT-OWNER APPROVAL.
DO NOT BEGIN IMPLEMENTATION UNTIL OWNER EXPLICITLY APPROVES.
===================================================================================================
```
