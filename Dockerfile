FROM python:3.12-slim
WORKDIR /app
COPY . .
ENV PORT=8000 DATA_DIR=/data
VOLUME /data
EXPOSE 8000
CMD ["python", "app.py"]
