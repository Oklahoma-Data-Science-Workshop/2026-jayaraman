import requests
from requests.auth import HTTPBasicAuth
from config import Config
import base64
from datetime import datetime
import os

class NextcloudClient:
    def __init__(self):
        config = Config()
        self.base_url = config.NEXTCLOUD_URL
        self.webdav_url = config.NEXTCLOUD_WEBDAV_URL
        self.username = config.NEXTCLOUD_USERNAME
        self.password = config.NEXTCLOUD_PASSWORD
        self.base_folder = config.NEXTCLOUD_BASE_FOLDER
        self.auth = HTTPBasicAuth(self.username, self.password)
    
    def _ensure_folder(self, path):
        """Create folder if it doesn't exist"""
        url = f"{self.webdav_url}{path}"
        response = requests.request('MKCOL', url, auth=self.auth)
        return response.status_code in [201, 405]  # 405 means already exists
    
    def upload_attachment(self, email_id, topic, sender_email, received_at, file_data, filename):
        """
        Upload attachment to Nextcloud
        Path structure: /Email_Assistant/{topic}/{sender}/{YYYY-MM-DD}/{filename}
        """
        try:
            # Create folder structure
            date_str = received_at.strftime('%Y-%m-%d')
            sender_folder = sender_email.split('@')[0]  # Use email username
            
            folder_path = f"{self.base_folder}{topic}/{sender_folder}/{date_str}"
            
            # Create nested folders
            parts = folder_path.strip('/').split('/')
            current = ""
            for part in parts:
                current += f"/{part}"
                self._ensure_folder(current)
            
            # Upload file
            file_path = f"{folder_path}/{filename}"
            url = f"{self.webdav_url}{file_path}"
            
            # Decode base64 if needed
            if isinstance(file_data, str):
                file_content = base64.b64decode(file_data)
            else:
                file_content = file_data
            
            response = requests.put(url, data=file_content, auth=self.auth)
            
            if response.status_code in [201, 204]:
                return file_path
            else:
                raise Exception(f"Upload failed: {response.status_code}")
                
        except Exception as e:
            print(f"Nextcloud upload error: {e}")
            raise
    
    def create_share_link(self, file_path):
        """Create a public share link for a file"""
        try:
            url = f"{self.base_url}/ocs/v2.php/apps/files_sharing/api/v1/shares"
            headers = {
                'OCS-APIRequest': 'true',
                'Content-Type': 'application/x-www-form-urlencoded'
            }
            data = {
                'path': file_path,
                'shareType': 3,  # Public link
                'permissions': 1  # Read only
            }
            
            response = requests.post(url, data=data, headers=headers, auth=self.auth)
            
            if response.status_code == 200:
                import xml.etree.ElementTree as ET
                root = ET.fromstring(response.content)
                url_elem = root.find('.//url')
                if url_elem is not None:
                    return url_elem.text
            
            return None
            
        except Exception as e:
            print(f"Share link creation error: {e}")
            return None
