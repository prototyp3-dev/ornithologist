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

from os import environ
import traceback
import logging
import requests
import json
from enum import Enum
import uuid

from eth_abi import decode, encode
import fiona
import pandas as pd
import numpy as np
from numpy.random import Generator, PCG64
from shapely.geometry.point import Point
from shapely.strtree import STRtree
from shapely.geometry import mapping, shape
from pyproj import Transformer
from Cryptodome.Hash import SHA512, SHA224


logging.basicConfig(level="INFO")
logger = logging.getLogger(__name__)

rollup_server = environ["ROLLUP_HTTP_SERVER_URL"]
logger.info(f"HTTP rollup_server url is {rollup_server}")

random_seed = 0

bird_contract_address = None
DAPP_BIRDS_GEO_FILE = environ["DAPP_BIRDS_GEO_FILE"]
DAPP_BIRDS_FILE = environ["DAPP_BIRDS_FILE"]

ENCOUNTER_INTERVAL = 120 # each 2 min
VISON_RANGE = 10 # 10 meters
DUEL_TIMEOUT = 600

###
# Initialization 

birds_geo = fiona.open(DAPP_BIRDS_GEO_FILE)
birds_df = pd.read_csv(DAPP_BIRDS_FILE, index_col=[0])

all_shapes = [shape(f['geometry']) for f in birds_geo]
shapes_tree = STRtree(all_shapes)

transformer = Transformer.from_crs("EPSG:4326","EPSG:3035")

###
# Birds Model 

class Location(Enum):
    DAPP = 1
    BASE_LAYER = 2

class BirdContractAction(Enum):
    ADMIN = 0
    BIRDWATCH = 1
    REGISTER_ERC721_ID = 2

class Bird:
    list_by_id = {} # id -> bird
    list_by_erc721_id = {} # erc721_id -> bird

    def __init__(self,ornithologist,species_name):
        self.ornithologist = ornithologist
        self.species_name = species_name
        self.location = Location.DAPP
        self.duels = []
        self.id = str(uuid.uuid4())
        self.erc721_id = None
        Bird.list_by_id[self.id] = self
        ornithologist = Ornithologist.get_ornithologist(self.ornithologist)
        ornithologist.bird_catalogue[self.id] = self

    def get_traits(self):
        return birds_df.loc[birds_df['key_0'] == self.species_name].to_dict('records')[0]

    def __str__(self):
        bird_dict = self.get_traits()
        bird_dict['id'] = self.id
        bird_dict['erc721_id'] = self.erc721_id
        bird_dict['location'] = self.location
        bird_dict['ornithologist'] = self.ornithologist
        bird_dict['duels'] = len(self.duels)
        bird_dict['wins'] = len(list(filter(lambda d: d.winner == self.id, self.duels)))
        return str(bird_dict)

    def __repr__(self):
        return self.__str__()
        
    def withdraw(self):
        voucher = None
        if bird_contract_address is None:
            raise Exception("bird_contract_address not yet defined")

        if self.erc721_id is None:
            # generate voucher to mint
            voucher = create_erc721_mint_voucher(bird_contract_address,self.ornithologist,self.id)
        else:
            # generate voucher to transfer
            voucher = create_erc721_safetransfer_voucher(bird_contract_address,rollup_address,self.ornithologist,self.erc721_id)

        if voucher:
            ornithologist = Ornithologist.get_ornithologist(self.ornithologist)
            del ornithologist.bird_catalogue[self.id]
            self.ornithologist = None
            self.location = Location.BASE_LAYER
            logger.info(f"voucher {voucher}")
            send_voucher(voucher)

    def get_encountered_summary():
        species_encountered = {}
        for k in Bird.list_by_id:
            v = Bird.list_by_id[k]
            if species_encountered.get(v.species_name) is None:
                species_encountered[v.species_name] = 0
            species_encountered[v.species_name] += 1
        # birds_df.loc[birds_df['key_0'] in species_encountered.keys()].to_dict('records')
        return str(species_encountered)

    def deposit(depositor,token_id):
        bird = Bird.list_by_erc721_id.get(token_id)
        if not bird:
            raise Exception("Bird not found, no erc721 id registered")
        bird.ornithologist = depositor
        ornithologist = Ornithologist.get_ornithologist(bird.ornithologist)
        ornithologist.bird_catalogue[bird.id] = bird
        bird.location = Location.DAPP
        return bird

    def register_erc721_id(bird_id,token_id):
        bird = Bird.list_by_id.get(bird_id)
        if not bird:
            raise Exception("Bird not found")
        bird.erc721_id = token_id
        Bird.list_by_erc721_id[token_id] = bird
        return bird


