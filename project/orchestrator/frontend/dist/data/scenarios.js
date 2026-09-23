window.ORCHESTRATOR_SCENARIOS = {
  "schema_version": "1.0.0",
  "generated_at": "2026-09-18T11:13:43.245648+00:00",
  "scenarios": [
    {
      "id": "recommend",
      "title": "Рекомендация",
      "short": "Риск серы",
      "description": "Текущий режим нарушает лимит, безопасная альтернатива найдена.",
      "group": "Основные",
      "input": {
        "schema_version": "1.0.0",
        "run_id": "demo-recommend-001",
        "process_state": {
          "timestamp": "2026-07-10T12:00:00Z",
          "quality": {
            "mg_sulfur": 11.2,
            "source": "pak"
          },
          "telemetry": {
            "hyd_t5": 342.0,
            "hyd_f26": 102.0
          },
          "data_quality": {
            "missing": [],
            "stale": [],
            "outlier": []
          },
          "data_confidence": "HIGH",
          "current_controls": {
            "hyd_t5": 342.0,
            "hyd_f26": 102.0
          }
        },
        "current_quality": {
          "status": "OK",
          "data": {
            "quality_prediction": 11.2,
            "prediction_lower": 10.4,
            "prediction_upper": 12.0,
            "violation_probability": 0.68,
            "data_confidence": "HIGH",
            "warnings": []
          },
          "error_code": null,
          "message": null,
          "latency_ms": 12
        },
        "current_reliability": {
          "status": "OK",
          "data": {
            "reliability_risk": "MEDIUM",
            "risk_score": 0.45,
            "data_confidence": "HIGH",
            "warnings": [],
            "risk_factors": [
              "MODE_NEAR_QUALITY_LIMIT"
            ]
          },
          "error_code": null,
          "message": null,
          "latency_ms": 12
        },
        "current_safety": {
          "status": "OK",
          "data": {
            "constraint_passed": false,
            "violations": [
              "SULFUR_LIMIT"
            ],
            "rejection_reason": "SULFUR_LIMIT"
          },
          "error_code": null,
          "message": null,
          "latency_ms": 12
        },
        "scenarios": [
          {
            "candidate": {
              "candidate_id": "CANDIDATE_001",
              "changes": {
                "hyd_t5": 345.0,
                "hyd_f26": 99.0
              },
              "delta": {
                "hyd_t5": 3.0,
                "hyd_f26": -3.0
              }
            },
            "quality_prediction": 8.8,
            "violation_probability": 0.09,
            "reliability_risk": "LOW",
            "constraint_passed": true,
            "violations": [],
            "score": 0.82
          }
        ],
        "optimization": {
          "status": "OK",
          "data": {
            "status": "SUCCESS",
            "ranked_candidates": [
              {
                "rank": 1,
                "score": 0.82,
                "score_components": {
                  "quality": 0.55,
                  "reliability": 0.2,
                  "change_penalty": -0.07
                },
                "candidate": {
                  "candidate_id": "CANDIDATE_001",
                  "changes": {
                    "hyd_t5": 345.0,
                    "hyd_f26": 99.0
                  },
                  "delta": {
                    "hyd_t5": 3.0,
                    "hyd_f26": -3.0
                  }
                }
              }
            ],
            "reasons": []
          },
          "error_code": null,
          "message": null,
          "latency_ms": 12
        }
      },
      "decision": {
        "schema_version": "1.0.0",
        "run_id": "demo-recommend-001",
        "timestamp": "2026-07-10T12:00:00Z",
        "decision": "RECOMMEND",
        "reason_codes": [
          "RECOMMEND_TOP_RANKED_SAFE_CANDIDATE"
        ],
        "selected_candidate": {
          "candidate_id": "CANDIDATE_001",
          "changes": {
            "hyd_t5": 345.0,
            "hyd_f26": 99.0
          },
          "delta": {
            "hyd_t5": 3.0,
            "hyd_f26": -3.0
          }
        },
        "current_state_summary": {
          "quality_prediction": 11.2,
          "violation_probability": 0.68,
          "reliability_risk": "MEDIUM",
          "risk_score": 0.45,
          "constraint_passed": false
        },
        "predicted_result": {
          "quality_prediction": 8.8,
          "violation_probability": 0.09,
          "reliability_risk": "LOW",
          "constraint_passed": true,
          "score": 0.82
        },
        "warnings": [],
        "explanation": "Рекомендован сценарий CANDIDATE_001: hyd_t5=345, hyd_f26=99. Прогноз качества — 8.8, вероятность нарушения — 9.0%. Сценарий прошёл Safety и занимает первое место в ranking оптимизатора.",
        "trace_id": "ea17b6c9-19d2-40b1-8d1a-a04973cce84d"
      }
    },
    {
      "id": "keep",
      "title": "Сохранить режим",
      "short": "Нормальный режим",
      "description": "Текущие показатели безопасны, изменение не требуется.",
      "group": "Основные",
      "input": {
        "schema_version": "1.0.0",
        "run_id": "demo-keep-001",
        "process_state": {
          "timestamp": "2026-07-10T12:00:00Z",
          "quality": {
            "mg_sulfur": 6.7,
            "source": "lims"
          },
          "telemetry": {
            "hyd_t5": 342.0,
            "hyd_f26": 102.0
          },
          "data_quality": {
            "missing": [],
            "stale": [],
            "outlier": []
          },
          "data_confidence": "HIGH",
          "current_controls": {
            "hyd_t5": 342.0,
            "hyd_f26": 102.0
          }
        },
        "current_quality": {
          "status": "OK",
          "data": {
            "quality_prediction": 6.7,
            "prediction_lower": 6.2,
            "prediction_upper": 7.3,
            "violation_probability": 0.02,
            "data_confidence": "HIGH",
            "warnings": []
          },
          "error_code": null,
          "message": null,
          "latency_ms": 12
        },
        "current_reliability": {
          "status": "OK",
          "data": {
            "reliability_risk": "LOW",
            "risk_score": 0.12,
            "data_confidence": "HIGH",
            "warnings": [],
            "risk_factors": []
          },
          "error_code": null,
          "message": null,
          "latency_ms": 12
        },
        "current_safety": {
          "status": "OK",
          "data": {
            "constraint_passed": true,
            "violations": [],
            "rejection_reason": null
          },
          "error_code": null,
          "message": null,
          "latency_ms": 12
        },
        "scenarios": [],
        "optimization": {
          "status": "OK",
          "data": {
            "status": "NO_FEASIBLE_SOLUTION",
            "ranked_candidates": [],
            "reasons": [
              "NO_BETTER_SAFE_ACTION"
            ]
          },
          "error_code": null,
          "message": null,
          "latency_ms": 12
        }
      },
      "decision": {
        "schema_version": "1.0.0",
        "run_id": "demo-keep-001",
        "timestamp": "2026-07-10T12:00:00Z",
        "decision": "KEEP",
        "reason_codes": [
          "KEEP_CURRENT_MODE_SAFE",
          "KEEP_NO_FEASIBLE_CHANGE"
        ],
        "selected_candidate": null,
        "current_state_summary": {
          "quality_prediction": 6.7,
          "violation_probability": 0.02,
          "reliability_risk": "LOW",
          "risk_score": 0.12,
          "constraint_passed": true
        },
        "predicted_result": null,
        "warnings": [],
        "explanation": "Режим оставлен без изменений: текущий режим прошёл проверку безопасности; допустимых изменений режима не найдено.",
        "trace_id": "5a1a4e71-568f-478d-ac26-56fd8fc3b3ff"
      }
    },
    {
      "id": "refuse",
      "title": "Отказ",
      "short": "Нет решения",
      "description": "Режим небезопасен, допустимых альтернатив нет.",
      "group": "Основные",
      "input": {
        "schema_version": "1.0.0",
        "run_id": "demo-refuse-001",
        "process_state": {
          "timestamp": "2026-07-10T12:00:00Z",
          "quality": {
            "mg_sulfur": 11.2,
            "source": "pak"
          },
          "telemetry": {
            "hyd_t5": 342.0,
            "hyd_f26": 102.0
          },
          "data_quality": {
            "missing": [],
            "stale": [],
            "outlier": []
          },
          "data_confidence": "HIGH",
          "current_controls": {
            "hyd_t5": 342.0,
            "hyd_f26": 102.0
          }
        },
        "current_quality": {
          "status": "OK",
          "data": {
            "quality_prediction": 11.2,
            "prediction_lower": 10.4,
            "prediction_upper": 12.0,
            "violation_probability": 0.68,
            "data_confidence": "HIGH",
            "warnings": []
          },
          "error_code": null,
          "message": null,
          "latency_ms": 12
        },
        "current_reliability": {
          "status": "OK",
          "data": {
            "reliability_risk": "HIGH",
            "risk_score": 0.91,
            "data_confidence": "HIGH",
            "warnings": [],
            "risk_factors": [
              "MODE_NEAR_QUALITY_LIMIT"
            ]
          },
          "error_code": null,
          "message": null,
          "latency_ms": 12
        },
        "current_safety": {
          "status": "OK",
          "data": {
            "constraint_passed": false,
            "violations": [
              "SULFUR_LIMIT",
              "RELIABILITY_LIMIT"
            ],
            "rejection_reason": "SULFUR_LIMIT, RELIABILITY_LIMIT"
          },
          "error_code": null,
          "message": null,
          "latency_ms": 12
        },
        "scenarios": [],
        "optimization": {
          "status": "OK",
          "data": {
            "status": "NO_FEASIBLE_SOLUTION",
            "ranked_candidates": [],
            "reasons": [
              "ALL_CANDIDATES_REJECTED"
            ]
          },
          "error_code": null,
          "message": null,
          "latency_ms": 12
        }
      },
      "decision": {
        "schema_version": "1.0.0",
        "run_id": "demo-refuse-001",
        "timestamp": "2026-07-10T12:00:00Z",
        "decision": "REFUSE",
        "reason_codes": [
          "REFUSE_CURRENT_UNSAFE_NO_FEASIBLE"
        ],
        "selected_candidate": null,
        "current_state_summary": {
          "quality_prediction": 11.2,
          "violation_probability": 0.68,
          "reliability_risk": "HIGH",
          "risk_score": 0.91,
          "constraint_passed": false
        },
        "predicted_result": null,
        "warnings": [],
        "explanation": "Надёжная рекомендация не сформирована: текущий режим небезопасен, а допустимых альтернатив не найдено.",
        "trace_id": "dfc3f6d1-2dee-48b9-8da1-d32c6ec4fc9a"
      }
    },
    {
      "id": "keep-ranked-no-change",
      "title": "Сохранить: NO_CHANGE",
      "short": "NO_CHANGE первый",
      "description": "Оптимизатор поставил сценарий без изменений на первое место.",
      "group": "Граничные",
      "input": {
        "schema_version": "1.0.0",
        "run_id": "demo-no-change-001",
        "process_state": {
          "timestamp": "2026-07-10T12:00:00Z",
          "quality": {
            "mg_sulfur": 6.7,
            "source": "lims"
          },
          "telemetry": {
            "hyd_t5": 342.0,
            "hyd_f26": 102.0
          },
          "data_quality": {
            "missing": [],
            "stale": [],
            "outlier": []
          },
          "data_confidence": "HIGH",
          "current_controls": {
            "hyd_t5": 342.0,
            "hyd_f26": 102.0
          }
        },
        "current_quality": {
          "status": "OK",
          "data": {
            "quality_prediction": 6.7,
            "prediction_lower": 6.2,
            "prediction_upper": 7.3,
            "violation_probability": 0.02,
            "data_confidence": "HIGH",
            "warnings": []
          },
          "error_code": null,
          "message": null,
          "latency_ms": 12
        },
        "current_reliability": {
          "status": "OK",
          "data": {
            "reliability_risk": "LOW",
            "risk_score": 0.12,
            "data_confidence": "HIGH",
            "warnings": [],
            "risk_factors": []
          },
          "error_code": null,
          "message": null,
          "latency_ms": 12
        },
        "current_safety": {
          "status": "OK",
          "data": {
            "constraint_passed": true,
            "violations": [],
            "rejection_reason": null
          },
          "error_code": null,
          "message": null,
          "latency_ms": 12
        },
        "scenarios": [
          {
            "candidate": {
              "candidate_id": "NO_CHANGE",
              "changes": {},
              "delta": {}
            },
            "quality_prediction": 6.7,
            "violation_probability": 0.02,
            "reliability_risk": "LOW",
            "constraint_passed": true,
            "violations": [],
            "score": 0.91
          }
        ],
        "optimization": {
          "status": "OK",
          "data": {
            "status": "SUCCESS",
            "ranked_candidates": [
              {
                "rank": 1,
                "score": 0.91,
                "score_components": {
                  "quality": 0.7,
                  "reliability": 0.21
                },
                "candidate": {
                  "candidate_id": "NO_CHANGE",
                  "changes": {},
                  "delta": {}
                }
              }
            ],
            "reasons": [
              "NO_CHANGE_IS_BEST"
            ]
          },
          "error_code": null,
          "message": null,
          "latency_ms": 12
        }
      },
      "decision": {
        "schema_version": "1.0.0",
        "run_id": "demo-no-change-001",
        "timestamp": "2026-07-10T12:00:00Z",
        "decision": "KEEP",
        "reason_codes": [
          "KEEP_CURRENT_MODE_SAFE",
          "KEEP_TOP_CANDIDATE_IS_NO_CHANGE"
        ],
        "selected_candidate": null,
        "current_state_summary": {
          "quality_prediction": 6.7,
          "violation_probability": 0.02,
          "reliability_risk": "LOW",
          "risk_score": 0.12,
          "constraint_passed": true
        },
        "predicted_result": null,
        "warnings": [],
        "explanation": "Режим оставлен без изменений: текущий режим прошёл проверку безопасности; лучшим вариантом признано сохранение текущего режима.",
        "trace_id": "fcddd2c5-e074-4395-bfbd-625c6e9d3b1f"
      }
    },
    {
      "id": "keep-medium-confidence",
      "title": "Сохранить: средняя уверенность",
      "short": "Средняя уверенность",
      "description": "Данных достаточно для сохранения, но недостаточно для изменения режима.",
      "group": "Граничные",
      "input": {
        "schema_version": "1.0.0",
        "run_id": "demo-medium-confidence-001",
        "process_state": {
          "timestamp": "2026-07-10T12:00:00Z",
          "quality": {
            "mg_sulfur": 8.9,
            "source": "pak"
          },
          "telemetry": {
            "hyd_t5": 342.0,
            "hyd_f26": 102.0
          },
          "data_quality": {
            "missing": [],
            "stale": [],
            "outlier": []
          },
          "data_confidence": "HIGH",
          "current_controls": {
            "hyd_t5": 342.0,
            "hyd_f26": 102.0
          }
        },
        "current_quality": {
          "status": "OK",
          "data": {
            "quality_prediction": 11.2,
            "prediction_lower": 10.4,
            "prediction_upper": 12.0,
            "violation_probability": 0.68,
            "data_confidence": "MEDIUM",
            "warnings": []
          },
          "error_code": null,
          "message": null,
          "latency_ms": 12
        },
        "current_reliability": {
          "status": "OK",
          "data": {
            "reliability_risk": "MEDIUM",
            "risk_score": 0.45,
            "data_confidence": "HIGH",
            "warnings": [],
            "risk_factors": [
              "MODE_NEAR_QUALITY_LIMIT"
            ]
          },
          "error_code": null,
          "message": null,
          "latency_ms": 12
        },
        "current_safety": {
          "status": "OK",
          "data": {
            "constraint_passed": true,
            "violations": [],
            "rejection_reason": null
          },
          "error_code": null,
          "message": null,
          "latency_ms": 12
        },
        "scenarios": [
          {
            "candidate": {
              "candidate_id": "CANDIDATE_001",
              "changes": {
                "hyd_t5": 345.0,
                "hyd_f26": 99.0
              },
              "delta": {
                "hyd_t5": 3.0,
                "hyd_f26": -3.0
              }
            },
            "quality_prediction": 8.8,
            "violation_probability": 0.09,
            "reliability_risk": "LOW",
            "constraint_passed": true,
            "violations": [],
            "score": 0.82
          }
        ],
        "optimization": {
          "status": "OK",
          "data": {
            "status": "SUCCESS",
            "ranked_candidates": [
              {
                "rank": 1,
                "score": 0.82,
                "score_components": {
                  "quality": 0.55,
                  "reliability": 0.2,
                  "change_penalty": -0.07
                },
                "candidate": {
                  "candidate_id": "CANDIDATE_001",
                  "changes": {
                    "hyd_t5": 345.0,
                    "hyd_f26": 99.0
                  },
                  "delta": {
                    "hyd_t5": 3.0,
                    "hyd_f26": -3.0
                  }
                }
              }
            ],
            "reasons": []
          },
          "error_code": null,
          "message": null,
          "latency_ms": 12
        }
      },
      "decision": {
        "schema_version": "1.0.0",
        "run_id": "demo-medium-confidence-001",
        "timestamp": "2026-07-10T12:00:00Z",
        "decision": "KEEP",
        "reason_codes": [
          "KEEP_CURRENT_MODE_SAFE",
          "KEEP_CONFIDENCE_BELOW_RECOMMENDATION"
        ],
        "selected_candidate": null,
        "current_state_summary": {
          "quality_prediction": 11.2,
          "violation_probability": 0.68,
          "reliability_risk": "MEDIUM",
          "risk_score": 0.45,
          "constraint_passed": true
        },
        "predicted_result": null,
        "warnings": [],
        "explanation": "Режим оставлен без изменений: текущий режим прошёл проверку безопасности; уверенности достаточно для сохранения режима, но недостаточно для изменения.",
        "trace_id": "f939e8d0-e303-4d3e-8008-da4c2e4c1c89"
      }
    },
    {
      "id": "refuse-low-confidence",
      "title": "Отказ: низкая уверенность",
      "short": "Низкая уверенность",
      "description": "Оркестратор закрывает контур из-за низкого доверия к данным.",
      "group": "Ошибки",
      "input": {
        "schema_version": "1.0.0",
        "run_id": "demo-low-confidence-001",
        "process_state": {
          "timestamp": "2026-07-10T12:00:00Z",
          "quality": {
            "mg_sulfur": 6.7,
            "source": "lims"
          },
          "telemetry": {
            "hyd_t5": 342.0,
            "hyd_f26": 102.0
          },
          "data_quality": {
            "missing": [],
            "stale": [],
            "outlier": []
          },
          "data_confidence": "LOW",
          "current_controls": {
            "hyd_t5": 342.0,
            "hyd_f26": 102.0
          }
        },
        "current_quality": {
          "status": "OK",
          "data": {
            "quality_prediction": 6.7,
            "prediction_lower": 6.2,
            "prediction_upper": 7.3,
            "violation_probability": 0.02,
            "data_confidence": "HIGH",
            "warnings": []
          },
          "error_code": null,
          "message": null,
          "latency_ms": 12
        },
        "current_reliability": {
          "status": "OK",
          "data": {
            "reliability_risk": "LOW",
            "risk_score": 0.12,
            "data_confidence": "HIGH",
            "warnings": [],
            "risk_factors": []
          },
          "error_code": null,
          "message": null,
          "latency_ms": 12
        },
        "current_safety": {
          "status": "OK",
          "data": {
            "constraint_passed": true,
            "violations": [],
            "rejection_reason": null
          },
          "error_code": null,
          "message": null,
          "latency_ms": 12
        },
        "scenarios": [],
        "optimization": {
          "status": "OK",
          "data": {
            "status": "NO_FEASIBLE_SOLUTION",
            "ranked_candidates": [],
            "reasons": [
              "NO_BETTER_SAFE_ACTION"
            ]
          },
          "error_code": null,
          "message": null,
          "latency_ms": 12
        }
      },
      "decision": {
        "schema_version": "1.0.0",
        "run_id": "demo-low-confidence-001",
        "timestamp": "2026-07-10T12:00:00Z",
        "decision": "REFUSE",
        "reason_codes": [
          "REFUSE_LOW_DATA_CONFIDENCE"
        ],
        "selected_candidate": null,
        "current_state_summary": {
          "quality_prediction": 6.7,
          "violation_probability": 0.02,
          "reliability_risk": "LOW",
          "risk_score": 0.12,
          "constraint_passed": true
        },
        "predicted_result": null,
        "warnings": [],
        "explanation": "Надёжная рекомендация не сформирована: доверие к входным данным недостаточно.",
        "trace_id": "e68a3eae-1137-4c76-a9e9-f0ae826fdaec"
      }
    },
    {
      "id": "refuse-missing-quality",
      "title": "Отказ: нет прогноза",
      "short": "Нет QualityAssessment",
      "description": "QualityAgent не вернул обязательные поля прогноза.",
      "group": "Ошибки",
      "input": {
        "schema_version": "1.0.0",
        "run_id": "demo-missing-quality-001",
        "process_state": {
          "timestamp": "2026-07-10T12:00:00Z",
          "quality": {
            "mg_sulfur": 11.2,
            "source": "pak"
          },
          "telemetry": {
            "hyd_t5": 342.0,
            "hyd_f26": 102.0
          },
          "data_quality": {
            "missing": [],
            "stale": [],
            "outlier": []
          },
          "data_confidence": "HIGH",
          "current_controls": {
            "hyd_t5": 342.0,
            "hyd_f26": 102.0
          }
        },
        "current_quality": {
          "status": "OK",
          "data": {
            "quality_prediction": null,
            "prediction_lower": null,
            "prediction_upper": null,
            "violation_probability": null,
            "data_confidence": "HIGH",
            "warnings": [
              "MODEL_DID_NOT_RETURN_PREDICTION"
            ]
          },
          "error_code": null,
          "message": null,
          "latency_ms": 12
        },
        "current_reliability": {
          "status": "OK",
          "data": {
            "reliability_risk": "MEDIUM",
            "risk_score": 0.45,
            "data_confidence": "HIGH",
            "warnings": [],
            "risk_factors": [
              "MODE_NEAR_QUALITY_LIMIT"
            ]
          },
          "error_code": null,
          "message": null,
          "latency_ms": 12
        },
        "current_safety": {
          "status": "OK",
          "data": {
            "constraint_passed": false,
            "violations": [
              "SULFUR_LIMIT"
            ],
            "rejection_reason": "SULFUR_LIMIT"
          },
          "error_code": null,
          "message": null,
          "latency_ms": 12
        },
        "scenarios": [
          {
            "candidate": {
              "candidate_id": "CANDIDATE_001",
              "changes": {
                "hyd_t5": 345.0,
                "hyd_f26": 99.0
              },
              "delta": {
                "hyd_t5": 3.0,
                "hyd_f26": -3.0
              }
            },
            "quality_prediction": 8.8,
            "violation_probability": 0.09,
            "reliability_risk": "LOW",
            "constraint_passed": true,
            "violations": [],
            "score": 0.82
          }
        ],
        "optimization": {
          "status": "OK",
          "data": {
            "status": "SUCCESS",
            "ranked_candidates": [
              {
                "rank": 1,
                "score": 0.82,
                "score_components": {
                  "quality": 0.55,
                  "reliability": 0.2,
                  "change_penalty": -0.07
                },
                "candidate": {
                  "candidate_id": "CANDIDATE_001",
                  "changes": {
                    "hyd_t5": 345.0,
                    "hyd_f26": 99.0
                  },
                  "delta": {
                    "hyd_t5": 3.0,
                    "hyd_f26": -3.0
                  }
                }
              }
            ],
            "reasons": []
          },
          "error_code": null,
          "message": null,
          "latency_ms": 12
        }
      },
      "decision": {
        "schema_version": "1.0.0",
        "run_id": "demo-missing-quality-001",
        "timestamp": "2026-07-10T12:00:00Z",
        "decision": "REFUSE",
        "reason_codes": [
          "REFUSE_REQUIRED_QUALITY_MISSING"
        ],
        "selected_candidate": null,
        "current_state_summary": {
          "quality_prediction": null,
          "violation_probability": null,
          "reliability_risk": "MEDIUM",
          "risk_score": 0.45,
          "constraint_passed": false
        },
        "predicted_result": null,
        "warnings": [
          "MODEL_DID_NOT_RETURN_PREDICTION"
        ],
        "explanation": "Надёжная рекомендация не сформирована: агент качества не вернул обязательный прогноз или вероятность нарушения.",
        "trace_id": "929f7419-757f-48dd-b073-ef9af0eb9b34"
      }
    },
    {
      "id": "refuse-quality-timeout",
      "title": "Отказ: таймаут",
      "short": "Таймаут QualityAgent",
      "description": "Компонент качества не ответил вовремя.",
      "group": "Ошибки",
      "input": {
        "schema_version": "1.0.0",
        "run_id": "demo-quality-timeout-001",
        "process_state": {
          "timestamp": "2026-07-10T12:00:00Z",
          "quality": {
            "mg_sulfur": 11.2,
            "source": "pak"
          },
          "telemetry": {
            "hyd_t5": 342.0,
            "hyd_f26": 102.0
          },
          "data_quality": {
            "missing": [],
            "stale": [],
            "outlier": []
          },
          "data_confidence": "HIGH",
          "current_controls": {
            "hyd_t5": 342.0,
            "hyd_f26": 102.0
          }
        },
        "current_quality": {
          "status": "TIMEOUT",
          "data": null,
          "error_code": "QUALITY_TIMEOUT",
          "message": "QualityAgent did not respond within the configured timeout",
          "latency_ms": 2000
        },
        "current_reliability": {
          "status": "OK",
          "data": {
            "reliability_risk": "MEDIUM",
            "risk_score": 0.45,
            "data_confidence": "HIGH",
            "warnings": [],
            "risk_factors": [
              "MODE_NEAR_QUALITY_LIMIT"
            ]
          },
          "error_code": null,
          "message": null,
          "latency_ms": 12
        },
        "current_safety": {
          "status": "OK",
          "data": {
            "constraint_passed": false,
            "violations": [
              "SULFUR_LIMIT"
            ],
            "rejection_reason": "SULFUR_LIMIT"
          },
          "error_code": null,
          "message": null,
          "latency_ms": 12
        },
        "scenarios": [
          {
            "candidate": {
              "candidate_id": "CANDIDATE_001",
              "changes": {
                "hyd_t5": 345.0,
                "hyd_f26": 99.0
              },
              "delta": {
                "hyd_t5": 3.0,
                "hyd_f26": -3.0
              }
            },
            "quality_prediction": 8.8,
            "violation_probability": 0.09,
            "reliability_risk": "LOW",
            "constraint_passed": true,
            "violations": [],
            "score": 0.82
          }
        ],
        "optimization": {
          "status": "OK",
          "data": {
            "status": "SUCCESS",
            "ranked_candidates": [
              {
                "rank": 1,
                "score": 0.82,
                "score_components": {
                  "quality": 0.55,
                  "reliability": 0.2,
                  "change_penalty": -0.07
                },
                "candidate": {
                  "candidate_id": "CANDIDATE_001",
                  "changes": {
                    "hyd_t5": 345.0,
                    "hyd_f26": 99.0
                  },
                  "delta": {
                    "hyd_t5": 3.0,
                    "hyd_f26": -3.0
                  }
                }
              }
            ],
            "reasons": []
          },
          "error_code": null,
          "message": null,
          "latency_ms": 12
        }
      },
      "decision": {
        "schema_version": "1.0.0",
        "run_id": "demo-quality-timeout-001",
        "timestamp": "2026-07-10T12:00:00Z",
        "decision": "REFUSE",
        "reason_codes": [
          "REFUSE_COMPONENT_TIMEOUT:quality"
        ],
        "selected_candidate": null,
        "current_state_summary": {
          "quality_prediction": null,
          "violation_probability": null,
          "reliability_risk": "MEDIUM",
          "risk_score": 0.45,
          "constraint_passed": false
        },
        "predicted_result": null,
        "warnings": [
          "QualityAgent did not respond within the configured timeout"
        ],
        "explanation": "Надёжная рекомендация не сформирована: компонент quality не ответил вовремя.",
        "trace_id": "dbfe741d-47b9-4618-a2d7-3cdfb9cc6d4f"
      }
    }
  ]
};
