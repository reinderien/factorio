# Factorio Analysis

## Intro

Factorio ([homepage](factorio.com),
[Steam](https://store.steampowered.com/app/427520)) is a fantastic top-down
open-world RTS/factory game with an emphasis on automation and technical depth.
There's no game I can't ruin by applying math! 

The purpose of this project is to get some analytical data about the game's
economics, and probably do some constrained linear programming optimization to
try out some "computed economies" at scale.

## Requirements

- [Python 3](python.org)
- [requests](python-requests.org)
- [R](r-project.org)

## Database pull

The scripts don't interact with the game itself. Instead, they pull and scrape
data from [the wiki](wiki.factorio.com), an instance of
[MediaWiki](mediawiki.org). As luck would have it, MediaWiki has a pretty good
[REST API](https://www.mediawiki.org/wiki/API:Main_page), and the API endpoint
for the Factorio wiki is open. This means that we can:

- Pull structured infobox content for each item in the game, yielding data like
  production recipes, power consumption, etc. This is done by pulling content
  for the most recent revision of every page in the Infobox category.
- Pull titles for each page in the Archived category, so that we know which
  items to ignore.

The wiki has two instances - one documenting the experimental version of
Factorio (0.17 as of this writing), and the other documenting the stable version
(0.16). This project uses the stable version.

To download and save the game's item database, issue

    ./pull-recipes.py

To look at the resulting (large) JSON file, use `xzless`.
    
## Preprocessing

The data from the wiki are a colourful mix of inaccurate, incomplete, and in a
format not conducive to analysis. The preprocessing step attempts to fix that:

    ./preprocess.py
    
To look at the resulting (huge: >5MiB) CSV, use `xzless -S`, that argument being
crucial to disable line wrapping.

## Analysis

Run

    ./analyse.r
    
This is a WIP.