class Duel:
    list_by_id = {} # id -> duel
    accepted_traits = ['complete.measures', 'beak.length_culmen', 'beak.length_nares', 'beak.width', 
        'beak.depth', 'tarsus.length',  'wing.length', 'kipps.distance', 'secondary1', 'hand-wing.index', 
        'tail.length', 'mass']

    def __init__(self,timestamp,ornithologist1,ornithologist2,ornithologist1_commit,trait,compare_greater=True):
        ornithologist1_obj = Ornithologist.get_ornithologist(ornithologist1)
        ornithologist2_obj = Ornithologist.get_ornithologist(ornithologist2)
        if len(ornithologist1_obj.bird_catalogue) == 0:
            raise Exception("Sender ornithologist bird catalogue is empty")
        if len(ornithologist2_obj.bird_catalogue) == 0:
            raise Exception("Opponent ornithologist bird catalogue is empty")

        self.ornithologist1 = ornithologist1
        self.ornithologist2 = ornithologist2
        self.ornithologist1_commit = ornithologist1_commit
        self.bird1_id = None
        self.bird2_id = None
        self.timestamp = timestamp
        self.winner = None
        self.winner_ornithologist = None

        if not trait in Duel.accepted_traits:
            raise Exception("Trait not accepted to duels")

        self.trait = trait
        self.compare_greater = compare_greater
        self.id = Duel.generate_duel_id(ornithologist1,ornithologist2)
        
        if Duel.list_by_id.get(self.id):
            raise Exception("Duel already happening")
        Duel.list_by_id[self.id] = self

        ornithologist1_object = Ornithologist.get_ornithologist(self.ornithologist1)
        ornithologist2_object = Ornithologist.get_ornithologist(self.ornithologist2)
        ornithologist1_object.unfinished_duels[self.id] = self
        ornithologist2_object.unfinished_duels[self.id] = self

    def __str__(self):
        return_dict = { 'id': self.id, 'ornithologist1':self.ornithologist1, 'ornithologist2':self.ornithologist2, 'winner':self.winner, \
            'winner_ornithologist':self.winner_ornithologist, 'timestamp': self.timestamp, 'bird1_id':self.bird1_id, 'bird2_id':self.bird2_id, \
            'trait':self.trait, 'compare_greater':self.compare_greater}
        if self.winner:
            return_dict['status'] = 'finished'
        elif self.bird2_id:
            return_dict['status'] = f"waiting ornithologist 1 ({self.ornithologist1}) reveal"
        else:
            return_dict['status'] = f"waiting ornithologist 2 ({self.ornithologist2}) bird"
        return str(return_dict)

    def __repr__(self):
        return self.__str__()

    def cancel(self):
        if not (self.bird2_id is None):
            raise Exception("Can not cancel if ornithologist 2 has already chosen bird")
        del Duel.list_by_id[self.id]
        ornithologist1_object = Ornithologist.get_ornithologist(self.ornithologist1)
        ornithologist2_object = Ornithologist.get_ornithologist(self.ornithologist2)
        del ornithologist1_object.unfinished_duels[self.id]
        del ornithologist2_object.unfinished_duels[self.id]
        
    def add_ornithologist2_bird(self,timestamp,bird2_id):
        bird2 = Bird.list_by_id.get(bird2_id)
        if not bird2:
            raise Exception("Bird 2 not found")
        if bird2.location != Location.DAPP:
            raise Exception("Bird 2 not in Dapp")
        self.bird2_id = bird2.id
        self.timestamp = timestamp

    def claim_timeout(self,timestamp):
        if self.bird2_id is None:
            raise Exception("Can not claim timeout if ornithologist 2 has not chosen bird yet")
        if timestamp < self.timestamp + DUEL_TIMEOUT:
            raise Exception(f"Can not claim timeout yet")
        if self.bird1_id is not None:
            raise Exception("Can not claim timeout if ornithologist 1 has already chosen bird")
        winner = self.bird2_id
        self.resolve_duel(timestamp,winner)
        
    def check_bird_reveal(self,chosen_bird,nonce):
        bird_nonce = f"{chosen_bird}-{nonce}"
        h = SHA512.new(truncate="256", data=str2binary(bird_nonce))
        if h.hexdigest() != self.ornithologist1_commit:
            return False

        bird1 = Bird.list_by_id.get(chosen_bird)
        if not bird1:
            msg = f"Bird 1 not found"
            logger.warn(msg)
            report_payload = str2hex(str(msg))
            send_report({"payload": report_payload})
            return False
        if bird1.location != Location.DAPP:
            msg = f"Bird 1 not in Dapp"
            logger.warn(msg)
            report_payload = str2hex(str(msg))
            send_report({"payload": report_payload})
            return False

        return True

    def add_ornithologist1_reveal(self,timestamp,chosen_bird,nonce):
        winner = None
        if self.check_bird_reveal(chosen_bird,nonce):
            bird1 = Bird.list_by_id.get(chosen_bird)
            self.bird1_id = bird1.id
            winner = self.calculate_winner()
        else:
            winner = self.bird2_id
        self.resolve_duel(timestamp,winner)

    def calculate_winner(self):
        if (self.bird1_id is None) or (self.bird2_id is None):
            raise Exception(f"Birds not defined yet")

        bird1 = Bird.list_by_id.get(self.bird1_id)
        bird2 = Bird.list_by_id.get(self.bird2_id)
        
        bird1_traits = bird1.get_traits()
        bird2_traits = bird2.get_traits()

        winner = None
        if bird1_traits[self.trait] == bird2_traits[self.trait]:
            pass
        elif (self.compare_greater and bird1_traits[self.trait] > bird2_traits[self.trait]) or \
                (not self.compare_greater and bird1_traits[self.trait] < bird2_traits[self.trait]): 
            winner = bird1
        else: 
            winner = bird2

        return winner.id

    def resolve_duel(self,timestamp,winner):
        self.timestamp = timestamp
        self.winner = winner
        winner_bird = Bird.list_by_id.get(self.winner)
        self.winner_ornithologist = winner_bird.ornithologist

        bird1 = Bird.list_by_id.get(self.bird1_id)
        bird2 = Bird.list_by_id.get(self.bird2_id)

        if (bird1 is not None) and (bird2 is not None):
            bird1.duels.append(self)
            bird2.duels.append(self)

        ornithologist1_object = Ornithologist.get_ornithologist(self.ornithologist1)
        ornithologist2_object = Ornithologist.get_ornithologist(self.ornithologist2)
        ornithologist1_object.duels.append(self)
        ornithologist2_object.duels.append(self)
        del ornithologist1_object.unfinished_duels[self.id]
        del ornithologist2_object.unfinished_duels[self.id]

        del Duel.list_by_id[self.id]

    def generate_duel_id(ornithologist_a, ornithologist_b):
        if ornithologist_a.lower() == ornithologist_b.lower():
            raise Exception(f"Can not duel with yourself")
        ornithologist_list = sorted([ornithologist_a.lower(), ornithologist_b.lower()])
        ornithologists_str = f"{ornithologist_list[0]}-{ornithologist_list[1]}"
        return SHA224.new(data=str2binary(ornithologists_str)).hexdigest()[:10]


