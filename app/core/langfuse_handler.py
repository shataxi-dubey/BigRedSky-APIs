from langfuse import Langfuse
from langfuse.langchain import CallbackHandler

from app import settings

# Initialize the global Langfuse client (configures the OTEL tracer provider).
# CallbackHandler picks up credentials from this global client automatically.
Langfuse(
    public_key=settings.LANGFUSE_PUBLIC_KEY,
    secret_key=settings.LANGFUSE_SECRET_KEY,
    host=settings.LANGFUSE_HOST,
)

langfuse_handler = CallbackHandler()
