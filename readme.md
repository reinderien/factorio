# Factorio Analysis

## Intro

Factorio
([homepage](https://factorio.com),
[Steam](https://store.steampowered.com/app/427520))
is a fantastic top-down open-world RTS/factory game with an emphasis on 
automation and technical depth. There's no game I can't ruin by applying math! 

The purpose of this project is to get some analytical data about the game's
economics, and probably do some constrained linear programming optimization to
try out some "computed economies" at scale.

## Requirements

- [Python 3](https://python.org)
- [requests](https://python-requests.org)
- [scipy](https://scipy.org)
- [R](https://r-project.org) (optional)

## Database pull

The scripts don't interact with the game itself. Instead, they pull and scrape
data from 
[the wiki](https://wiki.factorio.com), 
an instance of
[MediaWiki](https://mediawiki.org). 
As luck would have it, MediaWiki has a pretty good
[REST API](https://www.mediawiki.org/wiki/API:Main_page),
and the API endpoint for the Factorio wiki is open. This means that we can:

- Pull structured infobox content for each item in the game, yielding data like
  production recipes, power consumption, etc. This is done by pulling content
  for the most recent revision of every page in the Infobox category.
- Pull titles for each page in the Archived category, so that we know which
  items to ignore.

The wiki has two instances - one documenting the experimental version of
Factorio (0.17 as of this writing), and the other documenting the stable version
(0.16). This project uses the stable version.

To download and save the game's item database, issue

    ./pull-items.py

To look at the resulting (large) JSON file, use `xzless`.
    
## Preprocessing

The data from the wiki are a colourful mix of inaccurate, incomplete,
inconsistently presented, and in a format not conducive to analysis. The
preprocessing step attempts to fix that:

    ./preprocess.py
    
To look at the resulting (>5MiB) CSV, use `xzless -S`, unwrapped lines being
crucial here. As you'll notice, the data are extremely sparse, but let's not
overcomplicate things by switching to a sparse format when `xz` already has a
0.3% (!) compression ratio.

The CSV is for consumption by R. In addition, a NumPy zipped matrix (.npz) and
metadata JSON file are created, for consumption by `analyse.py`.

## Analysis

`analyse.r` is a stub; you can hack on it if you want to manipulate the recipe
matrix. Currently, though, I'm moving toward using `analyse.py` and SciPy.

SciPy has
[a lot of options](https://docs.scipy.org/doc/scipy/reference/optimize.html)
for numerical optimization. We're interested in linear programming via
[linprog](https://docs.scipy.org/doc/scipy/reference/generated/scipy.optimize.linprog.html)
:

- Minimize c * x
- Subject to
    - A_ub * x <= b_ub
    - A_eq * x == b_eq
    - lb <= x <= ub

Variables:

- `c` is a 1*n row vector of coefficients of the linear objective function.
- `x` is an n*1 column vector of linear objective function variables to be 
  minimized. 
- `A_ub` is a p*n matrix of upper bound constraints.
- `b_ub` is a p*1 column vector of upper bound constraints.
- `A_eq` is a q*n matrix of equality constraints.
- `b_eq` is a q*1 column vector of equality constraints.
- `bounds` is either one (min, max) tuple applying to all variables in `x`, or a
  sequence of `n` (min, max) variables for each variable in `x`.

In our case:

- `n` is equal to 681, the number of recipes
- Each entry in `x` is a floating-point number representing the (potentially
  partial-use) quantity of that recipe in use; i.e. "five assembler machine 3
  producing copper coil"
- The `min` portion of `bounds` must be zero; i.e., we cannot have a negative
  number of recipes
- `c` must be calculated based on the requested objective function. This can be
  influenced by pollution, area, etc.
- `A_ub` must take into account the total number of whole or partial manual 
  tasks summing to 1. It must also take into account the fact that no resource
  rate can go below 0 for a sustainable process.
  
To calculate `c`, the objective function coefficient 1*n row vector, multiply an
expense r*1 column vector by the recipe r*n matrix, `r` being the number of
resources. The expense vector has one entry per resource.
