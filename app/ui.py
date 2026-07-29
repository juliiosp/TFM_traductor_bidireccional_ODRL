"""Entry point for the Gradio client.

The UI contains no translation or persistence logic. It communicates with the
FastAPI service configured through ``API_BASE_URL``.
"""

import os

from app.web.interface import demo


if __name__ == "__main__":
    demo.queue().launch(
        server_name=os.getenv("GRADIO_SERVER_NAME", "0.0.0.0"),
        server_port=int(os.getenv("GRADIO_SERVER_PORT", "7860")),
    )