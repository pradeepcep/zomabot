from flask import *
import requests
import json
import os

app = Flask(__name__)


# To make testing easier.
DEBUG = False
if os.environ.get('ZOMABOT_DEBUG') and os.environ.get('ZOMABOT_DEBUG') == '1':
    DEBUG = True


def simple_log(log_message):
    '''
    Print the `log_message` to the console if in DEBUG mode.
    '''
    if DEBUG:
        print log_message


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
    # Get the posted data.
    message_response = json.loads(request.get_data())

    # Then, extract the message text.
    sender_id = message_response['entry'][0]['messaging'][0]['sender']['id']
    message_body = message_response['entry'][0]['messaging'][0]['message']
    simple_log("sender_id: %s\nmessage_body: %s" % (sender_id, message_body))
    post_reply(sender_id, message_body)
    return '', 200


# Some functions to make life easier.
def send_message(to_id, message='', quick_replies=[], list_elements=[]):
    '''
    Send the specified `message` to the user with ID `to_id`.

    Quick replies that are specified in the list of `quick_replies` are sent
    along with the `message`. Currently supported quick replies:

        - `location` Ask for Location.

    List elements that are listed in `list_elements` will be shown as a
    simple list. If set, this will replace the `text`.

    Returns `True` if message is sent successfully, `False` otherwise.
    '''
    quick_replies_data = []
    for qreply in quick_replies:
        if qreply == 'location':
            quick_replies_data.append({"content_type": "location"})

    message_data = {
        "recipient": {
            "id": to_id,
        },
        "message": {
            "text": message,
        }
    }

    if quick_replies_data:
        message_data['message']['quick_replies'] = quick_replies_data

    # In case it's a list.
    if list_elements:
        message_data = {
            "recipient": {
                "id": to_id,
            },
            "message": {
                "attachment": {
                    "type": "template",
                    "payload": {
                        "template_type": "list",
                        "top_element_style": "compact",
                        "elements": list_elements,
                    }
                }
            }
        }

    r = requests.post(
        'https://graph.facebook.com/v2.6/me/messages',
        params={
            'access_token': app.config['PAGE_TOKEN']
        },
        data=json.dumps(message_data),
        headers={
            "Content-Type": "application/json",
        })
    simple_log("Sending response: %s\n" % (message))
    simple_log(r.text)
    return r.status_code == requests.codes.ok


def post_reply(to_id, message_body):
    '''
    Generate and post a suitable reply to the user with ID `to_id`,
    for the given data in `message_body`.

    Returns `True` on successfully posting a reply. `False` otherwise.
    '''
    message = ''
    # If the message is just text.
    if message_body.get('text'):
        message = message_body['text'].lower()

        # Nearby restraunts.
        if ('near me' in message or 'nearby' in message) \
                and ('restaurants' in message or 'restaurant' in message):
            return send_message(
                to_id, 'Sure, where are you now?', ['location'])

        # Say 'hi'.
        if 'hi' in message or 'hey' in message:
            return send_message(to_id, 'Hey you!')

        # When we don't understand something.
        else:
            return send_message(to_id, 'Sorry, what was that again?')

    # If it's a non-text message, like location.
    elif message_body.get('attachments'):
        # Now determine the type of attachment.
        if message_body['attachments'][0].get('type') == 'location':
            lat = message_body['attachments'][
                0]['payload']['coordinates']['lat']
            lng = message_body['attachments'][
                0]['payload']['coordinates']['long']
            # Query the Zomato API.
            r = requests.get(
                'https://developers.zomato.com/api/v2.1/geocode',
                params={
                    'lat': lat,
                    'lon': lng,
                },
                headers={
                    'user-key': app.config['ZOMATO_API_KEY'],
                    "Content-Type": "application/json",
                })
            simple_log('Queried Zomato')
            simple_log(r.text)
            top_restaurants = geocode_to_list_elements(json.loads(r.text))
            send_message(to_id, 'Got your location!')
            if top_restaurants:
                send_message(
                    to_id, 'These are the top places near your location:')
                return send_message(to_id, list_elements=top_restaurants)
            return send_message(
                to_id,
                "Aw, snap! Couldn't find any places near you, sorry :/")
        # In case we don't support that attachment.
        else:
            return send_message(to_id, "Sorry, I don't understand that :/")

    # Neither `text` nor `attachment` are sent.
    else:
        simple_log('Neither text nor attachment set. No reply posted.')


def geocode_to_list_elements(response_data):
    '''
    Function to create a Messenger-style list template out of the response
    returned by the /gecode endpoint of Zomato API.
    '''
    elements = []
    for item in response_data.get('nearby_restaurants', []):
        element = {
            'title': item['restaurant']['name'],
            'image_url': item['restaurant']['featured_image'],
            'subtitle': item['restaurant']['location']['address'],
            'default_action': {
                'type': 'web_url',
                'url': item['restaurant']['menu_url'],
                'messenger_extensions': True,
                'webview_height_ratio': 'tall',
                'fallback_url': item['restaurant']['url']
            }
        }
        elements.append(element)

    return elements[:4]  # Because a maximum of four elements is only allowed.
