#!/usr/bin/env python3

import json, lzma
from scipy.sparse import csr_matrix, load_npz
from typing import Sequence


def load_meta(fn) -> (Sequence[str], Sequence[str]):
    print(f'Loading {fn}... ', end='')
    with lzma.open(fn) as f:
        meta: dict = json.load(f)
    recipes, resources = meta['recipes'], meta['resources']
    print(f'{len(recipes)} recipes, {len(resources)} resources')
    return recipes, resources


def load_matrix(fn) -> csr_matrix:
    print(f'Loading {fn}... ', end='')
    recipes: csr_matrix = load_npz(fn)
    print(f'{recipes.shape[0]}x{recipes.shape[1]}, {recipes.nnz} nnz, '
          f'{recipes.nnz / recipes.shape[0] / recipes.shape[1]:.1%} density')
    return recipes


def main():
    recipes = load_matrix('recipes.npz')
    recipe_names, resource_names = load_meta('recipes-meta.json.xz')


if __name__ == '__main__':
    main()
