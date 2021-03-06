import datetime
import pickle
import time
import os
import schedule
import requests
from lxml import html
from twilio.rest import Client

# Minutes between scraping
searchInterval = 1

# Twilio SMS API config
account_sid = 'AC8bd9f1713930d5c3a65e6ab592420dba'
auth_token = '82741da6122123696f5a4994a682f81d'
client = Client(account_sid, auth_token)


class TextSentLibrary:
    def __init__(self):
        self.library = list()

    def addListing(self, newListingID):
        self.library.append(newListingID)

    def newIDCheck(self, newID):
        listingIsUnknown = True
        for idCheck in self.library:
            if idCheck == newID:
                listingIsUnknown = False
                print("Hit found, text already sent!")
        return listingIsUnknown


# Define craigslist listing object
class Listing:
    def __init__(self, title, link, price, listID):
        self.title = str(title.lower())
        self.link = link
        self.price = price
        self.listingID = listID
        self.descriptiveText = ''
        # Try-catch block searches for more detail from each listing's specific page
        try:
            depthScrape = requests.get(self.link, timeout=10)
            subTree = html.fromstring(depthScrape.content)
            timeU = subTree.xpath(
                '/html/body/section/section/section/div[2]/p[3]/time[@class="date timeago"]/@datetime')
            timeP = subTree.xpath(
                '/html/body/section/section/section/div[2]/p[2]/time[@class="date timeago"]/@datetime')
            if len(timeU) == 0:
                if len(timeP) < 1:
                    print("                Time error! Marking post as deleted.")
                    self.title = "deleted"
                    print("Link to error page: ", self.link)
                    timeC = "2000-01-01 01:00:000"
                else:
                    timeC = timeP[0]
            else:
                timeC = timeU[0]
            self.listTime = datetime.datetime(int(timeC[0:4]), int(timeC[5:7]), int(timeC[8:10]), int(timeC[11:13]),
                                              int(timeC[14:16]), int(timeC[17:19]), 0)
            self.description = subTree.xpath('/html/body/section/section/section/section[@id="postingbody"]/text()['
                                             'normalize-space()]')

            # construct new list of strings for join function
            list_of_strings = [str(thing) for thing in self.description]
            self.description = "".join(list_of_strings)

            # Unclassified for now, may add in a future update
            self.classification = "Unclassified"

            # Collect all words in a listing, strip special characters, and store them as a string
            self.descriptiveText = str(self.title + self.description).replace(',', ' ').replace('\n', ' ').replace('.',
                                                                                                                   ' ')
            try:
                self.coverImageLink = str(subTree.xpath('/html/head/meta[9][@property="og:image"]/@content')[0])
            except IndexError as e:
                self.coverImageLink = "Unknown"

        except requests.exceptions.RequestException as e:
            print("Connection error:", e)
            self.listTime = "2000-01-01 01:00:000"
            self.description = "Could not retrieve item description!"
            self.classification = "Could not retrieve item classification!"


