import os
import time
import json
from flask import Flask, render_template, request, jsonify
from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload

app = Flask(__name__)

UPLOAD_FOLDER = 'static/uploads'
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
    return {"users": {}, "posts": []}

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

@app.route('/')
def index():
    return render_template('index.html')

# 로그인 API (프론트엔드와 완벽 호환)
@app.route('/api/login', methods=['POST'])
def login():
    data = request.json or {}
    user_type = data.get('type')  # 'student' 또는 'teacher'
    name = data.get('name', '').strip()
    pw = data.get('pw', '').strip()

    if user_type == 'student':
        if not name:
            return jsonify({'success': False, 'message': '이름을 입력하세요.'}), 400
        return jsonify({'success': True, 'name': name, 'type': 'student'})
    
    elif user_type == 'teacher':
        if not name or not pw:
            return jsonify({'success': False, 'message': '아이디와 비밀번호를 입력하세요.'}), 400
        
        users = db.get('users', {})
        if name in users:
            if users[name] == pw:
                return jsonify({'success': True, 'name': name, 'type': 'teacher'})
            else:
                return jsonify({'success': False, 'message': '비밀번호가 틀렸습니다.'}), 401
        else:
            users[name] = pw
            db['users'] = users
            save_data(db)
            return jsonify({'success': True, 'name': name, 'type': 'teacher'})
            
    return jsonify({'success': False, 'message': '잘못된 접근입니다.'}), 400

# 포스트 목록 조회 API
@app.route('/api/posts', methods=['GET'])
def get_posts():
    return jsonify({'success': True, 'posts': db.get('posts', [])})

# 포스트 작성 API
@app.route('/api/posts', methods=['POST'])
def add_post():
    data = request.json or {}
    post = {
        'id': f"post_{int(time.time()*1000)}",
        'section': data.get('section', '섹션 1'),
        'content': data.get('content', ''),
        'author': data.get('author', '익명'),
        'images': data.get('images', []),
        'comments': []
    }
    
    if 'posts' not in db:
        db['posts'] = []
    db['posts'].insert(0, post)
    save_data(db)
    return jsonify({'success': True, 'post': post})

# 댓글 작성 API
@app.route('/api/posts/<post_id>/comments', methods=['POST'])
def add_comment(post_id):
    data = request.json or {}
    comment_text = data.get('comment', '').strip()
    author = data.get('author', '익명')
    
    if not comment_text:
        return jsonify({'success': False, 'message': '내용을 입력하세요.'}), 400

    posts = db.get('posts', [])
    target_post = next((p for p in posts if p.get('id') == post_id), None)
    
    if target_post:
        if 'comments' not in target_post:
            target_post['comments'] = []
        target_post['comments'].append({'author': author, 'text': comment_text})
        save_data(db)
        return jsonify({'success': True, 'post': target_post})
        
    return jsonify({'success': False, 'message': '게시물을 찾을 수 없습니다.'}), 404

# 파일 업로드 및 구글 드라이브 연동 API
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

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)
