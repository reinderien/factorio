#!/usr/bin/env python3

import json, re
from typing import Dict, Iterable


power_re = re.compile(r'([0-9.]+) .*([kMG])(W|J)')

si_facs = {
    c: 10**(3*i) for i, c in enumerate(('', 'k', 'M', 'G'))
}


def parse_power(s: str) -> float:
    m = power_re.match(s)
    return float(m[1]) * si_facs[m[2]]


class Item:
    def __init__(self, data: dict):
        self.data = data
        self.title, self.archived, self.producers, self.prototype_type, \
            self.crafting_speed, self.pollution, self.energy, self.recipe, \
            self.mining_hardness, self.mining_time, self.cost, \
            self.cost_multiplier, self.recipes, self.valid_fuel, \
            self.fuel_value, self.mining_power, self.mining_speed = (None,)*17
        self.__dict__.update({k.replace('-', '_'): v
                              for k, v in data.items()})
        if self.prototype_type == 'technology':
            self.producers = 'Lab'

    def __str__(self) -> str:
        return self.title

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

    def get_recipes(self) -> Iterable:
        if self.recipes:
            for rates in self.recipes:
                fac = RecipeFactory(self, rates=rates)
                yield from fac.make()
        else:
            fac = RecipeFactory(self)
            yield from fac.make()

    def mine_rate(self, mining_hardness: float, mining_time: float) -> float:
        return (
                (float(self.mining_power) - mining_hardness)
                * float(self.mining_speed) / mining_time
        )


all_items: Dict[str, Item] = None


class ManualMiner:
    def __init__(self, tool: Item):
        self.tool = tool
        self.title = f'Manual with {tool}'

    def __str__(self) -> str:
        return self.title

    def mine_rate(self, mining_hardness: float, mining_time: float) -> float:
        return (
                0.6 * (float(self.tool.mining_power) - mining_hardness)
                / mining_time
        )


class Recipe:
    def __init__(self, resource: str, producer: Item, rates: dict,
                 title: str = None):
        self.resource = resource
        if title:
            self.title = title
        else:
            self.title = f'{resource} ({producer})'

        self.rates = rates
        self.producer = producer
        self.multiply_producer(producer)

    def __str__(self) -> str:
        return self.title

    def multiply_producer(self, prod: Item):
        rate = float(prod.crafting_speed)
        for k in self.rates:
            self.rates[k] *= rate


class MiningRecipe(Recipe):
    def __init__(self, resource: str, producer: Item, rates: dict,
                 mining_hardness: float, mining_time: float, title: str = ''):
        self.mining_hardness, self.mining_time = mining_hardness, mining_time
        super().__init__(resource, producer, rates, title)

    def multiply_producer(self, miner: Item):
        self.rates[self.resource] = self.producer.mine_rate(
            self.mining_hardness, self.mining_time
        )


class TechRecipe(Recipe):
    def __init__(self, resource: str, producer: Item, rates: dict,
                 cost_multiplier: float):
        self.cost_multiplier = cost_multiplier
        super().__init__(resource, producer, rates)

    def multiply_producer(self, lab: Item):
        self.rates[self.resource] /= self.cost_multiplier


class PumpjackRecipe(Recipe):
    def multiply_producer(self, pumpjack: Item):
        # Assume default 100% yield
        self.rates[self.resource] = 10


