# Neftecode Integration API

Единая точка сборки хакатонной системы. API вызывает реальный QualityAgent H+C,
оборачивает результаты компонентов в `ComponentResult` и передаёт собранный
`OrchestratorInput` в Orchestrator.

Reliability подключена локально через модель `reliability_agent`. Optimization
подключён локально через пакет `neftecode-optimization`: он генерирует кандидатов,
проверяет их Safety и передаёт сценарии вместе с ranking в Orchestrator.

Контур намеренно остаётся fail-closed для операторских воздействий: `T6/F9/P13`
сопоставлены, но их диапазоны пока имеют статус `EXPERIMENTAL_MODEL`, а
ReliabilityAgent выдаёт индекс режимного риска, но оценка кандидата остаётся
статическим прокси, а подтверждённых границ управлений в его policy нет.
QualityAgent уже формирует модельный
товарный продукт через редактируемый линейный блендинг.

## Запуск

Из корня workspace:

```powershell
uv sync --project integration --extra dev
uv run --project integration neftecode-api --host 127.0.0.1 --port 8000
```

После первого `uv sync` API также запускается из корня командой:

```powershell
.\run-api.ps1
```

Swagger UI: `http://127.0.0.1:8000/docs`.

Авторизация намеренно отключена. Разрешённые frontend origins заданы в
`integration/config.yaml`.

Demo API пишет shadow-события в `integration/runtime/quality_shadow.jsonl`, а не
в основной журнал `Quality_neftecode/runtime/shadow.jsonl`. Это защищает будущий
holdout от тестовых и демонстрационных событий.

## API

- `POST /api/v1/evaluate` — полный текущий расчёт;
- `POST /api/v1/decide` — передать уже собранные результаты реальных блоков;
- `GET /api/v1/health` — версии моделей и режимы адаптеров;
- `GET /api/v1/runs/{run_id}` — результат выполненного расчёта;
- `POST /api/v1/shadow/lims` — добавить фактическую пробу ЛИМС;
- `GET /api/v1/shadow/status` — shadow-метрики и readiness gates.
- `GET /api/v1/scenarios` — список редактируемых what-if сценариев;
- `GET /api/v1/scenarios/{id}` — готовый запрос, который можно изменить;
- `POST /api/v1/scenarios/{id}/evaluate` — выполнить сценарий.
- `GET /api/v1/examples` и `GET /api/v1/examples/{id}` — проверяемые примеры с явным происхождением полей;
- `POST /api/v1/examples/{id}/evaluate` — прогнать пример через текущие модели.
- `POST /api/v1/data-upload/evaluate` — обработать пользовательские тестовые файлы и сразу выполнить расчёт.

### Контракт «загрузка → обработка → расчёт»

`POST /api/v1/data-upload/evaluate` принимает `multipart/form-data` с обязательными
полями `avt_tags` (CSV), `hydro_tags` (CSV), `lims_xlsx` (XLSX) и `tags_xlsx`
(XLSX), а также необязательным `pak_xlsx` (XLSX). Общий лимит — 600 МБ.

Маршрут вызывает `neftecode_processing.run_processing`: именно его итоговая
таблица `final` является границей контрактов. Последняя временная точка становится
`process_state`, до 36 предыдущих — `history`; телеметрия берётся из колонок
`avt_*` / `hyd_*`, а качество — из канонических `*_value` полей. Запрос помечается
`HISTORICAL`, поэтому отсутствующие или ещё не опубликованные данные приводят к
защитному отказу, а не к выдуманной рекомендации. Ответ имеет обычную форму
`EvaluationResponse` и дополнительный объект `processing` со сводкой строк,
временного диапазона и экспортированных срезов. Исходные файлы и временные
артефакты удаляются сразу после расчёта; сам результат доступен по `run_id`.

