import os
from flask import Flask, render_template, request, jsonify, send_from_directory
from werkzeug.utils import secure_filename
from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload

app = Flask(__name__)

# ================= 설정 영역 =================
UPLOAD_FOLDER = 'static/uploads'
os.makedirs(UPLOAD_FOLDER, exist_ok=True)
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER

# 구글 드라이브 폴더 ID (사용 중인 폴더 ID 유지)
GOOGLE_DRIVE_FOLDER_ID = '1capKURBOv5TpP0DgNvagP8VQYfnLlBtl'

# Render 시크릿 파일 및 다양한 환경의 인증서 경로 우선순위 탐색
POSSIBLE_CRED_PATHS = [
    os.environ.get('GOOGLE_CREDENTIALS_PATH'),
    '/etc/secrets/google_creds.json',
    'google_creds.json'
]

GOOGLE_CREDENTIALS_PATH = None
for path in POSSIBLE_CRED_PATHS:
    if path and os.path.exists(path):
        GOOGLE_CREDENTIALS_PATH = path
        break
# ============================================

def get_drive_service():
    """구글 드라이브 API 클라이언트 인증 및 생성"""
    try:
        if GOOGLE_CREDENTIALS_PATH and os.path.exists(GOOGLE_CREDENTIALS_PATH):
            print(f"Using credentials from: {GOOGLE_CREDENTIALS_PATH}")
            SCOPES = ['https://www.googleapis.com/auth/drive.file']
            creds = service_account.Credentials.from_service_account_file(
                GOOGLE_CREDENTIALS_PATH, scopes=SCOPES
            )
            return build('drive', 'v3', credentials=creds)
        else:
            print("Google Drive Credentials file not found in any expected path!")
    except Exception as e:
        print(f"Google Drive Authentication Error: {e}")
    return None

def upload_file_to_drive(file_path, original_filename):
    """구글 드라이브로 파일을 업로드하고 공유 링크를 반환"""
    service = get_drive_service()
    if not service:
        print("Drive service is not available. Saving locally only.")
        return None

    try:
        file_metadata = {
            'name': original_filename,
            'parents': [GOOGLE_DRIVE_FOLDER_ID]
        }
        media = MediaFileUpload(file_path, resumable=True)
        
        # 파일 업로드 실행
        file = service.files().create(
            body=file_metadata,
            media_body=media,
            fields='id, webViewLink, webContentLink'
        ).execute()

        file_id = file.get('id')
        print(f"File successfully uploaded to Google Drive. ID: {file_id}")

        # 업로드된 파일에 대해 누구나 읽을 수 있는 권한 부여 (필요 시 선택)
        try:
            service.permissions().create(
                fileId=file_id,
                body={'role': 'reader', 'type': 'anyone'}
            ).execute()
        except Exception as perm_err:
            print(f"Permission setting warning: {perm_err}")

        # 웹뷰 링크 반환 (없을 경우 웹서버의 로컬 링크나 기본 링크 대체)
        return file.get('webViewLink')

    except Exception as e:
        print(f"Google Drive Upload Error: {e}")
        return None

# ================= 라우트 영역 (예시) =================
@app.route('/')
def index():
    return render_template('index.html')

@app.route('/upload', methods=['POST'])
def upload_file():
    if 'file' not in request.files:
        return jsonify({'error': 'No file part'}), 400
    
    file = request.files['file']
    if file.filename == '':
        return jsonify({'error': 'No selected file'}), 400

    if file:
        filename = secure_filename(file.filename)
        local_path = os.path.join(app.config['UPLOAD_FOLDER'], filename)
        file.save(local_path)

        # 1. 구글 드라이브 업로드 시도
        drive_link = upload_file_to_drive(local_path, filename)

        # 2. 드라이브 업로드가 성공하면 드라이브 링크 사용, 실패 시 로컬 파일 경로 사용
        final_url = drive_link if drive_link else f"/{UPLOAD_FOLDER}/{filename}"

        return jsonify({
            'success': True,
            'file_url': final_url,
            'filename': filename
        })

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)
