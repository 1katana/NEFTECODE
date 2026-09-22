# QualityAgent

Реализация QualityAgent для оценки содержания серы и вероятности `S > 10 мг/кг`.
Подготовка данных, контракты, общий offline/online FeaturePipeline и тренировочный
контур готовы. Подтверждено: `timestamp ЛИМС = время отбора`, а в runtime
результат считается доступным не раньше `sample_timestamp + 4h`; варианты A–H
обучены 2026-09-18.

## Текущий статус

- контракты зеркально совместимы с Orchestrator;
- batch и runtime используют один расчёт lag/rolling/trend;
- runtime накапливает шестичасовую историю и не подставляет нули;
- offline/online parity проверяется на реальной точке для актуальной схемы из 661 признака;
- changing candidate рассчитывается прозрачной экспериментальной линейной
  моделью отклика `T6/F9/P13` с горизонтом 0–3 часа; это what-if, не доказанный
  причинный эффект;
- training использует blocked time-series OOF и выбирает raw/sigmoid по
  отдельному последнему OOF-блоку, не используя test;
- model bundle проверяется по schema hash и manifest;
- runtime-router оставляет исправный ПАК point estimate, берёт риск/интервал из
  primary ML и переключает invalid/stale/missing ПАК на telemetry-only bundle;
- shadow JSONL сохраняет выбранный ответ, ответы обеих моделей, состояние ПАК,
  признаки и позволяет присоединять запоздавший результат ЛИМС;
- артефакты A–H сохранены в `artifacts/experiments`, но champion не назначен:
  residual-run почти догнал, но пока уступает наивному текущему ПАК по MAE;
- 51 тест QualityAgent проходит без пропусков; integration-тесты используют явно
  зафиксированные shadow-bundles H+C без продвижения их в production champion.

## Гранулярность обучающей выборки

- одна строка — одна реальная проба ЛИМС `Mg.Sulfur` финального продукта Гидроочистки;
- target — значение ЛИМС и бинарный признак `S > 10 мг/кг`;
- признаки — только значения ПАК и телеметрии АВТ/24-2000, доступные не позднее времени пробы;
- ЛИМС не протягивается на 10-минутную сетку и не используется как признак;
- ПАК не используется как target;
- выбросы не удаляются автоматически.

Полная витрина включает текущие as-of значения, лаги 30/60/120/240/360 минут,
rolling mean/std/min/max/coverage и trend за 1/2/4/6 часов. В
`feature_schema.json` отдельно записан более компактный набор
`baseline_feature_columns`, рекомендуемый для первого запуска на ноутбуке.
Из него исключаются телеметрические теги с существенными длинными flatline и
признаки, заполненные менее чем в 50% train. Они остаются в полной витрине для
дальнейшего анализа. Для ПАК добавлены признаки качества сигнала; после 60 минут
точного flatline числовые PAK-признаки маскируются в `NaN`, а health-флаги остаются.
Сильный соседний скачок помечается порогом `q99.9`, рассчитанным только на train;
само измерение при этом не удаляется.

## Окружение

Из папки `Quality_neftecode`:

```powershell
uv sync --extra dev
uv run pytest -q
```

Точные версии зависимостей находятся в `uv.lock`. Старый каталог `venv` не
используется: он привязан к отсутствующему Python 3.9 другого компьютера.

## Сборка данных

Из папки `Quality_neftecode`:

```powershell
uv run quality-agent prepare-data `
  --workspace-root .. `
  --output-dir data/processed `
  --feature-anchor-offset-min 0
```

Скрипт создаёт:

- `quality_training_lims_samples.csv` — все реальные пробы, включая строки без свежей телеметрии;
- `split_train.csv`, `split_val.csv`, `split_test.csv` — только строки со свежей телеметрией;
- `data_quality_report.csv` — пропуски и длинные точные flatline по исходным тегам;
- `feature_schema.json` — контракт признаков и запрет на target leakage;
- `manifest.json` — статистика, readiness и известные ограничения;
- `signal_anomaly_report.json/.md` — диагностика экстремальных ЛИМС, flatline,
  скачков и sensitivity по лагу.

## До обучения обязательно

1. Сверить принятый консервативный runtime-лаг публикации ЛИМС `+4h` с реальным
   признаком готовности анализа, когда он появится в промышленном источнике.
2. Откалибровать экспериментальные коэффициенты candidate-модели на будущих
   сценариях; горизонт выдаётся явно и ограничен диапазоном 0–3 часа.
3. Подтвердить промышленные диапазоны/шаги для уже сопоставленных `T6/F9/P13`.

Выбранная политика по экстремальным target, flatline, скачкам, режимам и матрице
первого эксперимента описана в `TRAINING_STRATEGY.md`.

Калибровка переведена с isotonic на проверяемый выбор raw/sigmoid по blocked OOF.

## Повторный запуск обучения

```powershell
uv run quality-agent train `
  --train data/processed/split_train.csv `
  --val data/processed/split_val.csv `
  --test data/processed/split_test.csv `
  --schema data/processed/feature_schema.json `
  --config configs/modeling.yaml `
  --out artifacts/current-v1
