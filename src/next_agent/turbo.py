"""Innovation I — Cost-aware model routing.

Selects deepseek-v4-flash vs deepseek-v4-pro based on task complexity
and project context. Only switches models at session boundaries to 
preserve prefix cache.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field


@dataclass
class ModelSelection:
    """Result of model routing."""
    model: str
    reasons: list[str] = field(default_factory=list)
    estimated_cost_savings: float = 0.0


class ModelRouter:
    """Session-level model selection."""

    PRO_TASK_KEYWORDS = {
        "architecture": [
            "design", "architecture", "refactor", "migrate",
            "schema", "restructure", "redesign", "overhaul",
            "设计", "架构", "重构", "迁移", "设计模式",
        ],
        "security": [
            "security", "vulnerability", "audit", "penetration",
            "injection", "xss", "csrf", "auth", "authorization",
            "安全", "漏洞", "审计", "注入",
        ],
        "deep_analysis": [
            "root cause", "why", "investigate", "race condition",
            "deadlock", "memory leak", "performance", "bottleneck",
            "根本原因", "为什么", "调查", "性能",
        ],
    }

    PRO_PROJECT_SIGNALS = {
        "file_count": 500,
        "size_mb": 50,
        "language_count": 3,
    }

    def select(
        self,
        user_request: str,
        file_count: int = 0,
        size_mb: float = 0.0,
        language_count: int = 1,
        forced_model: str | None = None,
    ) -> ModelSelection:
        """Choose flash or pro for this session."""
        if forced_model:
            return ModelSelection(model=forced_model, reasons=["user specified"])

        reasons = []
        score = 0.0

        task_score = self._score_task(user_request)
        if task_score > 0.5:
            reasons.append(f"complex task (score={task_score:.2f})")
        score += task_score * 0.6

        project_score = self._score_project(file_count, size_mb, language_count)
        if project_score > 0.4:
            reasons.append(f"complex project ({file_count} files, {size_mb:.0f}MB)")
        score += project_score * 0.4

        if score >= 0.35 or reasons:
            model = "deepseek-v4-pro"
            if not reasons:
                reasons.append("moderate complexity")
        else:
            model = "deepseek-v4-flash"
            reasons.append("routine task — flash is sufficient")

        savings = 0.0
        if model == "deepseek-v4-flash":
            savings = 20 * 5000 * (2.19 - 0.15) / 1_000_000

        return ModelSelection(model=model, reasons=reasons, estimated_cost_savings=savings)

    def _score_task(self, text: str) -> float:
        text_lower = text.lower()
        score = 0.0

        for category, keywords in self.PRO_TASK_KEYWORDS.items():
            if category == "multi_file":
                files = set(re.findall(r'[\w./-]+\.\w{1,6}', text))
                if len(files) >= 5:
                    score += 0.3
                elif len(files) >= 3:
                    score += 0.15
            else:
                hits = sum(1 for kw in keywords
                          if kw.lower() in text_lower or kw in text)
                if hits > 0:
                    score += min(hits * 0.30, 0.7)

        if len(text.split()) > 80:
            score += 0.15
        if "?" in text and len(text) > 100:
            score += 0.1

        return min(score, 1.0)

    @staticmethod
    def _score_project(file_count: int, size_mb: float, languages: int) -> float:
        score = 0.0
        if file_count > 500:
            score += 0.4
        elif file_count > 200:
            score += 0.2
        if size_mb > 50:
            score += 0.3
        elif size_mb > 20:
            score += 0.15
        if languages >= 3:
            score += 0.3
        elif languages >= 2:
            score += 0.15
        return min(score, 1.0)
