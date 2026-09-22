# Оркестратор Нефтекод

Модуль принимает уже рассчитанные результаты внешних компонентов и формирует
финальное решение `RECOMMEND`, `KEEP` или `REFUSE`.

Оркестратор не рассчитывает качество, надёжность, ограничения или ranking. Эти
результаты считаются входными контрактами внешних компонентов.

## Состав

- `src/neftecode_orchestrator/contracts.py` — временные Pydantic-контракты;
- `schemas/` — зафиксированные JSON Schema для интеграции;
- `src/neftecode_orchestrator/policy.py` — чистая decision policy;
- `src/neftecode_orchestrator/service.py` — сборка решения и trace;
- `src/neftecode_orchestrator/explanation.py` — детерминированное объяснение;
- `src/neftecode_orchestrator/stubs.py` — временные данные внешних блоков;
- `examples/` — три воспроизводимых сценария;
- `tests/` — contract и decision tests.

## Безопасность

- Любая ошибка обязательного компонента приводит к `REFUSE`.
- Кандидат может попасть в `RECOMMEND` только после положительного Safety.
- Средней уверенности достаточно для `KEEP`, но недостаточно для `RECOMMEND`.
- Низкая или неизвестная уверенность приводит к `REFUSE`.
- `NO_FEASIBLE_SOLUTION` означает `KEEP`, если текущий режим безопасен, и
  `REFUSE`, если текущий режим небезопасен.

## Запуск примера

Из каталога `orchestrator`:

```powershell
$env:PYTHONPATH = "src"
python -m neftecode_orchestrator.cli examples/recommend.json
```

С записью полного trace:

```powershell
$env:PYTHONPATH = "src"
python -m neftecode_orchestrator.cli examples/recommend.json --trace output/trace.jsonl
```

С явной конфигурацией policy:

```powershell
$env:PYTHONPATH = "src"
python -m neftecode_orchestrator.cli examples/recommend.json --policy config/policy.json
```

## Тесты

```powershell
$env:PYTHONPATH = "src"
python -m unittest discover -s tests -v
```

## Обновление JSON Schema

```powershell
$env:PYTHONPATH = "src"
python scripts/export_contracts.py
```

До появления общего пакета файлы из `schemas/` являются интеграционным
контрактом. Изменение схемы требует повышения `schema_version`.
