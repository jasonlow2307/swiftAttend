from flask import Flask, request, jsonify, send_from_directory, Response, render_template, session
from routes import blueprint as app_blueprint

app = Flask(__name__)
app.secret_key = 'secret'
app.register_blueprint(app_blueprint)

@app.before_request
def clear_session():
    session.clear()
    
if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)
