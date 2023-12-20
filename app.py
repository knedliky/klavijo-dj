import json
import logging
from os import environ
from pathlib import Path

import requests
import spotipy
from klaviyo_api import KlaviyoAPI
from litestar import Litestar, Request, Response, get, post
from litestar.background_tasks import BackgroundTask
from litestar.contrib.htmx.request import HTMXRequest
from litestar.contrib.htmx.response import HTMXTemplate
from litestar.contrib.jinja import JinjaTemplateEngine
from litestar.openapi.config import OpenAPIConfig
from litestar.response import Template
from litestar.static_files.config import StaticFilesConfig
from litestar.template.config import TemplateConfig
from openai import OpenAI
from spotipy.oauth2 import SpotifyOAuth

from models import Flow, User

logger = logging.getLogger(__name__)

# Initialise Models
USER_DB: dict[str, User] = {}
FLOW_PLAYLIST_DB: dict[str, Flow] = {}

# Initialise Clients
openai = OpenAI()
klaviyo = KlaviyoAPI(
    environ["KLAVIYO_API"], max_delay=60, max_retries=3, test_host=None
)
spotify = spotify = spotipy.Spotify(
    auth_manager=SpotifyOAuth(
        client_id=environ["SPOTIPY_CLIENT_ID"],
        client_secret=environ["SPOTIPY_CLIENT_SECRET"],
        redirect_uri="http://127.0.0.1/callback",
        scope="playlist-modify-public",
    )
)

#################
### Functions ###
#################


# Initialise Flow Playlist Database
def populate_db(DB: dict[str, Flow] = FLOW_PLAYLIST_DB):
    flows = klaviyo.Flows.get_flows()["data"]
    for flow in flows:
        DB[flow["id"]] = {
            "id": flow["id"],
            "name": flow["attributes"]["name"],
            "keywords": [],
            "sample_playlist_url": "",
            "active": False,
        }


# Get Flow Playlist Database
def get_db() -> dict[str, Flow]:
    return FLOW_PLAYLIST_DB


# Get Flow
def get_flow(id: str) -> Flow:
    logging.info(f"retrieving {FLOW_PLAYLIST_DB.get(id)}!")
    return FLOW_PLAYLIST_DB.get(id)


# Insert into Flow Playlist Database
def insert_db(id: str, keywords: list[str], sample_playlist_url: str):
    if id in FLOW_PLAYLIST_DB:
        FLOW_PLAYLIST_DB[id].update(
            {
                "id": id,
                "keywords": keywords,
                "sample_playlist_url": sample_playlist_url,
                "active": True,
            }
        )
        logging.info(f"inserted {FLOW_PLAYLIST_DB[id]}!")
    return FLOW_PLAYLIST_DB


# Delete from Flow Playlist Database
def delete_db(id: str):
    if id in FLOW_PLAYLIST_DB:
        FLOW_PLAYLIST_DB[id].update(
            {
                "id": id,
                "keywords": [],
                "sample_playlist_url": "",
                "active": False,
            }
        )
        logging.info(f"deleted {FLOW_PLAYLIST_DB[id]}!")
    return FLOW_PLAYLIST_DB


# Get ChatGPT output for Mood
async def gpt_mood(keywords: list[str]) -> str:
    completion = openai.chat.completions.create(
        model="gpt-3.5-turbo",
        messages=[
            {
                "role": "system",
                "content": "You are a poetic assistant, \
                skilled in writing concise yet emotional prose. \
                Your role is to write a single sentence. \
                You will have a set of keywords to create your concise, \
                descriptive sentence. Based on the keywords, describe a mood. \
                Do not use the word mood or genre. \
                The description will be used to describe a music playlist for someone you care about.",
            },
            {"role": "user", "content": str(keywords)},
        ],
    )
    return completion.choices[0].message.content


# Get ChatGPT output for Playlist in JSON format
async def gpt_playlist(description: str) -> dict:
    response = openai.chat.completions.create(
        model="gpt-4-1106-preview",
        response_format={"type": "json_object"},
        messages=[
            {
                "role": "system",
                "content": "You are a helpful assistant designed to output perfectly formatted JSON. \
                You role is to return a list of song names and song artists, as well as a playlist title. \
                You will have a description to create your list. \
                Based on the description, create a list of songs. \
                Do not use the word song or artist. \
                The list will be used for a music playlist to someone you care about. \
                Do not use a list you have already used. \
                There should be a key for the playlist_title and tracks. \
                Tracks should be a list of song titles and artist.",
            },
            {
                "role": "assistant",
                "content": 'Are you sure that it is valid? Make sure there is a key for playlist_title and tracks. \
                tracks is a list of song and artist. \
                It should look like this: \
                {"playlist_title": "My Playlist", \
                "tracks": [{"song": "Song Name", "artist": "Artist Name"}, {"song": "Song Name", "artist": "Artist Name"}]}',
            },
            {
                "role": "user",
                "content": description,
            },
        ],
    )

    return {
        **json.loads(response.choices[0].message.content),
        "description": description,
    }


