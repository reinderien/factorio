#!/usr/bin/env python3

import json, lzma, pathlib, re
import typing

from requests import Session


class ProgressCallback(typing.Protocol):
    def __call__(self, so_far: int, total: int) -> None: ...


def get_mediawiki(
    session: Session,
    content: bool = False,
    progress: ProgressCallback | None = None,
    **kwargs: typing.Any,
) -> typing.Iterator[dict[str, str]]:
    """
    https://stable.wiki.factorio.com is an instance of MediaWiki.
    The API endpoint is
    https://stable.wiki.factorio.com/api.php
    """
    params = {
        'action': 'query',
        'format': 'json',
        **kwargs,
    }
    if content:
        params.update({
            'prop': 'revisions',
            'rvprop': 'content',
        })

    so_far = 0
    while True:
        with session.get(
            url='https://wiki.factorio.com/api.php',
            params=params,
        ) as resp:
            resp.raise_for_status()
            doc = resp.json()

        pages = doc['query']['pages'].values()

        if content:
            full_pages = tuple(p for p in pages if 'revisions' in p)
            so_far += len(full_pages)
            if progress:
                progress(so_far, len(pages))
            yield from full_pages
        else:
            yield from pages

        if 'batchcomplete' in doc.keys():
            break
        params.update(doc['continue'])


def get_category(
    session: Session,
    name: str,
    content: bool = False,
    progress=None,
    **kwargs: typing.Any,
) -> typing.Iterator[dict[str, str]]:
    return get_mediawiki(
        session=session,
        content=content,
        progress=progress,
        generator='categorymembers',
        gcmtitle=f'Category:{name}',
        gcmtype='page',
        gcmlimit=500,
        **kwargs,
    )


def get_archived_titles(session: Session) -> typing.Iterator[dict[str, str]]:
    return get_category(session=session, name='Archived')


def get_infoboxes(
    session: Session,
    progress: ProgressCallback | None,
) -> typing.Iterator[dict[str, str]]:
    return get_category(
        session=session, name='Infobox_page', content=True, progress=progress,
    )


def get_inter_tables(
    session: Session,
    titles: typing.Iterable[str],
    progress: ProgressCallback | None,
) -> typing.Iterator[dict[str, str]]:
    return get_mediawiki(
        session=session, content=True, progress=progress,
        titles='|'.join(titles),
    )


line_re = re.compile(r'\n\s*\|')
var_re = re.compile(r'''(?x)
    ^\s*
    (\S+)
    \s*=\s*
    (.+?)
    \s*$
''')


def parse_infobox(page: dict[str, typing.Any]) -> dict[str, str]:
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
# e.g.
# | {{Imagelink|Oil refinery}} || {{Imagelink|Advanced oil processing}}
# || {{icon|Time|5}} + {{Icon|Crude oil|100}} + {{icon|Water|50}} →
# {{Icon|Heavy oil|25}} + ({{Icon|Light oil|45}} + {{Icon|Petroleum gas|55}})
row_image_re = re.compile(fr'''(?x)
    \{{\{{\s*         # opening {{ braces
    (?P<type>\w+?)    # type, e.g. ImageLink or icon
    {border_tok}      # first inner | separator
    {part_tok}        # part name
    (?:               # non-capturing
       {border_tok}   # second inner | separator
       {part_tok}     # quantity, e.g. 100
    )?                # optional
    (?:               # non-capturing
       {border_tok}   # third inner | separator
       [^{{}}]*       # ...what is this?
    )?                # optional
    }}}}\s*           # closing }} braces
    (?P<sep>          # arrow separator between recipe left and right sides
      (?:
        \|\||\+|→
      )?
    )
''')


def iter_cells(row: str) -> typing.Iterator[tuple[
    str,  # type, e.g. icon
    str,  # name, e.g. Oil refinery
    str | None,  # quantity, e.g. 100
    typing.Literal['+', '→', ''],  # recipe operator
]]:
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


def parse_inter_table(page: dict[str, typing.Any]) -> tuple[
    str,  # title
    dict[str, typing.Any],  # recipes
]:
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
    heads = tuple(
        h.strip().lower()
        for h in row_strings[0]
            .split('!', maxsplit=1)[1]
            .split('!!')
    )

    for line in row_strings[1:]:
        inputs: dict[str, int] = {}
        outputs: dict[str, int] = {}
        row = {'inputs': inputs, 'outputs': outputs}
        for head, parts in zip(heads, iter_cells(line)):
            if head in {'process', 'building'}:
                type_, name, quantity = parts[0]
                row[head.lower()] = name
                continue
            elif head not in {'input', 'output', 'results'}:
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
            for type_, name, quantity, *other_parts in parts:
                res_type = type_.lower()
                if res_type != 'icon':
                    raise ValueError(f'Unexpected resource type {res_type}')
                side[name] = int(quantity)
                if 'results' in head and len(other_parts) >= 1:
                    operator = other_parts[0]
                    if operator == '→':
                        side = outputs

        if inputs or outputs:
            rows.append(row)

    return title, {'recipes': rows}


def inter_needed(items: typing.Iterable) -> typing.Iterator[str]:
    return (
        i['title'] for i in items
        if not i['archived']
        and i.get('category') == 'Intermediate products'
        and not ('cost' in i or 'recipe' in i)
    )


def save(fn: pathlib.Path, recipes: dict[str, typing.Any]) -> None:
    with lzma.open(fn, 'wt') as f:
        json.dump(recipes, f, indent=4)


def main() -> None:
    def progress(so_far, total):
        print(f'{so_far}/{total} {so_far/total:.0%}', end='\r', flush=True)

    with Session() as session:
        session.headers['Accept'] = 'application/json'

        print('Getting archived items... ', end='')
        archived_titles = {
            p['title']
            for p in get_archived_titles(session=session)
        }
        print(len(archived_titles))

        print('Getting item content...')
        items: tuple[dict[str, str | bool], ...] = tuple(
            parse_infobox(p)
            for p in get_infoboxes(session=session, progress=progress)
        )
        items_by_name = {i['title']: i for i in items}
        for item in items:
            item['archived'] = item['title'] in archived_titles

        print('\nFilling in intermediate products...')
        inter_tables = get_inter_tables(
            session=session,
            titles=inter_needed(items),
            progress=progress,
        )
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

    fn = pathlib.Path('items.json.xz')
    print(f'Saving to {fn}... ', end='')
    save(fn=fn, recipes=items_by_name)
    print(f'{fn.stat().st_size//1024} KiB')


if __name__ == '__main__':
    main()