class Ornithologist:
    list_by_id = {} # address -> ornithologist
    def __init__(self,address):
        self.address = address
        self.duels = []
        self.unfinished_duels = {}
        self.bird_catalogue = {}
        Ornithologist.list_by_id[address] = self

    def __str__(self):
        return_dict = {'ornithologist': self.address, 'unfinished_duels': self.unfinished_duels, 'bird_catalogue': self.bird_catalogue}
        return_dict['duels'] = len(self.duels)
        return_dict['wins'] = len(list(filter(lambda d: d.winner_ornithologist == self.address, self.duels)))
        return str(return_dict)

    def __repr__(self):
        return self.__str__()

    def get_ornithologist(ornithologist_address):
        ornithologist = Ornithologist.list_by_id.get(ornithologist_address)
        if not ornithologist:
            ornithologist = Ornithologist(ornithologist_address)
        return ornithologist

###
# Aux Functions 

def str2hex(string):
    return binary2hex(str2binary(string))

def str2binary(string):
    return string.encode("utf-8")

def binary2hex(binary):
    return "0x" + binary.hex()

def hex2binary(hexstr):
    return bytes.fromhex(hexstr[2:])

def hex2str(hexstr):
    return binary2str(hex2binary(hexstr))

def binary2str(binary):
    return binary.decode("utf-8")

