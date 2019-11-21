#!/usr/bin/env python
# encoding: utf-8

from bs4 import BeautifulSoup
from collections import OrderedDict
import configparser
import dimcli
import json
import logging
import re
import requests
import sys
import time
import traceback
import urllib.parse


class ScholInfra:
    """
    methods for accessing a specific Scholarly Infrastructure API
    """

    def __init__ (self, parent=None, name="Generic", api_url=None, cgi_url=None):
        self.parent = parent
        self.name = name
        self.api_url = api_url
        self.cgi_url = cgi_url
        self.elapsed_time = 0.0


    def get_xml_node_value (self, root, name):
        """
        return the named value from an XML node, if it exists
        """
        node = root.find(name)
        return (node.text if node else None)


    def clean_title (self, title):
        """
        minimal set of string transformations so that a title can be
        compared consistently across API providers
        """
        return re.sub("\s+", " ", title.strip(" \"'?!.,")).lower()


    def title_match (self, title0, title1):
        """
        within reason, do the two titles match?
        """
        return self.clean_title(title0) == self.clean_title(title1)


    def get_api_url (self, *args):
        """
        construct a URL to query the API
        """
        return self.api_url.format(*args)


class ScholInfra_EuropePMC (ScholInfra):
    """
    https://europepmc.org/RestfulWebService
    """

    #super().__init__(name, attitude, behaviour, face)

    def title_search (self, title):
        """
        parse metadata from XML returned from the EuropePMC API query
        """
        t0 = time.time()

        url = self.get_api_url(urllib.parse.quote(title))
        response = requests.get(url).text
        soup = BeautifulSoup(response,  "html.parser")

        if self.parent.logger:
            self.parent.logger.debug(soup.prettify())

        meta = OrderedDict()
        result_list = soup.find_all("result")

        for result in result_list:
            if self.parent.logger:
                self.parent.logger.debug(result)

            result_title = self.get_xml_node_value(result, "title")

            if self.title_match(title, result_title):
                meta["doi"] = self.get_xml_node_value(result, "doi")
                meta["pmcid"] = self.get_xml_node_value(result, "pmcid")
                meta["journal"] = self.get_xml_node_value(result, "journaltitle")
                meta["authors"] = self.get_xml_node_value(result, "authorstring").split(", ")

                if self.get_xml_node_value(result, "haspdf") == "Y":
                    meta["pdf"] = "http://europepmc.org/articles/{}?pdf=render".format(meta["pmcid"])

        t1 = time.time()
        self.elapsed_time = (t1 - t0) * 1000.0

        return meta


class ScholInfra_OpenAIRE (ScholInfra):
    """
    https://develop.openaire.eu/
    """

    def title_search (self, title):
        """
        parse metadata from XML returned from the OpenAIRE API query
        """
        t0 = time.time()

        url = self.get_api_url(urllib.parse.quote(title))
        response = requests.get(url).text
        soup = BeautifulSoup(response,  "html.parser")

        if self.parent.logger:
            self.parent.logger.debug(soup.prettify())

        meta = OrderedDict()

        for result in soup.find_all("oaf:result"):
            result_title = self.get_xml_node_value(result, "title")

            if self.title_match(title, result_title):
                meta["url"] = self.get_xml_node_value(result, "url")
                meta["authors"] = [a.text for a in result.find_all("creator")]
                meta["open"] = len(result.find_all("bestaccessright",  {"classid": "OPEN"})) > 0
                break

        t1 = time.time()
        self.elapsed_time = (t1 - t0) * 1000.0

        return meta


class ScholInfra_SemanticScholar (ScholInfra):
    """
    http://api.semanticscholar.org/
    """

    def publication_lookup (self, identifier):
        """
        parse metadata returned from a Semantic Scholar API query
        """
        t0 = time.time()

        url = self.get_api_url(identifier)
        meta = json.loads(requests.get(url).text)

        t1 = time.time()
        self.elapsed_time = (t1 - t0) * 1000.0

        return meta


class ScholInfra_Unpaywall (ScholInfra):
    """
    https://unpaywall.org/products/api
    """

    def publication_lookup (self, identifier):
        """
        construct a URL to query the API for Unpaywall
        """
        t0 = time.time()

        email = self.parent.config["DEFAULT"]["email"]

        url = self.get_api_url(identifier, email)
        meta = json.loads(requests.get(url).text)

        t1 = time.time()
        self.elapsed_time = (t1 - t0) * 1000.0

        return meta


class ScholInfra_dissemin (ScholInfra):
    """
    https://dissemin.readthedocs.io/en/latest/api.html
    """

    def publication_lookup (self, identifier):
        """
        parse metadata returned from a dissemin API query
        """
        t0 = time.time()

        url = self.get_api_url(identifier)
        meta = json.loads(requests.get(url).text)

        t1 = time.time()
        self.elapsed_time = (t1 - t0) * 1000.0

        return meta


