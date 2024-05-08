from flask import Flask, request, jsonify, send_from_directory, Response, render_template
from routes import blueprint as app_blueprint

app = Flask(__name__)
app.register_blueprint(app_blueprint)

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)


