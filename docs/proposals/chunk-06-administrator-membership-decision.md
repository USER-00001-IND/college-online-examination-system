# Architectural Decision Proposal: Administrator-to-College Membership Architecture
## Final Architecture Proposal — Security, RBAC, Concurrency and Audit Retention

**Project:** College Online Examination System  
**Academic Context:** Gauhati University FYUGP Context (College Level)  
**Target Domain:** Domain A: Identity, Authentication & Role-Based Access Control  
**Document ID:** `PROP-CHUNK-06-ADMIN-MEMBERSHIP-FINAL`  
**Status:** **FINAL ARCHITECTURE PROPOSAL — PENDING INDEPENDENT REVIEW AND PROJECT-OWNER APPROVAL**  
**Author:** Antigravity Engineering Team  
**Date:** 2026-11-04  
**Last Independently Audited Commit:** `74862dd18724524915be8c997cfb9374c33b9eff`  
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

| Proposal Iteration | Verdict | Findings / Scope Addressed |
|---|---|---|
| **Round 1 (`PROP-...-001`)** | REVISION REQUIRED | 5 Findings: Incomplete college scoping, lock-order contradictions, audit deletion risk, SQL/Django constraint mismatches, overstated deployment claims. |
| **Round 2 (`PROP-...-002`)** | CONDITIONAL PASS | Preferred Option B retained; identified 3 remaining specification gaps: Read-operation scoping, in-flight transaction synchronization, durable audit retention. |
| **Final Addendum (`PROP-...-FINAL-ADDENDUM`)** | CONDITIONAL PASS | Delivered 2D read/write RBAC, service locking matrix, audit retention policy analysis; identified 4 targeted refinement findings (P4-A through P4-D). |
| **Final Proposal (Current)** | **PENDING REVIEW** | Resolves Findings P4-A, P4-B, P4-C, and P4-D. Establishes operation validation before superadmin bypass, unified global 5-level lock hierarchy, self-service domain separation, and dual audit transaction semantics. |

### 1.3 Resolution Summary of Targeted Findings (P4-A through P4-D)

| Finding | Severity | Defect Analysis & Root Cause | Final Resolution & Document Section |
| :---: | :---: | :--- | :--- |
| **P4-A** | **HIGH** | `get_authorized_college_ids_for_operation` returned unrestricted superadmin scope before verifying whether `operation` was in the approved registry, allowing unknown operations to bypass default-deny for Superadmin. | Enforced an unbypassable 11-step evaluation pipeline where operation type and registry validation occur **first**, guaranteeing unknown operations fail closed for all roles, including Superadmin. *(Section 8.4, Section 14.1, 14.2)* |
| **P4-B** | **HIGH** | Standard mutation hierarchy (`College -> Actor User -> Membership -> Target`) conflicted with membership grant/revoke and registration review workflows that lock target user rows; multi-college updates lacked deterministic global ordering. | Established a unified global Five-Level Lock Hierarchy: **Level 1 College $\rightarrow$ Level 2 All Users in ascending PK order $\rightarrow$ Level 3 Memberships in ascending PK order $\rightarrow$ Level 4 Academic Parents $\rightarrow$ Level 5 Academic Children**. Documented exact 8 mutation sequences and reconciled 13 services. *(Section 9, Section 14.3, 14.4, 14.5)* |
| **P4-C** | **MEDIUM** | The institutional helper returning `set()` for student/faculty accounts conflated administrative authority with legitimate student/faculty self-service and general academic reference data visibility. | Established four independent authorization domains: Domain A (Institutional Admin), Domain B (Student Self-Service), Domain C (Faculty Self-Service), and Domain D (General Academic Read Access). Proved self-service never depends on administrative membership. *(Section 14.6, 14.7, 14.8)* |
| **P4-D** | **MEDIUM** | Single atomic audit transaction model fails for rejected security attempts (rollback erases the rejection event); append-only database table was loosely described as tamper-evident non-repudiation. | Formulated dual audit transaction semantics: atomic commit for successful mutations; separate structured security logging sink for rejected authorization attempts. Accurately disclaimed cryptographic tamper-evidence and mapped Table 51 columns. *(Section 12, Section 14.9, 14.10, 14.11)* |

