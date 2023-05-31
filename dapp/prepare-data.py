# Copyright 2022 Cartesi Pte. Ltd.
#
# SPDX-License-Identifier: Apache-2.0
# Licensed under the Apache License, Version 2.0 (the "License"); you may not use
# this file except in compliance with the License. You may obtain a copy of the
# License at http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software distributed
# under the License is distributed on an "AS IS" BASIS, WITHOUT WARRANTIES OR
# CONDITIONS OF ANY KIND, either express or implied. See the License for the
# specific language governing permissions and limitations under the License.

# All data taken from 
#   https://www.eea.europa.eu/data-and-maps/data/article-12-database-birds-directive-2009-147-ec-1
#   https://opentraits.org/datasets/avonet

from os import environ
import pandas as pd
import numpy as np

# environment variables
EEA_BIRDS_FILE = f"{environ['EEA_BIRDS_FILE']}"
AVONET_BIRDS_FILE = f"{environ['AVONET_BIRDS_FILE']}"
DAPP_BIRDS_FILE = environ['DAPP_BIRDS_FILE']

# read data files
birds_df = pd.read_csv(EEA_BIRDS_FILE)
birds_traits_df = pd.read_csv(AVONET_BIRDS_FILE)

# lowercase columns
birds_df.columns = map(str.lower, birds_df.columns)
birds_traits_df.columns = map(str.lower, birds_traits_df.columns)

# remove unused columns
birds_traits_df = birds_traits_df[['species1', 'family1', 'order1', 'complete.measures',
       'beak.length_culmen', 'beak.length_nares', 'beak.width', 'beak.depth', 'tarsus.length', 
       'wing.length', 'kipps.distance', 'secondary1', 'hand-wing.index', 'tail.length', 'mass', 
       'habitat', 'habitat.density', 'migration', 'trophic.level',  'trophic.niche', 
       'primary.lifestyle']]

# Remove rows with no distribution data
birds_pop_df = birds_df.drop(birds_df[(birds_df['distribution_surface_area']==0) | (np.isnan(birds_df['distribution_surface_area']))].index)

# remove unused columns
birds_pop_df = birds_pop_df[['speciesname', 'speciescode', 'distribution_surface_area',
        'population_minimum_size', 'population_maximum_size', 'population_size_unit',
        'population_trend', 'population_trend_long', 'red_list_cat']]

# calculat a density to use as base probability of encoutering a bird
birds_pop_df['density'] = birds_pop_df.apply(
    lambda d: ((d['population_maximum_size'] + d['population_minimum_size'])/(2 if d['population_size_unit'] == 'i' else 1))/d['distribution_surface_area']
    ,axis=1)

# create a column to join data
birds_pop_df['speciesname_join'] = birds_pop_df.apply(
    lambda f: ' '.join(f['speciesname'].lower().split()[:2])
    , axis=1)
birds_traits_df['speciesname_join'] = birds_traits_df.apply(
    lambda f: ' '.join(f['species1'].lower().split()[:2])
    , axis=1)

# merge dataframes
birds_join_df = pd.merge(left=birds_pop_df,right=birds_traits_df,left_on=birds_pop_df['speciesname_join'],right_on=birds_traits_df['speciesname_join'],how='inner')
birds_join_df = birds_join_df.drop(columns=list(filter(lambda c: "speciesname_join" in c, birds_join_df.columns)))

# write to file
birds_join_df.to_csv(DAPP_BIRDS_FILE)

