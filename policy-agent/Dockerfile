ARG REGISTRY=
FROM ${REGISTRY}python:3.12-slim
WORKDIR /app
ARG PIP_INDEX_URL
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
# Bake the reranker model into the image so the first request never downloads anything.
RUN python -c "from flashrank import Ranker; Ranker(model_name='ms-marco-MiniLM-L-12-v2')"
COPY . .
EXPOSE 8001
CMD ["sh", "docker-entrypoint.sh"]
