-- Инициализация схемы БД приложения «Менеджер задач» (вариант 16)
-- Таблица: список задач и статусы их выполнения

CREATE TABLE IF NOT EXISTS tasks (
    id              SERIAL PRIMARY KEY,
    title           VARCHAR(200)  NOT NULL,
    description     TEXT,
    importance      SMALLINT      NOT NULL DEFAULT 3 CHECK (importance BETWEEN 1 AND 5),
    urgency         SMALLINT      NOT NULL DEFAULT 3 CHECK (urgency    BETWEEN 1 AND 5),
    estimated_hours NUMERIC(6,1)  NOT NULL DEFAULT 2.0 CHECK (estimated_hours > 0),
    status          VARCHAR(20)   NOT NULL DEFAULT 'new'
                    CHECK (status IN ('new', 'in_progress', 'done', 'cancelled')),
    -- Результаты работы web-service (priority-service)
    priority_score  NUMERIC(6,2),
    priority_label  VARCHAR(20),
    due_date        DATE,
    created_at      TIMESTAMPTZ   NOT NULL DEFAULT now(),
    updated_at      TIMESTAMPTZ   NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_tasks_status   ON tasks (status);
CREATE INDEX IF NOT EXISTS idx_tasks_priority ON tasks (priority_score DESC NULLS LAST);

-- Первичные данные
INSERT INTO tasks (title, description, importance, urgency, estimated_hours, status, due_date) VALUES
    ('Сдать лабораторную по Docker Compose', 'Собрать 4 контейнера и запушить репозиторий', 5, 5, 6.0,  'in_progress', CURRENT_DATE + 2),
    ('Подготовиться к экзамену по БД',       'Повторить нормальные формы и транзакции',      5, 3, 12.0, 'new',         CURRENT_DATE + 10),
    ('Обновить резюме',                      'Добавить проект с микросервисами',             3, 2, 2.0,  'new',         NULL),
    ('Купить продукты',                      'Молоко, хлеб, овощи',                          2, 4, 1.0,  'new',         CURRENT_DATE + 1),
    ('Оплатить интернет',                    'Успеть до конца месяца',                       4, 5, 0.5,  'new',         CURRENT_DATE + 3),
    ('Прочитать главу по FastAPI',           NULL,                                           3, 1, 3.0,  'done',        CURRENT_DATE - 5);