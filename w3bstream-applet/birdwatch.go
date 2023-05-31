package main

import (
	"fmt"
	"strings"
    "math"
	"math/big"
	"strconv"

	"encoding/hex"

	"github.com/mailru/easyjson"
	"github.com/tidwall/gjson"

	"birdwatch/model"

	"github.com/machinefi/w3bstream-wasm-golang-sdk/blockchain"
	"github.com/machinefi/w3bstream-wasm-golang-sdk/log"
	"github.com/machinefi/w3bstream-wasm-golang-sdk/stream"
	"github.com/machinefi/w3bstream-wasm-golang-sdk/database"
)

var chainId uint32 = 31337
var functionSelector = "f32078e8"
var maxTsTimeout uint32 = 43200

func main() {}

//export start
func _start(rid uint32) int32 {
	log.Log(fmt.Sprintf("start received: %d", rid))
	message, err := stream.GetDataByRID(rid)
	if err != nil {
		log.Log("error: " + err.Error())
		return -1
	}
	res := string(message)
	log.Log("Got the json: " + res)

	signal := model.Signal{}
	easyjson.Unmarshal(message, &signal)

	// TODO: Get Signature and check it

	signalAcc, err := getSignalAccumulator(signal.DeviceId)
	// if err != nil {
	// 	log.Log("error: " + err.Error())
	// 	return -1
	// }

	if (signalAcc.Account == "") {
		signalAcc.Account = strings.ToLower(signal.Account)
	}

	if (strings.ToLower(signalAcc.Account) != strings.ToLower(signal.Account)) {
		log.Log("error: Different accounts")
		return -1
	}

	// Discard old data if accumulated ts too old (and unclaimed)
	if (len(signalAcc.Latitudes) > 0 && signal.Timestamp > signalAcc.TimestampEnd + maxTsTimeout) {
		signalAcc = model.SignalAccumulator{}
	}
	
	// Update accumulator values
	signalAcc.Latitudes = append(signalAcc.Latitudes,signal.Latitude)
	signalAcc.Longitudes = append(signalAcc.Longitudes,signal.Longitude)
	if (signalAcc.TimestampStart == 0 || signal.Timestamp < signalAcc.TimestampStart) {
		signalAcc.TimestampStart = signal.Timestamp	
	}
	if (signalAcc.TimestampEnd == 0 || signal.Timestamp > signalAcc.TimestampEnd) {
		signalAcc.TimestampEnd = signal.Timestamp	
	}
	// Save in db
	err = setSignalAccumulator(signal.DeviceId,signalAcc)
	if err != nil {
		log.Log("error: " + err.Error())
		return -1
	}
	
	return 0
}

//export claim
func _claim(rid uint32) int32 {

	log.Log(fmt.Sprintf("start received: %d", rid))
	message, err := stream.GetDataByRID(rid)
	if err != nil {
		log.Log("error: " + err.Error())
		return -1
	}
	res := string(message)
	log.Log("Got the claim: " + res)
	data := gjson.Get(res, "data").String()[2:]
	dappAddress := gjson.Get(res, "address").String()
	
	// get device id and account
	// var abiJson = `[{"type": "event","name":"ActivityRequested","inputs":[{"type":"uint256"},{"type":"uint256"},{"type":"address"},{"type":"string"}]}]`

	nReq := new(big.Int)
	nReq.SetString(data[0:64], 16)
	log.Log("nReq: " + nReq.String())

	ts := new(big.Int)
	ts.SetString(data[64:128], 16)
	log.Log("ts: " + ts.String())

	account := "0x" + data[152:192]
	log.Log("account: " + account)

	strLength, err := strconv.ParseUint(data[256:320], 16, 64)
    if err != nil {
		log.Log("error: " + err.Error())
		return 0
    }

	devId, err := hex.DecodeString(data[320:(320+2*strLength)])
	if err != nil {
		log.Log("error: " + err.Error())
		return 0
	}
	deviceId := string(devId)
	log.Log("deviceId: " + deviceId)

	// deviceId := "dev001"
	// account := "0xf39Fd6e51aad88F6F4ce6aB8827279cffFb92266"

	signalAcc, err := getSignalAccumulator(deviceId)
	if (signalAcc.Account == "") {
		log.Log("Nothing accumulated yet")
		return 0
	}
	if (strings.ToLower(signalAcc.Account) != strings.ToLower(account)) {
		log.Log("error: Different accounts")
		return 0
	}

	// parse correct contract call
	if len(signalAcc.Latitudes) > 0 {
		// get signal summary
		signalSum := getSignalSummary(account,signalAcc)
		summaryStr, err := easyjson.Marshal(signalSum)
		if err != nil {
			log.Log("error: " + err.Error())
			return 0
		}
		log.Log("summaryStr: " + string(summaryStr))
		txPayload, err := geTxPayload(summaryStr)

		// send tx
		txRes, err := blockchain.SendTx(
			chainId, // chain id
			dappAddress, // Cartesi DApp contract address
			big.NewInt(0),
			txPayload,
		)
		if err != nil {
			log.Log("error: " + err.Error())
			return -1
		}
		log.Log("Tx result : " + txRes)

		err = deleteSignalAccumulator(deviceId)
		if err != nil {
			log.Log("error: " + err.Error())
			return 0
		}
	}

	return 0
}


