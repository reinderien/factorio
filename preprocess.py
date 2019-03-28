#!/usr/bin/env python3

import json


class Item:
    def __init__(self, data):
        self.data = data
        self.__dict__.update(data)

    @property
    def keep(self):
        return (
            (not self.archived) and
            (
                any(self.data.get(k) for k in ('cost', 'recipe', 'recipes'))
                or 'mining-hardness' in self.data
                or self.title in {'Crude oil',
                                  'Water',
                                  'Space science pack',
                                  'Steam'}
            )
        )


def trim(items):
    to_delete = tuple(k for k, v in items.items() if not v.keep)
    print(f'Dropping {len(to_delete)} items...')
    for k in to_delete:
        del items[k]


def main():
    with open('recipes.json') as f:
        items = {k: Item(d) for k, d in json.load(f).items()}
    trim(items)


if __name__ == '__main__':
    main()