# Initialise Spotify playlist and return the playlist JSON object
def initialise_playlist(user: str, title: str, description: str) -> dict:
    return spotify.user_playlist_create(user, title, description=description)


# Search and add tracks to playlist to a users playlist (One by one)
async def add_track_to_playlist(user: str, track: dict, playlist_id: str):
    # Search for most similar track and artist, to minimize hallucinations
    artist = track["artist"]
    title = track["title"]
    spotify_track = spotify.search(
        q=f"artist:{artist} track:{title}", limit=1, type="track"
    )

    try:
        # Add track to playlist
        track_id = spotify_track["tracks"]["items"][0]["id"]
        spotify.user_playlist_add_tracks(user, playlist_id, [track_id])
    except IndexError:
        # Handle the IndexError gracefully
        logging.error(f"Could not find track: {track} by {artist}in Spotify")
        # You can choose to skip adding the track or take any other appropriate action
    logging.info(f"Added track: {track} by {artist} to playlist")


# Create full Spotify playlist from GPT JSON, returning a URL link for the playlist
async def create_spotify_playlist(
    user: str, gpt_playlist: dict
) -> tuple[str, str, str]:
    # Initialise the playlist
    title = gpt_playlist["playlist_title"]
    description = gpt_playlist["description"]
    playlist = initialise_playlist(user, title, description)

    # For every song recommended by GPT, search and add to Spotify playlist
    for song in gpt_playlist["tracks"]:
        await add_track_to_playlist(user, song, playlist["id"])

    # Finally, get playlist link
    title = playlist["name"]
    url = playlist["external_urls"]["spotify"]
    description = playlist["description"]

    return title, description, url


# Trigger a Place Order Event
def trigger_order(email: str):
    url = f"https://a.klaviyo.com/client/events/?company_id={environ.get('KLAVIYO_COMPANY_ID')}"
    headers = {
        "accept": "application/json",
        "content-type": "application/json",
        "revision": "2023-12-15",
    }
    event_json = {
        "data": {
            "type": "event",
            "attributes": {
                "properties": {
                    "Type": "Election",
                    "amount": 500.00,
                    "Category": "Annual",
                },
                "metric": {
                    "data": {"type": "metric", "attributes": {"name": "Placed Order"}}
                },
                "profile": {
                    "data": {
                        "type": "profile",
                        "attributes": {"email": email},
                    }
                },
            },
        }
    }

    response = requests.post(url, headers=headers, json=event_json)
    return response


# Create an Event to trigger the custom Email Flow
def trigger_email(title: str, url: str, description: str, email: str):
    url = f"https://a.klaviyo.com/client/events/?company_id={environ.get('KLAVIYO_COMPANY_ID')}"
    headers = {
        "accept": "application/json",
        "content-type": "application/json",
        "revision": "2023-12-15",
    }
    event_json = {
        "data": {
            "type": "event",
            "attributes": {
                "properties": {
                    "title": title,
                    "url": url,
                    "description": description,
                },
                "metric": {
                    "data": {
                        "type": "metric",
                        "attributes": {"name": "Playlist Created"},
                    }
                },
                "profile": {
                    "data": {
                        "type": "profile",
                        "attributes": {"email": email},
                    }
                },
            },
        }
    }
    response = requests.post(url, headers=headers, json=event_json)
    return response


#################
### Endpoints ###
#################


# Index route
@get("/")
async def index() -> Template:
    logger.info("Returning home page")
    return Template(template_name="base.html", context={})


# Route for initialising Database
@get("/db/init")
async def db_init() -> Response:
    populate_db()
    return Response(content="", status_code=204)


# Route for inserting into Database
@post("/db")
async def db_insert(request: HTMXRequest) -> Template:
    form_data = await request.form()
    id = form_data.get("flow-id")
    keywords = form_data.get("keywords").split(",")
    json = insert_db(id, keywords, "")
    logging.info(f"Inserted flow playlist into DB.\n{json}")
    return HTMXTemplate(template_name="content/table.html", context={"flows": json})