def send_voucher(voucher):
    send_post("voucher",voucher)

def send_report(report):
    send_post("report",report)

def send_notice(notice):
    send_post("notice",notice)

def send_post(endpoint,json_data):
    response = requests.post(rollup_server + f"/{endpoint}", json=json_data)
    logger.info(f"/{endpoint}: Received response status {response.status_code} body {response.content}")


###
# Portal Deposit headers

# Default header for ERC-20 transfers coming from the Portal, which corresponds
#   to the Keccak256-encoded string "ERC20_Transfer", as defined at
#   https://github.com/cartesi/rollups/blob/v0.8.2/onchain/rollups/contracts/facets/ERC20PortalFacet.sol
ERC20_DEPOSIT_HEADER = b'Y\xda*\x98N\x16Z\xe4H|\x99\xe5\xd1\xdc\xa7\xe0L\x8a\x990\x1b\xe6\xbc\t)2\xcb]\x7f\x03Cx'

# Default header for ERC-721 transfers coming from the Portal, which corresponds
#   to the Keccak256-encoded string "ERC721_Transfer", as defined at
#   https://github.com/cartesi/rollups/blob/v0.8.2/onchain/rollups/contracts/facets/ERC721PortalFacet.sol
ERC721_DEPOSIT_HEADER = b'd\xd9\xdeE\xe7\xdb\x1c\n|\xb7\x96\n\xd2Q\x07\xa67\x9bj\xb8[0DO:\x8drHW\xc1\xacx'

# Default header for Ether transfers coming from the Portal, which corresponds
# to the Keccak256-encoded string "Ether_Transfer", as defined at
#   https://github.com/cartesi/rollups/blob/v0.8.2/onchain/rollups/contracts/facets/EtherPortalFacet.sol
ETHER_DEPOSIT_HEADER = b'\xf2X\xe0\xfc9\xd3Z\xbd}\x83\x93\xdc\xfe~\x1c\xf8\xc7E\xdd\xca8\xaeA\xd4Q\xd0\xc5Z\xc5\xf2\xc4\xce'


###
# Selector of functions of solidity <contract>.call(<payload>)

# ERC-20 contract function selector to be called during the execution of a voucher,
#   which corresponds to the first 4 bytes of the Keccak256-encoded result of "transfer(address,uint256)"
ERC20_TRANSFER_FUNCTION_SELECTOR = b'\xa9\x05\x9c\xbb'

# ERC-721 contract function selector to be called during the execution of a voucher,
#   which corresponds to the first 4 bytes of the Keccak256-encoded result of "safeTransferFrom(address,address,uint256)"
ERC721_SAFETRANSFER_FUNCTION_SELECTOR = b'B\x84.\x0e'

