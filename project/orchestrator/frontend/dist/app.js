(function () {
  "use strict";

  const dataset = window.ORCHESTRATOR_SCENARIOS;
  if (!dataset || !Array.isArray(dataset.scenarios)) {
    document.body.innerHTML =
      '<main class="workspace"><h1>Не удалось загрузить демо-данные</h1><p>Запустите scripts/build_demo_data.py.</p></main>';
    return;
  }

  const $ = (selector) => document.querySelector(selector);
  const elements = {
    select: $("#scenario-select"),
    description: $("#scenario-description"),
    decisionPanel: $("#decision-panel"),
    decisionCode: $("#decision-code"),
    decisionPictogram: $("#decision-pictogram"),
    explanation: $("#decision-explanation"),
    nextStep: $("#decision-next-step"),
    reasonCodes: $("#reason-codes"),
    safetyBadge: $("#state-safety-badge"),
    quality: $("#quality-value"),
    qualityRange: $("#quality-range"),
    violation: $("#violation-value"),
    violationBar: $("#violation-bar"),
    reliability: $("#reliability-value"),
    riskScore: $("#risk-score"),
    confidence: $("#confidence-value"),
    timestamp: $("#state-timestamp"),
    currentControls: $("#current-controls"),
    recommendation: $("#recommendation-block"),
    candidateId: $("#candidate-id"),
    recommendedControls: $("#recommended-controls"),
    predictedQuality: $("#predicted-quality"),
    predictedViolation: $("#predicted-violation"),
    predictedScore: $("#predicted-score"),
    componentList: $("#component-list"),
    pipelineTotal: $("#pipeline-total"),
    scenarioCount: $("#scenario-count"),
    safeCount: $("#safe-count"),
    optimizationStatus: $("#optimization-status"),
    rankingBody: $("#ranking-body"),
    rankingEmpty: $("#ranking-empty"),
    traceRunId: $("#trace-run-id"),
    traceId: $("#trace-id"),
    traceTime: $("#trace-time"),
    traceSchema: $("#trace-schema"),
    warningBlock: $("#warning-block"),
    warningList: $("#warning-list"),
    traceToggle: $("#trace-toggle"),
    traceJson: $("#trace-json"),
    copyButton: $("#copy-button"),
    importButton: $("#import-button"),
    importDialog: $("#import-dialog"),
    importTextarea: $("#import-textarea"),
    importError: $("#import-error"),
    applyImport: $("#apply-import"),
    toast: $("#toast"),
    apiSelect: $("#api-select"),
    apiRun: $("#api-run"),
    activeSource: $("#active-source"),
    modeApi: $("#mode-api"),
    modeDemo: $("#mode-demo"),
    apiControls: $("#api-controls"),
    demoControls: $("#demo-controls"),
    uploadButton: $("#upload-test-data"),
    uploadDialog: $("#upload-dialog"),
    uploadForm: $("#upload-form"),
    uploadError: $("#upload-error"),
    closeUpload: $("#close-upload"),
    cancelUpload: $("#cancel-upload"),
    submitUpload: $("#submit-upload"),
  };

  const labels = {
    HIGH: "Высокая",
    MEDIUM: "Средняя",
    LOW: "Низкая",
    UNKNOWN: "Неизвестна",
  };

  const componentNames = {
    current_quality: "QualityAgent",
    current_reliability: "ReliabilityAgent",
    current_safety: "Safety",
    optimization: "Optimizer",
  };

  const decisionVisuals = {
    KEEP: { src: "assets/decision-keep.png?v=2", alt: "Улыбающаяся капля" },
    RECOMMEND: { src: "assets/decision-recommend.png?v=2", alt: "Задумчивая капля" },
    REFUSE: { src: "assets/decision-refuse.png?v=2", alt: "Грустная капля" },
  };

  let currentScenario = dataset.scenarios[0];
  let lastDemoScenario = dataset.scenarios[0];
  let lastApiScenario = null;
  let toastTimer;
  const apiBase = window.NEFTECODE_API_BASE || "http://127.0.0.1:8000/api/v1";
  let apiItems = [];

  function setMode(mode) {
    const isApi = mode === "api";
    elements.apiControls.hidden = !isApi;
    elements.demoControls.hidden = isApi;
    elements.modeApi.classList.toggle("active", isApi);
    elements.modeDemo.classList.toggle("active", !isApi);
    elements.modeApi.setAttribute("aria-selected", String(isApi));
    elements.modeDemo.setAttribute("aria-selected", String(!isApi));
  }

  function showDemoMode() {
    setMode("demo");
    const selected = dataset.scenarios.find((scenario) => scenario.id === elements.select.value);
    const scenario = selected || lastDemoScenario || dataset.scenarios[0];
    lastDemoScenario = scenario;
    elements.select.value = dataset.scenarios.some((item) => item.id === scenario.id)
      ? scenario.id
      : "";
    renderScenario(scenario);
  }

  function showApiMode() {
    setMode("api");
    if (lastApiScenario) renderScenario(lastApiScenario);
  }

  function escapeHtml(value) {
    return String(value ?? "")
      .replaceAll("&", "&amp;")
      .replaceAll("<", "&lt;")
      .replaceAll(">", "&gt;")
      .replaceAll('"', "&quot;")
      .replaceAll("'", "&#039;");
  }

  function displayNumber(value, digits = 1) {
    return value !== null && value !== undefined && value !== "" && Number.isFinite(Number(value))
      ? Number(value).toFixed(digits)
      : "—";
  }

  function displayProbability(value) {
    return value !== null && value !== undefined && value !== "" && Number.isFinite(Number(value))
      ? `${Math.round(Number(value) * 100)}%`
      : "—";
  }

  function displayDate(value) {
    if (!value) return "—";
    const date = new Date(value);
    return Number.isNaN(date.getTime())
      ? String(value)
      : new Intl.DateTimeFormat("ru-RU", {
          dateStyle: "short",
          timeStyle: "medium",
          timeZone: "UTC",
        }).format(date) + " UTC";
  }

  function statusClass(status) {
    if (status === "OK" || status === true || status === "SUCCESS") return "ok";
    if (status === "TIMEOUT" || status === "ERROR" || status === false) return "danger";
    return "warn";
  }

  function showToast(message) {
    window.clearTimeout(toastTimer);
    elements.toast.textContent = message;
    elements.toast.classList.add("visible");
    toastTimer = window.setTimeout(() => elements.toast.classList.remove("visible"), 2200);
  }

  function initializeSelect() {
    const groups = new Map();
    dataset.scenarios.forEach((scenario) => {
      if (!groups.has(scenario.group)) groups.set(scenario.group, []);
      groups.get(scenario.group).push(scenario);
    });

    elements.select.innerHTML = [...groups.entries()]
      .map(
        ([group, scenarios]) =>
          `<optgroup label="${escapeHtml(group)}">${scenarios
            .map(
              (scenario) =>
                `<option value="${escapeHtml(scenario.id)}">${escapeHtml(scenario.short)}</option>`,
            )
            .join("")}</optgroup>`,
      )
      .join("");
  }

  function renderCurrentState(input, decision) {
    const qualityResult = input?.current_quality;
    const quality = qualityResult?.data;
    const reliability = input?.current_reliability?.data;
    const safety = input?.current_safety?.data;
    const state = input?.process_state;
    const summary = decision.current_state_summary || {};

    const prediction = quality?.quality_prediction ?? summary.quality_prediction;
    const probability = quality?.violation_probability ?? summary.violation_probability;
    const risk = reliability?.reliability_risk ?? summary.reliability_risk;
    const riskScore = reliability?.risk_score ?? summary.risk_score;
    const passed = safety?.constraint_passed ?? summary.constraint_passed;

    elements.quality.textContent = prediction == null ? "—" : `${displayNumber(prediction)} мг/кг`;
    elements.qualityRange.textContent =
      quality?.prediction_lower != null && quality?.prediction_upper != null
        ? `Лимит 10 · интервал ${displayNumber(quality.prediction_lower)}–${displayNumber(quality.prediction_upper)}`
        : "Лимит 10 мг/кг";
    elements.violation.textContent = displayProbability(probability);
    elements.violationBar.style.width = `${Math.max(0, Math.min(100, Number(probability || 0) * 100))}%`;
    elements.violationBar.style.background = Number(probability) >= 0.5 ? "var(--red)" : "var(--amber)";
    elements.reliability.textContent = labels[risk] || risk || "—";
    elements.riskScore.textContent = riskScore == null ? "нет оценки" : `score ${displayNumber(riskScore, 2)}`;
    elements.confidence.textContent = labels[state?.data_confidence] || state?.data_confidence || "—";
    elements.timestamp.textContent = displayDate(state?.timestamp || decision.timestamp);

    elements.safetyBadge.className = `status-pill ${statusClass(passed)}`;
    elements.safetyBadge.textContent =
      passed === true ? "Safety пройден" : passed === false ? "Safety не пройден" : "Safety неизвестен";

    const controls = state?.current_controls || {};
    const entries = Object.entries(controls);
    elements.currentControls.innerHTML = entries.length
      ? entries
          .map(
            ([name, value]) =>
              `<div><dt>${escapeHtml(name)}</dt><dd>${escapeHtml(displayNumber(value))}</dd></div>`,
          )
          .join("")
      : "<div><dt>Уставки</dt><dd>нет данных</dd></div>";
  }

  function renderDecision(decision, input) {
    const type = String(decision.decision || "REFUSE").toLowerCase();
    elements.decisionPanel.classList.remove("recommend", "keep", "refuse");
    elements.decisionPanel.classList.add(type);
    elements.decisionCode.textContent = decision.decision || "UNKNOWN";
    const visual = decisionVisuals[decision.decision] || decisionVisuals.REFUSE;
    elements.decisionPictogram.src = visual.src;
    elements.decisionPictogram.alt = visual.alt;
    elements.explanation.textContent = decision.explanation || "Пояснение не передано.";
    elements.nextStep.textContent =
      decision.decision === "RECOMMEND"
        ? "Действие: проверить рекомендуемые уставки перед применением."
        : decision.decision === "KEEP"
          ? "Действие: оставить текущие уставки без изменений."
          : "Действие: не менять режим и проверить причину защитного отказа.";
    elements.reasonCodes.innerHTML = (decision.reason_codes || [])
      .map((code) => `<span class="tag">${escapeHtml(code)}</span>`)
      .join("");

    const selected = decision.selected_candidate;
    const predicted = decision.predicted_result;
    elements.recommendation.hidden = decision.decision !== "RECOMMEND" || !selected || !predicted;

    if (!elements.recommendation.hidden) {
      elements.candidateId.textContent = selected.candidate_id;
      const changes = selected.changes || {};
      const delta = selected.delta || {};
      elements.recommendedControls.innerHTML = Object.entries(changes)
        .map(
          ([name, value]) =>
            `<div class="change-card"><span>${escapeHtml(name)}</span><strong>${escapeHtml(
              displayNumber(value),
            )}<em>${Number(delta[name]) >= 0 ? "+" : ""}${escapeHtml(
              displayNumber(delta[name]),
            )}</em></strong></div>`,
        )
        .join("");
      elements.predictedQuality.textContent =
        predicted.quality_prediction == null
          ? "—"
          : `${displayNumber(predicted.quality_prediction)} мг/кг`;
      elements.predictedViolation.textContent = displayProbability(predicted.violation_probability);
      elements.predictedScore.textContent = displayNumber(predicted.score, 2);
    }

    elements.traceRunId.textContent = decision.run_id || "—";
    elements.traceId.textContent = decision.trace_id || "—";
    elements.traceTime.textContent = displayDate(decision.timestamp);
    elements.traceSchema.textContent = decision.schema_version || input?.schema_version || "—";

    const warnings = decision.warnings || [];
    elements.warningBlock.hidden = warnings.length === 0;
    elements.warningList.innerHTML = warnings.map((item) => `<li>${escapeHtml(item)}</li>`).join("");
  }

  function renderPipeline(input) {
    const components = Object.entries(componentNames).map(([key, name]) => ({
      name,
      ...(input?.[key] || { status: "UNAVAILABLE" }),
    }));
    const okCount = components.filter((item) => item.status === "OK").length;
    elements.pipelineTotal.className = `status-pill ${okCount === components.length ? "ok" : "danger"}`;
    elements.pipelineTotal.textContent = `${okCount}/${components.length} работают`;
    elements.componentList.innerHTML = components
      .map(
        (component, index) => `
          <li class="component-item">
            <span class="component-index">${String(index + 1).padStart(2, "0")}</span>
            <span>
              <span class="component-name">${escapeHtml(component.name)}</span>
              <span class="component-meta">${
                component.latency_ms == null ? component.message || "нет latency" : `${component.latency_ms} ms`
              }</span>
            </span>
            <span class="component-status ${statusClass(component.status)}">${escapeHtml(
              component.status,
            )}</span>
          </li>`,
      )
      .join("");

    const scenarios = input?.scenarios || [];
    elements.scenarioCount.textContent = String(scenarios.length);
    elements.safeCount.textContent = String(scenarios.filter((item) => item.constraint_passed).length);
  }

  function renderRanking(input) {
    const optimization = input?.optimization;
    const result = optimization?.data;
    const ranked = result?.ranked_candidates || [];
    elements.optimizationStatus.className = `status-pill ${statusClass(
      optimization?.status === "OK" ? result?.status : optimization?.status,
    )}`;
    elements.optimizationStatus.textContent = result?.status || optimization?.status || "NO DATA";
    elements.rankingBody.innerHTML = ranked
      .map((item) => {
        const scenario = (input.scenarios || []).find(
          (candidate) => candidate.candidate.candidate_id === item.candidate.candidate_id,
        );
        const changes = Object.entries(item.candidate.changes || {})
          .map(([name, value]) => `${name}=${displayNumber(value)}`)
          .join(" · ");
        return `<tr>
          <td>#${item.rank}</td>
          <td>${escapeHtml(item.candidate.candidate_id)}</td>
          <td>${escapeHtml(displayNumber(item.score, 2))}</td>
          <td class="${scenario?.constraint_passed ? "safety-pass" : "safety-fail"}">${
            scenario?.constraint_passed ? "PASSED" : "FAILED"
          }</td>
          <td>${escapeHtml(changes || "без изменений")}</td>
        </tr>`;
      })
      .join("");
    elements.rankingEmpty.hidden = ranked.length > 0;
    elements.rankingEmpty.textContent = result?.reasons?.length
      ? `Кандидатов нет: ${result.reasons.join(", ")}`
      : "Ranking не передан.";
  }

  function renderScenario(scenario) {
    currentScenario = scenario;
    const input = scenario.input || {};
    const decision = scenario.decision;
    elements.description.textContent = scenario.description || "Импортированный результат.";
    const source = scenario.sourceLabel || "Контрактный пример · не запуск API";
    elements.activeSource.textContent = source;
    elements.activeSource.className = `source-label ${scenario.apiResult ? "verified" : "caution"}`;
    renderCurrentState(input, decision);
    renderDecision(decision, input);
    renderPipeline(input);
    renderRanking(input);
    elements.traceJson.querySelector("code").textContent = JSON.stringify(
      { input, decision },
      null,
      2,
    );
  }

  async function apiJson(path, options) {
    const response = await fetch(`${apiBase}${path}`, options);
    if (!response.ok) throw new Error(`HTTP ${response.status}: ${path}`);
    return response.json();
  }

  async function runApiItem(item) {
    elements.apiRun.disabled = true;
    elements.apiRun.textContent = "Расчёт…";
    try {
      const result = await apiJson(item.path, { method: "POST" });
      const source = result.assembled_input?.optimization?.data?.input_source || "UNKNOWN";
      lastApiScenario = {
        id: item.id,
        title: item.title,
        short: item.title,
        description: `${item.title}. Источник: ${source}. ${source === "SYNTHETIC" ? "Доли смеси и свойства компонентов — допущения; это не операторская рекомендация." : "Измеренный срез без подтверждённой рецептуры."}`,
        sourceLabel: `API · ${source}${item.kind === "example" && source === "SYNTHETIC" ? " · расчётная смесь" : ""}`,
        apiResult: true,
        input: result.assembled_input,
        decision: result.decision,
      };
      renderScenario(lastApiScenario);
      elements.select.value = "";
      setMode("api");
    } catch (error) {
      showToast("Не удалось выполнить расчёт");
    } finally {
      elements.apiRun.disabled = false;
      elements.apiRun.textContent = "Выполнить расчёт";
    }
  }

  async function uploadTestData(event) {
    event.preventDefault();
    elements.uploadError.textContent = "";
    const formData = new FormData(elements.uploadForm);
    for (const name of ["avt_tags", "hydro_tags", "lims_xlsx", "tags_xlsx"]) {
      const file = formData.get(name);
      if (!(file instanceof File) || !file.name) {
        elements.uploadError.textContent = "Заполните все обязательные поля.";
        return;
      }
    }
    elements.submitUpload.disabled = true;
    elements.submitUpload.textContent = "Обработка…";
    try {
      const response = await fetch(`${apiBase}/data-upload/evaluate`, {
        method: "POST",
        body: formData,
      });
      const payload = await response.json().catch(() => ({}));
      if (!response.ok) throw new Error(payload.detail || `HTTP ${response.status}`);
      const processing = payload.processing || {};
      lastApiScenario = {
        id: payload.run_id,
        title: "Загруженные тестовые данные",
        short: "Загруженные данные",
        description: `Пользовательские тестовые данные: ${processing.rows ?? "—"} точек, ${processing.timestamp_from ?? "—"} — ${processing.timestamp_to ?? "—"}. ${processing.warnings?.join(" ") || ""}`,
        sourceLabel: "API · пользовательские тестовые данные · HISTORICAL",
        apiResult: true,
        input: payload.assembled_input,
        decision: payload.decision,
      };
      renderScenario(lastApiScenario);
      elements.select.value = "";
      setMode("api");
      elements.uploadDialog.close();
      showToast("Данные обработаны, расчёт выполнен");
    } catch (error) {
      elements.uploadError.textContent = error instanceof Error ? error.message : "Ошибка загрузки.";
    } finally {
      elements.submitUpload.disabled = false;
      elements.submitUpload.textContent = "Обработать и рассчитать";
    }
  }

  async function initializeApi() {
    try {
      await apiJson("/health");
      const [examples, scenarios] = await Promise.all([
        apiJson("/examples"), apiJson("/scenarios"),
      ]);
      apiItems = [
        ...examples.map((item) => ({ id: item.example_id, title: item.title, kind: "example", path: `/examples/${encodeURIComponent(item.example_id)}/evaluate` })),
        ...scenarios.map((item) => ({ id: item.scenario_id, title: item.title, kind: "scenario", path: `/scenarios/${encodeURIComponent(item.scenario_id)}/evaluate` })),
      ];
      elements.apiSelect.innerHTML = apiItems.map((item) => `<option value="${escapeHtml(item.id)}">${escapeHtml(item.title)}</option>`).join("");
      elements.apiSelect.disabled = false;
      elements.apiRun.disabled = false;
      elements.apiSelect.value = "illustrative_blend_20260515_1200";
      await runApiItem(apiItems.find((item) => item.id === elements.apiSelect.value));
    } catch {
      setMode("demo");
    }
  }

  function validateDecision(decision) {
    if (!decision || typeof decision !== "object") throw new Error("Ожидается JSON-объект.");
    if (!["RECOMMEND", "KEEP", "REFUSE"].includes(decision.decision)) {
      throw new Error("Поле decision должно быть RECOMMEND, KEEP или REFUSE.");
    }
    if (!decision.run_id || !decision.schema_version) {
      throw new Error("Нужны поля run_id и schema_version.");
    }
    if (!Array.isArray(decision.reason_codes)) {
      throw new Error("Поле reason_codes должно быть массивом.");
    }
  }

  function applyImport() {
    elements.importError.textContent = "";
    try {
      const parsed = JSON.parse(elements.importTextarea.value);
      const wrapped = parsed.input && parsed.decision ? parsed : { input: {}, decision: parsed };
      validateDecision(wrapped.decision);
      const scenario = {
        id: "imported",
        title: "Импортированный результат",
        short: "Импорт",
        description: "Локально импортированный результат оркестратора.",
        sourceLabel: "Локальный импорт · источник не проверен",
        input: wrapped.input || {},
        decision: wrapped.decision,
      };
      lastDemoScenario = scenario;
      renderScenario(scenario);
      elements.select.value = "";
      setMode("demo");
      elements.importDialog.close();
      showToast("Результат импортирован");
    } catch (error) {
      elements.importError.textContent = error instanceof Error ? error.message : "Ошибка импорта.";
    }
  }

  function registerWebMcpTools() {
    const context = document.modelContext;
    if (!context?.registerTool) return;
    const lifecycle = new AbortController();

    Promise.resolve(
      context.registerTool(
        {
          name: "select_demo_scenario",
          title: "Выбрать демо-сценарий",
          description:
            "Выбирает один из сценариев оркестратора и обновляет видимое решение в консоли.",
          inputSchema: {
            type: "object",
            properties: {
              scenarioId: {
                type: "string",
                enum: dataset.scenarios.map((scenario) => scenario.id),
              },
            },
            required: ["scenarioId"],
            additionalProperties: false,
          },
          annotations: { readOnlyHint: false, untrustedContentHint: false },
          execute(input) {
            const scenario = dataset.scenarios.find((item) => item.id === input?.scenarioId);
            if (!scenario) throw new Error("Неизвестный scenarioId.");
            lastDemoScenario = scenario;
            elements.select.value = scenario.id;
            renderScenario(scenario);
            setMode("demo");
            return {
              scenarioId: scenario.id,
              decision: scenario.decision.decision,
              runId: scenario.decision.run_id,
            };
          },
        },
        { signal: lifecycle.signal },
      ),
    ).catch(() => {});

    Promise.resolve(
      context.registerTool(
        {
          name: "read_current_decision",
          title: "Прочитать текущее решение",
          description: "Возвращает решение, открытое сейчас в операторской консоли.",
          inputSchema: { type: "object", properties: {}, additionalProperties: false },
          annotations: { readOnlyHint: true, untrustedContentHint: false },
          execute() {
            return {
              scenarioId: currentScenario.id,
              decision: currentScenario.decision,
            };
          },
        },
        { signal: lifecycle.signal },
      ),
    ).catch(() => {});
  }

  initializeSelect();
  elements.select.value = currentScenario.id;
  renderScenario(currentScenario);

  elements.select.addEventListener("change", () => {
    const selected = dataset.scenarios.find((scenario) => scenario.id === elements.select.value);
    if (selected) {
      lastDemoScenario = selected;
      renderScenario(selected);
    }
  });
  elements.modeApi.addEventListener("click", showApiMode);
  elements.modeDemo.addEventListener("click", showDemoMode);
  elements.apiRun.addEventListener("click", () => {
    const item = apiItems.find((candidate) => candidate.id === elements.apiSelect.value);
    if (item) runApiItem(item);
  });
  elements.uploadButton.addEventListener("click", () => {
    elements.uploadError.textContent = "";
    elements.uploadForm.reset();
    elements.uploadDialog.showModal();
  });
  elements.closeUpload.addEventListener("click", () => elements.uploadDialog.close());
  elements.cancelUpload.addEventListener("click", () => elements.uploadDialog.close());
  elements.uploadForm.addEventListener("submit", uploadTestData);

  elements.traceToggle.addEventListener("click", () => {
    const next = elements.traceJson.hidden;
    elements.traceJson.hidden = !next;
    elements.traceToggle.setAttribute("aria-expanded", String(next));
    elements.traceToggle.textContent = next ? "Скрыть JSON" : "Показать JSON";
  });

  elements.copyButton.addEventListener("click", async () => {
    try {
      await navigator.clipboard.writeText(JSON.stringify(currentScenario.decision, null, 2));
      showToast("Решение скопировано");
    } catch {
      showToast("Не удалось скопировать");
    }
  });

  elements.importButton.addEventListener("click", () => {
    elements.importError.textContent = "";
    elements.importTextarea.value = "";
    elements.importDialog.showModal();
  });
  elements.applyImport.addEventListener("click", applyImport);

  registerWebMcpTools();
  initializeApi();
})();
