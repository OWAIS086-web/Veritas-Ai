"""SQLAlchemy models. Importing this package registers every table on Base.metadata."""

from app.models.audit import AuditLog
from app.models.base import Base
from app.models.doccompare import (
    COMPARISON_LIMITATION,
    ComparisonExport,
    ComparisonFinding,
    ComparisonReview,
    DocumentComparison,
)
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
from app.models.investigation import (
    FINISHED_STATUSES,
    AgentEvent,
    AgentRun,
    EvidenceRequest,
    Investigation,
    InvestigationCheckpoint,
    InvestigationCheckpointWrite,
    InvestigationStatus,
)
from app.models.job import TERMINAL_STATUSES, Job, JobEvent, JobStatus
from app.models.reporting import REPORT_FORMATS, Report

__all__ = [
    "COMPARISON_LIMITATION",
    "FINISHED_STATUSES",
    "REPORT_FORMATS",
    "TERMINAL_STATUSES",
    "AgentEvent",
    "AgentRun",
    "AuditLog",
    "Base",
    "Case",
    "CaseStatus",
    "ComparisonExport",
    "ComparisonFinding",
    "ComparisonReview",
    "Document",
    "DocumentComparison",
    "DocumentPage",
    "DocumentStage",
    "DocumentStatus",
    "DocumentVersion",
    "Entity",
    "EntityMention",
    "EvidenceItem",
    "EvidenceRequest",
    "ExtractedField",
    "ExtractionRun",
    "Finding",
    "FindingDecision",
    "FindingStatus",
    "ForensicAnomaly",
    "ForensicRun",
    "Investigation",
    "InvestigationCheckpoint",
    "InvestigationCheckpointWrite",
    "InvestigationStatus",
    "InvestigatorComment",
    "Job",
    "JobEvent",
    "JobStatus",
    "Organization",
    "OrganizationMember",
    "OutboxEvent",
    "RefreshToken",
    "Relationship",
    "Report",
    "Role",
    "User",
]