# Route for populating Flow Playlist table with DB
@get("/flow_playlist_table")
async def flow_playlist_table() -> Template:
    json = get_db()
    logger.info(f"Returning Flow Playlist Table.\n{json}")
    return HTMXTemplate(template_name="content/table.html", context={"flows": json})


# Klavijo DJ main component
@get("/dj")
async def klavijo_dj() -> Template:
    logger.info("Returning Klavijo DJ page")
    return Template(template_name="poster.html", context={})


# Route to generate form data to be used for downstream
# event handling and form rendering. Add form is used for
# creating event listeners on Klaviyo Flows, Edit form is to edit
# existing event listeners, Event form is for creating custom
# events to test the event listeners and the Test form is to
# test GPTs playlist output, in order to sense check the keywords
# being used are creating good playlists.
@post("/form")
async def form(request: HTMXRequest) -> Template:
    form_type = request.headers.get("HX-Trigger")
    form_data = await request.form()
    flow_id = form_data.get("flow-id")
    flow = get_flow(flow_id)

    if form_type == "add-button":
        return HTMXTemplate(template_name="forms/add.html", context={"flow": flow})
    if form_type == "edit-button":
        return HTMXTemplate(template_name="forms/edit.html", context={"flow": flow})
    if form_type == "event-button":
        return HTMXTemplate(template_name="forms/event.html", context={"flow": flow})
    if form_type == "test-button":
        return HTMXTemplate(template_name="forms/test.html", context={"flow": flow})


# Route to receieve keywords and return a recommended playlist
# from GPT.
@post("/playlist")
async def playlist(request: HTMXRequest) -> Template:
    form_data = await request.form()
    keywords = form_data.get("keywords")
    description = await gpt_mood(keywords)
    playlist = await gpt_playlist(description)
    logger.info(f"GPT mood created: {description}\nGPT playlist created: {playlist}")
    context = {"keywords": keywords, "description": description, "playlist": playlist}
    return HTMXTemplate(
        template_name="partials/table_gpt_playlist.html",
        context={"playlist": context},
    )


# Event listener to Trigger a Sample Purchase Order
@post("event/test")
async def test_event(request: HTMXRequest) -> Response:
    email = "simon.karumbi@gmail.com"
    logger.info(f"Triggering test event using email: {email}...")
    trigger_order(email)
    return Response(content="", status_code=204)


# Listener for Klaviyo Webhooks
# If a flow is triggered and exists, create playlist
@post("/webhook/klaviyo")
async def klaviyo_webhook(request: Request) -> Response:
    json = await request.json()
    logging.info(f"Received webhook data: {json}")
    task = BackgroundTask(process_klaviyo_webhook, json=json)
    return Response(
        "Processing webhook...",
        background=task,
        status_code=202,
    )


# Process the webhook data asynchronously
async def process_klaviyo_webhook(json: dict):
    logger.info(f"Processing webhook data: {json}")
    id = json.get("flow_id")
    if FLOW_PLAYLIST_DB.get(id).get("active"):
        email = json.get("email")
        keywords = FLOW_PLAYLIST_DB.get(id).get("keywords")
        mood = await gpt_mood(keywords)
        logger.info(f"GPT mood created: {mood}")
        playlist = await gpt_playlist(mood)
        logger.info(f"GPT playlist created: {playlist}")
        spotify_playlist = await create_spotify_playlist(
            user=environ.get("SPOTIFY_USER"), gpt_playlist=playlist
        )
        title, description, url = spotify_playlist
        logger.info(f"Spotify playlist created: {title} at {url}")
        trigger_email(title=title, url=url, description=description, email=email)
        logger.info(f"Flow triggered to send personalised email to: {email}!")


app = Litestar(
    route_handlers=[
        index,
        klavijo_dj,
        flow_playlist_table,
        db_init,
        db_insert,
        form,
        playlist,
        test_event,
        klaviyo_webhook,
    ],
    request_class=HTMXRequest,
    openapi_config=OpenAPIConfig(
        title="Demo API",
        version="0.1.0",
    ),
    template_config=TemplateConfig(
        directory=Path("templates"), engine=JinjaTemplateEngine
    ),
    static_files_config=[
        StaticFilesConfig(directories=["static"], path="/static", name="static")
    ],
)
