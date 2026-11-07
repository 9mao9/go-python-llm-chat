package main

import (
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"strings"
	"sync/atomic"
	"testing"
	"time"

	"github.com/labstack/echo/v5"

	"chat-app/backend/model"
	"chat-app/backend/service"
	"chat-app/backend/store"
)

func testServer(
	t *testing.T,
	pythonHandler http.Handler,
) (*echo.Echo, *store.SessionStore) {
	t.Helper()
	python := httptest.NewServer(pythonHandler)
	t.Cleanup(python.Close)
	sessions := store.NewSessionStore()
	client := service.NewInferenceClient(python.URL, time.Second)
	return newServerWithDependencies(sessions, client), sessions
}

func issueSessionCookie(t *testing.T, e *echo.Echo) *http.Cookie {
	t.Helper()
	recorder := httptest.NewRecorder()
	e.ServeHTTP(
		recorder,
		httptest.NewRequest(http.MethodPost, "/api/session", nil),
	)
	if recorder.Code != http.StatusCreated {
		t.Fatalf("session status = %d, want %d", recorder.Code, http.StatusCreated)
	}
	cookies := recorder.Result().Cookies()
	if len(cookies) != 1 {
		t.Fatalf("session cookie count = %d, want 1", len(cookies))
	}
	return cookies[0]
}

func requestWithCookie(
	e *echo.Echo,
	method string,
	path string,
	body string,
	cookie *http.Cookie,
) *httptest.ResponseRecorder {
	request := httptest.NewRequest(method, path, strings.NewReader(body))
	if body != "" {
		request.Header.Set("Content-Type", "application/json")
	}
	if cookie != nil {
		request.AddCookie(cookie)
	}
	recorder := httptest.NewRecorder()
	e.ServeHTTP(recorder, request)
	return recorder
}

func TestChatUsesPythonAPIAndStoresSuccessfulHistory(t *testing.T) {
	var gotPayload struct {
		SystemPrompt string          `json:"system_prompt"`
		History      []model.Message `json:"history"`
		UserInput    string          `json:"user_input"`
	}
	pythonHandler := http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.Method != http.MethodPost || r.URL.Path != "/generate" {
			t.Errorf("Python request = %s %s, want POST /generate", r.Method, r.URL.Path)
		}
		if err := json.NewDecoder(r.Body).Decode(&gotPayload); err != nil {
			t.Errorf("decode Python request: %v", err)
		}
		w.Header().Set("Content-Type", "application/json")
		_, _ = w.Write([]byte(`{"text":"Hello!"}`))
	})
	e, sessions := testServer(t, pythonHandler)
	cookie := issueSessionCookie(t, e)
	if !sessions.UpdateSystemPrompt(cookie.Value, "Be helpful") {
		t.Fatal("failed to set system prompt")
	}
	if !sessions.Update(cookie.Value, &model.Session{
		SystemPrompt: "Be helpful",
		History: []model.Message{
			{Role: "user", Content: "Earlier"},
			{Role: "assistant", Content: "Earlier answer"},
		},
	}) {
		t.Fatal("failed to set history")
	}

	response := requestWithCookie(
		e,
		http.MethodPost,
		"/api/chat",
		`{"message":"Hi"}`,
		cookie,
	)
	if response.Code != http.StatusOK || response.Body.String() != "{\"response\":\"Hello!\"}\n" {
		t.Fatalf("chat response = %d %s", response.Code, response.Body.String())
	}
	if gotPayload.SystemPrompt != "Be helpful" || gotPayload.UserInput != "Hi" ||
		len(gotPayload.History) != 2 || gotPayload.History[0].Content != "Earlier" {
		t.Fatalf("Python payload = %#v", gotPayload)
	}
	session, ok := sessions.Get(cookie.Value)
	if !ok || len(session.History) != 4 ||
		session.History[2] != (model.Message{Role: "user", Content: "Hi"}) ||
		session.History[3] != (model.Message{Role: "assistant", Content: "Hello!"}) {
		t.Fatalf("session after chat = %#v, exists = %v", session, ok)
	}
}

func TestChatRejectsEmptyMessage(t *testing.T) {
	e, _ := testServer(t, http.NotFoundHandler())
	cookie := issueSessionCookie(t, e)

	response := requestWithCookie(e, http.MethodPost, "/api/chat", `{"message":"  "}`, cookie)

	if response.Code != http.StatusBadRequest {
		t.Fatalf("status = %d, want %d", response.Code, http.StatusBadRequest)
	}
}

