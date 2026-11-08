"""Pydantic request/response models for the ExamPilot API."""

from __future__ import annotations

from datetime import date
from typing import Any

from pydantic import BaseModel, Field


class SessionCreate(BaseModel):
    name: str = Field(default="", max_length=128)


class SessionOut(BaseModel):
    id: str
    name: str
    created_at: Any = None
    memory_warning: str | None = None
    stats: dict = Field(default_factory=dict)


class SessionCreatedOut(BaseModel):
    """Identity creation response: the bearer token is returned exactly once."""

    session: SessionOut
    token: str


class DocumentOut(BaseModel):
    id: int | None = None
    filename: str
    ok: bool = True
    error: str | None = None
    duplicate: bool = False
    file_type: str = ""
    page_count: int = 0
    parse_status: str = ""
    classify_status: str = ""
    classify_confidence: float = 0.0
    classify_reason: str = "ok"
    course: str | None = None
    chapter: str | None = None
    knowledge_points: list[str] = Field(default_factory=list)
    course_candidates: list[dict] = Field(default_factory=list)
    chapter_candidates: list[dict] = Field(default_factory=list)
    kp_evidence: dict = Field(default_factory=dict)
    # classification results stored in classify_evidence — present even when
    # the suggested classification was not applied to a course row yet
    evidence_course: str | None = None
    evidence_chapter: str | None = None
    evidence_knowledge_points: list[str] = Field(default_factory=list)
    extracted_chars: int = 0
    ocr_required: bool = False
    warnings: list[str] = Field(default_factory=list)


class UploadResponse(BaseModel):
    session_id: str
    results: list[DocumentOut]


class ConfirmClassificationRequest(BaseModel):
    course: str = Field(min_length=1, max_length=256)
    chapter: str | None = Field(default=None, max_length=256)
    knowledge_points: list[str] = Field(default_factory=list)


class CourseOut(BaseModel):
    id: int
    name: str
    status: str
    confidence: float
    chapter_count: int
    knowledge_point_count: int
    document_count: int
    question_count: int


class KnowledgePointOut(BaseModel):
    id: int
    name: str
    course_id: int
    course_name: str | None = None
    chapter_name: str | None = None
    description: str | None = None
    mastery: dict | None = None


class SearchRequest(BaseModel):
    query: str = Field(min_length=1, max_length=2000)
    course_id: int | None = None
    chapter_id: int | None = None
    limit: int = Field(default=10, ge=1, le=50)


class SourceHitOut(BaseModel):
    chunk_id: int
    document_id: int
    filename: str
    course: str | None = None
    chapter: str | None = None
    page_number: int
    text: str
    score: float
    matched_by: list[str]


class MemoryRecallOut(BaseModel):
    available: bool
    mode: str | None = None
    hits: list[dict] = Field(default_factory=list)
    warning: str | None = None


class SearchResponse(BaseModel):
    query: str
    hits: list[SourceHitOut]
    mode: str
    fts_hits: int
    vector_hits: int
    warning: str | None = None
    memory: MemoryRecallOut = Field(
        default_factory=lambda: MemoryRecallOut(available=False)
    )


class ExplainRequest(BaseModel):
    knowledge_point_id: int | None = None
    query: str | None = Field(default=None, max_length=2000)
    question_stem: str | None = Field(default=None, max_length=2000)


class ExplainResponse(BaseModel):
    knowledge_point: str
    explanation: str
    provider: str
    sources: list[SourceHitOut] = Field(default_factory=list)
    memory: dict = Field(default_factory=dict)


class PracticeStartRequest(BaseModel):
    course_id: int | None = None
    knowledge_point_ids: list[int] = Field(default_factory=list)
    count: int = Field(default=5, ge=1, le=20)
    mode: str = Field(default="mixed", pattern="^(mixed|weak|mistakes)$")


class PracticeQuestionOut(BaseModel):
    id: int
    type: str
    stem: str
    options: list[dict] = Field(default_factory=list)
    difficulty: int
    knowledge_points: list[str] = Field(default_factory=list)


class PracticeStartResponse(BaseModel):
    practice_session_id: int
    course_id: int | None = None
    course_name: str | None = None
    mode: str
    total: int
    questions: list[PracticeQuestionOut]


class SubmitAnswer(BaseModel):
    question_id: int
    answer: str


class SubmitRequest(BaseModel):
    answers: list[SubmitAnswer] = Field(min_length=1)


class GradedAnswerOut(BaseModel):
    question_id: int
    type: str
    stem: str
    options: list[dict] = Field(default_factory=list)
    user_answer: str
    is_correct: bool
    score: float
    evidence: str
    correct_answer: str
    explanation: str
    knowledge_points: list[str] = Field(default_factory=list)


class SubmitResponse(BaseModel):
    practice_session_id: int
    total: int
    correct_count: int
    score: float
    results: list[GradedAnswerOut]
    mastery: list[dict] = Field(default_factory=list)
    review_tasks_created: int = 0
    memory: dict = Field(default_factory=dict)


class MistakeOut(BaseModel):
    question_id: int
    type: str
    stem: str
    options: list[dict] = Field(default_factory=list)
    correct_answer: str
    explanation: str
    knowledge_points: list[str] = Field(default_factory=list)
    wrong_count: int
    last_wrong_at: Any = None
    user_answers: list[str] = Field(default_factory=list)


class ReviewTaskOut(BaseModel):
    id: int
    knowledge_point_id: int
    knowledge_point_name: str
    course_name: str | None = None
    due_date: Any = None
    reason: str
    status: str
    mastery_score: float | None = None


class ReviewPlanResponse(BaseModel):
    due: list[ReviewTaskOut]
    upcoming: list[ReviewTaskOut]
    mastery: list[dict]


class ReviewCompleteRequest(BaseModel):
    correct: bool = True


class ReviewCompleteResponse(BaseModel):
    task_id: int
    status: str
    follow_up_task_id: int | None = None


class MemoryWriteRequest(BaseModel):
    kind: str = Field(min_length=1, max_length=128)
    text: str = Field(min_length=1)


class MemoryEventOut(BaseModel):
    id: int
    session_id: str
    kind: str
    summary: str
    memory_reference: str | None = None
    status: str
    created_at: Any = None


class PreferencesUpdate(BaseModel):
    exam_date: date | None = None
    goal: str | None = Field(default=None, max_length=2000)
    preferred_language: str = Field(default="zh", max_length=16)


class PreferencesOut(BaseModel):
    session_id: str
    exam_date: date | None = None
    goal: str | None = None
    preferred_language: str = "zh"


class HealthResponse(BaseModel):
    status: str
    version: str
    seekdb: dict
    memory: dict
    embedding: dict
    llm: dict
