"""Transport-independent contracts. Unknown fields are always rejected."""
from typing import Any, Literal
from pydantic import BaseModel, ConfigDict, Field, model_validator


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ReadRequest(Strict):
    project: str | None = None
    book_id: str | None = None


class BookStatus(ReadRequest):
    brief: bool = False


class WriteRequest(ReadRequest):
    project: str
    book_id: str
    operation_id: str = Field(min_length=1)
    run_id: str | None = None


class BookInit(Strict):
    project: str
    title: str = Field(min_length=1)
    operation_id: str = Field(min_length=1)


class SourceGet(ReadRequest):
    source_version: str
    offset: int = Field(default=0, ge=0)
    max_chars: int = Field(default=12000, ge=1, le=100000)
    if_none_match: str | None = Field(default=None, description="Only supply a hash when this exact source/page is already cached and available to the caller.")


class Finding(Strict):
    severity: Literal["info", "warning", "critical"]
    message: str
    quote: str = ""


class Review(Strict):
    source_version: str
    source_hash: str
    findings: list[Finding] = Field(default_factory=list)
    summary: str = ""


class SourceSave(WriteRequest):
    model_config = ConfigDict(json_schema_extra={"allOf": [
        {"if": {"properties": {"kind": {"const": "chapter"}}, "required": ["kind"]},
         "then": {"required": ["chapter", "context_id"], "properties": {"chapter": {"type": "integer"}, "context_id": {"type": "string", "minLength": 1}}},
         "else": {"properties": {"chapter": {"type": "null"}}}},
        {"if": {"properties": {"kind": {"const": "review"}}, "required": ["kind"]},
         "then": {"required": ["review"], "properties": {"review": {"type": "object"}}}}
    ]})
    kind: Literal["chapter", "outline", "setting", "research", "idea", "style", "decision", "review"]
    logical_id: str = Field(min_length=1)
    content: str
    chapter: int | None = Field(default=None, ge=1)
    context_id: str | None = None
    review: Review | None = None
    expected_source_hash: str | None = None

    @model_validator(mode="after")
    def validate_kind(self):
        if self.kind == "chapter" and (self.chapter is None or not self.context_id):
            raise ValueError("chapter saves require chapter and context_id")
        if self.kind == "chapter" and not self.content.strip():
            raise ValueError("a chapter cannot be empty")
        if self.kind == "review" and self.review is None:
            raise ValueError("review saves require structured review")
        if self.kind != "chapter" and self.chapter is not None:
            raise ValueError("only chapter sources have a chapter number")
        return self


class Evidence(Strict):
    quote: str = Field(min_length=1)
    offset: int = Field(ge=0)


class Entity(Strict):
    id: str = Field(min_length=1)
    name: str = Field(min_length=1)
    kind: str = "character"
    aliases: list[str] = Field(default_factory=list)


class Fact(Strict):
    model_config = ConfigDict(json_schema_extra={"oneOf": [
        {"required": ["object"], "properties": {"object": {"type": "string"}, "value": {"type": "null"}}},
        {"required": ["value"], "properties": {"value": {"type": "string"}, "object": {"type": "null"}}}
    ]})
    id: str = Field(min_length=1)
    subject: str
    predicate: str
    object: str | None = None
    value: str | None = None
    evidence: Evidence
    certainty: Literal["established", "candidate"] = "established"
    valid_from: int | None = Field(default=None, ge=0)
    story_time: str | None = None

    @model_validator(mode="after")
    def object_or_value(self):
        if (self.object is None) == (self.value is None):
            raise ValueError("fact requires exactly one of object or value")
        return self


class CloseFact(Strict):
    id: str
    evidence: Evidence


class Knowledge(Strict):
    character: str  # reserved value 'reader' denotes reader knowledge
    fact: str
    state: Literal["knows", "believes", "heard", "rejects"]
    evidence: Evidence


class Hook(Strict):
    id: str
    summary: str
    status: Literal["open", "progressing", "deferred", "resolved"] = "open"
    target_chapter: int | None = Field(default=None, ge=1)
    evidence: Evidence


class MemoryDelta(Strict):
    source_hash: str
    entities: list[Entity] = Field(default_factory=list)
    facts: list[Fact] = Field(default_factory=list)
    close_facts: list[CloseFact] = Field(default_factory=list)
    knowledge: list[Knowledge] = Field(default_factory=list)
    hooks: list[Hook] = Field(default_factory=list)
    summary: str = ""


class MemoryStage(WriteRequest):
    source_version: str
    base_revision: int = Field(ge=0)
    delta: MemoryDelta


class SourceAccept(WriteRequest):
    source_version: str
    expected_revision: int = Field(ge=0)
    batch_id: str | None = None
    review_id: str | None = None


class MemorySync(WriteRequest):
    model_config = ConfigDict(json_schema_extra={"allOf": [{
        "if": {"properties": {"mode": {"const": "apply"}}, "required": ["mode"]},
        "then": {"required": ["source_version", "base_revision", "delta"], "properties": {
            "source_version": {"type": "string"}, "base_revision": {"type": "integer"}, "delta": {"type": "object"}}}
    }]})
    mode: Literal["next", "apply"] = "next"
    job_id: str
    source_version: str | None = None
    base_revision: int | None = Field(default=None, ge=0)
    delta: MemoryDelta | None = None
    include_source: bool = False
    max_chars: int = Field(default=12000, ge=1, le=100000)

    @model_validator(mode="after")
    def validate_apply(self):
        if self.mode == "apply" and (not self.source_version or self.base_revision is None or self.delta is None):
            raise ValueError("apply requires source_version, base_revision and delta")
        return self