# EtherPortalFacet contract function selector to be called during the execution of a voucher,
#   which corresponds to the first 4 bytes of the Keccak256-encoded result of "etherWithdrawal(bytes)"
ETHER_WITHDRAWAL_FUNCTION_SELECTOR = b't\x95k\x94'

# ERC721 contract function selector to be called during the execution of a voucher,
#   which corresponds to the first 4 bytes of the Keccak256-encoded result of "mint(address,string)"
ERC721_MINTTOADDRESS_FUNCTION_SELECTOR = b'\xd0\xde\xf5!'

# Set Dapp Address contract function selector called during setup to set the dapp address,
#   which corresponds to the first 4 bytes of the Keccak256-encoded result of "sendBirdAddress()"
BIRD_SENDBIRDADDRESS_FUNCTION_SELECTOR = b'\xe8A\xebW'


###
# Create Voucher Aux Functions 

def create_erc20_transfer_voucher(token_address,receiver,amount):
    # Function to be called in voucher [token_address].transfer([address receiver],[uint256 amount])
    data = encode(['address', 'uint256'], [receiver,amount])
    voucher_payload = binary2hex(ERC20_TRANSFER_FUNCTION_SELECTOR + data)
    voucher = {"address": token_address, "payload": voucher_payload}
    return voucher

def create_erc721_safetransfer_voucher(token_address,sender,receiver,token_id):
    # Function to be called in voucher [token_address].transfer([address sender],[address receiver],[uint256 id])
    data = encode(['address', 'address', 'uint256'], [sender,receiver,token_id])
    voucher_payload = binary2hex(ERC721_SAFETRANSFER_FUNCTION_SELECTOR + data)
    voucher = {"address": token_address, "payload": voucher_payload}
    return voucher

def create_ether_withdrawal_voucher(receiver,amount):
    # Function to be called in voucher [rollups_address].etherWithdrawal(bytes) where bytes is ([address receiver],[uint256 amount])
    data = encode(['address', 'uint256'], [receiver,amount])
    data2 = encode(['bytes'],[data])
    voucher_payload = binary2hex(ETHER_WITHDRAWAL_FUNCTION_SELECTOR + data2)
    voucher = {"address": rollup_address, "payload": voucher_payload}
    return voucher

def create_erc721_mint_voucher(token_address,receiver,string_data):
    # Function to be called in voucher [token_address].mint([address receiver],[string string_data])
    data = encode(['address', 'string'], [receiver,string_data])
    voucher_payload = binary2hex(ERC721_MINTTOADDRESS_FUNCTION_SELECTOR + data)
    voucher = {"address": token_address, "payload": voucher_payload}
    return voucher


###
# Decode Inputs Aux Functions 

def decode_erc20_deposit(binary):
    decoded = decode(['bytes32', 'address', 'address', 'uint256', 'bytes'], binary)
    erc20_deposit = {
        "depositor":decoded[1],
        "token_address":decoded[2],
        "amount":decoded[3],
        "data":decoded[4],
    }
    logger.info(erc20_deposit)
    return erc20_deposit

def decode_erc721_deposit(binary):
    decoded = decode(['bytes32', 'address', 'address', 'address', 'uint256', 'bytes'], binary)
    erc721_deposit = {
        "token_address":decoded[1],
        "operator":decoded[2],
        "depositor":decoded[3],
        "token_id":decoded[4],
        "data":decoded[5],
    }
    logger.info(erc721_deposit)
    return erc721_deposit

def decode_ether_deposit(binary):
    decoded = decode(['bytes32', 'address', 'uint256', 'bytes'], binary)
    ether_deposit = {
        "depositor":decoded[1],
        "amount":decoded[2],
        "data":decoded[3],
    }
    logger.info(ether_deposit)
    return ether_deposit

