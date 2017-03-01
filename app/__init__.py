from flask import *
import os

app = Flask(__name__)


# Some tokens and keys used by the app.
app.config['VERIFY_TOKEN'] = '<you could hard-code your token here>'
# Or set an environment variable to override it.
if os.environ.get('VERIFY_TOKEN'):
    app.config['VERIFY_TOKEN'] = os.environ.get('VERIFY_TOKEN')


@app.route('/')
def index():
    return 'Zomabot!'


@app.route('/webhook', methods=['GET', 'POST'])
def webhook():
    if request.args.get('hub.verify_token', '') == app.config['VERIFY_TOKEN']:
        return request.args.get('hub.challenge')
    return 'Authentication failed', 403
