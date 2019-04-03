#!/usr/bin/env R -q --vanilla -f
options(echo=F)

recipes = read.csv('recipes.csv.xz')

# Todo:
# Be able to enforce these constraints:
# - minimum or maximize end production
# - maximum or minimize:
#     - electric power capacity
#     - mining/pumping capacity
#     - surplus, particularly for petrochemicals
#     - pollution