class ScholInfra_Dimensions (ScholInfra):
    """
    https://docs.dimensions.ai/dsl/
    """

    def run_query (self, query):
        """
        run one Dimensions API query through their 'DSL'
        """
        dimcli.login(
            username=self.parent.config["DEFAULT"]["email"],
            password=self.parent.config["DEFAULT"]["dimensions_password"]
            )

        dsl = dimcli.Dsl(verbose=False)

        return dsl.query(query)


    def title_search (self, title):
        """
        parse metadata from a Dimensions API query
        """
        t0 = time.time()

        enc_title = title.replace('"', '\\"')
        query = 'search publications in title_only for "\\"{}\\"" return publications[all]'.format(enc_title)

        response = self.run_query(query)

        for meta in response.publications:
            result_title = meta["title"]

            if self.title_match(title, result_title):
                if self.parent.logger:
                    self.parent.logger.debug(meta)

                t1 = time.time()
                self.elapsed_time = (t1 - t0) * 1000.0

                return meta

        return None


    def full_text_search (self, search_term):
        """
        parse metadata from a Dimensions API full-text search
        """
        t0 = time.time()

        query = 'search publications in full_data for "\\"{}\\"" return publications[doi+title+journal]'.format(search_term)
        response = self.run_query(query)

        t1 = time.time()
        self.elapsed_time = (t1 - t0) * 1000.0

        return response.publications


class ScholInfra_RePEc (ScholInfra):
    """
    https://ideas.repec.org/api.html
    """

    def get_cgi_url (self, title):
        """
        construct a URL to query the CGI for RePEc
        """
        enc_title = urllib.parse.quote_plus(title.replace("(", "").replace(")", "").replace(":", ""))
        return self.cgi_url.format(enc_title)


    def get_handle (self, title):
        """
        to use the RePEc API, first obtain a handle for a publication
        """
        t0 = time.time()

        url = self.get_cgi_url(title)
        response = requests.get(url).text
        soup = BeautifulSoup(response,  "html.parser")

        if self.parent.logger:
            self.parent.logger.debug(soup.prettify())

        ol = soup.find("ol", {"class": "list-group"})
        results = ol.findChildren()

        if len(results) > 0:
            li = results[0]

            if self.parent.logger:
                self.parent.logger.debug(li)

            # TODO: can we perform a title search here?

            handle = li.find("i").get_text()

            t1 = time.time()
            self.elapsed_time = (t1 - t0) * 1000.0

            return handle

        # otherwise...
        self.elapsed_time = 0.0
        return None


    def get_meta (self, handle):
        """
        pull RePEc metadata based on the handle
        """
        try:
            t0 = time.time()

            token = self.parent.config["DEFAULT"]["repec_token"]
            url = self.get_api_url(token, handle)
            meta = json.loads(requests.get(url).text)

            t1 = time.time()
            self.elapsed_time = (t1 - t0) * 1000.0

            return meta

        except:
            self.elapsed_time = 0.0
            print(traceback.format_exc())
            print("ERROR: {}".format(handle))
            return None


######################################################################
## federated API access

class ScholInfraAPI:
    """
    API integrations for federating metadata lookup across multiple
    scholarly infrastructure providers
    """

    def __init__ (self, config_file="rc.cfg", logger=None):
        self.config = configparser.ConfigParser()
        self.config.read(config_file)
        self.logger = logger

        self.europepmc = ScholInfra_EuropePMC(
            parent=self,
            name="EuropePMC",
            api_url="https://www.ebi.ac.uk/europepmc/webservices/rest/search?query={}"
            )

        self.openaire = ScholInfra_OpenAIRE(
            parent=self,
            name="OpenAIRE",
            api_url="http://api.openaire.eu/search/publications?title={}"
            )

        self.semantic = ScholInfra_SemanticScholar(
            parent=self,
            name="Semantic Scholar",
            api_url = "http://api.semanticscholar.org/v1/paper/{}"
            )

        self.unpaywall = ScholInfra_Unpaywall(
            parent=self,
            name="Unpaywall",
            api_url = "https://api.unpaywall.org/v2/{}?email={}"
            )

        self.dissemin = ScholInfra_dissemin(
            parent=self,
            name="dissemin",
            api_url = "https://dissem.in/api/{}"
            )

        self.dimensions = ScholInfra_Dimensions(
            parent=self,
            name="Dimensions",
            )

        self.repec = ScholInfra_RePEc(
            parent=self,
            name="RePEc",
            api_url = "https://api.repec.org/call.cgi?code={}&getref={}",
            cgi_url = "https://ideas.repec.org/cgi-bin/htsearch?q={}"
            )


######################################################################
## main entry point (not used)

if __name__ == "__main__":
    schol = ScholInfraAPI(config_file="rc.cfg")
    print([ (k, v) for k, v in schol.config["DEFAULT"].items()])