class Search:
    def __init__(self, location, searchTerms, keywordsPos, keyWordsNeg, minPrice, maxPrice, contactPhone):
        self.location = location
        self.searchTerms = searchTerms
        self.keywordsPos = keywordsPos + ' ' + searchTerms.replace('+', ' ')
        self.keywordsNeg = keyWordsNeg
        self.minPrice = minPrice
        self.maxPrice = maxPrice
        self.allObjects = list()
        self.hitObjects = list()
        self.contactNumber = contactPhone

    def scrape(self, enableTexting, IDlib):
        listingIndex = 0
        titles = list()
        links = list()
        prices = list()
        IDs = list()

        while True:
            try:
                r = requests.get("https://" + self.location + ".craigslist.org/search/sss?s=" + str(
                    listingIndex) + "&sort=date&query=" + self.searchTerms, timeout=10)
            except requests.exceptions.RequestException as e:
                print("Connection error:", e)
                return

            listingIndex = listingIndex + 120
            tree = html.fromstring(r.content)
            try:
                totalListings = int(
                    tree.xpath(
                        '/html/body/section/form/div[3]/div[3]/span[2]/span[3]/span[2][@class="totalcount"]/text()')[
                        0])
                shownListings = int(tree.xpath(
                    '/html/body/section/form/div[3]/div[3]/span[2]/span[3]/span[1]/span[2][@class="rangeTo"]/text()')[
                                        0])
            except IndexError as e:
                print("Index error: possible search timeout (10s timeout)", e)
                return

            titles.extend(tree.xpath('/html/body/section/form/div/ul/li/p/a[@class="result-title hdrlnk"]/text()'))
            links.extend(tree.xpath('/html/body/section/form/div/ul/li/p/a[@class="result-title hdrlnk"]/@href'))
            prices.extend(tree.xpath('/html/body/section/form/div/ul/li/p/span/span[@class="result-price"]/text()'))
            IDs.extend(tree.xpath('/html/body/section/form/div/ul/li[@class="result-row"]/@data-pid'))
            if shownListings == totalListings:
                break

        if len(prices) > totalListings:
            totalListings = len(prices)

        # Pre-filter results
        for i in range(len(prices)):
            print("        Checking", self.searchTerms.upper(), "-", self.location.upper(), i + 1, "/",
                  str(totalListings), "(", IDs[i], ") Texting:", enableTexting)
            if self.listingIsNew(IDs[i]) and (self.maxPrice >= int(prices[i][1:].replace(",", "")) >= self.minPrice):
                newListing = Listing(titles[i], links[i], int(prices[i][1:].replace(",", "")), IDs[i])
                print("Price hit: analyzing further...", newListing.price)
                # Scoring using 'manual' identifiers
                self.allObjects.append(newListing)
                scoreReport = Search.scoreMatch(self.keywordsPos, self.keywordsNeg, newListing.descriptiveText)

                # print("Found NEW listing! Score:", scoreReport)

                if scoreReport > 0.1 and newListing.title != "deleted" and IDlib.newIDCheck(IDs[i]):
                    if self.maxPrice >= newListing.price >= self.minPrice:
                        self.hitObjects.append(newListing)
                        IDlib.addListing(IDs[i])
                        if enableTexting:
                            Search.sendText(newListing.price, newListing.link, self.location, self.contactNumber)

    def listingIsNew(self, listingID):
        status = True
        for thing in self.allObjects:
            if thing.listingID == listingID:
                status = False
        return status

    @staticmethod
    def sendText(price, link, domain, number):
        print("TEXT SENT Price: $", price, link, domain)
        message = client.messages.create(
            body=('$' + str(price) + ' in ' + str(domain) + ' ' + str(link)),
            from_='+16076994438', to=str(number))
        print(message.sid)

    @staticmethod
    def scoreMatch(hotWords, coldWordsLocal, inString):
        badSymbols = ";:,./\\][!@#$%^&*()-=+_<>`~?\"\'"
        for symbol in badSymbols:
            inString.replace(symbol, ' ')
        stringWords = (inString.lower()).split()
        for word in stringWords:
            word.strip()

        hotWords = hotWords.split()
        coldWordsLocal = coldWordsLocal.split()
        hitScore = 0
        for word in stringWords:
            for checkWord in hotWords:
                if word == checkWord:
                    hitScore = hitScore + 1
            for checkWord in coldWordsLocal:
                if word == checkWord:
                    hitScore = hitScore - 10
        return hitScore / len(stringWords)


loadData = True

#####################################################################################################################
#####################################################################################################################
#####################################################################################################################
# TO SET UP A NEW SEARCH:
# 1. Install python 3.8 or newer with the packages: twilio, requests, and lxml (use "pip install PACKAGE" in
#    python terminal)
# 2. Add a new Search(location, search string, positiveWords, negativeWords, minPrice, maxPrice) to the
#    desiredSearches array.
#####################################################################################################################
words = "motor honda mercury evinrude boat hp johnson yamaha marine fish suzuki two stroke four pull " \
        "fishing trailer mariner sail spinnaker sailboat catalina hobie rigging hours dinghy skiff tiller running  " \
        "clymer seloc start ft foot merc parts horse horsepower tohatsu"

coldWords = "wanted quangsoutboards wanted looking 4x4 camper homestead jayco slx van rv rvs fifth gmc ford chevy radeon " \
            "keyboard dell pc gaming motorhome 5th toyhauler tent pop travel touring slideout pontoon mercruiser " \
            "parting wtb props propeller prop"

genWords = "honda coleman watt"
genColdWords = "wanted rent rental"

genMin = 25
genMax = 200

boatMin = 500
boatMax = 1500

outboardMin = 40
outboardMax = 250

notifiedListings = TextSentLibrary()

clSearchDomain = ["sfbay", "reno", "sacramento", "modesto", "monterey", "fresno", "bakersfield", "chico",
                  "goldcountry", "hanford", "humboldt", "redding", "klamath", "susanville", "stockton", "yubasutter",
                  "merced"]
desiredSearches = list()