class RecipeFactory:
    def __init__(self, resource: Item, rates: dict = None):
        self.resource = resource
        self.producers = ()
        if rates:
            self.producers = (all_items[rates['building']],)
            self.title = rates['process']
            self.rates = self.calc_recipe(rates['inputs'], rates['outputs'])
        else:
            self.title = None
            recipe = resource.recipe or resource.cost
            if recipe:
                self.rates = self.parse_recipe(recipe)
                if resource.prototype_type == 'technology':
                    self.producers = (all_items['Lab'],)
            else:
                if resource.mining_time or resource.title == 'Crude oil':
                    self.rates = {}
                else:
                    raise NotImplementedError()
            if (not self.producers) and (resource.mining_time or recipe) and \
               resource.title != 'Raw wood':
                self.producers = tuple(parse_producers(resource.producers))

    @staticmethod
    def parse_side(s: str) -> Dict[str, float]:
        out = {}
        for pair in s.split('+'):
            k, v = pair.split(',')
            out[k.strip()] = float(v.strip())
        return out

    @staticmethod
    def calc_recipe(inputs: Dict[str, float],
                    outputs: Dict[str, float]) -> Dict[str, float]:
        rates = dict(outputs)
        t = inputs.pop('Time')
        for k in rates:
            rates[k] /= t
        for k, v in inputs.items():
            rates[k] = -v / t
        return rates

    def parse_recipe(self, recipe: str) -> Dict[str, float]:
        if '=' in recipe:
            inputs, outputs = recipe.split('=')
            outputs = self.parse_side(outputs)
        else:
            inputs = recipe
            outputs = {self.resource.title: 1}

        return self.calc_recipe(self.parse_side(inputs), outputs)

    def for_energy(self, cls, **kwargs) -> Iterable[Recipe]:
        for producer in self.producers:
            rates = dict(self.rates)

            if producer.pollution:
                rates['Pollution'] = float(producer.pollution)

            energy = -parse_power(producer.energy)
            if 'electric' in producer.energy:
                rates['Energy'] = energy
                yield cls(self.resource.title, producer, rates, **kwargs)
            elif 'burner' in producer.energy:
                for fuel_name in producer.valid_fuel.split('+'):
                    fuel_name = fuel_name.strip()
                    fuel = all_items[fuel_name]
                    fuel_value = parse_power(fuel.fuel_value)
                    rates_with_fuel = dict(rates)
                    rates_with_fuel[fuel.title] = energy / fuel_value
                    kwargs['title'] = (f'{self.resource} '
                                       f'({producer} '
                                       f'fueled by {fuel_name})')
                    yield cls(self.resource.title, producer,
                              rates_with_fuel, **kwargs)
            else:
                raise NotImplementedError()

    tree_re = re.compile(r'(\d+) .*?\|([^}|]+)\}')

    def wood_mining(self) -> Iterable[MiningRecipe]:
        miners = tuple(
            ManualMiner(tool)
            for tool in all_items.values()
            if tool.prototype_type == 'mining-tool'
        )
        for m in self.tree_re.finditer(self.resource.mining_time):
            mining_time, source = int(m[1]), m[2]
            for miner in miners:
                yield MiningRecipe(self.resource.title, miner, {},
                                   float(self.resource.mining_hardness),
                                   mining_time,
                                   title=f'{self.resource} '
                                   f'({miner} from {source})')

    def make(self) -> Iterable[Recipe]:
        if self.rates:
            if self.resource.prototype_type == 'technology':
                yield TechRecipe(self.resource.title, self.producers[0],
                                 self.rates,
                                 float(self.resource.cost_multiplier))
            else:
                yield from self.for_energy(Recipe, title=self.title)
        elif self.resource.title == 'Raw wood':
            yield from self.wood_mining()
        elif self.resource.mining_time:
            yield from self.for_energy(
                MiningRecipe,
                mining_hardness=float(self.resource.mining_hardness),
                mining_time=float(self.resource.mining_time))
        elif self.resource.title == 'Crude oil':
            yield from self.for_energy(PumpjackRecipe)
        else:
            raise NotImplementedError()


def parse_producers(s: str) -> Iterable[Item]:
    if s == 'Furnace':
        return (i for i in all_items.values()
                if i.prototype_type == 'furnace')
    if s == 'Assembling machine':
        return (i for i in all_items.values()
                if i.prototype_type == 'assembling-machine')
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
        try:
            item_recipes = tuple(item.get_recipes())
        except Exception as e:
            print(e)
            continue
        recipes.extend(item_recipes)
        for recipe in item_recipes:
            resources.update(recipe.rates.keys())


if __name__ == '__main__':
    main()
