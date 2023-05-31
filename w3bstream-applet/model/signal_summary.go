package model

//easyjson:json
type SignalSummary struct {
	CenterLatitude      float32     `json:"y"`
	CenterLongitude     float32     `json:"x"`
	MaxRadius           float32     `json:"r"`
	Distance            float32     `json:"d"`
	Timespan            uint32      `json:"t"`
	Account             string      `json:"a"`
}