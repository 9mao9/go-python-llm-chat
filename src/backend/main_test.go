package main

import (
	"crypto/tls"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"
)

func TestHealthEndpoint(t *testing.T) {
	e := newServer()
	req := httptest.NewRequest(http.MethodGet, "/health", nil)
	rec := httptest.NewRecorder()

	e.ServeHTTP(rec, req)
	if rec.Code != http.StatusOK {
		t.Fatalf("status = %d, want %d", rec.Code, http.StatusOK)
	}

	if got, want := rec.Body.String(), `{"status":"ok"}`+"\n"; got != want {
		t.Fatalf("body = %q, want %q", got, want)
	}
}

func TestFrontendFilesAreServedByBackend(t *testing.T) {
	e := newServer()
	for _, path := range []string{"/", "/style.css", "/app.js"} {
		recorder := httptest.NewRecorder()
		e.ServeHTTP(recorder, httptest.NewRequest(http.MethodGet, path, nil))
		if recorder.Code != http.StatusOK {
			t.Fatalf("GET %s status = %d, want %d", path, recorder.Code, http.StatusOK)
		}
		if recorder.Body.Len() == 0 {
			t.Fatalf("GET %s returned an empty body", path)
		}
	}
}

func TestInferenceAPIURLUsesEnvironmentOrDefault(t *testing.T) {
	t.Setenv("INFERENCE_API_URL", "")
	if got, want := inferenceAPIURL(), "http://127.0.0.1:8001"; got != want {
		t.Fatalf("default inference URL = %q, want %q", got, want)
	}

	t.Setenv("INFERENCE_API_URL", "http://localhost:9001/")
	if got, want := inferenceAPIURL(), "http://localhost:9001"; got != want {
		t.Fatalf("configured inference URL = %q, want %q", got, want)
	}
}

func TestSessionBootstrapIssuesHttpOnlyCookie(t *testing.T) {
	e := newServer()
	req := httptest.NewRequest(http.MethodPost, "/api/session", nil)
	rec := httptest.NewRecorder()

	e.ServeHTTP(rec, req)

	if rec.Code != http.StatusCreated {
		t.Fatalf("status = %d, want %d", rec.Code, http.StatusCreated)
	}
	cookies := rec.Result().Cookies()
	if len(cookies) != 1 {
		t.Fatalf("cookie count = %d, want 1", len(cookies))
	}
	cookie := cookies[0]
	if cookie.Name != sessionCookieName || len(cookie.Value) != 36 {
		t.Fatalf("unexpected session cookie: %#v", cookie)
	}
	if !cookie.HttpOnly || cookie.Path != "/" || cookie.SameSite != http.SameSiteLaxMode {
		t.Fatalf("cookie attributes are not secure: %#v", cookie)
	}
	if cookie.Secure {
		t.Fatal("Secure must be false for the HTTP test request")
	}
	if strings.Contains(rec.Body.String(), cookie.Value) {
		t.Fatal("session ID must not be included in the response body")
	}
}

func TestSessionBootstrapSetsSecureCookieOverTLS(t *testing.T) {
	e := newServer()
	req := httptest.NewRequest(http.MethodPost, "/api/session", nil)
	req.TLS = &tls.ConnectionState{}
	rec := httptest.NewRecorder()

	e.ServeHTTP(rec, req)

	cookies := rec.Result().Cookies()
	if len(cookies) != 1 || !cookies[0].Secure {
		t.Fatalf("expected Secure session cookie over TLS, got %#v", cookies)
	}
}

func TestSessionBootstrapReusesIssuedSession(t *testing.T) {
	e := newServer()
	first := httptest.NewRecorder()
	e.ServeHTTP(first, httptest.NewRequest(http.MethodPost, "/api/session", nil))
	cookies := first.Result().Cookies()
	if len(cookies) != 1 {
		t.Fatalf("first response cookie count = %d, want 1", len(cookies))
	}

	req := httptest.NewRequest(http.MethodPost, "/api/session", nil)
	req.AddCookie(cookies[0])
	rec := httptest.NewRecorder()
	e.ServeHTTP(rec, req)

	if rec.Code != http.StatusOK {
		t.Fatalf("status = %d, want %d", rec.Code, http.StatusOK)
	}
	if got := rec.Header().Values("Set-Cookie"); len(got) != 0 {
		t.Fatalf("Set-Cookie = %v, want no new cookie", got)
	}
}

func TestSessionBootstrapReissuesUnknownSession(t *testing.T) {
	e := newServer()
	req := httptest.NewRequest(http.MethodPost, "/api/session", nil)
	req.AddCookie(&http.Cookie{Name: sessionCookieName, Value: "unknown"})
	rec := httptest.NewRecorder()

	e.ServeHTTP(rec, req)

	if rec.Code != http.StatusCreated {
		t.Fatalf("status = %d, want %d", rec.Code, http.StatusCreated)
	}
	cookies := rec.Result().Cookies()
	if len(cookies) != 1 || cookies[0].Value == "unknown" {
		t.Fatalf("unknown session was not replaced: %#v", cookies)
	}
}
