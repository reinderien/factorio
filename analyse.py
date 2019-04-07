#!/usr/bin/env python3

import numpy as np
from math import ceil, log10
from scipy.optimize import linprog, OptimizeResult
from scipy.sparse import csr_matrix, load_npz
from sys import stdout
from typing import Iterable, List, TextIO


class Model:
    def __init__(self, recipes: csr_matrix, recipe_names: np.ndarray,
                 resource_names: np.ndarray):
        self.recipes = recipes.toarray()
        self.rec_names = recipe_names
        self.res_names = resource_names
        self.n_recipes = len(recipe_names)
        self.n_resources = len(resource_names)
        self.res_expenses: np.ndarray = np.zeros((1, self.n_resources))
        self.rec_expenses: np.ndarray = np.zeros((1, self.n_recipes))

        self.A_ub: np.ndarray = np.empty((0, self.n_recipes))
        self.b_ub: np.ndarray = np.empty((0, 1))

        # self.A_eq: np.ndarray = np.empty((0, self.n_recipes))
        # self.b_eq: np.ndarray = np.empty((0, 1))

        self.result: OptimizeResult = None

    def _add_ub(self, a: np.ndarray, b: float):
        self.A_ub = np.concatenate((self.A_ub, a))
        new_b = np.full((a.shape[0], 1), b)
        self.b_ub = np.concatenate((self.b_ub, new_b))

    def _manual_idx(self) -> List[bool]:
        return ['manual' in r.lower() for r in self.rec_names]

    def these_resources(self, *these: str) -> np.ndarray:
        return np.isin(self.res_names, these)

    def resources_but(self, *these: str) -> np.ndarray:
        return np.logical_not(self.these_resources(these))

    def these_recipes(self, *these: str) -> np.ndarray:
        return np.isin(self.rec_names, these)

    def recipes_but(self, *these: str) -> np.ndarray:
        return np.logical_not(self.these_recipes(these))

    def resource_equilibria(self, resources: np.ndarray):
        to_add = self.recipes[resources, :]
        self.A_eq = np.concatenate((self.A_eq, to_add))
        self.b_eq = np.concatenate((self.b_eq, np.zeros((len(to_add), 1))))

    def resource_expense(self, resources: np.ndarray, ex: float):
        self.res_expenses[0, resources] = ex

    def recipe_expense(self, recipes: np.ndarray, ex: float):
        self.rec_expenses[0, recipes] = ex

    def min_resource(self, resources: np.ndarray, rate: float):
        self._add_ub(-self.recipes[resources, :], -rate)

    def max_resource(self, resources: np.ndarray, rate: float):
        self._add_ub(self.recipes[resources, :], rate)

    def min_recipe(self, recipes: np.ndarray, rate: float):
        self._add_ub(np.expand_dims(np.where(recipes, -1, 0), 0), -rate)

    def max_recipe(self, recipes: np.ndarray, rate: float):
        self._add_ub(np.expand_dims(np.where(recipes, 1, 0), 0), rate)

    def player_laziness(self, l: float):
        self.rec_expenses[0, self._manual_idx()] += l

    def max_players(self, players: float):
        self._add_ub(np.expand_dims(np.where(self._manual_idx(), 1, 0), 0), players)

    def run(self):
        print('Optimizing...')

        c = np.matmul(self.res_expenses, self.recipes) + self.rec_expenses

        self.result = linprog(c=c, method='interior-point',
                              A_ub=self.A_ub, b_ub=self.b_ub,
                              # A_eq=self.A_eq, b_eq=self.b_eq,
                              options={})

    @staticmethod
    def title(f: TextIO, title: str):
        f.write(title)
        f.write('\n')
        f.write('-'*len(title))
        f.write('\n\n')

    @classmethod
    def diminishing_table(cls, f: TextIO, title: str, x: Iterable[float], names: Iterable[str],
                          digs: int):
        cls.title(f, title)

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

        # Initialize rates based on recipe and solution
        self.title(f, 'Resources')
        resources = np.empty(self.n_resources,
                             dtype=[
                                 ('rates', 'float64', (3,)),
                                 ('name', f'U{max(len(r) for r in self.res_names)}'),
                             ])
        rates = resources['rates']
        np.matmul(+self.recipes.clip(min=0), self.result.x, out=rates[:, 0])  # Produced
        np.matmul(-self.recipes.clip(max=0), self.result.x, out=rates[:, 1])  # Consumed
        np.matmul(+self.recipes,             self.result.x, out=rates[:, 2])  # Excess
        resources['name'] = self.res_names

        # Sort by produced, descending
        resources = resources[(-rates[:, 0]).argsort()]
        rates = resources['rates']

        # Filter by rates above a small margin
        eps = 1e-2
        to_show = np.any(np.abs(rates) > eps, axis=1)
        resources = resources[to_show]

        width = max(len(n) for n in resources['name'])
        titles = ('Produced', 'Consumed', 'Excess')
        name_fmt = f'{{:>{width}}} '
        fmt = name_fmt + ' '.join(
                '{:10.3e}' for _ in titles
              )

        print(name_fmt.format('Resource') + ' '.join(
            f'{t:>10}' for t in titles
        ))
        for row in resources:
            print(fmt.format(row['name'], *row['rates']))


def load_meta(fn) -> (np.ndarray, np.ndarray):
    print(f'Loading {fn}... ', end='')
    with np.load(fn) as meta:
        recipes, resources = meta['recipe_names'], meta['resource_names']
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
                  *load_meta('recipe-names.npz'))

    # There's only one player, and he doesn't want to do a lot of manual labour unless really
    # necessary
    model.max_players(1)
    model.player_laziness(100)

    # Closed system - no resource rate deficits
    model.min_resource(model.resources_but(), 0)

    # These are the things we want to minimize
    model.resource_expense(model.these_resources('Pollution', 'Area'), 1)

    # This is our desired output
    model.min_recipe(model.these_recipes('Space science pack (Rocket silo)'), 1)

    model.run()
    model.print(stdout)


if __name__ == '__main__':
    main()
