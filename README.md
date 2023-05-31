# Ornithologist DApp

```
This works for Cartesi Rollups version 0.8.x
```

The ornithologist DApp is an integration between IoT devices and a Cartesi DApp. The idea is that users will do birdwatches as amateurs ornithologists, and will encounter birds which will be minted as Non fungible tokens. The birds will be as rare as their extinction risk, and longer and further the birdwalks more probability to encounter a rarer bird. 

The data will flow from the IoT devices to the Cartesi DApp. The Iot device sends position inputs to w3bstream servers. Then, the users will do a web3 contract call to claim the birdwalk to get encountered bird tokens. The w3bstream servers will detect the contract call and return a summary of the birdwalk to the contract, which will forward the result to the Cartesi DApp. The Cartesi Dapp will use the birdwalk summary to calculate encounter probabilities of the bird species on the same region of the birdwalk. Then Cartesi Dapp will do a number of random choices to get the bird species encountered depending on the time span of the birdwalk, and will save the rarer encountered bird on the user's account. 

Users will be able to duel other users comparing traits of the owned bird tokens 

In summary users will interact with the project in many ways:
- users' IoT devices send birdwalk positions to w3bstream servers
- users send claim birdwalk to get a bird token in Cartesi DApp
- users duel other users comparing bird traits of owned bird tokens
- users withdraw the Birds ERC721, either by minting a new one or transfering a deposited bird token
- users deposit the Birds ERC721

DISCLAIMERS

This is not a final product and should not be used as one.

