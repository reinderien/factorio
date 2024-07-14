#!/usr/bin/env python3

import json, lzma, pathlib, re, typing
import numpy as np
import scipy.sparse
from collections import defaultdict


power_re = re.compile(r'([0-9.]+) .*([kMG])[WJ]')

si_facs = {
    c: 10**(3*i) for i, c in enumerate(('', 'k', 'M', 'G'))
}


class RecipeData(typing.TypedDict):
    building: str
    process: str
    inputs: dict[str, float]
    outputs: dict[str, float]


ItemData = typing.TypedDict(
    'ItemData',
    total=False,
    fields={
        'pageid': int,
        'title': str,
        'prototype-type': str,
        'internal-name': str,
        'expensive-total-raw': str,
        'expensive-recipe': str,
        'category': str,
        'stack-size': str,  # of an int
        'recipe': str,
        'total-raw': str,
        'required-technologies': str,
        'products': str,
        'consumers': str,
        'archived': bool,
        'recipes': tuple[RecipeData, ...]
    },
)


class Item:
    def __init__(self, data: ItemData) -> None:
        self.data = data

        self.archived: bool = False
        self.cost: str | None = None
        self.cost_multiplier: str | None = None
        self.crafting_speed: str | None = None
        self.dimensions: str | None = None
        self.energy: str | None = None
        self.fluid_consumption: str | None = None
        self.fuel_value: str | None = None
        self.mining_hardness: str | None = None
        self.mining_power: str | None = None
        self.mining_speed: str | None = None
        self.mining_time: str | None = None
        self.pollution: str | None = None
        self.power_output: str | None = None
        self.producers: str | None = None
        self.prototype_type: str | None = None
        self.recipe: str | None = None
        self.recipes: tuple[RecipeData, ...] = ()
        self.title: str | None = None
        self.valid_fuel: str | None = None

        self.__dict__.update({
            k.replace('-', '_'): v
            for k, v in data.items()
        })
        self.fill_gaps()

    def fill_gaps(self) -> None:
        if self.prototype_type == 'technology':
            self.producers = 'Lab'
        elif self.title in {'Flamethrower turret', 'Gun turret', 'Laser turret'}:
            self.producers = 'Assembling machine + manual'
        elif self.title == 'Space science pack':
            self.recipe = 'Time, 41.25 + Rocket part, 100 = Space science pack, 1000'
        elif self.title == 'Steam':
            ex_rate = 10e6 * 60 / 5.82e6
            self.recipes = (
                {
                    'process': 'Steam165 (Boiler)',
                    'building': 'Boiler',
                    'inputs': {
                        'Water': 60,
                        'Time': 1,
                    },
                    'outputs': {
                        'Steam165': 60,
                    },
                },
                {
                    'process': 'Steam500 (Heat exchanger)',
                    'building': 'Heat exchanger',
                    'inputs': {
                        'Water': ex_rate,
                        'Time': 1,
                    },
                    'outputs': {
                        'Steam500': ex_rate,
                    },
                },
            )

    def __str__(self) -> str:
        return self.title

    @property
    def keep(self) -> bool:
        return (
            (not self.archived) and
            (self.title not in {'Rock', 'Tree'}) and
            (
                any(self.data.get(k) for k in ('cost', 'recipe', 'recipes'))
                or 'mining-hardness' in self.data
                or self.title in {
                    'Crude oil', 'Water', 'Space science pack', 'Steam',
                }
            )
        )

    def get_recipes(self) -> typing.Iterator:
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


all_items: dict[str, Item] = {}


class ManualMiner:
    def __init__(self, tool: Item) -> None:
        self.tool = tool
        self.title = f'Manual with {tool}'
        self.pollution = 0
        self.dimensions = '0×0'

    def __str__(self) -> str:
        return self.title

    def mine_rate(self, mining_hardness: float, mining_time: float) -> float:
        return (
            0.6 * (float(self.tool.mining_power) - mining_hardness)
            / mining_time
        )


class Recipe:
    def __init__(
        self, resource: str, producer: Item, rates: dict,
        title: str | None = None,
    ) -> None:
        self.resource = resource
        if title:
            self.title = title
        else:
            self.title = f'{resource} ({producer})'

        self.rates = dict(rates)
        self.producer = producer
        self.multiply_producer(producer)

    def __str__(self) -> str:
        return self.title

    def multiply_producer(self, prod: Item) -> None:
        if prod.title in {'Boiler', 'Heat exchanger', 'Solar panel',
                          'Steam engine', 'Steam turbine'}:
            pass  # no crafting rate modifier
        elif prod.title == 'Nuclear reactor':
            self.rates['Heat'] = parse_power(prod.energy)
        else:
            rate = float(prod.crafting_speed)
            for k in self.rates:
                self.rates[k] *= rate


