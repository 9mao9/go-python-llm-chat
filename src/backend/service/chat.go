package service

import (
	"errors"

	"chat-app/backend/model"
	"chat-app/backend/store"
)

var ErrSessionNotFound = errors.New("session not found")

type InferenceFunc func(systemPrompt string, history []model.Message, input string) (string, error)

func RecentTurns(history []model.Message) []model.Message {
	pairs := make([][2]model.Message, 0, 5)
	for i := len(history) - 1; i > 0 && len(pairs) < 5; {
		if history[i-1].Role == "user" && history[i].Role == "assistant" {
			pairs = append(pairs, [2]model.Message{history[i-1], history[i]})
			i -= 2
			continue
		}
		i--
	}

	recent := make([]model.Message, 0, len(pairs)*2)
	for i := len(pairs) - 1; i >= 0; i-- {
		recent = append(recent, pairs[i][0], pairs[i][1])
	}
	return recent
}

func SendMessage(
	sessions *store.SessionStore,
	sessionID string,
	input string,
	infer InferenceFunc,
) (string, error) {
	session, unlock, ok := sessions.Lock(sessionID)
	if !ok {
		return "", ErrSessionNotFound
	}
	defer unlock()

	if infer == nil {
		return "", errors.New("inference function is required")
	}

	response, err := infer(session.SystemPrompt, RecentTurns(session.History), input)
	if err != nil {
		return "", err
	}

	session.History = append(session.History,
		model.Message{Role: "user", Content: input},
		model.Message{Role: "assistant", Content: response},
	)
	return response, nil
}