for location in clSearchDomain:
    desiredSearches.append(Search(location, "outboard", words, coldWords, outboardMin, outboardMax, '+16509954172'))
    desiredSearches.append(Search(location, "mercury hp", words, coldWords, outboardMin, outboardMax, '+16509954172'))
    desiredSearches.append(Search(location, "johnson hp", words, coldWords, outboardMin, outboardMax, '+16509954172'))
    desiredSearches.append(Search(location, "evinrude", words, coldWords, outboardMin, outboardMax, '+16509954172'))
    desiredSearches.append(Search(location, "generator", genWords, genColdWords, genMin, genMax, '+16509954172'))
    # desiredSearches.append(Search(location, "gregor", words, coldWords, boatMin, boatMax, '+16509954172'))
    # desiredSearches.append(Search(location, "sailboat", words, coldWords, boatMin, boatMax, '+16509954172'))
    # desiredSearches.append(Search(location, "starcraft", words, coldWords, boatMin, boatMax, '+16509954172'))
    # desiredSearches.append(Search(location, "aluminum boat", words, coldWords, boatMin, boatMax, '+16509954172'))
    # desiredSearches.append(Search(location, "fishing boat", words, coldWords, boatMin, boatMax, '+16509954172'))
    # desiredSearches.append(Search(location, "boat", words, coldWords, boatMin, boatMax, '+16509954172'))
    # desiredSearches.append(Search(location, "boston whaler", words, coldWords, 8000, 20000, '+16509954172'))

    # For Dad:
    desiredSearches.append(Search(location, "boston whaler", words, coldWords, 8000, 20000, '+16509969406'))
    desiredSearches.append(Search(location, "center console", words, coldWords, 8000, 20000, '+16509969406'))

#####################################################################################################################
#####################################################################################################################
#####################################################################################################################

rejSearches = list()
sendTexts = True
isClearCycle = False
containsNewSearch = False

try:
    hitCount = 0
    with open('searchFile.pickle', 'rb') as file:
        searchQue = pickle.load(file)
        for desired in desiredSearches:
            appendNewSearch = True
            for loaded in searchQue:
                if loaded.location == desired.location and desired.searchTerms == loaded.searchTerms:
                    if desired.contactNumber == loaded.contactNumber:
                        appendNewSearch = False
            if appendNewSearch:
                searchQue.append(desired)
                sendTexts = False
                containsNewSearch = True

        tempSearchQue = list()
        for loaded in searchQue:
            searchIsDesired = False
            for desired in desiredSearches:
                if desired.location == loaded.location and desired.searchTerms == loaded.searchTerms:
                    searchIsDesired = True
            if searchIsDesired:
                tempSearchQue.append(loaded)
            else:
                rejSearches.append(loaded)

        searchQue = tempSearchQue
        for search in searchQue:
            hitCount = hitCount + len(search.allObjects)
            print("Loaded", len(search.allObjects), "objects from:", search.location, "-", search.searchTerms)
    print("Loaded", hitCount, "objects from memory from", len(searchQue), "objects.")
    print("Loaded", len(rejSearches), "unused search objects from memory.")

except TypeError:
    print("Loaded file is empty.")
    searchQue = desiredSearches
    sendTexts = False
    isClearCycle = True

except FileNotFoundError:
    print("No save file found.")
    searchQue = desiredSearches
    sendTexts = False
    isClearCycle = True

except pickle.UnpicklingError:
    print("Corrupt pickle file.")
    searchQue = desiredSearches
    sendTexts = False
    isClearCycle = True


def deleteSearchFile():
    os.remove("searchFile.pickle")
    print("Deleting saved searchFile...")
    Search.sendText(0, 'Reset listing library', '__SYS MSG__', '+16509954172')


schedule.every().day.at("03:00").do(deleteSearchFile)

while 1:
    runStart = datetime.datetime.now()
    schedule.run_pending()
    print("Searching: ", runStart)
    if os.path.exists("searchFile.pickle") and not isClearCycle:
        if not containsNewSearch:
            sendTexts = True
    else:
        sendTexts = False
        isClearCycle = True
        searchQue = desiredSearches
        notifiedListings = TextSentLibrary()

    for search in searchQue:
        search.scrape(sendTexts, notifiedListings)
        # Save after each search completes
        try:
            with open('searchFile.pickle', 'wb') as searchFile:
                print("Saving to file...")
                pickle.dump(searchQue + rejSearches, searchFile)

        except OSError:
            print("Missing file")
            sendTexts = False

    runEnd = datetime.datetime.now()
    duration = (runEnd - runStart).seconds

    for search in searchQue:
        for listing in search.hitObjects:
            print("Hit - Location:", search.location, "        Search words:", search.searchTerms, "        Price: $",
                  listing.price, "        Title:", listing.title, "        Link:", listing.link)

    print("Finished search at: ", runEnd)
    print("Search time:", duration, "seconds")

    if not isClearCycle:
        sendTexts = True

    isClearCycle = False
    containsNewSearch = False
    time.sleep(searchInterval * 60)
