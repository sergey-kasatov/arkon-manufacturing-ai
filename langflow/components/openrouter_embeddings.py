"""OpenRouter embeddings for Langflow 1.11.5.

Langflow cannot embed through OpenRouter with any component it ships, and the
reason is worth stating because it is not visible from any error message.

OpenRouter serves 33 embedding models, including google/gemini-embedding-001 at
the 3072 dimensions the course prescribes, and the key is already configured in
Langflow. What is missing is a component that can talk to them:

- The generic "Embedding Model" component reaches providers through
  EMBEDDING_PROVIDER_CLASS_MAPPING, which has no OpenRouter entry, so its
  provider override raises "No embedding class defined in metadata".
- Overriding the provider to OpenAI and pointing api_base at OpenRouter does
  reach the endpoint, and then fails twice on the wire format. langchain's
  OpenAIEmbeddings tokenises input with tiktoken and sends token-id arrays,
  which Google AI Studio embeddings reject; and the openai SDK adds
  encoding_format=base64 whenever the caller does not set it, which they reject
  as well. The first needs check_embedding_ctx_length=False, a constructor
  field the component does not expose, and langchain refuses it through
  model_kwargs by name.
- The dedicated "OpenAI Embeddings" component has a fixed three-model dropdown
  with combobox disabled, so the model name cannot be typed at all.

The base64 failure is intermittent, which is the part that would cost a day:
OpenRouter routes one model across several upstreams and only some of them
reject base64, so the same call measured 3 successes in 8 attempts. Setting
encoding_format explicitly makes it 8 in 8. Both settings are required and only
one of them is reachable from a stock component, which is why this file exists.
"""

from lfx.base.embeddings.model import LCEmbeddingsModel
from lfx.field_typing import Embeddings
from lfx.io import IntInput, MessageTextInput, SecretStrInput, StrInput


class OpenRouterEmbeddingsComponent(LCEmbeddingsModel):
    display_name = "OpenRouter Embeddings"
    description = "Embeddings through OpenRouter, which no shipped component can reach."
    icon = "binary"
    name = "OpenRouterEmbeddings"

    inputs = [
        StrInput(
            name="model_name",
            display_name="Model Name",
            info="Any model listed at https://openrouter.ai/api/v1/embeddings/models.",
            value="google/gemini-embedding-001",
            required=True,
        ),
        SecretStrInput(
            name="api_key",
            display_name="OpenRouter API Key",
            info="Global variable name, resolved at run time. The value never enters the flow.",
            value="OPENROUTER_API_KEY",
            required=True,
        ),
        MessageTextInput(
            name="base_url",
            display_name="Base URL",
            value="https://openrouter.ai/api/v1",
            advanced=True,
        ),
        IntInput(
            name="chunk_size",
            display_name="Batch Size",
            info="Texts per request. Kept small because a rejected batch costs the whole batch.",
            value=32,
            advanced=True,
        ),
    ]

    def build_embeddings(self) -> Embeddings:
        from langchain_openai import OpenAIEmbeddings

        return OpenAIEmbeddings(
            model=self.model_name,
            base_url=self.base_url,
            api_key=self.api_key,
            chunk_size=self.chunk_size,
            # Send raw text. The default tokenises with tiktoken and sends token
            # ids, which Google AI Studio embeddings reject outright.
            check_embedding_ctx_length=False,
            # Pin the response format. Left unset, the openai SDK asks for base64
            # whenever numpy is importable, and some OpenRouter upstreams for this
            # model refuse it. That failure is intermittent by upstream, not by input.
            model_kwargs={"encoding_format": "float"},
        )
