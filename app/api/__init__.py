"""HTTP API layer.

This package exposes the translation, explanation and validation services
through a stateless FastAPI application, suitable for horizontal scaling.
It reuses the existing services in :mod:`app.services` and :mod:`app.validator`
without modifying them: the API is only a new presentation layer that replaces
the Gradio interface for production deployments.
"""