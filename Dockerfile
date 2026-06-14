FROM python:3.12-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY magpie/ magpie/
ENV DATA_DIR=/data
VOLUME /data
CMD ["python", "-m", "magpie"]
