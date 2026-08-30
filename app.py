import os
import time
from flask import Flask, render_template, request, jsonify
from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload

app = Flask(__name__)

# 업로드 임시 폴더 설정
UPLOAD_FOLDER = 'static/uploads'
os.makedirs(UPLOAD_FOLDER, exist_ok=True)
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER

# ================= 구글 드라이브 설정 =================
# ⭐️ 아래 빈칸에 본인의 구글 드라이브 폴더 ID를 직접 입력하세요.
# 예: '1A2B3C4D5E6F7G8H9I0J...'
GOOGLE_DRIVE_FOLDER_ID = '1capKURBOv5TpP0DgNvagP8VQYfnLlBtl'

GOOGLE_CREDENTIALS_PATH = os.environ.get('GOOGLE_CREDENTIALS_PATH', '/etc/secrets/google_creds.json')
if not os.path.exists(GOOGLE_CREDENTIALS_PATH):
    GOOGLE_CREDENTIALS_PATH = 'google_creds.json'
# =========================================================

def get_drive_service():
    """구글 드라이브 API 클라이언트 인증 및 생성"""
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
            # 구글 드라이브 서비스가 활성화되어 있고 폴더 ID가 올바르게 입력된 경우 업로드 시도
            if drive_service and folder_id and folder_id != '여기에_구글_드라이브_폴더_ID_입력':
                try:
                    file_metadata = {'name': save_name, 'parents': [folder_id]}
                    media = MediaFileUpload(filepath, resumable=True)
                    drive_file = drive_service.files().create(
                        body=file_metadata, 
                        media_body=media, 
                        fields='id, webContentLink, webViewLink'
                    ).execute()
                    
                    # 업로드된 파일 공개 권한 설정 (링크가 있는 누구나 뷰어)
                    drive_service.permissions().create(
                        fileId=drive_file.get('id'),
                        body={'type': 'anyone', 'role': 'reader'}
                    ).execute()
                    
                    url = drive_file.get('webViewLink') or drive_file.get('webContentLink')
                    
                    # 업로드 완료 후 로컬에 남은 임시 파일 삭제
                    if os.path.exists(filepath):
                        os.remove(filepath)
                except Exception as e:
                    print(f"Google Drive Upload Error: {e}")
            
            # 드라이브 업로드 실패 시 로컬 서버 경로로 대체
            if not url:
                url = f"/static/uploads/{save_name}"
                
            uploaded_urls.append(url)

    return jsonify({'success': True, 'urls': uploaded_urls})

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)
