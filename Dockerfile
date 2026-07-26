# API image: FastAPI + the RAG stack.
#
# Also the worker image — compose builds both services from this Dockerfile and
# only varies the command, which is why the OCR system dependency below has to
# live here: parsing runs in the worker, not the API.
#
# Qdrant and the frontend are separate services (see docker-compose.yml).
# Ollama deliberately stays on the host and is reached over OLLAMA_HOST.
#
# CPU-only by design: torch is pinned to the +cpu wheels in pyproject.toml, so no
# CUDA/nvidia packages are installed. Embedding and reranking run on CPU, and the
# one heavy generation step (Ollama) is outside this image entirely.
FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    HF_HOME=/opt/hf

# pytesseract is only a wrapper — it shells out to the tesseract binary, which
# pip cannot supply. Without this, image uploads fail in the worker at OCR time
# even though every Python dependency resolved. -fas is the Persian language
# data: the corpus is bilingual and parse_image asks for "eng+fas".
# Its own layer, before the lockfile, so it survives dependency churn.
RUN apt-get update && apt-get install -y --no-install-recommends \
        tesseract-ocr tesseract-ocr-fas && rm -rf /var/lib/apt/lists/*

COPY --from=ghcr.io/astral-sh/uv:0.9.30 /uv /usr/local/bin/uv

WORKDIR /app

# Dependencies resolve from the lockfile in their own layer, so touching source
# does not reinstall torch.
COPY pyproject.toml uv.lock README.md ./
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev --no-install-project

# Fail the build loudly if the CPU pin ever stops taking effect — a CUDA torch
# here would silently add multiple GB to the image.
RUN /app/.venv/bin/python -c "\
import torch; \
print('torch', torch.__version__, '| cuda_available', torch.cuda.is_available()); \
assert torch.__version__.endswith('+cpu'), 'expected a +cpu build, got ' + torch.__version__; \
assert not torch.cuda.is_available(), 'CUDA is available — CPU-only pin failed'"

# src/ before the rest: `eda` is the only packaged module (see pyproject).
COPY src/ ./src/
COPY api/ ./api/
COPY scripts/ ./scripts/

RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev

ENV PATH="/app/.venv/bin:$PATH"

EXPOSE 8000

# No --reload: this is the built image, not a dev loop.
CMD ["uvicorn", "api.main:app", "--host", "0.0.0.0", "--port", "8000"]
