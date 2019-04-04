#!/usr/bin/env R -q --vanilla -f
options(echo=F)

# This is a dataframe of recipes by resources. It's in non-sparse format. You
# can do different stuff with this, like apply lpSolve or other optimization
# functions.
recipes = read.csv('recipes.csv.xz')
