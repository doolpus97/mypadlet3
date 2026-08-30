import os
import random
import string
from flask import Flask, render_template, request, jsonify
from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseUpload
import io

app = Flask(__name__)

# ==========================================
# Google Drive API 설정 (필요 시 파일 업로드용)
# ==========================================
# SERVICE_ACCOUNT_FILE = 'credentials.json'  # 서비스 계정 키 파일 경로
# FOLDER_ID = 'YOUR_GOOGLE_DRIVE_FOLDER_ID' # 구글 드라이브 폴더 ID

# ==========================================
# 인메모리 데이터 저장소 (테스트 및 기본 구조)
# 실무 적용 시 DB(SQLite, PostgreSQL 등)로 대체 권장
# ==========================================
teachers = {}  # { teacher_id: teacher_pw }
boards = [
    # 기본 예시 게시판
    {
        "title": "기본 게시판",
        "code": "1234",
        "teacherId": "admin"
    }
]
posts = []    # [{ boardTitle, section, author, title, content, imgs }, ...]

# ------------------------------------------
# 라우트: 메인 페이지
# ------------------------------------------
@app.route('/')
def index():
    return render_template('index.html')

# ------------------------------------------
# API: 교사 회원가입 & 로그인
# ------------------------------------------
@app.route('/api/signup/teacher', methods=['POST'])
def signup_teacher():
    data = request.get_json()
    t_id = data.get('teacherId')
    t_pw = data.get('teacherPw')

    if not t_id or not t_pw:
        return jsonify({"success": False, "message": "아이디와 비밀번호를 입력하세요."}), 400

    if t_id in teachers:
        return jsonify({"success": False, "message": "이미 존재하는 아이디입니다."}), 400

    teachers[t_id] = t_pw
    return jsonify({"success": True, "message": "교사 회원가입이 완료되었습니다."})


@app.route('/api/login/teacher', methods=['POST'])
def login_teacher():
    data = request.get_json()
    t_id = data.get('teacherId')
    t_pw = data.get('teacherPw')

    if teachers.get(t_id) == t_pw:
        return jsonify({"success": True, "message": "로그인 성공"})
    else:
        return jsonify({"success": False, "message": "아이디 또는 비밀번호가 일치하지 않습니다."}), 401

# ------------------------------------------
# API: 게시판 관리 (생성 및 조회)
# ------------------------------------------
@app.route('/api/boards', methods=['GET', 'POST'])
def handle_boards():
    if request.method == 'POST':
        # 새 게시판 생성
        data = request.get_json()
        title = data.get('title')
        code = data.get('code')
        teacher_id = data.get('teacherId')

        if not title or not code:
            return jsonify({"success": False, "message": "게시판 제목과 코드가 필요합니다."}), 400

        # 중복 코드 방지 처리
        while any(b['code'] == code for b in boards):
            code = str(random.randint(1000, 9999))

        new_board = {
            "title": title,
            "code": code,
            "teacherId": teacher_id
        }
        boards.append(new_board)
        return jsonify({"success": True, "board": new_board})

    else:
        # 교사의 게시판 목록 조회
        teacher_id = request.args.get('teacherId')
        if teacher_id:
            user_boards = [b for b in boards if b.get('teacherId') == teacher_id]
            return jsonify({"success": True, "boards": user_boards})
        return jsonify({"success": True, "boards": boards})


@app.route('/api/boards/by_code', methods=['GET'])
def get_board_by_code():
    # 학생 4자리 코드로 게시판 검색
    code = request.args.get('code')
    found_board = next((b for b in boards if b.get('code') == code), None)

    if found_board:
        return jsonify({"success": True, "board": found_board})
    else:
        return jsonify({"success": False, "message": "존재하지 않는 입장 코드입니다."}), 440

# ------------------------------------------
# API: 게시물 관리 (목록 조회 및 등록)
# ------------------------------------------
@app.route('/api/posts', methods=['GET', 'POST'])
def handle_posts():
    if request.method == 'POST':
        data = request.get_json()
        board_title = data.get('boardTitle')
        section = data.get('section')
        author = data.get('author')
        title = data.get('title')
        content = data.get('content')
        imgs = data.get('imgs', [])

        new_post = {
            "boardTitle": board_title,
            "section": section,
            "author": author,
            "title": title,
            "content": content,
            "imgs": imgs
        }
        posts.append(new_post)
        return jsonify({"success": True, "post": new_post})

    else:
        board_title = request.args.get('boardTitle')
        board_posts = [p for p in posts if p.get('boardTitle') == board_title]
        return jsonify({"success": True, "posts": board_posts})

# ------------------------------------------
# API: 파일 업로드 (기본 구조)
# ------------------------------------------
@app.route('/upload', methods=['POST'])
def upload_file():
    uploaded_files = request.files.getlist('files')
    file_urls = []

    # 구글 드라이브 연동 또는 서버 로컬 저장 처리
    for file in uploaded_files:
        if file.filename != '':
            # 로컬 임시 저장 예시 (구글 드라이브 API 연동 시 해당 로직 작성)
            # file_urls.append(google_drive_upload(file))
            pass

    return jsonify({"success": True, "urls": file_urls})

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)