```

Bundle содержит модели regression/quantiles/classifier, calibrator, schema,
metrics, operating threshold, manifest и model card.

Обязательная матрица A/B/C запускается отдельной командой:

```powershell
uv run quality-agent train-matrix `
  --train data/processed/split_train.csv `
  --val data/processed/split_val.csv `
  --test data/processed/split_test.csv `
  --schema data/processed/feature_schema.json `
  --config configs/modeling.yaml `
  --out artifacts/experiments
```

Она создаёт full-model на всех target, sensitivity-регрессию без `S > 100` и
telemetry-only fallback. Anchor-варианты `t-60m` и `t-120m` сначала собираются
`prepare-data --feature-anchor-offset-min 60/120` в отдельных каталогах.

Результаты A–H и решение не назначать champion находятся в
`artifacts/experiments/COMPARISON.md`.

CLI поддерживает `--regression-mode pak_residual`: модель учит поправку
`LIMS − PAK`, а runtime прибавляет её к валидному текущему ПАК. При невалидном
ПАК router использует telemetry-only bundle. Опция
`--residual-scale-mode blocked_oof_mae` выбирает степень поправки на blocked OOF,
не используя test. Опция `--calibration-policy chronological_holdout` выбирает
raw или sigmoid на последнем OOF-блоке, затем обучает выбранный калибратор на всех
OOF-прогнозах.

## Runtime

Перед запуском проверяется зафиксированная shadow-конфигурация:

```powershell
uv run quality-agent runtime-check `
  --runtime-config configs/runtime_shadow.yaml
```

Команда загружает оба bundle, проверяет schema hash/manifest и роли `full` /
`telemetry_only`. Поддерживается только `mode: shadow`; production mode намеренно
отклоняется до появления независимого holdout и решения о champion.

Для построения временных признаков одиночного state недостаточно. CLI принимает
предшествующую историю `ProcessState` в JSONL:

```powershell
uv run quality-agent predict `
  --state-json state.json `
  --history-jsonl history.jsonl `
  --artifacts artifacts/experiments/H_full_pak_residual_oof_calibration `
  --telemetry-fallback-artifacts artifacts/experiments/C_telemetry_only `
  --point-policy pak_passthrough `
  --shadow-log runtime/shadow.jsonl `
  --config configs/modeling.yaml
```

`--point-policy pak_passthrough` меняет только точечный прогноз при неинвалидном
ПАК. Вероятность нарушения и интервал остаются ML-выходами; интервал при
необходимости расширяется так, чтобы включать point estimate. При invalid ПАК
router использует C. Без `--shadow-log` в нормальном режиме вызывается только
выбранная модель; в shadow-режиме вычисляются обе для последующего сравнения.

Когда получена проба ЛИМС, её добавляют по времени отбора:

```powershell
uv run quality-agent shadow-log-lims `
  --shadow-log runtime/shadow.jsonl `
  --timestamp 2026-09-19T10:30:00+03:00 `
  --value 8.7 `
  --sample-id LIMS-12345

uv run quality-agent shadow-summary `
  --shadow-log runtime/shadow.jsonl `
  --tolerance-min 10

uv run quality-agent shadow-evaluate `
  --shadow-log runtime/shadow.jsonl `
  --gates-config configs/shadow_gates.yaml
```

Сводка сопоставляет пробу только с прогнозом в то же или более раннее время,
считает MAE/RMSE для выбранного ответа, primary, fallback и ПАК, а также Brier.
Сам shadow-log не участвует в переобучении автоматически.
`shadow-evaluate` применяет заранее зафиксированные evidence/quality gates и
возвращает `INSUFFICIENT_EVIDENCE`, `NOT_READY` или `READY_FOR_REVIEW`. Даже
последний статус требует ручного решения и никогда не продвигает bundle автоматически.

При истории короче шести часов возвращаются null-прогнозы,
`data_confidence=UNKNOWN` и `INSUFFICIENT_HISTORY`.