class RevisionItem(Strict):
    source_version: str
    source_hash: str
    review_id: str


class RevisionBatch(WriteRequest):
    """Stage an ordered replacement suffix, then commit all canon changes atomically."""
    model_config = ConfigDict(json_schema_extra={"allOf": [
        {"if": {"properties": {"mode": {"const": "prepare"}}, "required": ["mode"]},
         "then": {"required": ["revisions", "expected_revision"], "properties": {"revisions": {"type": "array", "minItems": 1}, "expected_revision": {"type": "integer"}}},
         "else": {"required": ["job_id"], "properties": {"job_id": {"type": "string"}}}},
        {"if": {"properties": {"mode": {"const": "apply"}}, "required": ["mode"]},
         "then": {"required": ["source_version", "delta"], "properties": {"source_version": {"type": "string"}, "delta": {"type": "object"}}}},
        {"if": {"properties": {"mode": {"const": "commit"}}, "required": ["mode"]},
         "then": {"required": ["expected_revision"], "properties": {"expected_revision": {"type": "integer"}}}}
    ]})
    mode: Literal["prepare", "next", "context", "apply", "commit", "abort"]
    job_id: str | None = None
    expected_revision: int | None = Field(default=None, ge=0)
    revisions: list[RevisionItem] | None = Field(default=None, min_length=1, max_length=500)
    source_version: str | None = None
    delta: MemoryDelta | None = None
    include_source: bool = False
    max_chars: int = Field(default=12000, ge=1, le=100000)
    entity_ids: list[str] = Field(default_factory=list, description="For context only: filter candidate-prefix facts by stable IDs.")

    @model_validator(mode="after")
    def validate_mode(self):
        if self.mode == "prepare" and (not self.revisions or self.expected_revision is None):
            raise ValueError("prepare requires revisions and expected_revision")
        if self.mode != "prepare" and not self.job_id:
            raise ValueError("job_id is required")
        if self.mode == "apply" and (not self.source_version or self.delta is None):
            raise ValueError("apply requires source_version and delta")
        if self.mode == "commit" and self.expected_revision is None:
            raise ValueError("commit requires expected_revision")
        return self


class EntityResolve(ReadRequest):
    query: str = Field(min_length=1)
    chapter: int | None = Field(default=None, ge=0)
    pov: str | None = Field(default=None, description="With POV, only visible stable IDs are matched; names/aliases are not resolved.")
    kind: str | None = None
    limit: int = Field(default=10, ge=1, le=50)


class ErrorDetail(Strict):
    code: str
    message: str
    retryable: bool
    exit_code: int
    details: dict[str, Any] = Field(default_factory=dict)


class ResponseEnvelope(Strict):
    schema_version: int
    status: Literal["ok", "error", "partial", "awaiting_author"]
    book_id: str | None
    revision: int | None
    data: dict[str, Any]
    warnings: list[dict[str, Any]]
    error: ErrorDetail | None
    next_actions: list[dict[str, Any]]


class SceneBrief(Strict):
    goal: str = ""
    story_time: str = ""
    constraints: list[str] = Field(default_factory=list)
    reveal_limit: str = ""


class ContextBuild(ReadRequest):
    task: Literal["write", "revise", "review", "plan", "query"] = "write"
    chapter: int | None = Field(default=None, ge=1)
    query: str = ""
    entity_ids: list[str] = Field(default_factory=list)
    pov: str | None = None
    draft_id: str | None = None
    scene_brief: SceneBrief | None = None
    budget_chars: int = Field(default=12000, ge=500, le=100000)
    run_id: str | None = None


class Search(ReadRequest):
    query: str
    chapter: int | None = Field(default=None, ge=0)
    scope: Literal["canon", "plan", "reference"] = "canon"
    limit: int = Field(default=12, ge=1, le=50)
    explain: bool = True


class GraphQuery(ReadRequest):
    mode: Literal["entity", "neighbors", "path", "timeline"] = "neighbors"
    entity: str | None = None
    target: str | None = None
    chapter: int | None = Field(default=None, ge=0)
    depth: int = Field(default=1, ge=1, le=2)
    pov: str | None = None


class ImportMapping(Strict):
    title: str
    content: str
    chapter: int = Field(ge=1)


class BookImport(WriteRequest):
    mode: Literal["preview", "start"]
    files: list[str] = Field(default_factory=list)
    encoding: str | None = None
    split_rule: str | None = None
    mapping_id: str | None = None
    mapping: list[ImportMapping] | None = None


class IndexUpdate(WriteRequest):
    mode: Literal["update", "rebuild"] = "update"
    embedding: bool = False


ACTION_MODELS = {
    "revision_batch": RevisionBatch, "entity_resolve": EntityResolve,
    "book_init": BookInit, "book_status": BookStatus, "book_import": BookImport,
    "source_get": SourceGet, "source_save": SourceSave, "source_accept": SourceAccept,
    "context_build": ContextBuild, "memory_stage": MemoryStage, "memory_sync": MemorySync,
    "search": Search, "graph_query": GraphQuery, "index_status": ReadRequest,
    "index_update": IndexUpdate, "index_rebuild": IndexUpdate,
    "doctor_check": ReadRequest, "doctor_repair": WriteRequest,
}
