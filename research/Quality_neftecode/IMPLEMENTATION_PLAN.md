# План реализации QualityAgent

## 1. Цель и границы компонента

QualityAgent должен по `ProcessState` и опциональному `CandidateAction` вернуть
стабильный `QualityAssessment`:

- прогноз содержания серы, мг/кг;
- нижнюю и верхнюю границы прогноза;
- вероятность нарушения `S > 10 мг/кг`;
- оценку доверия к данным/прогнозу;
- машинно-читаемые предупреждения.

Компонент не принимает финальное решение `RECOMMEND/KEEP/REFUSE`, не проверяет
механическую надёжность и не выполняет safety constraints. Эти обязанности
остаются у Orchestrator, ReliabilityAgent и Safety.

## 2. Текущая готовность

| Блок | Статус | Что уже есть |
|---|---|---|
| Данные | Готово с оговорками | 1 462 LIMS-пробы, 1 458 допустимых строк |
| Схема признаков | Готово | 2 985 полных и 661 baseline-признак |
| Защита от leakage | Готово | LIMS target исключён из feature list, past-only join |
| Data quality | Готово | отчёт по missing/flatline, маркировка выбросов |
| Training code | A–H выполнены | Direct anchors, target sensitivity, telemetry fallback, PAK-residual, OOF-shrinkage и OOF-выбор калибровки |
| Runtime inference | Реализован | общий FeaturePipeline, history buffer, confidence gates, PAK passthrough, telemetry-only router и shadow-log |
| Candidate prediction | What-if готов | линейный отклик `T6/F9/P13`, горизонт 0–3 ч, явная маркировка experimental |
| Контракт Orchestrator | Готово | двусторонние contract-parity tests проходят |
| Артефакты моделей | A–H готовы | H — shadow candidate; champion не назначен: residual MAE 1,3629 против 1,3128 у текущего ПАК |
| Тесты | Готовы для текущего этапа | 50 QualityAgent tests; H+C runtime/shadow интеграция проверена |

## 3. Ключевое архитектурное разделение

Нужно реализовать два явно различающихся режима.

### 3.1. Current quality assessment

Оценка качества текущего состояния по последним доступным ПАК и телеметрии.
Это soft sensor и первый MVP. Обучающая строка привязана к времени реальной
пробы ЛИМС, все признаки имеют timestamp `<= sample_timestamp`.

### 3.2. Candidate quality projection

Оценка качества после применения управляющего воздействия. Она не может честно
использовать ту же постановку, что current assessment: действие в момент `t`
должно сопоставляться с LIMS target в момент `t + horizon`.

Текущий runtime реализует упрощённую candidate-модель:

1. принимает горизонт 0–3 часа в `CandidateAction.horizon_hours`;
2. применяет first-order response к `hyd_t6/hyd_f9/hyd_p13`;
3. не меняет исторические lag-факты и не пропускает неизвестный CONTROL;
4. маркирует ответ `EXPERIMENTAL_LINEAR_COUNTERFACTUAL`.

Следующий научный этап — заменить коэффициенты отдельными horizon-datasets и
blocked time-series validation. До этого результат является сценарной оценкой,
а не доказательством причинного эффекта воздействия.

## 4. Целевая схема компонента

```text
ProcessState + CandidateAction
              |
              v
      Contract adapter
              |
              v
   History/Feature provider ---- feature_schema.json
              |
              v
     Data-quality gates
              |
              v
  Current model / Candidate model
       |       |       |
   regression quantiles classifier
              |
              v
       probability calibration
              |
              v
  confidence + warnings + OOD checks
              |
              v
       QualityAssessment
```

Orchestrator не должен рассчитывать ML-признаки. QualityAgent должен владеть
feature pipeline и обеспечивать одинаковую логику offline/online.

## 5. Этапы реализации

### Этап 0. Зафиксировать постановку — 0,5 дня

Нужно подтвердить:

- фактический признак публикации ЛИМС вместо консервативного `+4h`;
- коэффициенты отклика и утверждённые диапазоны/шаги CONTROL;
- подтверждение модельных рецептур блендинга;
- статус трёх значений серы выше 100 мг/кг;
- приоритет classifier: максимальный recall или баланс precision/recall.

Результат: `configs/modeling.yaml` с target, limit, horizon, split, feature group,
outlier policy и calibration policy.

### Этап 1. Окружение и единый контракт — 1 день

