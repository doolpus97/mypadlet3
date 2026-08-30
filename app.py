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
# 1. 구글 드라이브 폴더 ID를 아래에 직접 입력하세요.
GOOGLE_DRIVE_FOLDER_ID = '1capKURBOv5TpP0DgNvagP8VQYfnLlBtl'

# 2. Render의 Secret File 경로 (/etc/secrets/google_creds.json)를 기본 참조하며, 
#    로컬 실행 시에는 같은 폴더의 'google_creds.json'을 읽어옵니다.
GOOGLE_CREDENTIALS_PATH = os.environ.get('GOOGLE_CREDENTIALS_PATH', '/etc/secrets/google_creds.json')
if not os.path.exists(GOOGLE_CREDENTIALS_PATH):
    GOOGLE_CREDENTIALS_PATH = 'google_creds.json'
# =========================================================

def get_drive_service():
    if not GOOGLE_CREDENTIALS_PATH or not os.path.exists(GOOGLE_CREDENTIALS_PATH):
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

@app.route('/upload', methods=['POST'])
def upload_files():
    files = request.files.getlist('files')
    uploaded_urls = []
    uploaded_files = [] 
    
    drive_service = get_drive_service()

    for file in files:
        if file and file.filename != '':
            ext = os.path.splitext(file.filename)[1]
            if not ext: ext = '.png'
            
            save_name = f"{int(time.time() * 1000)}_{os.urandom(4).hex()}{ext}"
            filepath = os.path.join(app.config['UPLOAD_FOLDER'], save_name)
            file.save(filepath)
            
            # Google Drive 연동 처리
            if drive_service and GOOGLE_DRIVE_FOLDER_ID and GOOGLE_DRIVE_FOLDER_ID != '여기에_구글_드라이브_폴더_ID_입력':
                try:
                    file_metadata = {'name': save_name, 'parents': [GOOGLE_DRIVE_FOLDER_ID]}
                    media = MediaFileUpload(filepath, resumable=True)
                    drive_file = drive_service.files().create(
                        body=file_metadata, 
                        media_body=media, 
                        fields='id, webContentLink'
                    ).execute()
                    
                    # 업로드 파일 권한 변경 (누구나 보기 가능)
                    drive_service.permissions().create(
                        fileId=drive_file.get('id'),
                        body={'type': 'anyone', 'role': 'reader'}
                    ).execute()
                    
                    url = drive_file.get('webContentLink')
                    
                    # 임시 로컬 파일 삭제
                    os.remove(filepath)
                except Exception as e:
                    print(f"Drive Upload Error: {e}")
                    url = f"/static/uploads/{save_name}"
            else:
                url = f"/static/uploads/{save_name}"
                
            uploaded_urls.append(url)
            uploaded_files.append({"url": url, "name": file.filename})

    return jsonify({'urls': uploaded_urls, 'files': uploaded_files})

# ================= 백엔드 API (서버 동기화) =================

@app.route('/api/login/teacher', methods=['POST'])
def login_teacher():
    data = request.json or {}
    teacher_id = data.get('teacherId', '').strip()
    teacher_pw = data.get('teacherPw', '').strip()
    
    if not teacher_id:
        return jsonify({'success': False, 'message': '아이디를 입력하세요.'}), 400
        
    if teacher_id not in db['users']:
        db['users'][teacher_id] = teacher_pw
        save_data(db)
    
    return jsonify({'success': True, 'teacherId': teacher_id})

@app.route('/api/boards', methods=['GET'])
def get_boards():
    teacher_id = request.args.get('teacherId', '').strip()
    if teacher_id:
        teacher_boards = [b for b in db['boards'] if b.get('owner') == teacher_id]
        return jsonify({'boards': teacher_boards})
    return jsonify({'boards': db['boards']})

@app.route('/api/boards/by_code', methods=['GET'])
def get_board_by_code():
    code = request.args.get('code', '').strip()
    board = next((b for b in db['boards'] if b.get('code') == code), None)
    if board:
        return jsonify({'success': True, 'board': board})
    return jsonify({'success': False, 'message': '입장 코드에 해당하는 게시판이 없습니다.'}), 404

