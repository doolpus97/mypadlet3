import os
import time
import json
from flask import Flask, render_template, request, jsonify
from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload

app = Flask(__name__)

UPLOAD_FOLDER = os.path.join('static', 'uploads')
os.makedirs(UPLOAD_FOLDER, exist_ok=True)
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER

DATA_FILE = 'data.json'

# ================= 구글 드라이브 설정 =================
# 본인의 구글 드라이브 폴더 ID를 여기에 입력하세요.
GOOGLE_DRIVE_FOLDER_ID = '여기에_구글_드라이브_폴더_ID_입력'

GOOGLE_CREDENTIALS_PATH = os.environ.get('GOOGLE_CREDENTIALS_PATH', '/etc/secrets/google_creds.json')
if not os.path.exists(GOOGLE_CREDENTIALS_PATH):
    GOOGLE_CREDENTIALS_PATH = 'google_creds.json'
# =========================================================

def load_data():
    if os.path.exists(DATA_FILE):
        try:
            with open(DATA_FILE, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception:
            pass
    # 원본 데이터 구조 호환 (users, boards, posts)
    return {"users": {}, "boards": [], "posts": {}}

def save_data(data):
    with open(DATA_FILE, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

db = load_data()

def get_drive_service():
    try:
        if os.path.exists(GOOGLE_CREDENTIALS_PATH):
            SCOPES = ['https://www.googleapis.com/auth/drive.file']
            creds = service_account.Credentials.from_service_account_file(
                GOOGLE_CREDENTIALS_PATH, scopes=SCOPES
            )
            return build('drive', 'v3', credentials=creds)
    except Exception as e:
        print(f"Google Drive Authentication Error: {e}")
    return None

@app.after_request
def add_header(response):
    response.headers['ngrok-skip-browser-warning'] = 'true'
    return response

@app.route('/')
def index():
    return render_template('index.html')

# 1. 파일 업로드 및 구글 드라이브 연동
@app.route('/upload', methods=['POST'])
def upload_files():
    files = request.files.getlist('files')
    uploaded_urls = []
    
    drive_service = get_drive_service()
    folder_id = GOOGLE_DRIVE_FOLDER_ID

    for file in files:
        if file and file.filename != '':
            ext = os.path.splitext(file.filename)[1]
            if not ext: 
                ext = '.png'
            
            save_name = f"{int(time.time() * 1000)}_{os.urandom(4).hex()}{ext}"
            filepath = os.path.join(app.config['UPLOAD_FOLDER'], save_name)
            file.save(filepath)
            
            url = None
            if drive_service and folder_id and folder_id != '여기에_구글_드라이브_폴더_ID_입력':
                try:
                    file_metadata = {'name': save_name, 'parents': [folder_id]}
                    media = MediaFileUpload(filepath, resumable=True)
                    drive_file = drive_service.files().create(
                        body=file_metadata, 
                        media_body=media, 
                        fields='id, webContentLink, webViewLink'
                    ).execute()
                    
                    drive_service.permissions().create(
                        fileId=drive_file.get('id'),
                        body={'type': 'anyone', 'role': 'reader'}
                    ).execute()
                    
                    url = drive_file.get('webViewLink') or drive_file.get('webContentLink')
                    if os.path.exists(filepath):
                        os.remove(filepath)
                except Exception as e:
                    print(f"Google Drive Upload Error: {e}")
            
            if not url:
                url = f"/static/uploads/{save_name}"
                
            uploaded_urls.append(url)

    return jsonify({'success': True, 'urls': uploaded_urls})

# 2. 교사 로그인 API
@app.route('/api/login/teacher', methods=['POST'])
def login_teacher():
    data = request.json or {}
    teacher_id = data.get('teacherId', '').strip()
    teacher_pw = data.get('teacherPw', '').strip()
    
    if not teacher_id or not teacher_pw:
        return jsonify({'success': False, 'message': '아이디와 비밀번호를 모두 입력하세요.'}), 400
        
    users = db.setdefault('users', {})
    if teacher_id in users:
        if users[teacher_id] == teacher_pw:
            return jsonify({'success': True, 'teacherId': teacher_id})
        else:
            return jsonify({'success': False, 'message': '비밀번호가 일치하지 않습니다.'}), 401
    else:
        users[teacher_id] = teacher_pw
        save_data(db)
        return jsonify({'success': True, 'teacherId': teacher_id})

# 3. 전체 게시판 목록 조회
@app.route('/api/boards', methods=['GET'])
def get_boards():
    teacher_id = request.args.get('teacherId', '').strip()
    boards = db.get('boards', [])
    if teacher_id:
        user_boards = [b for b in boards if b.get('owner') == teacher_id]
        return jsonify({'success': True, 'boards': user_boards})
    return jsonify({'success': True, 'boards': boards})

# 4. 입장 코드로 게시판 조회 (학생 접속용)
@app.route('/api/boards/by_code', methods=['GET'])
def get_board_by_code():
    code = request.args.get('code', '').strip()
    boards = db.get('boards', [])
    board = next((b for b in boards if str(b.get('code')).strip() == code), None)
    
    if board:
        return jsonify({'success': True, 'board': board})
    return jsonify({'success': False, 'message': '입장 코드가 올바르지 않거나 등록된 게시판이 없습니다.'}), 404

# 5. 새 게시판 생성
@app.route('/api/boards', methods=['POST'])
def create_board():
    data = request.json or {}
    title = data.get('title', '').strip()
    code = data.get('code', '').strip()
    teacher_id = data.get('teacherId', '').strip()
    
    if not title or not code:
        return jsonify({'success': False, 'message': '게시판 제목과 코드를 입력하세요.'}), 400
        
    boards = db.setdefault('boards', [])
    if any(str(b.get('code')).strip() == code for b in boards):
        return jsonify({'success': False, 'message': '이미 사용 중인 입장 코드입니다.'}), 400
        
    new_board = {
        'id': f"board_{int(time.time()*1000)}",
        'title': title,
        'code': code,
        'owner': teacher_id
    }
    boards.append(new_board)
    save_data(db)
    return jsonify({'success': True, 'board': new_board})

# 6. 게시글(포스트잇) 조회
@app.route('/api/posts', methods=['GET'])
def get_posts():
    board_title = request.args.get('boardTitle', '').strip()
    posts_dict = db.get('posts', {})
    posts = posts_dict.get(board_title, [])
    return jsonify({'success': True, 'posts': posts})

# 7. 게시글 작성
@app.route('/api/posts', methods=['POST'])
def add_post():
    data = request.json or {}
    board_title = data.get('boardTitle', '').strip()
    if not board_title:
        return jsonify({'success': False, 'message': '게시판 정보를 찾을 수 없습니다.'}), 400
        
    posts_dict = db.setdefault('posts', {})
    posts = posts_dict.setdefault(board_title, [])
        
    post = {
        'postId': f"post_{int(time.time()*1000)}",
        'section': data.get('section', '모둠 1'),
        'author': data.get('author'),
        'title': data.get('title', ''),
        'content': data.get('content', ''),
        'imgs': data.get('imgs', []),
        'attachedFiles': data.get('attachedFiles', []),
        'comments': []
    }
    posts.insert(0, post)
    save_data(db)
    return jsonify({'success': True, 'post': post})

# 8. 댓글 작성
@app.route('/api/posts/comments', methods=['POST'])
def add_comment():
    data = request.json or {}
    board_title = data.get('boardTitle', '').strip()
    post_id = data.get('postId', '').strip()
    comment_text = data.get('comment', '').strip()
    author = data.get('author', '익명')
    
    if not comment_text or not post_id:
        return jsonify({'success': False, 'message': '댓글 내용을 입력하세요.'}), 400

    posts_dict = db.get('posts', {})
    posts = posts_dict.get(board_title, [])
    target_post = next((p for p in posts if p.get('postId') == post_id), None)
    
    if target_post:
        comments = target_post.setdefault('comments', [])
        comments.append({'author': author, 'text': comment_text})
        save_data(db)
        return jsonify({'success': True, 'post': target_post})
        
    return jsonify({'success': False, 'message': '게시물을 찾을 수 없습니다.'}), 404

if __name__ == '__main__':
    port = int(os.environ.get("PORT", 5000))
    app.run(host='0.0.0.0', port=port, debug=True)
