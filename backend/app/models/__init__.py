"""SQLAlchemy models. Importing this package registers every table on Base.metadata."""

from app.models.audit import AuditLog
from app.models.base import Base
from app.models.documents import (
    Case,
    CaseStatus,
    Document,
    DocumentPage,
    DocumentStage,
    DocumentStatus,
    DocumentVersion,
    ExtractedField,
    ExtractionRun,
)
from app.models.findings import (
    EvidenceItem,
    Finding,
    FindingDecision,
    FindingStatus,
    InvestigatorComment,
)
from app.models.forensics import ForensicAnomaly, ForensicRun
from app.models.graph import Entity, EntityMention, OutboxEvent, Relationship
from app.models.identity import Organization, OrganizationMember, RefreshToken, Role, User
from app.models.job import TERMINAL_STATUSES, Job, JobEvent, JobStatus

__all__ = [
    "TERMINAL_STATUSES",
    "AuditLog",
    "Base",
    "Case",
    "CaseStatus",
    "Document",
    "DocumentPage",
    "DocumentStage",
    "DocumentStatus",
    "DocumentVersion",
    "Entity",
    "EntityMention",
    "EvidenceItem",
    "ExtractedField",
    "ExtractionRun",
    "Finding",
    "FindingDecision",
    "FindingStatus",
    "ForensicAnomaly",
    "ForensicRun",
    "InvestigatorComment",
    "Job",
    "JobEvent",
    "JobStatus",
    "Organization",
    "OrganizationMember",
    "OutboxEvent",
    "RefreshToken",
    "Relationship",
    "Role",
    "User",
]
