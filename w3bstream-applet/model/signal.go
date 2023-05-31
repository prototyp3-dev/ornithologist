package model

//easyjson:json
type Signal struct {
	DeviceId    string      `json:"i"`
	Latitude    float32     `json:"y"`
	Longitude   float32     `json:"x"`
	Timestamp   uint32      `json:"t"`
	Signature   string      `json:"s"`
	Account     string      `json:"a"`
}