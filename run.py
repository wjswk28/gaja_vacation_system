import os
import sys

# 현재 디렉토리를 Python 경로에 추가 (Render에서 import 오류 방지)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from app import create_app

app = create_app()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
