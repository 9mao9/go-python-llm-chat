package service

import (
	"encoding/json"
	"errors"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"
	"time"

	"chat-app/backend/model"
)

func TestInferenceClientGenerate(t *testing.T) {
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.Method != http.MethodPost || r.URL.Path != "/generate" {
			t.Errorf("request = %s %s, want POST /generate", r.Method, r.URL.Path)
		}
		var payload struct {
			SystemPrompt string          `json:"system_prompt"`
			History      []model.Message `json:"history"`
			UserInput    string          `json:"user_input"`
		}
		if err := json.NewDecoder(r.Body).Decode(&payload); err != nil {
			t.Errorf("decode request: %v", err)
		}
		if payload.SystemPrompt != "Be helpful" ||
			payload.UserInput != "Hello" ||
			len(payload.History) != 1 ||
			payload.History[0] != (model.Message{Role: "user", Content: "Earlier"}) {
			t.Errorf("payload = %#v", payload)
		}
		w.Header().Set("Content-Type", "application/json")
		_, _ = w.Write([]byte(`{"text":"Hi!"}`))
	}))
	defer server.Close()

	client := NewInferenceClient(server.URL+"/", time.Second)
	got, err := client.Generate(
		"Be helpful",
		[]model.Message{{Role: "user", Content: "Earlier"}},
		"Hello",
	)
	if err != nil {
		t.Fatalf("Generate returned error: %v", err)
	}
	if got != "Hi!" {
		t.Fatalf("Generate = %q, want %q", got, "Hi!")
	}
}

func TestInferenceClientCurrentModel(t *testing.T) {
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.Method != http.MethodGet || r.URL.Path != "/models/current" {
			t.Errorf("request = %s %s, want GET /models/current", r.Method, r.URL.Path)
		}
		_, _ = w.Write([]byte(`{"model_id":"gemma","name":"Gemma","status":"ready"}`))
	}))
	defer server.Close()

	got, err := NewInferenceClient(server.URL, time.Second).CurrentModel()
	if err != nil {
		t.Fatalf("CurrentModel returned error: %v", err)
	}
	if got.ModelID == nil || *got.ModelID != "gemma" ||
		got.Name == nil || *got.Name != "Gemma" || got.Status != "ready" {
		t.Fatalf("CurrentModel = %#v", got)
	}
}

func TestInferenceClientClassifiesConnectionError(t *testing.T) {
	server := httptest.NewServer(http.NotFoundHandler())
	url := server.URL
	server.Close()

	_, err := NewInferenceClient(url, time.Second).CurrentModel()
	if !errors.Is(err, ErrInferenceConnection) {
		t.Fatalf("error = %v, want connection error", err)
	}
}

func TestInferenceClientClassifiesTimeout(t *testing.T) {
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, _ *http.Request) {
		time.Sleep(50 * time.Millisecond)
		_, _ = w.Write([]byte(`{"text":"too late"}`))
	}))
	defer server.Close()

	_, err := NewInferenceClient(server.URL, time.Millisecond).Generate("", nil, "Hi")
	if !errors.Is(err, ErrInferenceTimeout) {
		t.Fatalf("error = %v, want timeout error", err)
	}
}

func TestInferenceClientRejectsInvalidResponse(t *testing.T) {
	tests := []struct {
		name string
		body string
	}{
		{name: "invalid JSON", body: `not json`},
		{name: "missing text", body: `{}`},
		{name: "non-string text", body: `{"text":1}`},
	}
	for _, test := range tests {
		t.Run(test.name, func(t *testing.T) {
			server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, _ *http.Request) {
				_, _ = w.Write([]byte(test.body))
			}))
			defer server.Close()

			_, err := NewInferenceClient(server.URL, time.Second).Generate("", nil, "Hi")
			if !errors.Is(err, ErrInferenceResponse) {
				t.Fatalf("error = %v, want invalid response error", err)
			}
		})
	}
}

func TestInferenceClientPreservesHTTPError(t *testing.T) {
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, _ *http.Request) {
		w.WriteHeader(http.StatusServiceUnavailable)
		_, _ = w.Write([]byte(`{"detail":"model is not ready"}`))
	}))
	defer server.Close()

	_, err := NewInferenceClient(server.URL, time.Second).Generate("", nil, "Hi")
	var responseError *InferenceHTTPError
	if !errors.As(err, &responseError) {
		t.Fatalf("error = %v, want InferenceHTTPError", err)
	}
	if responseError.StatusCode != http.StatusServiceUnavailable ||
		!strings.Contains(responseError.Detail, "not ready") {
		t.Fatalf("HTTP error = %#v", responseError)
	}
}
