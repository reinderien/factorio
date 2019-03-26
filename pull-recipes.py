#!/usr/bin/env python3

import json, re
from os.path import getsize
from requests import Session

session = Session()


def get_category(name, on_page=None, **kwargs):
    """
    https://stable.wiki.factorio.com is an instance of MediaWiki.
    The API endpoint is
    https://stable.wiki.factorio.com/api.php
    """
    params = {'action': 'query',
              'generator': 'categorymembers',
              'gcmtitle': f'Category:{name}',
              'gcmtype': 'page',
              'gcmlimit': 500,
              'format': 'json'}
    params.update(kwargs)
    while True:
        resp = session.get('https://stable.wiki.factorio.com/api.php',
                           params=params)
        resp.raise_for_status()

        doc = resp.json()
        yield from doc['query']['pages'].values()
        if on_page:
            on_page()

        if 'batchcomplete' in doc:
            break
        params.update(doc['continue'])


def get_archived_titles():
    return get_category('Archived')


def get_item_pages(progress):
    """
    Category:Infobox_page lists all of the infobox pages we care about,
    containing recipes.
    """
    so_far, total = 0, 0

    def on_page():
        nonlocal total
        progress(so_far, total)
        total = 0

    for page in get_category('Infobox_page', on_page=on_page,
                             prop='revisions', rvprop='content'):
        total += 1
        if 'revisions' in page:
            so_far += 1
            yield page


line_re = re.compile(r'\n\s*\|')
var_re = re.compile(
    r'^\s*'
    r'(\S+)'
    r'\s*=\s*'
    r'(.+?)'
    r'\s*$')


def parse(pages, archived_titles):
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
        title = p['title'].split(':', maxsplit=1)[1]
        d = {
            'pageid': p['pageid'],
            'title': title,
            'archived': title in archived_titles
        }
        d.update(dict(e.groups() for e in entries if e))
        yield d


def save(fn, recipes):
    with open(fn, 'w') as f:
        json.dump(tuple(recipes), f, indent=4)


def main():
    def progress(so_far, total):
        print(f'{so_far}/{total} {so_far/total:.0%}', end='\r')

    print('Getting archived items... ', end='')
    archived_titles = {p['title'] for p in get_archived_titles()}
    print(len(archived_titles))

    print('Getting item content...')
    items = parse(get_item_pages(progress), archived_titles)

    fn = 'recipes.json'
    save(fn, items)
    print(f'\n{getsize(fn)//1024} kiB on disk')


if __name__ == '__main__':
    main()
