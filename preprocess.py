#!/usr/bin/env python3

import json


class Item:
    def __init__(self, data):
        self.data = data

    @property
    def keep(self):
        return (
            (not self.data['archived']) and
            (self.data.get('cost') or self.data.get('recipe'))
        )


def main():
    with open('recipes.json') as f:
        items = [Item(d) for d in json.load(f)]

    print('Not interesting:')
    print('\n'.join(i.data['title']
                    for i in items
                    if not i.keep))


if __name__ == '__main__':
    main()
