#!/usr/bin/env python3

import json, lzma
import numpy as np
from scipy.optimize import linprog, OptimizeResult
from scipy.sparse import csr_matrix, load_npz
from sys import stdout
from typing import Iterable, Sequence, TextIO


class Model:
    def __init__(self, recipes: csr_matrix,
                 recipe_names: Sequence[str],
                 resource_names: Sequence[str]):
        self.recipes = recipes.transpose()
        self.rec_names = recipe_names
        self.res_names = resource_names
        self.n_recipes = len(recipe_names)
        self.n_resources = len(resource_names)
        self.res_expenses: np.ndarray = np.zeros((1, self.n_resources))
        self.rec_expenses: np.ndarray = np.zeros((1, self.n_recipes))

        # No resource rate can go below 0, i.e.
        # No negated resource rate can go above 0
        self.A_ub: np.ndarray = (-self.recipes).toarray()
        self.b_ub: np.ndarray = np.zeros((self.n_resources, 1))

        # self.A_eq = np.empty((0, self.n_recipes))
        # self.b_eq = np.empty((0, 1))

        self.res: OptimizeResult = None

    def _res_idx(self, res_name: str) -> int:
        return self.res_names.index(res_name)

    def _rec_idx(self, rec_name: str) -> int:
        return self.rec_names.index(rec_name)

    def resource_expense(self, res_name: str, ex: float):
        self.res_expenses[0, self._res_idx(res_name)] = ex

    def recipe_expense(self, rec_name: str, ex: float):
        self.rec_expenses[0, self._res_idx(rec_name)] = ex

    def min_resource(self, res_name: str, rate: float):
        # in-place based on existing negative recipe init
        self.b_ub[self._res_idx(res_name)] = -rate

    def max_resource(self, res_name: str, rate: float):
        raise NotImplementedError()

    def min_recipe(self, rec_name: str, rate: float):
        raise NotImplementedError()

    def max_recipe(self, rec_name: str, rate: float):
        raise NotImplementedError()

    def _manual_idx(self) -> Iterable[int]:
        for i, rec in enumerate(self.rec_names):
            if 'manual' in rec.lower():
                yield i

    def player_laziness(self, l: float):
        for i in self._manual_idx():
            self.rec_expenses[0, i] += l

    def max_players(self, players: float):
        manual_row = np.zeros((1, self.n_recipes))
        for i in self._manual_idx():
            manual_row[0, i] = 1
        self.A_ub = np.concatenate((self.A_ub, manual_row))
        self.b_ub = np.concatenate((self.b_ub, ((players,),)))

    def run(self):
        print('Optimizing...')

        # "it is strongly discouraged to use NumPy functions directly on
        # [sparse] matrices"
        # c = np.matmul(self.expenses, self.recipes.toarray())
        # ...but the following seems to work anyway
        c = self.res_expenses * self.recipes + self.rec_expenses

        self.res = linprog(c=c, method='interior-point',
                           A_ub=self.A_ub, b_ub=self.b_ub,
                           # A_eq=self.A_eq, b_eq=self.b_eq
                           )

    def print(self, f: TextIO):
        f.write(self.res.message)
        f.write('\n\n'
                'Recipe counts\n'
                '-------------\n')
        width = max(len(r) for r in self.rec_names)
        fmt = f'{{:>{width}}} {{:.2f}}\n'
        for res, q in zip(self.rec_names, self.res.x):
            if q > 1e-6:
                f.write(fmt.format(res, q))


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
    model = Model(load_matrix('recipes.npz'),
                  *load_meta('recipes-meta.json.xz'))
    model.max_players(1)
    model.player_laziness(1)
    model.resource_expense('Pollution', 1)
    model.resource_expense('Area', 1)
    model.run()
    model.print(stdout)


if __name__ == '__main__':
    main()