1. Создать новый `.venv` на Python 3.11/3.12, установить зависимости и lock-файл.
2. Удалить зависимость разработки от сломанного `venv` Python 3.9.
3. Привести локальные модели к контрактам Orchestrator:
   - `ProcessState.timestamp/quality/telemetry/data_quality/data_confidence/current_controls`;
   - `CandidateAction.candidate_id/changes/delta`;
   - строгий `QualityAssessment` с finite values и probability `[0, 1]`.
4. До появления общего пакета оставить зеркальные stubs и contract-parity test.
5. Добавить `model_version`, `schema_version` и `prediction_horizon` в runtime
   metadata/log, не меняя согласованный ответ Safety без необходимости.

Результат: совместимые Pydantic-контракты и тесты сериализации в обе стороны.

### Этап 2. Единый offline/online FeaturePipeline — 1–1,5 дня

1. Вынести расчёт lag/rolling/trend из `data_prep.py` в чистый `FeaturePipeline`.
2. Реализовать интерфейс `HistoryProvider` с окном минимум 6 часов.
3. Реализовать два адаптера:
   - batch/pandas для обучения;
   - in-memory history buffer для runtime/demo.
4. Зафиксировать порядок, типы и hash 661 baseline-признака.
5. При отсутствии истории не подставлять нули: вернуть `UNKNOWN`/warning.
6. Добавить parity test: одна и та же временная точка даёт одинаковый vector в
   batch и online pipeline.

Результат: `FeatureVector` одной схемы для обучения и inference без training-serving skew.

### Этап 3. Baseline current-quality models — 1 день

1. Зафиксировать простые baselines:
   - текущее значение ПАК-серы;
   - rolling median/mean ПАК;
   - train median для regression;
   - prevalence для classifier.
2. Обучить на 661 признаке:
   - CatBoostRegressor с MAE;
   - quantile regressors 0.1/0.9;
   - CatBoostClassifier для `P(S > 10)`.
3. Использовать early stopping и фиксированный seed.
4. Основной эксперимент оставить с экстремальными LIMS-значениями.
5. Отдельно выполнить sensitivity-run по согласованной outlier policy.
6. Test не использовать для выбора параметров.

Результат: воспроизводимый bundle baseline-моделей.

### Этап 4. Временная валидация и калибровка — 1 день

1. Внутри train/validation построить blocked expanding-window CV.
2. Собирать out-of-fold probabilities.
3. Использовать sigmoid/Platt calibration; isotonic не применять при 12
   положительных примерах validation.
4. Зафиксировать operating threshold отдельно от `0.5`.
5. Единожды оценить выбранный вариант на test.
6. Считать:
   - regression: MAE, median AE, RMSE, R²;
   - interval: coverage и average width;
   - classifier: PR-AUC, ROC-AUC, precision, recall, F1;
   - calibration: Brier score и ECE;
   - метрики отдельно с/без проб `target_requires_review`.

Рекомендуемые гейты:

- MAE лучше наивного ПАК-baseline;
- PR-AUC заметно выше prevalence;
- калибровка улучшает Brier score;
- 80% interval имеет приемлемое покрытие без чрезмерной ширины;
- метрики не рушатся на последовательных временных фолдах.

Результат: `metrics.json`, CV-таблица, calibration artifact и model card.

### Этап 5. Сокращение и стабилизация признаков — 0,5–1 день

1. Сравнить importance/SHAP между временными фолдами.
2. Удалить признаки, важность которых нестабильна или основана на missingness/date proxy.
3. Проверить отдельные модели на 100–250 устойчивых признаках.
4. Сравнить качество, latency и стабильность с baseline на 661 признаке.
5. Зафиксировать финальную feature schema как immutable artifact.

Результат: компактная схема без ухудшения test-качества.

### Этап 6. Candidate model — 1,5–2,5 дня

1. Пересобрать выборки `features(t) -> LIMS(t + H)` для согласованных горизонтов.
2. Оставить только controls, которые реально присутствуют в historical data и
   доступны через `CandidateAction`.
3. Реализовать `apply_candidate` без изменения исторических lag-фактов.
4. Обучить candidate regression/classifier/interval для выбранного horizon.
5. Добавить OOD-проверку:
   - control вне train min/max/quantile range;
   - слишком большая delta;
   - неизвестный control;
   - недостаточная история.
6. При OOD снижать confidence и возвращать warning; Safety остаётся владельцем
   окончательного запрета.
7. Проверить инвариант: `NO_CHANGE` близок к current projection в пределах
   согласованной погрешности.

Результат: candidate-aware `predict(state, candidate)` без игнорирования candidate.

### Этап 7. Runtime QualityAgent — 1 день

