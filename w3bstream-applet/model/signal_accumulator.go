package model

//easyjson:json
type SignalAccumulator struct {
	Latitudes           []float32   `json:"lats"`
	Longitudes          []float32	`json:"lons"`
	TimestampStart      uint32      `json:"tsStart"`
	TimestampEnd        uint32      `json:"tsEnd"`
	Account             string      `json:"acc"`
}