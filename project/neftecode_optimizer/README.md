# Neftecode Optimizer

Краткий документ для сборки общего пайплайна и передачи Полине:
[POLINA_HANDOFF.md](POLINA_HANDOFF.md).
Готовый архив для передачи собирается командой `py scripts/build_handoff.py`
в `handoff/neftecode_optimizer_for_polina.zip`.

Подробное описание контрактов, выбора, ошибок и незаполненных настроек:
[docs/integration.md](docs/integration.md).

Сверка с исходным ZIP и список подтверждённых/неподтверждённых фактов:
[docs/source_evidence.md](docs/source_evidence.md).

Офлайн-проверка на архиве `датасеты.zip`:
[docs/dataset_replay.md](docs/dataset_replay.md).

Установка в новом каталоге (PowerShell, Python 3.11+):

```powershell
py -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e ".[dev]"
.\.venv\Scripts\python.exe -m pytest
```

Дополнительный параметр CLI `--safety-policy optimization/safety_policy.yaml`
загружает явную политику проверок. `--output result.json` сохраняет новый файл,
отказываясь перезаписывать существующий. Ошибки входа дают код возврата 2.

Рабочий MVP слоя `Candidate Generator -> Safety -> Ranking`. QualityAgent и
ReliabilityAgent подключаются снаружи и могут разрабатываться независимо.

## Что гарантирует оптимизатор

- изменяет только CONTROL из `control_config.yaml`: по умолчанию допускаются
  лишь диапазоны `CONFIRMED_OPERATING`, экспериментальные и моковые требуют
  явного разрешения в SafetyPolicy;
- всегда рассматривает KEEP;
- ограничивает `min/max`, `max_delta`, число одновременно изменяемых CONTROL и
  общее число кандидатов;
- запускает Safety до Ranking;
- жёстко отбрасывает нарушение `sulfur <= 10 mg/kg`;
- для товарного продукта также проверяет `T95 <= 360 °C`, сезонную плотность,
  сезонное цетановое число, сумму долей 100% и присадку не более 3%;
- не считает серу после гидроочистки доказательством качества товарного дизеля:
  агент качества должен явно указать `product: COMMERCIAL_DIESEL`;
- требует явный источник входа `SYNTHETIC`, `HISTORICAL` или `LIVE`;
  небоевые входы по умолчанию не могут дать действие;
- по умолчанию не допускает действие на оценках агентов без `source: REAL`;
- возвращает `RECOMMEND`, `KEEP` или `NO_FEASIBLE_SOLUTION`; среди вариантов с
  одинаковым риском учитывает `relative_cost` бленда, включая цену присадки;
- не использует экономический score для компенсации hard constraints.

Timestamp состояния, привязанного к LIMS, трактуется как время отбора пробы.

## Запуск mock-пайплайна

```powershell
.\.venv\Scripts\python.exe -m optimization `
  --state examples\mock_state.json `
  --control-config examples\mock_control_config.yaml `
  --mock-config examples\mock_assessments.yaml `
  --safety-policy examples\mock_safety_policy.yaml
```

Вход примера помечен `source: SYNTHETIC`, оценки — `source: MOCK`.
Результат содержит `input_source: SYNTHETIC`,
`uses_mock_assessments: true` и `RELAXED_ACTION_POLICY`. Это только
интеграционный прогон, не рекомендация оператору. Разрешения на действия
по синтетическим данным находятся лишь в `examples/mock_safety_policy.yaml`.

В `OptimizationResult` безопасные варианты находятся в `ranked_candidates`,
отбракованные Safety — в `rejected_candidates`, а сбои вызова агентов — в
`agent_failures`. Поэтому решение можно полностью объяснить и восстановить.

## Контракт интеграции агентов

```python
class QualityAgent:
    def predict(self, state, candidate) -> QualityAssessment: ...

class ReliabilityAgent:
    def evaluate(self, state, candidate) -> ReliabilityAssessment: ...
```

Затем агенты передаются без дополнительных зависимостей:

```python
optimizer = Optimizer(
    quality_agent=quality_agent,
    reliability_agent=reliability_agent,
    control_config="optimization/control_config.yaml",
)
result = optimizer.search(process_state)
```

Агенты также могут вернуть обычный `dict` с полями соответствующей Pydantic-
модели: Optimizer валидирует его на границе. `ProcessState.source` обязателен:
пока данные генерируются — `SYNTHETIC`; для офлайн-архива — `HISTORICAL`;
в будущем для реального потока — `LIVE`. Интерфейс `Optimizer.search(state)`
при этом не меняется.

Для проверки контракта на реальных исторических строках есть
`iter_historical_cases("датасеты.zip", split="test")`. Он передаёт оптимизатору
только текущую телеметрию; лабораторная сера остаётся отдельно и не попадает
во вход агента. Это проверка пайплайна, а не доказательство эффекта изменения
режима. Пример и ограничения — в [docs/dataset_replay.md](docs/dataset_replay.md).

JSON Schema и отдельный API не нужны: все блоки работают в одном Python-
процессе через Pydantic-модели. Их валидация остаётся на границах оптимизатора.

## Что требуется подтвердить вручную

В production-конфиг внесены подтверждённые по смыслу теги `hyd_t6`, `hyd_f9`,
`hyd_p13`, а также модельные доли блендинга и присадка. Их min/max/step/max_delta
помечены `EXPERIMENTAL_MODEL`: это сценарные границы, не утверждённый операторный
регламент. Товарное качество приходит из явной линейной модели блендинга.
Экономический callback необязателен: без него работает прозрачное ранжирование
по качеству, риску и величине действия.
