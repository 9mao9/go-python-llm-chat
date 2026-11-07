package model

type Session struct {
	ID           string
	SystemPrompt string
	History      []Message
}