func getSignalAccumulator(deviceId string) (model.SignalAccumulator, error) {

	signalAcc := model.SignalAccumulator{}

	res, err := database.Get(deviceId)
	if err != nil {
		return signalAcc, err
	}
	if len(res) != 0 {
		easyjson.Unmarshal(res, &signalAcc)
	}
	log.Log("get key: " + fmt.Sprint(signalAcc))
	
	return signalAcc, nil
}

func setSignalAccumulator(deviceId string, signalAcc model.SignalAccumulator) error {
	msg, err := easyjson.Marshal(signalAcc)
	if err != nil {
		return err
	}

	if err := database.Set(deviceId, []byte(msg)); err != nil {
		return err
	}
	log.Log("set key success: "+ string(msg))

	return nil
}

func deleteSignalAccumulator(deviceId string) error {
	if err := database.Set(deviceId, []byte("{}")); err != nil {
		return err
	}
	log.Log("Delete key success: " + deviceId)

	return nil
}

func getSignalSummary(account string,signalAcc model.SignalAccumulator) model.SignalSummary {
	numberOfSignals := len(signalAcc.Latitudes)
	var latAcc float64 = 0
	var lonAcc float64 = 0
	var maxRadius float64 = 0

    for i := 0; i < numberOfSignals; i++ {
        latAcc = latAcc + float64(signalAcc.Latitudes[i])
        lonAcc = lonAcc + float64(signalAcc.Longitudes[i])
    }
	latAcc = latAcc/float64(numberOfSignals)
	lonAcc = lonAcc/float64(numberOfSignals)
	var distance float64 = 0
    for i := 0; i < numberOfSignals; i++ {
        radius := math.Sqrt(math.Pow(float64(signalAcc.Latitudes[i])-latAcc,2) + math.Pow(float64(signalAcc.Longitudes[i])-lonAcc,2))
		if (radius > maxRadius) {
			maxRadius = radius 	
		}
		if (i > 0) {
        	distance = distance + 
				math.Sqrt(
					math.Pow(111000*(float64(signalAcc.Latitudes[i])-float64(signalAcc.Latitudes[i-1])),2) + // 1 deg lat ~> 111km
					math.Pow(73000*(float64(signalAcc.Longitudes[i])-float64(signalAcc.Longitudes[i-1])),2)) // 1 deg lon ~> 73km
		}
    }
	
	signalSummary := model.SignalSummary{}
	signalSummary.Account = account
	signalSummary.Timespan = signalAcc.TimestampEnd -signalAcc.TimestampStart
	signalSummary.CenterLatitude = float32(latAcc)
	signalSummary.CenterLongitude = float32(lonAcc)
	signalSummary.MaxRadius = float32(maxRadius)
	signalSummary.Distance = float32(distance)

	return signalSummary
}

func geTxPayload(payload []byte) (string, error) {
	hexPayload := hex.EncodeToString([]byte(payload))

	sizePayload := len(payload)
	log.Log(fmt.Sprintf("sizePayload: %d", sizePayload))

	padSize := 64 * (1 + 2*sizePayload/64)
	log.Log(fmt.Sprintf("padSize: %d", padSize))

	paddedHex := fmt.Sprintf("%s%0*s",string(hexPayload), padSize - 2*sizePayload, "")
	log.Log("paddedHex: " + paddedHex)

	withSizeHex := fmt.Sprintf("%0*x%s",64,sizePayload,paddedHex)
	log.Log("withSizeHex: " + withSizeHex)

	// type 0x20 (32 - bytes)
	bytesHex := fmt.Sprintf("%0*x%s",64,32,string(withSizeHex))
	log.Log("bytesHex: " + bytesHex)

	// 0xf32078e = addInput(bytes)
	txPayload := fmt.Sprintf("0x%s%s",functionSelector,string(bytesHex))
	log.Log("txPayload: " + txPayload)

	return txPayload, nil

}
