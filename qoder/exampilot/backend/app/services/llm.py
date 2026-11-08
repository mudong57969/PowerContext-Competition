"""LLM adapter for explanations.

With ``llm_provider=none`` (default) the backend returns an honest,
deterministic template that quotes the retrieved sources — no model call is
fabricated. With ``llm_provider=openai`` a real chat-completion request is
sent to the configured OpenAI-compatible endpoint.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from app.core.config import Settings

log = logging.getLogger("exampilot.llm")

SYSTEM_PROMPT = (
    "你是 ExamPilot 的课程助教。请基于提供的课程资料片段，用中文解释知识点。"
    "要求：先给结论再展开；不超过 400 字；只使用资料中出现的依据，不要编造内容；"
    "最后给出一个自测问题。"
)


class ExplanationError(RuntimeError):
    pass


@dataclass
class Explanation:
    text: str
    provider: str  # "template" | "openai"


class LLMProvider:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    @property
    def enabled(self) -> bool:
        return self.settings.llm_provider == "openai" and bool(
            self.settings.llm_api_key or self.settings.llm_base_url
        )

    def explain(
        self,
        knowledge_point: str,
        context_chunks: list[dict],
        question_stem: str | None = None,
    ) -> Explanation:
        if self.enabled:
            return self._explain_openai(knowledge_point, context_chunks, question_stem)
        return self._explain_template(knowledge_point, context_chunks, question_stem)

    # --- deterministic template (no LLM configured) ------------------------
    def _explain_template(
        self,
        knowledge_point: str,
        context_chunks: list[dict],
        question_stem: str | None,
    ) -> Explanation:
        parts = [
            f"## {knowledge_point}",
            "",
            "> 说明：当前未配置 LLM，以下为基于资料片段的模板讲解。",
            "",
        ]
        if question_stem:
            parts += ["**问题**：" + question_stem, ""]
        parts += ["**资料要点**：", ""]
        for i, chunk in enumerate(context_chunks[:3], 1):
            filename = chunk.get("filename") or "未知来源"
            page = chunk.get("page_number")
            source = f"{filename} 第{page}页" if page else filename
            text = str(chunk.get("text") or "")[:300]
            parts.append(f"{i}. 〔{source}〕{text}")
        parts += [
            "",
            "**学习建议**：",
            "1. 用自己的话复述上述要点，并找出它们之间的联系；",
            "2. 完成对应知识点的练习题，错题会自动进入错题本；",
            "3. 按复习计划隔日回顾，巩固记忆。",
        ]
        return Explanation(text="\n".join(parts), provider="template")

    # --- OpenAI-compatible chat completion ---------------------------------
    def _explain_openai(
        self,
        knowledge_point: str,
        context_chunks: list[dict],
        question_stem: str | None,
    ) -> Explanation:
        import httpx

        if not self.settings.llm_model:
            raise ExplanationError(
                "llm_provider is 'openai' but llm_model is not configured"
            )
        base = self.settings.llm_base_url.rstrip("/") or "https://api.openai.com/v1"
        headers = {"Content-Type": "application/json"}
        if self.settings.llm_api_key:
            headers["Authorization"] = f"Bearer {self.settings.llm_api_key}"
        sources = "\n\n".join(
            f"[{chunk.get('filename')} 第{chunk.get('page_number')}页] {chunk.get('text')}"
            for chunk in context_chunks[:3]
        )
        user_content = f"知识点：{knowledge_point}\n\n课程资料片段：\n{sources}"
        if question_stem:
            user_content += f"\n\n学生的问题：{question_stem}"
        try:
            resp = httpx.post(
                base + "/chat/completions",
                headers=headers,
                json={
                    "model": self.settings.llm_model,
                    "messages": [
                        {"role": "system", "content": SYSTEM_PROMPT},
                        {"role": "user", "content": user_content},
                    ],
                },
                timeout=60,
            )
            resp.raise_for_status()
            content = resp.json()["choices"][0]["message"]["content"]
        except Exception as exc:
            raise ExplanationError(f"LLM request failed: {exc}") from exc
        return Explanation(text=content, provider="openai")
