import sqlite3
from werkzeug.security import generate_password_hash, check_password_hash

db = sqlite3.connect('instance/sms.db')
h = generate_password_hash('a5666888')
print('Werkzeug version:', __import__('werkzeug').__version__)
print('Hash:', h[:60])

# Delete old and insert new admin
db.execute("DELETE FROM admins")
db.execute("INSERT INTO admins (username, password) VALUES (?,?)", ('1340647127@qq.com', h))
db.commit()

# Verify
r = db.execute("SELECT username, password FROM admins").fetchone()
print('Username:', r[0])
print('Verify login:', check_password_hash(r[1], 'a5666888'))
db.close()