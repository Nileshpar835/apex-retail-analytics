FROM python:3.11-slim

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    libgl1 \
    libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Prepare data files if inputs exist, skip gracefully if not
RUN python -c "from pathlib import Path; import sys; sys.exit(0 if Path('data/pos_raw.csv').exists() else 1)" && python scripts/prepare_pos.py && python scripts/generate_events_from_pos.py || true

ENV PYTHONPATH=/app
ENV DATABASE_URL=sqlite+aiosqlite:///./data/store_intel.db

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