def decode_birdwatch_input(payload):
    str_payload = binary2str(payload)
    summary = json.loads(str_payload)

    # transform coordinates to the used on geo file
    y,x = transformer.transform(summary['y'],summary['x']) # coordinates
    y2,x2 = transformer.transform(summary['y'],summary['x']+summary['r'])
    r = x2-x # radius

    birdwatch_input = {
        "longitude":x,
        "latitude":y,
        "radius":r,
        "distance":summary['d'],
        "timespan":summary['t'],
        "account":summary['a']
    }
    return birdwatch_input


###
#  Process Input Functions 

# input from birdwatch contract
def process_bird_contract_input(payload):
    binary = hex2binary(payload)
    action_index = int.from_bytes(binary[0:1], "little")
    logger.info(f"action_index {action_index}")
    
    returned_bird = None

    if action_index == BirdContractAction.BIRDWATCH.value:
        birdwatch_payload = binary[1:]
        returned_bird = process_birdwatch(birdwatch_payload)

    elif action_index == BirdContractAction.REGISTER_ERC721_ID.value:
        token_id = int.from_bytes(binary[1:33], "big")
        bird_id = binary2str(binary[33:])
        returned_bird = Bird.register_erc721_id(bird_id,token_id)

    else:
        raise Exception(f"Invalid action index {action_index}")

    if returned_bird:
        logger.info(f"Send notice {returned_bird}")
        send_notice({"payload": str2hex(str(returned_bird))})


def process_birdwatch(payload):
    birdwatch_input = decode_birdwatch_input(payload)
    logger.info(f"Processing birdwatch input {birdwatch_input}")

    # Simple probability of encountering a bird
    #   The centroid and radius define a region of birds that live in the area
    #   From all possible birds, define a rectangle of vision given by the distance and a fixed vision range
    #   Each interval, run a new 
    # TODO: enhance this method

    # The region walked is the centroid and the radius
    walk_region = Point(birdwatch_input['longitude'],birdwatch_input['latitude']).buffer(birdwatch_input['radius'])

    # Birds that could have been crossed according to their regiosn
    crossed_by_birds = shapes_tree.query(walk_region)
    birds_codes_in_area = []
    for bird_type in crossed_by_birds:
        b = birds_geo.__getitem__(shapes_tree.nearest_item(bird_type))
        birds_codes_in_area.append(b['properties']['speciescodeEU'])
    
    birds_codes_in_area = list(set(birds_codes_in_area))

    # df of possible birds crossed
    possible_birds = birds_df[birds_df['speciescode'].isin(birds_codes_in_area)]

    total_density = sum(possible_birds['density'])

    # each 2 min a new encounter
    n_encounters = int(birdwatch_input['timespan'] / ENCOUNTER_INTERVAL)

    # approximation 
    area_checked = birdwatch_input['distance'] * VISON_RANGE

    # probabiliy of each bird encounter
    n_possible = len(possible_birds['density'])
    probabilities = possible_birds['density']/total_density

    # get bird specie per encounter
    rnd_generator = Generator(PCG64(random_seed))
    chosen = []
    for i in range(n_encounters):
        chosen.append(rnd_generator.choice(possible_birds.index,p=probabilities))
    chosen = list(set(chosen))
    chosen_birds = possible_birds.loc[chosen]

    # the least common bird encountered is the one registered
    least_common_bird = chosen_birds[chosen_birds['density'].min() == chosen_birds['density']]

    # create new bird
    return Bird(birdwatch_input['account'],least_common_bird['key_0'].iloc[0])

# input from admin
def process_admin(sender,payload):
    binary = hex2binary(payload)
    action_index = int.from_bytes(binary[0:1], "little")
    logger.info(f"action_index {action_index}")
    
    function_signature = binary[1:]

    if action_index != BirdContractAction.ADMIN.value or function_signature != BIRD_SENDBIRDADDRESS_FUNCTION_SELECTOR:
        raise Exception("Could not define the bird contract address: wrong payload")

    global bird_contract_address
    bird_contract_address = sender
    msg = f"The configured bird contract address is {bird_contract_address}"
    logger.info(f"Send notice {msg}")
    send_notice({"payload": str2hex(str(msg))})
    return True

