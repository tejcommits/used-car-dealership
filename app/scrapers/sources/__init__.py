"""Registry of all source scrapers.

To add a source: create a module here with a Scraper subclass and add it to
ALL_SOURCES below. Nothing else in the app needs to change.
"""
from .olx import OlxScraper
from .cars24 import Cars24Scraper
from .spinny import SpinnyScraper
from .carwale import CarWaleScraper
from .cardekho import CarDekhoScraper
from .quikr import QuikrScraper
from .facebook import FacebookScraper
from .teambhp import TeamBhpScraper

ALL_SOURCES = [
    OlxScraper,
    Cars24Scraper,
    SpinnyScraper,
    CarWaleScraper,
    CarDekhoScraper,
    QuikrScraper,
    FacebookScraper,
    TeamBhpScraper,
]
