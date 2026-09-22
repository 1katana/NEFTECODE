# Состояние QualityAgent на 2026-09-20

## Оценка готовности

- Контрольная точка до продолжения работ: **75%** полного плана / **90%** MVP.
- После закрытия локальной интеграции и shadow-gates: **80%** полного плана /
  **95%** MVP оценки текущего качества.
- Режим эксплуатации: **shadow only**, production champion не назначен.

## Зафиксированная архитектура

1. Одна строка обучения соответствует одной реальной пробе ЛИМС.
2. `timestamp` ЛИМС — подтверждённое время отбора; runtime-доступность — `+4h`.
3. При неинвалидном серном ПАК точечная оценка берётся из ПАК.
4. Primary ML возвращает вероятность нарушения и prediction interval.
5. При `FLATLINE/STALE/MISSING/JUMP_UNCONFIRMED` используется telemetry-only fallback C;
   `Q21=307` исключается как выброс.
6. Changing `CandidateAction` использует явно маркированную линейную what-if модель
   `T6/F9/P13` и возвращает `candidate_horizon_hours` в диапазоне 0–3 часа.
7. Товарное качество считается модельным блендингом; Safety проверяет серу, T95,
   плотность, цетановое число, 100% долей и присадку не более 3%.
8. Shadow-log не запускает автоматическое переобучение и не меняет контракт
   `QualityAssessment`.

## Данные и модель

- Всего проб ЛИМС: 1 462.
- Допустимых строк: 1 458.
- Baseline-признаков: 661.
- Основной shadow-bundle:
  `artifacts/experiments/H_full_pak_residual_oof_calibration`.
- Fallback-bundle:
  `artifacts/experiments/C_telemetry_only`.
- Residual scale H: 1.00, выбран на blocked OOF.
- OOF calibration selection: sigmoid, Brier 0.1224 против 0.1338 у raw.
- Test calibration: sigmoid Brier 0.1351 против 0.1227 у raw.
- Test MAE H: 1.3629.
- Test MAE текущего ПАК: 1.3128.

Вывод: H не проходит regression-gate относительно ПАК и остаётся только
shadow-кандидатом. Test уже раскрыт и не используется для дальнейшей настройки.

## Реализовано

- строгие временные контракты, совместимые с Orchestrator;
- LIMS-centric data preparation и past-only joins;
- общий offline/online FeaturePipeline;
- обработка missing/stale/flatline/jump;
- regression, quantile interval и violation classifier;
- blocked expanding OOF с gap 6 часов;
- OOF-выбор residual scale и raw/sigmoid;
- hybrid router H+C;
- PAK passthrough для point estimate;
- append-only shadow JSONL;
- присоединение фактических проб ЛИМС без будущих прогнозов;
- shadow-метрики MAE/RMSE/Brier;
- schema hash, manifest и training ID;
- CLI prepare/train/predict/shadow-log-lims/shadow-summary.
- pinned `configs/runtime_shadow.yaml` и preflight-команда `runtime-check`.
- 51 автоматический тест проходит, пропущенных тестов нет.
- QualityAgent подключён к общему Integration API и проверен сквозным HTTP
  сценарием `ProcessState + 6h history → Quality → Safety → Orchestrator → KEEP`.
- Добавлены коммерческий блендинг и девять редактируемых what-if сценариев.
- Управляющие теги исправлены на `hyd_t6`, `hyd_f9`, `hyd_p13`; диапазоны
  помечены `EXPERIMENTAL_MODEL`.

## Открытые ограничения

1. Коэффициенты candidate-отклика и диапазоны CONTROL не утверждены технологом.
2. Линейное смешение не является реальной заводской рецептурой.
3. Нет независимого будущего holdout после 2026-08-06.
4. Нет production-решения о минимальном объёме shadow-выборки и promotion gates.
5. Не завершены timeout/latency/memory и end-to-end проверки реального транспорта.

## Следующий неблокированный этап

1. Проверить H+C как единый runtime bundle.
2. ~~Закрыть все локальные integration tests без продвижения H в champion.~~
3. ~~Зафиксировать машинно-читаемые shadow promotion gates.~~
4. Подключить накопление будущих LIMS-фактов к реальному транспорту.
