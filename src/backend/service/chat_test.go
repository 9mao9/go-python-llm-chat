package service

import (
	"errors"
	"fmt"
	"testing"

	"chat-app/backend/model"
	"chat-app/backend/store"
)

func TestRecentTurns(t *testing.T) {
	tests := []struct {
		name    string
		history []model.Message
		want    []model.Message
	}{
		{name: "empty history", history: []model.Message{}, want: []model.Message{}},
		{
			name: "one turn",
			history: []model.Message{
				{Role: "user", Content: "u1"},
				{Role: "assistant", Content: "a1"},
			},
			want: []model.Message{
				{Role: "user", Content: "u1"},
				{Role: "assistant", Content: "a1"},
			},
		},
		{
			name:    "five turns",
			history: conversation(5),
			want:    conversation(5),
		},
		{
			name:    "six turns returns latest five",
			history: conversation(6),
			want:    conversation(6)[2:],
		},
		{
			name:    "incomplete trailing user is ignored",
			history: append(conversation(2), model.Message{Role: "user", Content: "unfinished"}),
			want:    conversation(2),
		},
		{
			name:    "incomplete trailing assistant is ignored",
			history: append(conversation(2), model.Message{Role: "assistant", Content: "orphan"}),
			want:    conversation(2),
		},
	}

	for _, test := range tests {
		t.Run(test.name, func(t *testing.T) {
			got := RecentTurns(test.history)
			if len(got) != len(test.want) {
				t.Fatalf("len(RecentTurns()) = %d, want %d; got %#v", len(got), len(test.want), got)
			}
			for i := range test.want {
				if got[i] != test.want[i] {
					t.Fatalf("RecentTurns()[%d] = %#v, want %#v", i, got[i], test.want[i])
				}
			}
		})
	}
}

func TestSendMessageKeepsCurrentInputSeparateAndAppendsOnSuccess(t *testing.T) {
	sessions := store.NewSessionStore()
	session := createTestSession(t, sessions)
	session.SystemPrompt = "Be helpful"
	session.History = conversation(1)
	if !sessions.Update(session.ID, session) {
		t.Fatal("failed to set up session")
	}

	response, err := SendMessage(sessions, session.ID, "current input",
		func(systemPrompt string, history []model.Message, input string) (string, error) {
			if systemPrompt != "Be helpful" {
				t.Errorf("system prompt = %q, want %q", systemPrompt, "Be helpful")
			}
			if len(history) != 2 || history[0].Content != "u1" || history[1].Content != "a1" {
				t.Errorf("inference history = %#v, want previous turn only", history)
			}
			if input != "current input" {
				t.Errorf("input = %q, want %q", input, "current input")
			}
			return "generated response", nil
		})
	if err != nil {
		t.Fatalf("SendMessage returned error: %v", err)
	}
	if response != "generated response" {
		t.Fatalf("response = %q, want generated response", response)
	}

	updated, ok := sessions.Get(session.ID)
	if !ok {
		t.Fatal("session not found after successful inference")
	}
	want := append(conversation(1),
		model.Message{Role: "user", Content: "current input"},
		model.Message{Role: "assistant", Content: "generated response"},
	)
	assertHistory(t, updated.History, want)
}

func TestSendMessageDoesNotUpdateHistoryOnInferenceError(t *testing.T) {
	sessions := store.NewSessionStore()
	session := createTestSession(t, sessions)
	initial := conversation(1)
	if !sessions.Update(session.ID, &model.Session{History: initial}) {
		t.Fatal("failed to set up session")
	}

	inferenceError := errors.New("inference failed")
	_, err := SendMessage(sessions, session.ID, "current input",
		func(string, []model.Message, string) (string, error) {
			return "", inferenceError
		})
	if !errors.Is(err, inferenceError) {
		t.Fatalf("error = %v, want %v", err, inferenceError)
	}

	updated, ok := sessions.Get(session.ID)
	if !ok {
		t.Fatal("session not found after inference error")
	}
	assertHistory(t, updated.History, initial)
}

func TestResetHistoryKeepsSystemPrompt(t *testing.T) {
	sessions := store.NewSessionStore()
	session := createTestSession(t, sessions)
	if !sessions.Update(session.ID, &model.Session{
		SystemPrompt: "Keep this prompt",
		History:      conversation(2),
	}) {
		t.Fatal("failed to set up session")
	}

	if !sessions.ResetHistory(session.ID) {
		t.Fatal("ResetHistory failed")
	}
	updated, ok := sessions.Get(session.ID)
	if !ok {
		t.Fatal("session not found after reset")
	}
	if updated.SystemPrompt != "Keep this prompt" {
		t.Fatalf("SystemPrompt = %q, want preserved prompt", updated.SystemPrompt)
	}
	if len(updated.History) != 0 {
		t.Fatalf("History = %#v, want empty", updated.History)
	}
}

func TestUpdateSystemPromptOnlyChangesTargetSession(t *testing.T) {
	sessions := store.NewSessionStore()
	first := createTestSession(t, sessions)
	second := createTestSession(t, sessions)

	if !sessions.UpdateSystemPrompt(first.ID, "First prompt") {
		t.Fatal("UpdateSystemPrompt failed")
	}
	updatedFirst, ok := sessions.Get(first.ID)
	if !ok {
		t.Fatal("first session not found")
	}
	updatedSecond, ok := sessions.Get(second.ID)
	if !ok {
		t.Fatal("second session not found")
	}
	if updatedFirst.SystemPrompt != "First prompt" || updatedSecond.SystemPrompt != "" {
		t.Fatalf("prompts = (%q, %q), want (%q, empty)",
			updatedFirst.SystemPrompt, updatedSecond.SystemPrompt, "First prompt")
	}
}

func TestSendMessageReturnsErrorForMissingSession(t *testing.T) {
	_, err := SendMessage(store.NewSessionStore(), "missing", "hello",
		func(string, []model.Message, string) (string, error) {
			t.Fatal("inference should not run for a missing session")
			return "", nil
		})
	if !errors.Is(err, ErrSessionNotFound) {
		t.Fatalf("error = %v, want %v", err, ErrSessionNotFound)
	}
}

func conversation(turns int) []model.Message {
	messages := make([]model.Message, 0, turns*2)
	for i := 1; i <= turns; i++ {
		messages = append(messages,
			model.Message{Role: "user", Content: fmt.Sprintf("u%d", i)},
			model.Message{Role: "assistant", Content: fmt.Sprintf("a%d", i)},
		)
	}
	return messages
}

func createTestSession(t *testing.T, sessions *store.SessionStore) *model.Session {
	t.Helper()
	session, err := sessions.Create()
	if err != nil {
		t.Fatalf("create session: %v", err)
	}
	return session
}

func assertHistory(t *testing.T, got, want []model.Message) {
	t.Helper()
	if len(got) != len(want) {
		t.Fatalf("history length = %d, want %d: %#v", len(got), len(want), got)
	}
	for i := range want {
		if got[i] != want[i] {
			t.Fatalf("history[%d] = %#v, want %#v", i, got[i], want[i])
		}
	}
}
