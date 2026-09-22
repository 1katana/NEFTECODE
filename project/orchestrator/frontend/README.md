# Orchestrator frontend

Операторская консоль запрашивает актуальные решения `KEEP / REFUSE` у Integration
API и показывает происхождение данных. Сохранённые `RECOMMEND / KEEP / REFUSE`
остаются отдельными контрактными примерами интерфейса. Они генерируются из
`../examples/*.json` через `OrchestratorService`.

## Обновить демо-данные

```powershell
python scripts/build_demo_data.py
```

## Локальный запуск

```powershell
python -m http.server 4173 --directory dist
```

Перед этим запустить API из корня проекта через `.\run-api.ps1`. Открыть
`http://127.0.0.1:4173`. Экран автоматически запускает расчётную смесь,
затем позволяет выбрать исторический срез и девять what-if запросов. Если API
недоступен, остаются сохранённые контрактные примеры.

Для другого адреса API установить `window.NEFTECODE_API_BASE` до загрузки
`app.js`; значение должно оканчиваться на `/api/v1`. Origin frontend следует
добавить в `integration/config.yaml`.

## Проверка

```powershell
node tests/smoke.mjs
```

Консоль также умеет локально импортировать `FinalDecision` или объект
`{"input": OrchestratorInput, "decision": FinalDecision}` для проверки интеграции.
