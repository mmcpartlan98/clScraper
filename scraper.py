import math
import pickle
import requests
import datetime
import time
from lxml import html
from twilio.rest import Client

# Minutes between scraping
searchInterval = 1

# Twilio SMS API config
account_sid = 'AC8bd9f1713930d5c3a65e6ab592420dba'
auth_token = '82741da6122123696f5a4994a682f81d'
client = Client(account_sid, auth_token)


# Define craigslist listing object
class Listing:
    def __init__(self, title, link, price, listID):
        self.title = str(title.lower())
        self.link = link
        self.price = int(price[1:])
        self.listingID = listID
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
    def __init__(self, location, searchTerms, keywordsPos, keyWordsNeg, minPrice, maxPrice):
        self.location = location
        self.searchTerms = searchTerms
        self.keywordsPos = keywordsPos + ' ' + searchTerms.replace('+', ' ')
        self.keywordsNeg = keyWordsNeg
        self.minPrice = minPrice
        self.maxPrice = maxPrice
        self.allObjects = list()
        self.hitObjects = list()

    def scrape(self, enableTexting):
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
                  str(totalListings), "(", IDs[i], ")")
            if self.listingIsNew(IDs[i]):
                newListing = Listing(titles[i], links[i], prices[i], IDs[i])

                # Scoring using 'manual' identifiers
                self.allObjects.append(newListing)
                scoreReport = Search.scoreMatch(self.keywordsPos, self.keywordsNeg, newListing.descriptiveText)

                print("Found NEW listing! Score:", scoreReport)

                if scoreReport > 0.1 and newListing.title != "deleted":
                    if self.maxPrice >= newListing.price > self.minPrice:
                        self.hitObjects.append(newListing)
                        if enableTexting:
                            Search.sendText(newListing.price, newListing.link)

    def listingIsNew(self, listingID):
        status = True
        for thing in self.allObjects:
            if thing.listingID == listingID:
                status = False
        return status

    @staticmethod
    def sendText(price, link):
        print("TEXT SENT Price: $", price, link)
        message = client.messages.create(
            body=('Result: $' + str(price) + ' ' + str(link)),
            from_='+16076994438', to='+16509954172')
        print(message.sid)

    @staticmethod
    def scoreMatch(hotWords, coldWordsLocal, inString):
        badSymbols = ",./\\][!@#$%^&*()-=+_<>`~?\"\'"
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
# 3. Change sendTexts to true or false depending on whether you want to be notified of new listings
#       NOTE: The first time you run the program, it will send a text for ALL hits (not only new ones).
#             If this is not desired, run the program once with sentTexts set to False and allow it to build
#             and save a library of search results. Exit the script, change sendTexts to True, and restart.
#             Now, only notifications for new listings will be sent via text.

#####################################################################################################################

words = "motor honda mercury evinrude boat hp johnson yamaha marine fish suzuki two stroke four pull " \
        "fishing trailer mariner sail spinnaker sailboat catalina hobie rigging hours dinghy skiff tiller"

welderHotWords = "mig tig stick shield 220 230 240"

coldWords = "wanted quangsoutboards.com"

welderColdWords = ""

desiredSearches = [Search("sfbay", "outboard", words, coldWords, 0, 150),
                   Search("reno", "outboard", words, coldWords, 0, 150),
                   Search("sacramento", "outboard", words, coldWords, 0, 150),
                   Search("sfbay", "welder", welderHotWords, welderColdWords, 0, 150)]
sendTexts = True

#####################################################################################################################
#####################################################################################################################
#####################################################################################################################

rejSearches = list()

try:
    hitCount = 0
    with open('searchFile.pickle', 'rb') as file:
        searchQue = pickle.load(file)
        for desired in desiredSearches:
            appendNewSearch = True
            for loaded in searchQue:
                if desired.location == loaded.location and desired.searchTerms == loaded.searchTerms:
                    appendNewSearch = False
            if appendNewSearch:
                searchQue.append(desired)

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

except FileNotFoundError:
    print("No save file found.")
    searchQue = desiredSearches

except pickle.UnpicklingError:
    print("Corrupt pickle file.")
    searchQue = desiredSearches

time.sleep(10)
while 1:
    runStart = datetime.datetime.now()
    print("Searching: ", runStart)

    for search in searchQue:
        search.scrape(sendTexts)
        # Save after each search completes
        with open('searchFile.pickle', 'wb') as searchFile:
            print("Saving to file...")
            pickle.dump(searchQue + rejSearches, searchFile)

    runEnd = datetime.datetime.now()
    duration = (runEnd - runStart).seconds

    for search in searchQue:
        for listing in search.hitObjects:
            print("Hit - Location:", search.location, "        Search words:", search.searchTerms, "        Price: $",
                  listing.price, "        Title:", listing.title, "        Link:", listing.link)

    print("Finished search at: ", runEnd)
    print("Search time:", duration, "seconds")
    time.sleep(searchInterval * 60)
