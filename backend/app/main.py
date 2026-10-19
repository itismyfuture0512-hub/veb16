"""Backend приложения «Менеджер задач» (вариант 16).

REST API поверх PostgreSQL. Для расчёта приоритета и сроков
обращается к отдельному микросервису web-service (priority-service).
"""

import logging
import os
import time
from contextlib import asynccontextmanager, contextmanager
from typing import Optional

import httpx
import psycopg2
import psycopg2.extras
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger("todo-backend")

DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://todo_user:todo_pass@db:5432/todo")
WEB_SERVICE_URL = os.getenv("WEB_SERVICE_URL", "http://web-service:8000").rstrip("/")
WEB_SERVICE_TIMEOUT = float(os.getenv("WEB_SERVICE_TIMEOUT", "10"))

TASK_COLUMNS = (
    "id, title, description, importance, urgency, estimated_hours, "
    "status, priority_score, priority_label, due_date, created_at, updated_at"
)
OPEN_STATUSES = ("new", "in_progress")


# --------------------------------------------------------------------------
# Работа с БД
# --------------------------------------------------------------------------
@contextmanager
def db_conn():
    conn = psycopg2.connect(DATABASE_URL)
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def wait_for_db(attempts: int = 30, delay: float = 2.0) -> None:
    last_error: Optional[Exception] = None
    for attempt in range(1, attempts + 1):
        try:
            with db_conn() as conn:
                with conn.cursor() as cur:
                    cur.execute("SELECT 1")
            log.info("Подключение к PostgreSQL установлено")
            return
        except psycopg2.Error as exc:
            last_error = exc
            log.warning("PostgreSQL ещё не готов (%s/%s): %s", attempt, attempts, exc)
            time.sleep(delay)
    raise RuntimeError(f"Не удалось подключиться к PostgreSQL: {last_error}")


def serialize_task(row: dict) -> dict:
    task = dict(row)
    if task.get("priority_score") is not None:
        task["priority_score"] = float(task["priority_score"])
    if task.get("estimated_hours") is not None:
        task["estimated_hours"] = float(task["estimated_hours"])
    for key in ("due_date", "created_at", "updated_at"):
        value = task.get(key)
        if value is not None:
            task[key] = value.isoformat()
    return task


def fetch_tasks(conn, order: str = "priority") -> list[dict]:
    query = f"SELECT {TASK_COLUMNS} FROM tasks"
    if order == "priority":
        query += " ORDER BY priority_score DESC NULLS LAST, urgency DESC, importance DESC, id ASC"
    else:
        query += " ORDER BY id ASC"
    with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute(query)
        return [serialize_task(row) for row in cur.fetchall()]


# --------------------------------------------------------------------------
# Приложение
# --------------------------------------------------------------------------
@asynccontextmanager
async def lifespan(_: FastAPI):
    wait_for_db()
    yield


