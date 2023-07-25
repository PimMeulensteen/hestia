import os
import telegram
import requests
import pickle
import json
import logging
import psycopg2
from psycopg2.extras import RealDictCursor
from bs4 import BeautifulSoup
from datetime import datetime
from asyncio import run
from targets import targets
from secrets import OWN_CHAT_ID, TOKEN, DB
from hestia import WORKDIR

BOT = telegram.Bot(TOKEN)

HOUSE_EMOJI = "\U0001F3E0"
LINK_EMOJI = "\U0001F517"

logging.basicConfig(
    format="%(asctime)s [%(levelname)s]: %(message)s",
    level=logging.WARNING,
    filename=WORKDIR + "hestia-scraper.log"
)

async def main():
    if os.path.exists(WORKDIR + "HALT"):
        logging.warning("Scraper is halted.")
        exit()

    for item in targets:
        try:
            await scrape_site(item)
        except BaseException as e:
            await handle_exception(item["site"], item["savefile"], e)

async def handle_exception(site, savefile, e):
    error = f"[{site}: {savefile}] {repr(e)}"
    last_error = "["

    # If the error was already logged, do not log it again
    # This is to prevent the same error popping up every time cron runs the scraper
    if os.path.exists(WORKDIR + "error.log"):
        with open(WORKDIR + "error.log", 'r') as err:
            last_error = err.readlines()[-1]

    if last_error[last_error.index('['):-1] != error:
        logging.error(error)
        await BOT.send_message(text=error, chat_id=OWN_CHAT_ID)

async def broadcast(new_homes):

    #with open(WORKDIR + "subscribers", 'rb') as subscribers_file:
    #    subs = pickle.load(subscribers_file)
       
    subs = set()

    subquery = DB.cursor(cursor_factory=RealDictCursor)
    subquery.execute("SELECT * FROM subscribers WHERE subscription_expiry IS NOT NULL AND telegram_enabled = true")

    # Overwrite subs if DEVMODE is enabled
    if os.path.exists(WORKDIR + "DEVMODE"):
        logging.warning("Dev mode is enabled.")
        subs = set([OWN_CHAT_ID])

    for home in new_homes:
        for sub in subquery.fetchall():
            # TODO check if home is within user parameters
            
            message = f"{HOUSE_EMOJI} {home[0]}\n"
            message += f"{LINK_EMOJI} {home[1]}"
            
            # If a user blocks the bot, this would throw an error and kill the entire broadcast
            try:
                await BOT.send_message(text=message, chat_id=sub["telegram_id"])
            except:
                logging.warning(f"Error transmitting to user {sub['username']}")
                pass

async def scrape_site(item):
    site = item["site"]
    savefile = item["savefile"]
    url = item["url"]
    method = item["method"]
    
    if method == "GET":
        r = requests.get(url)
    elif method == "POST":
        r = requests.post(url, json=item["data"], headers=item["headers"])
    
    houses = []
    prev_homes = set()
    new_homes = set()
    
    # Create savefile if it does not exist
    if not os.path.exists(WORKDIR + savefile):
        with open(WORKDIR + savefile, 'wb') as w:
            pickle.dump(set([]), w)

    # Get the previously broadcasted homes
    with open(WORKDIR + savefile, 'rb') as prev_homes_file:
        prev_homes = pickle.load(prev_homes_file)
        
    # TODO save homes to db
    # TODO get previously broadcasted homes of current agent from db
    
    if not r.status_code == 200:
        raise ConnectionError(f"Got a non-OK status code: {r.status_code}.")
        
    if site == "vesteda":
        results = json.loads(r.content)["results"]["items"]
        
        for res in results:
            # Filter non-available properties
            # Status 0 seems to be that the property is a project/complex
            if res["status"] != 1:
                continue
                
            address = f"{res['street']} {res['houseNumber']}"
            if res["houseNumberAddition"] is not None:
                address += f" {res['houseNumberAddition']}"
            link = "https://vesteda.com" + res["url"]
            if address not in prev_homes:
                new_homes.add((address, link))
                prev_homes.add(address)
                
    elif site == "vbt":
        results = json.loads(r.content)["houses"]
        
        for res in results:
            # Filter Bouwinvest results to not have double results
            if res["isBouwinvest"]:
                continue
        
            address = res["address"]["house"]
            link = res["source"]["externalLink"]
            if address not in prev_homes:
                new_homes.add((address, link))
                prev_homes.add(address)
        
    elif site == "alliantie":
        results = json.loads(r.content)["data"]
        
        for res in results:
            # Filter results not in selection because why the FUCK would you include
            # parameters and then not actually use them in your FUCKING API
            if not res["isInSelection"]:
                continue
                
            address = res["address"]
            link = "https://ik-zoek.de-alliantie.nl/" + res["url"].replace(" ", "%20")
            if address not in prev_homes:
                new_homes.add((address, link))
                prev_homes.add(address)
        
    elif site == "woningnet":
        results = json.loads(r.content)["Resultaten"]
        
        for res in results:
            # Filter senior & family priority results
            if res["WoningTypeCssClass"] == "Type03":
                continue
                
            address = res["Adres"]
            link = "https://www.woningnetregioamsterdam.nl" + res["AdvertentieUrl"]
            if address not in prev_homes:
                new_homes.add((address, link))
                prev_homes.add(address)
    
    elif site == "bouwinvest":
        results = json.loads(r.content)["data"]

        for res in results:
            # Filter non-property results
            if res["class"] == "Project":
                continue

            address = res["name"]
            link = res["url"]
            if address not in prev_homes:
                new_homes.add((address, link))
                prev_homes.add(address)

    elif site == "ikwilhuren":
        results = BeautifulSoup(r.content, "html.parser").find_all("li", class_="search-result")

        for res in results:
            address = str(res.find(class_="street-name").contents[0])
            link = res.find(class_="search-result-title").a["href"]
            if address not in prev_homes:
                new_homes.add((address, link))
                prev_homes.add(address)

    # Write new homes to savefile
    with open(WORKDIR + savefile, 'wb') as prev_homes_file:
        pickle.dump(prev_homes, prev_homes_file)
        
    # TODO write new homes to db

    await broadcast(new_homes)


if __name__ == '__main__':
    run(main())
