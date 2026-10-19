"""Web-service варианта 16: сервис приоритезации и расчёта сроков задач.

Отдельный микросервис, не имеющий собственной БД.
Принимает список задач и возвращает для каждой:
  * priority_score  — балл приоритета (0..100)
  * priority_label  — категория (critical / high / medium / low)
  * plan_start / plan_finish — рекомендуемое окно выполнения
  * due_date        — рекомендуемый срок сдачи
  * risk            — риск срыва относительно текущего срока пользователя
"""

import math
import os
from datetime import date, timedelta
from typing import List, Optional

from fastapi import FastAPI
from pydantic import BaseModel, Field

SERVICE_NAME = os.getenv("SERVICE_NAME", "priority-service")
WORKDAY_HOURS = float(os.getenv("WORKDAY_HOURS", "8"))
HORIZON_DAYS = int(os.getenv("HORIZON_DAYS", "30"))

app = FastAPI(
    title="Priority & Deadline Service",
    description="Вариант 16 — приоритезация и расчёт сроков задач",
    version="1.0.0",
)


# --------------------------------------------------------------------------
# Модели
# --------------------------------------------------------------------------
class TaskIn(BaseModel):
    id: int
    title: str = ""
    importance: int = Field(default=3, ge=1, le=5)
    urgency: int = Field(default=3, ge=1, le=5)
    estimated_hours: float = Field(default=2.0, gt=0)
    status: str = "new"
    due_date: Optional[str] = None


class BatchRequest(BaseModel):
    tasks: List[TaskIn] = Field(default_factory=list)
    today: Optional[str] = None  # для тестируемости


# --------------------------------------------------------------------------
# Алгоритмы
# --------------------------------------------------------------------------
def _clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def priority_score(importance: int, urgency: int, hours: float) -> float:
    """Формула: 40% важность + 45% срочность + 15% «лёгкость» задачи."""
    ease = 1.0 - min(max(hours, 0.25), 40.0) / 40.0
    score = (
        40.0 * _clamp(importance, 1, 5) / 5.0
        + 45.0 * _clamp(urgency, 1, 5) / 5.0
        + 15.0 * ease
    )
    return round(score, 2)


def priority_label(score: float) -> str:
    if score >= 80:
        return "critical"
    if score >= 60:
        return "high"
    if score >= 40:
        return "medium"
    return "low"


def effort_days(hours: float) -> int:
    return max(1, math.ceil(hours / WORKDAY_HOURS))


# --------------------------------------------------------------------------
# Эндпоинты
# --------------------------------------------------------------------------
@app.get("/health")
def health() -> dict:
    return {"status": "ok", "service": SERVICE_NAME}


@app.get("/")
def root() -> dict:
    return {
        "service": SERVICE_NAME,
        "variant": 16,
        "formula": "score = 40*importance/5 + 45*urgency/5 + 15*(1 - min(hours,40)/40)",
        "endpoints": ["POST /api/priority", "GET /health"],
    }


@app.post("/api/priority")
def compute_priorities(request: BatchRequest) -> dict:
    today = date.fromisoformat(request.today) if request.today else date.today()

    scored: list[dict] = []
    for task in request.tasks:
        score = priority_score(task.importance, task.urgency, task.estimated_hours)
        scored.append(
            {
                "id": task.id,
                "title": task.title,
                "priority_score": score,
                "priority_label": priority_label(score),
                "effort_days": effort_days(task.estimated_hours),
                "estimated_hours": float(task.estimated_hours),
                "status": task.status,
                "current_due_date": task.due_date,
            }
        )

    # Сортировка: сначала самые приоритетные, при равенстве — по id
    scored.sort(key=lambda item: (-item["priority_score"], item["id"]))

    summary = {
        "total": len(scored),
        "critical": 0,
        "high": 0,
        "medium": 0,
        "low": 0,
        "total_hours": 0.0,
        "total_effort_days": 0,
        "avg_score": 0.0,
    }

    cursor = today
    results: list[dict] = []

    for index, item in enumerate(scored, start=1):
        plan_start = cursor
        plan_finish = plan_start + timedelta(days=item["effort_days"])
        cursor = plan_finish

        risk = "low"
        if item["current_due_date"]:
            try:
                current_due = date.fromisoformat(str(item["current_due_date"]))
                if current_due < plan_finish:
                    risk = "high"
                elif current_due == plan_finish:
                    risk = "medium"
            except ValueError:
                pass

        summary[item["priority_label"]] += 1
        summary["total_hours"] += item["estimated_hours"]
        summary["total_effort_days"] += item["effort_days"]

        results.append(
            {
                "id": item["id"],
                "title": item["title"],
                "priority_score": item["priority_score"],
                "priority_label": item["priority_label"],
                "schedule_order": index,
                "plan_start": plan_start.isoformat(),
                "plan_finish": plan_finish.isoformat(),
                "due_date": plan_finish.isoformat(),
                "days_left": (plan_finish - today).days,
                "effort_days": item["effort_days"],
                "risk": risk,
            }
        )

    if results:
        summary["avg_score"] = round(
            sum(item["priority_score"] for item in results) / len(results), 2
        )
    summary["total_hours"] = round(summary["total_hours"], 1)

    return {
        "service": SERVICE_NAME,
        "generated_at": today.isoformat(),
        "workday_hours": WORKDAY_HOURS,
        "summary": summary,
        "tasks": results,
    }