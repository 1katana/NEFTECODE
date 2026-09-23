# Нефтекод 2.0 — единая хакатонная система

Workspace объединяет пять устанавливаемых пакетов:

- `Quality_neftecode` — реальный QualityAgent H+C в shadow-режиме;
- `neftecode_optimizer` — генерация кандидатов, Safety и ранжирование;
- `reliability_agent` — локальная модель режимного риска АВТ и 24-2000;
- `orchestrator` — детерминированный fail-closed decision engine;
- `integration` — composition root и HTTP API для frontend и блоков коллег.

## Быстрый запуск в Docker

```powershell
docker compose up --build -d
docker compose ps
```

После запуска:

- операторский интерфейс: `http://127.0.0.1:4173`;
- API: `http://127.0.0.1:8000`;
- Swagger: `http://127.0.0.1:8000/docs`;
- health: `http://127.0.0.1:8000/api/v1/health`.

Оба сервиса должны перейти в состояние `healthy`. Проверка API:

```powershell
Invoke-RestMethod http://127.0.0.1:8000/api/v1/health
```

Просмотр журналов и остановка:

```powershell
docker compose logs -f
# После выхода через Ctrl+C:
docker compose down
```

Первый запуск собирает image и может занять несколько минут. Для последующих
запусков достаточно `docker compose up -d`; после изменения кода добавьте `--build`.
Runtime-журналы сохраняются в именованном volume `neftecode-runtime`.

## Локальный запуск без Docker

```powershell
uv sync --project integration --extra dev
.\run-api.ps1
```

Во втором терминале из каталога `project` запустите frontend:

```powershell
.\.venv\Scripts\python.exe -m http.server 4173 --bind 127.0.0.1 --directory orchestrator/frontend/dist
```

Авторизация для хакатона отключена. CORS уже разрешает локальные frontend-порты и
`https://neftecode-orchestrator-console.yabalbes15.chatgpt.site`.

## Два пути интеграции

1. `POST /api/v1/evaluate` принимает `ProcessState` и историю, вызывает локальные
   адаптеры, собирает `OrchestratorInput` и возвращает решение.
2. `POST /api/v1/decide` принимает готовый `OrchestratorInput`. Этот путь нужен,
   когда Reliability/Safety/Optimization коллег уже сформировали согласованные DTO.

Quality работает на реальных H+C, Reliability — на локальной модели режимного риска.
`/evaluate` вызывает реальный `neftecode_optimizer`; его Safety
проверяет `NO_CHANGE` и каждый кандидат, а сценарии передаются в Orchestrator.
Quality теперь строит candidate-aware прогноз по сопоставленным технологическим тегам
`T6/F9/P13` и переводит серу гидроочистки в модельный товарный продукт через
редактируемый блендинг. Диапазоны CONTROL и рецептуры остаются экспериментальными,
а Reliability оценивает кандидатов только как статический прокси без прогноза
последствий управления. Неподдержанные теги, `UNKNOWN` и отсутствие подтверждённых
управлений сохраняют маршрут fail-closed для операторских изменений.

## Проверка

```powershell
.\.venv\Scripts\python.exe -m pytest -q integration/tests
.\.venv\Scripts\python.exe -m pytest -q neftecode_optimizer/tests
$env:PYTHONPATH = (Resolve-Path "orchestrator/src").Path
.\.venv\Scripts\python.exe -m unittest discover -s orchestrator/tests -q
Remove-Item Env:PYTHONPATH
.\.venv\Scripts\python.exe -m pytest -q Quality_neftecode/tests
.\.venv\Scripts\python.exe -m unittest reliability_agent.test_agent -q
```

Текущее состояние проверяется пятью независимыми наборами тестов: Integration,
Optimizer, Orchestrator, QualityAgent и ReliabilityAgent.

## Бенчмарк и дашборд

Откройте [бенчмарк-дашборд](integration/dashboard/benchmark.html) в браузере. Страница работает
офлайн и показывает тестовые метрики QualityAgent рядом с ПАК, частоту
предупреждений ReliabilityAgent на калибровке и позднем тесте, а также результаты
повторного запуска девяти демо-сценариев, исторического среза и расчётной смеси.
Исторический случай без рецептуры получает `REFUSE`; расчётная смесь на реальных
измерениях с предположенными долями 80/20 получает `KEEP`. Они разделены по
происхождению данных.

Пересборка из сохранённых метрик и текущего API:

```powershell
.\.venv\Scripts\python.exe -X utf8 -m integration.scripts.build_benchmark_dashboard
```

Рядом создаётся `integration/dashboard/benchmark_data.json` с исходными числами.
Точность прогноза отказов здесь не оценивается: в данных нет меток отказов.
Метрики качества уже были получены на раскрытом test-периоде; новый независимый
holdout ещё не накоплен.

## Операторский экран

Откройте `http://127.0.0.1:4173`. Экран проверит API на `127.0.0.1:8000` и
автоматически покажет результат расчётной смеси. В списке API доступны
исторический срез и девять what-if сценариев. Выбор «Пример интерфейса» показывает
ранее сохранённые контрактные результаты, включая `RECOMMEND`; они не являются
решениями текущих моделей. При недоступности API экран продолжает работать как
просмотрщик этих примеров. Границы достоверности расчётной смеси описаны в
[аудите рецептуры и управлений](neftecode_optimizer/docs/recipe_and_controls_audit.md).

## Состав Docker-сборки

В image включаются код, операторский frontend, необходимые H+C bundles и модель Reliability; исходные Excel/CSV,
старые окружения и исследовательские artifacts исключены. Compose автоматически подключает
именованный volume `neftecode-runtime` к `/app/integration/runtime` для trace и shadow-логов.

Перед сборкой должны существовать два активных bundle:

- `Quality_neftecode/artifacts/experiments/H_full_pak_residual_oof_calibration`;
- `Quality_neftecode/artifacts/experiments/C_telemetry_only`.

Оба активных bundle входят в release-сборку. Если они отсутствуют, контейнер завершится
с понятным сообщением и перечислит недостающие пути. Проверить журнал можно командой
`docker compose logs api`.

Материалы для защиты собраны в [submission](submission/DEMO_CHECKLIST.md): там
есть четырёхминутный сценарий показа и финальная презентация.

После публикации контейнера frontend должен использовать его HTTPS URL как API base,
например `https://api.example.ru/api/v1`. Разрешённый origin текущего frontend уже
зафиксирован в `integration/config.yaml`.
