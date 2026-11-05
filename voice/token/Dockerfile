FROM python:3.12-slim
RUN pip install --no-cache-dir livekit-api
COPY token_server.py /app/token_server.py
CMD ["python", "/app/token_server.py"]
