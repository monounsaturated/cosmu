FROM python:3.12-slim

WORKDIR /app

RUN pip install --no-cache-dir tradingagents fastapi uvicorn

COPY main.py .

EXPOSE 8100

CMD ["python", "main.py"]
