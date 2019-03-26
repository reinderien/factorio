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
        contents = tuple(p['revisions'][0]['*'] for p in pages
                         if 'revisions' in p)

        so_far += len(contents)
        total = len(pages)
        progress(so_far, total)
        yield from contents

        if 'batchcomplete' in doc:
            break
        params.update(doc['continue'])


box_re = re.compile(
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
    |prototype-type = assembling-machine
    |internal-name = assembling-machine-3
    |expensive-total-raw = Time, 465.5 + Copper plate, 460 + Iron plate, 330 + Plastic bar, 80
    |category = Production
    |image = assembling_machine_3_entity
    |health = 400
    |stack-size    =50
    |energy        =210 kW electric
    |drain         =7.0 kW electric
    |dimensions    =3×3
    |crafting-speed =1.25
    |pollution     =1.8
    |modules       =4
    |recipe = Time, 0.5 + Assembling machine 2, 2 + Speed module, 4
    |total-raw = Time, 302.5 + Copper plate, 148 + Iron plate, 148 + Plastic bar, 40
    |required-technologies = Automation 3
    |producers     =Manual + Assembling machine
    }}<noinclude>
    [[Category:Infobox page]]
    </noinclude>
    """
    for p in pages:
        entries = (
            box_re.match(e) for e in
            p.split('{{', maxsplit=1)[1]
            .split('}}', maxsplit=1)[0]
            .split('|')
        )
        yield dict(e.groups() for e in entries if e)


def save(fn, recipes):
    with open(fn, 'w') as f:
        json.dump(tuple(recipes), f, indent=4)


def main():
    def progress(so_far, total):
        print(f'{so_far}/{total} {so_far/total:.1%}\r')

    save('recipes.json', parse(get_pages(progress)))


if __name__ == '__main__':
    main()
