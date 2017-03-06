from flask import *
from celery import Celery
from wit import Wit
from redis import StrictRedis
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
app.config['CELERY_BROKER_URL'] = '<url for the broker you use>'
app.config['WITAI_TOKEN'] = '<your wit.ai token here>'
app.config['REDIS_DB_URL'] = '<redis db url eg. redis://localhost:6379/1>'

# Or set environment variables to override them.
if os.environ.get('VERIFY_TOKEN'):
    app.config['VERIFY_TOKEN'] = os.environ.get('VERIFY_TOKEN')
if os.environ.get('PAGE_TOKEN'):
    app.config['PAGE_TOKEN'] = os.environ.get('PAGE_TOKEN')
if os.environ.get('ZOMATO_API_KEY'):
    app.config['ZOMATO_API_KEY'] = os.environ.get('ZOMATO_API_KEY')
if os.environ.get('CELERY_BROKER_URL'):
    app.config['CELERY_BROKER_URL'] = os.environ.get('CELERY_BROKER_URL')
if os.environ.get('WITAI_TOKEN'):
    app.config['WITAI_TOKEN'] = os.environ.get('WITAI_TOKEN')
if os.environ.get('REDIS_DB_URL'):
    app.config['REDIS_DB_URL'] = os.environ.get('REDIS_DB_URL')


# Spin up Celery.
celery = Celery(app.name, broker=app.config['CELERY_BROKER_URL'])
celery.conf.update(app.config)

# Spin up WitAI.
wit = Wit(access_token=app.config['WITAI_TOKEN'])

# Spin up Redis.
redis = StrictRedis.from_url(app.config['REDIS_DB_URL'])


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
    post_reply.delay(sender_id, message_body)
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


def process_message(to_id, message):
    message_details = {
        'intent': None,
    }
    wit_response = wit.message(message)
    simple_log(str(wit_response))

    if wit_response.get('entities'):
        if wit_response['entities'].get('intent'):
            if wit_response['entities']['intent'][0].get('value'):
                message_details['intent'] = wit_response['entities'][
                        'intent'][0]['value']

    record_context(to_id, message_details['intent'])
    return message_details


def record_context(to_id, context):
    '''
    Records the context of a message, to be used by get_message_context()
    later.
    '''
    redis.rpush(str(to_id), context)
    return


def get_context(to_id):
    '''
    Function that guesses the context of the current message based on
    previous messages.

    Returns a string defining the context.
    Returns an empty string if the context cannot be defined.
    '''
    # Read the previous message's intent.
    context_list = redis.lrange(str(to_id), 0, -1)

    # If the previous message was a search, then the response is an answer
    # to our question about where the user is.
    if context_list[-1] == 'search':
        return 'location'

    # If the user mis-spells the location, or the Zomato API doesn't recognize
    # it.
    if context_list[-1] == 'None' and context_list[-2] == 'search':
        return 'location'

    return ''


def clear_context(to_id):
    '''
    Clear the context for a user. Any messages after this will be treated as a
    fresh conversation.
    '''
    redis.delete(str(to_id))


@celery.task
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

        message_context = get_context(to_id)
        message_details = process_message(to_id, message)
        simple_log(str(message_details))

        # Nearby restraunts.
        if message_details.get('intent') == 'search':
            return send_message(
                to_id, 'Sure, where are you now?', ['location'])

        # Say 'hi'.
        elif message_details.get('intent') == 'greeting':
            return send_message(to_id, 'Hey you!')

        # If the user replies with place name instead of tapping on
        # 'Send location', or cannot, as in the case of messenger on desktop.
        elif message_context == 'location':
            possible_coordinates = city_name_to_coordinates(message)
            if possible_coordinates:
                r = requests.get(
                    'https://developers.zomato.com/api/v2.1/geocode',
                    params={
                        'lat': possible_coordinates['lat'],
                        'lon': possible_coordinates['lon'],
                    },
                    headers={
                        'user-key': app.config['ZOMATO_API_KEY'],
                        "Content-Type": "application/json",
                    })
                simple_log('Queried Zomato #2')
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
            else:
                return send_message(
                    to_id,
                    'Sorry, I cannot find that place. '
                    'Maybe it\'s written differently?')

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


def city_name_to_coordinates(name):
    '''
    Gets the co-ordinates of a city so that it can be used with the /geocode
    endpoint.
    '''
    if name:
        r = requests.get(
            'https://developers.zomato.com/api/v2.1/locations',
            params={
                'query': name,
                'count': 1,
            },
            headers={
                'user-key': app.config['ZOMATO_API_KEY'],
                "Content-Type": "application/json",
            })
        simple_log('Queried Zomato for city name')
        simple_log(r.text)
        possible_location = json.loads(r.text)
        if possible_location.get('location_suggestions'):
            return {
                'lat': possible_location['location_suggestions'][
                        0]['latitude'],
                'lon': possible_location['location_suggestions'][
                        0]['longitude']
            }

    return {}