# input from users
def process_input(metadata,json_input):
    action = json_input.get('action')
    msg_return = None
    if action == 'withdraw': 
        msg_return = process_withdraw(metadata['msg_sender'],json_input)
    elif action == 'duel':
        msg_return = process_duel(metadata['msg_sender'],metadata['timestamp'],json_input)
    else:
        raise Exception(f"Unrecognized 'action' {action}")
        
    if msg_return:
        logger.info(f"Send notice {msg_return}")
        send_notice({"payload": str2hex(str(msg_return))})

def process_withdraw(sender,json_input):
    bird_id = json_input.get('bird')
    if not bird_id:
        raise Exception("'bird' id not informed")
    bird = Bird.list_by_id.get(bird_id)
    if not bird:
        raise Exception("Bird not found")
        
    if bird.ornithologist != sender:
        raise Exception("Bird current ornithologist is not sender")
    
    bird.withdraw()

def process_duel(sender,timestamp,json_input):
    opponent = json_input.get('opponent')
    if not opponent:
        raise Exception("Opponent ornithologist address not informed")

    duel_id = Duel.generate_duel_id(sender,opponent)
    duel = Duel.list_by_id.get(duel_id)

    if not duel:
        # create new duel
        ornithologist1_commit = json_input.get('commit')
        if not ornithologist1_commit:
            raise Exception("Commit (from ornithologist 1) not informed")
        trait = json_input.get('trait')
        if not trait:
            raise Exception("Trait to compare not informed")
        compare_greater = json_input.get('compare_greater')
        if not (compare_greater is None):
            compare_greater = bool(json.loads(compare_greater) if type(compare_greater) == type('') else compare_greater)
            duel = Duel(timestamp,sender,opponent,ornithologist1_commit,trait,compare_greater)
        else:
            duel = Duel(timestamp,sender,opponent,ornithologist1_commit,trait)

    elif not duel.bird2_id:
        # ornithologist 2 should send his bird or ornithologist 1 cancel the duel
        if sender == duel.ornithologist2:
            bird2 = json_input.get('bird')
            if bird2 is None:
                raise Exception("You must provide the 'bird' id")
            duel.add_ornithologist2_bird(timestamp, bird2)

        elif sender == duel.ornithologist1:
            cancel = json_input.get('cancel')
            if (not (cancel is None)) and bool(json.loads(cancel) if type(cancel) == type('') else cancel):
                duel.cancel()
                return f"Duel canceled: {duel}"
        else:
            raise Exception("User not in this duel")
    else:
        # resolve duel with ornithologist 1 reveal or ornithologist 2 timeout request
        if sender == duel.ornithologist2:
            timeout = json_input.get('timeout')
            if (not (timeout is None)) and bool(json.loads(timeout) if type(timeout) == type('') else timeout):
                duel.claim_timeout(timestamp)

        elif sender == duel.ornithologist1:
            bird1 = json_input.get('bird')
            nonce = json_input.get('nonce')
            if bird1 is None:
                raise Exception("You must provide the 'bird' id")
            if nonce is None:
                raise Exception("You must provide the 'nonce' used in commit")
            duel.add_ornithologist1_reveal(timestamp,bird1,nonce)
        else:
            pass

    return duel

