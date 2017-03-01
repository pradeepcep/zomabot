from flask import *
import os

app = Flask(__name__)


# Some tokens and keys used by the app.
app.config['VERIFY_TOKEN'] = '<you could hard-code your token here>'
app.config['PAGE_TOKEN'] = '<you could hard-code your page token here>'
app.config['ZOMATO_API_KEY'] = '<your zomato api key>'

# Or set environment variables to override them.
if os.environ.get('VERIFY_TOKEN'):
    app.config['VERIFY_TOKEN'] = os.environ.get('VERIFY_TOKEN')
if os.environ.get('PAGE_TOKEN'):
    app.config['PAGE_TOKEN'] = os.environ.get('PAGE_TOKEN')
if os.environ.get('ZOMATO_API_KEY'):
    app.config['ZOMATO_API_KEY'] = os.environ.get('ZOMATO_API_KEY')


@app.route('/')
def index():
    return 'Zomabot!'


# GET request to the webhook is used for authentication.
@app.route('/webhook', methods=['GET'])
def webhook():
    if request.args.get('hub.verify_token', '') == app.config['VERIFY_TOKEN']:
        return request.args.get('hub.challenge')
    return 'Authentication failed', 403


# POST request to the webhook is used for events.
@app.route('/webhook', methods=['POST'])
def events():
    # For now, just log that we received something.
    print "Received a POST request!\n"
    return '', 200