The database contains only Europe birds, and it is composed by a merge of 
- [Avonet Database](https://opentraits.org/datasets/avonet) to get the bird traits
- [EEA Database](https://www.eea.europa.eu/data-and-maps/data/article-12-database-birds-directive-2009-147-ec-1) to get the bird geolocations

downloaded in 2023-05

Also, we see that some improvements could be done to:
- better detect a birdwatch session, separate sessions into multiple, avoid claims, etc
- better probabilistic function of bird encouters
- better source of entropy

As final notes, the security of the IoT devices and the security of the W3bstream servers are out of the scope of this project.

## Requirements

Please refer to the [rollups-examples requirements](https://github.com/cartesi/rollups-examples/tree/main/README.md#requirements).

Tou will also need go and tinygo to build the wasm binaries.

## Building

### w3bstream-studio
To build the application, you must first build a custom image of the w3bstream-studio to allow local hardhat chain. you can download the w3bstream-studio source with, then apply the patch to add the hardhat chain. First define the version

```shell
W3BSTREAMSTUDIO_VERSION=1.2.1-rc2
```

Prepare the environment:

```shell
cd w3bstream-studio/
mkdir build && cd build
wget https://github.com/machinefi/w3bstream-studio/archive/refs/tags/v$W3BSTREAMSTUDIO_VERSION.tar.gz
tar xvf v$W3BSTREAMSTUDIO_VERSION.tar.gz
cd w3bstream-studio-$W3BSTREAMSTUDIO_VERSION/
patch -p1 < ../../add-localhost-w3bstream-studio.patch
```

Then define the built image as the one used in docker compose, and build the w3bstream-studio image

```shell
cd w3bstream-studio/build/w3bstream-studio-$W3BSTREAMSTUDIO_VERSION/
export WS_STUDIO_IMAGE=test/w3bstream-studio:main
docker build -f Dockerfile -t $WS_STUDIO_IMAGE .
```

### w3bstream wasm

To build the w3bstream wasm file youl will need go installed on your system and tinygo. To generate the wasm file, you should compile the birdwatch.go using tinygo

```shell
cd w3bstream-applet/
go mod tidy
tinygo build -o birdwatch.wasm -scheduler=none --no-debug -target=wasi birdwatch.go
```

If you do any changes to the model, you should rebuild the models

```shell
go get github.com/mailru/easyjson && go install github.com/mailru/easyjson/...@latest
cd w3bstream-applet/model/
go generate ./...
```

The go bin directory should be in path. 

### Cartesi DApp Image
 
Run the following command:

```shell
docker buildx bake -f docker-bake.hcl -f docker-bake.override.hcl --load
```

## Running

### Start 

First define the w3bstream-studio image:

```shell
export WS_STUDIO_IMAGE=test/w3bstream-studio:main
```

To start the application, execute the following command:

```shell
docker compose -f docker-compose.yml -f docker-compose.override.yml up
```

Open the w3bstream studio (http://localhost:3001/). In w3bstream studio 
1. create project with the built wasm
2. get the operator address on <project> -> settings. Also, save the PROJECT_NAME
3. transfer funds to w3bstream operator

Open the solidity contract (solidity/contracts/Bird.sol) in [Remix](https://remix.ethereum.org/), and:
1. compile and deploy the contract, and get the address
2. run the setOperatorAddress function with the operator address from w3btream
2. run the transferOwnership function to the DApp address (in localhost chain it should be 0xF8C694fd58360De278d5fF2276B7130Bfdc0192A)
2. run the sendBirdAddress function to send the contract address to DApp

You should configure the Cartesi DApp

```shell
yarn start input send --payload '{"admin":true,"bird_contract_address":"0x95401dc811bb5740090279Ba06cfA8fcF6113778"}'
```

Go back to the w3bstream studio (http://localhost:3001/). In w3bstream studio 
1. go to the created project
2. create device and save the DEVICE_NAME and DEVICE_TOKEN
3. create Smart contract monitor. Configuration:

```
Event Type: CLAIM
Chain ID: 31337
Contract address: <deployed contract address>
Smart Contract Event: ActivityRequested(uint256,uint256,address,string)
```

4. create Event routing (strategy). Configuration:

```
Event Type: CLAIM
Handler: claim
```

### Stop

The application can afterwards be shut down with the following command:

```shell
docker compose -f docker-compose.yml -f docker-compose.override.yml down -v
```

This will remove all containers and volumes

### Advancing time

When executing an example, it is possible to advance time in order to simulate the passing of epochs. To do that, run:

```shell
curl --data '{"id":1337,"jsonrpc":"2.0","method":"evm_increaseTime","params":[864010]}' http://localhost:8545
```

## Running the back-end in host mode

It is possible to run the Cartesi Rollups environment in [host mode](https://github.com/cartesi/rollups-examples/tree/main/README.md#host-mode), so that the DApp's back-end can be executed directly on the host machine, allowing it to be debugged using regular development tools such as an IDE. 

One important note is that Cartesi Rollups can't generate the voucher proofs in host mode, so you wouldn't be able to execute the vouchers.

To start the application, execute the following command:
```shell
docker compose -f docker-compose.yml -f docker-compose.override.yml -f docker-compose-host.yml up
```

The application can afterwards be shut down with the following command:
```shell
docker compose -f docker-compose.yml -f docker-compose.override.yml -f docker-compose-host.yml down -v
```

This DApp's back-end is written in Python, so to run it in your machine you need to have `python3` installed.
In order to start the back-end, run the following commands in a dedicated terminal to prepare the data:

```shell
cd dapp
python3 -m venv .venv
. .venv/bin/activate
pip install -r requirements.txt

mkdir data && cd data
export EEA_BIRDS_FILE="Article12_2020_birdsEUpopulation.csv"
export AVONET_BIRDS_FILE="AVONET1_BirdLife.csv"
export DAPP_BIRDS_GEO_FILE="birds_geo.gpkg"
export DAPP_BIRDS_FILE="birds_data.csv"
 
while read DEP; do wget -O $DEP; done < ../files
while read ZIP; do unzip $ZIP; done <<< $(ls | grep zip)
find . -type f -name *.gpkg -exec mv {} ../${DAPP_BIRDS_GEO_FILE} \;
find . -type f -name ${EEA_BIRDS_FILE} -exec cp {} .. \;
find . -type f -name ${AVONET_BIRDS_FILE} -exec cp {} .. \;
cd ..
rm -rf data

python3 prepare-data.py
```

And these commands after the data preparation to run the backend:

```shell
DAPP_BIRDS_GEO_FILE="birds_geo.gpkg" \
DAPP_BIRDS_FILE="birds_data.csv" \
ROLLUP_HTTP_SERVER_URL="http://127.0.0.1:5004" python3 ornithologist.py
```

The final command will effectively run the back-end and send corresponding outputs to port `5004`.
It can optionally be configured in an IDE to allow interactive debugging using features like breakpoints.

After that, you can interact with the application normally [as explained above](#interacting-with-the-application).

## Interacting with the application

### Sending position data

Send some data to the w3bstream server. Use the PROJECT_NAME, DEVICE_ID and DEVICE_TOKEN registered in w3bstream, and the ACCOUNT address of the first user

```shell
DEVICE_TOKEN="eyJh...vYzw"
DEVICE_ID="dev...001"
PROJECT_NAME="eth_0xf39f...2266_testproject"
ACCOUNT="0xf39f...92266"

curl -X POST "http://localhost:8889/srv-applet-mgr/v0/event/$PROJECT_NAME?eventType=DEFAULT&timestamp=$(date +%s)" -H 'Content-Type: application/json' -H "authorization: $DEVICE_TOKEN" -d "{\"a\":\"$ACCOUNT\",\"i\":\"$DEVICE_ID\",\"s\":\"\",\"x\":8.187715803601593,\"y\":48.42030672369912,\"t\":$(date +%s)}"

curl -X POST "http://localhost:8889/srv-applet-mgr/v0/event/$PROJECT_NAME?eventType=DEFAULT&timestamp=$(date +%s)" -H 'Content-Type: application/json' -H "authorization: $DEVICE_TOKEN" -d "{\"a\":\"$ACCOUNT\",\"i\":\"$DEVICE_ID\",\"s\":\"\",\"x\":8.187715803601593,\"y\":48.43030672369912,\"t\":$(($(date +%s) + 150))}"

curl -X POST "http://localhost:8889/srv-applet-mgr/v0/event/$PROJECT_NAME?eventType=DEFAULT&timestamp=$(date +%s)" -H 'Content-Type: application/json' -H "authorization: $DEVICE_TOKEN" -d "{\"a\":\"$ACCOUNT\",\"i\":\"$DEVICE_ID\",\"s\":\"\",\"x\":8.177715803601593,\"y\":48.43030672369912,\"t\":$(($(date +%s) + 300))}"
```

You can also send data for a second device

```shell
DEVICE_TOKEN="eyJh...vYzw"
DEVICE_ID="dev...002"
ACCOUNT="0x7099...79c8"

curl -X POST "http://localhost:8889/srv-applet-mgr/v0/event/$PROJECT_NAME?eventType=DEFAULT&timestamp=$(date +%s)" -H 'Content-Type: application/json' -H "authorization: $DEVICE_TOKEN" -d "{\"a\":\"$ACCOUNT\",\"i\":\"$DEVICE_ID\",\"s\":\"\",\"x\":10.187715803601593,\"y\":48.42030672369912,\"t\":$(date +%s)}"

curl -X POST "http://localhost:8889/srv-applet-mgr/v0/event/$PROJECT_NAME?eventType=DEFAULT&timestamp=$(date +%s)" -H 'Content-Type: application/json' -H "authorization: $DEVICE_TOKEN" -d "{\"a\":\"$ACCOUNT\",\"i\":\"$DEVICE_ID\",\"s\":\"\",\"x\":10.187715803601593,\"y\":48.43030672369912,\"t\":$(($(date +%s) + 150))}"

curl -X POST "http://localhost:8889/srv-applet-mgr/v0/event/$PROJECT_NAME?eventType=DEFAULT&timestamp=$(date +%s)" -H 'Content-Type: application/json' -H "authorization: $DEVICE_TOKEN" -d "{\"a\":\"$ACCOUNT\",\"i\":\"$DEVICE_ID\",\"s\":\"\",\"x\":10.177715803601593,\"y\":48.43030672369912,\"t\":$(($(date +%s) + 300))}"
```

Then, on the solidity contract (solidity/contracts/Bird.sol) in Remix run to get the bird token in the DApp:
- the reportBirdwatch function with the device sent to the w3bstream server

### Duel other users

The user can also directly interact with the application to duel other users, withdraw and deposit birds:

The duels are performed in commit reveal approach to compare birds' traits. The duel score will be persisted in DApp on the bird tokens' and users' information.

The flow of the duel is as follows:
1. an user can choose to duel any opponent. The message must contain the chosen trait to compare and the commitment of the bird chosen. which is the SHA512-256 of 'BIRD-NONCE' (<in dapp bird id> + '-' + <nonce: any non-predictable string>). The hash can be obtained using online tools such as [SHA512_256](https://emn178.github.io/online-tools/sha512_256.html). 
2. before the opponent sends his bird, the user can cancel the duel
3. the opponent sends the chosen bird
4. before the first user sends the reveal (and after the timeout period), the opponent can claim a timeout to win the duel
5. the first user sends the chosen bird with the nonce

Duel message examples:

user A 0xf39f...2266 commit: 
 
```json
{"action":"duel","opponent":"0x7099...79c8","trait":"mass","commit":"0d5f...0fad"}
```

user A 0xf39f...2266 cancel:

```json
{"action":"duel","opponent":"0x7099...79c8","cancel":true}
```

user B 0x7099...79c8 send bird (reveal): 

```json
{"action":"duel","opponent":"0xf39f...2266","bird":"d8c40...44f5"}
```

user B 0x7099...79c8 timeout:

```json
{"action":"duel","opponent":"0xf39f...2266","timeout":true}
```

user A 0xf39f...2266 reveal: 

```json
{"action":"duel","opponent":"0x7099...79c8","bird":"9b253...c82a","nonce":"abc...789"}
```

To withdraw the birds,the user can send the following message. If the bird was not minted yet it is minted first then transfered to the user.

```json
{"action":"withdraw","bird":"9b25...c82a"}
```