func TestSessionAPIsRequireIssuedCookie(t *testing.T) {
	e, _ := testServer(t, http.NotFoundHandler())
	tests := []struct {
		method string
		path   string
		body   string
	}{
		{http.MethodPost, "/api/chat", `{"message":"Hi"}`},
		{http.MethodGet, "/api/history", ""},
		{http.MethodPost, "/api/reset", ""},
		{http.MethodPut, "/api/system-prompt", `{"system_prompt":"x"}`},
		{http.MethodGet, "/api/models/current", ""},
	}

	for _, test := range tests {
		t.Run(test.method+" "+test.path, func(t *testing.T) {
			for _, cookie := range []*http.Cookie{
				nil,
				{Name: sessionCookieName, Value: "unknown"},
			} {
				response := requestWithCookie(e, test.method, test.path, test.body, cookie)
				if response.Code != http.StatusUnauthorized {
					t.Fatalf("status = %d, want %d", response.Code, http.StatusUnauthorized)
				}
			}
		})
	}

	response := requestWithCookie(
		e,
		http.MethodGet,
		"/api/history?session_id=known",
		"",
		nil,
	)
	if response.Code != http.StatusUnauthorized {
		t.Fatalf("query session status = %d, want %d", response.Code, http.StatusUnauthorized)
	}
}

func TestHistoryResetKeepsSystemPrompt(t *testing.T) {
	e, sessions := testServer(t, http.NotFoundHandler())
	cookie := issueSessionCookie(t, e)
	if !sessions.Update(cookie.Value, &model.Session{
		SystemPrompt: "Keep me",
		History:      []model.Message{{Role: "user", Content: "Old"}},
	}) {
		t.Fatal("failed to set up session")
	}

	response := requestWithCookie(e, http.MethodPost, "/api/reset", "", cookie)
	if response.Code != http.StatusOK {
		t.Fatalf("reset status = %d, want %d", response.Code, http.StatusOK)
	}
	response = requestWithCookie(e, http.MethodGet, "/api/history", "", cookie)
	if response.Code != http.StatusOK || response.Body.String() != "{\"history\":[]}\n" {
		t.Fatalf("history response = %d %s", response.Code, response.Body.String())
	}
	session, ok := sessions.Get(cookie.Value)
	if !ok || session.SystemPrompt != "Keep me" || len(session.History) != 0 {
		t.Fatalf("session after reset = %#v, exists = %v", session, ok)
	}
}

func TestSystemPromptUpdatesOnlyCookieSession(t *testing.T) {
	e, sessions := testServer(t, http.NotFoundHandler())
	first := issueSessionCookie(t, e)
	second := issueSessionCookie(t, e)

	response := requestWithCookie(
		e,
		http.MethodPut,
		"/api/system-prompt",
		`{"system_prompt":"First prompt"}`,
		first,
	)
	if response.Code != http.StatusOK {
		t.Fatalf("update status = %d, want %d", response.Code, http.StatusOK)
	}
	firstSession, _ := sessions.Get(first.Value)
	secondSession, _ := sessions.Get(second.Value)
	if firstSession.SystemPrompt != "First prompt" || secondSession.SystemPrompt != "" {
		t.Fatalf("prompts = (%q, %q)", firstSession.SystemPrompt, secondSession.SystemPrompt)
	}
}

func TestCurrentModelUsesPythonAPI(t *testing.T) {
	e, _ := testServer(t, http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.Method != http.MethodGet || r.URL.Path != "/models/current" {
			t.Errorf("Python request = %s %s, want GET /models/current", r.Method, r.URL.Path)
		}
		_, _ = w.Write([]byte(`{"model_id":"gemma","name":"Gemma","status":"ready"}`))
	}))
	cookie := issueSessionCookie(t, e)

	response := requestWithCookie(e, http.MethodGet, "/api/models/current", "", cookie)

	if response.Code != http.StatusOK ||
		response.Body.String() != "{\"model_id\":\"gemma\",\"name\":\"Gemma\",\"status\":\"ready\"}\n" {
		t.Fatalf("model response = %d %s", response.Code, response.Body.String())
	}
}

func TestChatMapsPythonFailureAndKeepsHistoryUnchanged(t *testing.T) {
	e, sessions := testServer(t, http.HandlerFunc(func(w http.ResponseWriter, _ *http.Request) {
		http.Error(w, `{"detail":"inference failed"}`, http.StatusInternalServerError)
	}))
	cookie := issueSessionCookie(t, e)
	initial := []model.Message{{Role: "user", Content: "Previous"}}
	if !sessions.Update(cookie.Value, &model.Session{History: initial}) {
		t.Fatal("failed to set up history")
	}

	response := requestWithCookie(e, http.MethodPost, "/api/chat", `{"message":"Hi"}`, cookie)

	if response.Code != http.StatusBadGateway {
		t.Fatalf("status = %d, want %d", response.Code, http.StatusBadGateway)
	}
	session, ok := sessions.Get(cookie.Value)
	if !ok || len(session.History) != 1 || session.History[0] != initial[0] {
		t.Fatalf("history after failed inference = %#v, exists = %v", session, ok)
	}
}