1. Загружать bundle атомарно и валидировать schema/version/hash.
2. Реализовать:
   - `predict_current(state)`;
   - `predict_candidate(state, candidate)`;
   - публичный `predict(state, candidate=None)`.
3. Собрать confidence из:
   - полноты и свежести данных;
   - доступности 6-часовой истории;
   - interval width;
   - OOD score;
   - наличия PAK flatline;
   - версии/совместимости схемы.
4. При критическом недостатке данных возвращать null-прогнозы и
   `INSUFFICIENT_INPUT`, а не число низкого качества.
5. Обеспечить deterministic result для одинакового входа и model bundle.

Результат: рабочий агент и CLI/API для локального вызова.

### Этап 8. Интеграция с Orchestrator — 0,5–1 день

1. Добавить adapter, реализующий интерфейс `QualityAgentPort` Orchestrator.
2. Прогнать сценарии:
   - current/NO_CHANGE;
   - normal candidate;
   - risky candidate;
   - отсутствующая история;
   - stale/flatline ПАК;
   - неизвестный control;
   - timeout/model unavailable.
3. Проверить, что Orchestrator передаёт `QualityAssessment` в Safety без
   преобразований и потери warnings.
4. Зафиксировать timeout и fallback policy.

Результат: end-to-end вызов Orchestrator → QualityAgent → Safety.

### Этап 9. Тесты, наблюдаемость и документация — 1 день

1. Исправить `text_fixtures.py` на `test_fixtures.py`.
2. Синхронизировать ожидания normal/risky/insufficient fixtures.
3. Добавить тесты:
   - no future leakage;
   - target отсутствует в X;
   - offline/online feature parity;
   - contract parity с Orchestrator;
   - artifact load/version mismatch;
   - probability/interval invariants;
   - candidate NO_CHANGE/change/OOD;
   - deterministic output;
   - smoke latency и memory.
4. Логировать model/schema version, latency, confidence и warning codes.
5. Подготовить README, model card, команды rebuild/train/evaluate/predict.

Результат: воспроизводимая сборка и эксплуатационная документация.

## 6. Структура артефактов

```text
artifacts/<model_version>/
  feature_schema.json
  training_manifest.json
  current_regression.cbm
  current_quantile_low.cbm
  current_quantile_high.cbm
  current_classifier.cbm
  candidate_<horizon>_regression.cbm
  candidate_<horizon>_classifier.cbm
  probability_calibrator.pkl
  operating_thresholds.json
  metrics.json
  model_card.md
```

Каждый bundle immutable. Агент запускается только если все файлы соответствуют
одному `model_version` и одному hash схемы.

## 7. Definition of Done

- [ ] Зафиксированы target, признаки, horizon, split и outlier policy.
- [x] Regression и classifier обучаются одной воспроизводимой командой.
- [x] Метрики val/CV/test и сравнение с наивными baseline сохранены.
- [x] Raw/sigmoid выбирается и калибруется на out-of-fold predictions без test.
- [x] Offline и online feature vectors совпадают для зафиксированной feature schema.
- [x] `CandidateAction` реально влияет на candidate-модель либо агент явно
      возвращает неподдерживаемый режим; молчаливое игнорирование запрещено.
- [x] Контракты совместимы с Orchestrator.
- [x] `predict(state, candidate)` возвращает валидный `QualityAssessment` либо
      явный fail-closed ответ для неподдерживаемого changing candidate.
- [x] При недостатке данных прогнозы null, confidence `UNKNOWN`, есть warning.
- [ ] Normal/risky/insufficient и candidate fixtures проходят.
- [x] Model/schema versions проверяются при загрузке.
- [x] Нет target leakage и future leakage.
- [x] Есть инструкции rebuild/train/predict; model card создаётся training pipeline.

## 8. Оценка сроков

- MVP current-quality agent без candidate projection: **5–6 рабочих дней**.
- Полный DoD с candidate-aware моделью и интеграцией: **8–10 рабочих дней**.
- Само локальное обучение занимает минуты; основное время — постановка horizon,
  временная валидация, online feature parity и интеграционные тесты.

## 9. Рекомендуемая последовательность ближайших действий

1. Запустить H + C в shadow-режиме с point estimate из исправного ПАК.
2. Накопить заранее ограниченный будущий LIMS-holdout и оценить drift.
3. Согласовать candidate horizon и control mapping.
4. Реализовать candidate horizon dataset/model.
5. Выполнить end-to-end интеграцию с Orchestrator и закрыть fixture/latency DoD.
