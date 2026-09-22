__all__ = [
    "CandidateAction",
    "ProcessState",
    "QualityAgent",
    "QualityAgentRouter",
    "QualityAssessment",
    "RuntimeConfig",
    "ShadowLogger",
    "ShadowPromotionGates",
]
__version__ = "0.1.0"


def __getattr__(name: str):
    """Keep data-preparation imports independent from optional ML binaries."""
    if name == "QualityAgent":
        from .agent import QualityAgent

        return QualityAgent
    if name == "QualityAgentRouter":
        from .router import QualityAgentRouter

        return QualityAgentRouter
    if name in {"ShadowLogger", "ShadowPromotionGates"}:
        from .shadow import ShadowLogger, ShadowPromotionGates

        return {
            "ShadowLogger": ShadowLogger,
            "ShadowPromotionGates": ShadowPromotionGates,
        }[name]
    if name == "RuntimeConfig":
        from .runtime import RuntimeConfig

        return RuntimeConfig
    if name in {"ProcessState", "CandidateAction", "QualityAssessment"}:
        from .contracts import CandidateAction, ProcessState, QualityAssessment

        return {
            "ProcessState": ProcessState,
            "CandidateAction": CandidateAction,
            "QualityAssessment": QualityAssessment,
        }[name]
    raise AttributeError(name)
