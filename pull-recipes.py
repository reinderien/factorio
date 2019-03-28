#!/usr/bin/env python3

import json, re
from os.path import getsize
from requests import Session
from sys import stdout

session = Session()


def get_mediawiki(content=False, progress=None, **kwargs):
    """
    https://stable.wiki.factorio.com is an instance of MediaWiki.
    The API endpoint is
    https://stable.wiki.factorio.com/api.php
    """
    params = {'action': 'query',
              'format': 'json',
              **kwargs}
    if content:
        params.update({'prop': 'revisions',
                       'rvprop': 'content'})
    so_far = 0
    while True:
        resp = session.get('https://stable.wiki.factorio.com/api.php',
                           params=params)
        resp.raise_for_status()

        doc = resp.json()
        pages = doc['query']['pages'].values()
        if content:
            full_pages = tuple(p for p in pages if 'revisions' in p)
            if progress:
                so_far += len(full_pages)
                progress(so_far, len(pages))
            yield from full_pages
        else:
            yield from pages

        if 'batchcomplete' in doc:
            break
        params.update(doc['continue'])


def get_category(name, content=False, progress=None, **kwargs):
    return get_mediawiki(content=content, progress=progress,
                         generator='categorymembers',
                         gcmtitle=f'Category:{name}',
                         gcmtype='page',
                         gcmlimit=500,
                         **kwargs)


def get_archived_titles():
    return get_category('Archived')


def get_infoboxes(progress):
    return get_category('Infobox_page', content=True, progress=progress)


def get_inter_tables(titles, progress):
    return get_mediawiki(content=True, progress=progress,
                         titles='|'.join(titles))


line_re = re.compile(r'\n\s*\|')
var_re = re.compile(
    r'^\s*'
    r'(\S+)'
    r'\s*=\s*'
    r'(.+?)'
    r'\s*$')


def parse_infobox(page):
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

    content = page['revisions'][0]['*']
    entries = (
        var_re.match(e)
        for e in line_re.split(
            content.split('{{', maxsplit=1)[1]
            .rsplit('}}', maxsplit=1)[0]
        )
    )
    title = page['title'].split(':', maxsplit=1)[1]
    d = {'pageid': page['pageid'],
         'title': title}
    d.update(dict(e.groups() for e in entries if e))
    return d


part_tok = r'\s*([^|{}]*?)'
border_tok = r'\s*\|'
row_image_re = re.compile(
    r'\{\{\s*'
    r'(?P<type>\w+)'
    f'{border_tok}'
    f'{part_tok}'
    r'(?:'
       f'{border_tok}'    
       f'{part_tok}'
    r')?'
    r'(?:'
       f'{border_tok}'
       r'[^{}]*'
    r')?'
    r'\}\}\s*'
    r'(?P<sep>'
      r'(?:'
        r'\|\||\+|→'
      r')?'
    r')',
)


def iter_cells(row):
    """
    e.g.
    | {{Icon|Solid fuel from light oil||}}
    || {{icon|Light oil|10}} + {{icon|time|3}}
    || {{icon|Solid fuel|1}}
    or
    | {{Imagelink|Oil refinery}}
    || {{Imagelink|Basic oil processing}}
    || {{Icon|Crude oil|100}} + {{icon|Time|5}}
    → {{Icon|Heavy oil|30}} + ({{Icon|Light oil|30}} {{Icon|Petroleum gas|40}})
    """

    cell = []
    for m in row_image_re.finditer(row):
        if m.group('sep') == '||':
            cell.append(m.groups()[:-1])
            yield cell
            cell = []
        else:
            cell.append(m.groups())
    if cell:
        yield cell