func TestDifferentSessionsKeepHistorySeparate(t *testing.T) {
	payloads := make(chan struct {
		SystemPrompt string          `json:"system_prompt"`
		History      []model.Message `json:"history"`
		UserInput    string          `json:"user_input"`
	}, 2)
	pythonHandler := http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		var payload struct {
			SystemPrompt string          `json:"system_prompt"`
			History      []model.Message `json:"history"`
			UserInput    string          `json:"user_input"`
		}
		if err := json.NewDecoder(r.Body).Decode(&payload); err != nil {
			t.Errorf("decode Python request: %v", err)
		}
		payloads <- payload
		_, _ = w.Write([]byte(`{"text":"reply"}`))
	})
	e, sessions := testServer(t, pythonHandler)
	first := issueSessionCookie(t, e)
	second := issueSessionCookie(t, e)
	if !sessions.Update(first.Value, &model.Session{
		SystemPrompt: "First prompt",
		History: []model.Message{
			{Role: "user", Content: "First history"},
			{Role: "assistant", Content: "First answer"},
		},
	}) {
		t.Fatal("failed to set up first session")
	}
	if !sessions.Update(second.Value, &model.Session{
		SystemPrompt: "Second prompt",
		History: []model.Message{
			{Role: "user", Content: "Second history"},
			{Role: "assistant", Content: "Second answer"},
		},
	}) {
		t.Fatal("failed to set up second session")
	}

	for _, test := range []struct {
		cookie  *http.Cookie
		message string
	}{
		{first, "First input"},
		{second, "Second input"},
	} {
		response := requestWithCookie(
			e,
			http.MethodPost,
			"/api/chat",
			`{"message":"`+test.message+`"}`,
			test.cookie,
		)
		if response.Code != http.StatusOK {
			t.Fatalf("chat status = %d, want %d", response.Code, http.StatusOK)
		}
	}

	firstPayload := <-payloads
	secondPayload := <-payloads
	if firstPayload.SystemPrompt != "First prompt" ||
		firstPayload.History[0].Content != "First history" ||
		firstPayload.UserInput != "First input" {
		t.Fatalf("first Python payload = %#v", firstPayload)
	}
	if secondPayload.SystemPrompt != "Second prompt" ||
		secondPayload.History[0].Content != "Second history" ||
		secondPayload.UserInput != "Second input" {
		t.Fatalf("second Python payload = %#v", secondPayload)
	}
	firstSession, _ := sessions.Get(first.Value)
	secondSession, _ := sessions.Get(second.Value)
	if firstSession.History[2].Content != "First input" ||
		secondSession.History[2].Content != "Second input" {
		t.Fatalf("session histories mixed: first=%#v second=%#v",
			firstSession.History, secondSession.History)
	}
}

func TestConcurrentChatsForOneSessionAreSerialized(t *testing.T) {
	started := make(chan struct{})
	release := make(chan struct{})
	var active atomic.Int32
	var maxActive atomic.Int32
	var requests atomic.Int32
	pythonHandler := http.HandlerFunc(func(w http.ResponseWriter, _ *http.Request) {
		current := active.Add(1)
		for {
			maximum := maxActive.Load()
			if current <= maximum || maxActive.CompareAndSwap(maximum, current) {
				break
			}
		}
		if requests.Add(1) == 1 {
			close(started)
			<-release
		}
		active.Add(-1)
		_, _ = w.Write([]byte(`{"text":"ok"}`))
	})
	e, _ := testServer(t, pythonHandler)
	cookie := issueSessionCookie(t, e)
	firstDone := make(chan int, 1)
	secondDone := make(chan int, 1)

	go func() {
		firstDone <- requestWithCookie(
			e, http.MethodPost, "/api/chat", `{"message":"First"}`, cookie,
		).Code
	}()
	select {
	case <-started:
	case <-time.After(time.Second):
		t.Fatal("first inference did not start")
	}
	go func() {
		secondDone <- requestWithCookie(
			e, http.MethodPost, "/api/chat", `{"message":"Second"}`, cookie,
		).Code
	}()
	time.Sleep(25 * time.Millisecond)
	if got := requests.Load(); got != 1 {
		t.Fatalf("inferences started concurrently: %d", got)
	}
	close(release)
	if <-firstDone != http.StatusOK || <-secondDone != http.StatusOK {
		t.Fatal("one of the chat requests failed")
	}
	if got := maxActive.Load(); got != 1 {
		t.Fatalf("maximum concurrent inference count = %d, want 1", got)
	}
}

func TestInferenceErrorStatusMapping(t *testing.T) {
	if got := inferenceHTTPStatus(service.ErrInferenceTimeout); got != http.StatusGatewayTimeout {
		t.Fatalf("timeout status = %d, want %d", got, http.StatusGatewayTimeout)
	}
	if got := inferenceHTTPStatus(service.ErrInferenceConnection); got != http.StatusBadGateway {
		t.Fatalf("connection status = %d, want %d", got, http.StatusBadGateway)
	}
	if got := inferenceHTTPStatus(&service.InferenceHTTPError{
		StatusCode: http.StatusServiceUnavailable,
		Detail:     "not ready",
	}); got != http.StatusServiceUnavailable {
		t.Fatalf("upstream 503 status = %d, want %d", got, http.StatusServiceUnavailable)
	}
}