`POST /evaluate` может принять до 1 000 исторических `ProcessState`. Это позволяет
передать необходимое шестичасовое окно при первом запросе после запуска.
Точки истории позже текущего `process_state.timestamp` отклоняются с HTTP 422.
Лабораторные значения с `source=lims` удаляются из runtime-входа до
`sample_timestamp + 4h`; при отсутствии временных метаданных действует fail-closed.
Поле `input_source` принимает `SYNTHETIC`, `HISTORICAL` или `LIVE`; безопасное
значение по умолчанию — `SYNTHETIC`. Источник не определяется по значениям датчиков.

Для Reliability передавайте телеметрию с префиксами `avt_` и `hyd_` и при наличии
метаданные сигналов в `data_quality` (`flag_missing`, `flag_stale`, `flag_outlier`,
`age_min`, `flatline_min`). Общие списки `missing`, `stale`, `outlier` также
преобразуются для известных тегов. Недостающие признаки дают `UNKNOWN` и
`risk_score: null`; итоговое решение при этом остаётся fail-closed. Версия модели,
факторы риска и оценки узлов доступны в `assembled_input.current_reliability.data`;
статические баллы кандидатов и признаки поддержки управлений — в
`assembled_input.scenarios`.
Список `flatline` без длительности не превращается в выдуманное число минут:
для соответствующего тега адаптер понижает доверие до `LOW` и добавляет предупреждение.
Путь к policy задаётся `reliability_policy` в `integration/config.yaml`.

Детерминированный запрос для проверки полного `KEEP`-маршрута создаётся командой:

```powershell
uv run --project integration python integration/scripts/build_demo_request.py
```

Исторический контрольный случай за `2026-05-15 04:00–10:00` собирается из
исходных CSV АВТ и 24-2000 и выгрузки ПАК:

```powershell
.\.venv\Scripts\python.exe -X utf8 -m integration.scripts.build_historical_request
Invoke-RestMethod -Uri http://127.0.0.1:8000/api/v1/evaluate -Method Post -ContentType 'application/json; charset=utf-8' -InFile integration/examples/historical_20260515_1000.json
```

Готовый запрос лежит в `integration/examples/historical_20260515_1000.json`,
происхождение данных и контрольная проба — в соседнем файле с суффиксом
`_evidence.json`. В запросе 37 последовательных десятиминутных точек, реальные
значения ПАК по сере и плотности. Проба ЛИМС в 10:00 (11,9 мг/кг, test split)
используется только для последующей проверки и не передаётся модели. В исходных
материалах нет подтверждённой рецептуры товарного смешения, поэтому в запросе
нет выдуманных долей компонентов. Текущая конфигурация API в таком случае
возвращает `REFUSE` с `BLENDING_PLAN_MISSING`; Reliability выдаёт числовую
оценку. Это воспроизводимая проверка данных и защитного отказа, а не пример
промышленной рекомендации. Времена исходных файлов не содержат часового пояса;
при сборке им назначается UTC только для формата API.

Для полного расчёта на том же типе реальных измерений создан отдельный
`integration/examples/illustrative_blend_20260515_1200.json` за 12:00. Доли 80/20,
свойства второго компонента и параметры присадки взяты из учебного
`integration/runtime/demo_request.json`; запрос помечен `SYNTHETIC`, а не
`HISTORICAL`. На текущей версии API он выдаёт `KEEP` и числовые оценки качества
и надёжности. Пересобрать пример можно командой:

```powershell
.\.venv\Scripts\python.exe -X utf8 -m integration.scripts.build_illustrative_request
```

Источник и ограничения каждого поля описаны в соседнем `_evidence.json` и в
`neftecode_optimizer/docs/recipe_and_controls_audit.md`. Этот результат
показывает работоспособность программного контура, а не заводскую рецептуру.

`POST /decide` принимает существующий строгий `OrchestratorInput`. Это переходный
интеграционный путь для блоков коллег: они могут отправлять согласованные результаты
сразу, не ожидая появления локального Python-адаптера.

Сценарии лежат в `integration/scenarios/catalog.yaml`: рост серы сырья,
летнее/зимнее ДТ, `Q21=307`, устаревший ПАК, пуск/останов, недостаток данных,
невозможный паспорт и выбор между блендингом и дорогой присадкой. Значения и
рецептуры намеренно редактируемы и не выдаются за промышленный регламент.
