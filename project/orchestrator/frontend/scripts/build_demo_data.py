from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path


FRONTEND_DIR = Path(__file__).resolve().parents[1]
ORCHESTRATOR_DIR = FRONTEND_DIR.parent
SRC_DIR = ORCHESTRATOR_DIR / "src"
EXAMPLES_DIR = ORCHESTRATOR_DIR / "examples"
OUTPUT_FILE = FRONTEND_DIR / "dist" / "data" / "scenarios.js"

sys.path.insert(0, str(SRC_DIR))

from neftecode_orchestrator.service import OrchestratorService  # noqa: E402


SCENARIO_META = {
    "recommend.json": {
        "title": "Рекомендация",
        "short": "Риск серы",
        "description": "Текущий режим нарушает лимит, безопасная альтернатива найдена.",
        "group": "Основные",
    },
    "keep.json": {
        "title": "Сохранить режим",
        "short": "Нормальный режим",
        "description": "Текущие показатели безопасны, изменение не требуется.",
        "group": "Основные",
    },
    "refuse.json": {
        "title": "Отказ",
        "short": "Нет решения",
        "description": "Режим небезопасен, допустимых альтернатив нет.",
        "group": "Основные",
    },
    "keep-ranked-no-change.json": {
        "title": "Сохранить: NO_CHANGE",
        "short": "NO_CHANGE первый",
        "description": "Оптимизатор поставил сценарий без изменений на первое место.",
        "group": "Граничные",
    },
    "keep-medium-confidence.json": {
        "title": "Сохранить: средняя уверенность",
        "short": "Средняя уверенность",
        "description": "Данных достаточно для сохранения, но недостаточно для изменения режима.",
        "group": "Граничные",
    },
    "refuse-low-confidence.json": {
        "title": "Отказ: низкая уверенность",
        "short": "Низкая уверенность",
        "description": "Оркестратор закрывает контур из-за низкого доверия к данным.",
        "group": "Ошибки",
    },
    "refuse-missing-quality.json": {
        "title": "Отказ: нет прогноза",
        "short": "Нет QualityAssessment",
        "description": "QualityAgent не вернул обязательные поля прогноза.",
        "group": "Ошибки",
    },
    "refuse-quality-timeout.json": {
        "title": "Отказ: таймаут",
        "short": "Таймаут QualityAgent",
        "description": "Компонент качества не ответил вовремя.",
        "group": "Ошибки",
    },
}


def build() -> dict[str, object]:
    service = OrchestratorService()
    scenarios: list[dict[str, object]] = []

    for filename, meta in SCENARIO_META.items():
        payload = json.loads((EXAMPLES_DIR / filename).read_text(encoding="utf-8"))
        decision = service.decide_payload(payload).model_dump(mode="json")
        scenarios.append(
            {
                "id": Path(filename).stem,
                **meta,
                "input": payload,
                "decision": decision,
            }
        )

    return {
        "schema_version": "1.0.0",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "scenarios": scenarios,
    }


def main() -> None:
    OUTPUT_FILE.parent.mkdir(parents=True, exist_ok=True)
    data = json.dumps(build(), ensure_ascii=False, indent=2)
    OUTPUT_FILE.write_text(f"window.ORCHESTRATOR_SCENARIOS = {data};\n", encoding="utf-8")
    print(f"Generated {OUTPUT_FILE.relative_to(ORCHESTRATOR_DIR)}")


if __name__ == "__main__":
    main()
