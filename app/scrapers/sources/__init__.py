"""Registry of the locked, working source scrapers.

Six verified Pune sources. Three scrape directly (free); three go through Apify
(need APIFY_TOKEN). Cars24 and Droom were dropped — Cars24's actor is broken
and Droom blocks the renderer; neither returned usable data in testing.

  Direct:  Spinny, CarWale, CarDekho
  Apify:   OLX, Facebook, CarTrade
"""
from .spinny import SpinnyScraper
from .carwale import CarWaleScraper
from .cardekho import CarDekhoScraper
from .olx import OlxScraper
from .facebook import FacebookScraper
from .cartrade import CarTradeScraper

ALL_SOURCES = [
    SpinnyScraper,
    CarWaleScraper,
    CarDekhoScraper,
    OlxScraper,
    FacebookScraper,
    CarTradeScraper,
]
