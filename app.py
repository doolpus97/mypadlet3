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

# 구글 드라이브 환경변수 및 인증 처리
GOOGLE_CREDENTIALS_PATH = os.environ.get('GOOGLE_CREDENTIALS_PATH', '/etc/secrets/google_creds.json')
if not os.path.exists(GOOGLE_CREDENTIALS_PATH):
    GOOGLE_CREDENTIALS_PATH = 'google_creds.json'

def get_drive_service():
    if not os.path.exists(GOOGLE_CREDENTIALS_PATH):
        return None
    try:
        creds = service_account.Credentials.from_service_account_file(
            GOOGLE_CREDENTIALS_PATH, 
            scopes=['https://www.googleapis.com/auth/drive.file']
        )
        return build('drive', 'v3', credentials=creds)
    except Exception as e:
        print(f"Drive Auth Error: {e}")
        return None

def load_data():
    if os.path.exists(DATA_FILE):
        try:
            with open(DATA_FILE, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception:
            pass
    return {"users": {}, "boards": [], "posts": {}}

def save_data(data):
    with open(DATA_FILE, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

db = load_data()

@app.after_request
def add_header(response):
    response.headers['ngrok-skip-browser-warning'] = 'true'
    return response

@app.route('/')
def index():
    return render_template('index.html')

# 구글 드라이브 업로드 엔드포인트
@app.route('/upload', methods=['POST'])
def upload_files():
    files = request.files.getlist('files')
    uploaded_urls = []
    uploaded_files = [] 
    
    drive_service = get_drive_service()
    # 구글 드라이브 폴더 ID (환경변수로 받거나 기본값 설정)
    folder_id = os.environ.get('GOOGLE_DRIVE_FOLDER_ID', '')

    for file in files:
        if file and file.filename != '':
            ext = os.path.splitext(file.filename)[1]
            if not ext: ext = '.png'
            
            save_name = f"{int(time.time() * 1000)}_{os.urandom(4).hex()}{ext}"
            filepath = os.path.join(app.config['UPLOAD_FOLDER'], save_name)
            file.save(filepath)
            
            if drive_service and folder_id:
                try:
                    file_metadata = {'name': save_name, 'parents': [folder_id]}
                    media = MediaFileUpload(filepath, resumable=True)
                    drive_file = drive_service.files().create(
                        body=file_metadata, 
                        media_body=media, 
                        fields='id, webContentLink'
                    ).execute()
                    
                    drive_service.permissions().create(
                        fileId=drive_file.get('id'),
                        body={'type': 'anyone', 'role': 'reader'}
                    ).execute()
                    
                    url = drive_file.get('webContentLink')
                    os.remove(filepath)
                except Exception as e:
                    print(f"Drive Upload Error: {e}")
                    url = f"/static/uploads/{save_name}"
            else:
                url = f"/static/uploads/{save_name}"
                
            uploaded_urls.append(url)
            uploaded_files.append({"url": url, "name": file.filename})

    return jsonify({'urls': uploaded_urls, 'files': uploaded_files})

# 교사 로그인
@app.route('/api/login/teacher', methods=['POST'])
def login_teacher():
    data = request.json or {}
    teacher_id = data.get('teacherId', '').strip()
    teacher_pw = data.get('teacherPw', '').strip()
    
    if not teacher_id or not teacher_pw:
        return jsonify({'success': False, 'message': '아이디와 비밀번호를 모두 입력하세요.'}), 400
        
    if teacher_id in db['users']:
        if db['users'][teacher_id] == teacher_pw:
            return jsonify({'success': True, 'teacherId': teacher_id})
        else:
            return jsonify({'success': False, 'message': '비밀번호가 일치하지 않습니다.'}), 401
    else:
        db['users'][teacher_id] = teacher_pw
        save_data(db)
        return jsonify({'success': True, 'teacherId': teacher_id})

# 전체 게시판 목록 조회
@app.route('/api/boards', methods=['GET'])
def get_boards():
    teacher_id = request.args.get('teacherId', '').strip()
    if teacher_id:
        user_boards = [b for b in db.get('boards', []) if b.get('owner') == teacher_id]
        return jsonify({'success': True, 'boards': user_boards})
    return jsonify({'success': True, 'boards': db.get('boards', [])})

# 입장 코드로 게시판 조회 (원래 프론트엔드가 요구하는 반환 형식을 정확히 맞춤)
@app.route('/api/boards/by_code', methods=['GET'])
def get_board_by_code():
    code = request.args.get('code', '').strip()
    boards = db.get('boards', [])
    board = next((b for b in boards if str(b.get('code')).strip() == code), None)
    
    if board:
        return jsonify({'success': True, 'board': board})
    return jsonify({'success': False, 'message': '입장 코드가 올바르지 않거나 등록된 게시판이 없습니다.'}), 404

# 새 게시판 생성
@app.route('/api/boards', methods=['POST'])
def create_board():
    data = request.json or {}
    title = data.get('title', '').strip()
    code = data.get('code', '').strip()
    teacher_id = data.get('teacherId', '').strip()
    
    if not title or not code:
        return jsonify({'success': False, 'message': '게시판 제목과 코드를 입력하세요.'}), 400
        
    if 'boards' not in db:
        db['boards'] = []

    if any(str(b.get('code')).strip() == code for b in db['boards']):
        return jsonify({'success': False, 'message': '이미 사용 중인 입장 코드입니다.'}), 400
        
    new_board = {
        'id': f"board_{int(time.time()*1000)}",
        'title': title,
        'code': code,
        'owner': teacher_id
    }
    db['boards'].append(new_board)
    save_data(db)
    return jsonify({'success': True, 'board': new_board})

# 게시글 조회
@app.route('/api/posts', methods=['GET'])
def get_posts():
    board_title = request.args.get('boardTitle', '').strip()
    posts = db.get('posts', {}).get(board_title, [])
    return jsonify({'success': True, 'posts': posts})

# 게시글 작성
@app.route('/api/posts', methods=['POST'])
def add_post():
    data = request.json or {}
    board_title = data.get('boardTitle', '').strip()
    if not board_title:
        return jsonify({'success': False, 'message': '게시판 정보를 찾을 수 없습니다.'}), 400
        
    if 'posts' not in db:
        db['posts'] = {}
    if board_title not in db['posts']:
        db['posts'][board_title] = []
        
    post = {
        'postId': f"post_{int(time.time()*1000)}_{os.urandom(2).hex()}",
        'author': data.get('author'),
        'title': data.get('title'),
        'content': data.get('content'),
        'imgs': data.get('imgs', []),
        'attachedFiles': data.get('attachedFiles', [])
    }
    db['posts'][board_title].insert(0, post)
    save_data(db)
    return jsonify({'success': True, 'post': post})

if __name__ == '__main__':
    port = int(os.environ.get("PORT", 5000))
    app.run(host='0.0.0.0', port=port)