class MiningRecipe(Recipe):
    def __init__(
        self, resource: str, producer: Item, rates: dict,
        mining_hardness: float, mining_time: float, title: str = '',
    ) -> None:
        self.mining_hardness, self.mining_time = mining_hardness, mining_time
        super().__init__(resource, producer, rates, title)

    def multiply_producer(self, miner: Item) -> None:
        self.rates[self.resource] = self.producer.mine_rate(
            self.mining_hardness, self.mining_time
        )
        if self.resource == 'Uranium ore':
            self.rates['Sulphuric acid'] = -self.rates[self.resource]


class TechRecipe(Recipe):
    def __init__(
        self, resource: str, producer: Item, rates: dict,
        cost_multiplier: float, title: str = '',
    ) -> None:
        self.cost_multiplier = cost_multiplier
        super().__init__(resource, producer, rates, title)

    def multiply_producer(self, lab: Item) -> None:
        self.rates[self.resource] /= self.cost_multiplier


class FluidRecipe(Recipe):
    """Pump jacks, offshore pumps"""
    def multiply_producer(self, producer: Item) -> None:
        if producer.title == 'Pumpjack':
            yield_factor = 1.00  # Assumed
            rate = 10*yield_factor
        elif producer.title == 'Offshore pump':
            rate = 1200
        else:
            raise NotImplementedError()
        self.rates[self.resource] = rate


class RecipeFactory:
    def __init__(self, resource: Item, rates: dict | None = None) -> None:
        self.resource = resource
        self.producers = ()
        if rates:
            self.producers, self.title, self.rates = self.intermediate(rates)
        else:
            self.title = None
            needs_producers = False
            recipe = resource.recipe or resource.cost
            if recipe:
                self.rates = self.parse_recipe(recipe)
                if resource.prototype_type == 'technology':
                    self.producers = (all_items['lab'],)
                else:
                    needs_producers = True
            else:
                if resource.mining_time or \
                        resource.title in {'Crude oil', 'Water'}:
                    self.rates = {}
                    if resource.title != 'Raw wood':
                        needs_producers = True
                else:
                    raise NotImplementedError()
            if needs_producers:
                self.producers = tuple(parse_producers(resource.producers))

    def __str__(self) -> str:
        return self.title

    def intermediate(self, rates) -> tuple[
        typing.Iterable[Item],
        str,
        dict,
    ]:
        building = rates.get('building')
        if building:
            producers = (all_items[building.lower()],)
        else:
            producers = parse_producers(self.resource.producers)
        title = rates['process']
        sane_rates = self.calc_recipe(rates['inputs'], rates['outputs'])
        return producers, title, sane_rates

    @staticmethod
    def parse_side(s: str) -> dict[str, float]:
        out = {}
        for pair in s.split('+'):
            k, v = pair.split(',')
            out[k.strip()] = float(v.strip())
        return out

    @staticmethod
    def calc_recipe(
        inputs: dict[str, float], outputs: dict[str, float],
    ) -> dict[str, float]:
        rates = defaultdict(float, outputs)
        if 'time' in inputs:
            k = 'time'
        else:
            k = 'Time'
        t = inputs.pop(k)
        for k in rates:
            rates[k] /= t
        for k, v in inputs.items():
            rates[k] -= v / t
        return rates

    def parse_recipe(self, recipe: str) -> dict[str, float]:
        if '=' in recipe:
            inputs, outputs = recipe.split('=')
            outputs = self.parse_side(outputs)
        else:
            inputs = recipe
            outputs = {self.resource.title: 1}

        return self.calc_recipe(self.parse_side(inputs), outputs)

    def produce(self, cls, producer, **kwargs):
        kwargs.setdefault('title', self.title)
        recipe = cls(self.resource.title, producer, self.rates, **kwargs)
        if producer.pollution:
            recipe.rates['Pollution'] = float(producer.pollution)

        dims = tuple(float(x) for x in producer.dimensions.split('×'))
        recipe.rates['Area'] = dims[0] * dims[1]

        return recipe

    def for_energy(self, cls, **kwargs) -> typing.Iterable[Recipe]:
        for producer in self.producers:
            energy = -parse_power(producer.energy)

            if 'electric' in producer.energy:
                recipe = self.produce(cls, producer, **kwargs)
                recipe.rates['Energy'] = energy
                yield recipe

            elif 'heat' in producer.energy:
                recipe = self.produce(cls, producer, **kwargs)
                recipe.rates['Heat'] = energy
                yield recipe

            elif 'burner' in producer.energy:
                for fuel_name in producer.valid_fuel.split('+'):
                    fuel_name = fuel_name.strip().lower()
                    fuel = all_items[fuel_name]
                    fuel_value = parse_power(fuel.fuel_value)
                    new_kwargs = dict(kwargs)
                    if self.title:
                        title = self.title
                    else:
                        title = f'{self.resource} ({producer})'
                    new_kwargs['title'] = f'{title} fueled by {fuel_name}'

                    recipe = self.produce(cls, producer, **new_kwargs)
                    recipe.rates[fuel.title] = energy / fuel_value
                    yield recipe
            else:
                raise NotImplementedError()

    tree_re = re.compile(r'(\d+) .*?\|([^}|]+)}')

    def wood_mining(self) -> typing.Iterable[MiningRecipe]:
        miners = tuple(
            ManualMiner(tool)
            for tool in all_items.values()
            if tool.prototype_type == 'mining-tool'
        )
        for m in self.tree_re.finditer(self.resource.mining_time):
            mining_time, source = int(m[1]), m[2]
            for miner in miners:
                yield self.produce(
                    MiningRecipe, miner,
                    mining_hardness=float(self.resource.mining_hardness),
                    mining_time=mining_time,
                    title=f'{self.resource} ({miner} from {source})')

    def make(self) -> typing.Iterator[Recipe]:
        if self.rates:
            if self.resource.prototype_type == 'technology':
                yield self.produce(
                    TechRecipe, self.producers[0],
                    cost_multiplier=float(self.resource.cost_multiplier))
            elif self.resource.title == 'Energy':
                yield self.produce(Recipe, self.producers[0])
            else:
                yield from self.for_energy(Recipe)
        elif self.resource.title == 'Raw wood':
            yield from self.wood_mining()
        elif self.resource.mining_time:
            yield from self.for_energy(
                MiningRecipe,
                mining_hardness=float(self.resource.mining_hardness),
                mining_time=float(self.resource.mining_time))
        elif self.resource.title == 'Crude oil':
            yield from self.for_energy(FluidRecipe)
        elif self.resource.title == 'Water':
            yield self.produce(FluidRecipe, self.producers[0])
        else:
            raise NotImplementedError()