> [!IMPORTANT]
> **Governance Boundary:** This document is an **architecture proposal only**. Implementation authorization is **NOT GRANTED**. No Django models, migrations, serializers, or services have been modified. Protected architecture documents ([`design.md`](file:///home/zero/Documents/college/design.md), [`handover.txt`](file:///home/zero/Documents/college/handover.txt), [`docs/architecture.md`](file:///home/zero/Documents/college/docs/architecture.md), [`docs/database-architecture.md`](file:///home/zero/Documents/college/docs/database-architecture.md), [`docs/development-progress.md`](file:///home/zero/Documents/college/docs/development-progress.md)) remain 100% untouched.

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

The proposed architecture adopts **Option B** enhanced with a **Two-Dimensional Institutional Authorization System** (resolving Findings P2-A, P3-A, and P4-A).

Administrative authority requires satisfying two distinct dimensions simultaneously:
$$\text{Authorized Operation} \iff \text{Dimension 1 (Institution Scope)} \land \text{Dimension 2 (Role Permission)}$$

1. **Dimension 1 (Institution Scope):** The acting user must hold an authoritative, active `AdministrativeMembership` record for the target `academics_college` (`is_active = TRUE`, `status = 'ACTIVE'`).
2. **Dimension 2 (Role Permission):** The specific granular role assigned to the user within that institution (`membership.role`) must possess the explicit capability to execute the requested administrative operation (read or write).

---

## 5. Table 53 SQL Schema Definition

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

## 8. Two-Dimensional Read & Write Authorization System (Finding P3-A, P4-A)

### 8.1 Explicit Operation Identifiers (Read & Write)
Administrative operations are partitioned into 25 discrete, non-redundant operation identifiers across Domain A and Domain B:

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

### 8.2 Comprehensive Institutional Role-to-Operation Matrix
The matrix defines exact administrative capabilities. Default-deny is enforced for any unlisted operation.

| Operation Identifier | Operation Type | System `SUPERADMIN` | Assigned `COLLEGE_SUPERADMIN` | Assigned `EXAM_OFFICER` | Unmapped / Cross-College `ADMIN` |
| :--- | :---: | :---: | :---: | :---: | :---: |
| `student.registration.list` | Read | **ALLOW** | **ALLOW** | **DENY** | **DENY** |
| `student.registration.read` | Read | **ALLOW** | **ALLOW** | **DENY** | **DENY** |
| `student.registration.review` | Mutation | **ALLOW** | **ALLOW** | **DENY** | **DENY** |
| `student.profile.list` | Read | **ALLOW** | **ALLOW** | **ALLOW** | **DENY** |
| `student.profile.read` | Read | **ALLOW** | **ALLOW** | **ALLOW** | **DENY** |
| `student.profile.manage` | Mutation | **ALLOW** | **ALLOW** | **DENY** | **DENY** |
| `faculty.profile.list` | Read | **ALLOW** | **ALLOW** | **ALLOW** | **DENY** |
| `faculty.profile.read` | Read | **ALLOW** | **ALLOW** | **ALLOW** | **DENY** |
| `faculty.account.provision` | Mutation | **ALLOW** | **ALLOW** | **DENY** | **DENY** |
| `faculty.profile.manage` | Mutation | **ALLOW** | **ALLOW** | **DENY** | **DENY** |
| `enrollment.record.list` | Read | **ALLOW** | **ALLOW** | **ALLOW** | **DENY** |
| `enrollment.record.read` | Read | **ALLOW** | **ALLOW** | **ALLOW** | **DENY** |
| `enrollment.record.manage` | Mutation | **ALLOW** | **ALLOW** | **ALLOW** | **DENY** |
| `academic.faculty_assignment.list` | Read | **ALLOW** | **ALLOW** | **ALLOW** | **DENY** |
| `academic.faculty_assignment.read` | Read | **ALLOW** | **ALLOW** | **ALLOW** | **DENY** |
| `academic.faculty_assignment.manage`| Mutation | **ALLOW** | **ALLOW** | **ALLOW** | **DENY** |
| `academic.structure.list` | Read | **ALLOW** | **ALLOW** | **ALLOW** | **DENY** |
| `academic.structure.read` | Read | **ALLOW** | **ALLOW** | **ALLOW** | **DENY** |
| `academic.structure.manage` | Mutation | **ALLOW** | **ALLOW** | **DENY** | **DENY** |
| `academic.programme.manage` | Mutation | **ALLOW** | **ALLOW** | **DENY** | **DENY** |
| `academic.session.manage` | Mutation | **ALLOW** | **ALLOW** | **DENY** | **DENY** |
| `academic.config.read` | Read | **ALLOW** | **ALLOW** | **DENY** | **DENY** |
| `academic.config.manage` | Sensitive | **ALLOW** | **ALLOW** | **DENY** | **DENY** |
| `admin.membership.read` | Read | **ALLOW** | **ALLOW** | **DENY** | **DENY** |
| `admin.membership.manage` | Governance| **ALLOW** | **DENY** | **DENY** | **DENY** |

*(Note: Student and Faculty self-service access is formally decoupled into Domain B and Domain C; see Section 14.6 and 14.7).*

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

### 8.4 Collection Queryset Scoping Helper Contract (Corrected Evaluation Order)
Collection querysets in ViewSets must enforce operation-specific scoping before applying filters, search, or pagination. As required by Finding P4-A, **operation validation occurs before Superadmin bypass**:

```python
# Proposed: backend/apps/accounts/authorization.py

def get_authorized_college_ids_for_operation(
    actor,
    operation: str,
) -> Optional[Set[int]]:
    """
    Authoritative resolution of college IDs permitted for a specific operation.
    Enforces strict evaluation order: Operation Validation BEFORE Superadmin Bypass (Finding P4-A).
    
    Returns:
    - None: Unrestricted system-wide authority across registered operations (Superadmin)
    - Set[int]: Explicit authorized college IDs from active memberships
    - Set(): Empty set -> actor has no authority; ViewSets call qs.none().
    """
    # 1. Operation type validation
    if not isinstance(operation, str):
        return set()

    # 2. Approved operation registry validation (Fail closed for unknown operations)
    if operation not in VALID_INSTITUTIONAL_OPERATIONS:
        logger.warning("Unrecognized institutional operation requested: %s", operation)
        return set()

    # 3. Authentication check
    if not actor or not getattr(actor, 'is_authenticated', False):
        return set()

    # 4. Active account check
    if not getattr(actor, 'is_active', False):
        return set()

    # 5. Primary role restriction: STUDENTS and FACULTY accounts fail closed
    if actor.role in (RoleChoices.STUDENT, RoleChoices.FACULTY):
        return set()

    # 6 & 7. Superadministrator authority for validated registered operations
    if actor.role == RoleChoices.SUPERADMIN or getattr(actor, 'is_superuser', False):
        return None

    # 8. Ordinary administrator check
    if actor.role != RoleChoices.ADMIN:
        return set()

    # 9, 10 & 11. Authoritative membership lookup and capability check
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

---

## 9. Comprehensive Service Transaction Lock Hierarchy

All institutional mutations conform to the unified global Five-Level Lock Hierarchy:
$$\text{Level 1: College Coordination Lock} \longrightarrow \text{Level 2: All Users Lock (Ascending PK)} \longrightarrow \text{Level 3: Membership Lock (Ascending PK)} \longrightarrow \text{Level 4: Academic Parent Locks} \longrightarrow \text{Level 5: Academic Child Locks}$$

---

## 10. Service-Level Locking Matrix (14 Administrative Services)

| Service Function | Operation Code | Candidate Read | Level 1: College Lock | Level 2: All Users Lock (Ascending PK) | Level 3: Membership Lock | Level 4: Parent Locks | Level 5: Child Locks | Recheck & Outcome |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| `review_student_registration` | `student.registration.review` | Target user & college from approval | `lock_colleges(college_id)` | `User.objects.filter(pk__in=sorted([actor_id, target_id])).order_by('pk')` | Membership `FOR UPDATE` | Target User verified | `RegistrationApproval`, `StudentProfile` `FOR UPDATE` | Recheck pending, verified email; approve/reject |
| `update_student_profile` | `student.profile.manage` | Profile PK, college | `lock_colleges(college_id)` | `User.objects.filter(pk__in=sorted([actor_id, student_id])).order_by('pk')` | Membership `FOR UPDATE` | Student User verified | `StudentProfile` `FOR UPDATE` | Recheck semester bounds, save |
| `provision_faculty` | `faculty.account.provision` | Target college, department | `lock_colleges(college_id)` | `User.objects.select_for_update().get(pk=actor_id)` | Membership `FOR UPDATE` | Target User (New row) | `FacultyProfile` (New row) | Verify department same-college; create user & profile |
| `update_faculty_profile` | `faculty.profile.manage` | Profile PK, college, depts | `lock_colleges(college_id)` | `User.objects.filter(pk__in=sorted([actor_id, faculty_user_id])).order_by('pk')` | Membership `FOR UPDATE` | Faculty User verified | `FacultyProfile`, `Department` `FOR UPDATE` | Verify dept same-college, recheck examiner flag |
| `create_student_academic_record`| `enrollment.record.manage` | Student PK, college | `lock_colleges(college_id)` | `User.objects.filter(pk__in=sorted([actor_id, student_id])).order_by('pk')` | Membership `FOR UPDATE` | Student User verified | `StudentProfile`, `StudentAcademicRecord` | Verify same-college programme, save record |
| `update_student_academic_record`| `enrollment.record.manage` | Record PK, college | `lock_colleges(college_id)` | `User.objects.filter(pk__in=sorted([actor_id, student_id])).order_by('pk')` | Membership `FOR UPDATE` | Student User verified | `StudentAcademicRecord` `FOR UPDATE` | Revalidate status transition, save |
| `assign_faculty_to_paper` | `academic.faculty_assignment.manage` | Offering PK, Faculty PK | `lock_colleges(college_id)` | `User.objects.filter(pk__in=sorted([actor_id, faculty_user_id])).order_by('pk')` | Membership `FOR UPDATE` | `PaperOffering`, `FacultyProfile` `FOR UPDATE`| `FacultySubjectAssignment` (New) | Verify same-college, examiner flag; create |
| `update_faculty_assignment` | `academic.faculty_assignment.manage` | Assignment PK, offerings, fac | `lock_colleges(*sorted_colleges)`| `User.objects.filter(pk__in=sorted([actor_id, faculty_user_id])).order_by('pk')` | Membership `FOR UPDATE` | `PaperOffering`, `FacultyProfile` `FOR UPDATE`| `FacultySubjectAssignment` `FOR UPDATE`| Reconcile stale snapshot, verify examiner; save |
| `delete_faculty_assignment` | `academic.faculty_assignment.manage` | Assignment PK, offering | `lock_colleges(college_id)` | `User.objects.select_for_update().get(pk=actor_id)` | Membership `FOR UPDATE` | `PaperOffering` `FOR UPDATE` | `FacultySubjectAssignment` `FOR UPDATE`| Reconcile stale snapshot, delete assignment |
| `update_programme` | `academic.programme.manage` | Programme PK, college | `lock_colleges(college_id)` | `User.objects.select_for_update().get(pk=actor_id)` | Membership `FOR UPDATE` | `Programme` `FOR UPDATE` | Child `Semester` count query | Revalidate duration covers semesters; save |
| `set_current_academic_session` | `academic.session.manage` | Session PK, college | `lock_colleges(college_id)` | `User.objects.select_for_update().get(pk=actor_id)` | Membership `FOR UPDATE` | `AcademicSession` (All for college) `FOR UPDATE`| None | Deactivate other sessions, activate target |
| `set_institutional_config` | `academic.config.manage` | College PK, config key | `lock_colleges(college_id)` | `User.objects.select_for_update().get(pk=actor_id)` | Membership `FOR UPDATE` | `InstitutionalConfig` `FOR UPDATE` | None | Verify value format, save config |
| `grant_administrative_membership`| `admin.membership.manage` | College PK, User PK | `lock_colleges(college_id)` | `User.objects.filter(pk__in=sorted([superadmin_id, target_admin_id])).order_by('pk')` | None (New membership row) | Target User verified | None | Verify Superadmin, check target role; create |
| `revoke_administrative_membership`| `admin.membership.manage` | Membership PK, college | `lock_colleges(college_id)` | `User.objects.filter(pk__in=sorted([superadmin_id, target_admin_id])).order_by('pk')` | `AdministrativeMembership` `FOR UPDATE`| Target User verified | None | Set `is_active=F`, `status='REVOKED'`; save |

---

## 11. Multi-Connection MySQL Concurrency Test Design

The following 10 real multi-connection integration tests are specified for post-approval implementation, using `TransactionTestCase` with multiple independent database connections:

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

## 12. Durable Administrative Audit Retention Analysis

### 12.1 Policy Evaluation: Policy A vs. Policy B
- **Policy A — Audit Prerequisite (Recommended for Production):** Administrative membership mutations remain gated until Table 51 (`audit_system_audit_log` from Domain I) is implemented via explicit owner authorization. Guarantees durable relational audit history across reappointments.
- **Policy B — Explicit Interim Limitation (Development / Staging Only):** Project owner accepts temporary structured application logging (`college.accounts.audit`) for membership lifecycle events until Chunk 15 implements Table 51. Discloses that application logs can be rotated/lost and that reappointment overwrites row metadata.
- **Owner Decision Gate:** Policy A is recommended for production. The choice between Policy A and Policy B is submitted to the project owner for decision and is not selected on the owner's behalf.

---

## 13. Phased Deployment & Rollback Strategy

1. **Stage 1 (Schema Introduction):** Apply migration `accounts.0002_administrative_membership` during maintenance window with active transactions drained.
2. **Stage 2 (Dual-Compatible Code):** Deploy code; institutional authorization remains fail-closed for unmapped admins.
3. **Stage 3 (Membership Provisioning):** Superadmin provisions initial memberships via audited bootstrap script.
4. **Stage 4 (Gate Activation):** Switch `authorize_institutional_operation` to permit active members.
5. **Stage 5 (Verification):** Staging regression verification.

---

# Final Targeted Corrections — P4-A Through P4-D

---

## 14. Targeted Corrections Specification

### 14.1 Finding P4-A: Unknown-Operation Authorization Correction
In Round 2, `get_authorized_college_ids_for_operation` checked Superadmin status *before* verifying the operation registry:
```python
# DEFECTIVE ROUND 2 SEQUENCE:
if actor.role == RoleChoices.SUPERADMIN:
    return None  # Permitted unregistered operations for Superadmin!
if operation not in VALID_INSTITUTIONAL_OPERATIONS:
    return set()
```

**Corrected Policy:** Every authorization check validates the requested operation identifier against `VALID_INSTITUTIONAL_OPERATIONS` **before evaluating actor privileges**.

Superadministrator authority:
- Bypasses ordinary college-membership requirements for valid operations.
- Does **not** bypass authentication or active account status.
- Does **not** permit unknown or unregistered operations.
- Does **not** bypass mandatory academic integrity constraints (e.g., student profile requirement, same-college programme matching).

### 14.2 Revised Centralized Authorization Contract
The centralized interface enforces this unbypassable 11-step evaluation pipeline:

```python
# Proposed Interface: backend/apps/accounts/authorization.py

def authorize_institutional_operation(
    actor,
    college_id: Union[int, College],
    operation: str,
) -> InstitutionalAuthorizationContext:
    """
    Two-Dimensional Institutional Authorization Interface (Findings P2-A, P3-A, P4-A).
    
    Evaluation Pipeline:
    1. Validate operation type is str. If not, raise PermissionDenied.
    2. Confirm operation exists in VALID_INSTITUTIONAL_OPERATIONS. If not, raise PermissionDenied.
    3. Verify actor is authenticated. If not, raise NotAuthenticated (HTTP 401).
    4. Verify actor is active. If not, raise PermissionDenied (HTTP 403).
    5. Reject STUDENT and FACULTY accounts from administrative operations.
    6. Verify college_id is valid integer/model and college exists and is active.
    7. Superadmin bypass: If SUPERADMIN or is_superuser, grant access for this registered operation.
    8. Ordinary ADMIN: Query active AdministrativeMembership for (actor, college_id).
    9. Resolve membership.role.code.
    10. Verify operation in INSTITUTIONAL_ROLE_PERMISSIONS[role_code].
    11. If any check fails, raise PermissionDenied (HTTP 403).
    """
```

### 14.3 Unified Global Transaction Lock Hierarchy (Finding P4-B)
To eliminate cross-workflow lock conflicts, the system defines one authoritative Five-Level Global Lock Hierarchy:

```
+----------------------------------------------------------------------------------------------------+
| LEVEL   | ENTITY TYPE                   | ORDERING DISCIPLINE                                      |
+---------+-------------------------------+----------------------------------------------------------+
| Level 1 | Academics College             | Strictly ascending primary-key order (lock_colleges)     |
| Level 2 | Accounts User (All Roles)     | All involved User rows in ascending PK order (Actor/Tgt) |
| Level 3 | AdministrativeMembership      | All involved Membership rows in ascending PK order       |
| Level 4 | Academic Parent Records       | AcademicSession -> Programme -> Department -> PaperOffer |
| Level 5 | Academic Child Records        | RegApproval -> EmailVerify -> StudentProf -> FacultyProf |
+----------------------------------------------------------------------------------------------------+
```

### 14.4 Membership Mutation Lock Sequences
1. **Grant Membership:** Level 1 College $\rightarrow$ Level 2 `sorted([superadmin.pk, target_user.pk])` $\rightarrow$ Level 3 (New row created under lock).
2. **Update Institutional Role:** Level 1 College $\rightarrow$ Level 2 `sorted([superadmin.pk, target_user.pk])` $\rightarrow$ Level 3 Membership `FOR UPDATE`.
3. **Suspend / Reinstate Membership:** Level 1 College $\rightarrow$ Level 2 `sorted([superadmin.pk, target_user.pk])` $\rightarrow$ Level 3 Membership `FOR UPDATE`.
4. **Revoke Membership:** Level 1 College $\rightarrow$ Level 2 `sorted([superadmin.pk, target_user.pk])` $\rightarrow$ Level 3 Membership `FOR UPDATE`.
5. **Reappoint Member:** Level 1 College $\rightarrow$ Level 2 `sorted([superadmin.pk, target_user.pk])` $\rightarrow$ Level 3 Membership `FOR UPDATE`.
6. **Demote User Role:** Level 1 All colleges where user has active memberships in ascending PK order $\rightarrow$ Level 2 `sorted([superadmin.pk, target_user.pk])` $\rightarrow$ Level 3 All user memberships `FOR UPDATE`.
7. **Simultaneous Multi-College Update:** Level 1 All affected colleges in ascending PK order $\rightarrow$ Level 2 User $\rightarrow$ Level 3 Memberships in ascending PK order.

### 14.5 Cross-Service Lock Interaction Analysis
All 13 administrative services reconcile with this global hierarchy:
- In `review_student_registration()`, Level 1 College is locked first. At Level 2, `User.objects.filter(pk__in=sorted([reviewer.pk, target_user.pk])).select_for_update().order_by('pk')` locks both users in deterministic order, completely eliminating deadlock with membership mutation services.
- Academic mutations lock Level 1 College, Level 2 Actor User, Level 3 Membership, then Level 4/5 academic entities. Because Level 1 College lock serializes all mutations within that institution, no cyclic dependencies can occur.

### 14.6 Student Self-Service Separation (Domain B) (Finding P4-C)
Student self-service is formally isolated from administrative RBAC:
- **Authorization Authority:** Authenticated identity + `StudentProfile` ownership (`request.user.pk == profile.user_id`).
- **Permitted Operations:**
  - `GET /api/v1/students/profiles/me/`: Read own profile.
  - `PATCH /api/v1/students/profiles/me/`: Update permitted personal contact fields (`phone_number`, `guardian_name`).
  - `GET /api/v1/enrollments/records/`: Read own academic ledger entries (`filter(student__user=request.user)`).
- **Prohibited:** Students cannot modify institutional fields (`enrollment_number`, `college`, `programme`, `current_semester`).
- **Isolation Guarantee:** An empty administrative college scope never impairs legitimate student self-service.

### 14.7 Faculty Self-Service Separation (Domain C) (Finding P4-C)
Faculty self-service is formally isolated from administrative RBAC:
- **Authorization Authority:** Authenticated identity + `FacultyProfile` ownership (`request.user.pk == profile.user_id`).
- **Permitted Operations:**
  - `GET /api/v1/faculty/profiles/me/`: Read own profile.
  - `PATCH /api/v1/faculty/profiles/me/`: Update permitted personal contact fields (`phone_number`).
  - `GET /api/v1/academics/assignments/`: Read explicitly assigned papers (`filter(faculty__user=request.user)`).
- **Prohibited:** Faculty cannot modify institutional fields (designation, department, examiner eligibility).
- **Isolation Guarantee:** A faculty profile never confers administrative review or mutation privileges.

### 14.8 General Academic Read-Access Treatment (Domain D) (Finding P4-C)
Academic reference data visibility is governed by its own reference policy:
- **Public Reference Data (All Authenticated Users):** `Programme`, `Semester`, `Subject`, `AcademicSession` are readable across colleges to facilitate syllabus inquiries and curriculum browsing.
- **College-Scoped Reference Data:** `PaperOffering` records are scoped to students enrolled in mapped programmes and faculty teaching in the session/college.
- **Protected Configuration:** `InstitutionalConfig` is barred from general read access; restricted strictly to institutional administrators holding `academic.config.read`.

### 14.9 Audit Transaction Semantics (Finding P4-D)
Under Policy A, successful administrative mutations and audit events commit atomically:
```python
@transaction.atomic
def grant_administrative_membership(*, actor, target_user, college, role):
    # 1. Acquire Level 1 College Lock
    lock_colleges(college.pk)
    # 2. Acquire Level 2 User Locks in ascending order
    users = list(User.objects.filter(pk__in=sorted([actor.pk, target_user.pk])).select_for_update().order_by('pk'))
    # 3. Validate actor is Superadmin, target is ADMIN
    ...
    # 4. Mutate membership
    membership = AdministrativeMembership.objects.create(...)
    # 5. Persist audit record in same transaction
    SystemAuditLog.objects.create(
        actor_id=actor.pk,
        actor_role='SUPERADMIN',
        action='ADMIN_MEMBERSHIP_GRANTED',
        entity_type='AdministrativeMembership',
        entity_id=str(membership.pk),
        after_state_json={...},
        ...
    )
    # 6. Atomic commit
```
If audit insertion fails (e.g. database error), the entire transaction rolls back, preventing un-audited administrative appointments.

### 14.10 Rejected Security-Event Persistence (Finding P4-D)
Unauthorized access attempts occur during requests that fail or transactions that roll back. An audit insert inside that transaction would be erased upon rollback.

**Dual Persistence Strategy for Security Rejections:**
1. Rejections raise `PermissionDenied` or `ValidationError`, triggering transaction rollback.
2. The exception handler or authorization service emits a sanitized security audit event to a dedicated security sink (`logger = logging.getLogger('college.accounts.security')`).
3. Under no circumstances are nested database transactions used to force uncommitted writes.
4. Raw passwords, verification tokens, or examination PINs are never included in rejection logs.

### 14.11 Honest Tamper-Evidence Limitations (Finding P4-D)
1. **Append-Only Application Model:** Table 51's append-only database permission model prevents ordinary application `UPDATE` and `DELETE` operations.
2. **Infrastructure Disclaimer:** Append-only permissions do **not** constitute cryptographic tamper evidence or absolute non-repudiation. Database administrators or compromised database hosts could alter records.
3. **Cryptographic Proof Limitation:** True cryptographic tamper evidence requires Merkle tree chaining, digital signatures, external hash notarization, or tamper-proof ledger services, none of which are approved or present in the architecture.
4. **Legal Evidentiary Nature:** Audit records represent application-level evidence of system events, not mathematical proof of human identity.

---

## 15. Explicit Project-Owner Approval Checklist

Before any code implementation begins, the project owner must review this proposal and explicitly decide:

- [ ] **1. Architecture Selection:** Formally approve **Option B (Dedicated Administrative Membership Mapping Table)** with **Two-Dimensional Institutional Authorization**.
- [ ] **2. Schema Baseline Expansion:** Formally approve expanding the relational database architecture from **52 tables to 53 tables** to accommodate Table 53 (`accounts_administrative_membership`).
- [ ] **3. Mandatory Institutional Role:** Approve making `role_id` mandatory (`NOT NULL`) on Table 53.
- [ ] **4. Audit Retention Policy Selection:**
  - [ ] **Approve Policy A (Audit Prerequisite):** Bring forward Table 51 (`audit_system_audit_log`) for durable administrative auditing prior to production deployment.
  - [ ] **Approve Policy B (Interim Application Logging):** Authorize temporary structured application logging for development environments with documented limitations.
- [ ] **5. Authorization Matrix:** Approve the 25-operation institutional authorization matrix defined in Section 8.
- [ ] **6. Chunk 06 Round 6 Implementation:** Authorize the engineering team to implement Table 53, generate migration `0002_administrative_membership`, and wire `authorize_institutional_operation`.

---

## 16. Stop Condition & Governance Attestation

In accordance with explicit governance instructions:
- **Zero code changes** have been made to Django models, services, serializers, or views.
- **Zero migrations** have been created.
- Protected files ([`design.md`](file:///home/zero/Documents/college/design.md), [`handover.txt`](file:///home/zero/Documents/college/handover.txt), [`docs/architecture.md`](file:///home/zero/Documents/college/docs/architecture.md), [`docs/database-architecture.md`](file:///home/zero/Documents/college/docs/database-architecture.md), [`docs/development-progress.md`](file:///home/zero/Documents/college/docs/development-progress.md)) remain untouched.
- Git commit and push remain unexecuted.
- Chunk 07 onward remains strictly gated.
- Android application development remains paused.

```
===================================================================================================
STOP CONDITION MET: FINAL TARGETED CORRECTIONS COMPLETED.
AWAITING INDEPENDENT ARCHITECTURE AUDIT AND FORMAL PROJECT-OWNER APPROVAL.
DO NOT BEGIN IMPLEMENTATION UNTIL OWNER EXPLICITLY APPROVES.
===================================================================================================
```
