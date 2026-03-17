import os
from typing import Optional, Dict, Any
from crewai import LLM
from dotenv import load_dotenv

load_dotenv()

class LLMFactory:
    """
    LLM Factory for managing and creating LLM instances.
    Supports creating LLMs for different providers (Aliyun/OpenAI, Ollama, etc.)
    to enable task-level or agent-level model selection.
    """

    @staticmethod
    def get_aliyun_llm(model_name: Optional[str] = None, temperature: float = 0.7) -> LLM:
        """
        Get an LLM instance configured for Aliyun (compatible with OpenAI API).
        
        Args:
            model_name: Specific model name (e.g., 'qwen-turbo', 'qwen-max'). 
                        If None, uses the MODEL_NAME from environment variables.
            temperature: Sampling temperature.
            
        Returns:
            Configured crewai.LLM instance.
        """
        api_key = os.getenv("ALIYUN_API_KEY")
        base_url = os.getenv("ALIYUN_API_BASE")
        
        # Default model from env or fallback
        target_model = model_name or os.getenv("MODEL_NAME", "qwen3.5-flash")
        
        # Ensure correct prefix for LiteLLM
        if not target_model.startswith("openai/"):
            target_model = f"openai/{target_model}"

        # Set dummy key if not present (required by some libs even if using custom base_url)
        if "OPENAI_API_KEY" not in os.environ:
             os.environ["OPENAI_API_KEY"] = "NA"

        return LLM(
            model=target_model,
            base_url=base_url,
            api_key=api_key,
            temperature=temperature,
            timeout=600
        )

    @staticmethod
    def get_ollama_llm(model_name: str, base_url: str = "http://localhost:11434", temperature: float = 0.7) -> LLM:
        """
        Get an LLM instance configured for Ollama (local models).
        
        Args:
            model_name: Name of the local model (e.g., 'llama3', 'mistral').
            base_url: URL of the Ollama server.
            temperature: Sampling temperature.
            
        Returns:
            Configured crewai.LLM instance.
        """
        # Ensure correct prefix for LiteLLM
        if not model_name.startswith("ollama/"):
            target_model = f"ollama/{model_name}"
        else:
            target_model = model_name

        return LLM(
            model=target_model,
            base_url=base_url,
            temperature=temperature,
            timeout=600
        )

    @staticmethod
    def get_llm(config: Optional[Dict[str, Any]] = None) -> LLM:
        """
        Generic factory method to get an LLM based on a configuration dictionary.
        
        Args:
            config: Dictionary containing 'provider', 'model', and other settings.
                    Example: {'provider': 'ollama', 'model': 'llama3'}
                    If None, returns the default Aliyun LLM.
        """
        if not config:
            return LLMFactory.get_aliyun_llm()
            
        provider = config.get("provider", "aliyun").lower()
        model = config.get("model")
        temperature = config.get("temperature", 0.7)
        
        if provider == "ollama":
            base_url = config.get("base_url", "http://localhost:11434")
            return LLMFactory.get_ollama_llm(model_name=model, base_url=base_url, temperature=temperature)
        
        elif provider == "aliyun" or provider == "openai":
            return LLMFactory.get_aliyun_llm(model_name=model, temperature=temperature)
            
        else:
            # Fallback or raise error
            raise ValueError(f"Unsupported LLM provider: {provider}")