def parse_power(s: str) -> float:
    m = power_re.search(s)
    return float(m[1]) * si_facs[m[2]]


def items_of_type(t: str) -> typing.Iterator[Item]:
    return (
        i for i in all_items.values()
        if i.prototype_type == t
    )


barrel_re = re.compile(r'empty .+ barrel')


def parse_producers(s: str) -> typing.Iterator[Item]:
    for p in s.split('+'):
        p = p.strip().lower()
        if p == 'furnace':
            yield from items_of_type('furnace')
        elif p == 'assembling machine':
            yield from (all_items[f'assembling machine {i}']
                        for i in range(1, 4))
        elif p == 'mining drill':
            yield from (all_items[f'{t} mining drill']
                        for t in ('burner', 'electric'))
        elif p == 'manual' or barrel_re.match(p):
            continue
        else:
            yield all_items[p]


def trim(items: dict[str, Item]) -> None:
    to_delete = tuple(k for k, v in items.items() if not v.keep)
    print(f'Dropping {len(to_delete)} items...')
    for k in to_delete:
        del items[k]


def energy_data() -> ItemData:
    solar_ave = parse_power(next(
        s for s in all_items['solar panel'].power_output.split('<br/>')
        if 'average' in s
    ))

    eng = all_items['steam engine']
    eng_rate = float(eng.fluid_consumption.split('/')[0])
    eng_power = parse_power(eng.power_output)

    turbine = all_items['steam turbine']
    turbine_rate = float(turbine.fluid_consumption.split('/')[0])
    turbine_power_500 = 5.82e6  # ignore non-precise data and use this instead
    turbine_power_165 = 1.8e6   # from wiki page body

    return {
        'title': 'Energy',
        'recipes': (
            {
                'building': 'Solar panel',
                'process': 'Energy (Solar panel)',
                'inputs': {
                    'Time': 1,
                },
                'outputs': {
                    'Energy': solar_ave,
                },
            },
            {
                'building': 'Steam engine',
                'process': 'Energy (Steam engine)',
                'inputs': {
                    'Time': 1,
                    'Steam165': eng_rate,
                },
                'outputs': {
                    'Energy': eng_power,
                },
            },
            {
                'building': 'Steam turbine',
                'process': 'Energy (Steam turbine @ 165C)',
                'inputs': {
                    'Time': 1,
                    'Steam165': turbine_rate,
                },
                'outputs': {
                    'Energy': turbine_power_165,
                },
            },
            {
                'building': 'Steam turbine',
                'process': 'Energy (Steam turbine @ 500C)',
                'inputs': {
                    'Time': 1,
                    'Steam500': turbine_rate,
                },
                'outputs': {
                    'Energy': turbine_power_500,
                },
            }
        )
    }


