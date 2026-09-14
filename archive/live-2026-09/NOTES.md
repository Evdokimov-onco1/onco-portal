# Живая сборка исполнительницы (снято 14.09.2026)

Источник: страницы `/ordinatura-year-1` (page 229315509) и `/ordinatura-year-2` (page 229773709),
блок T123 (`data-record-type="131"`, rec3673463101 на 1-м году, rec3679525501 на 2-м).
Tilda API содержимое Members-страниц не отдаёт (`html: ""`), снимок сделан из браузера
под учётной записью пользователя. Инлайн-скрипт извлечён фрагментами, полный текст
не сохранён; ниже зафиксировано всё, что отличает его от `orp-engine.repo.js` из GitHub.

## Состав блока
- `<style>` 4996 символов, селекторы внутри `#oncoResidencyPortal`, те же классы `orp-*`,
  что в пакете руководителя, плюс `.orp-card-selected`, `.orp-module-inline` (карточка модуля
  раскрывается инлайн в сетке, `grid-column: 1 / -1`).
- Разметка: hero, три кнопки навигации (modules / library / tests), панели `modules`, `library`, `tests`.
  Счётчики `#orpModuleCount`, `#orpTestCount`. Панелей VP / OSCE / TB нет.
- `<script>` 12759 символов, IIFE, ES5.

## Отличия скрипта от репозитория llcbrein-pro/onco-portal
- `var YEAR = '1'` (на 2-м году `'2'`): модули фильтруются по `pedagogical_year`,
  вопросы по `question.year`. Один и тот же код в двух блоках, отличие в одной константе.
- `DATA_URL = https://cdn.jsdelivr.net/gh/llcbrein-pro/onco-portal@main/ordinatura/orp-data.json`.
- `RESULTS_URL` = Google Apps Script (`script.google.com/macros/s/AKfycby…/exec`).
  После завершения теста `sendResult()` делает `fetch(POST, mode: 'no-cors', Content-Type: text/plain)`
  с JSON: `completed_at, name, email, year, module, score, total, percent, page`.
  На экране: «Тест завершён. Результат отправлен преподавателю.»
- `getMember()` читает профиль из `localStorage['tilda_members_profile' + projectId]`
  (поля `name`, `login`/`email`).
- `openModule(id, button)`: карточка модуля вставляется инлайн после выбранной карточки
  (`.orp-module-inline`), есть кнопка «Закрыть модуль». Содержимое: лекция, задачи,
  вопросы (до 8), самоконтроль с кнопкой теста. Блоков интеграций и инструментов нет.
- `?module=` не обрабатывается.
- Библиотека и тест идентичны репозиторному движку.

## Что из этого переносим в наш движок
- Отправка результатов (нужен свой Apps Script или другой приёмник; текущий URL принадлежит исполнительнице).
- Чтение профиля Members из localStorage.
- Инлайн-раскрытие карточки в сетке (удобнее, чем отдельный runner под сеткой).
- Фильтр по году через конфигурацию блока, а не через копию скрипта.
