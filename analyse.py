#!/usr/bin/env python3

import json, lzma
from scipy.sparse import load_npz
from typing import Sequence


def load_meta(fn) -> (Sequence[str], Sequence[str]):
    print(f'Loading {fn}...')
    with lzma.open(fn) as f:
        meta = json.load(f)
    return meta['recipes'], meta['resources']


def main():
    fn = 'recipes.npz'
    print(f'Loading {fn}...')
    recipes = load_npz(fn)

    recipe_names, resource_names = load_meta('recipes-meta.json.xz')


if __name__ == '__main__':
    main()
