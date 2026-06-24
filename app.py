from flask import Flask, render_template, session as flask_session
from models import init_db
from config import SECRET_KEY
from views.user import user_bp
from views.admin import admin_bp

app = Flask(__name__)
app.secret_key = SECRET_KEY

app.register_blueprint(user_bp)
app.register_blueprint(admin_bp)

# Inject admin username into dashboard context
@app.context_processor
def inject_globals():
    return {
        'session_username': flask_session.get('admin_username', '')
    }

if __name__ == '__main__':
    init_db()
    print("OK - 数据库初始化完成")
    print("Front: http://127.0.0.1:5000")
    print("Admin: http://127.0.0.1:5000/admin")
    print("Default admin: admin / admin123")
    app.run(host='0.0.0.0', port=5000, debug=True)