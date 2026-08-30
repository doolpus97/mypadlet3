import os
import time
import json
from flask import Flask, render_template, request, jsonify, session, redirect, url_for
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import Flow
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload

app = Flask(__name__)
# 세션 유지를 위한 시크릿 키 설정
app.secret_key = os.environ.get('FLASK_SECRET_KEY', 'mypadlet_secure_secret_key_123')

# HTTPS 환경 (Render 등)에서 OAuth 리디렉션을 위한 설정
os.environ['OAUTHLIB_INSECURE_TRANSPORT'] = '1'

UPLOAD_FOLDER = os.path.join('static', 'uploads')
os.makedirs(UPLOAD_FOLDER, exist_ok=True)
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER

DATA_FILE = 'data.json'

# ================= 구글 드라이브 설정 =================
GOOGLE_DRIVE_FOLDER_ID = '1capKURBOv5TpP0DgNvagP8VQYfnLlBtl'
SCOPES = ['https://www.googleapis.com/auth/drive.file']

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

def get_oauth_client_config():
    """Render 환경 변수에서 OAuth 클라이언트 정보를 불러옵니다."""
    client_id = os.environ.get('GOOGLE_CLIENT_ID')
    client_secret = os.environ.get('GOOGLE_CLIENT_SECRET')
    if not client_id or not client_secret:
        return None
    return {
        "web": {
            "client_id": client_id,
            "client_secret": client_secret,
            "auth_uri": "https://accounts.google.com/o/oauth2/auth",
            "token_uri": "https://oauth2.googleapis.com/token",
        }
    }

@app.route('/')
def index():
    return render_template('index.html')

# ================= 구글 개인 계정 인증(OAuth) 라우트 =================
@app.route('/auth/google')
def google_auth():
    client_config = get_oauth_client_config()
    if not client_config:
        return "Google Client ID 또는 Secret 환경 변수가 설정되지 않았습니다.", 500
    
    flow = Flow.from_client_config(
        client_config,
        scopes=SCOPES,
        redirect_uri=url_for('google_callback', _external=True)
    )
    authorization_url, state = flow.authorization_url(
        access_type='offline',
        include_granted_scopes='true',
        prompt='consent'
    )
    session['oauth_state'] = state
    return redirect(authorization_url)

@app.route('/auth/google/callback')
def google_callback():
    state = session.get('oauth_state')
    client_config = get_oauth_client_config()
    
    flow = Flow.from_client_config(
        client_config,
        scopes=SCOPES,
        state=state,
        redirect_uri=url_for('google_callback', _external=True)
    )
    flow.fetch_token(authorization_response=request.url)
    credentials = flow.credentials
    
    # 인증된 크레덴셜 정보를 세션에 저장
    session['credentials'] = {
        'token': credentials.token,
        'refresh_token': credentials.refresh_token,
        'token_uri': credentials.token_uri,
        'client_id': credentials.client_id,
        'client_secret': credentials.client_secret,
        'scopes': credentials.scopes
    }
    return redirect('/')

