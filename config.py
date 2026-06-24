import os

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

SECRET_KEY = os.environ.get('SECRET_KEY', 'change-me-in-production')
DATABASE = os.path.join(BASE_DIR, 'sms.db')

# 默认管理员密码（首次登录可用）
ADMIN_USERNAME = 'admin'
ADMIN_PASSWORD = os.environ.get('ADMIN_PASSWORD', 'admin123')

# 站点基础URL（部署后通过环境变量设置）
SITE_URL = os.environ.get('SITE_URL', 'http://localhost:5000')