def parse_inter_table(page):
    """
    Example:

    {| class="wikitable"
    ! Building !! Process !! Results
    |-
    | {{Imagelink|Oil refinery}} || {{Imagelink|Basic oil processing}} || {{Icon|Crude oil|100}} + {{icon|Time|5}} → {{Icon|Heavy oil|30}} + ({{Icon|Light oil|30}} {{Icon|Petroleum gas|40}})
    |-
    | {{Imagelink|Oil refinery}} || {{Imagelink|Advanced oil processing}} || {{Icon|Crude oil|100}} + {{icon|Water|50}} + {{icon|Time|5}} → {{Icon|Heavy oil|10}} + ({{Icon|Light oil|45}} {{Icon|Petroleum gas|55}})
    |-
    | {{Imagelink|Oil refinery}} || {{imagelink|Coal liquefaction}} || {{icon|Coal|10}} + {{Icon|Heavy oil|25}} + {{icon|Steam|50}} + {{icon|Time|5}} → {{Icon|Heavy oil|35}} + ({{Icon|Light oil|15}} + {{Icon|Petroleum gas|20}})
    |}

    or

    {| class="wikitable"
    ! Process !! Input !! Output
    |-
    | {{Icon|Solid fuel from heavy oil||}} || {{icon|Heavy oil|20}} + {{icon|time|3}} || {{icon|Solid fuel|1}}
    |-
    | {{Icon|Solid fuel from light oil||}} || {{icon|Light oil|10}} + {{icon|time|3}} || {{icon|Solid fuel|1}}
    |-
    | {{Icon|Solid fuel from petroleum gas||}} || {{icon|Petroleum gas|20}} + {{icon|time|3}} || {{icon|Solid fuel|1}}
    |-
    |}
    """
    title = page['title']
    content = page['revisions'][0]['*']
    if '{|' not in content:
        return title, {}

    rows = []
    body = (content
            .replace('\n', '')
            .split('{|', maxsplit=1)[1]
            .rsplit('|}', maxsplit=1)[0])
    row_strings = body.split('|-')
    heads = tuple(h.strip().lower() for h in row_strings[0]
                  .split('!', maxsplit=1)[1]
                  .split('!!'))

    for line in row_strings[1:]:
        inputs = []
        outputs = []
        row = {'inputs': inputs, 'outputs': outputs}
        for head, parts in zip(heads, iter_cells(line)):
            if head in ('process', 'building'):
                row[head.lower()] = parts[0][1]
                continue
            elif head not in ('input', 'output', 'results'):
                if head == '':
                    return title, {}  # Space science pack edge case
                raise ValueError(f'Unrecognized head {head}')

            if 'input' in head:
                side = inputs
            elif 'output' in head:
                side = outputs
            else:
                side = inputs
                if 'results' not in head:
                    raise ValueError(f'Unexpected heading {head}')
            for part in parts:
                res_type = part[0].lower()
                if res_type != 'icon':
                    raise ValueError(f'Unexpected resource type {res_type}')
                ingredient = {'name': part[1],
                              'qty': int(part[2])}
                side.append(ingredient)
                if 'results' in head and len(part) == 4 and part[-1] == '→':
                    side = outputs

        if inputs or outputs:
            rows.append(row)

    return title, {'recipes': rows}


def inter_needed(items):
    return (i['title'] for i in items if
            not i['archived']
            and i.get('category') == 'Intermediate products'
            and not ('cost' in i or 'recipe' in i))


def save(fn, recipes):
    with open(fn, 'w') as f:
        json.dump(recipes, f, indent=4)


def main():
    def progress(so_far, total):
        print(f'{so_far}/{total} {so_far/total:.0%}', end='\r')
        stdout.flush()

    print('Getting archived items... ', end='')
    archived_titles = {p['title'] for p in get_archived_titles()}
    print(len(archived_titles))

    print('Getting item content...')
    items = tuple(parse_infobox(p) for p in get_infoboxes(progress))
    items_by_name = {i['title']: i for i in items}
    for item in items:
        item['archived'] = item['title'] in archived_titles

    print('\nFilling in intermediate products...')
    inter_tables = get_inter_tables(inter_needed(items), progress)
    used = 0
    for table_page in inter_tables:
        try:
            title, recipes = parse_inter_table(table_page)
            if recipes:
                used += 1
                items_by_name[title].update(recipes)
        except Exception as e:
            print(f'\nWarning: {table_page["title"]} failed to parse - {e}')
    print(f'\n{used} intermediate tables used.')

    fn = 'recipes.json'
    print(f'Saving to {fn}... ', end='')
    save(fn, items_by_name)
    print(f'{getsize(fn)//1024} kiB')


if __name__ == '__main__':
    main()
