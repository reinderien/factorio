#!/usr/bin/env python3

import json, re
from requests import Session


def get_pages(progress):
    """
    https://stable.wiki.factorio.com is an instance of MediaWiki.

    https://stable.wiki.factorio.com/Category:Infobox_page
    lists all of the infobox pages we care about, containing recipes.

    The API endpoint is
    https://stable.wiki.factorio.com/api.php
    """

    sess = Session()

    params = {'action': 'query',
              'generator': 'categorymembers',
              'gcmtitle': 'Category:Infobox_page',
              'gcmtype': 'page',
              'gcmlimit': 500,
              'prop': 'revisions',
              'rvprop': 'content',
              'format': 'json'}
    so_far, total = 0, 0
    while True:
        resp = sess.get('https://stable.wiki.factorio.com/api.php',
                        params=params)
        resp.raise_for_status()

        doc = resp.json()
        pages = doc['query']['pages'].values()
        contents = tuple(p for p in pages if 'revisions' in p)

        so_far += len(contents)
        total = len(pages)
        progress(so_far, total)
        yield from contents

        if 'batchcomplete' in doc:
            break
        params.update(doc['continue'])


line_re = re.compile(r'\n\s*\|')
var_re = re.compile(
    r'^\s*'
    r'(\S+)'
    r'\s*=\s*'
    r'(.+?)'
    r'\s*$')


def parse(pages):
    """
    Example:

    {{Infobox
    |map-color = 006090
    |prototype-type = mining-drill
    |internal-name = burner-mining-drill
    |expensive-total-raw = Time, 8 + Iron plate, 30 + Stone, 10
    |expensive-recipe = Time, 4 + Iron gear wheel, 6 + Iron plate, 6 + Stone furnace, 2
    |category = Production
    |image=Burner-Mining-Drill-Example
    |health = 150
    |stack-size=50
    |dimensions=2×2
    |energy=300 {{Translation|kW}} burner
    |mining-power=2.5
    |mining-speed=0.35
    |mining-area=2×2
    |pollution=10
    |valid-fuel = Wood + Raw wood + Wooden chest + Coal + Solid fuel + Small electric pole + Rocket fuel + Nuclear fuel
    |recipe = Time, 2 + Iron gear wheel, 3 + Iron plate, 3 + Stone furnace, 1
    |total-raw = Time, 4 + Iron plate, 9 + Stone, 5
    |producers=Manual + Assembling machine 2 + Assembling machine 3
    }}<noinclude>
    [[Category:Infobox page]]
    </noinclude>

    Splitting on newline isn't a great idea, because
    https://www.mediawiki.org/wiki/Help:Templates#Named_parameters
    shows that only the pipe is mandatory as a separator. However, only
    splitting on pipe is worse, because there are pipes on the inside of links.
    """
    for p in pages:
        content = p['revisions'][0]['*']
        entries = (
            var_re.match(e)
            for e in line_re.split(
                content.split('{{', maxsplit=1)[1]
                .rsplit('}}', maxsplit=1)[0]
            )
        )
        d = {
            'pageid': p['pageid'],
            'title': p['title'].split(':', maxsplit=1)[1]
        }
        d.update(dict(e.groups() for e in entries if e))
        yield d


def save(fn, recipes):
    with open(fn, 'w') as f:
        json.dump(tuple(recipes), f, indent=4)


def main():
    def progress(so_far, total):
        print(f'{so_far}/{total} {so_far/total:.0%}\r')

    save('recipes.json', parse(get_pages(progress)))
    print()


if __name__ == '__main__':
    main()
