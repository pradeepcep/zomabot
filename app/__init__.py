from flask import *

app = Flask(__name__)


@app.route('/')
def index():
    return 'Zomabot!'


@app.route('/webhook')
def webhook():
    return 'Zomabot webhook!'
