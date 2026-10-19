const API = '/api';

const STATUS_LABELS = {
  new: 'Новая',
  in_progress: 'В работе',
  done: 'Выполнена',
  cancelled: 'Отменена',
};

const PRIORITY_LABELS = {
  critical: 'Критический',
  high: 'Высокий',
  medium: 'Средний',
  low: 'Низкий',
};

const $ = (id) => document.getElementById(id);

function setStatus(text, kind = '') {
  const node = $('status');
  node.textContent = text;
  node.className = 'status' + (kind ? ' ' + kind : '');
}

function escapeHtml(value) {
  return String(value ?? '')
    .replaceAll('&', '&amp;')
    .replaceAll('<', '&lt;')
    .replaceAll('>', '&gt;')
    .replaceAll('"', '&quot;')
    .replaceAll("'", '&#039;');
}

async function api(path, options = {}) {
  const response = await fetch(API + path, {
    headers: { 'Content-Type': 'application/json' },
    ...options,
  });

  if (!response.ok) {
    let detail = `HTTP ${response.status}`;
    try {
      const data = await response.json();
      if (data && data.detail) detail = data.detail;
    } catch (_) { /* тело не JSON */ }
    throw new Error(detail);
  }

  if (response.status === 204) return null;
  return response.json();
}

/* ----------------------------- Отрисовка ----------------------------- */

function priorityBadge(task) {
  if (task.priority_score === null || task.priority_score === undefined) {
    return '<span class="pill pill-muted">не рассчитан</span>';
  }
  const label = PRIORITY_LABELS[task.priority_label] || task.priority_label || '';
  const score = Number(task.priority_score).toFixed(1);
  return `<span class="pill pill-${task.priority_label}">${label} · ${score}</span>`;
}

function renderTasks(tasks) {
  const body = $('tasks-body');

  if (!tasks || !tasks.length) {
    body.innerHTML = '<tr><td colspan="8" class="empty">Задач пока нет</td></tr>';
    return;
  }

  body.innerHTML = tasks.map((task) => `
    <tr>
      <td>${task.id}</td>
      <td>
        <div class="task-title">${escapeHtml(task.title)}</div>
        ${task.description ? `<div class="task-desc">${escapeHtml(task.description)}</div>` : ''}
      </td>
      <td>${task.importance} / ${task.urgency}</td>
      <td>${Number(task.estimated_hours).toFixed(1)}</td>
      <td>${priorityBadge(task)}</td>
      <td>${task.due_date || '—'}</td>
      <td>
        <select class="status-select" data-id="${task.id}">
          ${Object.entries(STATUS_LABELS).map(([value, label]) =>
            `<option value="${value}" ${task.status === value ? 'selected' : ''}>${label}</option>`
          ).join('')}
        </select>
      </td>
      <td><button class="btn btn-danger btn-sm" data-delete="${task.id}" title="Удалить">✕</button></td>
    </tr>
  `).join('');
}

function renderSummary(summary, updated) {
  if (!summary) return;
  $('summary-panel').hidden = false;

  const cards = [
    ['Обработано задач', updated],
    ['Критический', summary.critical],
    ['Высокий', summary.high],
    ['Средний', summary.medium],
    ['Низкий', summary.low],
    ['Суммарно часов', Number(summary.total_hours).toFixed(1)],
    ['Рабочих дней плана', summary.total_effort_days],
    ['Средний балл', Number(summary.avg_score).toFixed(1)],
  ];

  $('summary-cards').innerHTML = cards.map(([label, value]) => `
    <div class="card">
      <span class="card-value">${value}</span>
      <span class="card-label">${label}</span>
    </div>
  `).join('');
}

/* --------------------------- Действия (кнопки) --------------------------- */

// Кнопка 1: данные из внутренней БД через backend
async function loadTasks() {
  setStatus('Загрузка задач из БД…', 'busy');
  try {
    const data = await api('/tasks');
    renderTasks(data.tasks);
    setStatus(`Загружено задач: ${data.count}`, 'ok');
  } catch (error) {
    setStatus('Ошибка: ' + error.message, 'error');
  }
}

// Кнопка 2: обращение к web-service через backend + сохранение результата в БД
async function prioritizeTasks() {
  setStatus('Обращение к web-service…', 'busy');
  try {
    const data = await api('/tasks/prioritize', { method: 'POST' });
    renderTasks(data.tasks);
    renderSummary(data.summary, data.updated);
    setStatus(`Web-service обработал задач: ${data.updated}`, 'ok');
  } catch (error) {
    setStatus('Ошибка: ' + error.message, 'error');
  }
}

async function createTask(event) {
  event.preventDefault();
  const payload = {
    title: $('f-title').value.trim(),
    description: $('f-desc').value.trim() || null,
    importance: Number($('f-importance').value),
    urgency: Number($('f-urgency').value),
    estimated_hours: Number($('f-hours').value),
  };

  try {
    await api('/tasks', { method: 'POST', body: JSON.stringify(payload) });
    $('task-form').reset();
    $('f-importance').value = 3;
    $('f-urgency').value = 3;
    $('f-hours').value = 2;
    setStatus('Задача добавлена', 'ok');
    await loadTasks();
  } catch (error) {
    setStatus('Ошибка: ' + error.message, 'error');
  }
}

async function changeStatus(id, status) {
  try {
    await api(`/tasks/${id}/status`, {
      method: 'PATCH',
      body: JSON.stringify({ status }),
    });
    setStatus(`Задача ${id}: статус обновлён`, 'ok');
  } catch (error) {
    setStatus('Ошибка: ' + error.message, 'error');
  }
}

async function removeTask(id) {
  try {
    await api(`/tasks/${id}`, { method: 'DELETE' });
    setStatus(`Задача ${id} удалена`, 'ok');
    await loadTasks();
  } catch (error) {
    setStatus('Ошибка: ' + error.message, 'error');
  }
}

/* ------------------------------ Инициализация ------------------------------ */

document.addEventListener('DOMContentLoaded', () => {
  $('btn-load').addEventListener('click', loadTasks);
  $('btn-prioritize').addEventListener('click', prioritizeTasks);
  $('task-form').addEventListener('submit', createTask);

  $('tasks-body').addEventListener('change', (event) => {
    const select = event.target.closest('.status-select');
    if (select) changeStatus(select.dataset.id, select.value);
  });

  $('tasks-body').addEventListener('click', (event) => {
    const button = event.target.closest('[data-delete]');
    if (button) removeTask(button.dataset.delete);
  });

  loadTasks();
});