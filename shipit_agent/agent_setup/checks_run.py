"""AgentDoctor checks for iteration limits and efficiency, and provider details."""

from __future__ import annotations

from typing import Any

from .doctor_types import DoctorCheck


class _RunChecks:
    """AgentDoctor checks for iteration limits and efficiency, and provider details."""

    def _check_iterations(self, agent: Any) -> DoctorCheck:
        if getattr(agent, "max_iterations", None) is None:
            budget = getattr(agent, "max_budget_usd", None)
            return DoctorCheck(
                name="runtime_limits",
                status="pass",
                message=(
                    "No step limit: runs end when the model answers."
                    + (f" Spend is capped at ${budget}." if budget else "")
                ),
                details={"max_iterations": None, "max_budget_usd": budget},
            )
        max_iterations = int(getattr(agent, "max_iterations", 0) or 0)
        if max_iterations < 1:
            return DoctorCheck(
                name="runtime_limits",
                status="fail",
                message="max_iterations must be at least 1.",
                details={"max_iterations": max_iterations},
            )
        if max_iterations < 3:
            return DoctorCheck(
                name="runtime_limits",
                status="warn",
                message="max_iterations is low for a multi-step tool-using agent.",
                details={"max_iterations": max_iterations},
            )
        return DoctorCheck(
            name="runtime_limits",
            status="pass",
            message="Runtime iteration budget looks reasonable.",
            details={"max_iterations": max_iterations},
        )

    def _check_efficiency(self, agent: Any) -> DoctorCheck:
        """Report whether large/long-running agents use token controls."""
        llm = agent.llm
        class_name = llm.__class__.__name__
        if hasattr(llm, "prompt_caching"):
            cache_mode = "enabled" if llm.prompt_caching else "disabled"
        elif class_name in {"OpenAIChatLLM", "BedrockGemmaChatLLM"}:
            cache_mode = "automatic"
        else:
            cache_mode = "provider-managed or unavailable"

        tool_count = len(getattr(agent, "tools", []))
        code_mode = bool(getattr(agent, "code_mode", False))
        context_window = int(getattr(agent, "context_window_tokens", 0) or 0)
        tool_output_cap = int(getattr(agent, "max_tool_output_chars", 0) or 0)
        recommendations: list[str] = []
        if tool_count > 20 and not code_mode:
            recommendations.append("enable code_mode for progressive tool discovery")
        if context_window <= 0:
            recommendations.append("set context_window_tokens for long runs")
        if tool_count > 20 and tool_output_cap <= 0:
            recommendations.append("set max_tool_output_chars to bound tool context")
        if cache_mode == "disabled":
            recommendations.append("enable prompt_caching on the LLM adapter")

        return DoctorCheck(
            name="efficiency",
            status="warn" if recommendations else "pass",
            message=(
                "Token-efficiency controls can be improved."
                if recommendations
                else "Prompt caching and long-run token controls look ready."
            ),
            details={
                "prompt_caching": cache_mode,
                "code_mode": code_mode,
                "context_window_tokens": context_window,
                "max_tool_output_chars": tool_output_cap,
                "tool_count": tool_count,
                "session_store": agent.session_store.__class__.__name__
                if getattr(agent, "session_store", None)
                else "runtime default",
                "memory_store": agent.memory_store.__class__.__name__
                if getattr(agent, "memory_store", None)
                else "runtime default",
                "recommendations": "; ".join(recommendations) or "none",
            },
        )

    def _provider_details(self, llm: Any) -> tuple[str, dict[str, Any]]:
        class_name = llm.__class__.__name__
        model = getattr(llm, "model", "")
        provider = "unknown"
        missing: list[str] = []

        def env_present(*names: str) -> bool:
            return any(self.env.get(name) for name in names)

        if class_name in {"SimpleEchoLLM", "ShipitLLM"}:
            provider = "shipit"
        elif class_name == "OpenAIChatLLM":
            provider = "openai"
            if not (getattr(llm, "api_key", None) or env_present("OPENAI_API_KEY")):
                missing.append("OPENAI_API_KEY")
        elif class_name == "AnthropicChatLLM":
            provider = "anthropic"
            if not (getattr(llm, "api_key", None) or env_present("ANTHROPIC_API_KEY")):
                missing.append("ANTHROPIC_API_KEY")
        elif class_name in {
            "LiteLLMChatLLM",
            "BedrockChatLLM",
            "GeminiChatLLM",
            "GroqChatLLM",
            "TogetherChatLLM",
            "OllamaChatLLM",
        }:
            provider, missing = self._litellm_requirements(
                class_name=class_name, model=str(model)
            )

        return provider, {
            "class_name": class_name,
            "model": model or "n/a",
            "missing": missing,
        }

    def _litellm_requirements(
        self, *, class_name: str, model: str
    ) -> tuple[str, list[str]]:
        lower_model = model.lower()
        if class_name == "BedrockChatLLM" or lower_model.startswith("bedrock/"):
            provider = "bedrock"
            if not (
                self.env.get("AWS_PROFILE")
                or self.env.get("AWS_REGION_NAME")
                or self.env.get("AWS_DEFAULT_REGION")
            ):
                return provider, [
                    "AWS_REGION_NAME or AWS_DEFAULT_REGION or AWS_PROFILE"
                ]
            return provider, []
        if class_name == "GeminiChatLLM" or lower_model.startswith("gemini/"):
            return "gemini", [] if (
                self.env.get("GEMINI_API_KEY") or self.env.get("GOOGLE_API_KEY")
            ) else ["GEMINI_API_KEY or GOOGLE_API_KEY"]
        if class_name == "GroqChatLLM" or lower_model.startswith("groq/"):
            return "groq", [] if self.env.get("GROQ_API_KEY") else ["GROQ_API_KEY"]
        if class_name == "TogetherChatLLM" or lower_model.startswith("together_ai/"):
            return "together", [] if (
                self.env.get("TOGETHERAI_API_KEY") or self.env.get("TOGETHER_API_KEY")
            ) else ["TOGETHERAI_API_KEY or TOGETHER_API_KEY"]
        if class_name == "OllamaChatLLM" or lower_model.startswith("ollama/"):
            return "ollama", []
        return "litellm", []
