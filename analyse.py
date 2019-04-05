#!/usr/bin/env python3

import json, lzma
import numpy as np
from math import ceil, log10
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

        self.result: OptimizeResult = None

    def _res_idx(self, res_name: str) -> int:
        return self.res_names.index(res_name)

    def _rec_idx(self, rec_name: str) -> int:
        return self.rec_names.index(rec_name)

    def _manual_idx(self) -> Iterable[int]:
        for i, rec in enumerate(self.rec_names):
            if 'manual' in rec.lower():
                yield i

    def _add_ub(self, row: np.ndarray, b: float):
        self.A_ub = np.concatenate((self.A_ub, row))
        self.b_ub = np.concatenate((self.b_ub, ((b,),)))

    def resource_expense(self, res_name: str, ex: float):
        self.res_expenses[0, self._res_idx(res_name)] = ex

    def recipe_expense(self, rec_name: str, ex: float):
        self.rec_expenses[0, self._res_idx(rec_name)] = ex

    def min_resource(self, res_name: str, rate: float):
        # in-place based on existing negative recipe init
        self.b_ub[self._res_idx(res_name)] = -rate

    def max_resource(self, res_name: str, rate: float):
        i = self._res_idx(res_name)
        row = self.recipes[i, :].toarray()
        self._add_ub(row, rate)

    def min_recipe(self, rec_name: str, rate: float):
        row = np.zeros((1, self.n_recipes))
        row[0, self._rec_idx(rec_name)] = -1
        self._add_ub(row, -rate)

    def max_recipe(self, rec_name: str, rate: float):
        row = np.zeros((1, self.n_recipes))
        row[0, self._rec_idx(rec_name)] = 1
        self._add_ub(row, rate)

    def player_laziness(self, l: float):
        for i in self._manual_idx():
            self.rec_expenses[0, i] += l

    def max_players(self, players: float):
        manual_row = np.zeros((1, self.n_recipes))
        for i in self._manual_idx():
            manual_row[0, i] = 1
        self._add_ub(manual_row, players)

    def run(self):
        print('Optimizing...')

        # "it is strongly discouraged to use NumPy functions directly on
        # [sparse] matrices"
        # c = np.matmul(self.expenses, self.recipes.toarray())
        # ...but the following seems to work anyway
        c = self.res_expenses * self.recipes + self.rec_expenses

        self.result = linprog(c=c, method='interior-point',
                              A_ub=self.A_ub, b_ub=self.b_ub,
                              # A_eq=self.A_eq, b_eq=self.b_eq
                              )

    @staticmethod
    def diminishing_table(f: TextIO, title: str, x: Iterable[float], names: Iterable[str],
                          digs: int):
        f.write(title)
        f.write('\n')
        f.write('-'*len(title))
        f.write('\n\n')

        rows = sorted((
            (q, n)
            for q, n in zip(x, names)
            if q >= 10 ** -digs
        ), reverse=True)

        q_width = int(ceil(log10(max(q for q, n in rows)))) + 1 + digs
        fmt = f'{{:>{q_width}.{digs}f}} {{:}}\n'

        for q, name in rows:
            f.write(fmt.format(q, name))
        f.write('\n')

    def print(self, f: TextIO):
        f.write(self.result.message)
        f.write('\n\n')
        self.diminishing_table(f, 'Recipe counts', self.result.x, self.rec_names, 2)
        self.diminishing_table(f, 'Resource rates', self.recipes * self.result.x,
                               self.res_names, 2)


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

    # There's only one player, and he doesn't want to do a lot of manual labour unless really
    # necessary
    model.max_players(1)
    model.player_laziness(100)

    # These are the things we want to minimize
    model.resource_expense('Pollution', 1)
    model.resource_expense('Area', 1)

    # Also minimize net excess on things that will block up the production line
    model.resource_expense('Petroleum gas', 1)
    model.resource_expense('Light oil', 1)
    model.resource_expense('Heavy oil', 1)

    # This is our desired output
    model.min_recipe('Space science pack (Rocket silo)', 1)

    model.run()
    model.print(stdout)


if __name__ == '__main__':
    main()
