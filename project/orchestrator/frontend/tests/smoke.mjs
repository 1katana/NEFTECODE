import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import vm from "node:vm";

const root = new URL("../dist/", import.meta.url);
const [html, css, app, dataSource] = await Promise.all([
  readFile(new URL("index.html", root), "utf8"),
  readFile(new URL("styles.css", root), "utf8"),
  readFile(new URL("app.js", root), "utf8"),
  readFile(new URL("data/scenarios.js", root), "utf8"),
]);

assert.match(html, /<main class="workspace">/);
assert.match(html, /id="decision-panel"/);
assert.match(html, /id="scenario-select"/);
assert.match(html, /id="api-select"/);
assert.match(html, /id="upload-test-data"/);
assert.match(html, /id="upload-dialog"/);
assert.match(html, /name="avt_tags"/);
assert.match(html, /name="hydro_tags"/);
assert.match(html, /name="lims_xlsx"/);
assert.match(html, /name="tags_xlsx"/);
assert.match(html, /id="active-source"/);
assert.match(html, /id="mode-api"/);
assert.match(html, /id="mode-demo"/);
assert.match(html, /id="decision-next-step"/);
assert.match(html, /id="decision-pictogram"/);
assert.doesNotMatch(html, /id="decision-title"/);
assert.match(html, /Технические причины решения/);
assert.doesNotMatch(html, /Контур принятия решений|Запрос к Integration API|Контрактный пример интерфейса/);
assert.match(html, /rel="icon"/);
assert.match(css, /@media \(max-width: 760px\)/);
assert.match(app, /select_demo_scenario/);
assert.match(app, /read_current_decision/);
assert.match(app, /\/examples/);
assert.match(app, /\/scenarios/);
assert.match(app, /\/data-upload\/evaluate/);
assert.match(app, /uploadTestData/);
assert.match(app, /apiResult: true/);
assert.match(app, /showDemoMode/);
assert.match(app, /lastApiScenario/);
assert.match(app, /assets\/decision-keep\.png/);
assert.doesNotMatch(app, /Сохранить режим|Изменение не рекомендовано|Изменить режим/);

const sandbox = { window: {} };
vm.runInNewContext(dataSource, sandbox);
const data = sandbox.window.ORCHESTRATOR_SCENARIOS;
assert.equal(data.schema_version, "1.0.0");
assert.equal(data.scenarios.length, 8);
assert.deepEqual(
  [...new Set(data.scenarios.slice(0, 3).map((scenario) => scenario.decision.decision))].sort(),
  ["KEEP", "RECOMMEND", "REFUSE"],
);
for (const scenario of data.scenarios) {
  assert.equal(scenario.input.run_id, scenario.decision.run_id);
  assert.ok(scenario.decision.trace_id);
  assert.ok(scenario.decision.explanation);
}

console.log("Frontend smoke test passed: 8 scenarios, 3 decision types.");
