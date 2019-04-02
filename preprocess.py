#!/usr/bin/env python3

import json, re
from typing import Dict, Iterable


power_re = re.compile(r'([0-9.]+) ([kMG])W electric$')

si_facs = {
    c: 10**(3*i) for i, c in enumerate(('', 'k', 'M', 'G'))
}


def parse_power(s):
    m = power_re.match(s)
    return float(m[1]) * si_facs[m[2]]


class Recipe:
    def __init__(self, rates: dict = None, title: str = ''):
        if rates is None:
            self.rates = {}
        else:
            self.rates = rates
        self.title = title

    @staticmethod
    def parse_side(s: str) -> Dict[str, float]:
        out = {}
        for pair in s.split('+'):
            k, v = pair.split(',')
            out[k.strip()] = float(v.strip())
        return out

    @classmethod
    def parse_recipe(cls, s, output_title) -> Dict[str, float]:
        if '=' in s:
            inputs, outputs = s.split('=')
            recipe = cls.parse_side(outputs)
        else:
            inputs = s
            recipe = {output_title: 1}

        inputs = cls.parse_side(inputs)
        t = inputs.pop('Time')
        for k in recipe:
            recipe[k] /= t
        for k, v in inputs.items():
            recipe[k] = -v/t

        return recipe

    @classmethod
    def from_str(cls, s: str, output_title: str):
        r = Recipe()
        r.rates = cls.parse_recipe(s, output_title)
        return r

    def mutate_for_producer(self, producer):
        self.multiply_producer(producer)

        self.rates.update({
            'Pollution': float(producer.pollution),
            'Energy': -parse_power(producer.energy)
        })

    def multiply_producer(self, prod):
        rate = float(prod.crafting_speed)
        for k in self.rates:
            self.rates[k] *= rate

    def dupe_for_producer(self, producer, resource: str):
        title = f'{resource} ({producer.title})'
        rec = Recipe(dict(self.rates), title)
        rec.mutate_for_producer(producer)
        return rec


class MiningRecipe(Recipe):
    def __init__(self, title: str, mining_hardness: float, mining_time: float):
        super().__init__(title=title)
        self.mining_hardness, self.mining_time = mining_hardness, mining_time

    def multiply_producer(self, prod):
        power = float(prod.mining_power)
        speed = float(prod.mining_speed)
        self.rates = {
            self.title: (power - self.mining_hardness) *
            speed / self.mining_time
        }


class Item:
    def __init__(self, data: dict):
        self.data = data
        self.title, self.archived, self.producers, self.prototype_type, \
            self.crafting_speed, self.pollution, self.energy, self.recipe, \
            self.mining_hardness, self.mining_time \
            = (None,)*10
        self.__dict__.update({k.replace('-', '_'): v
                              for k, v in data.items()})

    @property
    def keep(self) -> bool:
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

    def for_producers(self, base_rec: Recipe) -> Iterable[Recipe]:
        return (base_rec.dupe_for_producer(p, self.title)
                for p in parse_producers(self.producers))

    def get_recipes(self) -> Iterable[Recipe]:
        if 'recipe' in self.data:
            base_rec = Recipe.from_str(self.recipe, self.title)
        elif 'mining-hardness' in self.data:
            base_rec = MiningRecipe(self.title,
                                    float(self.mining_hardness),
                                    float(self.mining_time))
        else:
            raise NotImplementedError()
        yield from self.for_producers(base_rec)


all_items: Dict[str, Item] = None


def parse_producers(s: str) -> Iterable[Item]:
    if s == 'Furnace':
        return (i for i in all_items.values()
                if i.prototype_type == 'furnace')
    return (all_items[p.strip()] for p in s.split('+')
            if 'manual' not in p.lower())


def trim(items: dict):
    to_delete = tuple(k for k, v in items.items() if not v.keep)
    print(f'Dropping {len(to_delete)} items...')
    for k in to_delete:
        del items[k]


def main():
    with open('recipes.json') as f:
        global all_items
        all_items = {k: Item(d) for k, d in json.load(f).items()}
    trim(all_items)

    '''
    Todo:
    Add Energy, Pollution resources and update all recipes
    
    Add all recipes:
    - All permitted producers:
        - miners (3)
        - assemblers (4)
        - Chemical plant, oil refinery
        - labs
        - power plants
    - 
    
    Be able to enforce these constraints:
    - minimum or maximize end production
    - maximum or minimize:
        - electric power capacity
        - mining/pumping capacity
        - surplus, particularly for petrochemicals
        - pollution 
    '''

    recipes = []
    resources = set()
    for item in all_items.values():
        item_recipes = item.get_recipes()
        recipes.extend(item_recipes)
        for recipe in item_recipes:
            resources.update(recipe.keys())


if __name__ == '__main__':
    main()
