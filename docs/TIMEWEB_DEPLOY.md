# Timeweb shared: опубликованный кабинет с регистрацией

11.10.2026: HTTPS и mod_wsgi Python 3.10.12 проверены; выполнены установка, smoke, откат и повторная установка с сохранением private. [Актуальные пути, проверки, ограничения и восстановление](HANDOFF_DEPLOY_2026-10-11.md).

> Ниже сохранён план до размещения; его отметки «не выполнено» являются историческими.

# Timeweb shared: размещение пилота (подготовка кода выполнена, деплой не выполнялся)

11.10.2026 · WSGI-адаптация реализована и покрыта синтетическими тестами.
Деплоя, покупок и изменений аккаунта/действующего сайта не было.

## Подтверждённые факты окружения

- Тариф Year: 2 сайта, 15 GB, 2 MySQL-БД; один сайт занят.
- SSH (read-only): Python 3.10.12, SQLite 3.37.2; панель показывает 3.4 —
  фактический интерпретатор mod_wsgi неизвестен (первый staging-шаг).
- Официальный способ: Apache + mod_wsgi, callable `application`, `.htaccess`
  `Options +ExecCGI` / `AddHandler wsgi-script` / rewrite на entry-файл;
  `WSGI*`-директивы недоступны; предупреждение о задержках SQLite 3.10+.
  https://timeweb.com/ru/docs/virtualnyj-hosting/prilozheniya-i-frejmvorki/django/

## Реализовано

- `pilot/serve_request` — вся маршрутизация вынесена из `Handler` в общий
  транспортно-нейтральный слой (`pilot/server.py`); локальный
  `python -m pilot.server` работает как раньше.
- `pilot/wsgi.py` — WSGI-вход: тот же роутинг и бизнес-логика; fail closed
  без `PILOT_HOST`/`PILOT_DB`/`PILOT_USERS_FILE`; обязателен
  `wsgi.url_scheme=https` и точный authority (hostname или `host:443`,
  произвольный порт отклоняется); `Origin: https://<host>` для мутаций;
  cookie `Secure; HttpOnly; SameSite=Strict`; `X-Forwarded-*` игнорируются;
  пути БД/сессий/аккаунтов резолвятся (expanduser+symlinks) и обязаны лежать
  вне любого `public_html`; `password_hash` валидируется по pbkdf2-формату.
- `pilot/session_store.py` — `SqliteSessions`: сессии в ОТДЕЛЬНОМ файле
  `pilot-sessions.sqlite3`, общие для всех процессов mod_wsgi, с expiry и
  logout; схема основной БД не меняется.
- Аккаунты: `PILOT_USERS_FILE` с pbkdf2-хэшами (генератор
  `deploy/timeweb/make_users.py`); демо-аккаунты в hosted-режиме
  отсутствуют по построению. `modules: "all"|[ids]` задаёт назначение
  преподавателя.
- `deploy/timeweb/app/` — entry `app.py` (пути заполняются при деплое) +
  `.htaccess` по официальной доке; `wsgi-config.example.json`.
- `deploy/timeweb/PACKAGE.txt` — явный allowlist офлайн-пакета.
- Диагностика остаётся отдельной: `deploy/timeweb/wsgi.py` + `.htaccess`
  (только версии Python/SQLite, не портал).

## Раскладка на хостинге

```
~/onco-pilot/              # код по PACKAGE.txt (вне public_html)
~/onco-pilot-private/      # 700: pilot.sqlite3, pilot-sessions.sqlite3,
                           #      users.json, wsgi-config.json, backups/, logs/
<staging web dir>/         # только app.py + .htaccess
```

Staging — второй сайт тарифа или отдельный поддомен, НЕ каталог
действующего сайта. Основная БД на staging создаётся пустой приложением;
локальную/приватную БД на хостинг не копировать (только синтетический seed).

## Проверки (выполнены / остаются)

Выполнено синтетически (`pilot/test_wsgi_hosted.py`): login с Secure-cookie,
cross-worker сессии через общий session DB, logout, expiry, отклонение
чужого Host/Origin и отсутствующего `X-Pilot-Request`, forwarded-заголовки
не влияют, статика и API, персистентный прогресс через основную БД,
отсутствие демо-аккаунтов, fail closed без env. Команды:

```bash
python3 -m unittest discover -s pilot -p 'test_*.py' -q   # весь пакет
python3 -m py_compile pilot/wsgi.py pilot/session_store.py deploy/timeweb/app/app.py deploy/timeweb/make_users.py
```

Остаются на staging (после выкладки пакета): фактический интерпретатор
mod_wsgi (диагностика), HTTPS-сертификат на staging-домене, latency SQLite
под реальной нагрузкой, браузерная приёмка.

## Бэкап и откат

- Бэкап: `sqlite3 pilot.sqlite3 ".backup 'backups/pilot-<ts>.sqlite3'"`,
  `PRAGMA integrity_check` + сверка sha256; данные не выводить.
- Откат кода: заменить каталог `~/onco-pilot` прежней версией — БД и
  `pilot-sessions.sqlite3` не перезаписывать; перед откатом бэкап и
  сверка совместимости схемы. Откат staging не затрагивает действующий сайт.
- `tilda/pilot/T123-pilot-entry.html` остаётся выключенным до проверенного
  HTTPS-адреса staging.

## Ограничения

- WSGI-режим проверен только синтетическими вызовами `application()`
  без настоящего mod_wsgi/Apache — реальное поведение ExecCGI не проверено.
- Баннер `index.html` «демонстрационные аккаунты» — текст локальной копии;
  для hosted при желании отдельная правка шаблона.
- Реальный ростер, HTTPS и деплой — шаги координатора после приёмки.