# input from portals
def process_deposit_and_generate_voucher(payload):
    binary = hex2binary(payload)
    input_header = decode(['bytes32'], binary)[0]
    logger.info(f"header {input_header}")
    voucher = None

    if input_header == ERC20_DEPOSIT_HEADER:
        erc20_deposit = decode_erc20_deposit(binary)

        # send deposited erc20 back to depositor
        token_address = erc20_deposit["token_address"]
        receiver = erc20_deposit["depositor"]
        amount = erc20_deposit["amount"]

        voucher = create_erc20_transfer_voucher(token_address,receiver,amount)

    elif input_header == ERC721_DEPOSIT_HEADER:
        erc721_deposit = decode_erc721_deposit(binary)

        token_address = erc721_deposit["token_address"]
        depositor = erc721_deposit["depositor"]
        token_id = erc721_deposit["token_id"]

        if token_address == bird_contract_address:
            try:
                Bird.deposit(depositor,token_id)
            except Exception as e:
                msg = f"Error depositing: {e}"
                logger.error(f"{msg}\n{traceback.format_exc()}")
                send_report({"payload": str2hex(msg)})
                receiver = depositor
                voucher = create_erc721_safetransfer_voucher(token_address,rollup_address,receiver,token_id)
        else:
            # send deposited erc721 back to depositor
            receiver = depositor
            voucher = create_erc721_safetransfer_voucher(token_address,rollup_address,receiver,token_id)

    elif input_header == ETHER_DEPOSIT_HEADER:
        ether_deposit = decode_ether_deposit(binary)

        # send deposited ether back to depositor
        receiver = ether_deposit["depositor"]
        amount = ether_deposit["amount"]

        voucher = create_ether_withdrawal_voucher(receiver,amount)

    else:
        pass

    if voucher:
        logger.info(f"voucher {voucher}")
        send_voucher(voucher)



###
# handlers

def handle_advance(data):
    logger.info(f"Received advance request data {data}")

    try:
        # TODO: use better randomness technique
        random_seed = data["metadata"]['block_number']

        payload = data["payload"]
        voucher = None

        # Check whether an input was sent by the Portal,
        #   which is where all deposits must come from
        if data["metadata"]["msg_sender"] == rollup_address:
            logger.info(f"Processing portal input")
            process_deposit_and_generate_voucher(payload)
        elif data["metadata"]["msg_sender"] == bird_contract_address:
            logger.info(f"Processing bird address input")
            # Check whether an input was sent by the bird contract,
            process_bird_contract_input(payload)
        elif bird_contract_address is None:
            # Try to set bird contract address 
            logger.info(f"Processing admin bird address input")
            process_admin(data["metadata"]["msg_sender"],payload)
        else:
            # Otherwise, payload should be a json with the action choice
            str_payload = hex2str(payload)
            logger.info(f"Received {str_payload}")
            json_input = json.loads(str_payload)
            process_input(data["metadata"],json_input)
        
        return "accept"

    except Exception as e:
        msg = f"Error {e} processing data {data}"
        logger.error(f"{msg}\n{traceback.format_exc()}")
        send_report({"payload": str2hex(msg)})
        return "reject"

def handle_inspect(data):
    logger.info(f"Received inspect request data {data}")

    try:
        payload = data["payload"]

        inspected_payload = hex2str(payload).lower()
        logger.info(f"Inspect payload {inspected_payload}")

        response = Bird.list_by_id.get(inspected_payload)

        if not response:
            response = Duel.list_by_id.get(inspected_payload)

        if not response:
            response = Ornithologist.list_by_id.get(inspected_payload)

        if not response:
            response = Bird.get_encountered_summary()

        logger.info(f"report {response}")
        report_payload = str2hex(str(response))

        send_report({"payload": report_payload})

        return "accept"

    except Exception as e:
        msg = f"Error {e} processing data {data}"
        logger.error(f"{msg}\n{traceback.format_exc()}")
        send_report({"payload": str2hex(msg)})
        return "reject"


handlers = {
    "advance_state": handle_advance,
    "inspect_state": handle_inspect,
}


###
# Main Loop

finish = {"status": "accept"}
rollup_address = None

while True:
    logger.info("Sending finish")
    response = requests.post(rollup_server + "/finish", json=finish)
    logger.info(f"Received finish status {response.status_code}")
    if response.status_code == 202:
        logger.info("No pending rollup request, trying again")
    else:
        rollup_request = response.json()
        data = rollup_request["data"]
        if "metadata" in data:
            metadata = data["metadata"]
            if metadata["epoch_index"] == 0 and metadata["input_index"] == 0:
                rollup_address = metadata["msg_sender"]
                logger.info(f"Captured rollup address: {rollup_address}")
                continue
        handler = handlers[rollup_request["request_type"]]
        finish["status"] = handler(rollup_request["data"])

