from typing import Literal

from pydantic import BaseModel, Field

Role = Literal["coordinator", "consolidator", "distributor", "transit", "terminal", "peripheral"]
RunStatus = Literal["queued", "running", "succeeded", "failed", "cancelled"]
StageCode = Literal["queued", "validating", "features", "roles", "clusters", "exports", "publishing", "done"]
MetricUnit = Literal["kzt", "share", "count", "days", "z", "gid", "ratio"]
RunErrorCode = Literal["validation_error", "engine_error", "worker_crashed", "timeout", "cancelled"]


class FieldIssue(BaseModel):
    field: str
    message: str


class ErrorBody(BaseModel):
    code: str
    message: str
    request_id: str
    details: list[FieldIssue] | None = None
    retryable: bool = False


class ErrorResponse(BaseModel):
    error: ErrorBody


class Health(BaseModel):
    status: str
    version: str


class Limits(BaseModel):
    max_upload_mb: int
    max_zip_members: int
    max_nodes: int
    max_transactions: int


class Meta(BaseModel):
    version: str
    auth_required: bool
    llm_enabled: bool
    limits: Limits


class RoleInfo(BaseModel):
    label: str
    color: str
    rule: str


class PriorityComponentInfo(BaseModel):
    key: str
    label: str
    weight: float


class Methodology(BaseModel):
    roles: dict[str, RoleInfo]
    role_order: list[Role]
    flags: dict[str, str]
    priority_components: list[PriorityComponentInfo]
    limitations: list[str]


class SessionState(BaseModel):
    authenticated: bool
    auth_required: bool


class SessionLogin(BaseModel):
    token: str = Field(min_length=1, max_length=512)


class RunParams(BaseModel):
    observation_start: str | None = None
    observation_end: str | None = None
    max_depth: int | None = None
    min_transfer_kzt: float | None = None
    collection_direction: Literal["outgoing"] = "outgoing"


class RunError(BaseModel):
    code: RunErrorCode
    message: str
    retryable: bool
    details: list[FieldIssue] | None = None


class RunSummary(BaseModel):
    n_nodes: int
    n_edges: int
    n_tx: int
    n_seeds: int
    total_kzt: float
    period: list[str]
    n_clusters: int
    roles: dict[str, int]
    flags: dict[str, int]


class Run(BaseModel):
    id: str
    name: str
    source: Literal["upload", "demo"]
    status: RunStatus
    cancel_requested: bool
    stage_code: StageCode | None
    stage_label: str | None
    progress: float | None
    error: RunError | None
    attempts: int
    created_at: str
    updated_at: str
    started_at: str | None
    finished_at: str | None
    duration_s: float | None
    poll_after_ms: int | None
    params: RunParams
    warnings: list[str]
    summary: RunSummary | None
    engine_version: str | None


class RunList(BaseModel):
    items: list[Run]
    total: int


class ModelQuality(BaseModel):
    status: Literal["ok", "insufficient_data"]
    auc_cv: float | None
    auc_transfer: float | None
    base_rate: float | None
    n_train: int


class ResilienceRow(BaseModel):
    removed_top_n: int
    reach_top: float
    flow_top: float
    reach_random: float
    flow_random: float
    components_top: int
    components_random: float


class Resilience(BaseModel):
    base: dict[str, float]
    rows: list[ResilienceRow]


class Overview(BaseModel):
    summary: RunSummary
    model: ModelQuality
    resilience: Resilience
    data_requests: dict[str, int]
    warnings: list[str]
    params: RunParams


class GraphNode(BaseModel):
    id: str
    x: float
    y: float
    role: Role
    cluster_id: int
    priority_score: float
    priority_rank: int
    top_rank: int | None
    is_seed: bool
    truncated: bool
    in_kzt: float
    out_kzt: float


class GraphEdge(BaseModel):
    source: str
    target: str
    sum_kzt: float
    n_tx: int
    first_date: str
    last_date: str