@app.route('/api/boards', methods=['POST'])
def create_board():
    data = request.json or {}
    title = data.get('title', '').strip()
    code = data.get('code', '').strip()
    teacher_id = data.get('teacherId', '').strip()
    
    if not title or not code:
        return jsonify({'success': False, 'message': '제목과 코드를 입력하세요.'}), 400
        
    new_board = {
        'id': f"board_{int(time.time()*1000)}",
        'title': title,
        'code': code,
        'owner': teacher_id
    }
    db['boards'].append(new_board)
    save_data(db)
    return jsonify({'success': True, 'board': new_board})

@app.route('/api/boards/code', methods=['PUT'])
def update_board_code():
    data = request.json or {}
    board_title = data.get('title', '').strip()
    new_code = data.get('code', '').strip()
    
    for b in db['boards']:
        if b['title'] == board_title:
            b['code'] = new_code
            break
    save_data(db)
    return jsonify({'success': True})

@app.route('/api/posts', methods=['GET'])
def get_posts():
    board_title = request.args.get('boardTitle', '').strip()
    posts = db['posts'].get(board_title, [])
    return jsonify({'posts': posts})

@app.route('/api/posts', methods=['POST'])
def add_post():
    data = request.json or {}
    board_title = data.get('boardTitle', '').strip()
    if not board_title:
        return jsonify({'success': False, 'message': '게시판 정보가 필요합니다.'}), 400
        
    if board_title not in db['posts']:
        db['posts'][board_title] = []
        
    post = {
        'postId': f"post_{int(time.time()*1000)}_{os.urandom(2).hex()}",
        'sectionId': data.get('sectionId'),
        'author': data.get('author'),
        'title': data.get('title'),
        'content': data.get('content'),
        'imgs': data.get('imgs', []),
        'links': data.get('links', []),
        'attachedFiles': data.get('attachedFiles', []),
        'comments': []
    }
    db['posts'][board_title].insert(0, post)
    save_data(db)
    return jsonify({'success': True, 'post': post})

@app.route('/api/posts/move', methods=['PUT'])
def move_post():
    data = request.json or {}
    board_title = data.get('boardTitle', '').strip()
    post_id = data.get('postId', '').strip()
    new_section = data.get('sectionId', '').strip()
    
    posts = db['posts'].get(board_title, [])
    for p in posts:
        if p['postId'] == post_id:
            p['sectionId'] = new_section
            break
    save_data(db)
    return jsonify({'success': True})

@app.route('/api/posts/edit', methods=['PUT'])
def edit_post():
    data = request.json or {}
    board_title = data.get('boardTitle', '').strip()
    post_id = data.get('postId', '').strip()
    new_title = data.get('title')
    new_content = data.get('content')
    new_imgs = data.get('imgs')
    new_links = data.get('links')
    new_attachedFiles = data.get('attachedFiles')
    
    posts = db['posts'].get(board_title, [])
    for p in posts:
        if p['postId'] == post_id:
            p['title'] = new_title
            p['content'] = new_content
            if new_imgs is not None:
                p['imgs'] = new_imgs
            if new_links is not None:
                p['links'] = new_links
            if new_attachedFiles is not None:
                p['attachedFiles'] = new_attachedFiles
            break
    save_data(db)
    return jsonify({'success': True})

@app.route('/api/posts', methods=['DELETE'])
def delete_post():
    data = request.json or {}
    board_title = data.get('boardTitle', '').strip()
    post_id = data.get('postId', '').strip()
    
    if board_title in db['posts']:
        db['posts'][board_title] = [p for p in db['posts'][board_title] if p['postId'] != post_id]
        save_data(db)
    return jsonify({'success': True})

@app.route('/api/comments', methods=['POST'])
def add_comment():
    data = request.json or {}
    board_title = data.get('boardTitle', '').strip()
    post_id = data.get('postId', '').strip()
    author = data.get('author', '').strip()
    text = data.get('text', '').strip()
    
    posts = db['posts'].get(board_title, [])
    for p in posts:
        if p['postId'] == post_id:
            if 'comments' not in p:
                p['comments'] = []
            p['comments'].append({'author': author, 'text': text})
            break
    save_data(db)
    return jsonify({'success': True})

if __name__ == '__main__':
    port = int(os.environ.get("PORT", 5000))
    app.run(host='0.0.0.0', port=port)