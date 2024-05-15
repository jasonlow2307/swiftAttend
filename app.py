from flask import Flask, request, jsonify, send_from_directory, Response, render_template, session
from routes import blueprint 
import json

app = Flask(__name__)

def escapejs(value):
    return json.dumps(value)

app.secret_key = 'secret'
app.register_blueprint(blueprint)

app.jinja_env.filters['escapejs'] = escapejs

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)