def load(fn: pathlib.Path) -> dict[str, Item]:
    with lzma.open(fn) as f:
        items = {k.lower(): Item(d) for k, d in json.load(f).items()}
    return items


def get_recipes() -> (dict[str, Recipe], set[str]):
    recipes = {}
    resources = set()
    for item in all_items.values():
        item_recipes = tuple(item.get_recipes())
        recipes.update({i.title: i for i in item_recipes})
        for recipe in item_recipes:
            resources.update(recipe.rates.keys())

    return recipes, resources


def field_size(names: typing.Iterable) -> int:
    return max(len(str(o)) for o in names)


def write_csv_for_r(
    recipes: typing.Sequence[Recipe], resources: typing.Sequence[str],
    fn: pathlib.Path,
) -> None:
    # Recipes going down, resources going right

    rec_width = field_size(recipes)
    float_width = 15
    col_format = f'{{:{float_width+8}}}'
    rec_format = '\n{:' + str(rec_width+1) + '}'

    with lzma.open(fn, 'wt') as f:
        f.write(' '*(rec_width+1))
        for res in resources:
            f.write(col_format.format(f'{res},'))

        for rec in recipes:
            f.write(rec_format.format(f'{rec},'))
            for res in resources:
                x = rec.rates.get(res, 0)
                col_format = f'{{:+{len(res)}.{float_width}e}},'
                f.write(col_format.format(x))


def write_for_numpy(
    recipes: typing.Sequence[Recipe], resources: typing.Sequence[str],
    meta_fn: pathlib.Path, npz_fn: pathlib.Path,
) -> None:
    rec_names = [r.title for r in recipes]
    w_rec = max(len(r) for r in rec_names)
    recipe_names = np.array(rec_names, copy=False, dtype=f'U{w_rec}')

    w_res = max(len(r) for r in resources)
    resource_names = np.array(resources, copy=False, dtype=f'U{w_res}')

    np.savez_compressed(meta_fn, recipe_names=recipe_names, resource_names=resource_names)

    rec_mat = scipy.sparse.lil_matrix((len(resources), len(recipes)))
    for j, rec in enumerate(recipes):
        for res, q in rec.rates.items():
            i = resources.index(res)
            rec_mat[i, j] = q
    scipy.sparse.save_npz(npz_fn, rec_mat.tocsr())


def file_banner(fn: pathlib.Path) -> None:
    print(f'{fn} {fn.stat().st_size//1024} KiB')


def main() -> None:
    fn = pathlib.Path('items.json.xz')
    print(f'Loading {fn}... ', end='')
    global all_items
    all_items = load(fn)
    print(f'{len(all_items)} items')

    all_items['energy'] = Item(energy_data())
    trim(all_items)

    print('Calculating recipes... ', end='')
    recipes, resources = get_recipes()
    print(f'{len(recipes)} recipes, {len(resources)} resources')

    resources = sorted(resources)
    recipes = sorted(recipes.values(), key=lambda i: i.title)

    print('Saving files for numpy...')
    meta_fn = pathlib.Path('recipe-names.npz')
    npz_fn = pathlib.Path('recipes.npz')
    write_for_numpy(recipes, resources, meta_fn, npz_fn)
    file_banner(meta_fn)
    file_banner(npz_fn)

    fn = pathlib.Path('recipes.csv.xz')
    print(f'Saving recipes for use by R...', flush=True)
    write_csv_for_r(recipes, resources, fn)
    file_banner(fn)


if __name__ == '__main__':
    main()