class Subgraph(BaseModel):
    center: str | None
    nodes: list[GraphNode]
    edges: list[GraphEdge]
    total_nodes: int
    total_edges: int
    truncated: bool
    truncation_reason: Literal["max_nodes", "max_edges"] | None


class HydrateRequest(BaseModel):
    ids: list[str] = Field(max_length=500)
    include_edges: bool = True


class NodeRow(BaseModel):
    id: str
    role: Role
    role_score: float
    priority_score: float
    priority_rank: int
    top_rank: int | None
    cluster_id: int
    depth: int
    is_seed: bool
    truncated: bool
    flags: list[str]
    in_deg: int
    out_deg: int
    in_kzt: float
    out_kzt: float
    in_tx: int
    out_tx: int
    evidence: str


class NodePage(BaseModel):
    items: list[NodeRow]
    total: int


class SearchHit(BaseModel):
    id: str
    role: Role
    priority_score: float
    priority_rank: int


class SearchResult(BaseModel):
    items: list[SearchHit]
    total: int


class Metric(BaseModel):
    key: str
    label: str
    value: float | int | str | None
    unit: MetricUnit | None


class PriorityComponent(BaseModel):
    key: str
    label: str
    weight: float
    value: float
    contribution: float


class RuleChecks(BaseModel):
    coordinator: bool
    consolidator: bool
    distributor: bool
    transit: bool
    terminal: bool


class NodeDetail(NodeRow):
    card: str
    why: str | None
    metrics: list[Metric]
    priority_components: list[PriorityComponent]
    priority_reliability: float
    rules: RuleChecks
    n_payers: int
    n_recipients: int


class Counterparty(BaseModel):
    id: str
    role: Role
    sum_kzt: float
    n_tx: int
    first_date: str
    last_date: str


class CounterpartyPage(BaseModel):
    items: list[Counterparty]
    total: int


class Transaction(BaseModel):
    date: str
    source: str
    target: str
    sum_kzt: float


class TransactionPage(BaseModel):
    items: list[Transaction]
    total: int


class PathResult(BaseModel):
    found: bool
    directed: bool
    nodes: list[str]
    edges: list[GraphEdge]


class TopItem(BaseModel):
    top_rank: int
    id: str
    role: Role
    priority_score: float
    role_score: float
    is_seed: bool
    cluster_id: int
    evidence: str
    why: str
    flags: list[str]


class TopList(BaseModel):
    items: list[TopItem]


class Cluster(BaseModel):
    cluster_id: int
    n_nodes: int
    n_seed: int
    sum_kzt_internal: float
    top_gids: list[str]
    hypothesis: str
    max_priority: float
    roles: dict[str, int]
    n_truncated: int


class ClusterPage(BaseModel):
    items: list[Cluster]
    total: int


class DataRequest(BaseModel):
    id: str
    request: str
    value_kzt: float
    reason: str


class DataRequestPage(BaseModel):
    items: list[DataRequest]
    total: int


class AssistantRequest(BaseModel):
    question: str = Field(min_length=1, max_length=2000)
    mode: Literal["auto", "offline", "llm"] = "auto"


class Citation(BaseModel):
    id: str
    role: Role
    note: str


class AssistantAction(BaseModel):
    type: Literal["focus", "highlight", "path"]
    ids: list[str]
    label: str


class Highlight(BaseModel):
    nodes: list[str]
    edges: list[list[str]]


class Candidate(BaseModel):
    fragment: str
    ids: list[str]


class AssistantAnswer(BaseModel):
    mode_used: Literal["offline", "llm"]
    intent: str
    answer_markdown: str
    citations: list[Citation]
    actions: list[AssistantAction]
    highlight: Highlight
    candidates: list[Candidate]
    warnings: list[str]
    suggestions: list[str]


class ExportItem(BaseModel):
    name: str
    filename: str
    content_type: str
    size_bytes: int | None
    description: str


class ExportList(BaseModel):
    items: list[ExportItem]