app = FastAPI(
    title="To-Do Backend API",
    description="Вариант 16 — менеджер задач: приоритезация и расчёт сроков",
    version="1.0.0",
    lifespan=lifespan,
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# --------------------------------------------------------------------------
# Схемы запросов
# --------------------------------------------------------------------------
class TaskCreate(BaseModel):
    title: str = Field(..., min_length=1, max_length=200)
    description: Optional[str] = Field(default=None, max_length=2000)
    importance: int = Field(default=3, ge=1, le=5)
    urgency: int = Field(default=3, ge=1, le=5)
    estimated_hours: float = Field(default=2.0, gt=0, le=1000)
    status: str = Field(default="new", pattern="^(new|in_progress|done|cancelled)$")


class StatusUpdate(BaseModel):
    status: str = Field(..., pattern="^(new|in_progress|done|cancelled)$")


# --------------------------------------------------------------------------
# Эндпоинты
# --------------------------------------------------------------------------
@app.get("/api/health")
def health() -> dict:
    db_ok = True
    try:
        with db_conn() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT 1")
    except psycopg2.Error:
        db_ok = False
    return {"status": "ok" if db_ok else "degraded", "database": db_ok, "service": "todo-backend"}


@app.get("/api/tasks")
def list_tasks() -> dict:
    """Кнопка 1: выборка задач из внутренней БД."""
    with db_conn() as conn:
        tasks = fetch_tasks(conn)
    return {"count": len(tasks), "tasks": tasks}


@app.post("/api/tasks", status_code=201)
def create_task(payload: TaskCreate) -> dict:
    with db_conn() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(
                f"""
                INSERT INTO tasks (title, description, importance, urgency, estimated_hours, status)
                VALUES (%s, %s, %s, %s, %s, %s)
                RETURNING {TASK_COLUMNS}
                """,
                (
                    payload.title,
                    payload.description,
                    payload.importance,
                    payload.urgency,
                    payload.estimated_hours,
                    payload.status,
                ),
            )
            row = cur.fetchone()
    return serialize_task(row)


@app.patch("/api/tasks/{task_id}/status")
def update_status(task_id: int, payload: StatusUpdate) -> dict:
    with db_conn() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(
                f"""
                UPDATE tasks SET status = %s, updated_at = now()
                WHERE id = %s
                RETURNING {TASK_COLUMNS}
                """,
                (payload.status, task_id),
            )
            row = cur.fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail=f"Задача {task_id} не найдена")
    return serialize_task(row)


@app.delete("/api/tasks/{task_id}", status_code=204)
def delete_task(task_id: int) -> None:
    with db_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM tasks WHERE id = %s", (task_id,))
            if cur.rowcount == 0:
                raise HTTPException(status_code=404, detail=f"Задача {task_id} не найдена")
    return None


@app.post("/api/tasks/prioritize")
def prioritize_tasks() -> dict:
    """Кнопка 2: обращение к web-service, расчёт приоритетов и сроков.

    Результаты расчёта сохраняются в БД (priority_score, priority_label, due_date).
    """
    with db_conn() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(
                f"""
                SELECT {TASK_COLUMNS} FROM tasks
                WHERE status IN ('new', 'in_progress')
                ORDER BY id ASC
                """
            )
            open_tasks = [dict(row) for row in cur.fetchall()]

        if not open_tasks:
            return {
                "updated": 0,
                "summary": None,
                "count": 0,
                "tasks": fetch_tasks(conn),
            }

        payload = {
            "tasks": [
                {
                    "id": task["id"],
                    "title": task["title"],
                    "importance": task["importance"],
                    "urgency": task["urgency"],
                    "estimated_hours": float(task["estimated_hours"]),
                    "status": task["status"],
                    "due_date": task["due_date"].isoformat() if task["due_date"] else None,
                }
                for task in open_tasks
            ]
        }

        try:
            response = httpx.post(
                f"{WEB_SERVICE_URL}/api/priority",
                json=payload,
                timeout=WEB_SERVICE_TIMEOUT,
            )
            response.raise_for_status()
            result = response.json()
        except httpx.HTTPError as exc:
            log.error("Ошибка обращения к web-service: %s", exc)
            raise HTTPException(status_code=502, detail=f"Web-service недоступен: {exc}") from exc

        computed = result.get("tasks", [])
        with conn.cursor() as cur:
            for item in computed:
                cur.execute(
                    """
                    UPDATE tasks
                       SET priority_score = %s,
                           priority_label = %s,
                           due_date       = %s,
                           updated_at     = now()
                     WHERE id = %s
                    """,
                    (
                        item["priority_score"],
                        item["priority_label"],
                        item["due_date"],
                        item["id"],
                    ),
                )

        tasks = fetch_tasks(conn)

    return {
        "updated": len(computed),
        "summary": result.get("summary"),
        "service": result.get("service"),
        "count": len(tasks),
        "tasks": tasks,
    }