# ================= 파일 업로드 및 구글 드라이브 연동 =================
@app.route('/upload', methods=['POST'])
def upload_files():
    files = request.files.getlist('files')
    uploaded_urls = []
    
    creds_dict = session.get('credentials')
    drive_service = None
    
    if creds_dict:
        try:
            creds = Credentials(**creds_dict)
            drive_service = build('drive', 'v3', credentials=creds)
        except Exception as e:
            print(f"[Drive Auth Error] {e}")

    for file in files:
        if file and file.filename != '':
            ext = os.path.splitext(file.filename)[1]
            if not ext: 
                ext = '.png'
            
            save_name = f"{int(time.time() * 1000)}_{os.urandom(4).hex()}{ext}"
            filepath = os.path.join(app.config['UPLOAD_FOLDER'], save_name)
            file.save(filepath)
            
            url = None
            if drive_service:
                try:
                    file_metadata = {
                        'name': save_name,
                        'parents': [GOOGLE_DRIVE_FOLDER_ID] if GOOGLE_DRIVE_FOLDER_ID else []
                    }
                    media = MediaFileUpload(filepath, resumable=True)
                    drive_file = drive_service.files().create(
                        body=file_metadata,
                        media_body=media,
                        fields='id, webContentLink, webViewLink'
                    ).execute()
                    
                    file_id = drive_file.get('id')
                    
                    # 외부 공개 권한 부여
                    drive_service.permissions().create(
                        fileId=file_id,
                        body={'type': 'anyone', 'role': 'reader'}
                    ).execute()
                    
                    url = drive_file.get('webViewLink') or drive_file.get('webContentLink')
                except Exception as e:
                    print(f"[Drive Upload Error] {e}")
            
            # 로컬 임시파일 삭제
            if os.path.exists(filepath):
                try:
                    os.remove(filepath)
                except Exception:
                    pass
            
            if url:
                uploaded_urls.append(url)
            else:
                uploaded_urls.append(f"/static/uploads/{save_name}")

    return jsonify({'success': True, 'urls': uploaded_urls})

# ================= 게시판 및 인증 API =================
@app.route('/api/signup/teacher', methods=['POST'])
def signup_teacher():
    data = request.json or {}
    teacher_id = data.get('teacherId', '').strip()
    teacher_pw = data.get('teacherPw', '').strip()
    
    if not teacher_id or not teacher_pw:
        return jsonify({'success': False, 'message': '아이디와 비밀번호를 모두 입력하세요.'}), 400
        
    users = db.setdefault('users', {})
    if teacher_id in users:
        return jsonify({'success': False, 'message': '이미 존재하는 교사 아이디입니다.'}), 400
        
    users[teacher_id] = teacher_pw
    save_data(db)
    return jsonify({'success': True, 'message': '회원가입이 완료되었습니다!'})

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
        return jsonify({'success': False, 'message': '존재하지 않는 아이디입니다.'}), 404

@app.route('/api/boards', methods=['GET'])
def get_boards():
    teacher_id = request.args.get('teacherId', '').strip()
    boards = db.get('boards', [])
    if teacher_id:
        # [수정 완료] 괄호 오류가 수정된 부분입니다.
        user_boards = [b for b in boards if b.get('owner') == teacher_id]
        return jsonify({'success': True, 'boards': user_boards})
    return jsonify({'success': True, 'boards': boards})

@app.route('/api/boards/by_code', methods=['GET'])
def get_board_by_code():
    code = request.args.get('code', '').strip()
    boards = db.get('boards', [])
    board = next((b for b in boards if str(b.get('code')).strip() == code), None)
    
    if board:
        return jsonify({'success': True, 'board': board})
    return jsonify({'success': False, 'message': '입장 코드가 올바르지 않습니다.'}), 404

@app.route('/api/boards', methods=['POST'])
def create_board():
    data = request.json or {}
    title = data.get('title', '').strip()
    code = data.get('code', '').strip()
    teacher_id = data.get('teacherId', '').strip()
    
    if not title or not code:
        return jsonify({'success': False, 'message': '제목과 코드를 입력하세요.'}), 400
        
    boards = db.setdefault('boards', [])
    new_board = {
        'id': f"board_{int(time.time()*1000)}",
        'title': title,
        'code': code,
        'owner': teacher_id
    }
    boards.append(new_board)
    save_data(db)
    return jsonify({'success': True, 'board': new_board})

@app.route('/api/posts', methods=['GET'])
def get_posts():
    board_title = request.args.get('boardTitle', '').strip()
    posts_dict = db.get('posts', {})
    posts = posts_dict.get(board_title, [])
    return jsonify({'success': True, 'posts': posts})

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
        'attachedFiles': [],
        'comments': []
    }
    posts.insert(0, post)
    save_data(db)
    return jsonify({'success': True, 'post': post})

if __name__ == '__main__':
    port = int(os.environ.get("PORT", 5000))
    app.run(host='0.0.0.0', port=port, debug=True)
