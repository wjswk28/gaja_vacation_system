# Python 3.10 이미지 사용
FROM python:3.10-slim

# 작업 디렉토리 설정
WORKDIR /app

# requirements.txt 복사
COPY requirements.txt .

# 의존성 설치
RUN pip install --no-cache-dir -r requirements.txt

# 소스 전체 복사
COPY . .

# Gunicorn 실행 (8000 포트)
CMD ["gunicorn", "-b", "0.0.0.0:8000", "run:app"]
